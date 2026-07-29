"""Stream helper for vibe agent events."""

import uuid

from app.infra.vibe_event_store import VibeEventStore


class VibeStream:
    """Convenience wrapper around VibeEventStore for agent runtime."""

    def __init__(self, run_id: str, event_store: VibeEventStore):
        self.run_id = run_id
        self.event_store = event_store

    def _event_id(self) -> str:
        return f"evt_{uuid.uuid4().hex[:16]}"

    def run_started(self) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "run_started",
                "status": "running",
            },
        )

    def tool_call_start(self, call_id: str, tool: str, input: dict) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "tool_call_start",
                "call_id": call_id,
                "tool": tool,
                "input": input,
            },
        )

    def tool_call_end(self, call_id: str, tool: str, output: dict) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "tool_call_end",
                "call_id": call_id,
                "tool": tool,
                "output": output,
            },
        )

    def delta(self, content: str) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "delta",
                "content": content,
            },
        )

    def card(self, card_type: str, payload: dict) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "card",
                "card_type": card_type,
                "payload": payload,
            },
        )

    def done(self, input_tokens: int, output_tokens: int, duration_ms: int) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "done",
                "status": "completed",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
            },
        )

    def error(self, code: str, message: str, retryable: bool = False) -> str:
        return self.event_store.publish(
            self.run_id,
            {
                "event_id": self._event_id(),
                "type": "error",
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        )
