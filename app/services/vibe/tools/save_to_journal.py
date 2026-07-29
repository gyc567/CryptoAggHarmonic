"""save_to_journal tool for vibe agent."""

from app.infra.supabase_client import get_supabase_client
from app.services.vibe.tools.base import Tool, ToolOutput, ToolRuntime


class SaveToJournalTool(Tool):
    """Save the current trading idea as a journal draft."""

    name = "save_to_journal"
    description = "将当前交易想法保存为交易日志草稿，仅做记录，不触发真实交易。"
    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "direction": {
                "type": "string",
                "enum": ["long", "short"],
            },
            "planned_size_wu": {"type": "number"},
            "entry_price": {"type": "number"},
            "stop_loss": {"type": "number"},
            "target_price": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["symbol"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "journal_id": {"type": "string"},
            "message": {"type": "string"},
        },
    }

    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        payload = {
            "user_id": runtime.user_id,
            "session_id": runtime.session_id,
            "symbol": input.get("symbol", "").upper().strip(),
            "direction": input.get("direction"),
            "planned_size_wu": input.get("planned_size_wu"),
            "entry_price": input.get("entry_price"),
            "stop_loss": input.get("stop_loss"),
            "target_price": input.get("target_price"),
            "reasoning": input.get("reasoning"),
        }

        try:
            client = get_supabase_client(use_service_role=True)
            result = client.table("vibe_journal_drafts").insert(payload).execute()
            journal_id = result.data[0]["id"] if result.data else None
        except Exception as e:
            return ToolOutput.error(f"保存日志失败: {e}", code="JOURNAL_SAVE_ERROR")

        data = {
            "schema_version": "save_to_journal_output_v1",
            "status": "completed",
            "journal_id": journal_id,
            "message": "已保存到交易日志草稿",
        }
        return ToolOutput.success(data, summary="已保存交易日志草稿")
