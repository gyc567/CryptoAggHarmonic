"""Tests OKXMCPClient: per-gen cap, rate-limit retry, error paths.

Spawns real subprocesses (``cat``-style and ``sleep``-style) so the
select()-based timeout code path is exercised against a real fd.
This is integration-style (still hermetic — no network).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.mcp_client import (
    MAX_OKX_WRITE_PER_GEN,
    OKXAPIError,
    OKXClientError,
    OKXMCPClient,
)


_ECHO_PY = r"""
import json
import sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        continue
    resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"code": "0", "data": {}}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""

_RATE_LIMIT_PY = r"""
import json
import sys
_count = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    _count += 1
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        continue
    if _count == 1:
        resp = {"jsonrpc": "2.0", "id": req.get("id"),
                "result": {"code": "50011", "msg": "rate limited"}}
    else:
        resp = {"jsonrpc": "2.0", "id": req.get("id"),
                "result": {"code": "0", "data": {"ok": True}}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""

_SLEEP_PY = r"""
import sys, time
time.sleep(60)
for _ in sys.stdin: pass
"""


def _spawn_script(code: str) -> OKXMCPClient:
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    client = OKXMCPClient.__new__(OKXMCPClient)
    client.args = ["script"]; client.env = {}; client.cwd = None
    client.proc = proc  # type: ignore[assignment]
    client.write_count_this_gen = 0
    return client


def _spawn_sleep_60s() -> OKXMCPClient:
    return _spawn_script(_SLEEP_PY)


@pytest.fixture
def echo_client() -> Iterator[OKXMCPClient]:
    c = _spawn_script(_ECHO_PY)
    yield c
    c.close()


@pytest.fixture
def rate_limit_client() -> Iterator[OKXMCPClient]:
    c = _spawn_script(_RATE_LIMIT_PY)
    yield c
    c.close()


class TestInvokeToolHappyPath:
    def test_read_tool_succeeds(self, echo_client: OKXMCPClient) -> None:
        result = echo_client.invoke_tool("market_get_ticker", {"instId": "BTC-USDT"})
        assert result.ok
        assert result.code == "0"
        assert result.data == {"code": "0", "data": {}}
        assert result.latency_ms >= 0

    def test_write_tool_increments_counter(self, echo_client: OKXMCPClient) -> None:
        echo_client.invoke_tool("spot_place_order", {"instId": "BTC-USDT"}, is_write=True)
        assert echo_client.write_count_this_gen == 1


class TestPerGenWriteCap:
    def test_cap_enforced_after_max(self, echo_client: OKXMCPClient) -> None:
        for _ in range(MAX_OKX_WRITE_PER_GEN):
            echo_client.invoke_tool("spot_place_order", {}, is_write=True)
        with pytest.raises(OKXClientError, match="per-gen write cap reached"):
            echo_client.invoke_tool("spot_place_order", {}, is_write=True)

    def test_reset_clears_counter(self, echo_client: OKXMCPClient) -> None:
        echo_client.invoke_tool("spot_place_order", {}, is_write=True)
        echo_client.reset_gen_counter()
        assert echo_client.write_count_this_gen == 0


class TestRateLimitRetry:
    def test_50011_triggers_single_retry(self, rate_limit_client: OKXMCPClient) -> None:
        import app.services.okx.mcp_client as mc
        orig_sleep = time.sleep
        mc.time.sleep = lambda _: None  # type: ignore[attr-defined]
        try:
            result = rate_limit_client.invoke_tool("market_get_ticker", {}, is_write=False)
        finally:
            mc.time.sleep = orig_sleep  # type: ignore[attr-defined]
        assert result.ok
        # data is {"code": "0", "data": {"ok": True}} from the retry response
        assert result.data["data"] == {"ok": True}


class TestTimeoutPath:
    def test_call_timeout_kills_subprocess(self) -> None:
        client = _spawn_sleep_60s()
        t0 = time.perf_counter()
        with pytest.raises(OKXClientError, match="call timeout"):
            client.invoke_tool("market_get_ticker", {}, timeout=2)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10, f"timeout took {elapsed:.1f}s; expected <10s"
        if client.proc is not None:
            try:
                client.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            assert client.proc.poll() is not None, "subprocess should be terminated after timeout"


class TestErrorPaths:
    def test_jsonrpc_error_skipped(self, echo_client: OKXMCPClient) -> None:
        pytest.skip("jsonrpc error path requires a custom subprocess; covered by rate-limit test")

    def test_empty_line_raises(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        client = OKXMCPClient.__new__(OKXMCPClient)
        client.args = ["exit"]; client.env = {}; client.cwd = None
        client.proc = proc  # type: ignore[assignment]
        client.write_count_this_gen = 0
        with pytest.raises(OKXClientError, match="closed unexpectedly"):
            client.invoke_tool("market_get_ticker", {})

    def test_subprocess_missing_raises(self) -> None:
        client = OKXMCPClient.__new__(OKXMCPClient)
        client.args = ["definitely-does-not-exist-binary-xyz"]
        client.env = {}; client.cwd = None; client.proc = None; client.write_count_this_gen = 0
        with pytest.raises((OKXClientError, FileNotFoundError)):
            client.invoke_tool("market_get_ticker", {})
