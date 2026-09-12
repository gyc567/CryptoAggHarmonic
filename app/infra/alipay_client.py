"""Alipay SkillPay integration client.

Provides:
  * :class:`AlipayClient`      — low-level alipay-bot CLI wrapper
  * :class:`SkillPayClient`    — high-level SkillPay operations
  * :func:`fulfill_skill`     — one-shot fulfill a purchase

SkillPay履约流程（基于 https://aipayapi.alipay.com 协议）:

  1. 接收 firsttimebuy 请求
  2. 若返回 "支付待确认" → 记录订单号，上报给用户
  3. 若返回 fulfillment_proof URL → 下载 + 安全解压 → 安装到 ~/.hermes/skills/
  4. 支付完成后用原订单号查询状态并恢复资源

环境变量:
  ALIPAY_MERCHANT_ID   — 商家 ID（从 skillpay.alipay.com 获取）
  ALIPAY_SKILL_ID      — 技能商品 ID
  HERMES_SKILLS_DIR    — 技能安装目录（默认 ~/.hermes/skills）
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERMES_SKILLS_DIR = Path(os.getenv("HERMES_SKILLS_DIR", str(Path.home() / ".hermes" / "skills")))

# Alipay SkillPay API endpoints
AGENTPAY_BASE   = "https://agentpay.alipay.com/ai-pay/proxy"
SKILLPAY_API    = "https://aipayapi.alipay.com"

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FulfillmentResult:
    success:        bool
    skill_name:     str | None = None
    install_path:   Path | None = None
    error:          str | None = None
    order_no:       str | None = None       # original order number
    payment_url:    str | None = None       # QR code URL if payment required
    already_paid:   bool = False            # True if order was already paid


@dataclass
class PaymentStatus:
    order_no:       str
    status:         str          # "PAID", "PENDING", "REFUNDED", "UNKNOWN"
    paid_at:        str | None
    skill_id:       str | None
    skill_name:     str | None


# ---------------------------------------------------------------------------
# AlipayClient — alipay-bot CLI wrapper
# ---------------------------------------------------------------------------

class AlipayClient:
    """Wrapper around the `alipay-bot` CLI tool.

    Requires `@alipay/agent-payment` npm package to be installed globally.

    Usage::

        client = AlipayClient()
        result = client.fulfill_skill("firsttimebuy")
    """

    def __init__(
        self,
        merchant_id: str | None = None,
        skill_id: str | None = None,
        alipay_bot_path: str | None = None,
    ):
        self.merchant_id = merchant_id or os.getenv("ALIPAY_MERCHANT_ID", "")
        self.skill_id    = skill_id    or os.getenv("ALIPAY_SKILL_ID", "")
        self._bot_path   = alipay_bot_path or self._find_alipay_bot()
        self._timeout    = 60.0

    # -- public API ---------------------------------------------------------

    def fulfill(
        self,
        prompt: str = "firsttimebuy",
        *,
        order_no: str | None = None,
        resource_url: str | None = None,
        method: str = "POST",
        data: str | None = None,
        skill_zip_url: str | None = None,
    ) -> dict[str, Any]:
        """Fulfill a skill purchase using alipay-bot skillpay command.

        Args:
            prompt:          Fulfillment prompt (default "firsttimebuy")
            order_no:        Existing order number (for payment recovery)
            resource_url:    Merchant resource URL for paid fulfillment
            method:          HTTP method (GET or POST)
            data:            Request body JSON string
            skill_zip_url:   Direct fulfillment proof URL (payment-exempt)

        Returns:
            Parsed JSON response from alipay-bot.
        """
        skill_zip_url = skill_zip_url or ""
        data_str = data or json.dumps({"prompt": prompt})

        cmd = [
            self._bot_path,
            "skillpay",
            "--json",
        ]

        if skill_zip_url:
            cmd += ["--fulfillment-proof", skill_zip_url]
        elif resource_url:
            cmd += [
                "--resource-url", resource_url,
                "--method", method,
                "--data", data_str,
                "--header", "Content-Type: application/json",
            ]
            if order_no:
                cmd += ["--out-shake-no", order_no]
        else:
            # Use default fulfillment URL
            fulfillment_url = self._fulfillment_url()
            cmd += [
                "--resource-url", fulfillment_url,
                "--method", "POST",
                "--data", data_str,
                "--header", "Content-Type: application/json",
            ]

        logger.info("Calling alipay-bot skillpay ...")
        raw = self._run(cmd)
        return self._parse_response(raw)

    def query_payment_status(
        self,
        order_no: str,
        *,
        resource_url: str | None = None,
        method: str = "POST",
        data: str | None = None,
    ) -> PaymentStatus:
        """Query payment status for an existing order.

        Args:
            order_no:      The original order number (out_shake_no)
            resource_url:  Override fulfillment URL
            method:        HTTP method
            data:          Request body

        Returns:
            PaymentStatus dataclass.
        """
        resource_url = resource_url or self._fulfillment_url()
        data_str = data or json.dumps({"prompt": "firsttimebuy"})

        cmd = [
            self._bot_path,
            "402-query-payment-status",
            "--out-shake-no", order_no,
            "--resource-url", resource_url,
            "--method", method,
            "--data", data_str,
            "--header", "Content-Type: application/json",
        ]

        logger.info("Querying payment status for order %s", order_no)
        raw = self._run(cmd)

        return self._parse_payment_status(raw, order_no)

    def check_bot_available(self) -> bool:
        """Return True if alipay-bot is installed and reachable."""
        try:
            result = subprocess.run(
                [self._bot_path, "--version"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("alipay-bot not available: %s", exc)
            return False

    # -- internal helpers --------------------------------------------------

    def _fulfillment_url(self) -> str:
        if not self.merchant_id or not self.skill_id:
            raise ValueError(
                "ALIPAY_MERCHANT_ID and ALIPAY_SKILL_ID must be set. "
                "Get them from https://skillpay.alipay.com → 创作者中心"
            )
        return f"{AGENTPAY_BASE}/{self.merchant_id}/{self.skill_id}"

    def _find_alipay_bot(self) -> str:
        """Locate alipay-bot-cli binary in PATH or common locations."""
        candidates = [
            "alipay-bot",          # when ~/.local/bin is in PATH
            str(Path.home() / ".local" / "bin" / "alipay-bot"),
        ]
        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    logger.info("Found alipay-bot at: %s", candidate)
                    return candidate
            except Exception:
                pass
        return "alipay-bot"  # fallback to PATH resolution

    def _run(self, cmd: list[str]) -> str:
        """Run a command, return stdout."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**os.environ, "NPX_YES": "1"},
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"alipay-bot timed out after {self._timeout}s")
        except Exception as exc:
            logger.error("alipay-bot command failed: %s", exc)
            raise

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse alipay-bot JSON output."""
        # alipay-bot outputs JSON with potential log prefix lines
        try:
            # Find first { or [ after any log lines
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    return json.loads(stripped)
            return {"raw": raw}
        except json.JSONDecodeError:
            return {"raw": raw}

    def _parse_payment_status(self, raw: str, order_no: str) -> PaymentStatus:
        """Parse alipay-bot payment status output."""
        parsed = self._parse_response(raw)

        # Try to extract status from parsed output
        status_text = str(parsed.get("status", parsed.get("trade_status", "")))
        if "PAID" in status_text.upper() or "TRADE_SUCCESS" in status_text.upper():
            status = "PAID"
        elif "PENDING" in status_text.upper() or "WAIT" in status_text.upper():
            status = "PENDING"
        elif "REFUND" in status_text.upper():
            status = "REFUNDED"
        else:
            status = "UNKNOWN"

        return PaymentStatus(
            order_no=order_no,
            status=status,
            paid_at=parsed.get("gmt_payment") or parsed.get("pay_time"),
            skill_id=parsed.get("skill_id"),
            skill_name=parsed.get("skill_name"),
        )


# ---------------------------------------------------------------------------
# SkillPayClient — high-level operations
# ---------------------------------------------------------------------------

class SkillPayClient:
    """High-level SkillPay operations.

    Usage::

        client = SkillPayClient(merchant_id="...", skill_id="...")
        result = client.fulfill_skill()
        if result.payment_url:
            print(f"请扫码支付: {result.payment_url}")
    """

    def __init__(
        self,
        merchant_id: str | None = None,
        skill_id: str | None = None,
    ):
        self.merchant_id = merchant_id or os.getenv("ALIPAY_MERCHANT_ID", "")
        self.skill_id    = skill_id    or os.getenv("ALIPAY_SKILL_ID", "")
        self._alipay    = AlipayClient(self.merchant_id, self.skill_id)

    def fulfill_skill(
        self,
        prompt: str = "firsttimebuy",
        *,
        skill_dir: Path | None = None,
        skill_zip_url: str | None = None,
    ) -> FulfillmentResult:
        """Attempt to fulfill a skill purchase.

        1. POST to agentpay.alipay.com
        2. If payment required → return payment URL
        3. If fulfillment_proof URL → download + install

        Args:
            prompt:        Prompt for the fulfillment endpoint
            skill_dir:     Override default ~/.hermes/skills/
            skill_zip_url: Direct zip URL (bypasses alipay-bot for manual install)

        Returns:
            FulfillmentResult with success/error/payment info.
        """
        if skill_zip_url:
            return self._install_from_url(skill_zip_url, skill_dir=skill_dir)

        # Use alipay-bot for fulfillment
        try:
            resp = self._alipay.fulfill(prompt=prompt)
        except Exception as exc:
            return FulfillmentResult(success=False, error=str(exc))

        return self._process_fulfillment_response(resp, skill_dir=skill_dir)

    def _process_fulfillment_response(
        self,
        resp: dict[str, Any],
        skill_dir: Path | None = None,
    ) -> FulfillmentResult:
        """Handle alipay-bot fulfillment response."""
        raw_str = json.dumps(resp, ensure_ascii=False)

        # Case A: Payment required
        if "支付待确认" in raw_str or "PAYMENT_REQUIRED" in raw_str:
            order_no = resp.get("order_no") or resp.get("out_trade_no", "")
            payment_url = resp.get("pay_url") or resp.get("qr_code") or ""
            return FulfillmentResult(
                success=False,
                order_no=order_no,
                payment_url=payment_url,
                error="PAYMENT_REQUIRED",
            )

        # Case B: Fulfillment URL provided
        fulfillment_url = (
            resp.get("fulfillment_proof")
            or resp.get("download_url")
            or resp.get("url")
        )
        if fulfillment_url and fulfillment_url.startswith("http"):
            return self._install_from_url(fulfillment_url, skill_dir=skill_dir)

        # Case C: Already fulfilled (success)
        if resp.get("success") is True or resp.get("fulfillment_result") == "SUCCESS":
            return FulfillmentResult(success=True, already_paid=True)

        # Case D: Unknown response
        return FulfillmentResult(
            success=False,
            error=f"Unhandled response: {raw_str[:500]}",
        )

    def _install_from_url(
        self,
        url: str,
        skill_dir: Path | None = None,
    ) -> FulfillmentResult:
        """Download, verify, and install a skill from a URL."""
        target_dir = skill_dir or HERMES_SKILLS_DIR

        try:
            with tempfile.TemporaryDirectory(prefix="skillpay_install_") as tmp:
                tmp_path = Path(tmp)
                archive_path = tmp_path / "skill_archive"

                # Step 1: Download with security checks
                logger.info("Downloading skill from %s", url)
                self._secure_download(url, archive_path)

                # Step 2: Extract
                skill_root = self._secure_extract(archive_path, tmp_path)
                if skill_root is None:
                    return FulfillmentResult(
                        success=False,
                        error="Archive extraction failed or no SKILL.md found",
                    )

                # Step 3: Validate SKILL.md
                skill_md = skill_root / "SKILL.md"
                if not skill_md.is_file():
                    return FulfillmentResult(
                        success=False,
                        error="Archive does not contain SKILL.md",
                    )

                # Step 4: Read skill name
                skill_name = self._read_skill_name(skill_md)
                if not skill_name:
                    return FulfillmentResult(
                        success=False,
                        error="SKILL.md missing required metadata",
                    )

                # Step 5: Install
                install_path = target_dir / skill_name
                self._install_to(skill_root, install_path)

                logger.info("Skill '%s' installed to %s", skill_name, install_path)
                return FulfillmentResult(
                    success=True,
                    skill_name=skill_name,
                    install_path=install_path,
                )

        except Exception as exc:
            logger.exception("Skill installation failed: %s", exc)
            return FulfillmentResult(success=False, error=str(exc))

    # -- security-hardened download + extract --------------------------------

    def _secure_download(self, url: str, dest: Path) -> None:
        """Download a file with path-traversal and size guards."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Only HTTP/HTTPS URLs allowed, got: {url}")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Hermes-Alipay-Client/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > 100 * 1024 * 1024:
                raise ValueError("File too large (max 100MB)")

            # Stream to disk to avoid memory bloat
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

    def _secure_extract(self, archive_path: Path, tmp_dir: Path) -> Path | None:
        """Extract archive with path-traversal guards.

        Returns the directory containing SKILL.md, or None on failure.
        """
        try:
            if archive_path.suffix in (".tar", ".gz", ".tgz", ".tar.gz"):
                mode = "r:gz" if archive_path.suffix == ".gz" else "r"
                with tarfile.open(archive_path, mode=mode) as tf:
                    self._validate_archive_members(tf)
                    tf.extractall(tmp_dir)
            elif archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    self._validate_zip_members(zf)
                    zf.extractall(tmp_dir)
            else:
                # Try tar.gz fallback
                try:
                    with tarfile.open(archive_path, "r:gz") as tf:
                        self._validate_archive_members(tf)
                        tf.extractall(tmp_dir)
                except Exception:
                    raise ValueError(f"Unsupported archive format: {archive_path.suffix}")

        except Exception as exc:
            logger.warning("Archive extraction failed: %s", exc)
            return None

        # Find SKILL.md root
        for item in tmp_dir.rglob("SKILL.md"):
            if item.is_file():
                return item.parent
        return None

    def _validate_archive_members(self, tf: tarfile.TarFile) -> None:
        """Reject archives with path-traversal or absolute paths."""
        for member in tf.getmembers():
            if not member.name:
                continue
            normalized = os.path.normpath(member.name)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"Unsafe archive member: {member.name}")
            if ".." in normalized:
                raise ValueError(f"Path traversal detected: {member.name}")

    def _validate_zip_members(self, zf: zipfile.ZipFile) -> None:
        """Reject zip files with path-traversal or absolute paths."""
        for member in zf.namelist():
            normalized = os.path.normpath(member)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"Unsafe zip member: {member}")
            if ".." in normalized:
                raise ValueError(f"Path traversal detected: {member}")

    def _read_skill_name(self, skill_md: Path) -> str | None:
        """Extract skill name from SKILL.md frontmatter."""
        try:
            text = skill_md.read_text(encoding="utf-8")
            # Try YAML frontmatter
            if text.startswith("---"):
                end = text.index("---", 3)
                frontmatter = text[3:end]
                for line in frontmatter.splitlines():
                    if line.strip().startswith("name:"):
                        return line.split("name:", 1)[1].strip().strip("\"'")
            # Fallback: look for name field anywhere
            match = re.search(r'^name:\s*(.+)$', text, re.MULTILINE)
            if match:
                return match.group(1).strip().strip("\"'")
            return None
        except Exception as exc:
            logger.warning("Failed to read skill name from %s: %s", skill_md, exc)
            return None

    def _install_to(self, skill_root: Path, install_path: Path) -> None:
        """Move skill to target directory, backing up existing version."""
        target_dir = install_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        if install_path.exists():
            backup = install_path.with_name(
                install_path.name + f".backup-{int(time.time())}"
            )
            shutil.move(str(install_path), str(backup))
            logger.info("Backed up existing skill to %s", backup)

        shutil.copytree(skill_root, install_path)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def fulfill_skill(
    merchant_id: str | None = None,
    skill_id: str | None = None,
    skill_zip_url: str | None = None,
) -> FulfillmentResult:
    """One-shot skill fulfillment.

    Use this for simple integrations where you just need to install a skill.

    Example::

        result = fulfill_skill(
            merchant_id="2088902259764064",
            skill_id="S0806000200878896",
        )
        if result.payment_url:
            print(f"请扫码: {result.payment_url}")
        elif result.success:
            print(f"安装成功: {result.install_path}")
    """
    client = SkillPayClient(merchant_id=merchant_id, skill_id=skill_id)
    return client.fulfill_skill(skill_zip_url=skill_zip_url)
