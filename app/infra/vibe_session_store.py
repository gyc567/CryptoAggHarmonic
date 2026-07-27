"""Persistence layer for vibe sessions, messages, and runs.

Uses Supabase service role for server-side persistence when available. All
methods are best-effort: failures are logged but do not block the agent runtime,
because Phase 1 uses localStorage as the primary client-side store.

When Supabase is not configured (e.g. local dev without env vars), the store
falls back to bounded in-memory caches so the Vibe UI can still be exercised
without unbounded growth.
"""
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from app.infra.memory_cache import MemoryCache
from app.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class VibeSessionStore:
    """Store for vibe sessions, messages, and runs."""

    def __init__(self):
        try:
            self.client = get_supabase_client(use_service_role=True)
        except Exception as e:
            logger.warning("Supabase unavailable for VibeSessionStore: %s", e)
            self.client = None

        # Bounded in-memory fallback: 256 entries each, 1 hour TTL.
        self._memory_sessions = MemoryCache[dict](max_size=256, ttl_seconds=3600)
        self._memory_messages = MemoryCache[list[dict]](max_size=256, ttl_seconds=3600)
        self._memory_runs = MemoryCache[dict](max_size=256, ttl_seconds=3600)

    def _use_memory(self) -> bool:
        return self.client is None

    # ---- Sessions ----

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

        if self._use_memory():
            self._memory_sessions.set(session_id, payload)
            return payload

        try:
            result = self.client.table("vibe_sessions").insert(payload).execute()
            return result.data[0] if result.data else payload
        except Exception as e:
            logger.exception("Failed to create vibe session")
            self._memory_sessions.set(session_id, payload)
            return payload

    def get_session(self, session_id: str, user_id: str) -> Optional[dict]:
        """Fetch a session if it belongs to the user."""
        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            return session if session and session.get("user_id") == user_id else None

        try:
            result = (
                self.client.table("vibe_sessions")
                .select("*")
                .eq("id", session_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
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
        if self._use_memory():
            sessions = [
                s for s in self._memory_sessions.values()
                if s.get("user_id") == user_id and s.get("status") == status
            ]
            sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at"), reverse=True)
            return sessions[offset:offset + limit]

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
            sessions = [
                s for s in self._memory_sessions.values()
                if s.get("user_id") == user_id and s.get("status") == status
            ]
            sessions.sort(key=lambda s: s.get("updated_at") or s.get("created_at"), reverse=True)
            return sessions[offset:offset + limit]

    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title (usually auto-generated)."""
        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            if session:
                session["title"] = title
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

        try:
            self.client.table("vibe_sessions").update(
                {"title": title, "updated_at": _now_iso()}
            ).eq("id", session_id).execute()
            return True
        except Exception as e:
            logger.warning("Failed to update session title %s: %s", session_id, e)
            session = self._memory_sessions.get(session_id)
            if session:
                session["title"] = title
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

    def archive_session(self, session_id: str, user_id: str) -> bool:
        """Soft-delete a session by setting status to deleted."""
        if self._use_memory():
            session = self._memory_sessions.get(session_id)
            if session and session.get("user_id") == user_id:
                session["status"] = "deleted"
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

        try:
            self.client.table("vibe_sessions").update(
                {"status": "deleted", "updated_at": _now_iso()}
            ).eq("id", session_id).eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.warning("Failed to archive vibe session %s: %s", session_id, e)
            session = self._memory_sessions.get(session_id)
            if session and session.get("user_id") == user_id:
                session["status"] = "deleted"
                session["updated_at"] = _now_iso()
                self._memory_sessions.set(session_id, session)
            return True

    # ---- Messages ----

    def create_message(self, message: dict) -> Optional[dict]:
        """Insert a single message."""
        msg_id = message.get("id") or str(uuid.uuid4())
        enriched = {**message, "id": msg_id}

        if self._use_memory():
            messages = self._memory_messages.get(enriched["session_id"]) or []
            messages.append(enriched)
            self._memory_messages.set(enriched["session_id"], messages)
            self._touch_session(enriched["session_id"])
            return enriched

        try:
            result = self.client.table("vibe_messages").insert(enriched).execute()
            self._touch_session(enriched["session_id"])
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("Failed to create vibe message: %s", e)
            messages = self._memory_messages.get(enriched["session_id"]) or []
            messages.append(enriched)
            self._memory_messages.set(enriched["session_id"], messages)
            self._touch_session(enriched["session_id"])
            return enriched

    def create_messages(self, messages: list[dict]) -> list[dict]:
        """Bulk insert messages."""
        if not messages:
            return []

        enriched = [{**m, "id": m.get("id") or str(uuid.uuid4())} for m in messages]

        if self._use_memory():
            for msg in enriched:
                session_messages = self._memory_messages.get(msg["session_id"]) or []
                session_messages.append(msg)
                self._memory_messages.set(msg["session_id"], session_messages)
            if enriched:
                self._touch_session(enriched[0]["session_id"])
            return enriched

        try:
            result = self.client.table("vibe_messages").insert(enriched).execute()
            if enriched:
                self._touch_session(enriched[0]["session_id"])
            return result.data or []
        except Exception as e:
            logger.warning("Failed to bulk create vibe messages: %s", e)
            for msg in enriched:
                session_messages = self._memory_messages.get(msg["session_id"]) or []
                session_messages.append(msg)
                self._memory_messages.set(msg["session_id"], session_messages)
            if enriched:
                self._touch_session(enriched[0]["session_id"])
            return enriched

    def list_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List messages for a session, oldest first."""
        if self._use_memory():
            messages = self._memory_messages.get(session_id) or []
            return messages[offset:offset + limit]

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
            return messages[offset:offset + limit]

    # ---- Runs ----

    def create_run(self, run: dict) -> Optional[dict]:
        """Insert a run record."""
        run_id = run.get("id") or str(uuid.uuid4())
        enriched = {**run, "id": run_id}

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

    def get_run(self, run_id: str, user_id: str) -> Optional[dict]:
        """Fetch a run if it belongs to the user."""
        if self._use_memory():
            run = self._memory_runs.get(run_id)
            return run if run and run.get("user_id") == user_id else None

        try:
            result = (
                self.client.table("vibe_runs")
                .select("*")
                .eq("id", run_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            return result.data
        except Exception as e:
            logger.warning("Failed to get vibe run %s: %s", run_id, e)
            run = self._memory_runs.get(run_id)
            return run if run and run.get("user_id") == user_id else None

    def update_run(self, run_id: str, updates: dict) -> bool:
        """Update a run record."""
        if self._use_memory():
            run = self._memory_runs.get(run_id)
            if run:
                run.update(updates)
                self._memory_runs.set(run_id, run)
            return True

        try:
            self.client.table("vibe_runs").update(updates).eq(
                "id", run_id
            ).execute()
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

    # ---- Helpers ----

    def _touch_session(self, session_id: str) -> None:
        """Bump session updated_at and message_count in memory fallback."""
        session = self._memory_sessions.get(session_id)
        if session:
            session["updated_at"] = _now_iso()
            session["message_count"] = len(self._memory_messages.get(session_id) or [])
            session["last_message_at"] = _now_iso()
            self._memory_sessions.set(session_id, session)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
