"""Tests for bench.runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pandas as pd
import pytest

# Skip if matplotlib is not available (required by bench.report.charts)
pytest.importorskip("matplotlib", reason="matplotlib not installed")

import bench.runner as runner_mod
from bench.runner import (
    BenchRunResult,
    ChartPaths,
    build_parser,
    convert_records,
    main,
    run_bench,
    run_pipeline,
)


# --- Fixtures ----------------------------------------------------------------

def _fake_backtest_record(**overrides):
    """Build a minimal BacktestSignalRecord-compatible object."""
    base = dict(
        step_index=0,
        signal_time="2026-07-30T00:00:00Z",
        direction="long",
        grade="A",
        pattern_name="gartley",
        family="gartley",
        formed=True,
        entry_price=100.0,
        stop_loss=95.0,
        tp1=110.0,
        rr1=2.0,
        entry_reference=99.5,
        entry_zone=[98.0, 102.0],
        horizon=30,
        result="win",
        r_multiple=2.0,
        exit_time="2026-08-15T00:00:00Z",
        bars_held=10,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_df(n: int = 100) -> pd.DataFrame:
    """Build a minimal OHLC dataframe for the fetch mock."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000.0] * n,
            "close_time": idx,
            "dts": idx,
        },
        index=idx,
    )


# --- convert_records ---------------------------------------------------------

def test_convert_records_win_to_tp2() -> None:
    r = _fake_backtest_record(result="win", r_multiple=2.5)
    out = convert_records([r], "BTCUSDT", "1d")
    assert len(out) == 1
    rec = out[0]
    assert rec.symbol == "BTCUSDT"
    assert rec.timeframe == "1d"
    assert rec.pattern_type == "gartley"
    assert rec.pattern_family == "gartley"
    assert rec.outcome == "tp2"
    assert rec.net_rr == 2.5
    assert rec.exit_reason == "win"


def test_convert_records_loss_to_stoploss() -> None:
    rec = convert_records(
        [_fake_backtest_record(result="loss", r_multiple=-1.0)],
        "ETHUSDT", "4h",
    )[0]
    assert rec.outcome == "stoploss"
    assert rec.net_rr == -1.0


def test_convert_records_scratch_to_breakeven() -> None:
    rec = convert_records(
        [_fake_backtest_record(result="scratch", r_multiple=0.0)],
        "BTCUSDT", "1d",
    )[0]
    assert rec.outcome == "breakeven"
    assert rec.net_rr == 0.0


def test_convert_records_skipped_to_incomplete() -> None:
    rec = convert_records(
        [_fake_backtest_record(result="skipped", r_multiple=0.0)],
        "BTCUSDT", "1d",
    )[0]
    assert rec.outcome == "incomplete"


def test_convert_records_unknown_result_to_incomplete() -> None:
    rec = convert_records(
        [_fake_backtest_record(result="weird", r_multiple=0.0)],
        "BTCUSDT", "1d",
    )[0]
    assert rec.outcome == "incomplete"


def test_convert_records_synthetic_defaults() -> None:
    rec = convert_records([_fake_backtest_record()], "BTCUSDT", "1d")[0]
    assert rec.atr_at_entry == 2.0
    assert rec.prz_width_atr == 0.3
    assert rec.entry_offset_atr == 0.0
    assert rec.confluence_score == 0.0
    assert rec.stability_verdict == ""
    assert rec.regime == ""
    assert rec.tp2 == 0.0
    assert rec.tp3 == 0.0


def test_convert_records_unknown_pattern_family_defaults() -> None:
    rec = convert_records(
        [_fake_backtest_record(family="", pattern_name="custom")],
        "BTCUSDT", "1d",
    )[0]
    assert rec.pattern_family == "XABCD"


def test_convert_records_unknown_pattern_name_defaults() -> None:
    rec = convert_records(
        [_fake_backtest_record(pattern_name="")],
        "BTCUSDT", "1d",
    )[0]
    assert rec.pattern_type == "unknown"


