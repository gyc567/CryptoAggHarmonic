"""analyze_harmonic tool for vibe agent."""

import logging

from app.domain.enums import AnalysisType, Interval, Market
from app.domain.schemas import AnalyzeRequest
from app.services.analysis import AnalysisOrchestrator
from app.services.vibe.tools.base import Tool, ToolOutput, ToolRuntime

logger = logging.getLogger(__name__)


class AnalyzeHarmonicTool(Tool):
    """Run harmonic pattern and divergence detection for an asset."""

    name = "analyze_harmonic"
    description = "对指定标的运行谐波形态与背离检测，返回方向、形态、入场、止损、目标价等结构化结果。"
    input_schema = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "enum": ["binance", "yahoo"],
                "description": "市场数据源",
            },
            "symbol": {
                "type": "string",
                "description": "标的代码，如 BTCUSDT、AAPL",
            },
            "interval": {
                "type": "string",
                "enum": ["15m", "1h", "4h", "1d", "1w"],
                "description": "分析周期",
            },
            "analysis_type": {
                "type": "string",
                "enum": ["auto", "forming", "formed", "divergence"],
                "description": "分析类型，默认为 auto",
            },
            "candles": {
                "type": "integer",
                "default": 1000,
                "description": "用于分析的 K 线数量",
            },
        },
        "required": ["market", "symbol", "interval"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "market": {"type": "string"},
            "symbol": {"type": "string"},
            "interval": {"type": "string"},
            "analysis_id": {"type": "string"},
            "direction": {"type": "string"},
            "pattern_family": {"type": "string"},
            "pattern_type": {"type": "string"},
            "confidence": {"type": "string"},
            "entry_price": {"type": "number"},
            "stop_loss": {"type": "number"},
            "target_price": {"type": "number"},
            "risk_reward_ratio": {"type": "number"},
            "signal": {"type": "object"},
            "chart_url": {"type": "string"},
            "interpretation_summary": {"type": "string"},
        },
    }

    def __init__(self, orchestrator: AnalysisOrchestrator):
        self.orchestrator = orchestrator

    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        market = input.get("market", "binance")
        symbol = input.get("symbol", "").upper().strip()
        interval = input.get("interval", "1h")
        analysis_type = input.get("analysis_type", "auto")
        candles = input.get("candles", 1000)

        try:
            request = AnalyzeRequest(
                market=Market(market),
                symbol=symbol,
                interval=Interval(interval),
                analysis_type=AnalysisType(analysis_type),
                candles=candles,
            )
        except Exception as e:
            return ToolOutput.invalid_input(f"参数错误: {e}")

        try:
            result = self.orchestrator.analyze(
                request,
                user_id=runtime.user_id,
                analysis_id=None,
            )
        except Exception as e:
            logger.exception("analyze_harmonic failed")
            return ToolOutput.error(f"分析失败: {e}", code="ANALYSIS_FAILED")

        tech = result.technical_result or {}
        signal = tech.signal
        signal_dict = signal.model_dump() if signal else None

        data = {
            "schema_version": "analyze_harmonic_output_v1",
            "status": "completed",
            "market": market,
            "symbol": symbol,
            "interval": interval,
            "analysis_id": result.analysis_id,
            "direction": tech.direction,
            "pattern_family": tech.pattern_family,
            "pattern_type": tech.pattern_type,
            "confidence": tech.confidence,
            "entry_price": tech.entry_price,
            "stop_loss": tech.stop_loss,
            "target_price": tech.target_price,
            "risk_reward_ratio": tech.risk_reward_ratio,
            "signal": signal_dict,
            "chart_url": result.chart.url if result.chart else None,
            "interpretation_summary": (result.interpretation.summary if result.interpretation else None),
        }

        summary = self._build_summary(data)
        return ToolOutput.success(data, summary=summary)

    def _build_summary(self, data: dict) -> str:
        direction = data.get("direction") or "unknown"
        pattern = data.get("pattern_type") or "none"
        rr = data.get("risk_reward_ratio")
        rr_text = f"RR {rr:.2f}" if rr else "RR unknown"
        return f"{data['symbol']} {data['interval']} 检测到 {direction} {pattern}，{rr_text}"
