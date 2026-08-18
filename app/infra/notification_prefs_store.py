"""User notification preferences persistence layer.

Backed by Supabase (production) or in-memory dict (tests/offline).

Exposes:
  * :func:`get_prefs`         — fetch prefs for a user
  * :func:`upsert_prefs`      — create or update prefs
  * :func:`list_enabled_users` — all users with scan_enabled=True
  * :func:`get_or_create_prefs` — fetch or create default prefs
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INTERVAL_HOURS = 4
DEFAULT_MIN_SCORE = 60
DEFAULT_MAX_RISK = 0.02  # 2% per trade


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NotificationPrefs:
    user_id: str
    scan_enabled: bool
    scan_interval_hours: int
    min_signal_score: int
    dingtalk_webhook_url: str | None
    dingtalk_secret: str | None
    notify_on_pattern: bool
    notify_bearish_only: bool
    send_daily_summary: bool
    max_risk_per_trade: float
    created_at: str
    updated_at: str

    @classmethod
    def defaults(cls, user_id: str) -> "NotificationPrefs":
        now = _now_iso()
        return cls(
            user_id=user_id,
            scan_enabled=True,
            scan_interval_hours=DEFAULT_INTERVAL_HOURS,
            min_signal_score=DEFAULT_MIN_SCORE,
            dingtalk_webhook_url=None,
            dingtalk_secret=None,
            notify_on_pattern=True,
            notify_bearish_only=False,
            send_daily_summary=True,
            max_risk_per_trade=DEFAULT_MAX_RISK,
            created_at=now,
            updated_at=now,
        )


# ---------------------------------------------------------------------------
# In-memory fallback (for tests / offline)
# ---------------------------------------------------------------------------
_MEMORY_DB: dict[str, dict[str, Any]] = {}
_MEMORY_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class NotificationPrefsStore:
    _client: Any = None
    _redis: Any = None

    def __init__(self):
        try:
            from app.infra.supabase_client import get_supabase_client
            self._client = get_supabase_client(use_service_role=True)
        except Exception as exc:
            logger.warning("Supabase unavailable for NotificationPrefsStore: %s", exc)
            self._client = None

        try:
            from app.infra.redis_client import get_redis_client
            self._redis = get_redis_client()
        except Exception as exc:
            logger.warning("Redis unavailable for NotificationPrefsStore: %s", exc)
            self._redis = None

    def _use_memory(self) -> bool:
        return self._client is None and self._redis is None

    # -- public API ---------------------------------------------------------

    def get_prefs(self, user_id: str) -> NotificationPrefs | None:
        """Return prefs for a user, or None if not configured."""
        if self._use_memory():
            with _MEMORY_LOCK:
                raw = _MEMORY_DB.get(user_id)
            return _dict_to_prefs(raw) if raw else None

        # Try Supabase first
        if self._client:
            try:
                result = (
                    self._client.table("user_notification_prefs")
                    .select("*")
                    .eq("user_id", user_id)
                    .maybe_single()
                    .execute()
                )
                if result and result.data:
                    return _dict_to_prefs(result.data)
            except Exception as exc:
                logger.warning("get_prefs Supabase failed, falling back: %s", exc)

        # Redis fallback
        if self._redis:
            try:
                key = f"notif_prefs:{user_id}"
                raw = self._redis.hgetall(key)
                if raw:
                    return _dict_to_prefs(raw)
            except Exception as exc:
                logger.warning("get_prefs Redis failed: %s", exc)

        return None

    def get_or_create_prefs(self, user_id: str) -> NotificationPrefs:
        """Return existing prefs or a new default set (does not persist defaults)."""
        existing = self.get_prefs(user_id)
        if existing:
            return existing
        return NotificationPrefs.defaults(user_id)

    def upsert_prefs(
        self,
        user_id: str,
        *,
        dingtalk_webhook_url: str | None = ...,
        dingtalk_secret: str | None = ...,
        scan_interval_hours: int | None = ...,
        scan_enabled: bool | None = ...,
        min_signal_score: int | None = ...,
        notify_on_pattern: bool | None = ...,
        notify_bearish_only: bool | None = ...,
        send_daily_summary: bool | None = ...,
        max_risk_per_trade: float | None = ...,
    ) -> NotificationPrefs:
        """Create or update notification preferences."""
        current = self.get_prefs(user_id) or NotificationPrefs.defaults(user_id)

        def _val(new, old):
            return new if new is not ... else old

        payload = {
            "user_id": user_id,
            "scan_enabled": _val(scan_enabled, current.scan_enabled),
            "scan_interval_hours": _val(scan_interval_hours, current.scan_interval_hours),
            "min_signal_score": _val(min_signal_score, current.min_signal_score),
            "dingtalk_webhook_url": _val(dingtalk_webhook_url, current.dingtalk_webhook_url),
            "dingtalk_secret": _val(dingtalk_secret, current.dingtalk_secret),
            "notify_on_pattern": _val(notify_on_pattern, current.notify_on_pattern),
            "notify_bearish_only": _val(notify_bearish_only, current.notify_bearish_only),
            "send_daily_summary": _val(send_daily_summary, current.send_daily_summary),
            "max_risk_per_trade": _val(max_risk_per_trade, current.max_risk_per_trade),
            "updated_at": _now_iso(),
        }

        if self._use_memory():
            with _MEMORY_LOCK:
                _MEMORY_DB[user_id] = payload
            return _dict_to_prefs(payload)

        try:
            result = (
                self._client.table("user_notification_prefs")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
            if result.data:
                return _dict_to_prefs(result.data[0])
        except Exception as exc:
            logger.warning("upsert_prefs Supabase failed: %s", exc)

        # Redis fallback
        if self._redis:
            try:
                key = f"notif_prefs:{user_id}"
                self._redis.hset(key, mapping=payload)
                self._redis.expire(key, 86400 * 30)  # 30-day TTL
                return _dict_to_prefs(payload)
            except Exception as exc:
                logger.warning("upsert_prefs Redis failed: %s", exc)

        return _dict_to_prefs(payload)

    def list_enabled_users(self) -> list[tuple[str, NotificationPrefs]]:
        """Return all users with scan_enabled=True.

        Yields (user_id, prefs) tuples.
        """
        if self._use_memory():
            return [
                (uid, _dict_to_prefs(v))
                for uid, v in _MEMORY_DB.items()
                if v.get("scan_enabled", False)
            ]

        if self._client:
            try:
                result = (
                    self._client.table("user_notification_prefs")
                    .select("*")
                    .eq("scan_enabled", True)
                    .execute()
                )
                return [(r["user_id"], _dict_to_prefs(r)) for r in (result.data or [])]
            except Exception as exc:
                logger.warning("list_enabled_users Supabase failed: %s", exc)

        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_to_prefs(d: dict[str, Any]) -> NotificationPrefs:
    """Convert a DB/Redis row dict to NotificationPrefs."""
    return NotificationPrefs(
        user_id=str(d["user_id"]),
        scan_enabled=bool(d.get("scan_enabled", True)),
        scan_interval_hours=int(d.get("scan_interval_hours", DEFAULT_INTERVAL_HOURS)),
        min_signal_score=int(d.get("min_signal_score", DEFAULT_MIN_SCORE)),
        dingtalk_webhook_url=d.get("dingtalk_webhook_url"),
        dingtalk_secret=d.get("dingtalk_secret"),
        notify_on_pattern=bool(d.get("notify_on_pattern", True)),
        notify_bearish_only=bool(d.get("notify_bearish_only", False)),
        send_daily_summary=bool(d.get("send_daily_summary", True)),
        max_risk_per_trade=float(d.get("max_risk_per_trade", DEFAULT_MAX_RISK)),
        created_at=str(d.get("created_at", _now_iso())),
        updated_at=str(d.get("updated_at", _now_iso())),
    )
