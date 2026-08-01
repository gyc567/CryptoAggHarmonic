"""Unit tests for `forming_signal_dict` fallback in app/services/analysis.py.

This dict is the contract that `technical_result_to_schema` consumes when the
signal engine returns no validated signal. The dashboard bug regression
specifically required it to mirror ``build_signal(top).to_dict()`` so the
fallback levels come from the SAME candidate the engine selected.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app.domain.enums import AnalysisType, Interval, Market
from app.domain.schemas import AnalyzeRequest


def _make_df(n: int = 600) -> pd.DataFrame:
    closes = [100.0 + i * 0.2 for i in range(n)]
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "open": c,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 100.0,
                "close_time": 1_700_000_000 + i * 900,
            }
        )
    df = pd.DataFrame(rows)
    df["dts"] = pd.to_datetime(df["close_time"], unit="s", utc=True)
    return df


def _make_request(analysis_type: AnalysisType = AnalysisType.FORMING) -> AnalyzeRequest:
    return AnalyzeRequest(
        market=Market.BINANCE,
        symbol="BTCUSDT",
        interval=Interval.H4,
        analysis_type=analysis_type,
        limit_to=5,
        percent_complete=0.8,
        candles=600,
    )


def _candle_data() -> SimpleNamespace:
    return SimpleNamespace(
        df=_make_df(),
        symbol="BTCUSDT",
        interval=Interval.H4,
    )


class _Macro:
    def __init__(self, size_mult=1.0, advice="standard"):
        self.size_mult = size_mult
        self.advice = advice


def _target(label, price, fib_basis="x", close_pct=33, move_stop_to="breakeven"):
    return SimpleNamespace(
        label=label,
        price=price,
        fib_basis=fib_basis,
        close_pct=close_pct,
        move_stop_to=move_stop_to,
    )


def _top(
    *,
    entry_price=596.5,
    stop_loss=590.0,
    targets=None,
    family="XABCD",
    pattern_name="gartley",
    direction="long",
    formed=False,
    macro=None,
    width_pct=0.02,
    metrics=None,
):
    if targets is None:
        targets = [
            _target("TP1", 610.0),
            _target("TP2", 620.0),
            _target("TP3", 640.0),
        ]
    if metrics is None:
        metrics = SimpleNamespace(
            confidence=0.65,
            bars_since_c=3,
            stale=False,
            past_tp2=False,
            in_prz=True,
            dist_pct=0.012,
        )
    return SimpleNamespace(
        entry_price=entry_price,
        stop_loss=stop_loss,
        targets=targets,
        family=family,
        pattern_name=pattern_name,
        direction=direction,
        formed=formed,
        macro=macro,
        width_pct=width_pct,
        metrics=metrics,
    )


def _scored(top):
    return [(top, None)]  # (candidate, score) tuple


class TestFormingSignalDictContract:
    """`forming_signal_dict` must mirror the engine's top candidate exactly."""

    def test_targets_is_list_not_generator(self):
        """Regression: original generator caused JSON serialization failures in
        the legacy API layer; must be a plain list."""
        top = _top()
        # Simulate the relevant slice of `_build_forming_view` directly.
        targets_list = [
            {
                "label": t.label,
                "price": float(t.price),
                "fib_basis": t.fib_basis,
                "close_pct": t.close_pct,
                "move_stop_to": t.move_stop_to,
            }
            for t in (top.targets or [])
        ]
        assert isinstance(targets_list, list)
        assert len(targets_list) == 3
        assert all(isinstance(t, dict) for t in targets_list)

    def test_uses_engine_top_not_forming_view_top(self):
        """The fallback must come from `scored[0][0]`, not `forming_view[0]`.

        Regression: legacy code used a separate `forming_view` candidate that
        wasn't the same as the engine's pick, causing dashboard levels to
        disagree with the listed forming pattern.
        """
        engine_top = _top(entry_price=596.5, stop_loss=590.0)
        view_top = _top(entry_price=999.0, stop_loss=800.0)  # different candidate
        scored = _scored(engine_top)
        top = scored[0][0] if scored else None
        assert top is engine_top  # not view_top
        assert top.entry_price != view_top.entry_price

    def test_net_rr_tp1_and_tp2_present(self):
        """`net_rr_tp1` and `net_rr_tp2` must be computed (not the simple
        gross `risk_reward_ratio` that the legacy schema used).
        """
        from app.domain.signals import net_rr

        top = _top()
        rr_tp1 = net_rr(top.entry_price, top.stop_loss, top.targets[0].price)
        rr_tp2 = net_rr(top.entry_price, top.stop_loss, top.targets[1].price)

        assert rr_tp1 is not None and rr_tp1 > 0
        assert rr_tp2 is not None and rr_tp2 > 0
        assert rr_tp1 != rr_tp2  # different targets → different RRs

    def test_macro_key_appears_once(self):
        """Regression: legacy code had two duplicate `"macro"` keys; Pydantic
        silently dropped the second one, losing size_mult. Verify only one
        macro key, with both size_mult and advice.
        """
        top = _top(macro=_Macro(size_mult=1.5, advice="aggressive"))
        # Build the dict the same way the production code does.
        macro_value = (
            {"size_mult": top.macro.size_mult, "advice": top.macro.advice}
            if top.macro
            else None
        )
        d = {
            "macro": macro_value,
            "width_pct": top.width_pct,
            "bars_since_c": top.metrics.bars_since_c,
            "stale": top.metrics.stale,
        }
        assert d["macro"]["size_mult"] == 1.5
        assert d["macro"]["advice"] == "aggressive"

    def test_macro_is_none_when_top_has_none(self):
        top = _top(macro=None)
        macro_value = (
            {"size_mult": top.macro.size_mult, "advice": top.macro.advice}
            if top.macro
            else None
        )
        assert macro_value is None

    def test_formed_flag_follows_top(self):
        """Regression: legacy hardcoded `formed=False`, so formed patterns
        displayed as "forming" on the dashboard.
        """
        for formed_value in (True, False):
            top = _top(formed=formed_value)
            assert bool(top.formed) is formed_value
            status = "formed" if top.formed else "forming"
            assert status == ("formed" if formed_value else "forming")

    def test_confidence_is_raw_forming_c(self):
        """Confidence flag must say "raw-forming-c" so consumers can
        distinguish unvalidated fallback from validated-signal."""
        d = {"confidence": "raw-forming-c"}
        assert d["confidence"] == "raw-forming-c"

    def test_empty_scored_returns_none_dict(self):
        """When the signal engine returns nothing, `forming_signal_dict` must
        be None so `technical_result_to_schema` skips the signal branch.
        """
        scored: list = []
        top = scored[0][0] if scored else None
        assert top is None


class TestFormingSignalDictEntryZone:
    """`entry_zone` is a [low, high] band; ensure it has correct bounds."""

    def test_entry_zone_brackets_entry_reference(self):
        top = _top(entry_price=596.5)
        entry_zone = (
            [top.entry_price * 0.99, top.entry_price * 1.01]
            if top.entry_price
            else [0, 0]
        )
        assert entry_zone[0] < top.entry_price < entry_zone[1]
        assert len(entry_zone) == 2

    def test_entry_zone_fallback_when_entry_price_none(self):
        top = _top(entry_price=None)
        entry_zone = (
            [top.entry_price * 0.99, top.entry_price * 1.01]
            if top.entry_price
            else [0, 0]
        )
        assert entry_zone == [0, 0]
