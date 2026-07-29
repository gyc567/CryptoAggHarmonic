"""Vibe tool registry and built-in tools."""

from app.services.analysis import AnalysisOrchestrator
from app.services.vibe.tools.analyze_harmonic import AnalyzeHarmonicTool
from app.services.vibe.tools.backtest_signal import BacktestSignalTool
from app.services.vibe.tools.build_trade_signal import BuildTradeSignalTool
from app.services.vibe.tools.explain_market import ExplainMarketTool
from app.services.vibe.tools.position_check import PositionCheckTool
from app.services.vibe.tools.registry import ToolRegistry
from app.services.vibe.tools.save_to_journal import SaveToJournalTool


def create_default_registry(orchestrator: AnalysisOrchestrator) -> ToolRegistry:
    """Create and register all built-in vibe tools."""
    registry = ToolRegistry()
    registry.register(AnalyzeHarmonicTool(orchestrator))
    registry.register(BuildTradeSignalTool(orchestrator))
    registry.register(PositionCheckTool())
    registry.register(BacktestSignalTool())
    registry.register(ExplainMarketTool())
    registry.register(SaveToJournalTool())
    return registry


__all__ = [
    "ToolRegistry",
    "create_default_registry",
    "AnalyzeHarmonicTool",
    "BuildTradeSignalTool",
    "PositionCheckTool",
    "BacktestSignalTool",
    "ExplainMarketTool",
    "SaveToJournalTool",
]
