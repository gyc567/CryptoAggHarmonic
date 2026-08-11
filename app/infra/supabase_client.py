"""Supabase client module for Pyharmonics SaaS.

Supports both REST API (via supabase-py) and direct PostgreSQL connections.
Handles proxy environments and connection pooling.
"""

import logging
import os
import threading
import time
import urllib.parse
from contextlib import contextmanager
from typing import Any, Optional

# Import create_client at module level for testability
try:
    from supabase import create_client as _create_supabase_client
except ImportError:
    _create_supabase_client = None  # type: ignore

logger = logging.getLogger(__name__)

# Lazy-loaded clients keyed by role to avoid anon/service_role cross-over.
_supabase_clients: dict[str, Any] = {}
_db_pool: Optional[Any] = None

# ---------------------------------------------------------------------------
# Idempotency lookup cache (in-process fast path)
# ---------------------------------------------------------------------------
# The /api/analyze route must dedupe retries by ``(user_id, idempotency_key)``
# without hitting Supabase on every request. We keep a small bounded dict
# keyed by that tuple, holding the most recent row (or None for miss) for a
# short TTL. Any error falls back to a miss so the request still succeeds.

_IDEM_CACHE_TTL_SECONDS = float(os.getenv("ANALYSIS_IDEM_CACHE_TTL", "60"))
_IDEM_CACHE_MAX_ENTRIES = int(os.getenv("ANALYSIS_IDEM_CACHE_MAX", "1024"))
_idem_cache: dict[tuple, tuple] = {}
_idem_lock = threading.Lock()


def _get_proxy_settings() -> dict[str, str]:
    """Get proxy settings from environment."""
    proxies = {}
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        if os.getenv(key):
            proxies[key.lower().replace("_proxy", "")] = os.getenv(key)
    return proxies


def get_supabase_url() -> str:
    """Get Supabase project URL from environment."""
    url = os.getenv("SUPABASE_URL")
    if not url:
        # Fallback: derive from connection string or use default
        conn_url = os.getenv("SUPABASE_DB_URL", "")
        if conn_url:
            parsed = urllib.parse.urlparse(conn_url)
            # Convert db.xxx.supabase.co to xxx.supabase.co
            host = parsed.hostname or ""
            if host.startswith("db."):
                project_ref = host.split(".")[1]
                return f"https://{project_ref}.supabase.co"
        raise RuntimeError("SUPABASE_URL environment variable not set")
    return url


def get_supabase_anon_key() -> str:
    """Get Supabase anon/publishable key from environment.

    Supports both legacy JWT format (eyJ...) and new Publishable Key format (sb_publishable_...).
    See: https://supabase.com/docs/guides/getting-started/api-keys
    """
    key = os.getenv("SUPABASE_ANON_KEY")
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY environment variable not set")
    return key


def get_supabase_service_key() -> str:
    """Get Supabase service role key from environment.

    Supports both legacy JWT format (eyJ...) and new Secret Key format (sb_secret_a_...).
    See: https://supabase.com/docs/guides/getting-started/api-keys
    """
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        # Fallback: try new secret key naming convention
        key = os.getenv("SUPABASE_SECRET_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY) environment variable not set")
    return key


def get_supabase_client(use_service_role: bool = False) -> Any:
    """Get or create Supabase client.

    Args:
        use_service_role: If True, use service_role key (server-side only).

    Returns:
        Supabase client instance.
    """
    global _supabase_clients
    role = "service_role" if use_service_role else "anon"
    client = _supabase_clients.get(role)
    if client is None:
        if _create_supabase_client is None:
            raise RuntimeError("supabase package not installed")
        url = get_supabase_url()
        key = get_supabase_service_key() if use_service_role else get_supabase_anon_key()
        client = _create_supabase_client(url, key)
        _supabase_clients[role] = client
        logger.info("Supabase client initialized (role=%s)", role)
    return client


def get_db_connection_string() -> str:
    """Get PostgreSQL connection string from environment.

    Handles URL-encoded passwords properly.
    """
    raw_url = os.getenv("SUPABASE_DB_URL", "")
    if not raw_url:
        # Construct from components
        host = os.getenv("SUPABASE_DB_HOST", "")
        port = os.getenv("SUPABASE_DB_PORT", "5432")
        user = os.getenv("SUPABASE_DB_USER", "postgres")
        password = os.getenv("SUPABASE_DB_PASSWORD", "")
        dbname = os.getenv("SUPABASE_DB_NAME", "postgres")
        if not host or not password:
            raise RuntimeError("Database connection details not configured")
        encoded_password = urllib.parse.quote(password, safe="")
        return f"postgresql://{user}:{encoded_password}@{host}:{port}/{dbname}"

    # Parse and re-encode password if needed
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.password:
        encoded_password = urllib.parse.quote(parsed.password, safe="")
        # Reconstruct URL with encoded password
        netloc = f"{parsed.username}:{encoded_password}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return raw_url


