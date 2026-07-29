"""Vibe agent orchestrator."""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.infra.supabase_client import (
    consume_ledger_quota,
    get_supabase_client,
    release_ledger_quota,
)
from app.infra.vibe_event_store import VibeEventStore
from app.infra.vibe_session_store import VibeSessionStore
from app.infra.vibe_trace_store import VibeTraceStore
from app.services.vibe.cancellation import CancellationToken
from app.services.vibe.context import (
    build_system_prompt,
    compress_messages,
    extract_position_summary,
)
from app.services.vibe.llm.provider import LLMProvider, ToolCall
from app.services.vibe.stream import VibeStream
from app.services.vibe.tools.base import ToolRuntime
from app.services.vibe.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.getenv("VIBE_MAX_ITERATIONS", "10"))
TOOL_TIMEOUT_SECONDS = int(os.getenv("VIBE_TOOL_TIMEOUT_SECONDS", "30"))


class VibeOrchestrator:
    """Orchestrates a single vibe agent run."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        session_store: VibeSessionStore,
        event_store: VibeEventStore,
        trace_store: VibeTraceStore,
    ):
        self.llm = llm_provider
        self.tools = tool_registry
        self.session_store = session_store
        self.event_store = event_store
        self.trace_store = trace_store

    def run(
        self,
        session_id: str,
        run_id: str,
        user_id: str,
        user_prompt: str,
        ledger_id: Optional[str] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Execute the agent run and publish events."""
        start_time = time.time()
        stream = VibeStream(run_id, self.event_store)
        stream.run_started()

        # Load session context and position config.
        session = self.session_store.get_session(session_id, user_id) or {}
        context = session.get("context") or {}
        position_config, position_balance = self._load_position(user_id)
        position_summary = extract_position_summary(position_config, position_balance)

        # Save user message.
        user_message = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "run_id": run_id,
            "role": "user",
            "content": user_prompt,
            "created_at": self._now(),
        }
        self.session_store.create_message(user_message)

        # Build messages.
        tool_schemas = self.tools.get_schemas()
        tool_descriptions = self.tools.get_prompt_description()
        system_prompt = build_system_prompt(
            tool_descriptions=tool_descriptions,
            default_market=context.get("default_market", "binance"),
            default_symbol=context.get("default_symbol", "BTCUSDT"),
            position_summary=position_summary,
        )

        history = self._load_history(session_id)
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_prompt},
        ]

        trace = {
            "system_prompt": system_prompt,
            "messages": [],
            "tool_calls": [],
        }

        total_input_tokens = 0
        total_output_tokens = 0
        final_content = ""
        final_cards = []
        status = "completed"
        error_message = None
        ledger_consumed = False

        def _is_cancelled() -> bool:
            return cancellation_token is not None and cancellation_token.is_set()

        try:
            for iteration in range(MAX_ITERATIONS):
                if _is_cancelled():
                    raise RuntimeError("运行已被用户取消")
                logger.info("Vibe run %s iteration %d", run_id, iteration + 1)
                response = self.llm.chat(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.3,
                    max_tokens=2000,
                )

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens
                trace["messages"].append(
                    {
                        "iteration": iteration,
                        "response": response.content,
                        "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls],
                    }
                )

                if response.is_error:
                    raise RuntimeError(response.error)

                if response.has_tool_calls:
                    # Add assistant message with tool_calls.
                    assistant_msg = {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                    messages.append(assistant_msg)

                    for tc in response.tool_calls:
                        if _is_cancelled():
                            raise RuntimeError("运行已被用户取消")
                        tool_output = self._execute_tool(tc, user_id, session_id, run_id, stream)
                        trace["tool_calls"].append(
                            {
                                "name": tc.name,
                                "input": tc.arguments,
                                "output": tool_output.status,
                                "data": tool_output.data,
                                "error": tool_output.error,
                            }
                        )

                        tool_result_msg = {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(
                                {
                                    "status": tool_output.status,
                                    "data": tool_output.data,
                                    "error": tool_output.error,
                                    "summary": tool_output.summary,
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                        messages.append(tool_result_msg)
                else:
                    final_content = response.content or ""
                    # Stream final content as deltas (fixed-size chunks).
                    for chunk in self._split_content(final_content):
                        stream.delta(chunk)
                    break

            else:
                final_content = "已达到最大迭代次数，以下是目前可获得的信息。"
                status = "completed_with_limit"

        except Exception as e:
            logger.exception("Vibe run %s failed", run_id)
            status = "failed"
            error_message = str(e)
            stream.error("RUN_ERROR", error_message, retryable=True)

        # Consume or release quota based on final status.
        if ledger_id and not ledger_consumed:
            if status in ("completed", "completed_with_limit"):
                if consume_ledger_quota(
                    ledger_id,
                    input_tokens=total_input_tokens or None,
                    output_tokens=total_output_tokens or None,
                ):
                    ledger_consumed = True
                else:
                    logger.warning("Failed to consume quota for run %s", run_id)
            else:
                if not release_ledger_quota(ledger_id):
                    logger.warning("Failed to release quota for run %s", run_id)

        duration_ms = int((time.time() - start_time) * 1000)

        # Build final assistant message with cards.
        if status != "failed":
            final_cards = self._build_cards(messages)
            assistant_message = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "run_id": run_id,
                "role": "assistant",
                "content": final_content,
                "cards": final_cards,
                "created_at": self._now(),
            }
            self.session_store.create_message(assistant_message)
            for card in final_cards:
                stream.card(card["type"], card["payload"])

        # Save run metadata.
        completed_at = self._now() if status in ("completed", "completed_with_limit") else None
        self.session_store.update_run(
            run_id,
            {
                "status": status,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "duration_ms": duration_ms,
                "user_prompt": user_prompt,
                "model": getattr(self.llm, "model", "unknown"),
                "decision_basis": self._build_decision_basis(messages),
                "error": error_message,
                "completed_at": completed_at,
            },
        )

        # Save trace.
        trace["final_status"] = status
        trace["final_content"] = final_content
        self.trace_store.save_trace(run_id, user_id, trace)

        if status == "failed":
            return

        # Mark quota consumed before emitting done so callers see consistent state.
        if ledger_id and not ledger_consumed and status in ("completed", "completed_with_limit"):
            if consume_ledger_quota(
                ledger_id,
                input_tokens=total_input_tokens or None,
                output_tokens=total_output_tokens or None,
            ):
                ledger_consumed = True

        stream.done(total_input_tokens, total_output_tokens, duration_ms)

        # Auto-generate session title on first assistant message.
        if session and not session.get("title"):
            title = self._generate_title(user_prompt, final_content)
            if title:
                self.session_store.update_session_title(session_id, title)

    def _execute_tool(
        self,
        tc: ToolCall,
        user_id: str,
        session_id: str,
        run_id: str,
        stream: VibeStream,
    ) -> dict:
        """Execute a single tool call and publish events."""
        stream.tool_call_start(tc.id, tc.name, tc.arguments)
        runtime = ToolRuntime(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
        )
        output = self.tools.execute(tc.name, tc.arguments, runtime)
        stream.tool_call_end(tc.id, tc.name, output.data)
        return output

    def _signal_from_analysis(self, data: dict) -> dict:
        """Extract a full Signal-shaped card payload from analyze_harmonic output.

        The tool already embeds the complete Signal model under the ``signal`` key.
        Prefer that; only build a minimal fallback when it is missing.
        """
        signal = data.get("signal")
        if signal:
            return signal

        # Minimal fallback so the frontend SignalCard does not crash.
        return {
            "status": "confirmed",
            "grade": "C",
            "direction": data.get("direction", "long"),
            "pattern_name": data.get("pattern_type", "unknown"),
            "family": data.get("pattern_family", "unknown"),
            "formed": True,
            "entry_zone": [data.get("entry_price"), data.get("entry_price")],
            "entry_reference": data.get("entry_price"),
            "stop_loss": data.get("stop_loss"),
            "targets": [{"label": "TP1", "price": data.get("target_price"), "close_pct": 100}],
        }

    def _build_cards(self, messages: list[dict]) -> list[dict]:
        """Build final card list from tool results in the message history."""
        cards = []
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            try:
                content = json.loads(msg.get("content", "{}"))
            except json.JSONDecodeError:
                continue
            data = content.get("data") or {}
            if content.get("status") != "completed":
                continue

            schema_version = data.get("schema_version", "")
            if "analyze_harmonic" in schema_version:
                cards.append({"type": "signal", "payload": self._signal_from_analysis(data)})
            elif "trade_signal" in schema_version and data.get("signal"):
                cards.append({"type": "signal", "payload": data["signal"]})
            elif "position_check" in schema_version:
                cards.append({"type": "position_check", "payload": data})
            elif "backtest_signal" in schema_version:
                cards.append({"type": "backtest", "payload": data})
        return cards

    def _build_decision_basis(self, messages: list[dict]) -> dict:
        """Summarize which tools were called."""
        tool_names = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tool_names.append(tc.get("function", {}).get("name"))
        return {"tools_called": tool_names}

    def _load_history(self, session_id: str) -> list[dict]:
        """Load and compress recent session messages."""
        raw_messages = self.session_store.list_messages(session_id, limit=50)
        formatted = []
        for msg in raw_messages:
            if msg.get("role") == "tool":
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.get("tool_call_id"),
                        "content": json.dumps(
                            msg.get("tool_output_summary") or {},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )
            elif msg.get("role") == "assistant":
                formatted.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": msg.get("tool_calls"),
                    }
                )
            else:
                formatted.append({"role": msg.get("role"), "content": msg.get("content") or ""})
        return compress_messages(formatted)

    def _load_position(self, user_id: str) -> tuple[dict | None, dict | None]:
        """Load user's position config and balance from Supabase."""
        try:
            client = get_supabase_client(use_service_role=True)
            result = client.table("profiles").select("position_config, position_balance").eq("id", user_id).single().execute()
            data = result.data or {}
            return data.get("position_config"), data.get("position_balance")
        except Exception as e:
            logger.warning("Failed to load position config for %s: %s", user_id, e)
            return None, None

    def _generate_title(self, user_prompt: str, assistant_content: Optional[str]) -> str:
        """Generate a short session title from the first exchange."""
        # Phase 1 simple heuristic: use user prompt truncated.
        title = user_prompt.strip().replace("\n", " ")[:30]
        return title + "..." if len(user_prompt) > 30 else title

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _split_content(text: str, chunk_size: int = 6) -> list[str]:
        """Split text into fixed-size chunks for streaming.

        Using fixed-size character chunks avoids inserting extra spaces between
        Chinese tokens while still producing smooth updates for English text.
        """
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
