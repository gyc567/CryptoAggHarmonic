"""Signal engine: turn harmonic pattern candidates into executable signals.

Thin orchestration layer over the pure domain math in ``app.domain.signals``
and the validity verifiers in ``app.domain.validation``. All market-data
access happens here; the domain layer stays pure.

Pipeline (v4):
    candidates -> freshness filter -> trap/adverse-momentum vetoes
               -> confluence score -> grade (regime-aware) -> best signal
               -> multi-window stability check (A/B only) -> Signal

The pipeline is composed from three small helpers so each stage can be
unit-tested in isolation:

    * :func:`score_candidate`  - per-candidate scoring + veto logic
    * :func:`rank_signals`    - pick the strongest signal from a list
    * :func:`apply_stability` - A/B-only multi-window re-detection guard
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Callable, List, NamedTuple, Optional, Sequence

import pandas as pd
from icontract import require

from app.config.tuning import TUNING
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

# Backwards-compat aliases — values live in TUNING.

ATR_WINDOW = TUNING.atr_window
ATR_LONG_WINDOW = TUNING.atr_long_window
RSI_WINDOW = TUNING.rsi_window
VOLUME_MA_WINDOW = TUNING.volume_ma_window
SWING_LOOKBACK = TUNING.swing_lookback

# Resample map: current interval -> higher timeframe rule for trend filter.
HTF_RULE = dict(TUNING.htf_rule)

MIN_CANDLES = TUNING.min_candles

A_GRADE_MIN = TUNING.a_grade_min
A_GRADE_MIN_HIGH_QUANT = TUNING.a_grade_min_high_quant
HIGH_QUANT_POSITION_MULT = TUNING.high_quant_position_mult

# Pattern names considered identical across sub-windows (pyharmonics suffixes
# like "gartley-382-1" are normalized by prefix matching).
_STABILITY_WINDOW = TUNING.stability_window


# Q4: Pattern-reliability weighting. Empirically observed win rates from the
# BTC/ETH/BNB 4H backtest documented in docs/. Gartley wins most often so it
# gets a positive bump; Crab/DeepCrab lose so they get a penalty. The lookup
# is keyed on the lowercase pattern family name (the prefix before any
# pyharmonics numeric suffix). Unknown patterns get 0.
PATTERN_BASE_SCORE: dict[str, int] = dict(TUNING.pattern_base_score)


def _pattern_base_score(pattern_name: str) -> int:
    """Look up the Q4 reliability bump for a pattern name.

    Matches on the family prefix so ``"gartley-382-1"`` still resolves to
    ``+5``. Returns ``0`` for unknown families.
    """
    if not pattern_name:
        return 0
    name = pattern_name.lower()
    for family, bump in PATTERN_BASE_SCORE.items():
        if name.startswith(family):
            return bump
    return 0


def extract_candidates(
    detection_result: dict,
    close_times: Optional[Sequence] = None,
) -> list[Candidate]:
    """Extract serializable candidates from a pyharmonics detection result.

    Reads the raw assessment dicts (formed + forming patterns) stored by the
    adapter under ``raw_assessment``. Tolerates missing/exotic pattern objects
    by skipping anything without numeric points and PRZ bounds.

    ``close_times``: optional sequence aligned with the candle dataframe rows.
    When provided, pattern ``x`` indices are mapped to the matching close_time
    so the staleness filter (``rejection_reason``) compares like-for-like units.
    Falls back to ``int(t)`` when not provided (used by unit tests that pass
    hand-built candidates with synthetic times).
    """
    @require(lambda detection_result: isinstance(detection_result, dict),
             "detection_result must be a dict")
    def _check_inputs(**_kwargs) -> None:
        return None

    _check_inputs(detection_result=detection_result)

    assessment = detection_result.get("raw_assessment") or {}
    candidates: list[Candidate] = []
    for formed, key in ((True, "patterns"), (False, "forming")):
        group = assessment.get(key) or {}
        for family, patterns in group.items():
            for pattern in patterns or []:
                candidate = _to_candidate(pattern, family, formed, close_times)
                if candidate is not None:
                    candidates.append(candidate)
    return candidates


def _to_candidate(
    pattern: Any,
    family: str,
    formed: bool,
    close_times: Optional[Sequence] = None,
) -> Optional[Candidate]:
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
    times, indices = _extract_times(pattern, close_times)
    return Candidate(
        family=family,
        name=name,
        bullish=bullish,
        formed=formed,
        points=points,
        completion_min=c_min,
        completion_max=c_max,
        times=times,
        indices=indices,
    )


def _extract_times(
    pattern: Any, close_times: Optional[Sequence]
) -> tuple[tuple, tuple]:
    """Map pattern.x to (epoch_seconds, bar_indices) tuples.

    ``pattern.x`` is ``df.index[x]`` where ``x`` is the peak-index list returned
    by pyharmonics (see ``pyharmonics.technicals.OHLCTechnicals.get_index_x``).
    When the source df carries a ``RangeIndex`` the values are integer bar
    positions; with a ``DatetimeIndex`` they are ``pd.Timestamp`` instances.
    The downstream staleness filter compares ``candidate.times[-1]`` against
    the df ``close_time`` column (epoch seconds), while the discipline filter
    needs ``candidate.indices[-2]`` as a bar position. We return both.

    Returns ``(times, indices)`` where ``times`` is a tuple of epoch seconds
    aligned with the candle close_time column (when provided), and ``indices``
    is a tuple of integer bar positions suitable for ``df.iloc[idx]`` slicing.
    """
    raw_x = getattr(pattern, "x", None) or ()
    try:
        raw_list = list(raw_x)
    except TypeError:
        return (), ()
    if not raw_list:
        return (), ()

    # Always collect integer bar indices, even when close_times is None.
    indices_list: List[int] = []
    for t in raw_list:
        try:
            indices_list.append(int(t))
        except (TypeError, ValueError):
            continue
    indices_tuple = tuple(indices_list)

    if close_times is None:
        # Legacy: times are an int cast of pattern.x — same value as indices
        # when the df has a RangeIndex, or nanosecond epoch when DatetimeIndex.
        try:
            return tuple(int(t) for t in raw_list), indices_tuple
        except (TypeError, ValueError):
            return (), indices_tuple

    mapped: List[int] = []
    for t in raw_list:
        # Prefer the integer-position path: pattern.x holds df.index[x]
        # which is the integer position when the df has a RangeIndex.
        pos: Optional[int] = None
        try:
            pos = int(t)
        except (TypeError, ValueError):
            pos = None
        if pos is not None and 0 <= pos < len(close_times):
            try:
                mapped.append(int(close_times[pos]))
                continue
            except (TypeError, ValueError):
                pass
        # Fallback: only when t is timestamp-like, not a bare integer.
        if pos is not None:
            continue
        try:
            ts = pd.Timestamp(t)
            if pd.notna(ts):
                mapped.append(int(ts.timestamp()))
        except (TypeError, ValueError):
            continue
    return tuple(mapped), indices_tuple


def compute_atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> float:
    """Robust ATR: min of the short-window and long-window means.

    A long lookback desensitizes the value to a recent crash/candle burst,
    which would otherwise inflate every ATR-derived buffer.
    """
    @require(lambda df: len(df) >= 2, "df must have at least 2 bars")
    @require(lambda window: window >= 1, "window must be >= 1")
    @require(lambda df: {"high", "low", "close"}.issubset(df.columns),
             "df must contain high/low/close columns")
    def _check_inputs(**_kwargs) -> None:
        return None

    _check_inputs(df=df, window=window)

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

    # RSI: divergence bonus + extreme-zone positioning + reverse-divergence penalty.
    # Q5: an RSI divergence that points the OPPOSITE direction of the candidate
    # is a strong warning (price-vs-momentum disagreement). Penalise -5 so a
    # candidate with opposite divergence can never reach A grade.
    div_families = divergences or {}
    rsi_divs = div_families.get("rsi", [])
    rsi_score = 0
    if any(bool(d.get("bullish")) == candidate.bullish for d in rsi_divs):
        rsi_score += 8
    elif any(d.get("bullish") is not None for d in rsi_divs):
        # At least one real RSI divergence was found, and it disagrees with
        # the pattern direction. Strong warning — a reversal harmonic pattern
        # riding against the divergence is fighting the most recent momentum.
        rsi_score -= 5
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


class _ScoreContext(NamedTuple):
    """Pre-computed, per-call data needed by :func:`score_candidate`.

    Bundling these keeps the per-candidate function pure: callers that need
    to score the same candidate under different ``stop_level`` values
    (e.g. A/B-grade stress tests) reuse the same context instead of
    recomputing ATR / RSI / regime from scratch.
    """

    df: pd.DataFrame
    atr: float
    rsi: float
    trend: str
    sharpe: float
    regime: str
    a_min: float
    pa_scale: float
    position_mult: float
    price: float
    last: Any  # last row of df
    divergences: dict
    volume_authenticity: int = 50  # 0-100; per-candidate gate reads this


def _prepare_score_context(
    df: pd.DataFrame,
    interval: str,
    divergences: Optional[dict],
) -> Optional[_ScoreContext]:
    """Compute shared data-level metrics. Returns None if a hard gate fires.

    Volume authenticity is computed here but the GATE is per-candidate
    (Q6 amendment): formed patterns use the strict ``AUTHENTICITY_VETO``
    threshold, forming patterns use the looser ``AUTHENTICITY_HALVE``
    because forming patterns haven't yet had their confirming volume spike.
    """
    auth = volume_authenticity(df)
    pa_scale = 0.5 if auth < AUTHENTICITY_HALVE else 1.0

    atr = compute_atr(df)
    if atr <= 0:
        return None
    rsi = compute_rsi(df["close"])
    trend = htf_trend(df, interval)
    sharpe = per_bar_sharpe(df["close"])
    regime_score, regime = quant_regime(df)
    a_min = A_GRADE_MIN_HIGH_QUANT if regime == "high_quant" else A_GRADE_MIN
    regime_mult = HIGH_QUANT_POSITION_MULT if regime == "high_quant" else 1.0
    price = float(df["close"].iloc[-1])
    position_mult = round(volatility_multiplier(atr, price) * regime_mult, 4)

    return _ScoreContext(
        df=df,
        atr=atr,
        rsi=rsi,
        trend=trend,
        sharpe=sharpe,
        regime=regime,
        a_min=a_min,
        pa_scale=pa_scale,
        position_mult=position_mult,
        price=price,
        last=df.iloc[-1],
        divergences=divergences or {},
        # New field: store the raw authenticity score so per-candidate
        # gates (Q6 formed vs forming) can consult it.
        volume_authenticity=auth,
    )


def score_candidate(
    ctx: _ScoreContext,
    candidate: Candidate,
    stop_level: str = "standard",
) -> Optional[Signal]:
    """Score a single surviving candidate.

    Runs every per-candidate gate in order: volume authenticity (formed vs
    forming threshold), trap veto, adverse-momentum veto, PRZ state
    inference, stop/targets, direction invariant, RR, confluence score,
    grade. Returns ``None`` for any rejection and the fully populated
    :class:`Signal` for survivors so callers can run their own ranking on
    the survivors.

    Q4 + Q6: the raw confluence score is bumped by ``PATTERN_BASE_SCORE`` for
    the pattern family, and the grade gate additionally receives
    ``width_pct`` so a wide PRZ can never reach A even with a perfect score.
    """
    df = ctx.df
    atr = ctx.atr
    last = ctx.last

    # Q6: per-candidate volume gate. formed=True → strict (AUTHENTICITY_VETO);
    # formed=False → lenient (AUTHENTICITY_HALVE) because forming patterns
    # legitimately lack the confirming volume spike.
    threshold = AUTHENTICITY_VETO if candidate.formed else AUTHENTICITY_HALVE
    if ctx.volume_authenticity < threshold:
        logger.debug(
            "Volume authenticity %d < %d for %s pattern, vetoing",
            ctx.volume_authenticity, threshold,
            "formed" if candidate.formed else "forming",
        )
        return None

    stop, stop_basis, invalidation_point = compute_stop(candidate, atr, stop_level)

    # Quant-trap veto (false breakouts, stop hunts, PRZ failure...).
    trap_score, trap_veto, _reasons = quant_trap_risk(
        df, candidate.prz_low, candidate.prz_high, candidate.bullish,
    )
    if trap_veto:
        return None

    # Falling-knife / blow-off veto.
    if adverse_momentum_veto(candidate.direction, ctx.sharpe):
        return None

    swept = is_swept(
        float(last["low"]), float(last["high"]), ctx.price,
        candidate.prz_low, candidate.prz_high,
    )
    status = prz_state(ctx.price, candidate.prz_low, candidate.prz_high, swept)
    if status in ("in_prz", "swept") and _is_reversal_candle(last, candidate.bullish):
        status = "confirmed"

    entry = ctx.price if status != "approaching" else (
        candidate.prz_high if candidate.bullish else candidate.prz_low
    )
    targets = compute_targets(candidate, entry)

    # Direction geometry invariant (defense in depth).
    if not direction_invariant_ok(
        candidate.direction, entry, stop,
        [t.price for t in targets],
    ):
        return None

    rr1 = net_rr(entry, stop, targets[0].price)
    rr2 = net_rr(entry, stop, targets[1].price)

    score, factors = confluence_score(
        df, candidate, atr, ctx.rsi, ctx.trend,
        ctx.divergences, ctx.pa_scale,
    )
    # Q4 pattern-reliability bump (Gartley +5, Crab -3, ...).
    score += _pattern_base_score(candidate.name)

    # Q6 PRZ width gate input. Computed here so grade() can apply its 4% cap
    # without each caller having to remember to thread the value through.
    prz_mid = (candidate.prz_low + candidate.prz_high) / 2
    width_pct = (
        (candidate.prz_high - candidate.prz_low) / prz_mid
        if prz_mid > 0 else 0.0
    )

    bullish_trend = ctx.trend == "bullish"
    bearish_trend = ctx.trend == "bearish"
    htf_aligned = (candidate.bullish and bullish_trend) or (
        not candidate.bullish and bearish_trend
    )
    htf_counter = (candidate.bullish and bearish_trend) or (
        not candidate.bullish and bullish_trend
    )
    g = grade(
        score, rr1, rr2, htf_aligned, htf_counter,
        a_min=ctx.a_min, width_pct=width_pct,
    )
    if g is None:
        return None

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
        htf_trend=ctx.trend,
        sharpe=_clamp_sharpe(ctx.sharpe),
        regime=ctx.regime,
        position_multiplier=ctx.position_mult,
        trap_score=trap_score,
        # Q6: width_pct kept on the signal so consumers can re-grade without
        # recomputing; Q7: tradable=False iff grade="C(参考)".
        tradable=(g != "C(参考)"),
        width_pct=round(width_pct, 4),
    )
    return replace(signal, reasoning=reasoning_from_signal(signal))


def rank_signals(signals: List[Signal]) -> Optional[Signal]:
    """Return the strongest signal by ``(grade, score, formed)``.

    Ties on grade break by raw confluence score; final tie-break is the
    ``formed`` flag (True > False) so we prefer finished patterns over
    in-flight ones when everything else is equal.
    """
    best: Optional[Signal] = None
    best_rank = (-1, -1.0, False)
    for signal in signals:
        g_rank = {"A": 3, "B": 2, "C": 1}.get(signal.grade, 0)
        rank = (g_rank, float(signal.confluence_score), bool(signal.formed))
        if rank > best_rank:
            best, best_rank = signal, rank
    return best


def apply_stability(
    df: pd.DataFrame,
    best: Optional[Signal],
    stability_detector: Optional[Callable[[pd.DataFrame], Optional[str]]],
) -> Optional[Signal]:
    """Re-detect the pattern on two shifted sub-windows; veto if it disappears.

    This is the only stage that costs an extra pattern-detection pass;
    we only run it for A/B-grade signals (the only grades worth the
    latency). Detector failures are treated as unverifiable -> pass.
    """
    if (
        best is None
        or best.grade not in ("A", "B")
        or stability_detector is None
    ):
        return best

    try:
        sub1 = stability_detector(df.iloc[:-_STABILITY_WINDOW])
        sub2 = stability_detector(df.iloc[_STABILITY_WINDOW:])
    except Exception:
        # Detector failures degrade to "unknown sub-windows"; the
        # downstream ``stability_verdict`` treats that as suspect so
        # A/B-grade signals still get vetoed on a flaky re-detector.
        logger.exception("Stability detector failed, treating as unverifiable")
        sub1 = sub2 = None

    s_score, suspect = stability_verdict(best.pattern_name, sub1, sub2)
    if suspect:
        logger.warning(
            "Pattern %s only exists in the full window, vetoing",
            best.pattern_name,
        )
        return None
    return replace(best, stability_score=s_score)


def build_signal(
    df: pd.DataFrame,
    interval: str,
    candidates: list[Candidate],
    divergences: Optional[dict] = None,
    stability_detector: Optional[Callable[[pd.DataFrame], Optional[str]]] = None,
    stop_level: str = "standard",
) -> Optional[Signal]:
    """Build the best executable signal from candidates, or None.

    Public façade kept for backwards compatibility. Implementation now
    delegates to :func:`score_candidate`, :func:`rank_signals` and
    :func:`apply_stability` so each stage is individually testable.

    ``stability_detector``: optional callable re-running pattern detection on
    a dataframe slice and returning the best pattern name (or None). Used for
    the multi-window stability check on A/B-grade signals.
    """
    @require(lambda interval: isinstance(interval, str) and len(interval) > 0,
             "interval must be a non-empty string")
    @require(lambda stop_level: stop_level in ("standard", "tight", "wide"),
             "stop_level must be one of standard/tight/wide")
    def _check_inputs(**_kwargs) -> None:
        return None

    _check_inputs(interval=interval, stop_level=stop_level)

    if df is None or len(df) < MIN_CANDLES or not candidates:
        return None

    ctx = _prepare_score_context(df, interval, divergences)
    if ctx is None:
        return None

    # --- Candidate freshness filter ---------------------------------------
    close_times = df["close_time"] if "close_time" in df.columns else None
    valid, rejected = filter_candidates(
        candidates, ctx.price, ctx.atr, close_times,
    )
    if rejected:
        logger.debug(
            "Filtered %d stale/invalid candidates: %s",
            len(rejected), [r.reason for r in rejected],
        )

    # --- Score surviving candidates ----------------------------------------
    scored: list[Signal] = []
    for candidate in valid:
        signal = score_candidate(ctx, candidate, stop_level=stop_level)
        if signal is not None:
            scored.append(signal)

    best = rank_signals(scored)
    return apply_stability(df, best, stability_detector)
