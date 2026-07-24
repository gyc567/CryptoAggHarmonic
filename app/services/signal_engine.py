"""Signal engine: turn harmonic pattern candidates into executable signals.

Thin orchestration layer over the pure domain math in ``app.domain.signals``
and the validity verifiers in ``app.domain.validation``. All market-data
access happens here; the domain layer stays pure.

Pipeline (v4):
    candidates -> freshness filter -> trap/adverse-momentum vetoes
               -> confluence score -> grade (regime-aware) -> best signal
               -> multi-window stability check (A/B only) -> Signal
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Callable, Optional

import pandas as pd

from app.domain.signals import (
    ATR_PRZ_SWEEP,
    Candidate,
    Signal,
    compute_stop,
    compute_targets,
    grade,
    is_swept,
    net_rr,
    prz_state,
    reasoning_from_signal,
)
from app.domain.validation import (
    AUTHENTICITY_HALVE,
    AUTHENTICITY_VETO,
    adverse_momentum_veto,
    direction_invariant_ok,
    filter_candidates,
    per_bar_sharpe,
    quant_regime,
    quant_trap_risk,
    stability_verdict,
    volatility_multiplier,
    volume_authenticity,
)

logger = logging.getLogger(__name__)

ATR_WINDOW = 14
ATR_LONG_WINDOW = 100
RSI_WINDOW = 14
VOLUME_MA_WINDOW = 20
SWING_LOOKBACK = 60

# Resample map: current interval -> higher timeframe rule for trend filter.
HTF_RULE = {
    "15m": "1h",
    "1h": "4h",
    "4h": "1D",
    "1d": "1W",
    "1w": "1ME",
}

MIN_CANDLES = 60

A_GRADE_MIN = 75
A_GRADE_MIN_HIGH_QUANT = 85
HIGH_QUANT_POSITION_MULT = 0.6

# Pattern names considered identical across sub-windows (pyharmonics suffixes
# like "gartley-382-1" are normalized by prefix matching).
_STABILITY_WINDOW = 5


def extract_candidates(detection_result: dict) -> list[Candidate]:
    """Extract serializable candidates from a pyharmonics detection result.

    Reads the raw assessment dicts (formed + forming patterns) stored by the
    adapter under ``raw_assessment``. Tolerates missing/exotic pattern objects
    by skipping anything without numeric points and PRZ bounds.
    """
    assessment = detection_result.get("raw_assessment") or {}
    candidates: list[Candidate] = []
    for formed, key in ((True, "patterns"), (False, "forming")):
        group = assessment.get(key) or {}
        for family, patterns in group.items():
            for pattern in patterns or []:
                candidate = _to_candidate(pattern, family, formed)
                if candidate is not None:
                    candidates.append(candidate)
    return candidates


def _to_candidate(pattern: Any, family: str, formed: bool) -> Optional[Candidate]:
    try:
        points = tuple(float(p) for p in pattern.y)
        c_min = float(pattern.completion_min_price)
        c_max = float(pattern.completion_max_price)
        name = str(pattern.name)
        bullish = bool(pattern.bullish)
    except (TypeError, ValueError, AttributeError):
        return None
    if len(points) < 3 or c_min <= 0 or c_max <= 0:
        return None
    try:
        times = tuple(int(t) for t in (getattr(pattern, "x", None) or ()))
    except (TypeError, ValueError):
        times = ()
    return Candidate(
        family=family,
        name=name,
        bullish=bullish,
        formed=formed,
        points=points,
        completion_min=c_min,
        completion_max=c_max,
        times=times,
    )


def compute_atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> float:
    """Robust ATR: min of the short-window and long-window means.

    A long lookback desensitizes the value to a recent crash/candle burst,
    which would otherwise inflate every ATR-derived buffer.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_short = tr.rolling(window).mean().iloc[-1]
    if pd.isna(atr_short):
        return float(high.tail(window).max() - low.tail(window).min()) / window
    atr_long = tr.tail(ATR_LONG_WINDOW).mean()
    return float(min(atr_short, atr_long))


def compute_rsi(closes: pd.Series, window: int = RSI_WINDOW) -> float:
    """Wilder RSI of the latest close."""
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    value = rsi.iloc[-1]
    if pd.isna(value):
        return 100.0 if gain.iloc[-1] > 0 else 50.0
    return float(value)


