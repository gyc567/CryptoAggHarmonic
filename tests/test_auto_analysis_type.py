"""Tests for the AUTO analysis type (docs/plans/auto-analysis-type-plan.md)."""
from unittest.mock import MagicMock, patch

import pytest

from app.domain.enums import AnalysisType
from app.domain.signals import Candidate, Signal, SignalTarget, resolve_analysis_type
from app.domain.validators import validate_analysis_type
from app.infra.pyharmonics_adapter import detect_patterns


def make_signal(formed: bool) -> Signal:
    target = SignalTarget(
        label="TP1", price=120.0, fib_basis="AD 38.2% retrace",
        close_pct=50, move_stop_to="breakeven",
    )
    return Signal(
        status="confirmed", grade="A", direction="long",
        pattern_name="gartley", family="XABCD", formed=formed,
        entry_zone=(108.0, 112.0), entry_reference=110.0,
        stop_loss=99.0, stop_basis="X/PRZ invalidation - 0.5*ATR",
        stop_level="standard",
        invalidation_point=99.5,
        targets=(target,), net_rr_tp1=1.2, net_rr_tp2=2.4,
        confluence_score=80,
    )


class TestAutoEnum:
    def test_auto_value(self):
        assert AnalysisType.AUTO.value == "auto"
        assert AnalysisType("auto") is AnalysisType.AUTO

    def test_validator_accepts_auto(self):
        assert validate_analysis_type("auto") is AnalysisType.AUTO

    def test_validator_still_rejects_garbage(self):
        from app.api.errors import AppError
        with pytest.raises(AppError):
            validate_analysis_type("not-a-type")

    def test_markets_includes_auto(self):
        values = [a.value for a in AnalysisType]
        assert "auto" in values
        assert "forming" in values


class TestResolveAnalysisType:
    def test_no_signal_returns_none(self):
        assert resolve_analysis_type(None) is None

    def test_formed_signal(self):
        assert resolve_analysis_type(make_signal(formed=True)) == "formed"

    def test_forming_signal(self):
        assert resolve_analysis_type(make_signal(formed=False)) == "forming"


class TestDetectPatternsAutoGate:
    def _make_mocks(self):
        mock_candle = MagicMock()
        mock_candle.df = MagicMock()
        mock_candle.symbol = "BTCUSDT"
        mock_candle.interval = "1d"
        empty = {"XABCD": [], "ABCD": [], "ABC": []}
        return mock_candle, empty

    def _run(self, analysis_type):
        mock_candle, empty = self._make_mocks()
        with patch("app.infra.pyharmonics_adapter.OHLCTechnicals"), \
             patch("app.infra.pyharmonics_adapter.HarmonicSearch") as hs_cls, \
             patch("app.infra.pyharmonics_adapter.DivergenceSearch") as div_cls, \
             patch("app.infra.pyharmonics_adapter.HarmonicPlotter"):
            hs = hs_cls.return_value
            hs.XABCD, hs.ABCD, hs.ABC = "XABCD", "ABCD", "ABC"
            hs.get_patterns.return_value = empty
            div_cls.return_value.get_patterns.return_value = {}
            detect_patterns(mock_candle, analysis_type=analysis_type)
            return hs

    def test_auto_runs_forming_scan(self):
        hs = self._run("auto")
        hs.forming.assert_called_once()

    def test_forming_runs_forming_scan(self):
        hs = self._run("forming")
        hs.forming.assert_called_once()

    def test_formed_skips_forming_scan(self):
        hs = self._run("formed")
        hs.forming.assert_not_called()

    def test_divergence_skips_forming_scan(self):
        hs = self._run("divergence")
        hs.forming.assert_not_called()


class TestOrchestratorResolvedType:
    """End-to-end: resolved_type lands in the API-facing TechnicalResult."""

    def _orchestrator(self):
        from app.services.analysis import AnalysisOrchestrator
        return AnalysisOrchestrator(prompt_context={})

    def _request(self, analysis_type):
        from app.domain.schemas import AnalyzeRequest
        from app.domain.enums import Market, Interval
        return AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            analysis_type=analysis_type,
        )

    def _detection(self):
        return {
            "position": MagicMock(),
            "patterns": {"family": "XABCD"},
            "divergences": {},
        }

    def test_auto_request_kept_resolved_type_set(self):
        orch = self._orchestrator()
        signal = make_signal(formed=True)
        with patch("app.services.analysis.fetch_market_data", return_value=MagicMock()), \
             patch("app.services.analysis.detect_patterns", return_value=self._detection()), \
             patch.object(orch, "_build_trade_signal", return_value=signal):
            result = orch.analyze(self._request(AnalysisType.AUTO))
        assert result.analysis_type == AnalysisType.AUTO
        assert result.technical_result.resolved_type == "formed"

    def test_no_signal_resolved_type_null(self):
        orch = self._orchestrator()
        with patch("app.services.analysis.fetch_market_data", return_value=MagicMock()), \
             patch("app.services.analysis.detect_patterns", return_value=self._detection()), \
             patch.object(orch, "_build_trade_signal", return_value=None):
            result = orch.analyze(self._request(AnalysisType.AUTO))
        assert result.analysis_type == AnalysisType.AUTO
        assert result.technical_result.resolved_type is None

    def test_forming_signal_resolved_forming(self):
        orch = self._orchestrator()
        signal = make_signal(formed=False)
        with patch("app.services.analysis.fetch_market_data", return_value=MagicMock()), \
             patch("app.services.analysis.detect_patterns", return_value=self._detection()), \
             patch.object(orch, "_build_trade_signal", return_value=signal):
            result = orch.analyze(self._request(AnalysisType.FORMED))
        assert result.analysis_type == AnalysisType.FORMED
        assert result.technical_result.resolved_type == "forming"
