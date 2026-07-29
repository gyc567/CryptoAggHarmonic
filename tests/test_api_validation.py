"""Contract tests for app/api/validation.py parse_request helper.

Layer 3 boundary: the API layer's only job is to translate HTTP requests into
validated Pydantic models. If a request body is malformed we return 400 (not
JSON); if the schema rejects it we return 422 with structured details.

These tests pin the helper's behavior so a future refactor that silently
broadens error handling (e.g. catching all exceptions and returning 500)
will fail this test suite, not production users.
"""
from __future__ import annotations

import json

import pytest
from flask import Flask
from pydantic import BaseModel, Field

from app.api.validation import parse_request


# ---------------------------------------------------------------------------
# Flask app fixture — jsonify() requires an application context.
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _push_app_context(app):
    with app.app_context():
        yield


# ---------------------------------------------------------------------------
# Test fixtures — simple model with several constraint types
# ---------------------------------------------------------------------------


class _Sample(BaseModel):
    """Used to exercise ge/le/required/non-str coercion paths."""

    name: str = Field(min_length=1, max_length=20)
    count: int = Field(ge=0, le=10)
    optional: str = "default"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_dict_passes_through(self):
        req, err = parse_request(_Sample, {"name": "alice", "count": 5})
        assert err is None
        assert req.name == "alice"
        assert req.count == 5
        assert req.optional == "default"

    def test_json_string_parsed(self):
        payload = json.dumps({"name": "bob", "count": 0})
        req, err = parse_request(_Sample, payload)
        assert err is None
        assert req.name == "bob"
        assert req.count == 0

    def test_none_payload_treated_as_empty(self):
        """Documented intentional non-contract: missing body → all defaults.
        Only valid for models where every required field has a default.
        """
        class _AllOptional(BaseModel):
            name: str = "anon"
            count: int = 0

        req, err = parse_request(_AllOptional, None)
        assert err is None
        assert req.name == "anon"

    def test_int_coerced_from_string(self):
        """Pydantic v2 default coercion: '5' → 5 for int fields."""
        req, err = parse_request(_Sample, {"name": "x", "count": "5"})
        assert err is None
        assert req.count == 5


# ---------------------------------------------------------------------------
# JSON parse failures → 400
# ---------------------------------------------------------------------------


class TestInvalidJSON:
    def test_garbage_string_returns_400(self):
        _, err = parse_request(_Sample, "not json {")
        assert err is not None
        body, status = err
        assert status == 400
        assert body.get_json()["error"]["code"] == "INVALID_PARAMS"

    def test_json_array_root_returns_400(self):
        _, err = parse_request(_Sample, json.dumps([1, 2, 3]))
        assert err is not None
        body, status = err
        assert status == 400

    def test_json_scalar_root_returns_400(self):
        _, err = parse_request(_Sample, json.dumps(42))
        assert err is not None
        body, status = err
        assert status == 400

    def test_unsupported_type_returns_400(self):
        _, err = parse_request(_Sample, 12345)
        assert err is not None
        body, status = err
        assert status == 400


# ---------------------------------------------------------------------------
# Schema validation failures → 422 with details
# ---------------------------------------------------------------------------


class TestSchemaErrors:
    def test_missing_required_returns_422(self):
        _, err = parse_request(_Sample, {})
        assert err is not None
        body, status = err
        assert status == 422

    def test_count_above_max_returns_422(self):
        _, err = parse_request(_Sample, {"name": "x", "count": 11})
        assert err is not None
        body, status = err
        assert status == 422

    def test_count_below_min_returns_422(self):
        _, err = parse_request(_Sample, {"name": "x", "count": -1})
        assert err is not None
        body, status = err
        assert status == 422

    def test_name_too_long_returns_422(self):
        _, err = parse_request(_Sample, {"name": "x" * 21, "count": 0})
        assert err is not None
        body, status = err
        assert status == 422

    def test_wrong_type_returns_422(self):
        """Can't coerce 'hello' to int → ValidationError, not ValueError."""
        _, err = parse_request(_Sample, {"name": "x", "count": "hello"})
        assert err is not None
        body, status = err
        assert status == 422

    def test_error_envelope_shape(self):
        """The error response uses the project's standard envelope."""
        _, err = parse_request(_Sample, {})
        assert err is not None
        body, status = err
        assert status == 422
        data = body.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAMS"
        assert "message" in data["error"]
        assert data["error"]["retryable"] is False

    def test_error_message_includes_field_name(self):
        """The summary line mentions the offending field."""
        _, err = parse_request(_Sample, {"count": 999})
        assert err is not None
        body, _ = err
        msg = body.get_json()["error"]["message"]
        assert "count" in msg


# ---------------------------------------------------------------------------
# 400 vs 422 distinction
# ---------------------------------------------------------------------------


class TestStatusCodeDistinction:
    """The helper distinguishes "couldn't parse" from "schema says no".

    400 is reserved for the former so clients can retry only after fixing
    the wire format; 422 is for the latter so clients know the payload is
    parseable but semantically rejected.
    """

    def test_400_status_unparseable_body(self):
        _, err = parse_request(_Sample, "{garbage")
        assert err is not None
        assert err[1] == 400

    def test_422_status_parseable_but_invalid(self):
        _, err = parse_request(_Sample, {"name": "x", "count": 999})
        assert err is not None
        assert err[1] == 422