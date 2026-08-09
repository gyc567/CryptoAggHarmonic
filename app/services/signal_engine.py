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
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, NamedTuple, Optional

import pandas as pd
from icontract import require

from app.config.tuning import TUNING, get_min_candles, get_tuning
from app.domain.signals import (
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
    adverse_momentum_veto,
    direction_invariant_ok,
    filter_candidates,
    per_bar_sharpe,
    quant_regime,
    quant_trap_risk,
    stability_verdict,
    trap_stop_multiplier,
    volatility_multiplier,
    volume_authenticity,
)

logger = logging.getLogger(__name__)


ATR_WINDOW = TUNING.atr_window
ATR_LONG_WINDOW = TUNING.atr_long_window
RSI_WINDOW = TUNING.rsi_window
VOLUME_MA_WINDOW = TUNING.volume_ma_window
SWING_LOOKBACK = TUNING.swing_lookback
HTF_RULE = dict(TUNING.htf_rule)
MIN_CANDLES = TUNING.min_candles
A_GRADE_MIN = TUNING.a_grade_min
A_GRADE_MIN_HIGH_QUANT = TUNING.a_grade_min_high_quant
HIGH_QUANT_POSITION_MULT = TUNING.high_quant_position_mult
_STABILITY_WINDOW = TUNING.stability_window
PATTERN_BASE_SCORE: dict[str, int] = dict(TUNING.pattern_base_score)


def _pattern_base_score(pattern_name: str) -> int:
    """Look up the Q4 reliability bump for a pattern name.

    Matches on the family prefix so ``"gartley-382-1"`` still resolves to
    ``+5``. Returns ``0`` for unknown families. Reads live tuning (Path A).
    """
    if not pattern_name:
        return 0
    name = pattern_name.lower()
    for family, bump in get_tuning().pattern_base_score.items():
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

    @require(lambda detection_result: isinstance(detection_result, dict), "detection_result must be a dict")
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
) -> Candidate | None:
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


def _extract_times(pattern: Any, close_times: Optional[Sequence]) -> tuple[tuple, tuple]:
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
    indices_list: list[int] = []
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

    mapped: list[int] = []
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


def compute_atr(df: pd.DataFrame, window: int | None = None) -> float:
    """Robust ATR: min of the short-window and long-window means.

    A long lookback desensitizes the value to a recent crash/candle burst,
    which would otherwise inflate every ATR-derived buffer.
    """
    t = get_tuning()
    if window is None:
        window = t.atr_window
    long_window = t.atr_long_window

    @require(lambda df: len(df) >= 2, "df must have at least 2 bars")
    @require(lambda window: window >= 1, "window must be >= 1")
    @require(lambda df: {"high", "low", "close"}.issubset(df.columns), "df must contain high/low/close columns")
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
    atr_long = tr.tail(long_window).mean()
    return float(min(atr_short, atr_long))


def compute_rsi(closes: pd.Series, window: int | None = None) -> float:
    """Wilder RSI of the latest close."""
    if window is None:
        window = get_tuning().rsi_window

    @require(lambda window: window >= 1, "window must be >= 1")
    @require(lambda closes: len(closes) >= 0, "closes must be a pd.Series")
    def _check(**_kwargs) -> None:
        return None

    _check(closes=closes, window=window)

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

    @require(lambda interval: isinstance(interval, str) and len(interval) > 0, "interval must be a non-empty string")
    def _check(**_kwargs) -> None:
        return None

    _check(interval=interval)

    rule = get_tuning().htf_rule.get(interval)
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
    rng = row["high"] - row["low"]
    if rng <= 0:
        return False
    if bullish:
        lower_wick = min(row["open"], row["close"]) - row["low"]
        return bool(row["close"] > row["open"] and lower_wick >= 0.5 * rng)
    upper_wick = row["high"] - max(row["open"], row["close"])
    return bool(row["close"] < row["open"] and upper_wick >= 0.5 * rng)


