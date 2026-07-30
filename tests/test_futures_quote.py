"""Tests for :mod:`app.infra.futures_quote`.

Coverage goal: 100% of the module. Mocks ``requests.Session`` so no
real HTTP traffic is generated.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from app.infra.futures_quote import (
    DEFAULT_FAPI_BASE,
    FuturesQuote,
    QuoteFetchError,
    claim_fetch,
    fetch_quotes,
    filter_known_symbols,
    normalize_symbol,
    parse_quotes_payload,
    release_fetch,
)


# ---------------------------------------------------------------------------
# normalize_symbol
# ---------------------------------------------------------------------------


class TestNormalizeSymbol:
    def test_uppercases(self):
        assert normalize_symbol("muusdt") == "MUUSDT"

    def test_strips_whitespace(self):
        assert normalize_symbol("  BTCUSDT  ") == "BTCUSDT"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            normalize_symbol("")
        with pytest.raises(ValueError):
            normalize_symbol("   ")

    @pytest.mark.parametrize("bad", [None, 123, ["x"], {"s": "x"}])
    def test_rejects_non_string(self, bad):
        with pytest.raises(ValueError):
            normalize_symbol(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# filter_known_symbols
# ---------------------------------------------------------------------------


class TestFilterKnownSymbols:
    def test_no_whitelist_returns_all_normalized(self):
        known, unknown = filter_known_symbols(
            [" muusdt ", "ORCLUSDT", "btcusdt"], whitelist=None
        )
        assert known == ["BTCUSDT", "MUUSDT", "ORCLUSDT"]
        assert unknown == []

    def test_drops_unknown_against_whitelist(self):
        known, unknown = filter_known_symbols(
            ["MUUSDT", "FOOUSDT", "ORCLUSDT"],
            whitelist=["MUUSDT", "ORCLUSDT"],
        )
        assert known == ["MUUSDT", "ORCLUSDT"]
        assert unknown == ["FOOUSDT"]

    def test_dedupes_and_normalizes_case(self):
        known, unknown = filter_known_symbols(
            ["muusdt", "MUUSDT", " muusdt "],
            whitelist=["MUUSDT"],
        )
        assert known == ["MUUSDT"]
        assert unknown == []

    def test_invalid_inputs_go_to_unknown(self):
        known, unknown = filter_known_symbols(
            ["", "  ", None, "MUUSDT"],  # type: ignore[list-item]
            whitelist=["MUUSDT"],
        )
        assert known == ["MUUSDT"]
        assert len(unknown) == 3  # "" + "  " + None


# ---------------------------------------------------------------------------
# parse_quotes_payload
# ---------------------------------------------------------------------------


def _ticker(symbol: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "symbol": symbol,
        "lastPrice": "100.5",
        "priceChangePercent": "1.5",
        "highPrice": "101",
        "lowPrice": "99",
        "volume": "12345",
        "quoteVolume": "67890",
        "count": "42",
    }
    base.update(overrides)
    return base


def _premium(symbol: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "symbol": symbol,
        "markPrice": "100.55",
        "fundingRate": "0.0001",
        "nextFundingTime": "1700000000000",
    }
    base.update(overrides)
    return base


class TestParseQuotesPayload:
    def test_merges_both_payloads(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT")],
            premium_payload=[_premium("MUUSDT")],
        )
        q = out["MUUSDT"]
        assert q.symbol == "MUUSDT"
        assert q.last_price == 100.5
        assert q.price_change_percent == 1.5
        assert q.mark_price == 100.55
        assert q.funding_rate == 0.0001
        assert q.next_funding_time == 1700000000000
        assert q.high_price == 101.0
        assert q.low_price == 99.0
        assert q.volume == 12345.0
        assert q.quote_volume == 67890.0
        assert q.count == 42

    def test_requested_symbol_with_no_payload_rows(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[],
            premium_payload=[],
        )
        assert out["MUUSDT"].last_price is None
        assert out["MUUSDT"].mark_price is None
        assert out["MUUSDT"].symbol == "MUUSDT"

    def test_only_ticker(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT")],
            premium_payload=None,
        )
        assert out["MUUSDT"].last_price == 100.5
        assert out["MUUSDT"].mark_price is None

    def test_only_premium(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=None,
            premium_payload=[_premium("MUUSDT")],
        )
        assert out["MUUSDT"].mark_price == 100.55
        assert out["MUUSDT"].last_price is None

    def test_malformed_ticker_does_not_overwrite(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[{"symbol": "MUUSDT", "lastPrice": "not-a-number"}],
            premium_payload=[_premium("MUUSDT")],
        )
        # malformed lastPrice → fallback None (no prior)
        assert out["MUUSDT"].last_price is None
        assert out["MUUSDT"].mark_price == 100.55

    def test_malformed_premium_does_not_overwrite(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT")],
            premium_payload=[{"symbol": "MUUSDT", "markPrice": "junk"}],
        )
        assert out["MUUSDT"].last_price == 100.5
        assert out["MUUSDT"].mark_price is None

    def test_malformed_int_field_does_not_overwrite(self):
        # Defaults are None, malformed strings should NOT crash and should
        # preserve the existing None rather than corrupting to fallback.
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT", count="abc")],
            premium_payload=[_premium("MUUSDT", nextFundingTime="xyz")],
        )
        assert out["MUUSDT"].count is None
        assert out["MUUSDT"].next_funding_time is None

    def test_typeerror_count_falls_back(self):
        # Passing a list/dict causes int(...) to raise TypeError, not ValueError.
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT", count=[1, 2])],
            premium_payload=[],
        )
        assert out["MUUSDT"].count is None

    def test_typeerror_funding_falls_back(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[],
            premium_payload=[_premium("MUUSDT", nextFundingTime={"x": 1})],
        )
        assert out["MUUSDT"].next_funding_time is None

    def test_typeerror_ticker_float_falls_back(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT", lastPrice={"junk": True})],
            premium_payload=[],
        )
        assert out["MUUSDT"].last_price is None

    def test_typeerror_premium_float_falls_back(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[],
            premium_payload=[_premium("MUUSDT", markPrice=["nope"])],
        )
        assert out["MUUSDT"].mark_price is None

    def test_row_with_no_symbol_skipped(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[{"lastPrice": "1"}, _ticker("MUUSDT")],
            premium_payload=[],
        )
        assert out["MUUSDT"].last_price == 100.5

    def test_premium_row_with_no_symbol_skipped(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT")],
            premium_payload=[{"markPrice": "1"}, _premium("MUUSDT")],
        )
        assert out["MUUSDT"].mark_price == 100.55

    def test_extra_unrelated_symbol_dropped(self):
        out = parse_quotes_payload(
            symbols=["MUUSDT"],
            ticker_payload=[_ticker("MUUSDT"), _ticker("FOOUSDT")],
            premium_payload=[],
        )
        assert "FOOUSDT" not in out
        assert "MUUSDT" in out

    def test_to_dict_omits_null(self):
        q = FuturesQuote(symbol="MUUSDT", last_price=1.0)
        d = q.to_dict()
        assert d == {"symbol": "MUUSDT", "lastPrice": 1.0}

    def test_to_dict_with_extra(self):
        q = FuturesQuote(symbol="MUUSDT", last_price=1.0, extra={"foo": 1})
        d = q.to_dict()
        assert d["extra"] == {"foo": 1}


# ---------------------------------------------------------------------------
# fetch_quotes — HTTP path with mocked session
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_payload: Any = None,
        json_raises: bool = False,
    ):
        self.status_code = status_code
        self._payload = json_payload if json_payload is not None else []
        self._json_raises = json_raises

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_raises:
            raise ValueError("bad json")
        return self._payload


def _session_factory(responses: list[_FakeResp]) -> MagicMock:
    sess = MagicMock()
    sess.headers = {}
    sess.get = MagicMock(side_effect=responses)
    return sess


class TestFetchQuotes:
    def test_returns_merged_payload(self, monkeypatch):
        sess = _session_factory([
            _FakeResp(json_payload=[_ticker("MUUSDT")]),   # ticker
            _FakeResp(json_payload=[_premium("MUUSDT")]),  # premium
        ])
        out = fetch_quotes(
            ["muusdt"],
            whitelist=["MUUSDT"],
            session=sess,
            sleep=lambda _: None,  # don't actually sleep
        )
        assert set(out) == {"MUUSDT"}
        assert out["MUUSDT"].last_price == 100.5
        assert out["MUUSDT"].mark_price == 100.55
        assert sess.get.call_count == 2

    def test_empty_known_returns_empty_without_http(self, monkeypatch):
        sess = _session_factory([])
        out = fetch_quotes([], whitelist=["MUUSDT"], session=sess)
        assert out == {}
        assert sess.get.call_count == 0

    def test_all_unknown_returns_empty(self, monkeypatch):
        sess = _session_factory([])
        out = fetch_quotes(["FOOUSDT"], whitelist=["MUUSDT"], session=sess)
        assert out == {}
        assert sess.get.call_count == 0

    def test_429_retries_then_succeeds(self):
        sess = _session_factory([
            _FakeResp(status_code=429),                  # retry
            _FakeResp(status_code=429),                  # retry
            _FakeResp(json_payload=[_ticker("MUUSDT")]), # success
            _FakeResp(json_payload=[_premium("MUUSDT")]),
        ])
        sleeps = []
        out = fetch_quotes(
            ["MUUSDT"],
            whitelist=["MUUSDT"],
            session=sess,
            max_retries=3,
            sleep=sleeps.append,
        )
        assert "MUUSDT" in out
        # 2 sleeps for 2 retries of the first request
        assert len(sleeps) == 2

    def test_429_exhausts_retries(self):
        sess = _session_factory([
            _FakeResp(status_code=429),
            _FakeResp(status_code=429),
            _FakeResp(status_code=429),
        ])
        with pytest.raises(QuoteFetchError):
            fetch_quotes(
                ["MUUSDT"],
                whitelist=["MUUSDT"],
                session=sess,
                max_retries=3,
                sleep=lambda _: None,
            )

    def test_hard_4xx_not_retried(self):
        sess = _session_factory([_FakeResp(status_code=500)])
        with pytest.raises(QuoteFetchError):
            fetch_quotes(
                ["MUUSDT"],
                whitelist=["MUUSDT"],
                session=sess,
                max_retries=3,
                sleep=lambda _: None,
            )
        assert sess.get.call_count == 1

    def test_bad_json_not_retried(self):
        sess = _session_factory([_FakeResp(json_raises=True)])
        with pytest.raises(QuoteFetchError):
            fetch_quotes(
                ["MUUSDT"],
                whitelist=["MUUSDT"],
                session=sess,
                max_retries=3,
                sleep=lambda _: None,
            )
        assert sess.get.call_count == 1

    def test_network_error_retries(self):
        sess = MagicMock()
        sess.headers = {}
        sess.get = MagicMock(side_effect=[
            requests.ConnectionError("nope"),
            requests.ConnectionError("nope again"),
            _FakeResp(json_payload=[_ticker("MUUSDT")]),
            _FakeResp(json_payload=[_premium("MUUSDT")]),
        ])
        out = fetch_quotes(
            ["MUUSDT"],
            whitelist=["MUUSDT"],
            session=sess,
            max_retries=3,
            sleep=lambda _: None,
        )
        assert "MUUSDT" in out

    def test_network_error_exhausts(self):
        sess = MagicMock()
        sess.headers = {}
        sess.get = MagicMock(side_effect=requests.ConnectionError("boom"))
        with pytest.raises(QuoteFetchError):
            fetch_quotes(
                ["MUUSDT"],
                whitelist=["MUUSDT"],
                session=sess,
                max_retries=2,
                sleep=lambda _: None,
            )

    def test_unknown_symbol_drops_from_output(self):
        sess = _session_factory([
            _FakeResp(json_payload=[_ticker("MUUSDT"), _ticker("FOOUSDT")]),
            _FakeResp(json_payload=[_premium("MUUSDT"), _premium("FOOUSDT")]),
        ])
        out = fetch_quotes(
            ["MUUSDT", "FOOUSDT"],
            whitelist=["MUUSDT"],
            session=sess,
            sleep=lambda _: None,
        )
        assert "MUUSDT" in out
        # FOOUSDT in upstream payload but not in whitelist → not requested,
        # so parse_quotes_payload never sees it.
        assert "FOOUSDT" not in out

    def test_default_base_url_used_when_no_session(self, monkeypatch):
        # Patch Session to avoid opening a real connection.
        monkeypatch.setattr(
            "app.infra.futures_quote.requests.Session",
            lambda: _session_factory([
                _FakeResp(json_payload=[_ticker("MUUSDT")]),
                _FakeResp(json_payload=[_premium("MUUSDT")]),
            ]),
        )
        out = fetch_quotes(
            ["MUUSDT"],
            whitelist=["MUUSDT"],
            sleep=lambda _: None,
        )
        assert "MUUSDT" in out

    def test_backoff_sleep_does_not_propagate(monkeypatch):
        # Sleep that raises should not crash the loop.
        sess = _session_factory([
            _FakeResp(status_code=429),
            _FakeResp(status_code=429),
            _FakeResp(json_payload=[_ticker("MUUSDT")]),
            _FakeResp(json_payload=[_premium("MUUSDT")]),
        ])

        def bad_sleep(_):
            raise RuntimeError("sleep failed")

        out = fetch_quotes(
            ["MUUSDT"],
            whitelist=["MUUSDT"],
            session=sess,
            sleep=bad_sleep,
            max_retries=3,
        )
        assert "MUUSDT" in out


# ---------------------------------------------------------------------------
# claim / release helpers
# ---------------------------------------------------------------------------


class TestInflightGuard:
    def setup_method(self):
        # Clean module state between tests.
        from app.infra import futures_quote
        futures_quote._INFLIGHT.clear()

    def test_first_claim_succeeds_second_fails(self):
        assert claim_fetch("client-A") is True
        assert claim_fetch("client-A") is False

    def test_release_allows_reclaim(self):
        assert claim_fetch("client-A") is True
        release_fetch("client-A")
        assert claim_fetch("client-A") is True

    def test_release_unclaimed_origin_does_not_raise(self):
        release_fetch("never-claimed")  # should not raise