def get_db_pool():
    """Get or create PostgreSQL connection pool.

    Returns:
        psycopg2 connection pool or None if not available.
    """
    global _db_pool
    if _db_pool is None:
        try:
            from psycopg2 import pool

            conn_string = get_db_connection_string()
            _db_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=conn_string,
                sslmode="require",
                connect_timeout=10,
            )
            logger.info("Database connection pool created")
        except Exception as e:
            logger.warning("Failed to create DB pool: %s", e)
            return None
    return _db_pool


@contextmanager
def db_connection():
    """Context manager for database connections.

    Yields:
        psycopg2 connection object.

    Example:
        with db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM profiles")
            rows = cur.fetchall()
    """
    pool = get_db_pool()
    if pool is None:
        raise RuntimeError("Database pool not available")

    conn = None
    try:
        conn = pool.getconn()
        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            pool.putconn(conn)


def verify_user_token(token: str) -> dict[str, Any] | None:
    """Verify Supabase JWT and return user info.

    Args:
        token: Supabase access token (from Authorization header).

    Returns:
        User dict with id, email, role, status, daily_quota or None if invalid.
    """
    try:
        # Reuse the anon client to avoid repeated initialization overhead.
        client = get_supabase_client(use_service_role=False)

        user = client.auth.get_user(token)
        if not user or not user.user:
            return None

        # Fetch profile via service-role client (server-side only).
        service_client = get_supabase_client(use_service_role=True)
        profile_result = service_client.table("profiles").select("*").eq("id", user.user.id).single().execute()

        if not profile_result.data:
            return None

        profile = profile_result.data
        # Handle both dict and MagicMock cases
        if hasattr(profile, "get"):
            role = profile.get("role", "user")
            status = profile.get("status", "active")
            daily_quota = profile.get("daily_quota", 5)
        else:
            role = getattr(profile, "role", "user")
            status = getattr(profile, "status", "active")
            daily_quota = getattr(profile, "daily_quota", 5)
        return {
            "id": user.user.id,
            "email": user.user.email,
            "role": role,
            "status": status,
            "daily_quota": daily_quota,
        }
    except Exception as e:
        logger.warning("Token verification failed: %s", e)
        return None


def check_invited_email(email: str) -> bool:
    """Check if email is in pending invites.

    Args:
        email: Email address to check.

    Returns:
        True if email is invited and not expired.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        result = client.rpc("is_invited_email", {"p_email": email.lower()}).execute()
        return bool(result.data) if result.data else False
    except Exception:
        logger.exception("Invite check failed")
        return False


def create_profile_for_user(user_id: str, email: str, daily_quota: int = 5) -> bool:
    """Create profile for a new user.

    Args:
        user_id: Auth user UUID.
        email: User email.
        daily_quota: Daily analysis quota.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.table("profiles").insert(
            {
                "id": user_id,
                "email": email,
                "role": "user",
                "status": "active",
                "daily_quota": daily_quota,
            }
        ).execute()
        return True
    except Exception:
        logger.exception("Profile creation failed")
        return False


def get_user_profile(user_id: str) -> dict[str, Any] | None:
    """Get user profile by ID.

    Args:
        user_id: User UUID.

    Returns:
        Profile dict or None.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        result = client.table("profiles").select("*").eq("id", user_id).single().execute()
        return result.data if result.data else None
    except Exception:
        logger.exception("Profile fetch failed")
        return None


def list_user_analyses(
    user_id: str, limit: int = 20, offset: int = 0, status: Optional[str] = None, market: Optional[str] = None
) -> list[dict[str, Any]]:
    """List analyses for a user.

    Args:
        user_id: User UUID.
        limit: Max results.
        offset: Pagination offset.
        status: Optional status filter.
        market: Optional market filter.

    Returns:
        List of analysis records.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        query = (
            client.table("analyses").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).offset(offset)
        )
        if status:
            query = query.eq("status", status)
        if market:
            query = query.eq("market", market)
        result = query.execute()
        return result.data or []
    except Exception:
        logger.exception("Analyses list failed")
        return []