def _rsi_zone_score(rsi: float, bullish: bool, rsi_series: pd.Series) -> float:
    """RSI extreme zone + RSI trend direction dual scoring.

    Regular bullish pattern: RSI in extreme oversold + RSI rising = strongest.
    Regular bearish pattern: RSI in extreme overbought + RSI falling = strongest.
    """
    score = 0
    rsi_recent = rsi_series.tail(5).values if rsi_series is not None and len(rsi_series) >= 2 else []
    # Guard pd.NA: ewm RSI can leave trailing NA; `bool(NA)` raises TypeError.
    if len(rsi_recent) >= 2 and pd.notna(rsi_recent[-1]) and pd.notna(rsi_recent[0]):
        rsi_rising = bool(rsi_recent[-1] > rsi_recent[0])
    else:
        rsi_rising = False

    if bullish:
        if rsi <= 30:
            score += 7
        elif rsi <= 40:
            score += 5
        elif rsi <= 50:
            score += 2
        # RSI improving (rising) = extra confirmation
        if score > 0 and rsi_rising:
            score += 3
        # RSI in overbought zone = caution (may not have bottomed yet)
        if rsi >= 60:
            score -= 3
    else:
        if rsi >= 70:
            score += 7
        elif rsi >= 60:
            score += 5
        elif rsi >= 50:
            score += 2
        # RSI worsening (falling) = extra confirmation for bearish pattern
        if score > 0 and not rsi_rising:
            score += 3
        if rsi <= 40:
            score -= 3
    return score


