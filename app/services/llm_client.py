"""Minimal LLM client for the RSI trading plan.

Intentionally separate from the vibe assistant — this module only needs
a single ``prompt → completion`` call, not a streaming conversation loop.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---- configuration -----------------------------------------------------------

_API_KEY = os.environ.get("RSI_PLAN_OPENAI_API_KEY")
_BASE_URL = os.environ.get("RSI_PLAN_OPENAI_BASE_URL", "https://api.openai.com/v1")
_MODEL = os.environ.get("RSI_PLAN_OPENAI_MODEL", "gpt-4o-mini")
_TIMEOUT_S = 10.0
_MAX_RETRIES = 1


# ---- public api --------------------------------------------------------------


def complete(prompt: str, *, max_tokens: int = 300, timeout: float = _TIMEOUT_S) -> Optional[str]:
    """Call the LLM and return the completion text, or ``None`` on failure."""
    if not _API_KEY:
        logger.warning("RSI_PLAN_OPENAI_API_KEY not set; LLM call skipped")
        return None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            return _call(prompt, max_tokens=max_tokens, timeout=timeout)
        except Exception:
            if attempt < _MAX_RETRIES:
                time.sleep(min(2 ** attempt, 4))
            else:
                logger.warning("LLM call failed after %d retries", _MAX_RETRIES, exc_info=True)
                return None
    return None


# ---- internal ----------------------------------------------------------------

def _call(prompt: str, *, max_tokens: int, timeout: float) -> Optional[str]:
    import requests

    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    resp = requests.post(
        f"{_BASE_URL}/chat/completions",
        headers=headers,
        json=body,
        timeout=timeout,
    )
    if resp.status_code != 200:
        logger.warning("LLM returned %d: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        return None
    content = choices[0].get("message", {}).get("content")
    return content.strip() if content else None
