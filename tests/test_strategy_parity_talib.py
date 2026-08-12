"""
Parity test: TA-Lib indicators (used by Freqtrade IStrategy) vs
``strategy_core`` indicators (used by API scan).

After full warmup (200 bars), the divergence is:

  - RSI:    max_abs ≈ 4e-6 (machine precision — Wilder=pandas EWM)
  - EMA:    max_abs ≈ 0.09 price units (same alpha formula, tiny drift)
  - ATR:    max_abs ≈ 1.5  price units (TA-Lib Wilder vs strategy_core
            simple rolling — the real divergence)
  - RSI cross-up signal mismatch: 3 / 500 bars (~0.6%)

The "single source of truth" claim in
``freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py`` line 4
("Single source of truth: app.domain.strategy_core") is currently
aspirational, not actual — the freqtrade file imports talib.abstract
at line 33 and re-implements populate_indicators at lines 113-144.

This test pins down the *current* divergence so future refactors can
verify the gap closes (and re-open it if it widens).

ponytail: this test exists because the freqtrade file re-implements
indicators instead of importing from strategy_core. The ceiling is to
delete populate_indicators in the freqtrade file and replace it with a
thin wrapper that calls strategy_core.compute_indicators(). Upgrade
path is in docs/plans/freqtrade-strategy-bidirectional-compat.md §4.2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.domain.strategy_core import (
    ATR_WINDOW,
    EMA_TREND_SPAN,
    RSI_WINDOW,
    atr_series,
    ema_series,
    rsi_series,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_df() -> pd.DataFrame:
    """500-bar synthetic OHLCV; deterministic via numpy seed."""
    rng = np.random.default_rng(42)
    n = 500
    base = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    return pd.DataFrame(
        {
            "open": base + rng.standard_normal(n) * 0.1,
            "high": base + rng.standard_normal(n).clip(min=0) * 0.3,
            "low": base - rng.standard_normal(n).clip(min=0) * 0.3,
            "close": base,
            "volume": rng.random(n) * 1000,
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import_talib() -> bool:
    try:
        import talib.abstract  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_strategy_core_rsi_returns_wilder_series(synthetic_df: pd.DataFrame) -> None:
    """strategy_core.rsi_series uses Wilder EWM (alpha = 1/N)."""
    rsi = rsi_series(synthetic_df["close"], RSI_WINDOW).dropna()
    # Wilder RSI stays in [0, 100]
    assert (rsi >= 0.0).all() and (rsi <= 100.0).all()
    # Mean reverts toward 50 in random walk
    assert 30.0 < rsi.mean() < 70.0


def test_strategy_core_ema_and_atr_smoke(synthetic_df: pd.DataFrame) -> None:
    """strategy_core.ema_series + atr_series are non-NaN after warmup."""
    ema = ema_series(synthetic_df["close"], EMA_TREND_SPAN).dropna()
    atr = atr_series(synthetic_df, ATR_WINDOW).dropna()
    assert len(ema) > 200
    assert len(atr) > 100
    assert (atr >= 0).all()


@pytest.mark.skipif(
    not _try_import_talib(),
    reason="TA-Lib not installed (optional dependency for parity test)",
)
def test_parity_talib_vs_strategy_core_pins_current_divergence(
    synthetic_df: pd.DataFrame,
) -> None:
    """
    Pin down the current numerical gap between TA-Lib (freqtrade side)
    and strategy_core (API side) so future refactors can verify the
    gap closes.

    Values pinned on 2026-08-12 with synthetic_df fixture (seed=42, n=500,
    dt=0.5). Documenting the gap here is preferable to ignoring it:
    a real backtest that mixes both implementations can produce
    contradictory signals on 0.5–1% of bars.
    """
    import talib.abstract as ta

    df = synthetic_df
    # TA-Lib uses Wilder smoothing from bar 0; pandas EWM `adjust=False`
    # matches after a few periods of warmup. Bars 0..~200 show the
    # largest discrepancy (transient convergence to steady state).
    warmup = 200

    rsi_pd = rsi_series(df["close"], RSI_WINDOW)
    ema_pd = ema_series(df["close"], EMA_TREND_SPAN)
    atr_pd = atr_series(df, ATR_WINDOW)

    rsi_ta = pd.Series(ta.RSI(df, timeperiod=RSI_WINDOW), index=df.index)
    ema_ta = pd.Series(ta.EMA(df, timeperiod=EMA_TREND_SPAN), index=df.index)
    atr_ta = pd.Series(ta.ATR(df, timeperiod=ATR_WINDOW), index=df.index)

    rsi_diff = (rsi_pd - rsi_ta).dropna().iloc[warmup:]
    ema_diff = (ema_pd - ema_ta).dropna().iloc[warmup:]
    atr_diff = (atr_pd - atr_ta).dropna().iloc[warmup:]

    # After full warmup:
    #   RSI: max_abs ≈ 4e-6 (machine precision match, Wilder=pandas EWM)
    #   EMA: max_abs ≈ 0.09 price units (acceptable; same alpha formula)
    #   ATR: max_abs ≈ 1.5 price units — TA-Lib Wilder vs strategy_core
    #        simple rolling; this is the real divergence.
    assert rsi_diff.abs().mean() < 1e-3
    assert rsi_diff.abs().max() < 1e-2

    assert ema_diff.abs().mean() < 0.1
    assert ema_diff.abs().max() < 0.2

    # ATR — pinned divergence. If the gap widens, fail. If a future
    # refactor switches strategy_core.atr_series to Wilder smoothing,
    # tighten these bounds to < 0.1.
    assert atr_diff.abs().mean() < 1.0
    assert atr_diff.abs().max() < 2.0

    # ── Signal divergence: rsi_prev <= 30 < rsi_now cross-up flag
    cross_up_pd = (rsi_pd.shift(1) <= 30) & (rsi_pd > 30)
    cross_up_ta = (rsi_ta.shift(1) <= 30) & (rsi_ta > 30)
    sig_mismatch = int((cross_up_pd != cross_up_ta).sum())
    # Pinned at 3/500 on the synthetic fixture. If a future refactor
    # closes this gap to 0, this assertion must be tightened.
    assert sig_mismatch < 10


def test_freqtrade_strategy_docstring_claims_strategy_core() -> None:
    """
    Locked assertion: the freqtrade trend_rsi_strategy.py docstring
    claims ``app.domain.strategy_core`` as the source of truth. If the
    file ever removes that claim without actually importing
    strategy_core, fail this test.
    """
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "freqtrade_dev_mcp" / "user_data" / "strategies" / "trend_rsi_strategy.py"
    src = p.read_text()
    assert "Single source of truth" in src, (
        f"{p} lost its 'Single source of truth' docstring marker; "
        "re-add the marker or update the parity test."
    )
    # Either: imports strategy_core (ideal), or its docstring marker
    # is present (current state with drift).
    assert "app.domain.strategy_core" in src or "talib.abstract" in src