def confluence_score(
    df: pd.DataFrame,
    candidate: Candidate,
    atr: float,
    rsi: float,
    trend: str,
    divergences: dict,
    pa_scale: float = 1.0,
    rsi_series: pd.Series = None,
    macd_line: float = 0.0,
    macd_histogram: float = 0.0,
    macd_histogram_prev: float = 0.0,
) -> tuple:
    """Enhanced confluence: price action 18, HTF 18, RSI 12, structure 10,
    MACD 8, MACD-zero 8, dual-confirm 8, histogram 5, funding 10.

    Key enhancements vs v4:
    - Regular vs Hidden divergence filtering (not just "any bullish")
    - MACD zero-line position filter
    - RSI zone + RSI trend direction scoring
    - Dual-indicator (RSI + MACD) Regular divergence bonus
    - MACD histogram momentum strength
    """

    @require(lambda atr: atr >= 0, "atr must be non-negative")
    @require(lambda rsi: 0.0 <= rsi <= 100.0, "rsi must be in [0, 100]")
    @require(lambda trend: trend in ("bullish", "bearish", "unknown"), "trend must be one of bullish/bearish/unknown")
    @require(lambda pa_scale: 0.0 <= pa_scale <= 2.0, "pa_scale must be in [0, 2]")
    @require(lambda df: "close" in df.columns and "volume" in df.columns, "df must contain close and volume columns")
    @require(lambda candidate: candidate.prz_low > 0 and candidate.prz_high > 0, "candidate PRZ bounds must be positive")
    def _check(**_kwargs) -> None:
        return None

    _check(df=df, candidate=candidate, atr=atr, rsi=rsi, trend=trend, pa_scale=pa_scale)

    factors: dict[str, float] = {}
    last = df.iloc[-1]

    # --- Price action at the PRZ: reversal candle + volume expansion ---
    pa = 0.0
    if _is_reversal_candle(last, candidate.bullish):
        pa += 15.0
        vol_ma = df["volume"].tail(get_tuning().volume_ma_window).mean()
        if vol_ma > 0 and last["volume"] >= 1.5 * vol_ma:
            pa += 10.0
    factors["price_action"] = pa * pa_scale

    # --- Higher-timeframe trend alignment ---
    if trend == ("bullish" if candidate.bullish else "bearish"):
        factors["htf_trend"] = 25
    elif trend == "unknown":
        factors["htf_trend"] = 10
    else:
        factors["htf_trend"] = 0

    # --- RSI: Regular/Hidden divergence filtering + zone + trend ---
    div_families = divergences or {}
    rsi_divs = div_families.get("rsi", [])

    # Separate Regular vs Hidden divergences (divergences are dicts from pa.to_dict())
    rsi_regular_bull = [d for d in rsi_divs if d.get("name") == "Regular" and d.get("bullish") is True]
    rsi_regular_bear = [d for d in rsi_divs if d.get("name") == "Regular" and d.get("bullish") is False]
    rsi_hidden_bull = [d for d in rsi_divs if d.get("name") == "Hidden" and d.get("bullish") is True]
    rsi_hidden_bear = [d for d in rsi_divs if d.get("name") == "Hidden" and d.get("bullish") is False]

    rsi_score = 0
    if candidate.bullish:
        if rsi_regular_bull:
            rsi_score += 8  # Regular bullish div = true reversal signal
        elif rsi_hidden_bull:
            rsi_score -= 5  # Hidden = momentum延续, 不利于反转
    else:
        if rsi_regular_bear:
            rsi_score += 8
        elif rsi_hidden_bear:
            rsi_score -= 5

    # RSI zone + trend direction scoring
    rsi_zone = _rsi_zone_score(rsi, candidate.bullish, rsi_series if rsi_series is not None else pd.Series([]))
    rsi_score += rsi_zone
    factors["rsi"] = rsi_score

    # --- Structure: PRZ overlaps a recent swing low/high ---
    lookback = get_tuning().swing_lookback
    tail = df["low"].tail(lookback) if candidate.bullish else df["high"].tail(lookback)
    swing = tail.min() if candidate.bullish else tail.max()
    mid = (candidate.prz_low + candidate.prz_high) / 2
    factors["structure"] = 15 if abs(mid - swing) <= get_tuning().atr_prz_sweep * atr else 0

    # --- MACD: Regular/Hidden divergence + zero-line filter + histogram momentum ---
    macd_divs = div_families.get("macd", [])
    macd_regular_bull = [d for d in macd_divs if d.get("name") == "Regular" and d.get("bullish") is True]
    macd_regular_bear = [d for d in macd_divs if d.get("name") == "Regular" and d.get("bullish") is False]
    macd_hidden_bull = [d for d in macd_divs if d.get("name") == "Hidden" and d.get("bullish") is True]
    macd_hidden_bear = [d for d in macd_divs if d.get("name") == "Hidden" and d.get("bullish") is False]

    macd_score = 0
    if candidate.bullish:
        if macd_regular_bull:
            macd_score += 10
        elif macd_hidden_bull:
            macd_score -= 5
    else:
        if macd_regular_bear:
            macd_score += 10
        elif macd_hidden_bear:
            macd_score -= 5
    factors["macd"] = macd_score

    # MACD zero-line filter: MACD below zero for bullish = oversold zone, more reliable
    if candidate.bullish:
        factors["macd_zero"] = 8 if macd_line < 0 else -4
    else:
        factors["macd_zero"] = 8 if macd_line > 0 else -4

    # --- Dual-indicator confirmation: RSI + MACD both with Regular divergences ---
    has_rsi_regular = (candidate.bullish and rsi_regular_bull) or (not candidate.bullish and rsi_regular_bear)
    has_macd_regular = (candidate.bullish and macd_regular_bull) or (not candidate.bullish and macd_regular_bear)
    if has_rsi_regular and has_macd_regular:
        factors["dual_confirm"] = 8
    elif has_rsi_regular or has_macd_regular:
        factors["dual_confirm"] = 3
    else:
        factors["dual_confirm"] = 0

    # --- MACD histogram momentum: bars getting larger in correct direction ---
    if candidate.bullish:
        factors["histogram"] = 5 if (macd_histogram > 0 and macd_histogram > macd_histogram_prev) else 0
    else:
        factors["histogram"] = 5 if (macd_histogram < 0 and macd_histogram < macd_histogram_prev) else 0

    # --- Funding: neutral without futures feed ---
    factors["funding"] = 5

    return sum(factors.values()), factors


def _clamp_sharpe(sharpe: float) -> float:
    return round(max(-10.0, min(10.0, sharpe)), 4)


