"""build_trade_signal tool for vibe agent."""

from app.domain.enums import AnalysisType, Interval, Market
from app.domain.schemas import AnalyzeRequest
from app.services.analysis import AnalysisOrchestrator
from app.services.vibe.tools.base import Tool, ToolOutput, ToolRuntime


class BuildTradeSignalTool(Tool):
    """Build a structured trade signal for an asset."""

    name = "build_trade_signal"
    description = "基于谐波形态检测生成结构化的交易信号，包含方向、入场区、止损、目标价和仓位建议。"
    input_schema = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "enum": ["binance", "yahoo"],
            },
            "symbol": {"type": "string"},
            "interval": {
                "type": "string",
                "enum": ["15m", "1h", "4h", "1d", "1w"],
            },
            "analysis_type": {
                "type": "string",
                "enum": ["auto", "forming", "formed", "divergence"],
            },
        },
        "required": ["market", "symbol", "interval"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "signal": {"type": "object"},
        },
    }

    def __init__(self, orchestrator: AnalysisOrchestrator):
        self.orchestrator = orchestrator

    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        market = input.get("market", "binance")
        symbol = input.get("symbol", "").upper().strip()
        interval = input.get("interval", "1h")
        analysis_type = input.get("analysis_type", "auto")

        try:
            request = AnalyzeRequest(
                market=Market(market),
                symbol=symbol,
                interval=Interval(interval),
                analysis_type=AnalysisType(analysis_type),
            )
        except Exception as e:
            return ToolOutput.invalid_input(f"参数错误: {e}")

        try:
            result = self.orchestrator.analyze(request, user_id=runtime.user_id, analysis_id=None)
        except Exception as e:
            return ToolOutput.error(f"信号生成失败: {e}", code="SIGNAL_FAILED")

        signal = result.technical_result.signal if result.technical_result else None
        if not signal:
            return ToolOutput.success(
                {
                    "schema_version": "trade_signal_output_v1",
                    "status": "no_signal",
                    "signal": None,
                },
                summary=f"{symbol} 当前未生成明确交易信号",
            )

        data = {
            "schema_version": "trade_signal_output_v1",
            "status": "completed",
            "signal": signal.model_dump(),
        }
        return ToolOutput.success(
            data,
            summary=f"{symbol} 生成 {signal.direction} 信号，RR {signal.net_rr_tp1 or 'unknown'}",
        )
