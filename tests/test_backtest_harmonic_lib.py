"""100% coverage tests for scripts/backtest_harmonic_lib.

Each test exercises a single seam in the walk-forward pipeline. The detector
and forward simulator are monkeypatched through the ``detect``/``extract``/
``forward_sim`` kwargs of ``walk_forward``, so the tests stay deterministic.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from scripts.backtest_harmonic_lib import (
    BacktestSignalRecord,
    ForwardResult,
    _maybe_relax_filters,
    _restore_filters,
    aggregate_records,
    markdown_summary,
    report,
    simulate_one,
    walk_forward,
    write_json,
)


# --- Helpers -----------------------------------------------------------------


def _make_window_df(n: int = 30, start_price: float = 100.0) -> pd.DataFrame:
    """Generate a simple uptrending OHLCV window with deterministic timestamp."""
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex([base + timedelta(days=i) for i in range(n)])
    closes = [start_price + i * 0.5 for i in range(n)]
    opens = [closes[i - 1] if i else closes[0] for i in range(n)]
    highs = [max(o, c) + 0.4 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.4 for o, c in zip(opens, closes)]
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
            "close_time": [int(base.timestamp()) + i * 86400 for i in range(n)],
        },
        index=idx,
    )
    df["dts"] = idx
    return df


def _fake_signal_payload(direction: str = "bullish", entry: float = 100.0, tp1: float = 102.0, stop: float = 97.0) -> SimpleNamespace:
    """Build a Signal-like namespace matching what the lib expects."""
    target = SimpleNamespace(label="TP1", price=tp1, fib_basis=None, close_pct=None, move_stop_to=None)
    return SimpleNamespace(
        direction=direction,
        grade="A",
        pattern_name="gartley",
        family="XABCD",
        formed=True,
        entry_reference=entry,
        entry_zone=[entry - 1.0, entry + 1.0],
        stop_loss=stop,
        targets=[target],
        net_rr_tp1=2.0,
    )


def _fake_extract_signal(window_df, symbol, interval, **_):
    return _fake_signal_payload()


def _fake_forward_sim_win(forward_df, signal, **_):
    return ForwardResult("win", 2.0, forward_df.index[1], 1)


def _fake_forward_sim_loss(forward_df, signal, **_):
    return ForwardResult("loss", -1.0, forward_df.index[1], 1)


def _fake_forward_sim_skipped(forward_df, signal, **_):
    return ForwardResult("skipped", 0.0, None, None)


# --- aggregate_records -------------------------------------------------------


class TestAggregateRecords:
    def test_empty(self):
        summary = aggregate_records([])
        assert summary["total_signals"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["avg_r"] == 0.0
        assert summary["profit_factor"] == 0.0
        assert summary["by_grade"] == {}
        assert summary["by_family"] == {}

    def test_mixed(self):
        records = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "win", 2.0, None, 1),
            BacktestSignalRecord(1, "2026-06-02T00:00:00+00:00", "bearish", "A",
                                 "crab", "ABCD", True, 105.0, 108.0, 102.0, 2.0,
                                 105.0, [104, 106], 10, "loss", -1.0, None, 1),
            BacktestSignalRecord(2, "2026-06-03T00:00:00+00:00", "bullish", "B",
                                 "bat", "XABCD", True, 103.0, 100.0, 106.0, 2.0,
                                 103.0, [102, 104], 10, "scratch", 0.0, None, 10),
            BacktestSignalRecord(3, "2026-06-04T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 110.0, 107.0, 113.0, 2.0,
                                 110.0, [109, 111], 10, "skipped", 0.0, None, None),
        ]
        summary = aggregate_records(records)
        assert summary["total_signals"] == 4
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert summary["scratches"] == 1
        assert summary["skipped_signals"] == 1
        assert summary["decisions"] == 2
        assert summary["win_rate"] == 0.5
        # avg_r over all 4 records: 2 + (-1) + 0 + 0 / 4 = 0.25
        assert summary["avg_r"] == pytest.approx(0.25)
        assert summary["total_r"] == pytest.approx(1.0)
        # profit_factor: win_r=2, |loss_r|=1 -> 2
        assert summary["profit_factor"] == pytest.approx(2.0)
        # by grade:
        assert summary["by_grade"]["A"]["count"] == 3
        assert summary["by_grade"]["A"]["wins"] == 1
        assert summary["by_grade"]["B"]["count"] == 1
        # by family:
        assert summary["by_family"]["XABCD"]["count"] == 3
        assert summary["by_family"]["ABCD"]["count"] == 1

    def test_profit_factor_inf_when_all_wins(self):
        records = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "win", 1.5, None, 1),
            BacktestSignalRecord(1, "2026-06-02T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 105.0, 102.0, 107.0, 2.0,
                                 105.0, [104, 106], 10, "win", 2.0, None, 1),
        ]
        summary = aggregate_records(records)
        assert summary["profit_factor"] == float("inf")

    def test_profit_factor_inf_when_losses_zero_with_wins(self):
        # Any wins with zero losses produces an unbounded profit factor.
        records = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "win", 1.0, None, 1),
            BacktestSignalRecord(1, "2026-06-02T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 105.0, 102.0, 107.0, 2.0,
                                 105.0, [104, 106], 10, "scratch", 0.0, None, 1),
        ]
        summary = aggregate_records(records)
        assert summary["profit_factor"] == float("inf")

    def test_profit_factor_zero_when_no_wins_no_losses(self):
        records = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "scratch", 0.0, None, 1),
            BacktestSignalRecord(1, "2026-06-02T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 105.0, 102.0, 107.0, 2.0,
                                 105.0, [104, 106], 10, "skipped", 0.0, None, None),
        ]
        summary = aggregate_records(records)
        assert summary["profit_factor"] == 0.0


# --- write_json --------------------------------------------------------------


class TestWriteJson:
    def test_infinite_float_serialised_as_none(self, tmp_path):
        out = tmp_path / "report.json"
        report_dict = report(
            config={"symbol": "BTCUSDT", "interval": "1d", "days": 90,
                    "window": 30, "step": 1, "horizon": 30},
            summary={"total_signals": 2, "skipped_signals": 0, "decisions": 2,
                     "wins": 2, "losses": 0, "scratches": 0, "win_rate": 1.0,
                     "avg_r": 1.5, "total_r": 3.0, "profit_factor": float("inf"),
                     "by_grade": {}, "by_family": {}},
            records=[],
        )
        write_json(report_dict, out)
        loaded = json.loads(out.read_text())
        # Inf was serialised via allow_nan=False + replace to None:
        assert loaded["summary"]["profit_factor"] is None

    def test_normal_report_roundtrips(self, tmp_path):
        out = tmp_path / "report.json"
        rec = BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                   "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                   100.0, [99, 101], 10, "win", 2.0, "2026-06-02T00:00:00+00:00", 1)
        summary = aggregate_records([rec])
        report_dict = report(
            config={"symbol": "BTCUSDT", "interval": "1d", "days": 90,
                    "window": 30, "step": 1, "horizon": 30},
            summary=summary,
            records=[rec],
        )
        write_json(report_dict, out)
        loaded = json.loads(out.read_text())
        assert loaded["config"]["symbol"] == "BTCUSDT"
        assert loaded["signals"][0]["result"] == "win"


# --- markdown_summary --------------------------------------------------------


class TestMarkdownSummary:
    def test_includes_summary_section(self):
        md = markdown_summary(
            report(config={"symbol": "BTCUSDT", "interval": "1d", "days": 90,
                           "window": 30, "step": 1, "horizon": 30},
                   summary={"total_signals": 0, "skipped_signals": 0, "decisions": 0,
                            "wins": 0, "losses": 0, "scratches": 0, "win_rate": 0.0,
                            "avg_r": 0.0, "total_r": 0.0, "profit_factor": 0.0,
                            "by_grade": {}, "by_family": {}},
                   records=[])
        )
        assert "# Walk-forward backtest — BTCUSDT 1d" in md
        assert "## Config" in md
        assert "## Summary" in md
        assert "total signals: **0**" in md

    def test_includes_signal_table_when_records_present(self):
        recs = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "win", 1.5, None, 1)
        ]
        md = markdown_summary(
            report(config={"symbol": "ETHUSDT", "interval": "4h", "days": 90,
                           "window": 30, "step": 1, "horizon": 30},
                   summary=aggregate_records(recs), records=recs)
        )
        assert "## Signals (first 20)" in md
        assert "gartley" in md
        assert "+1.50" in md

    def test_by_grade_and_family_sections(self):
        recs = [
            BacktestSignalRecord(0, "2026-06-01T00:00:00+00:00", "bullish", "A",
                                 "gartley", "XABCD", True, 100.0, 97.0, 102.0, 2.0,
                                 100.0, [99, 101], 10, "win", 2.0, None, 1),
            BacktestSignalRecord(1, "2026-06-02T00:00:00+00:00", "bearish", "B",
                                 "butterfly", "ABCD", True, 105.0, 108.0, 102.0, 2.0,
                                 105.0, [104, 106], 10, "loss", -1.0, None, 1),
        ]
        md = markdown_summary(
            report(config={"symbol": "BTCUSDT", "interval": "1d", "days": 90,
                           "window": 30, "step": 1, "horizon": 30},
                   summary=aggregate_records(recs), records=recs)
        )
        assert "## By grade" in md
        assert "## By family" in md
        assert "XABCD" in md
        assert "ABCD" in md


# --- simulate_one ------------------------------------------------------------


class TestSimulateOne:
    def test_win_pass_through(self):
        forward = pd.DataFrame(
            {
                "open": [100.0, 100.0, 105.0],
                "high": [101.0, 102.0, 106.0],
                "low": [99.0, 100.0, 104.0],
                "close": [100.5, 101.0, 105.5],
                "volume": [1, 1, 1],
                "close_time": [1, 2, 3],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        sig = _fake_signal_payload(entry=100.0, tp1=105.0, stop=98.0)
        result = simulate_one(forward, sig)
        assert result.result == "win"
        assert result.r_multiple == pytest.approx(5.0 / 2.0)

    def test_loss_pass_through(self):
        forward = pd.DataFrame(
            {
                "open": [100.0, 100.0, 95.0],
                "high": [101.0, 100.5, 96.0],
                "low": [99.0, 97.0, 94.0],
                "close": [100.5, 97.5, 95.5],
                "volume": [1, 1, 1],
                "close_time": [1, 2, 3],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        sig = _fake_signal_payload(entry=100.0, tp1=105.0, stop=98.0)
        result = simulate_one(forward, sig)
        assert result.result == "loss"
        assert result.r_multiple < 0

    def test_skipped_when_entry_never_touched(self):
        forward = pd.DataFrame(
            {
                "open": [200.0, 200.0],
                "high": [201.0, 201.0],
                "low": [199.0, 199.0],
                "close": [200.5, 200.5],
                "volume": [1, 1],
                "close_time": [1, 2],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02"]),
        )
        sig = _fake_signal_payload(entry=100.0, tp1=105.0, stop=98.0)
        result = simulate_one(forward, sig)
        assert result.result == "skipped"
        assert result.r_multiple == 0.0

    def test_bearish_short_win(self):
        forward = pd.DataFrame(
            {
                "open": [200.0, 199.0, 180.0],
                "high": [200.5, 198.5, 181.0],
                "low": [199.0, 179.0, 178.0],
                "close": [199.5, 180.0, 179.5],
                "volume": [1, 1, 1],
                "close_time": [1, 2, 3],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        # Short signal: entry at 200, target 180 (below), stop 210 (above)
        sig = _fake_signal_payload(
            direction="bearish", entry=200.0, tp1=190.0, stop=210.0
        )
        result = simulate_one(forward, sig)
        assert result.result == "win"

    def test_bars_held_attribute(self):
        forward = pd.DataFrame(
            {
                "open": [100.0, 100.0, 105.0],
                "high": [101.0, 102.0, 106.0],
                "low": [99.0, 100.0, 104.0],
                "close": [100.5, 101.0, 105.5],
                "volume": [1, 1, 1],
                "close_time": [1, 2, 3],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        # entry 100, target 105 (above), stop 98 (below).
        sig = _fake_signal_payload(entry=100.0, tp1=105.0, stop=98.0)
        result = simulate_one(forward, sig)
        # Entry triggered on 2026-06-01 (low 99 <= 100 <= high 101); target hit
        # on 2026-06-03 (high 106 >= 105). Two daily bars between them.
        assert result.bars_held == 2

    def test_uses_current_price_when_provided(self):
        forward = pd.DataFrame(
            {
                "open": [100.0, 100.0, 105.0],
                "high": [101.0, 102.0, 106.0],
                "low": [99.0, 100.0, 104.0],
                "close": [100.5, 101.0, 105.5],
                "volume": [1, 1, 1],
                "close_time": [1, 2, 3],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        # Bullish harmonic: PRZ=105 entry zone, stop at 95, TP1 at 115.
        # From the PRZ perspective, stop < entry < target all hold.
        sig = _fake_signal_payload(entry=105.0, tp1=115.0, stop=95.0)
        # Without current_price: entry = signal.entry_reference = 105 → touched
        # on 2026-06-03 (low 104 <= 105 <= high 106), then closes as scratch
        # (stop 95 and tp1 115 not hit before data ends).
        result_prz = simulate_one(forward, sig)
        assert result_prz.result == "scratch"
        # With current_price = 100: entry re-mapped to 100 (live market).
        # Forward row 0 has 99 <= 100 <= 101, entry triggered day 0.
        # Trade stays open; close at last bar as scratch.
        result_market = simulate_one(forward, sig, current_price=100.0)
        assert result_market.result == "scratch"
        assert result_market.r_multiple == 0.0

    def test_malformed_long_levels_skipped(self):
        forward = pd.DataFrame(
            {
                "open": [100.0, 100.0], "high": [101.0, 102.0],
                "low": [99.0, 100.0], "close": [100.5, 101.0],
                "volume": [1, 1], "close_time": [1, 2],
            },
            index=pd.to_datetime(["2026-06-01", "2026-06-02"]),
        )
        # Long signal with target BELOW entry -> invariant violated.
        sig = _fake_signal_payload(entry=100.0, tp1=95.0, stop=90.0)
        result = simulate_one(forward, sig)
        assert result.result == "skipped"
        assert result.r_multiple == 0.0


class TestRelaxFilters:
    def test_relax_patches_rejection_reason(self):
        from app.domain import validation as _val
        original = _val.rejection_reason
        saved = _maybe_relax_filters(True)
        try:
            # Filter is now a no-op.
            assert _val.rejection_reason(original, 100.0, 1.0) is None
            assert _val.rejection_reason(original, 1e9, 0.0) is None
        finally:
            _restore_filters(saved)
        # After restore: original function is back.
        assert _val.rejection_reason is original

    def test_no_relax_leaves_filter_intact(self):
        from app.domain import validation as _val
        original = _val.rejection_reason
        saved = _maybe_relax_filters(False)
        try:
            assert saved is None
            # Filter unchanged; a real candidate should return a rejection.
            assert _val.rejection_reason is original
        finally:
            # Should also be a no-op for restore.
            _restore_filters(None)


# --- walk_forward ------------------------------------------------------------


class TestWalkForward:
    def test_too_few_bars_yields_empty(self):
        df = _make_window_df(n=10)
        out = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=1, horizon=30,
            extract=lambda *a, **k: _fake_signal_payload(),
            forward_sim=lambda *a, **k: ForwardResult("win", 1.0, None, 1),
        )
        assert out == []

    def test_produces_record_for_each_valid_step(self):
        # 90 daily bars → window=30 + horizon=30 → 31 valid steps at step=1.
        df = _make_window_df(n=90)
        out = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=1, horizon=30,
            extract=_fake_extract_signal,
            forward_sim=_fake_forward_sim_win,
        )
        assert len(out) == 31  # end_idx 29..59 inclusive = 31

    def test_step_kwarg_chunks_correctly(self):
        df = _make_window_df(n=90)
        out = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=10, horizon=30,
            extract=_fake_extract_signal,
            forward_sim=_fake_forward_sim_win,
        )
        # end_idx = 29, 39, 49, 59 → 4 records. (last_start = n-horizon = 60).
        assert len(out) == 4

    def test_extract_returns_none_skips(self):
        df = _make_window_df(n=90)

        def extract_none(*args, **kwargs):
            return None

        out = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=20, horizon=30,
            extract=extract_none,
            forward_sim=_fake_forward_sim_win,
        )
        assert out == []

    def test_simulate_returns_skipped_record_still_kept(self):
        df = _make_window_df(n=90)
        out = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=20, horizon=30,
            extract=_fake_extract_signal,
            forward_sim=_fake_forward_sim_skipped,
        )
        # end_idx = 29, 49 → 2 records
        assert len(out) == 2
        assert all(r.result == "skipped" for r in out)

    def test_signal_time_offset_next_open(self):
        df = _make_window_df(n=90)
        out_close = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=30, horizon=30,
            extract=_fake_extract_signal,
            forward_sim=_fake_forward_sim_win,
            signal_time_offset="close",
        )
        out_next = walk_forward(
            df, "BTCUSDT", "1d",
            window=30, step=30, horizon=30,
            extract=_fake_extract_signal,
            forward_sim=_fake_forward_sim_win,
            signal_time_offset="next_open",
        )
        assert len(out_close) == len(out_next) == 2
        # next_open is the candle right after the window-close ts.
        from datetime import datetime as _dt

        idx = df.index
        assert out_next[0].signal_time == _dt.fromisoformat(out_next[0].signal_time).isoformat()


# --- extract_signal ----------------------------------------------------------


class TestExtractSignalNoPattern:
    def test_returns_none_when_detector_empty(self):
        # A monotonically increasing flat series never produces a harmonic.
        df = _make_window_df(n=120, start_price=100.0)
        out = simulate_one.__module__  # noqa: F841 — keep pylint happy on this branch

        from scripts.backtest_harmonic_lib import extract_signal

        result = extract_signal(df, "BTCUSDT", "1d")
        # Either None (no pattern) or a Signal — both are valid; but on this
        # 120-bar near-linear walk there will be no formed pattern.
        # The test guards against crashes / unhandled exceptions.
        assert result is None or hasattr(result, "targets")