def _compute_swing_anchor(
    df: pd.DataFrame, atr: float, bullish: bool, entry: float
) -> float | None:
    """Return the recent swing extreme used as a stop redundancy anchor.

    Carney's 3-layer stop: structure + swing + volatility.  This function
    supplies the swing layer — the lowest low (long) or highest high (short)
    over a window long enough to capture ~8 ATR units of price travel.  The
    window is ATR-normalized (bounded 20..120 bars) so 1H and 1D see
    comparable volatility coverage; ``compute_stop`` will reject any swing
    that lands on the wrong side of ``entry``.

    Returns ``None`` when the dataframe is too short or ATR is non-positive.
    """
    if atr <= 0 or len(df) < 20:
        return None
    # Pick a window length that covers ~8 ATRs of recent price travel.
    recent = df.tail(60)
    if recent.empty:
        return None
    bar_range = float(recent["high"].max() - recent["low"].min())
    if bar_range <= 0 or atr <= 0:
        return None
    lookback = max(20, min(120, int(8 * atr / bar_range * 60)))
    lookback = min(lookback, len(df))
    window = df.tail(lookback)
    if window.empty:
        return None
    return float(window["low"].min()) if bullish else float(window["high"].max())


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
    # Fix 8: optional escape hatch passed through to compute_stop.  When
    # not None, completely overrides the level vocabulary for the buffer.
    stop_buffer_atr: float | None = None
    # --- RSI + MACD enhancement fields ---
    rsi_series: pd.Series = None  # full RSI series for trend direction
    macd_line: float = 0.0  # EMA12 - EMA26
    macd_signal: float = 0.0  # 9-period EMA of macd_line
    macd_histogram: float = 0.0  # macd_line - macd_signal (== df["macd"])
    macd_histogram_prev: float = 0.0  # previous bar histogram


def _prepare_score_context(
    df: pd.DataFrame,
    interval: str,
    divergences: Optional[dict],
    stop_buffer_atr: float | None = None,
) -> _ScoreContext | None:
    """Compute shared data-level metrics. Returns None if a hard gate fires.

    Volume authenticity is computed here but the GATE is per-candidate
    (Q6 amendment): formed patterns use the strict authenticity_veto
    threshold, forming patterns use the looser authenticity_halve
    because forming patterns haven't yet had their confirming volume spike.
    """
    t = get_tuning()
    auth = volume_authenticity(df)
    pa_scale = 0.5 if auth < t.authenticity_halve else 1.0

    atr = compute_atr(df)
    if atr <= 0:
        return None
    rsi = compute_rsi(df["close"])
    trend = htf_trend(df, interval)
    sharpe = per_bar_sharpe(df["close"])
    regime_score, regime = quant_regime(df)
    a_min = t.a_grade_min_high_quant if regime == "high_quant" else t.a_grade_min
    regime_mult = t.high_quant_position_mult if regime == "high_quant" else 1.0
    price = float(df["close"].iloc[-1])
    position_mult = round(volatility_multiplier(atr, price) * regime_mult, 4)

    # --- RSI + MACD enhancement: compute full series (df has no "rsi" column) ---
    closes = df["close"]
    delta = closes.diff()
    rsi_w = t.rsi_window
    gain = delta.clip(lower=0).ewm(alpha=1 / rsi_w, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / rsi_w, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi_series = 100 - 100 / (1 + rs)

    # MACD: pyharmonics only stores histogram; recompute line + signal for zero-line filter
    ema_fast = closes.ewm(span=12, adjust=False).mean()
    ema_slow = closes.ewm(span=26, adjust=False).mean()
    macd_line_series = ema_fast - ema_slow
    macd_signal_series = macd_line_series.ewm(span=9, adjust=False).mean()
    macd_histogram_series = macd_line_series - macd_signal_series

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
        # Fix 8: escape hatch forwarded as-is.
        stop_buffer_atr=stop_buffer_atr,
        # --- RSI + MACD enhancement fields ---
        rsi_series=rsi_series,
        macd_line=float(macd_line_series.iloc[-1]),
        macd_signal=float(macd_signal_series.iloc[-1]),
        macd_histogram=float(macd_histogram_series.iloc[-1]),
        macd_histogram_prev=float(macd_histogram_series.iloc[-2]) if len(macd_histogram_series) >= 2 else 0.0,
    )


