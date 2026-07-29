"""Context management for vibe agent sessions."""

from datetime import datetime, timezone
from typing import Optional


def build_system_prompt(
    tool_descriptions: str,
    default_market: str = "binance",
    default_symbol: str = "BTCUSDT",
    position_summary: Optional[str] = None,
) -> str:
    """Build the system prompt for the vibe agent."""
    position_text = position_summary or "用户尚未设置仓位配置。"
    return (
        "你是一位专业的技术分析助手，名为 AI 交易助手。"
        "你只提供市场研究、谐波形态分析、信号生成和风险提示，不提供具体投资建议。\n\n"
        "可用工具：\n"
        f"{tool_descriptions}\n\n"
        "安全约束：\n"
        "- 禁止建议用户满仓、杠杆、借贷或进行任何真实资金操作。\n"
        "- 任何涉及仓位的问题必须先调用 position_check 工具检查风控等级。\n"
        "- 任何交易信号必须同时给出止损价；风险收益比低于 1.0 时，必须标注“风险收益比不佳”。\n"
        "- 若用户问题超出技术分析范畴，礼貌拒绝并说明范围。\n\n"
        "会话上下文：\n"
        f"- 默认市场：{default_market}\n"
        f"- 默认标的：{default_symbol}\n"
        f"- 仓位配置摘要：{position_text}\n\n"
        f"当前时间：{datetime.now(timezone.utc).isoformat()}"
    )


def compress_messages(messages: list[dict], max_recent: int = 6) -> list[dict]:
    """Keep recent messages and summarize older ones.

    Phase 1 uses a simple truncation strategy. Phase 2 will use an LLM to
    generate a rich summary.
    """
    if len(messages) <= max_recent:
        return messages

    recent = messages[-max_recent:]
    older = messages[:-max_recent]

    summary_parts = []
    for msg in older:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "user":
            summary_parts.append(f"用户之前问：{content[:100]}")
        elif role == "assistant":
            summary_parts.append(f"助手之前答：{content[:100]}")

    summary = "\n".join(summary_parts)
    system_summary = {
        "role": "system",
        "content": f"以下是对话历史摘要：\n{summary}",
    }
    return [system_summary] + recent


def extract_position_summary(config: Optional[dict], balance: Optional[dict]) -> str:
    """Build a short text summary of the user's position config."""
    if not config:
        return "未设置"
    total = config.get("totalCapitalWu", 0)
    return f"总资金 {total} WU，已保存仓位配置"