def create_analysis_record(
    user_id: str,
    data: dict[str, Any],
    analysis_id: Optional[str] = None,
) -> str | None:
    """Create analysis record.

    Args:
        user_id: User UUID.
        data: Analysis data dict.
        analysis_id: Optional analysis UUID. If provided it is used as the
            record primary key, allowing callers to correlate the response ID
            with the persisted row.

    Returns:
        Analysis ID or None.
    """
    try:
        import uuid

        record_id = analysis_id if analysis_id else str(uuid.uuid4())
        record = {
            "id": record_id,
            "user_id": user_id,
            **data,
        }
        # Normalize values to the LIVE schema's CHECK constraints. The
        # analyses table on Supabase only allows analysis_type IN
        # ('forming','formed','divergence'), market IN ('binance','yahoo'),
        # interval IN ('15m','1h','4h','1d','1w'). The app enum is wider
        # (auto, futures, 1m, 5m) and the resolved type is only known after
        # the analysis runs — so we persist a legal placeholder here and the
        # record is updated to the final type/status after the run.
        _ANALYSIS_TYPE_MAP = {"auto": "forming"}
        _MARKET_MAP = {"futures": "binance"}
        _INTERVAL_MAP = {"1m": "15m", "5m": "15m"}
        record["analysis_type"] = _ANALYSIS_TYPE_MAP.get(record.get("analysis_type"), record.get("analysis_type"))
        record["market"] = _MARKET_MAP.get(record.get("market"), record.get("market"))
        record["interval"] = _INTERVAL_MAP.get(record.get("interval"), record.get("interval"))

        client = get_supabase_client(use_service_role=True)
        client.table("analyses").insert(record).execute()
        return record_id
    except Exception:
        logger.exception("Analysis creation failed")
        return None


def update_analysis_record(analysis_id: str, updates: dict[str, Any]) -> bool:
    """Update analysis record.

    Args:
        analysis_id: Analysis UUID.
        updates: Fields to update.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.table("analyses").update(updates).eq("id", analysis_id).execute()
        return True
    except Exception:
        logger.exception("Analysis update failed")
        return False


def delete_analysis_record(analysis_id: str) -> bool:
    """Delete an analysis record.

    Used to clean up a placeholder "created" row when quota reservation
    fails after the record was inserted (the row would otherwise be an
    orphan: usage_ledger FK requires the analyses row to exist BEFORE the
    quota RPC inserts its ledger entry).

    Args:
        analysis_id: Analysis UUID.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.table("analyses").delete().eq("id", analysis_id).execute()
        return True
    except Exception:
        logger.exception("Analysis delete failed")
        return False


