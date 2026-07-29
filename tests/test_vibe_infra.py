"""Tests for vibe-specific infrastructure: cancellation, event store, trace store, prompt parsing."""
import os
import time
from unittest.mock import MagicMock

import pytest

from app.infra.vibe_event_store import VibeEventStore
from app.infra.vibe_trace_store import VibeTraceStore
from app.services.vibe.cancellation import (
    CancellationToken,
    cancel_run,
    register_run,
    unregister_run,
)
from app.services.vibe.llm.prompt_provider import PromptProvider


class TestCancellation:
    def test_local_event_cancellation(self):
        token = register_run("run-local")
        assert not token.is_set()
        cancel_run("run-local")
        assert token.is_set()
        unregister_run("run-local")

    def test_redis_cancellation_check(self):
        fake_redis = MagicMock()
        fake_redis.exists.return_value = 1

        token = CancellationToken("run-redis", redis_client=fake_redis)
        assert token.is_set()
        token.set()
        fake_redis.setex.assert_called_once()


class TestVibeEventStore:
    def test_get_events_by_offset(self):
        store = VibeEventStore(redis_url="")  # force in-memory
        run_id = "run-offset"
        e1 = store.publish(run_id, {"type": "delta", "content": "a"})
        e2 = store.publish(run_id, {"type": "delta", "content": "b"})
        e3 = store.publish(run_id, {"type": "done"})

        events = store.get_events(run_id, offset=1, limit=10)
        assert len(events) == 2
        assert events[0]["event_id"] == e2
        assert events[1]["event_id"] == e3

    def test_get_events_by_after_event_id(self):
        store = VibeEventStore(redis_url="")
        run_id = "run-after"
        e1 = store.publish(run_id, {"type": "delta", "content": "a"})
        store.publish(run_id, {"type": "delta", "content": "b"})
        e3 = store.publish(run_id, {"type": "done"})

        events = store.get_events(run_id, after_event_id=e1, limit=10)
        assert len(events) == 2
        assert events[-1]["event_id"] == e3

    def test_seq_assigned_sequentially_and_polling(self):
        """Each event gets a monotonic seq, and get_events(after_seq=...) skips O(1)."""
        store = VibeEventStore(redis_url="")
        run_id = "run-seq"

        e1 = store.publish(run_id, {"type": "delta", "content": "a"})
        store.publish(run_id, {"type": "delta", "content": "b"})
        e3 = store.publish(run_id, {"type": "done"})

        all_events = store.get_events(run_id, offset=0, limit=10)
        seqs = [ev["seq"] for ev in all_events]
        # seq 0, 1, 2 in insertion order.
        assert seqs == [0, 1, 2]

        # after_seq=0 returns events 1..2.
        nxt = store.get_events(run_id, after_seq=0, limit=10)
        assert [ev["event_id"] for ev in nxt] == [
            ev["event_id"] for ev in all_events if ev["seq"] > 0
        ]

        # after_seq=last returns empty.
        empty = store.get_events(run_id, after_seq=2, limit=10)
        assert empty == []

        # clear() also resets seq.
        store.clear(run_id)
        e_after_clear = store.publish(run_id, {"type": "delta", "content": "fresh"})
        after_clear = store.get_events(run_id, offset=0, limit=10)
        assert len(after_clear) == 1
        assert after_clear[0]["seq"] == 0
        assert after_clear[0]["event_id"] == e_after_clear



class TestVibeTraceStore:
    def test_retention_cleanup(self, tmp_path):
        store = VibeTraceStore(base_dir=str(tmp_path))
        store.save_trace("run-old", "u1", {"data": 1})
        store.save_trace("run-new", "u1", {"data": 2})

        old_path = tmp_path / "u1" / "run-old.json"
        new_path = tmp_path / "u1" / "run-new.json"

        # Age the old trace beyond the default 30-day retention.
        old_mtime = time.time() - 40 * 86400
        os.utime(old_path, (old_mtime, old_mtime))

        # Re-instantiating the store triggers cleanup.
        VibeTraceStore(base_dir=str(tmp_path))

        assert not old_path.exists()
        assert new_path.exists()


class TestPromptProviderParsing:
    def test_multiple_inline_json_objects(self):
        provider = PromptProvider()
        text = (
            'Some text {"tool": "t1", "arguments": {"a": 1}} '
            'more {"tool": "t2", "arguments": {"b": 2}}'
        )
        content, calls = provider._parse_response(text)
        assert len(calls) == 2
        assert calls[0].name == "t1"
        assert calls[1].name == "t2"
        assert content is None or "more" in content

    def test_fenced_json_block(self):
        provider = PromptProvider()
        text = "Analysis:\n```json\n{\"tool\": \"t1\", \"arguments\": {\"a\": 1}}\n```"
        content, calls = provider._parse_response(text)
        assert len(calls) == 1
        assert calls[0].name == "t1"
        assert "Analysis" in (content or "")

    def test_nested_json_arguments(self):
        provider = PromptProvider()
        text = '{"tool": "t1", "arguments": {"nested": {"key": "value"}}}'
        content, calls = provider._parse_response(text)
        assert len(calls) == 1
        assert calls[0].arguments == {"nested": {"key": "value"}}
        assert content is None