def htf_trend(df: pd.DataFrame, interval: str) -> str:
    """Trend on the resampled higher timeframe via EMA21 vs EMA55."""
    rule = HTF_RULE.get(interval)
    if rule is None or "dts" not in df.columns:
        return "unknown"
    closes = df.set_index("dts")["close"].resample(rule).last().dropna()
    if len(closes) < 55:
        return "unknown"
    ema_fast = closes.ewm(span=21, adjust=False).mean().iloc[-1]
    ema_slow = closes.ewm(span=55, adjust=False).mean().iloc[-1]
    if ema_fast > ema_slow:
        return "bullish"
    if ema_fast < ema_slow:
        return "bearish"
    return "unknown"


def _is_reversal_candle(row: pd.Series, bullish: bool) -> bool:
    """Hammer/engulfing-style rejection candle at the PRZ."""
    body = abs(row["close"] - row["open"])
    rng = row["high"] - row["low"]
    if rng <= 0:
        return False
    if bullish:
        lower_wick = min(row["open"], row["close"]) - row["low"]
        return bool(row["close"] > row["open"] and lower_wick >= 0.5 * rng)
    upper_wick = row["high"] - max(row["open"], row["close"])
    return bool(row["close"] < row["open"] and upper_wick >= 0.5 * rng)


def confluence_score(
    df: pd.DataFrame,
    candidate: Candidate,
    atr: float,
    rsi: float,
    trend: str,
    divergences: dict,
    pa_scale: float = 1.0,
) -> tuple:
    """Weighted confluence: price action 25, HTF 25, RSI 15, structure 15,
    MACD 10, funding 10 (neutral without futures data)."""
    factors: dict[str, float] = {}
    last = df.iloc[-1]

    # Price action at the PRZ: reversal candle + volume expansion.
    pa = 0.0
    if _is_reversal_candle(last, candidate.bullish):
        pa += 15.0
        vol_ma = df["volume"].tail(VOLUME_MA_WINDOW).mean()
        if vol_ma > 0 and last["volume"] >= 1.5 * vol_ma:
            pa += 10.0
    factors["price_action"] = pa * pa_scale

    # Higher-timeframe trend alignment.
    if trend == ("bullish" if candidate.bullish else "bearish"):
        factors["htf_trend"] = 25
    elif trend == "unknown":
        factors["htf_trend"] = 10
    else:
        factors["htf_trend"] = 0

    # RSI: divergence bonus + extreme-zone positioning.
    div_families = divergences or {}
    rsi_divs = div_families.get("rsi", [])
    rsi_score = 0
    if any(bool(d.get("bullish")) == candidate.bullish for d in rsi_divs):
        rsi_score += 8
    if (candidate.bullish and rsi <= 35) or (not candidate.bullish and rsi >= 65):
        rsi_score += 7
    elif (candidate.bullish and rsi <= 45) or (not candidate.bullish and rsi >= 55):
        rsi_score += 4
    factors["rsi"] = rsi_score

    # Structure: PRZ overlaps a recent swing low/high (support/resistance).
    tail = df["low"].tail(SWING_LOOKBACK) if candidate.bullish else df["high"].tail(SWING_LOOKBACK)
    swing = tail.min() if candidate.bullish else tail.max()
    mid = (candidate.prz_low + candidate.prz_high) / 2
    factors["structure"] = 15 if abs(mid - swing) <= ATR_PRZ_SWEEP * atr else 0

    # MACD divergence.
    macd_divs = div_families.get("macd", [])
    factors["macd"] = 10 if any(bool(d.get("bullish")) == candidate.bullish for d in macd_divs) else 0

    # Funding: unknown without a futures feed -> neutral half weight.
    factors["funding"] = 5

    return sum(factors.values()), factors


def _clamp_sharpe(sharpe: float) -> float:
    return round(max(-10.0, min(10.0, sharpe)), 4)


