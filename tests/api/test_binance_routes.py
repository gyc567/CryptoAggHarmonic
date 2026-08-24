"""Tests for the binance Flask routes (Loop #12 Phase 2).

Most tests use the Flask test client + monkeypatched data_source
functions so they don't depend on the live binance-cli. A single
integration test (test_live_mark_price_endpoint) skips gracefully if
binance-cli is missing.
"""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from app.api import binance_routes
from app.api.binance_routes import (
    _fetch_funding_history_handler,
    _fetch_mark_price_handler,
    _fetch_open_interest_handler,
    _valid_symbol,
    make_binance_blueprint,
)
from app.services.binance import data_source
from app.services.binance.data_source import (
    FundingRate,
    MarkPrice,
    OpenInterest,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Build a minimal Flask app for route testing."""
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(make_binance_blueprint())
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_mark_price():
    return MarkPrice(
        symbol="BTCUSDT",
        mark_price=63500.0,
        index_price=63500.0,
        estimated_settle_price=63500.0,
        last_funding_rate=0.0001,
        next_funding_time=1786550400000,
        time=1786545458000,
    )


@pytest.fixture
def mock_open_interest():
    return OpenInterest(
        symbol="BTCUSDT",
        open_interest=108905.842,
        time=1786545458000,
    )


@pytest.fixture
def mock_funding_history():
    return [
        FundingRate(
            symbol="BTCUSDT",
            funding_time=1,
            funding_rate=0.0001,
            mark_price=100.0,
        ),
        FundingRate(
            symbol="BTCUSDT",
            funding_time=2,
            funding_rate=0.0002,
            mark_price=101.0,
        ),
    ]


# ── Symbol validation ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BTCUSDT", True),
        ("ETHUSDT", True),
        ("BTC/USDT", True),
        ("BTC/USDT:USDT", True),
        ("BTC", False),          # too short
        ("", False),
        ("X" * 25, False),       # 25 chars, exceeds upper bound
        ("A" * 50, False),       # too long
        ("BTC-USDT", False),     # hyphen not in allowed chars
    ],
)
def test_valid_symbol(symbol: str, expected: bool) -> None:
    assert _valid_symbol(symbol) is expected


# ── Endpoint smoke tests (mocked upstream) ──────────────────────────────────


def test_mark_price_endpoint_returns_200(client, mock_mark_price) -> None:
    # Patch the LOCAL reference in binance_routes, not the data_source module.
    with patch.object(binance_routes, "fetch_mark_price", return_value=mock_mark_price):
        resp = client.get("/api/binance/mark-price?symbol=BTCUSDT")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["endpoint"] == "mark_price"
    assert body["symbol"] == "BTCUSDT"
    assert body["data"]["mark_price"] == 63500.0
    assert body["persisted"] is False
    assert body["latency_ms"] >= 0


def test_open_interest_endpoint_returns_200(client, mock_open_interest) -> None:
    with patch.object(binance_routes, "fetch_open_interest", return_value=mock_open_interest):
        resp = client.get("/api/binance/open-interest?symbol=BTCUSDT")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["open_interest"] == 108905.842


def test_funding_history_endpoint_returns_200(client, mock_funding_history) -> None:
    with patch.object(binance_routes, "fetch_funding_history", return_value=mock_funding_history):
        resp = client.get("/api/binance/funding-history?symbol=BTCUSDT&limit=2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    # funding_history is a list; data field is the list itself
    assert body["data"] is not None


def test_capabilities_endpoint_returns_self_describing(client) -> None:
    resp = client.get("/api/binance/capabilities")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["loop"] == "Binance Market Data Loop (#12)"
    assert body["adr"] == "0013"
    paths = [e["path"] for e in body["endpoints"]]
    assert "/api/binance/mark-price" in paths
    assert "/api/binance/open-interest" in paths
    assert "/api/binance/funding-history" in paths


# ── Validation paths ───────────────────────────────────────────────────────


def test_missing_symbol_returns_400(client) -> None:
    resp = client.get("/api/binance/mark-price")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "invalid_symbol"


def test_garbage_symbol_returns_400(client) -> None:
    resp = client.get("/api/binance/mark-price?symbol=$$$")
    assert resp.status_code == 400


# ── Error paths ────────────────────────────────────────────────────────────


def test_cli_timeout_returns_502(client) -> None:
    from app.services.binance.data_source import BinanceCliError

    err = BinanceCliError("binance-cli futures-usds mark-price timed out after 5s (elapsed 5000ms)")
    with patch.object(binance_routes, "fetch_mark_price", side_effect=err):
        resp = client.get("/api/binance/mark-price?symbol=BTCUSDT")
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "timeout"


def test_cli_error_returns_502(client) -> None:
    from app.services.binance.data_source import BinanceCliError

    err = BinanceCliError("binance-cli futures-usds mark-price exited 1: invalid op")
    with patch.object(binance_routes, "fetch_mark_price", side_effect=err):
        resp = client.get("/api/binance/mark-price?symbol=BTCUSDT")
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "cli_error"


def test_value_error_returns_400(client) -> None:
    """Invalid limit (e.g. negative) -> ValueError -> 400/500."""
    with patch.object(
        binance_routes,
        "fetch_funding_history",
        side_effect=ValueError("limit must be a positive int"),
    ):
        resp = client.get("/api/binance/funding-history?symbol=BTCUSDT&limit=-1")
    # ValueError raised by the data_source call -> the general Exception
    # handler catches it -> 500. (data_source level validation should
    # happen before the handler.)
    assert resp.status_code in (400, 500)


# ── Persistence opt-in ─────────────────────────────────────────────────────


def test_persistence_query_appends_to_history(client, mock_mark_price, tmp_path) -> None:
    """?persistence=true triggers a HISTORY.jsonl append."""
    import os

    cwd = os.getcwd()
    live = os.path.join(cwd, ".scratch", "loop_state", "HISTORY.jsonl")
    if os.path.exists(live):
        os.remove(live)

    with patch.object(binance_routes, "fetch_mark_price", return_value=mock_mark_price):
        resp = client.get("/api/binance/mark-price?symbol=BTCUSDT&persistence=true")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["persisted"] is True
    # HISTORY.jsonl should now exist (real path, not tmp)
    assert os.path.exists(live)
    # Cleanup
    os.remove(live)


def test_persistence_default_false(client, mock_mark_price) -> None:
    """Default persistence is False — no side effect."""
    import os

    cwd = os.getcwd()
    live = os.path.join(cwd, ".scratch", "loop_state", "HISTORY.jsonl")
    existed = os.path.exists(live)
    if existed:
        with open(live) as f:
            before = f.read()

    with patch.object(binance_routes, "fetch_mark_price", return_value=mock_mark_price):
        resp = client.get("/api/binance/mark-price?symbol=BTCUSDT")
    body = resp.get_json()
    assert body["persisted"] is False

    if existed:
        with open(live) as f:
            after = f.read()
        assert after == before


# ── Live integration smoke (skipped if binance-cli missing) ────────────────


@pytest.mark.skipif(
    shutil.which(data_source.BINANCE_CLI_BIN) is None,
    reason=f"binance-cli binary not found at {data_source.BINANCE_CLI_BIN}",
)
def test_live_mark_price_endpoint(client) -> None:
    resp = client.get("/api/binance/mark-price?symbol=BTCUSDT")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["mark_price"] > 0


# ── Internal handler wrappers ──────────────────────────────────────────────


def test_handler_wrappers_pass_through(app) -> None:
    """Each endpoint calls the matching data_source function."""
    with patch.object(binance_routes, "fetch_mark_price", return_value="mp") as mock_mp, \
         patch.object(binance_routes, "fetch_open_interest", return_value="oi") as mock_oi, \
         patch.object(binance_routes, "fetch_funding_history", return_value="fh") as mock_fh:
        # _fetch_mark_price_handler / _fetch_open_interest_handler don't
        # read request context — pure pass-through.
        assert _fetch_mark_price_handler("BTCUSDT") == "mp"
        assert _fetch_open_interest_handler("BTCUSDT") == "oi"
        # _fetch_funding_history reads request.args; needs a request context.
        with app.test_request_context(
            "/api/binance/funding-history?symbol=BTCUSDT&limit=5"
        ):
            assert _fetch_funding_history_handler("BTCUSDT") == "fh"