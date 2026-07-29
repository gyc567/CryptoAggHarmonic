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


def _make_candle_data(closes=(100.0, 101.0, 102.0), n=None):
    close_series = list(closes)
    if n is not None:
        # Build a 600-bar synthetic series (rising, with a hammer tail) so the
        # v2 forming view has realistic data to evaluate against.
        close_series = [100.0 + i * 0.2 for i in range(n)]
    df = pd.DataFrame(
        {
            "dts": pd.date_range("2026-01-01", periods=len(close_series), freq="D"),
            "open": close_series,
            "high": close_series,
            "low": close_series,
            "close": close_series,
            "volume": [1.0] * len(close_series),
        }
    )
    # close_time is required by the v2 staleness filter. Use a stable epoch
    # series aligned with the dts column (1d granularity).
    df["close_time"] = (df["dts"].astype("int64") // 10**9).astype("int64")
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
            market="binance",
            symbol="BTCUSDT",
            interval="1d",
            analysis_type="forming",
            limit_to=10,
            percent_complete=0.8,
            candles=1000,
            fingerprint="abc",
        )
        assert cache.make_key(**kwargs) == cache.make_key(**kwargs)

    def test_differs_on_params_and_fingerprint(self, cache):
        base = dict(
            market="binance",
            symbol="BTCUSDT",
            interval="1d",
            analysis_type="forming",
            limit_to=10,
            percent_complete=0.8,
            candles=1000,
            fingerprint="abc",
        )
        key = cache.make_key(**base)
        assert cache.make_key(**{**base, "symbol": "ETHUSDT"}) != key
        assert cache.make_key(**{**base, "fingerprint": "xyz"}) != key
        assert cache.make_key(**{**base, "analysis_type": "formed"}) != key


class TestSetGet:
    def test_roundtrip_with_chart_url(self, cache):
        cache.set(
            "k1",
            '{"a": 1}',
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
        legacy_payload = json.dumps(
            {
                "analysis_json": '{"a": "legacy"}',
                "chart_png_b64": base64.b64encode(b"old-bytes").decode(),
            }
        )
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

        assert calls["n"] == 1  # 检测只跑一次
        assert render_calls["n"] == 1  # 图表只渲染一次
        assert first.status == Status.COMPLETED
        assert second.status == Status.COMPLETED
        # Cache stores chart URL/path (no re-distribute on hit), so the
        # second response reuses the first run's URL/path verbatim.
        assert second.chart.url == first.chart.url
        assert second.chart.path == first.chart.path
        assert first.analysis_id != second.analysis_id
        assert second.technical_result.pattern_family == "XABCD"


# --- v2 forming/formed dual-path cache integration -----------------------------


class _Pattern:
    """Stand-in for a pyharmonics pattern (extract_candidates reads .y/.x/etc)."""

    def __init__(self, name, y, completion_min, completion_max, bullish=True, x=None):
        self.name = name
        self.y = y
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else [0, 10, 20, 580, 599]


class TestFormingCacheIntegration:
    """End-to-end: v2 forming view populates on first call, cached on second."""

    def _patch_common(self, monkeypatch, detection_result):
        monkeypatch.setattr(
            "app.services.analysis.fetch_market_data",
            lambda **kwargs: _make_candle_data(n=600),
        )
        detect_calls = {"n": 0}

        def fake_detect(**kwargs):
            detect_calls["n"] += 1
            return detection_result

        monkeypatch.setattr("app.services.analysis.detect_patterns", fake_detect)
        monkeypatch.setattr(
            AnalysisOrchestrator,
            "_build_trade_signal",
            staticmethod(lambda *a, **k: None),
        )
        return detect_calls

    def test_forming_candidates_cached_on_second_call(self, monkeypatch):
        forming = _Pattern(
            "gartley-382-0",
            [95.0, 110.0, 100.0, 107.0, 103.0],
            221.0,
            222.0,
            bullish=True,
        )
        detection = {
            "position": SimpleNamespace(side="long"),
            "patterns": {},
            "divergences": {},
            "raw_assessment": {
                "forming": {"XABCD": [forming]},
                "patterns": {"XABCD": []},
            },
        }
        calls = self._patch_common(monkeypatch, detection)
        monkeypatch.setattr(
            "app.services.analysis.render_chart",
            lambda det, dpi=150: (b"png", ChartMeta(format="png", width=600, height=300)),
        )
        monkeypatch.setattr(
            "app.services.analysis.save_chart_locally",
            lambda analysis_id, image_bytes: f"/fake/{analysis_id}.png",
        )

        cache = AnalysisCache(redis_url="")
        orch = AnalysisOrchestrator(cache=cache)
        from app.domain.enums import AnalysisType

        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.H4,
            analysis_type=AnalysisType.FORMING,
            limit_to=5,
            percent_complete=0.8,
            candles=600,
        )
        first = orch.analyze(req)
        second = orch.analyze(req)

        # Detection runs once (cached after).
        assert calls["n"] == 1
        # Both responses carry the forming view.
        assert len(first.forming_candidates) == 1
        assert len(second.forming_candidates) == 1
        # Same pattern name from both (proves cache hit returned the list).
        assert first.forming_candidates[0]["pattern_name"] == "gartley-382-0"
        assert second.forming_candidates[0]["pattern_name"] == "gartley-382-0"
        # tradable + macro + width_pct built into the dict.
        assert "tradable" in first.forming_candidates[0]
        assert "macro" in first.forming_candidates[0]
