"""position_check tool for vibe agent."""

from app.infra.supabase_client import get_supabase_client
from app.services.vibe.tools.base import Tool, ToolOutput, ToolRuntime


class PositionCheckTool(Tool):
    """Check the risk level of a planned trade against the user's position config."""

    name = "position_check"
    description = "根据用户保存的仓位配置，检查计划交易金额会触发哪个风控等级。"
    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "planned_trade_wu": {"type": "number"},
            "direction": {
                "type": "string",
                "enum": ["long", "short"],
            },
        },
        "required": ["symbol", "planned_trade_wu"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "symbol": {"type": "string"},
            "planned_trade_wu": {"type": "number"},
            "risk_level": {"type": "integer"},
            "risk_label": {"type": "string"},
            "trouble": {"type": "string"},
            "cooldown": {"type": "string"},
            "available_wu": {"type": "number"},
            "suggestion": {"type": "string"},
        },
    }

    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        symbol = input.get("symbol", "").upper().strip()
        planned = float(input.get("planned_trade_wu", 0))

        try:
            client = get_supabase_client(use_service_role=True)
            result = (
                client.table("profiles").select("position_config, position_balance").eq("id", runtime.user_id).single().execute()
            )
            profile = result.data or {}
        except Exception as e:
            return ToolOutput.error(f"读取仓位配置失败: {e}", code="PROFILE_READ_ERROR")

        config = profile.get("position_config") or {}
        balance = profile.get("position_balance") or {}

        if not config:
            return ToolOutput.success(
                {
                    "schema_version": "position_check_output_v1",
                    "status": "no_config",
                    "symbol": symbol,
                    "planned_trade_wu": planned,
                    "suggestion": "尚未设置仓位配置，请前往 仓位管理 页面设置总资金与账户拆分。",
                }
            )

        try:
            risk = self._compute_risk(config, balance, planned)
        except Exception as e:
            return ToolOutput.error(f"风控计算失败: {e}", code="RISK_CALC_ERROR")

        data = {
            "schema_version": "position_check_output_v1",
            "status": "completed",
            "symbol": symbol,
            "planned_trade_wu": planned,
            **risk,
        }
        return ToolOutput.success(data, summary=risk["suggestion"])

    def _compute_risk(self, config: dict, balance: dict, planned: float) -> dict:
        total = float(config.get("totalCapitalWu", 0))
        cut = float(config.get("cutPositionWu", 0))
        regular = max(0.0, total - cut)

        if regular <= 0:
            return {
                "risk_level": 5,
                "risk_label": "5 级",
                "trouble": "常规管理资金为零",
                "cooldown": "禁止",
                "available_wu": 0.0,
                "suggestion": "常规管理资金不足，请检查总资金与切割仓位设置。",
            }

        float(config.get("emergencyRatio", 0.3))
        btc_ratio = float(config.get("btcRatio", 0.5))
        alt_max_ratio = float(config.get("altcoinMaxRatio", 0.2))
        small_ratio = float(config.get("smallAccountRatio", 0.05))
        small_tradable_ratio = float(config.get("smallTradableRatio", 0.7))

        btc_trend = regular * btc_ratio
        alt_limit = regular * alt_max_ratio
        small_account = alt_limit * small_ratio
        small_tradable = small_account * small_tradable_ratio

        # Use balance-driven available amounts if present, otherwise config-driven.
        available = float(balance.get("smallTradableWu", small_tradable))

        levels = [
            (0, small_tradable, "无额外麻烦", "至少确认逻辑"),
            (1, small_account, "需划转小账户备用", "暂停 5 分钟"),
            (2, alt_limit, "换账户 / 换手机", "暂停 15 分钟"),
            (3, btc_trend, "必须回家电脑操作", "隔夜复盘"),
            (4, regular, "再次从理财资管划转", "原则上禁止"),
        ]

        risk_level = 5
        trouble = "无法覆盖"
        cooldown = "禁止"
        for lvl, threshold, t, c in levels:
            if planned <= threshold:
                risk_level = lvl
                trouble = t
                cooldown = c
                break

        if risk_level == 0:
            suggestion = f"计划金额在风控可接受范围内，当前小账户可交易额度约 {available:.2f} WU。"
        elif risk_level < 5:
            suggestion = f"触发 {risk_level} 级风控，需跨越：{trouble}。建议 {cooldown}。"
        else:
            suggestion = "计划金额超过常规管理资金，建议减少仓位或重新配置资金。"

        return {
            "risk_level": risk_level,
            "risk_label": f"{risk_level} 级",
            "trouble": trouble,
            "cooldown": cooldown,
            "available_wu": round(available, 2),
            "suggestion": suggestion,
        }