def test_convert_records_signal_id_unique() -> None:
    a = convert_records(
        [_fake_backtest_record(step_index=0)],
        "BTCUSDT", "1d",
    )[0]
    b = convert_records(
        [_fake_backtest_record(step_index=1)],
        "BTCUSDT", "1d",
    )[0]
    assert a.signal_id != b.signal_id


# --- run_pipeline ------------------------------------------------------------

def test_run_pipeline_runs_stages_and_aggregates() -> None:
    sigs = convert_records(
        [
            _fake_backtest_record(result="win", r_multiple=2.0),
            _fake_backtest_record(result="win", r_multiple=2.0),
            _fake_backtest_record(result="loss", r_multiple=-1.0),
        ],
        "BTCUSDT", "1d",
    )
    agg = run_pipeline(sigs)
    assert agg["n_signals"] == 3
    assert agg["n_patterns"] == 1
    # All 3 in same pattern (gartley), so 2 wins + 1 loss
    for rec in sigs:
        assert rec.stage1_score is not None
        assert rec.stage3_score is not None
        assert rec.stage4a_score == 0.0  # skipped in v1
        assert rec.stage4b_score is not None
        assert rec.signal_score is not None
        assert rec.config_score is not None
        assert rec.bench_total is not None


def test_run_pipeline_empty_returns_empty_agg() -> None:
    agg = run_pipeline([])
    assert agg["n_signals"] == 0
    assert agg["n_patterns"] == 0


# --- ChartPaths dataclass ----------------------------------------------------

def test_chart_paths_defaults_to_empty_list() -> None:
    cp = ChartPaths()
    assert cp.dir == ""
    assert cp.paths == []


def test_chart_paths_explicit() -> None:
    cp = ChartPaths(dir="/tmp", paths=["/tmp/a.png"])
    assert cp.dir == "/tmp"
    assert cp.paths == ["/tmp/a.png"]


# --- run_bench orchestrator --------------------------------------------------

@pytest.fixture
def fake_walk_forward():
    """A walk_forward replacement that returns 2 fake records."""
    def _fn(df, symbol, interval, **kw):
        return [
            _fake_backtest_record(result="win", r_multiple=2.0),
            _fake_backtest_record(result="loss", r_multiple=-1.0),
        ]
    return _fn


@pytest.fixture
def patch_fetch(monkeypatch):
    """Stub fetch_historical_data to return a tiny DataFrame."""
    def _fake_fetch(market, symbol, interval, lookback_days, end=None):
        return _fake_df(n=100)
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        _fake_fetch,
    )


def test_run_bench_returns_result_without_writes(
    fake_walk_forward, patch_fetch,
) -> None:
    res = run_bench(
        walk_forward_fn=fake_walk_forward,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=None,
    )
    assert res.n_records == 2
    assert res.n_wins == 1
    assert res.n_losses == 1
    assert res.csv_path is None
    assert res.leaderboard_path is None
    assert res.charts.paths == []


def test_run_bench_default_config_id(
    fake_walk_forward, patch_fetch,
) -> None:
    res = run_bench(
        walk_forward_fn=fake_walk_forward,
        symbol="ETHUSDT",
        interval="4h",
        days=60,
        window=20,
        step=1,
        horizon=15,
        out_dir=None,
    )
    assert res.config_id == "ETHUSDT_4h_60d"


def test_run_bench_explicit_config_id(
    fake_walk_forward, patch_fetch,
) -> None:
    res = run_bench(
        walk_forward_fn=fake_walk_forward,
        symbol="ETHUSDT",
        interval="4h",
        days=60,
        window=20,
        step=1,
        horizon=15,
        out_dir=None,
        config_id="my_run",
    )
    assert res.config_id == "my_run"


