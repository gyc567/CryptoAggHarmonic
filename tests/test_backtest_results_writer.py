"""Unit tests for scripts/run_backtest.py — results writer and history loader."""
import json
import pathlib

import pandas as pd
import pytest

from scripts.run_backtest import _load_history, _slice_range, write_results

SAMPLE_RESULT = {
    "run_id": "run_test",
    "timestamp": "2026-08-10T00:00:00Z",
    "symbols": ["BTC/USDT"],
    "interval": "1h",
    "total_signals": 5,
    "aggregated": {"wins": 3, "losses": 2, "win_rate": 0.6},
    "records": [],
}


def test_write_results_creates_file(tmp_path):
    p = tmp_path / "results.json"
    write_results(SAMPLE_RESULT, p)
    data = json.loads(p.read_text())
    assert data["version"] == 1
    assert len(data["runs"]) == 1
    assert data["runs"][0]["run_id"] == "run_test"
    assert data["last_updated"] == SAMPLE_RESULT["timestamp"]


def test_write_results_appends(tmp_path):
    existing = {"version": 1, "last_updated": "2026-08-01", "runs": [{"run_id": "run_1"}]}
    p = tmp_path / "results.json"
    p.write_text(json.dumps(existing))
    write_results(SAMPLE_RESULT, p)
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 2
    assert data["last_updated"] == "2026-08-10T00:00:00Z"
    assert data["runs"][1]["run_id"] == "run_test"


def test_load_history_from_cache(tmp_path, monkeypatch):
    """Cached parquet is loaded without hitting the network."""
    from scripts import run_backtest as mod

    cache = tmp_path / "BTCUSDT_1h.parquet"
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1.0, 2.0],
            "close_time": [1704067200000, 1704070800000],
        }
    )
    df["dts"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df.to_parquet(cache)

    # Point the managed-cache lookup at tmp_path via a fake ROOT.
    managed_root = tmp_path / "data" / "backtest" / "binance" / "BTCUSDT"
    managed_root.mkdir(parents=True, exist_ok=True)
    df.to_parquet(managed_root / "1h.parquet")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RESULT_DIR", tmp_path / "data")
    loaded = _load_history("BTC/USDT", "1h", "2024-01-01", "2026-01-01")
    assert len(loaded) == 2
    assert list(loaded.columns) == ["open", "high", "low", "close", "volume", "close_time", "dts"]


def test_slice_range_filters_by_dates():
    df = pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [102.0] * 5,
            "low": [99.0] * 5,
            "close": [101.0] * 5,
            "volume": [1.0] * 5,
            "close_time": [1704067200000 + i * 3600000 for i in range(5)],
        }
    )
    df["dts"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    sliced = _slice_range(df, "2024-01-01", "2024-01-01T03:00:00")
    assert len(sliced) == 3  # rows at 00:00, 01:00, 02:00 (03:00 excluded)


def test_load_history_no_cache_raises_http_error(monkeypatch, tmp_path):
    """Empty cache dir with unreachable network raises httpx error."""
    from scripts import run_backtest as mod

    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RESULT_DIR", tmp_path)
    monkeypatch.setattr(httpx, "Client", _boom)
    with pytest.raises(Exception):
        _load_history("BTC/USDT", "1h", "2024-01-01", "2026-01-01")
