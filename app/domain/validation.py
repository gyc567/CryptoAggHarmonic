"""Signal validity verification (P4 pillar): pure, I/O-free functions.

Four independent verifiers plus statistical gates, per
docs/plans/harmonic-signal-optimization-plan.md (v4):

1. Candidate freshness/validity filter (stale / violated / completed / degenerate PRZ)
2. Quant-trap risk (false breakouts, stop hunts, volume climax, PRZ failure)
3. Volume authenticity (price-volume alignment, spikes, autocorrelation)
4. Multi-window pattern stability verdict
Plus: quant regime scoring, per-bar momentum Sharpe gate, volatility targeting.

Everything is a pure function of plain values or pandas frames, so the module
can be unit-tested to 100% coverage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd

from app.domain.signals import Candidate, compute_stop, compute_targets

# --- Thresholds ----------------------------------------------------------------

MAX_PRZ_DISTANCE_ATR = 3.0       # |price - PRZ mid| beyond this => stale
MAX_D_AGE_BARS = 20              # D point older than this many bars => stale
MAX_FORMING_PRZ_WIDTH_ATR = 1.0  # forming PRZ wider than this => degenerate

FALSE_BREAK_VETO = 0.25          # false-breakout rate above this => veto
FALSE_BREAK_PENALTY = 0.15
FALSE_BREAK_WARN = 0.08
STOP_HUNT_PENALTY = 0.10
VOL_CLIMAX_PENALTY = 0.12

AUTHENTICITY_HALVE = 40          # below this, price-action factor is halved
AUTHENTICITY_VETO = 25           # below this, all candidates are vetoed

ADVERSE_SHARPE_THRESHOLD = 1.0   # per-bar momentum Sharpe veto threshold

REGIME_MODERATE = 35
REGIME_HIGH = 60

TARGET_ATR_PCT = 2.5             # volatility targeting anchor


# --- 1. Candidate validity filter -----------------------------------------------


@dataclass(frozen=True)
class Rejection:
    candidate: Candidate
    reason: str  # stale_distance | stale_age | degenerate_prz | violated | completed


def rejection_reason(
    candidate: Candidate,
    price: float,
    atr: float,
    close_times: Optional[Sequence] = None,
) -> Optional[str]:
    """Return the rejection reason for a candidate, or None when it is valid."""
    prz_mid = (candidate.prz_low + candidate.prz_high) / 2
    if atr > 0 and abs(price - prz_mid) > MAX_PRZ_DISTANCE_ATR * atr:
        return "stale_distance"

    if close_times is not None and candidate.times:
        d_time = candidate.times[-1]
        age = sum(1 for t in close_times if t > d_time)
        if age > MAX_D_AGE_BARS:
            return "stale_age"

    if not candidate.formed:
        width = candidate.prz_high - candidate.prz_low
        if width <= 0 or (atr > 0 and width > MAX_FORMING_PRZ_WIDTH_ATR * atr):
            return "degenerate_prz"

    stop, _, _ = compute_stop(candidate, atr)
    if (candidate.bullish and price < stop) or (not candidate.bullish and price > stop):
        return "violated"

    # "Completed": price already travelled beyond TP2 measured from the PRZ,
    # i.e. the trade played out without us. Anchored at the PRZ, not at price.
    tp2 = compute_targets(candidate, prz_mid)[1].price
    if (candidate.bullish and price > tp2) or (not candidate.bullish and price < tp2):
        return "completed"

    return None


def filter_candidates(
    candidates: Sequence[Candidate],
    price: float,
    atr: float,
    close_times: Optional[Sequence] = None,
) -> tuple:
    """Split candidates into (valid, rejections)."""
    valid: list[Candidate] = []
    rejected: list[Rejection] = []
    for cand in candidates:
        reason = rejection_reason(cand, price, atr, close_times)
        if reason is None:
            valid.append(cand)
        else:
            rejected.append(Rejection(candidate=cand, reason=reason))
    return valid, rejected


def direction_invariant_ok(
    direction: str,
    entry: float,
    stop: float,
    target_prices: Sequence[float],
) -> bool:
    """Hard geometry invariant: long stop < entry <= TP1 < TP2 < TP3 (short mirrored)."""
    if len(target_prices) < 3:
        return False
    t1, t2, t3 = target_prices[0], target_prices[1], target_prices[2]
    if direction == "long":
        return stop < entry <= t1 < t2 < t3
    return stop > entry >= t1 > t2 > t3


# --- 2. Quant-trap risk ----------------------------------------------------------


def quant_trap_risk(
    df: pd.DataFrame,
    prz_low: float,
    prz_high: float,
    bullish: bool,
    lookback: int = 60,
) -> tuple:
    """Score trap risk and veto on structural failures.

    Returns (score 10-90, veto, reasons).
    """
    d = df.tail(lookback)
    n = len(d)
    if n < 15:
        return 50, False, []

    opens = d["open"].to_numpy(dtype=float)
    highs = d["high"].to_numpy(dtype=float)
    lows = d["low"].to_numpy(dtype=float)
    closes = d["close"].to_numpy(dtype=float)
    vols = d["volume"].to_numpy(dtype=float)

    score = 50
    veto = False
    reasons: list[str] = []

    # False breakouts: pierce a 5-bar extreme by >1% then close back inside.
    false_breaks = 0
    for i in range(5, n):
        prev_high = highs[i - 5:i].max()
        prev_low = lows[i - 5:i].min()
        if (highs[i] > prev_high * 1.01 and closes[i] < prev_high) or (
            lows[i] < prev_low * 0.99 and closes[i] > prev_low
        ):
            false_breaks += 1
    fb_rate = false_breaks / (n - 5)
    if fb_rate > FALSE_BREAK_VETO:
        veto = True
        reasons.append(f"假突破率{fb_rate:.0%}")
    elif fb_rate > FALSE_BREAK_PENALTY:
        score -= 20
        reasons.append(f"假突破频繁({fb_rate:.0%})")
    elif fb_rate > FALSE_BREAK_WARN:
        score -= 8
        reasons.append(f"存在假突破({fb_rate:.0%})")

    # Stop hunts: new 3-bar low followed by a full recovery next bar.
    stop_hunts = 0
    for i in range(3, n - 1):
        recent_low = lows[i - 3:i].min()
        if lows[i] < recent_low * 0.995 and closes[i + 1] > highs[i]:
            stop_hunts += 1
    sh_rate = stop_hunts / (n - 4)
    if sh_rate > STOP_HUNT_PENALTY:
        score -= 15
        reasons.append(f"止损猎杀({sh_rate:.0%})")

    # Volume climax: 2x volume with a tiny body (absorption).
    climaxes = 0
    for i in range(1, n):
        if vols[i - 1] > 0 and vols[i] > 2 * vols[i - 1]:
            body = abs(closes[i] - opens[i])
            price = closes[i] if closes[i] > 0 else opens[i]
            if price > 0 and body / price < 0.015:
                climaxes += 1
    vc_rate = climaxes / (n - 1)
    if vc_rate > VOL_CLIMAX_PENALTY:
        score -= 15
        reasons.append(f"量能高潮({vc_rate:.0%})")

    # PRZ support/resistance failure: wick into the zone, close through it.
    for i in range(n):
        if bullish:
            if prz_low <= lows[i] <= prz_high and closes[i] < prz_low:
                veto = True
                reasons.append("PRZ支撑失败")
                break
        else:
            if prz_low <= highs[i] <= prz_high and closes[i] > prz_high:
                veto = True
                reasons.append("PRZ阻力失败")
                break

    score = min(90, max(10, score))
    return score, veto, reasons


# --- 3. Volume authenticity ------------------------------------------------------


def volume_authenticity(df: pd.DataFrame, window: int = 60) -> int:
    """Price-volume authenticity score (0-100)."""
    d = df.tail(window)
    n = len(d)
    if n < 10:
        return 50

    closes = d["close"].to_numpy(dtype=float)
    vols = d["volume"].to_numpy(dtype=float)

    aligned = 0
    for i in range(1, n):
        price_up = closes[i] > closes[i - 1]
        vol_up = vols[i] > vols[i - 1]
        if price_up == vol_up:
            aligned += 1
    alignment_rate = aligned / (n - 1)

    vol_mean = vols.mean()
    spike_rate = float((vols > vol_mean * 2.5).mean()) if vol_mean > 0 else 0.0

    # Lag-1 autocorrelation of volume.
    v = vols - vol_mean
    denom = float((v * v).sum())
    autocorr = float((v[:-1] * v[1:]).sum() / denom) if denom > 0 else 0.0

    align_score = alignment_rate * 100
    spike_score = max(0.0, 100 - spike_rate * 400)
    autocorr_score = max(0.0, 50 + autocorr * 50)

    score = align_score * 0.40 + spike_score * 0.40 + autocorr_score * 0.20
    return int(min(100, max(0, round(score))))


# --- 4. Multi-window stability verdict ------------------------------------------


def stability_verdict(
    full: Optional[str],
    sub1: Optional[str],
    sub2: Optional[str],
) -> tuple:
    """Compare the pattern found in full/head-trimmed/tail-trimmed windows.

    Returns (score, suspect). suspect=True means the pattern only exists in
    the full window and is likely manufactured noise => veto.
    """
    if full and sub1 and sub2:
        if full == sub1 == sub2:
            return 85, False
        if full == sub1 or full == sub2:
            return 55, False
        return 25, False
    if full and (sub1 or sub2):
        return 40, False
    if full:
        return 20, True
    return 60, False


# --- 5. Quant regime -------------------------------------------------------------


def quant_regime(df: pd.DataFrame, window: int = 100) -> tuple:
    """Market manipulation/quant-dominance regime from recent candles.

    Returns (score 0-100, regime) where regime is normal | moderate_quant | high_quant.
    """
    d = df.tail(window)
    n = len(d)
    if n < 20:
        return 50, "normal"

    opens = d["open"].to_numpy(dtype=float)
    highs = d["high"].to_numpy(dtype=float)
    lows = d["low"].to_numpy(dtype=float)
    closes = d["close"].to_numpy(dtype=float)
    vols = d["volume"].to_numpy(dtype=float)

    gaps = 0
    for i in range(1, n):
        if closes[i - 1] > 0 and abs(opens[i] - closes[i - 1]) / closes[i - 1] > 0.008:
            gaps += 1
    gap_freq = gaps / (n - 1)

    reversals = 0
    for i in range(n):
        if opens[i] > 0 and lows[i] > 0:
            body = abs(closes[i] - opens[i]) / opens[i]
            rng = (highs[i] - lows[i]) / lows[i]
            if rng > 0.03 and body < 0.005:
                reversals += 1
    reversal_rate = reversals / n

    vol_mean = vols.mean()
    vol_cv = float(vols.std() / vol_mean) if vol_mean > 0 else 0.0

    rets = (closes[1:] - closes[:-1]) / closes[:-1]
    ret_mean = rets.mean()
    ret_std = rets.std()
    tails = 0
    if ret_std > 0:
        tails = int((abs(rets - ret_mean) > 3 * ret_std).sum())
    tail_rate = tails / len(rets)

    gap_score = min(100.0, gap_freq * 300)
    reversal_score = min(100.0, reversal_rate * 500)
    vol_score = min(100.0, vol_cv * 80)
    tail_score = min(100.0, tail_rate * 1000)

    score = gap_score * 0.25 + reversal_score * 0.25 + vol_score * 0.30 + tail_score * 0.20
    score = int(min(100, max(0, round(score))))

    if score >= REGIME_HIGH:
        regime = "high_quant"
    elif score >= REGIME_MODERATE:
        regime = "moderate_quant"
    else:
        regime = "normal"
    return score, regime


# --- 6. Statistical gates ---------------------------------------------------------


def per_bar_sharpe(closes: pd.Series, window: int = 20) -> float:
    """Per-bar momentum Sharpe (mean/std of recent returns).

    Interval-agnostic: no annualization, so it works uniformly from 15m to 1w.
    Returns +/-inf for zero-variance drift (consistent momentum), 0.0 for flat.
    """
    rets = closes.pct_change().dropna().tail(window)
    if len(rets) < 3:
        return 0.0
    mean = float(rets.mean())
    std = float(rets.std(ddof=1))
    if math.isnan(std) or std < 1e-12:
        # Effectively zero-variance drift (floating-point noise included).
        if mean > 0:
            return math.inf
        if mean < 0:
            return -math.inf
        return 0.0
    return mean / std


def adverse_momentum_veto(direction: str, sharpe: float, threshold: float = ADVERSE_SHARPE_THRESHOLD) -> bool:
    """Veto entries against extreme consistent momentum (falling knives / blow-offs).

    Mild adverse momentum is EXPECTED at a reversal PRZ and is not penalized;
    only |sharpe| above the threshold in the adverse direction vetoes.
    """
    if direction == "long":
        return sharpe < -threshold
    return sharpe > threshold


def volatility_multiplier(atr: float, close: float, target_atr_pct: float = TARGET_ATR_PCT) -> float:
    """Position scaling so each trade carries similar volatility (clamped 0.5-1.5)."""
    if close <= 0:
        return 1.0
    atr_pct = atr / close * 100
    mult = target_atr_pct / max(atr_pct, 0.5)
    return round(min(1.5, max(0.5, mult)), 4)