def score_candidate(
    ctx: _ScoreContext,
    candidate: Candidate,
    stop_level: str = "standard",
) -> Signal | None:
    """Score a single surviving candidate.

    Runs every per-candidate gate in order: volume authenticity (formed vs
    forming threshold), trap veto, adverse-momentum veto, PRZ state
    inference, stop/targets, direction invariant, RR, confluence score,
    grade. Returns ``None`` for any rejection and the fully populated
    :class:`Signal` for survivors so callers can run their own ranking on
    the survivors.

    Q4 + Q6: the raw confluence score is bumped by pattern_base_score for
    the pattern family, and the grade gate additionally receives
    ``width_pct`` so a wide PRZ can never reach A even with a perfect score.
    """

    @require(lambda stop_level: stop_level in ("conservative", "standard", "aggressive"), "stop_level must be one of conservative/standard/aggressive")
    @require(lambda ctx: ctx.atr > 0, "ctx.atr must be positive (set by _prepare_score_context)")
    def _check(**_kwargs) -> None:
        return None

    _check(ctx=ctx, stop_level=stop_level)

    df = ctx.df
    atr = ctx.atr
    last = ctx.last
    t = get_tuning()

    # Q6: per-candidate volume gate. formed=True → strict (authenticity_veto);
    # formed=False → lenient (authenticity_halve) because forming patterns
    # legitimately lack the confirming volume spike.
    threshold = t.authenticity_veto if candidate.formed else t.authenticity_halve
    if ctx.volume_authenticity < threshold:
        logger.debug(
            "Volume authenticity %d < %d for %s pattern, vetoing",
            ctx.volume_authenticity,
            threshold,
            "formed" if candidate.formed else "forming",
        )
        return None

    # PRZ state — needed to derive entry price, which validates swing_anchor.
    swept = is_swept(
        float(last["low"]),
        float(last["high"]),
        ctx.price,
        candidate.prz_low,
        candidate.prz_high,
    )
    status = prz_state(ctx.price, candidate.prz_low, candidate.prz_high, swept)
    if status in ("in_prz", "swept") and _is_reversal_candle(last, candidate.bullish):
        status = "confirmed"
    entry = ctx.price if status != "approaching" else (candidate.prz_high if candidate.bullish else candidate.prz_low)

    # Swing anchor (Carney's 3-layer redundancy): recent extreme on the
    # entry-correct side of price.  ATR-normalized lookback so 1H and 1D
    # see comparable volatility windows.  Returns None on degenerate input.
    swing_anchor = _compute_swing_anchor(df, atr, candidate.bullish, entry)

    # First-pass stop: needed by grade() to compute rr1/rr2. No multipliers
    # yet (grade/regime/trap all default to 1.0).  The final stop with the
    # full multiplier chain is computed below after grade is known.
    stop, stop_basis, invalidation_point = compute_stop(
        candidate, atr, stop_level, swing_anchor=swing_anchor, entry=entry,
    )

    # Quant-trap veto (false breakouts, stop hunts, PRZ failure...).  Note
    # Fix 5: a high trap_score no longer forces a None — it only widens the
    # buffer via trap_multiplier.  trap_veto=True (structural failure) is
    # the only signal that returns None.
    trap_score, trap_veto, _reasons = quant_trap_risk(
        df,
        candidate.prz_low,
        candidate.prz_high,
        candidate.bullish,
    )
    if trap_veto:
        return None

    # Falling-knife / blow-off veto.
    if adverse_momentum_veto(candidate.direction, ctx.sharpe):
        return None

    targets = compute_targets(candidate, entry)

    # Direction geometry invariant (defense in depth).
    if not direction_invariant_ok(
        candidate.direction,
        entry,
        stop,
        [t.price for t in targets],
    ):
        return None

    rr1 = net_rr(entry, stop, targets[0].price)
    rr2 = net_rr(entry, stop, targets[1].price)

    score, factors = confluence_score(
        df,
        candidate,
        atr,
        ctx.rsi,
        ctx.trend,
        ctx.divergences,
        ctx.pa_scale,
        rsi_series=ctx.rsi_series,
        macd_line=ctx.macd_line,
        macd_histogram=ctx.macd_histogram,
        macd_histogram_prev=ctx.macd_histogram_prev,
    )
    # Q4 pattern-reliability bump (Gartley +5, Crab -3, ...).
    score += _pattern_base_score(candidate.name)

    # Q6 PRZ width gate input. Computed here so grade() can apply its 4% cap
    # without each caller having to remember to thread the value through.
    prz_mid = (candidate.prz_low + candidate.prz_high) / 2
    width_pct = (candidate.prz_high - candidate.prz_low) / prz_mid if prz_mid > 0 else 0.0

    bullish_trend = ctx.trend == "bullish"
    bearish_trend = ctx.trend == "bearish"
    htf_aligned = (candidate.bullish and bullish_trend) or (not candidate.bullish and bearish_trend)
    htf_counter = (candidate.bullish and bearish_trend) or (not candidate.bullish and bullish_trend)
    g = grade(
        score,
        rr1,
        rr2,
        htf_aligned,
        htf_counter,
        a_min=ctx.a_min,
        width_pct=width_pct,
    )
    if g is None:
        return None

    # Fix 5/6/7/8: second-pass stop with the full multiplier chain.  grade
    # widens (C/C(参考)) so the wider stop must propagate to the signal,
    # which means RR must be re-derived.  escape hatch (stop_buffer_atr)
    # overrides the level vocabulary entirely.
    trap_m = trap_stop_multiplier(trap_score)
    stop, stop_basis, invalidation_point = compute_stop(
        candidate,
        atr,
        stop_level,
        swing_anchor=swing_anchor,
        entry=entry,
        trap_multiplier=trap_m,
        regime=ctx.regime,
        grade=g,
        stop_buffer_atr=ctx.stop_buffer_atr,
    )

    # Fix 7: RR must be re-derived with the grade-widened stop.  Plan §2.7
    # expects "代码增加 5 行但语义正确" — re-running net_rr is the simplest
    # way to honour the new geometry.
    rr1 = net_rr(entry, stop, targets[0].price)
    rr2 = net_rr(entry, stop, targets[1].price)

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


