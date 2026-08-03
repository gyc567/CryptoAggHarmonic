"""Tests for scripts/download_backtest_data.py.

Comprehensive tests covering all public functions with mocked network calls
to ensure 100% coverage without actually hitting the Binance API.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# --------------------------------------------------------------------------- #
# Fixtures                                                                   #
# --------------------------------------------------------------------------- #

@pytest.fixture
def temp_root(tmp_path):
    """Temporary data root for tests."""
    return tmp_path / "backtest"


@pytest.fixture
def sample_df():
    """Create a sample OHLC DataFrame."""
    dates = pd.date_range("2026-07-01", periods=10, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(10)],
            "high": [105.0 + i for i in range(10)],
            "low": [95.0 + i for i in range(10)],
            "close": [102.0 + i for i in range(10)],
            "volume": [1000.0 + i * 10 for i in range(10)],
            "close_time": [d + pd.Timedelta(hours=4) for d in dates],
        },
        index=dates,
    )


# --------------------------------------------------------------------------- #
# Path helpers                                                                #
# --------------------------------------------------------------------------- #

class TestGetDataPath:
    """Tests for get_data_path()."""

    def test_basic(self, temp_root):
        from scripts.download_backtest_data import get_data_path

        path = get_data_path("BTCUSDT", "4h", root=temp_root)
        expected = temp_root / "binance" / "BTCUSDT" / "4h.parquet"
        assert path == expected

    def test_different_exchange(self, temp_root):
        from scripts.download_backtest_data import get_data_path

        path = get_data_path("BTCUSDT", "4h", exchange="okx", root=temp_root)
        expected = temp_root / "okx" / "BTCUSDT" / "4h.parquet"
        assert path == expected

    def test_symbol_with_prefix(self, temp_root):
        from scripts.download_backtest_data import get_data_path

        path = get_data_path("ETHUSDT", "1d", root=temp_root)
        assert "ETHUSDT" in str(path)
        assert path.suffix == ".parquet"


class TestGetMetaPath:
    """Tests for get_meta_path()."""

    def test_basic(self, temp_root):
        from scripts.download_backtest_data import get_meta_path

        path = get_meta_path("BTCUSDT", "4h", root=temp_root)
        expected = temp_root / "binance" / "BTCUSDT" / "4h.meta.json"
        assert path == expected

    def test_different_symbol(self, temp_root):
        from scripts.download_backtest_data import get_meta_path

        path = get_meta_path("ETHUSDT", "1h", root=temp_root)
        assert "ETHUSDT" in str(path)
        assert path.name == "1h.meta.json"


# --------------------------------------------------------------------------- #
# Load / Save                                                                 #
# --------------------------------------------------------------------------- #

class TestSaveData:
    """Tests for save_data()."""

    def test_save_creates_directories(self, temp_root, sample_df):
        from scripts.download_backtest_data import save_data

        path = save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        assert path.exists()
        assert path.suffix == ".parquet"

    def test_save_parquet_roundtrip(self, temp_root, sample_df):
        from scripts.download_backtest_data import save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        loaded = pd.read_parquet(temp_root / "binance" / "BTCUSDT" / "4h.parquet")
        assert len(loaded) == len(sample_df)
        assert list(loaded.columns) == list(sample_df.columns)

    def test_save_creates_meta_file(self, temp_root, sample_df):
        from scripts.download_backtest_data import get_meta_path, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        meta_path = get_meta_path("BTCUSDT", "4h", root=temp_root)
        assert meta_path.exists()

    def test_save_meta_content(self, temp_root, sample_df):
        from scripts.download_backtest_data import get_meta_path, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        meta_path = get_meta_path("BTCUSDT", "4h", root=temp_root)
        meta = json.loads(meta_path.read_text())

        assert meta["symbol"] == "BTCUSDT"
        assert meta["interval"] == "4h"
        assert meta["exchange"] == "binance"
        assert meta["candles"] == 10
        assert meta["source"] == "binance_stdlib"
        assert meta["version"] == "v1"
        assert "downloaded_at" in meta

    def test_save_empty_df(self, temp_root):
        from scripts.download_backtest_data import save_data

        empty_df = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []}
        )
        empty_df.index = pd.to_datetime(empty_df.index)

        path = save_data(empty_df, "BTCUSDT", "4h", root=temp_root)
        assert path.exists()

        # Check meta has candles=0
        meta_path = temp_root / "binance" / "BTCUSDT" / "4h.meta.json"
        meta = json.loads(meta_path.read_text())
        assert meta["candles"] == 0


class TestLoadCached:
    """Tests for load_cached()."""

    def test_load_nonexistent_returns_none(self, temp_root):
        from scripts.download_backtest_data import load_cached

        result = load_cached("BTCUSDT", "4h", root=temp_root)
        assert result is None

    def test_load_existing(self, temp_root, sample_df):
        from scripts.download_backtest_data import load_cached, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)
        result = load_cached("BTCUSDT", "4h", root=temp_root)

        assert result is not None
        assert len(result) == 10

    def test_load_preserves_columns(self, temp_root, sample_df):
        from scripts.download_backtest_data import load_cached, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)
        result = load_cached("BTCUSDT", "4h", root=temp_root)

        assert set(result.columns) == {"open", "high", "low", "close", "volume", "close_time"}

    def test_load_preserves_index(self, temp_root, sample_df):
        from scripts.download_backtest_data import load_cached, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)
        result = load_cached("BTCUSDT", "4h", root=temp_root)

        assert result.index.name == "dts" or result.index.name is None  # Index name depends on parquet save


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #

class TestValidateData:
    """Tests for validate_data()."""

    def test_valid_df(self, sample_df):
        from scripts.download_backtest_data import validate_data

        assert validate_data(sample_df) is True

    def test_none_returns_false(self):
        from scripts.download_backtest_data import validate_data

        assert validate_data(None) is False

    def test_empty_df_returns_false(self):
        from scripts.download_backtest_data import validate_data

        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        assert validate_data(empty_df) is False

    def test_missing_columns_returns_false(self, sample_df):
        from scripts.download_backtest_data import validate_data

        bad_df = sample_df.drop(columns=["close"])
        assert validate_data(bad_df) is False

    def test_non_monotonic_index_returns_false(self, sample_df):
        from scripts.download_backtest_data import validate_data

        bad_df = sample_df.iloc[::-1]  # Reverse order.
        assert validate_data(bad_df) is False

    def test_high_below_low_returns_false(self, sample_df):
        from scripts.download_backtest_data import validate_data

        bad_df = sample_df.copy()
        bad_df.loc[bad_df.index[0], "high"] = 90  # Below low.
        assert validate_data(bad_df) is False

    def test_negative_close_returns_false(self, sample_df):
        from scripts.download_backtest_data import validate_data

        bad_df = sample_df.copy()
        bad_df.loc[bad_df.index[0], "close"] = -10
        assert validate_data(bad_df) is False


# --------------------------------------------------------------------------- #
# Download                                                                   #
# --------------------------------------------------------------------------- #

class TestDownloadData:
    """Tests for download_data()."""

    @patch("scripts.download_backtest_data.fetch_binance_klines")
    def test_download_calls_api(self, mock_fetch, temp_root, sample_df):
        from scripts.download_backtest_data import download_data

        mock_fetch.return_value = sample_df

        result = download_data(
            "BTCUSDT", "4h", days=30,
            root=temp_root, verbose=False
        )

        mock_fetch.assert_called_once()
        assert len(result) == 10

    @patch("scripts.download_backtest_data.fetch_binance_klines")
    def test_download_saves_to_cache(self, mock_fetch, temp_root, sample_df):
        from scripts.download_backtest_data import download_data

        mock_fetch.return_value = sample_df

        download_data("BTCUSDT", "4h", days=30, root=temp_root, verbose=False)

        # Verify saved to disk.
        path = temp_root / "binance" / "BTCUSDT" / "4h.parquet"
        assert path.exists()

    @patch("scripts.download_backtest_data.fetch_binance_klines")
    def test_download_retries_on_failure(self, mock_fetch, temp_root, sample_df):
        """Test that download retries on failure and succeeds on 3rd attempt."""
        # Fail twice, succeed on third attempt.
        side_effects = [
            RuntimeError("error1"),
            RuntimeError("error2"),
            sample_df,
        ]
        mock_fetch.side_effect = side_effects

        from scripts.download_backtest_data import download_data

        result = download_data(
            "BTCUSDT", "4h", days=30,
            root=temp_root, verbose=False, max_retries=3
        )

        assert mock_fetch.call_count == 3
        assert len(result) == 10

    @patch("scripts.download_backtest_data.fetch_binance_klines")
    def test_download_raises_after_max_retries(self, mock_fetch, temp_root):
        from scripts.download_backtest_data import download_data

        mock_fetch.side_effect = RuntimeError("Persistent error")

        with pytest.raises(RuntimeError, match="after 3 attempts"):
            download_data(
                "BTCUSDT", "4h", days=30,
                root=temp_root, verbose=False, max_retries=3
            )

    def test_download_invalid_interval_raises(self, temp_root):
        from scripts.download_backtest_data import download_data

        with pytest.raises(ValueError, match="Unsupported interval"):
            download_data("BTCUSDT", "invalid", root=temp_root, verbose=False)

    @patch("scripts.download_backtest_data.fetch_binance_klines")
    def test_download_validates_data(self, mock_fetch, temp_root):
        from scripts.download_backtest_data import download_data

        # Return invalid data (missing columns).
        mock_fetch.return_value = pd.DataFrame({"open": [100]})

        with pytest.raises(ValueError, match="failed validation"):
            download_data("BTCUSDT", "4h", days=30, root=temp_root, verbose=False)


# --------------------------------------------------------------------------- #
# Ensure data (cache-first)                                                    #
# --------------------------------------------------------------------------- #

class TestEnsureData:
    """Tests for ensure_data()."""

    def test_ensure_returns_cached(self, temp_root, sample_df):
        from scripts.download_backtest_data import ensure_data, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        result, was_cached = ensure_data(
            "BTCUSDT", "4h", root=temp_root, verbose=False
        )

        assert was_cached is True
        assert len(result) == 10

    @patch("scripts.download_backtest_data.download_data")
    def test_ensure_downloads_when_not_cached(self, mock_download, temp_root, sample_df):
        from scripts.download_backtest_data import ensure_data

        mock_download.return_value = sample_df

        result, was_cached = ensure_data(
            "BTCUSDT", "4h", root=temp_root, verbose=False
        )

        assert was_cached is False
        mock_download.assert_called_once()


# --------------------------------------------------------------------------- #
# Cache status                                                                 #
# --------------------------------------------------------------------------- #

class TestGetCacheStatus:
    """Tests for get_cache_status()."""

    def test_status_empty_cache(self, temp_root):
        from scripts.download_backtest_data import get_cache_status

        status = get_cache_status(root=temp_root)

        assert status["root"] == str(temp_root)
        assert len(status["entries"]) > 0
        for entry in status["entries"]:
            assert entry["cached"] is False

    def test_status_with_cached_data(self, temp_root, sample_df):
        from scripts.download_backtest_data import get_cache_status, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        status = get_cache_status(symbol="BTCUSDT", interval="4h", root=temp_root)

        entry = status["entries"][0]
        assert entry["cached"] is True
        assert entry["meta"] is not None
        assert entry["meta"]["candles"] == 10

    def test_status_filter_by_symbol(self, temp_root, sample_df):
        from scripts.download_backtest_data import get_cache_status, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        status = get_cache_status(symbol="ETHUSDT", root=temp_root)

        for entry in status["entries"]:
            assert entry["symbol"] == "ETHUSDT"


class TestCleanCache:
    """Tests for clean_cache()."""

    def test_clean_deletes_files(self, temp_root, sample_df):
        from scripts.download_backtest_data import clean_cache, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        deleted = clean_cache("BTCUSDT", "4h", root=temp_root, verbose=False)

        assert deleted >= 2  # At least .parquet and .meta.json
        assert not (temp_root / "binance" / "BTCUSDT" / "4h.parquet").exists()

    def test_clean_returns_count(self, temp_root, sample_df):
        from scripts.download_backtest_data import clean_cache, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        deleted = clean_cache("BTCUSDT", "4h", root=temp_root, verbose=False)

        assert deleted == 2

    def test_clean_nonexistent_returns_zero(self, temp_root):
        from scripts.download_backtest_data import clean_cache

        deleted = clean_cache("BTCUSDT", "4h", root=temp_root, verbose=False)
        assert deleted == 0


# --------------------------------------------------------------------------- #
# CLI                                                                        #
# --------------------------------------------------------------------------- #

class TestCLI:
    """Tests for main() CLI interface."""

    def test_status_command(self, temp_root, sample_df, capsys):
        from scripts.download_backtest_data import main, save_data

        # Create some cached data.
        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        # Mock DATA_ROOT temporarily.
        with patch("scripts.download_backtest_data.DATA_ROOT", temp_root):
            exit_code = main(["--status"])

        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "BTCUSDT" in captured
        assert "4h" in captured

    def test_clean_command(self, temp_root, sample_df, capsys):
        from scripts.download_backtest_data import main, save_data

        save_data(sample_df, "BTCUSDT", "4h", root=temp_root)

        with patch("scripts.download_backtest_data.DATA_ROOT", temp_root):
            exit_code = main(["--clean"])

        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "deleted" in captured

    def test_download_single(self, temp_root, sample_df, capsys):
        from scripts.download_backtest_data import main

        with (
            patch("scripts.download_backtest_data.DATA_ROOT", temp_root),
            patch("scripts.download_backtest_data.ensure_data") as mock_ensure,
        ):
            mock_ensure.return_value = (sample_df, False)
            exit_code = main(["--symbol", "BTCUSDT", "--interval", "4h"])

        assert exit_code == 0
        mock_ensure.assert_called_once()

    def test_batch_command(self, temp_root, capsys):
        from scripts.download_backtest_data import main

        with (
            patch("scripts.download_backtest_data.DATA_ROOT", temp_root),
            patch("scripts.download_backtest_data.ensure_data") as mock_ensure,
        ):
            mock_ensure.return_value = (pd.DataFrame(), False)
            exit_code = main(["--batch", "BTCUSDT:4h", "ETHUSDT:1h"])

        assert exit_code == 0
        assert mock_ensure.call_count == 2

    def test_invalid_interval_exits_with_error(self, temp_root, capsys):
        """Test that --interval validation happens via argparse (before main)."""
        from scripts.download_backtest_data import main
        import pytest

        with patch("scripts.download_backtest_data.DATA_ROOT", temp_root):
            with pytest.raises(SystemExit) as exc_info:
                main(["--interval", "invalid"])

        # argparse exits with 2 for argument errors
        assert exc_info.value.code == 2