def build_signal(
    df: pd.DataFrame,
    interval: str,
    candidates: list[Candidate],
    divergences: Optional[dict] = None,
    stability_detector: Optional[Callable[[pd.DataFrame], Optional[str]]] = None,
    stop_level: str = "standard",
) -> Optional[Signal]:
    """Build the best executable signal from candidates, or None.

    ``stability_detector``: optional callable re-running pattern detection on
    a dataframe slice and returning the best pattern name (or None). Used for
    the multi-window stability check on A/B-grade signals.
    """
    if df is None or len(df) < MIN_CANDLES or not candidates:
        return None

    # --- Data-level gates -------------------------------------------------
    auth = volume_authenticity(df)
    if auth < AUTHENTICITY_VETO:
        logger.info("Volume authenticity %d < %d, vetoing all signals", auth, AUTHENTICITY_VETO)
        return None
    pa_scale = 0.5 if auth < AUTHENTICITY_HALVE else 1.0

    atr = compute_atr(df)
    if atr <= 0:
        return None
    rsi = compute_rsi(df["close"])
    trend = htf_trend(df, interval)
    price = float(df["close"].iloc[-1])
    last = df.iloc[-1]

    sharpe = per_bar_sharpe(df["close"])
    regime_score, regime = quant_regime(df)
    a_min = A_GRADE_MIN_HIGH_QUANT if regime == "high_quant" else A_GRADE_MIN
    regime_mult = HIGH_QUANT_POSITION_MULT if regime == "high_quant" else 1.0
    position_mult = round(volatility_multiplier(atr, price) * regime_mult, 4)

    # --- Candidate freshness filter ---------------------------------------
    close_times = df["close_time"] if "close_time" in df.columns else None
    valid, rejected = filter_candidates(candidates, price, atr, close_times)
    if rejected:
        logger.debug("Filtered %d stale/invalid candidates: %s",
                     len(rejected), [r.reason for r in rejected])

    # --- Score surviving candidates ----------------------------------------
    best: Optional[Signal] = None
    best_rank: tuple = ()
    for candidate in valid:
        stop, stop_basis, invalidation_point = compute_stop(candidate, atr, stop_level)

        # Quant-trap veto (false breakouts, stop hunts, PRZ failure...).
        trap_score, trap_veto, _reasons = quant_trap_risk(
            df, candidate.prz_low, candidate.prz_high, candidate.bullish
        )
        if trap_veto:
            continue

        # Falling-knife / blow-off veto.
        if adverse_momentum_veto(candidate.direction, sharpe):
            continue

        swept = is_swept(float(last["low"]), float(last["high"]), price,
                         candidate.prz_low, candidate.prz_high)
        status = prz_state(price, candidate.prz_low, candidate.prz_high, swept)
        if status in ("in_prz", "swept") and _is_reversal_candle(last, candidate.bullish):
            status = "confirmed"

        entry = price if status != "approaching" else (
            candidate.prz_high if candidate.bullish else candidate.prz_low
        )
        targets = compute_targets(candidate, entry)

        # Direction geometry invariant (defense in depth).
        if not direction_invariant_ok(candidate.direction, entry, stop,
                                      [t.price for t in targets]):
            continue

        rr1 = net_rr(entry, stop, targets[0].price)
        rr2 = net_rr(entry, stop, targets[1].price)

        score, factors = confluence_score(df, candidate, atr, rsi, trend,
                                          divergences or {}, pa_scale)
        bullish_trend = trend == "bullish"
        bearish_trend = trend == "bearish"
        htf_aligned = (candidate.bullish and bullish_trend) or (not candidate.bullish and bearish_trend)
        htf_counter = (candidate.bullish and bearish_trend) or (not candidate.bullish and bullish_trend)
        g = grade(score, rr1, rr2, htf_aligned, htf_counter, a_min=a_min)
        if g is None:
            continue

        signal = Signal(
            status=status,
            grade=g,
            direction=candidate.direction,
            pattern_name=candidate.name,
            family=candidate.family,
            formed=candidate.formed,
            entry_zone=(candidate.prz_low, candidate.prz_high),
            entry_reference=round(entry, 8),
            stop_loss=stop,
            stop_basis=stop_basis,
            stop_level=stop_level,
            invalidation_point=invalidation_point,
            targets=targets,
            net_rr_tp1=rr1 if rr1 is not None else 0.0,
            net_rr_tp2=rr2 if rr2 is not None else 0.0,
            confluence_score=int(round(score)),
            confluence=factors,
            htf_trend=trend,
            sharpe=_clamp_sharpe(sharpe),
            regime=regime,
            position_multiplier=position_mult,
            trap_score=trap_score,
        )
        signal = replace(signal, reasoning=reasoning_from_signal(signal))

        rank = ({"A": 3, "B": 2, "C": 1}[g], score, candidate.formed)
        if best is None or rank > best_rank:
            best, best_rank = signal, rank

    # --- Multi-window stability (A/B-grade only, saves the 2x re-detect) ---
    if best is not None and best.grade in ("A", "B") and stability_detector is not None:
        try:
            sub1 = stability_detector(df.iloc[:-_STABILITY_WINDOW])
            sub2 = stability_detector(df.iloc[_STABILITY_WINDOW:])
        except Exception:
            logger.exception("Stability detector failed, treating as unverifiable")
            sub1 = sub2 = None
        s_score, suspect = stability_verdict(best.pattern_name, sub1, sub2)
        if suspect:
            logger.warning("Pattern %s only exists in the full window, vetoing",
                           best.pattern_name)
            return None
        best = replace(best, stability_score=s_score)

    return best
