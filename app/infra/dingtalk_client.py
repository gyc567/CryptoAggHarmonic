"""DingTalk Webhook client with signature support.

Supports:
  * Markdown-formatted robot messages
  * HMAC-SHA256 signature (加签) mode
  * Automatic retry on transient failures
  * Structured signal card format
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

SIGNAL_GRADE_THRESHOLDS = {
    "strong": 80,
    "medium": 60,
    "skip":   0,
}


@dataclass(frozen=True)
class DingTalkMessage:
    """A single DingTalk Markdown message."""

    title: str
    text: str  # Markdown content

    def to_webhook_payload(self, webhook_url: str, secret: str | None) -> dict[str, Any]:
        """Build the HTTP body dict for the DingTalk API."""
        body: dict[str, Any] = {
            "msgtype": "markdown",
            "markdown": {
                "title": self.title,
                "content": self.text,
            },
        }
        # Add at most one action_card to avoid API rejection
        return body


# ---------------------------------------------------------------------------
# Signature (加签) helpers
# ---------------------------------------------------------------------------

def _compute_sign(secret: str) -> tuple[str, str]:
    """Return (timestamp, sign) for DingTalk加签.

    Algorithm:
      1. timestamp = current unix ms
      2. sign_str  = timestamp + "\\n" + secret
      3. sign = Base64(HmacSHA256(sign_str))
    """
    timestamp = str(round(time.time() * 1000))
    sign_str  = f"{timestamp}\n{secret}"
    signature = base64.b64encode(
        hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).digest()
    ).decode()
    return timestamp, signature


def _build_url(webhook_url: str, secret: str | None) -> str:
    """Append timestamp + sign query params if secret is configured."""
    if not secret:
        return webhook_url
    timestamp, sign = _compute_sign(secret)
    sep = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{sep}timestamp={timestamp}&sign={sign}"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DingTalkClient:
    """Thread-safe DingTalk Webhook sender.

    Usage:
        client = DingTalkClient()
        client.send(message, webhook_url="https://oapi.dingtalk.com/...", secret="SEC...")
    """

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ):
        self._timeout    = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def send(
        self,
        message: DingTalkMessage,
        webhook_url: str,
        secret: str | None = None,
    ) -> bool:
        """Send a Markdown message to the DingTalk webhook.

        Returns True on success, False on final failure.
        """
        if not webhook_url:
            logger.warning("DingTalk webhook URL is empty — skipping send")
            return False

        url  = _build_url(webhook_url, secret)
        body = message.to_webhook_payload(webhook_url, secret)

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._http.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                data = resp.json()

                if resp.status_code == 200 and data.get("errcode") == 0:
                    logger.debug("DingTalk send OK (attempt %d)", attempt + 1)
                    return True

                # DingTalk returns errcode 43004 when the robot is blocked (群风控)
                errcode = data.get("errcode", 0)
                if errcode in (43004, 43005):
                    logger.error(
                        "DingTalk robot blocked (errcode=%d). "
                        "Check robot security settings in DingTalk group.",
                        errcode,
                    )
                    return False

                logger.warning(
                    "DingTalk API error: errcode=%d, errmsg=%s (attempt %d)",
                    errcode, data.get("errmsg"), attempt + 1,
                )

            except httpx.TimeoutException:
                logger.warning("DingTalk request timeout (attempt %d/%d)", attempt + 1, self._max_retries + 1)
            except httpx.HTTPError as exc:
                logger.warning("DingTalk HTTP error: %s (attempt %d/%d)", exc, attempt + 1, self._max_retries + 1)

            if attempt < self._max_retries:
                time.sleep(self._retry_delay * (attempt + 1))

        logger.error("DingTalk send failed after %d attempts", self._max_retries + 1)
        return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