def rank_signals(signals: list[Signal]) -> Signal | None:
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
    stability_detector: Callable[[pd.DataFrame], str | None] | None,
) -> Signal | None:
    """Re-detect the pattern on two shifted sub-windows; veto if it disappears.

    This is the only stage that costs an extra pattern-detection pass;
    we only run it for A/B-grade signals (the only grades worth the
    latency). Detector failures are treated as unverifiable -> pass.
    """
    if best is None or best.grade not in ("A", "B") or stability_detector is None:
        return best

    stab = get_tuning().stability_window
    try:
        sub1 = stability_detector(df.iloc[:-stab])
        sub2 = stability_detector(df.iloc[stab:])
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
    stability_detector: Callable[[pd.DataFrame], str | None] | None = None,
    stop_level: str = "standard",
    stop_buffer_atr: float | None = None,
) -> Signal | None:
    """Build the best executable signal from candidates, or None.

    Public façade kept for backwards compatibility. Implementation now
    delegates to :func:`score_candidate`, :func:`rank_signals` and
    :func:`apply_stability` so each stage is individually testable.

    ``stability_detector``: optional callable re-running pattern detection on
    a dataframe slice and returning the best pattern name (or None). Used for
    the multi-window stability check on A/B-grade signals.
    """

    @require(lambda interval: isinstance(interval, str) and len(interval) > 0, "interval must be a non-empty string")
    @require(lambda stop_level: stop_level in ("conservative", "standard", "aggressive"), "stop_level must be one of conservative/standard/aggressive")
    def _check_inputs(**_kwargs) -> None:
        return None

    _check_inputs(interval=interval, stop_level=stop_level)
    if df is None or len(df) < get_min_candles() or not candidates:
        return None

    ctx = _prepare_score_context(df, interval, divergences, stop_buffer_atr=stop_buffer_atr)
    if ctx is None:
        return None

    # --- Candidate freshness filter ---------------------------------------
    close_times = df["close_time"] if "close_time" in df.columns else None
    valid, rejected = filter_candidates(
        candidates,
        ctx.price,
        ctx.atr,
        close_times,
    )
    if rejected:
        logger.debug(
            "Filtered %d stale/invalid candidates: %s",
            len(rejected),
            [r.reason for r in rejected],
        )

    # --- Score surviving candidates ----------------------------------------
    scored: list[Signal] = []
    for candidate in valid:
        signal = score_candidate(ctx, candidate, stop_level=stop_level)
        if signal is not None:
            scored.append(signal)

    best = rank_signals(scored)
    return apply_stability(df, best, stability_detector)