def get_analysis_by_idem_key(user_id: str, idem_key: str) -> dict[str, Any] | None:
    """Return the most recent analysis row matching ``(user_id, idempotency_key)``.

    The route ``/api/analyze`` deduplicates retries by ``idempotency_key``:
    when the same user re-submits the same key within ``ANALYSIS_IDEM_CACHE_TTL``
    seconds the stored row is returned without burning an extra quota unit.

    The function first checks an in-process LRU so the hot path never
    touches Supabase; on miss it falls through to a single indexed lookup
    and caches the result (including negative results). Errors degrade
    gracefully to ``None`` so callers can still complete a fresh analysis.

    Returns:
        The row dict on hit, ``None`` on miss / error.
    """
    if not (user_id and idem_key):
        return None
    cache_key = (user_id, idem_key)
    now = time.time()

    with _idem_lock:
        cached = _idem_cache.get(cache_key)
        if cached is not None:
            ts, rec = cached
            if now - ts < _IDEM_CACHE_TTL_SECONDS:
                return rec
            _idem_cache.pop(cache_key, None)

    try:
        client = get_supabase_client(use_service_role=True)
        result = (
            client.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .eq("idempotency_key", idem_key)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rec = result.data[0] if result.data else None
    except Exception as e:  # noqa: BLE001 - any error = treat as miss
        logger.warning("get_analysis_by_idem_key lookup failed: %s", e)
        rec = None

    with _idem_lock:
        # Bounded insertion: drop the oldest entry when over capacity.
        if len(_idem_cache) >= _IDEM_CACHE_MAX_ENTRIES:
            oldest_key = min(_idem_cache, key=lambda k: _idem_cache[k][0])
            _idem_cache.pop(oldest_key, None)
        _idem_cache[cache_key] = (now, rec)
    return rec


def reset_idem_cache() -> None:
    """Clear the in-process idempotency lookup cache (test-only)."""
    with _idem_lock:
        _idem_cache.clear()


def reserve_user_quota(user_id: str, analysis_id: str | None, units: int = 1) -> tuple[bool, int, str | None]:
    """Reserve daily quota for user.

    Args:
        user_id: User UUID.
        analysis_id: Analysis UUID.
        units: Units to reserve.

    Returns:
        (success, remaining, ledger_id)
    """
    try:
        client = get_supabase_client(use_service_role=True)
        result = _reserve_quota_rpc(client, user_id, analysis_id, units)

        if not result.data:
            return False, 0, None

        row = result.data[0]
        reserved = row.get("reserved", False)
        remaining = row.get("remaining", 0)

        # Get ledger ID — find the most-recently-created 'reserved' row for this user.
        # analysis_id may be NULL (RSI-trend / vibe routes) so we can't filter on it.
        ledger_result = (
            client.table("usage_ledger")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "reserved")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        ledger_id = ledger_result.data[0]["id"] if ledger_result.data else None

        return reserved, remaining, ledger_id
    except Exception:
        logger.exception("Quota reservation failed")
        return False, 0, None


def _reserve_quota_rpc(
    client, user_id: str, analysis_id: str, units: int, retry_on_409: bool = True
):
    """Call the reserve_quota RPC. Retries once on PostgreSQL constraint/lock errors.

    postgrest.APIError has no .response attribute — status code is not accessible.
    PostgreSQL error codes 23xxx = constraint violations (FK, check); 40xxx =
    transaction rollbacks (advisory lock conflicts). Both can occur when concurrent
    requests race. Retry once; the outer reserve_user_quota() catches all failures
    and returns (False, 0, None) so the caller gets a safe 429.
    """
    try:
        return client.rpc(
            "reserve_quota",
            {
                "p_user_id": user_id,
                "p_analysis_id": analysis_id,
                "p_units": units,
            },
        ).execute()
    except Exception as e:
        # APIError has no .response attribute — inspect the error code string.
        # PostgreSQL error codes: 23xxx = constraint violations (FK, check, etc.)
        # These can occur when two concurrent requests race; retry once.
        # 40xxx = transaction rollback (advisory lock conflicts, serialization).
        code = str(getattr(e, "code", "") or "")
        if retry_on_409 and len(code) >= 2 and code[:2] in ("23", "40"):
            logger.warning("reserve_quota RPC got PostgreSQL %s error, retrying once: %s", code, e)
            return _reserve_quota_rpc(client, user_id, analysis_id, units, retry_on_409=False)
        raise


def consume_ledger_quota(
    ledger_id: str, input_tokens: Optional[int] = None, output_tokens: Optional[int] = None, cost_micros: Optional[int] = None
) -> bool:
    """Mark reserved quota as consumed.

    Args:
        ledger_id: Ledger entry UUID.
        input_tokens: Model input tokens.
        output_tokens: Model output tokens.
        cost_micros: Estimated cost in micros.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.rpc(
            "consume_quota",
            {
                "p_ledger_id": ledger_id,
                "p_input_tokens": input_tokens,
                "p_output_tokens": output_tokens,
                "p_cost_micros": cost_micros,
            },
        ).execute()
        return True
    except Exception:
        logger.exception("Quota consumption failed")
        return False


def release_ledger_quota(ledger_id: str) -> bool:
    """Release reserved quota back to user.

    Args:
        ledger_id: Ledger entry UUID.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.rpc(
            "release_quota",
            {
                "p_ledger_id": ledger_id,
            },
        ).execute()
        return True
    except Exception:
        logger.exception("Quota release failed")
        return False


def upload_chart(user_id: str, analysis_id: str, image_bytes: bytes) -> str | None:
    """Upload chart to Supabase Storage.

    Args:
        user_id: User UUID.
        analysis_id: Analysis UUID.
        image_bytes: PNG image bytes.

    Returns:
        Storage path or None.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        path = f"{user_id}/{analysis_id}.png"
        result = client.storage.from_("cryptoagg-bucket").upload(
            path,
            image_bytes,
            {
                "content-type": "image/png",
                "upsert": "true",
            },
        )
        if result:
            return path
        return None
    except Exception:
        logger.exception("Chart upload failed")
        return None


def get_chart_url(path: str, expires_in: int = 300) -> str | None:
    """Generate signed URL for chart download.

    Args:
        path: Storage path.
        expires_in: URL expiry in seconds.

    Returns:
        Signed URL or None.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        result = client.storage.from_("cryptoagg-bucket").create_signed_url(path, expires_in)
        return result.get("signedURL") if result else None
    except Exception:
        logger.exception("Chart URL generation failed")
        return None


def delete_chart(path: str) -> bool:
    """Delete chart from storage.

    Args:
        path: Storage path.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.storage.from_("cryptoagg-bucket").remove([path])
        return True
    except Exception:
        logger.exception("Chart deletion failed")
        return False


def log_audit_event(
    actor_id: Optional[str], action: str, target_type: str, target_id: Optional[str] = None, details: Optional[dict] = None
) -> bool:
    """Log audit event.

    Args:
        actor_id: User UUID who performed the action.
        action: Action name.
        target_type: Target type (user, invite, quota, etc.).
        target_id: Target identifier.
        details: Additional details dict.

    Returns:
        True if successful.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        client.table("audit_events").insert(
            {
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "details": details or {},
            }
        ).execute()
        return True
    except Exception:
        logger.exception("Audit logging failed")
        return False
