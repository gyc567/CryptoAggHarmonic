"""Supabase client module for Pyharmonics SaaS.

Supports both REST API (via supabase-py) and direct PostgreSQL connections.
Handles proxy environments and connection pooling.
"""
import os
import logging
import urllib.parse
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

# Import create_client at module level for testability
try:
    from supabase import create_client as _create_supabase_client
except ImportError:
    _create_supabase_client = None  # type: ignore

logger = logging.getLogger(__name__)

# Lazy-loaded clients keyed by role to avoid anon/service_role cross-over.
_supabase_clients: Dict[str, Any] = {}
_db_pool: Optional[Any] = None


def _get_proxy_settings() -> Dict[str, str]:
    """Get proxy settings from environment."""
    proxies = {}
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if os.getenv(key):
            proxies[key.lower().replace('_proxy', '')] = os.getenv(key)
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
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY) environment variable not set"
        )
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
        return urllib.parse.urlunparse(
            (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
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


def verify_user_token(token: str) -> Optional[Dict[str, Any]]:
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
        if hasattr(profile, 'get'):
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
    except Exception as e:
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
        client.table("profiles").insert({
            "id": user_id,
            "email": email,
            "role": "user",
            "status": "active",
            "daily_quota": daily_quota,
        }).execute()
        return True
    except Exception as e:
        logger.exception("Profile creation failed")
        return False


def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
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
    except Exception as e:
        logger.exception("Profile fetch failed")
        return None


def list_user_analyses(user_id: str, limit: int = 20, offset: int = 0,
                       status: Optional[str] = None, market: Optional[str] = None) -> List[Dict[str, Any]]:
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
        query = client.table("analyses").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).offset(offset)
        if status:
            query = query.eq("status", status)
        if market:
            query = query.eq("market", market)
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.exception("Analyses list failed")
        return []


def create_analysis_record(
    user_id: str,
    data: Dict[str, Any],
    analysis_id: Optional[str] = None,
) -> Optional[str]:
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
        client = get_supabase_client(use_service_role=True)
        client.table("analyses").insert(record).execute()
        return record_id
    except Exception as e:
        logger.exception("Analysis creation failed")
        return None


def update_analysis_record(analysis_id: str, updates: Dict[str, Any]) -> bool:
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
    except Exception as e:
        logger.exception("Analysis update failed")
        return False


def reserve_user_quota(user_id: str, analysis_id: str, units: int = 1) -> tuple[bool, int, Optional[str]]:
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
        result = client.rpc("reserve_quota", {
            "p_user_id": user_id,
            "p_analysis_id": analysis_id,
            "p_units": units,
        }).execute()

        if not result.data:
            return False, 0, None

        row = result.data[0]
        reserved = row.get("reserved", False)
        remaining = row.get("remaining", 0)

        # Get ledger ID
        ledger_result = client.table("usage_ledger").select("id").eq("user_id", user_id).eq("analysis_id", analysis_id).eq("status", "reserved").order("created_at", desc=True).limit(1).execute()
        ledger_id = ledger_result.data[0]["id"] if ledger_result.data else None

        return reserved, remaining, ledger_id
    except Exception as e:
        logger.exception("Quota reservation failed")
        return False, 0, None


def consume_ledger_quota(ledger_id: str, input_tokens: Optional[int] = None,
                         output_tokens: Optional[int] = None, cost_micros: Optional[int] = None) -> bool:
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
        client.rpc("consume_quota", {
            "p_ledger_id": ledger_id,
            "p_input_tokens": input_tokens,
            "p_output_tokens": output_tokens,
            "p_cost_micros": cost_micros,
        }).execute()
        return True
    except Exception as e:
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
        client.rpc("release_quota", {
            "p_ledger_id": ledger_id,
        }).execute()
        return True
    except Exception as e:
        logger.exception("Quota release failed")
        return False


def upload_chart(user_id: str, analysis_id: str, image_bytes: bytes) -> Optional[str]:
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
        result = client.storage.from_("pyharmonics-gpt-bucket").upload(path, image_bytes, {
            "content-type": "image/png",
            "upsert": "true",
        })
        if result:
            return path
        return None
    except Exception as e:
        logger.exception("Chart upload failed")
        return None


def get_chart_url(path: str, expires_in: int = 300) -> Optional[str]:
    """Generate signed URL for chart download.

    Args:
        path: Storage path.
        expires_in: URL expiry in seconds.

    Returns:
        Signed URL or None.
    """
    try:
        client = get_supabase_client(use_service_role=True)
        result = client.storage.from_("pyharmonics-gpt-bucket").create_signed_url(path, expires_in)
        return result.get("signedURL") if result else None
    except Exception as e:
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
        client.storage.from_("pyharmonics-gpt-bucket").remove([path])
        return True
    except Exception as e:
        logger.exception("Chart deletion failed")
        return False


def log_audit_event(actor_id: Optional[str], action: str, target_type: str,
                    target_id: Optional[str] = None, details: Optional[Dict] = None) -> bool:
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
        client.table("audit_events").insert({
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
        }).execute()
        return True
    except Exception as e:
        logger.exception("Audit logging failed")
        return False