def test_run_bench_writes_artifacts(
    fake_walk_forward, patch_fetch, tmp_path: Path,
) -> None:
    res = run_bench(
        walk_forward_fn=fake_walk_forward,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=tmp_path,
    )
    # CSV + leaderboard + 8 charts (8 PNG files)
    assert res.csv_path is not None
    assert Path(res.csv_path).exists()
    assert res.leaderboard_path is not None
    assert Path(res.leaderboard_path).exists()
    assert len(res.charts.paths) == 8
    for p in res.charts.paths:
        assert Path(p).exists()


def test_run_bench_leaderboard_json_loadable(
    fake_walk_forward, patch_fetch, tmp_path: Path,
) -> None:
    res = run_bench(
        walk_forward_fn=fake_walk_forward,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=tmp_path,
        config_id="lbtest",
    )
    data = json.loads(Path(res.leaderboard_path).read_text())
    assert data["extra"]["config_id"] == "lbtest"
    assert data["n_points"] == 1
    # Only 2 records in one pattern → n<10 → low_confidence=True (expected)
    assert data["low_confidence"] is True
    # The top-level warnings key surfaces which patterns are low-sample.
    # fake_walk_forward emits 2 records all in pattern "gartley" → "gartley"
    # is in the low-sample list.
    assert "gartley" in data["warnings"]
    pt = data["points"][0]
    assert "base_params_sha" in pt
    assert "signal_score" in pt
    assert "config_score" in pt
    assert "bench_total" in pt


def test_run_bench_leaderboard_no_warnings_when_all_patterns_have_10_plus(
    monkeypatch, patch_fetch, tmp_path: Path,
) -> None:
    """Top-level warnings=[] when every pattern has ≥10 signals."""
    def _ten(df, symbol, interval, **kw):
        return [_fake_backtest_record(result="win", r_multiple=2.0) for _ in range(12)]
    res = run_bench(
        walk_forward_fn=_ten,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=tmp_path,
        config_id="lwtest",
    )
    data = json.loads(Path(res.leaderboard_path).read_text())
    assert data["warnings"] == []
    assert data["low_confidence"] is False


def test_run_bench_passes_args_to_walk_forward(
    fake_walk_forward, patch_fetch,
) -> None:
    seen: dict = {}

    def _spy(df, symbol, interval, **kw):
        seen["symbol"] = symbol
        seen["interval"] = interval
        seen.update(kw)
        return [_fake_backtest_record()]

    run_bench(
        walk_forward_fn=_spy,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=None,
    )
    assert seen["symbol"] == "BTCUSDT"
    assert seen["interval"] == "1d"
    assert seen["window"] == 30
    assert seen["step"] == 1
    assert seen["horizon"] == 30


def test_run_bench_empty_records(
    monkeypatch, patch_fetch,
) -> None:
    def _empty(df, symbol, interval, **kw):
        return []

    res = run_bench(
        walk_forward_fn=_empty,
        symbol="BTCUSDT",
        interval="1d",
        days=90,
        window=30,
        step=1,
        horizon=30,
        out_dir=None,
    )
    assert res.n_records == 0
    assert res.n_wins == 0
    assert res.n_losses == 0
    assert res.signal_score == 0.0


def test_run_bench_no_data_exits(
    monkeypatch,
) -> None:
    def _no_data(market, symbol, interval, lookback_days, end=None):
        return None

    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        _no_data,
    )
    with pytest.raises(SystemExit):
        run_bench(
            walk_forward_fn=lambda *a, **k: [],
            symbol="BTCUSDT",
            interval="1d",
            days=90,
            window=30,
            step=1,
            horizon=30,
            out_dir=None,
        )


def test_run_bench_no_data_empty_df_exits(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        lambda *a, **k: _fake_df(n=0),
    )
    with pytest.raises(SystemExit):
        run_bench(
            walk_forward_fn=lambda *a, **k: [],
            symbol="BTCUSDT",
            interval="1d",
            days=90,
            window=30,
            step=1,
            horizon=30,
            out_dir=None,
        )


