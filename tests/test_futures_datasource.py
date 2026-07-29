"""Phase 1: 独立验证 Binance Futures REST 接口连通性."""

import time

import pytest


class TestFuturesDataSource:
    """验证 Binance Futures 正式网 REST 接口"""

    def test_get_candles_returns_data(self):
        """正式网 REST /fapi/v1/klines 返回正确数据"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        data = source.get_candles(limit=10)

        df = data.df
        assert len(df) == 10, f"Expected 10 rows, got {len(df)}"
        assert all(df["close"] > 0), "All close prices should be positive"
        assert all(df["volume"] >= 0), "All volumes should be non-negative"
        assert all(df["high"] >= df["low"]), "High should be >= low"
        assert all(df["high"] >= df["open"]), "High should be >= open"
        assert all(df["high"] >= df["close"]), "High should be >= close"
        assert all(df["low"] <= df["open"]), "Low should be <= open"
        assert all(df["low"] <= df["close"]), "Low should be <= close"
        # K线应按时间升序
        open_times = df["open_time"].tolist()
        for i in range(1, len(open_times)):
            assert open_times[i] > open_times[i - 1], f"Candle {i} time should be > candle {i-1} time"

    def test_get_candles_latest_close_time(self):
        """最新K线收盘时间合理（接近当前时间）"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        close_time = source.get_latest_close_time()

        assert close_time is not None, "Should return close time"
        now_ms = int(time.time() * 1000)
        # 1m K线关闭时间应在当前时间前后 2min 内
        assert abs(now_ms - close_time) < 120_000, f"Close time {close_time} differs too much from now {now_ms}"

    def test_websocket_url_format(self):
        """WebSocket URL 格式正确"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        assert source.websocket_url == "wss://fstream.binance.com/ws/btcusdt@kline_1m"

    def test_futures_candle_data_websocket_url(self):
        """FuturesCandleData 也有 websocket_url 属性"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        data = source.get_candles(limit=1)
        assert data.websocket_url == "wss://fstream.binance.com/ws/btcusdt@kline_1m"
        assert data.symbol == "BTCUSDT"
        assert data.interval == "1m"

    def test_symbol_normalized_to_uppercase(self):
        """symbol 自动转大写"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("btcusdt", "1h")
        assert source.symbol == "BTCUSDT"
        assert "btcusdt" in source.websocket_url

    def test_invalid_symbol_raises(self):
        """无效交易对返回错误"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("INVALIDPAIR", "1m")
        with pytest.raises((RuntimeError, ValueError)):
            source.get_candles(limit=1)

    @pytest.mark.parametrize("interval", ["1m", "5m", "15m", "1h", "4h", "1d"])
    def test_different_intervals(self, interval):
        """各周期K线都能正常获取"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", interval)
        data = source.get_candles(limit=5)
        df = data.df
        assert len(df) == 5, f"Interval {interval}: expected 5 rows, got {len(df)}"
        # 验证时间间隔合理
        if len(df) >= 2:
            diff = df["open_time"].iloc[1] - df["open_time"].iloc[0]
            expected = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
            assert diff == expected[interval], f"Interval {interval}: expected gap {expected[interval]}, got {diff}"

    def test_interval_case_insensitive(self):
        """interval 大小写不敏感"""
        from app.infra.futures_data_source import FuturesDataSource

        source_lower = FuturesDataSource("BTCUSDT", "1H")
        source_upper = FuturesDataSource("BTCUSDT", "1h")
        data_lower = source_lower.get_candles(limit=1)
        data_upper = source_upper.get_candles(limit=1)
        assert data_lower.df["open_time"].iloc[0] == data_upper.df["open_time"].iloc[0]

    def test_get_latest_close_time_returns_int(self):
        """get_latest_close_time 返回整数时间戳"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        result = source.get_latest_close_time()
        assert result is not None
        assert isinstance(result, int)

    def test_multiple_symbols(self):
        """不同交易对都能获取数据"""
        from app.infra.futures_data_source import FuturesDataSource

        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        for sym in symbols:
            source = FuturesDataSource(sym, "1h")
            data = source.get_candles(limit=3)
            assert len(data.df) == 3, f"Symbol {sym}: expected 3 rows"
            assert all(data.df["close"] > 0)

    def test_df_columns(self):
        """DataFrame 包含所有必要列"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        data = source.get_candles(limit=1)
        df = data.df
        required_cols = ["open_time", "open", "high", "low", "close", "volume", "close_time"]
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_df_has_dts_index(self):
        """DataFrame 有 dts 索引（pyharmonics 兼容）"""
        from app.infra.futures_data_source import FuturesDataSource

        source = FuturesDataSource("BTCUSDT", "1m")
        data = source.get_candles(limit=5)
        assert data.df.index.name == "dts" or "dts" in data.df.columns, "DataFrame should have dts index or column"
