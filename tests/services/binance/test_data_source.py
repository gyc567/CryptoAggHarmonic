"""Tests for the binance-cli data source (Loop #12).

Pinned to the actual CLI installed at /Users/jie/.hermes/node/bin/binance-cli
(v1.3.0). If the binary is missing, all tests are skipped (so a dev
machine without npm install doesn't fail). When the binary IS present,
tests verify the real round-trip — the CLI spawn is fast (~10ms node
boot + ~400ms REST) and the assertions are exact, not loose bounds.
"""

from __future__ import annotations

import shutil

import pytest

from app.services.binance import data_source
from app.services.binance.data_source import (
    BinanceCliError,
    fetch_funding_history,
    fetch_mark_price,
    fetch_open_interest,
)


def _binance_cli_available() -> bool:
    return shutil.which(data_source.BINANCE_CLI_BIN) is not None


pytestmark = pytest.mark.skipif(
    not _binance_cli_available(),
    reason=f"binance-cli binary not found at {data_source.BINANCE_CLI_BIN}",
)


# ── Smoke tests against the live CLI ──────────────────────────────────────


def test_fetch_mark_price_returns_dataclass() -> None:
    mp = fetch_mark_price("BTCUSDT")
    assert mp.symbol == "BTCUSDT"
    assert mp.mark_price > 0
    assert mp.index_price > 0
    assert mp.last_funding_rate >= 0
    assert mp.next_funding_time > 0
    assert mp.time > 0


def test_fetch_open_interest_returns_dataclass() -> None:
    oi = fetch_open_interest("BTCUSDT")
    assert oi.symbol == "BTCUSDT"
    assert oi.open_interest > 0
    assert oi.time > 0


def test_fetch_funding_history_returns_list() -> None:
    hist = fetch_funding_history("BTCUSDT", limit=5)
    assert isinstance(hist, list)
    assert len(hist) >= 1
    entry = hist[0]
    assert entry.symbol == "BTCUSDT"
    assert entry.funding_rate >= 0
    assert entry.funding_time > 0


# ── Parser unit tests (no CLI call) ─────────────────────────────────────────


def test_parse_json_handles_eagain_warning_leading_line() -> None:
    """The CLI sometimes emits an EAGAIN warning to stdout when stdin is not a TTY."""
    # Find first JSON-looking line
    out = (
        "\nError reading stdin: Error: EAGAIN: resource temporarily unavailable\n"
        "{\n"
        ' "symbol": "BTCUSDT",\n'
        ' "markPrice": "63557.41"\n'
        "}\n"
    )
    parsed = data_source._parse_json(out, ["test"])
    assert parsed == {"symbol": "BTCUSDT", "markPrice": "63557.41"}


def test_parse_json_handles_array() -> None:
    out = "warning-line\n[{\"a\": 1}, {\"a\": 2}]\n"
    parsed = data_source._parse_json(out, ["test"])
    assert parsed == [{"a": 1}, {"a": 2}]


def test_parse_json_raises_on_empty() -> None:
    with pytest.raises(BinanceCliError, match="empty stdout"):
        data_source._parse_json("", ["test"])


def test_parse_json_raises_on_no_json() -> None:
    with pytest.raises(BinanceCliError, match="no JSON"):
        data_source._parse_json("just plain text\nno braces here\n", ["test"])


def test_parse_json_raises_on_malformed() -> None:
    with pytest.raises(BinanceCliError, match="JSON parse failed"):
        data_source._parse_json('{"unterminated": ', ["test"])


# ── DTO validation ─────────────────────────────────────────────────────────


def test_fetch_mark_price_rejects_unknown_symbol() -> None:
    """An unknown symbol returns an empty / error payload that we should surface."""
    with pytest.raises(BinanceCliError):
        fetch_mark_price("NOTAREALSYMBOL123", timeout_s=5.0)


def test_fetch_funding_history_validates_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        fetch_funding_history("BTCUSDT", limit=0)
    with pytest.raises(ValueError, match="limit"):
        fetch_funding_history("BTCUSDT", limit=-1)


# ── Timeout / subprocess resilience ────────────────────────────────────────


def test_timeout_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forced timeout raises BinanceCliError with timeout context."""
    import subprocess as sp

    def fake_run(*args, **kwargs):  # noqa: ANN001
        raise sp.TimeoutExpired(cmd=["fake"], timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(sp, "run", fake_run)
    with pytest.raises(BinanceCliError, match="timed out"):
        data_source._run_cli(["futures-usds", "mark-price"], timeout_s=2.0)


def test_missing_binary_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing binance-cli binary raises BinanceCliError, not FileNotFoundError."""
    monkeypatch.setattr(data_source, "BINANCE_CLI_BIN", "/nonexistent/path/cli")
    with pytest.raises(BinanceCliError, match="not found"):
        data_source._run_cli(["futures-usds", "mark-price"])


def test_subprocess_called_with_shell_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0013 D3: argv list + shell=False."""
    import subprocess as sp

    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        # Mimic a JSON-OK response
        class _P:
            returncode = 0
            stdout = '{"symbol": "BTCUSDT", "markPrice": "1.0", "indexPrice": "1.0", "estimatedSettlePrice": "1.0", "lastFundingRate": "0", "nextFundingTime": 1, "time": 1}'
            stderr = ""
        return _P()

    monkeypatch.setattr(sp, "run", fake_run)
    data_source._run_cli(["futures-usds", "mark-price", "--symbol", "BTCUSDT"])
    assert captured["kwargs"].get("shell") is False
    assert isinstance(captured["argv"], list)
    assert "--json" in captured["argv"]
    assert "shell=True" not in str(captured["kwargs"])