# --- build_parser ------------------------------------------------------------

def test_build_parser_defaults() -> None:
    ns = build_parser().parse_args([])
    assert ns.symbol == "BTCUSDT"
    assert ns.interval == "1d"
    assert ns.days == 90
    assert ns.window == 30
    assert ns.step == 1
    assert ns.horizon == 30
    assert ns.market == "binance"
    assert ns.no_write is False
    assert ns.silent is False


def test_build_parser_overrides() -> None:
    ns = build_parser().parse_args(
        ["--symbol", "ETHUSDT", "--interval", "4h", "--days", "30",
         "--window", "15", "--step", "2", "--horizon", "10",
         "--no-write", "--silent", "--config-id", "x",
         "--out-dir", "/tmp/out"],
    )
    assert ns.symbol == "ETHUSDT"
    assert ns.interval == "4h"
    assert ns.days == 30
    assert ns.window == 15
    assert ns.step == 2
    assert ns.horizon == 10
    assert ns.no_write is True
    assert ns.silent is True
    assert ns.config_id == "x"
    assert ns.out_dir == "/tmp/out"


# --- main() CLI --------------------------------------------------------------

def test_main_help_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_main_with_no_write_silent(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        lambda *a, **k: _fake_df(n=100),
    )
    monkeypatch.setattr(
        "scripts.backtest_harmonic_lib.walk_forward",
        lambda df, s, i, **kw: [_fake_backtest_record()],
    )
    rc = main([
        "--no-write", "--silent",
        "--symbol", "BTCUSDT", "--interval", "1d", "--days", "60",
        "--window", "20", "--step", "1", "--horizon", "15",
    ])
    assert rc == 0


def test_main_writes_artifacts_under_default_out_dir(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        lambda *a, **k: _fake_df(n=100),
    )
    monkeypatch.setattr(
        "scripts.backtest_harmonic_lib.walk_forward",
        lambda df, s, i, **kw: [_fake_backtest_record()],
    )
    # Use tmp_path as the out-dir via CLI arg
    rc = main([
        "--silent",
        "--out-dir", str(tmp_path),
        "--symbol", "BTCUSDT", "--interval", "1d", "--days", "60",
        "--window", "20", "--step", "1", "--horizon", "15",
    ])
    assert rc == 0
    # CSV + leaderboard written
    csv_files = list(tmp_path.glob("*.csv"))
    json_files = list(tmp_path.glob("*_leaderboard.json"))
    assert len(csv_files) == 1
    assert len(json_files) == 1


def test_main_prints_summary_when_not_silent(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        lambda *a, **k: _fake_df(n=100),
    )
    monkeypatch.setattr(
        "scripts.backtest_harmonic_lib.walk_forward",
        lambda df, s, i, **kw: [_fake_backtest_record()],
    )
    rc = main([
        "--no-write",
        "--out-dir", str(tmp_path),
        "--symbol", "BTCUSDT", "--interval", "1d", "--days", "60",
        "--window", "20", "--step", "1", "--horizon", "15",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    # Without --silent, prints the summary line.
    assert "signals" in captured.out
    assert "bench_total" in captured.out


def test_main_prints_will_create_out_dir_hint(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    new_dir = tmp_path / "fresh"
    monkeypatch.setattr(
        "app.infra.historical_data.fetch_historical_data",
        lambda *a, **k: _fake_df(n=100),
    )
    monkeypatch.setattr(
        "scripts.backtest_harmonic_lib.walk_forward",
        lambda df, s, i, **kw: [],
    )
    # out_dir doesn't exist, no --silent, no --no-write → "will create" hint on stderr.
    rc = main([
        "--out-dir", str(new_dir),
        "--symbol", "BTCUSDT", "--interval", "1d", "--days", "60",
        "--window", "20", "--step", "1", "--horizon", "15",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "does not exist yet" in captured.err