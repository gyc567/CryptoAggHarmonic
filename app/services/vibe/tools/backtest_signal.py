"""backtest_signal tool for vibe agent (Phase 3)."""

import pandas as pd

from app.infra.historical_data import fetch_historical_data
from app.services.vibe.backtest_engine import compute_metrics, simulate_trades
from app.services.vibe.tools.base import Tool, ToolOutput, ToolRuntime


class BacktestSignalTool(Tool):
    """Backtest a trading signal over historical market data."""

    name = "backtest_signal"
    description = "对给定的交易信号在历史数据上做简化回测，支持 30/90/180/365 天默认模板或自定义区间（最大 365 天）。"
    input_schema = {
        "type": "object",
        "properties": {
            "market": {"type": "string", "enum": ["binance", "yahoo"]},
            "symbol": {"type": "string"},
            "interval": {"type": "string", "enum": ["15m", "1h", "4h", "1d", "1w"]},
            "direction": {"type": "string", "enum": ["long", "short"]},
            "entry_price": {"type": "number"},
            "stop_loss": {"type": "number"},
            "target_price": {"type": "number"},
            "lookback_days": {"type": "integer", "default": 90},
        },
        "required": ["market", "symbol", "interval", "direction"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "market": {"type": "string"},
            "symbol": {"type": "string"},
            "interval": {"type": "string"},
            "direction": {"type": "string"},
            "lookback_days": {"type": "integer"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "total_signals": {"type": "integer"},
            "win_count": {"type": "integer"},
            "loss_count": {"type": "integer"},
            "win_rate": {"type": "number"},
            "avg_rr": {"type": "number"},
            "profit_factor": {"type": "number"},
            "max_drawdown": {"type": "number"},
            "note": {"type": "string"},
        },
    }

    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        market = input.get("market", "binance")
        symbol = input.get("symbol", "").upper().strip()
        interval = input.get("interval", "1h")
        direction = input.get("direction", "long")
        entry_price = input.get("entry_price")
        stop_loss = input.get("stop_loss")
        target_price = input.get("target_price")
        lookback_days = int(input.get("lookback_days", 90))

        if lookback_days > 365:
            return ToolOutput.invalid_input("回测区间最大支持 365 天")
        if lookback_days < 1:
            return ToolOutput.invalid_input("回测区间至少 1 天")

        if not symbol:
            return ToolOutput.invalid_input("symbol 不能为空")

        # If levels are missing, we can still run a conceptual backtest using
        # the current close as a placeholder, but the result is mostly a no-op.
        # Prefer explicit levels when available.
        try:
            df = fetch_historical_data(market, symbol, interval, lookback_days)
        except Exception as e:
            return ToolOutput.error(f"获取历史数据失败: {e}", code="MARKET_DATA_ERROR")

        if df is None or df.empty:
            return ToolOutput.error("历史数据为空", code="NO_MARKET_DATA")

        start_ts = pd.to_datetime(df.index[0])
        end_ts = pd.to_datetime(df.index[-1])
        start_date = start_ts.isoformat() if hasattr(start_ts, "isoformat") else str(start_ts)
        end_date = end_ts.isoformat() if hasattr(end_ts, "isoformat") else str(end_ts)

        if entry_price is None or stop_loss is None or target_price is None:
            data = {
                "schema_version": "backtest_signal_output_v1",
                "status": "completed",
                "market": market,
                "symbol": symbol,
                "interval": interval,
                "direction": direction,
                "lookback_days": lookback_days,
                "start_date": start_date,
                "end_date": end_date,
                "total_signals": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "avg_rr": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "note": "缺少入场/止损/目标价，无法生成交易信号，仅返回历史数据区间。",
            }
            return ToolOutput.success(data, summary="缺少交易价位，回测未执行")

        try:
            trades = simulate_trades(
                df,
                direction=direction,
                entry_price=float(entry_price),
                stop_loss=float(stop_loss),
                target_price=float(target_price),
            )
        except ValueError as e:
            return ToolOutput.invalid_input(f"回测参数错误: {e}")
        except Exception as e:
            return ToolOutput.error(f"回测模拟失败: {e}", code="BACKTEST_ERROR")

        metrics = compute_metrics(trades)

        data = {
            "schema_version": "backtest_signal_output_v1",
            "status": "completed",
            "market": market,
            "symbol": symbol,
            "interval": interval,
            "direction": direction,
            "lookback_days": lookback_days,
            "start_date": start_date,
            "end_date": end_date,
            "total_signals": metrics.total_signals,
            "win_count": metrics.win_count,
            "loss_count": metrics.loss_count,
            "win_rate": round(metrics.win_rate, 4),
            "avg_rr": round(metrics.avg_rr, 4),
            "profit_factor": round(metrics.profit_factor, 4) if metrics.profit_factor != float("inf") else None,
            "max_drawdown": round(metrics.max_drawdown, 4),
            "note": (
                "基于固定入场/止损/目标的简化回测，未考虑滑点、手续费、部分成交及时间衰减。"
                "若单根 K 线同时触及止损与目标，按距离入场价更近的一方优先处理。"
            ),
        }
        summary = (
            f"{symbol} {interval} 近 {lookback_days} 天回测: "
            f"{metrics.total_signals} 笔, 胜率 {metrics.win_rate:.1%}, 平均 R {metrics.avg_rr:.2f}"
        )
        return ToolOutput.success(data, summary=summary)
