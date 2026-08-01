"""Persistence layer for vibe sessions, messages, and runs.

Uses Supabase service role for server-side persistence when available. Falls
back to Redis (shared across gunicorn workers) when Supabase is unavailable,
and finally to a bounded in-memory cache for offline tests.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.infra.memory_cache import MemoryCache
from app.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_key(session_id: str) -> str:
    return f"vibe:session:{session_id}"


def _messages_key(session_id: str) -> str:
    return f"vibe:messages:{session_id}"


def _run_key(run_id: str) -> str:
    return f"vibe:run:{run_id}"


def _user_sessions_key(user_id: str) -> str:
    return f"vibe:user_sessions:{user_id}"


class VibeSessionStore:
    """Store for vibe sessions, messages, and runs.

    Redis data model:
    - ``vibe:session:{session_id}`` -> session JSON
    - ``vibe:messages:{session_id}`` -> JSON list of messages
    - ``vibe:run:{run_id}`` -> run JSON
    - ``vibe:user_sessions:{user_id}`` -> JSON list of active session ids
    """

    def __init__(self):
        try:
            self.client = get_supabase_client(use_service_role=True)
        except Exception as e:
            logger.warning("Supabase unavailable for VibeSessionStore: %s", e)
            self.client = None

        # Shared Redis fallback (survives across gunicorn workers).
        try:
            from app.infra.redis_client import get_redis_client

            self._redis = get_redis_client()
        except Exception as e:
            logger.warning("Redis unavailable for VibeSessionStore: %s", e)
            self._redis = None

        # Last-resort in-memory fallback for tests / totally offline setups.
        self._memory_sessions = MemoryCache[dict](max_size=256, ttl_seconds=3600)
        self._memory_messages = MemoryCache[list[dict]](max_size=256, ttl_seconds=3600)
        self._memory_runs = MemoryCache[dict](max_size=256, ttl_seconds=3600)

    def _use_redis(self) -> bool:
        return self.client is None and self._redis is not None

    def _use_memory(self) -> bool:
        return self.client is None and self._redis is None

    # ---- Redis helpers -----------------------------------------------------

    def _redis_get_json(self, key: str) -> dict | list | None:
        if self._redis is None:
            return None
        raw = self._redis.get(key)
        if raw is None or raw == "":
            return None
        try:
            return json.loads(raw)
        except Exception as exc:
            logger.warning("VibeSessionStore failed to parse %s: %s", key, exc)
            return None

    def _redis_set_json(self, key: str, value: dict | list) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(key, json.dumps(value, ensure_ascii=False, default=str))
        except Exception as exc:
            logger.warning("VibeSessionStore failed to write %s: %s", key, exc)

    def _redis_delete(self, *keys: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(*keys)
        except Exception as exc:
            logger.warning("VibeSessionStore failed to delete %s: %s", keys, exc)

    # ---- Sessions ----------------------------------------------------------

    def create_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """Create a new session and return its record."""
        now = _now_iso()
        session_id = str(uuid.uuid4())
        payload = {
            "id": session_id,
            "user_id": user_id,
            "title": title,
            "context": context or {},
            "status": "active",
            "message_count": 0,
            "last_message_at": None,
            "created_at": now,
            "updated_at": now,
        }

        if self._use_redis():
            self._redis_set_json(_session_key(session_id), payload)
            self._redis_set_json(_messages_key(session_id), [])
            ids = list(self._redis_get_json(_user_sessions_key(user_id)) or [])
            if session_id not in ids:
                ids.insert(0, session_id)
            self._redis_set_json(_user_sessions_key(user_id), ids)
            return payload

        if self._use_memory():
            self._memory_sessions.set(session_id, payload)
            self._memory_messages.set(session_id, [])
            return payload

        try:
            result = self.client.table("vibe_sessions").insert(payload).execute()
            return result.data[0] if result.data else payload
        except Exception:
            logger.exception("Failed to create vibe session")
            self._memory_sessions.set(session_id, payload)
            return payload

    def get_session(self, session_id: str, user_id: str) -> dict | None:
        """Fetch a session if it belongs to the user."""
        if self._use_redis():
            session = self._redis_get_json(_session_key(session_id))
            return session if session and session.get("user_id") == user_id else None

        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            return session if session and session.get("user_id") == user_id else None

        try:
            result = self.client.table("vibe_sessions").select("*").eq("id", session_id).eq("user_id", user_id).single().execute()
            return result.data
        except Exception as e:
            logger.warning("Failed to get vibe session %s: %s", session_id, e)
            session = self._memory_sessions.get(session_id)
            return session if session and session.get("user_id") == user_id else None

    def list_sessions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        status: str = "active",
    ) -> list[dict]:
        """List sessions for a user, newest first."""
        if self._use_redis():
            ids = list(self._redis_get_json(_user_sessions_key(user_id)) or [])
            sessions: list[dict] = []
            for sid in ids:
                session = self._redis_get_json(_session_key(sid))
                if session and session.get("status") == status:
                    sessions.append(session)
            sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at"), reverse=True)
            return sessions[offset : offset + limit]

        if self._use_memory():
            sessions = [s for s in self._memory_sessions.values() if s.get("user_id") == user_id and s.get("status") == status]
            sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at"), reverse=True)
            return sessions[offset : offset + limit]

        try:
            result = (
                self.client.table("vibe_sessions")
                .select("*")
                .eq("user_id", user_id)
                .eq("status", status)
                .order("last_message_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning("Failed to list vibe sessions: %s", e)
            sessions = [s for s in self._memory_sessions.values() if s.get("user_id") == user_id and s.get("status") == status]
            sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at"), reverse=True)
            return sessions[offset : offset + limit]

    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title (usually auto-generated)."""
        if self._use_redis():
            session = self._redis_get_json(_session_key(session_id))
            if session:
                session["title"] = title
                session["updated_at"] = _now_iso()
                self._redis_set_json(_session_key(session_id), session)
            return True

        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            if session:
                session["title"] = title
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

        try:
            self.client.table("vibe_sessions").update({"title": title, "updated_at": _now_iso()}).eq("id", session_id).execute()
            return True
        except Exception as e:
            logger.warning("Failed to update vibe session title %s: %s", session_id, e)
            session = self._memory_sessions.get(session_id)
            if session:
                session["title"] = title
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

    def archive_session(self, session_id: str, user_id: str) -> bool:
        """Soft-delete a session by setting status to deleted."""
        if self._use_redis():
            session = self._redis_get_json(_session_key(session_id))
            if session and session.get("user_id") == user_id:
                session["status"] = "deleted"
                session["updated_at"] = _now_iso()
                self._redis_set_json(_session_key(session_id), session)
                ids = list(self._redis_get_json(_user_sessions_key(user_id)) or [])
                if session_id in ids:
                    ids.remove(session_id)
                    self._redis_set_json(_user_sessions_key(user_id), ids)
            return True

        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            if session and session.get("user_id") == user_id:
                session["status"] = "deleted"
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

        try:
            self.client.table("vibe_sessions").update({"status": "deleted", "updated_at": _now_iso()}).eq("id", session_id).eq(
                "user_id", user_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("Failed to archive vibe session %s: %s", session_id, e)
            session = self._memory_sessions.get(session_id)
            if session and session.get("user_id") == user_id:
                session["status"] = "deleted"
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

    # ---- Messages ----------------------------------------------------------

    def create_message(self, message: dict) -> dict | None:
        """Insert a single message."""
        msg_id = message.get("id") or str(uuid.uuid4())
        enriched = {**message, "id": msg_id}
        session_id = enriched["session_id"]

        if self._use_redis():
            messages = list(self._redis_get_json(_messages_key(session_id)) or [])
            messages.append(enriched)
            self._redis_set_json(_messages_key(session_id), messages)
            self._touch_session(session_id)
            return enriched

        if self._use_memory():
            messages = self._memory_messages.get(session_id) or []
            messages.append(enriched)
            self._memory_messages.set(session_id, messages)
            self._touch_session(session_id)
            return enriched

        try:
            result = self.client.table("vibe_messages").insert(enriched).execute()
            self._touch_session(session_id)
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("Failed to create vibe message: %s", e)
            messages = self._memory_messages.get(session_id) or []
            messages.append(enriched)
            self._memory_messages.set(session_id, messages)
            self._touch_session(session_id)
            return enriched

    def create_messages(self, messages: list[dict]) -> list[dict]:
        """Bulk insert messages."""
        if not messages:
            return []

        enriched = [{**m, "id": m.get("id") or str(uuid.uuid4())} for m in messages]
        session_id = enriched[0]["session_id"]

        if self._use_redis():
            stored = list(self._redis_get_json(_messages_key(session_id)) or [])
            stored.extend(enriched)
            self._redis_set_json(_messages_key(session_id), stored)
            self._touch_session(session_id)
            return enriched

        if self._use_memory():
            for msg in enriched:
                session_messages = self._memory_messages.get(msg["session_id"]) or []
                session_messages.append(msg)
                self._memory_messages.set(msg["session_id"], session_messages)
            if enriched:
                self._touch_session(session_id)
            return enriched

        try:
            result = self.client.table("vibe_messages").insert(enriched).execute()
            if enriched:
                self._touch_session(session_id)
            return result.data or []
        except Exception as e:
            logger.warning("Failed to bulk create vibe messages: %s", e)
            for msg in enriched:
                session_messages = self._memory_messages.get(msg["session_id"]) or []
                session_messages.append(msg)
                self._memory_messages.set(msg["session_id"], session_messages)
            if enriched:
                self._touch_session(session_id)
            return enriched

    def list_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List messages for a session, oldest first."""
        if self._use_redis():
            messages = list(self._redis_get_json(_messages_key(session_id)) or [])
            return messages[offset : offset + limit]

        if self._use_memory():
            messages = self._memory_messages.get(session_id) or []
            return messages[offset : offset + limit]

        try:
            result = (
                self.client.table("vibe_messages")
                .select("*")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning("Failed to list vibe messages: %s", e)
            messages = self._memory_messages.get(session_id) or []
            return messages[offset : offset + limit]

    # ---- Runs --------------------------------------------------------------

    def create_run(self, run: dict) -> dict | None:
        """Insert a run record."""
        run_id = run.get("id") or str(uuid.uuid4())
        enriched = {**run, "id": run_id}

        if self._use_redis():
            self._redis_set_json(_run_key(run_id), enriched)
            return enriched

        if self._use_memory():
            self._memory_runs.set(run_id, enriched)
            return enriched

        try:
            result = self.client.table("vibe_runs").insert(enriched).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("Failed to create vibe run: %s", e)
            self._memory_runs.set(run_id, enriched)
            return enriched

    def get_run(self, run_id: str, user_id: str) -> dict | None:
        """Fetch a run if it belongs to the user."""
        if self._use_redis():
            run = self._redis_get_json(_run_key(run_id))
            return run if run and run.get("user_id") == user_id else None

        if self._use_memory():
            run = self._memory_runs.get(run_id)
            return run if run and run.get("user_id") == user_id else None

        try:
            result = self.client.table("vibe_runs").select("*").eq("id", run_id).eq("user_id", user_id).single().execute()
            return result.data
        except Exception as e:
            logger.warning("Failed to get vibe run %s: %s", run_id, e)
            run = self._memory_runs.get(run_id)
            return run if run and run.get("user_id") == user_id else None

    def update_run(self, run_id: str, updates: dict) -> bool:
        """Update a run record."""
        if self._use_redis():
            run = self._redis_get_json(_run_key(run_id))
            if run:
                run.update(updates)
                self._redis_set_json(_run_key(run_id), run)
            return True

        if self._use_memory():
            run = self._memory_runs.get(run_id)
            if run:
                run.update(updates)
                self._memory_runs.set(run_id, run)
            return True

        try:
            self.client.table("vibe_runs").update(updates).eq("id", run_id).execute()
            return True
        except Exception as e:
            logger.warning("Failed to update vibe run %s: %s", run_id, e)
            run = self._memory_runs.get(run_id)
            if run:
                run.update(updates)
                self._memory_runs.set(run_id, run)
            return True

    def cancel_run(self, run_id: str, cancelled_by: str) -> bool:
        """Mark a run as cancelled."""
        return self.update_run(
            run_id,
            {
                "status": "cancelled",
                "cancelled_by": cancelled_by,
                "completed_at": _now_iso(),
            },
        )

    # ---- Helpers -----------------------------------------------------------

    def _touch_session(self, session_id: str) -> None:
        """Bump session updated_at and message_count."""
        if self._use_redis():
            session = self._redis_get_json(_session_key(session_id))
            if session:
                messages = list(self._redis_get_json(_messages_key(session_id)) or [])
                session["updated_at"] = _now_iso()
                session["message_count"] = len(messages)
                session["last_message_at"] = _now_iso()
                self._redis_set_json(_session_key(session_id), session)
            return

        session = self._memory_sessions.get(session_id)
        if session:
            session["updated_at"] = _now_iso()
            session["message_count"] = len(self._memory_messages.get(session_id) or [])
            session["last_message_at"] = _now_iso()
            self._memory_sessions.set(session_id, session)
