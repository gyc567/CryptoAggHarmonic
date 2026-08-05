"""Shared LLM client factory.

Provides a thread-safe singleton OpenAI client for all consumers:
- ``app/openai_handler.py`` (legacy query endpoint)
- ``app/services/vibe/llm/openai_provider.py`` (vibe agent)

This module has NO side effects at import time (no load_dotenv, no client creation).
Call ``get_llm_client()`` to get the lazily-initialized singleton.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

# Module-level constants read from environment on first call to get_llm_client().
_api_key: str | None = None
_api_base_url: str | None = None
_request_timeout: int = 60

_client: "OpenAI | None" = None
_client_lock = threading.Lock()


def _ensure_env() -> None:
    """Ensure environment variables are loaded. Idempotent."""
    global _api_key, _api_base_url, _request_timeout
    if _api_key is None:
        # Import dotenv lazily to avoid polluting module namespace.
        from dotenv import load_dotenv

        load_dotenv()
        _api_key = os.getenv("OPENAI_API_KEY") or "dummy-key-for-testing"
        _api_base_url = os.getenv("OPENAI_API_BASE_URL")
        _request_timeout = int(os.getenv("OPENAI_REQUEST_TIMEOUT", "60"))


def get_llm_client() -> "OpenAI":
    """Thread-safe lazy client initialization.

    Environment variables are loaded on first call if not already loaded.
    Subsequent calls return the cached singleton.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # Double-check after acquiring lock.
                _ensure_env()
                from openai import OpenAI

                kwargs: dict = {
                    "api_key": _api_key,
                    "timeout": _request_timeout,
                }
                if _api_base_url:
                    kwargs["base_url"] = _api_base_url
                _client = OpenAI(**kwargs)
    return _client


def reset_client() -> None:
    """Reset the client singleton. For testing only."""
    global _client
    with _client_lock:
        _client = None
