"""Tests for app.infra.analysis_cache and orchestrator cache integration."""
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.domain.enums import Interval, Market, Status
from app.domain.schemas import AnalyzeRequest, ChartMeta
from app.infra.analysis_cache import AnalysisCache
from app.services.analysis import AnalysisOrchestrator


def _make_candle_data(closes=(100.0, 101.0, 102.0)):
    df = pd.DataFrame(
        {
            "dts": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )
    return SimpleNamespace(df=df, symbol="BTCUSDT", interval="1d")


def _make_request() -> AnalyzeRequest:
    return AnalyzeRequest(market=Market.BINANCE, symbol="BTCUSDT", interval=Interval.D1)


@pytest.fixture
def cache():
    return AnalysisCache(redis_url="")


class TestFingerprint:
    def test_stable_for_same_data(self):
        cd = _make_candle_data()
        assert AnalysisCache.candle_fingerprint(cd) == AnalysisCache.candle_fingerprint(cd)

    def test_changes_when_last_close_changes(self):
        fp1 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 102.0)))
        fp2 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 103.0)))
        assert fp1 != fp2

    def test_changes_when_new_candle_appears(self):
        fp1 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0)))
        fp2 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 102.0)))
        assert fp1 != fp2

    def test_empty_dataframe_does_not_raise(self):
        cd = SimpleNamespace(df=pd.DataFrame(columns=["dts", "close"]))
        assert AnalysisCache.candle_fingerprint(cd)

    def test_missing_columns_fallback(self):
        cd = SimpleNamespace(df=pd.DataFrame({"foo": [1, 2]}))
        assert AnalysisCache.candle_fingerprint(cd)

    def test_non_dataframe_objects_get_distinct_fingerprints(self):
        # MagicMock 等 Mock 对象的 len() 默认为 0，不能被误判为空数据而碰撞
        fp1 = AnalysisCache.candle_fingerprint(SimpleNamespace(df=MagicMock()))
        fp2 = AnalysisCache.candle_fingerprint(SimpleNamespace(df=MagicMock()))
        assert fp1 != fp2


class TestMakeKey:
    def test_same_inputs_same_key(self, cache):
        kwargs = dict(
            market="binance", symbol="BTCUSDT", interval="1d", analysis_type="forming",
            limit_to=10, percent_complete=0.8, candles=1000, fingerprint="abc",
        )
        assert cache.make_key(**kwargs) == cache.make_key(**kwargs)

    def test_differs_on_params_and_fingerprint(self, cache):
        base = dict(
            market="binance", symbol="BTCUSDT", interval="1d", analysis_type="forming",
            limit_to=10, percent_complete=0.8, candles=1000, fingerprint="abc",
        )
        key = cache.make_key(**base)
        assert cache.make_key(**{**base, "symbol": "ETHUSDT"}) != key
        assert cache.make_key(**{**base, "fingerprint": "xyz"}) != key
        assert cache.make_key(**{**base, "analysis_type": "formed"}) != key


class TestSetGet:
    def test_roundtrip_with_chart_url(self, cache):
        cache.set(
            "k1", '{"a": 1}',
            chart_url="/api/charts/abc.png",
            chart_path="charts/abc.png",
        )
        entry = cache.get("k1")
        assert entry["analysis_json"] == '{"a": 1}'
        assert entry["chart_url"] == "/api/charts/abc.png"
        assert entry["chart_path"] == "charts/abc.png"

    def test_roundtrip_without_chart(self, cache):
        cache.set("k2", '{"a": 2}')
        entry = cache.get("k2")
        assert entry["analysis_json"] == '{"a": 2}'
        assert entry["chart_url"] is None
        assert entry["chart_path"] is None

    def test_miss_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self):
        cache = AnalysisCache(redis_url="", ttl_seconds=1)
        cache.set("k3", '{"a": 3}')
        future = time.time() + 2
        original_time = time.time
        try:
            time.time = lambda: future
            assert cache.get("k3") is None
        finally:
            time.time = original_time

    def test_disabled_cache(self, monkeypatch):
        monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "false")
        cache = AnalysisCache(redis_url="")
        cache.set("k4", '{"a": 4}')
        assert cache.get("k4") is None

    def test_legacy_chart_png_b64_payload_is_decoded_as_none(self, cache):
        """Cache entries written by the previous version stored chart_png_b64;
        on read we must not crash and must surface both refs as None.
        """
        legacy_payload = json.dumps({
            "analysis_json": '{"a": "legacy"}',
            "chart_png_b64": base64.b64encode(b"old-bytes").decode(),
        })
        # Bypass set() so we can write the legacy shape.
        cache._memory.set("legacy", legacy_payload)
        entry = cache.get("legacy")
        assert entry is not None
        assert entry["analysis_json"] == '{"a": "legacy"}'
        assert entry["chart_url"] is None
        assert entry["chart_path"] is None


class TestOrchestratorCacheIntegration:
    """End-to-end: second identical analyze() call must skip all heavy work."""

    def _patch_common(self, monkeypatch, detection_result):
        monkeypatch.setattr(
            "app.services.analysis.fetch_market_data",
            lambda **kwargs: _make_candle_data(),
        )
        detect_calls = {"n": 0}

        def fake_detect(**kwargs):
            detect_calls["n"] += 1
            return detection_result

        monkeypatch.setattr("app.services.analysis.detect_patterns", fake_detect)
        return detect_calls

    def test_no_result_cached(self, monkeypatch, tmp_path):
        detection = {"position": None, "patterns": {}, "divergences": {}}
        calls = self._patch_common(monkeypatch, detection)

        orchestrator = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        first = orchestrator.analyze(_make_request())
        second = orchestrator.analyze(_make_request())

        assert calls["n"] == 1  # detect_patterns 只跑一次
        assert first.status == Status.NO_RESULT
        assert second.status == Status.NO_RESULT
        assert first.analysis_id != second.analysis_id  # 每次新 ID

    def test_completed_cached_with_chart(self, monkeypatch):
        position = MagicMock(strike=100.0, stop=95.0, targets=[110.0])
        detection = {
            "position": position,
            "patterns": {"family": "XABCD", "direction": "bullish"},
            "divergences": {},
        }
        calls = self._patch_common(monkeypatch, detection)
        monkeypatch.setattr(AnalysisOrchestrator, "_build_trade_signal", staticmethod(lambda *a, **k: None))

        render_calls = {"n": 0}

        def fake_render(det, dpi=150):
            render_calls["n"] += 1
            return b"png-bytes", ChartMeta(format="png", width=600, height=300)

        monkeypatch.setattr("app.services.analysis.render_chart", fake_render)
        monkeypatch.setattr(
            "app.services.analysis.save_chart_locally",
            lambda analysis_id, image_bytes: f"/fake/{analysis_id}.png",
        )

        orchestrator = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        first = orchestrator.analyze(_make_request())
        second = orchestrator.analyze(_make_request())

        assert calls["n"] == 1   # 检测只跑一次
        assert render_calls["n"] == 1  # 图表只渲染一次
        assert first.status == Status.COMPLETED
        assert second.status == Status.COMPLETED
        # Cache stores chart URL/path (no re-distribute on hit), so the
        # second response reuses the first run's URL/path verbatim.
        assert second.chart.url == first.chart.url
        assert second.chart.path == first.chart.path
        assert first.analysis_id != second.analysis_id
        assert second.technical_result.pattern_family == "XABCD"
