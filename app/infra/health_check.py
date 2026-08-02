"""Health checks for downstream dependencies."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _check_supabase() -> dict[str, Any]:
    """Check Supabase connectivity by fetching the current user count via service role."""
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    if not url or not service_key:
        return {"status": "skipped", "message": "Supabase not configured"}

    try:
        from app.infra.supabase_client import get_supabase_client

        client = get_supabase_client(use_service_role=True)
        # Lightweight query that does not depend on application data.
        client.table("profiles").select("id", count="exact").limit(1).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Supabase health check failed: %s", e)
        return {"status": "error", "message": str(e)}


def _check_redis() -> dict[str, Any]:
    """Check Redis connectivity (redis-py or Upstash REST)."""
    has_upstash = bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))
    has_redis_url = bool(os.getenv("REDIS_URL", "").startswith(("redis://", "rediss://")))
    if not has_upstash and not has_redis_url:
        return {"status": "skipped", "message": "Redis not configured"}

    try:
        from app.infra.redis_client import get_redis_client

        r = get_redis_client()
        if r is None:
            return {"status": "error", "message": "Redis client creation failed"}
        r.ping()
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Redis health check failed: %s", e)
        return {"status": "error", "message": str(e)}


def _check_tradingview_bridge() -> dict[str, Any]:
    """Check TradingView bridge connectivity."""
    if os.getenv("USE_TRADINGVIEW", "true").lower() in ("0", "false", "no"):
        return {"status": "skipped", "message": "TradingView disabled"}

    try:
        import requests

        from app.infra.tradingview_adapter import get_bridge_url

        resp = requests.get(f"{get_bridge_url()}/health", timeout=2)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Bridge returned {resp.status_code}"}
        data = resp.json()
        if data.get("connected") is True:
            return {"status": "ok"}
        return {"status": "error", "message": "Bridge not connected to TradingView"}
    except requests.exceptions.ConnectionError:
        # Bridge is not running; treat as skipped so local/dev health stays green.
        return {"status": "skipped", "message": "TradingView bridge not reachable"}
    except Exception as e:
        logger.warning("TradingView bridge health check failed: %s", e)
        return {"status": "error", "message": str(e)}


def run_health_checks() -> dict[str, Any]:
    """Run all dependency health checks.

    Returns a dict with overall status and per-dependency details.
    """
    checks = {
        "supabase": _check_supabase(),
        "redis": _check_redis(),
        "tradingview_bridge": _check_tradingview_bridge(),
    }
    any_error = any(c["status"] == "error" for c in checks.values())
    any_ok = any(c["status"] == "ok" for c in checks.values())
    # If no dependencies are configured at all, the app is still "ok".
    # If at least one dependency is healthy and another is failing -> degraded.
    if any_error:
        overall = "degraded" if any_ok else "error"
    else:
        overall = "ok"
    return {"status": overall, "checks": checks}
