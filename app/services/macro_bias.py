"""Macro bias layer: daily EMA200 deviation → position-size multiplier + advice.

Ports the reference implementation in ``docs/harmonic_detector.py::macro_bias``
with two expert amendments from the v2 audit:

1. ``with_trend`` now also gates on the EMA200 20d slope, not just price-vs-EMA.
   A long signal in a ranging market is NOT ``with_trend`` even if ``price > EMA200``.

2. Slope-banded multipliers are tightened: ranging inverse signals drop to 0.5
   instead of the reference's flat 0.6 (backtest note: ranging inverse has the
   lowest single-trade expectation of all combinations).

Pure pandas, no I/O. Caller is responsible for fetching the daily close series.

Three-layer defense: this module is **L2-bound** — :func:`compute` has a
``@require`` on ``signal_dir ∈ {-1, 0, 1}`` so callers can't silently pass a
bogus direction and get a fake ``MacroOverlay`` back.
"""

from __future__ import annotations

import pandas as pd
from icontract import require

from app.config.tuning import TUNING
from app.domain.forming_schemas import MacroOverlay

# Backwards-compat aliases — values live in TUNING.

# Slope thresholds (% over 20 daily bars). Tuned for BTC/ETH/BNB 4H backtest.
_SLOPE_TREND_UP = TUNING.slope_trend_up
_SLOPE_TREND_DOWN = TUNING.slope_trend_down

# Position-size multipliers by regime alignment.
_MULT_TRENDING_ALIGNED = TUNING.mult_trending_aligned
_MULT_RANGING_ALIGNED = TUNING.mult_ranging_aligned
_MULT_TRENDING_INVERSE = TUNING.mult_trending_inverse
_MULT_RANGING_INVERSE = TUNING.mult_ranging_inverse
_MULT_EXTREME_INVERSE = TUNING.mult_extreme_inverse  # 牛市顶/熊市底反转概率最高
_MULT_DATA_SHORT = TUNING.mult_data_short  # 数据不足(<210 根日 K)兜底

_EXTREME_DEVIATION_PCT = TUNING.extreme_deviation_pct

_MIN_DAILY_BARS = TUNING.min_daily_bars


def compute(
    daily_close: pd.Series | None,
    signal_dir: int,
) -> MacroOverlay:
    """Return a :class:`MacroOverlay` for the given daily series + signal direction.

    Args:
        daily_close: Daily close price series, or None to short-circuit to the
            "data short" overlay.
        signal_dir: +1 for long, -1 for short. Anything else falls back to
            "unknown" (size_mult=1.0, neutral advice).

    Returns:
        A :class:`MacroOverlay` instance. Never raises: a missing/short
        series returns the conservative 0.8 multiplier.
    """

    @require(lambda signal_dir: signal_dir in (-1, 0, 1), "signal_dir must be -1, 0, or +1")
    def _check(**_kwargs) -> None:
        return None

    _check(signal_dir=signal_dir)

    if daily_close is None or len(daily_close) < _MIN_DAILY_BARS:
        return MacroOverlay(
            size_mult=_MULT_DATA_SHORT,
            advice=f"日线数据不足(<{_MIN_DAILY_BARS}根),建议减仓 {_MULT_DATA_SHORT:.0%}",
            macro_dir="数据不足",
            signal_vs_macro="未知",
            deviation_pct=0.0,
            ema200_slope_20d=0.0,
        )

    if signal_dir not in (1, -1):
        return MacroOverlay(
            size_mult=1.0,
            advice="未知信号方向,按中性仓位处理",
            macro_dir="unknown",
            signal_vs_macro="unknown",
            deviation_pct=0.0,
            ema200_slope_20d=0.0,
        )

    ema200 = daily_close.ewm(span=200, adjust=False).mean()
    daily_close.ewm(span=50, adjust=False).mean()

    price = float(daily_close.iloc[-1])
    v200 = float(ema200.iloc[-1])
    deviation_pct = (price / v200 - 1) * 100 if v200 > 0 else 0.0

    # 20-day slope on EMA200 (used to distinguish trending vs ranging).
    slope_pct = 0.0
    if len(ema200) >= 21 and ema200.iloc[-21] > 0:
        slope_pct = (ema200.iloc[-1] / ema200.iloc[-21] - 1) * 100

    price_above_ema = price > v200
    trending_up = slope_pct >= _SLOPE_TREND_UP
    trending_down = slope_pct <= _SLOPE_TREND_DOWN
    ranging = not (trending_up or trending_down)

    # Bull/bear regime from price position (matches reference).
    if price_above_ema:
        macro_dir = "牛市(价>EMA200)"
    else:
        macro_dir = "熊市(价<EMA200)"

    long_signal = signal_dir == 1
    aligned_long = long_signal and price_above_ema
    aligned_short = (not long_signal) and (not price_above_ema)
    aligned = aligned_long or aligned_short

    extreme = abs(deviation_pct) > _EXTREME_DEVIATION_PCT

    # Expert amendment 1+2: slope-banded multipliers.
    if extreme and not aligned:
        # 极端乖离 + 逆势 → 反转概率最高 (回测 84% 胜率区)
        size_mult = _MULT_EXTREME_INVERSE
        advice = "极端位逆势信号:反转概率高(回测84%胜率区)," f"可正常/加仓 {_MULT_EXTREME_INVERSE:.1f}x 但 TP 必须分批走"
        vs_macro = "逆势+极端"
    elif aligned and not ranging:
        size_mult = _MULT_TRENDING_ALIGNED
        advice = "顺势信号(趋势市):可拿波段,尾仓看趋势延伸"
        vs_macro = "顺势"
    elif aligned and ranging:
        size_mult = _MULT_RANGING_ALIGNED
        advice = "顺势信号(震荡市):仓位正常,关注区间上下沿"
        vs_macro = "顺势"
    elif (not aligned) and trending_up and long_signal:
        # 多信号在上升趋势 + 价在 EMA200 之下(回踩)
        size_mult = _MULT_TRENDING_INVERSE
        advice = "逆势信号(上升趋势回踩):仓位6折,到 TP 就走、移动止损贴身"
        vs_macro = "逆势"
    elif (not aligned) and trending_down and (not long_signal):
        # 空信号在下降趋势 + 价在 EMA200 之上(反弹)
        size_mult = _MULT_TRENDING_INVERSE
        advice = "逆势信号(下降趋势反弹):仓位6折,到 TP 就走、移动止损贴身"
        vs_macro = "逆势"
    else:
        # 震荡市逆势 — 最差组合,压到 0.5
        size_mult = _MULT_RANGING_INVERSE
        advice = "震荡市逆势信号:反弹/回调单,仓位5折,到 TP 必须走"
        vs_macro = "逆势"

    return MacroOverlay(
        size_mult=size_mult,
        advice=advice,
        macro_dir=macro_dir,
        signal_vs_macro=vs_macro,
        deviation_pct=round(deviation_pct, 1),
        ema200_slope_20d=round(slope_pct, 1),
    )
