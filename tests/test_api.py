"""Tests for API layer: errors, middleware."""

import pytest
from flask import Flask

from app.api.errors import AppError, ErrorCode, format_error, map_exception_to_error
from app.api.middleware import (
    _status_code_for_error,
    log_request_middleware,
    register_error_handlers,
)


class TestAppError:
    def test_basic_error(self):
        err = AppError(ErrorCode.INVALID_PARAMS, "Bad request")
        assert err.code == ErrorCode.INVALID_PARAMS
        assert err.message == "Bad request"
        assert err.retryable is False
        assert err.request_id is not None

    def test_error_with_request_id(self):
        err = AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            "Data unavailable",
            retryable=True,
            request_id="req123",
        )
        assert err.retryable is True
        assert err.request_id == "req123"

    def test_error_to_dict(self):
        err = AppError(ErrorCode.INTERNAL_ERROR, "Oops")
        d = err.to_dict()
        assert d["success"] is False
        assert d["error"]["code"] == "INTERNAL_ERROR"
        assert d["error"]["message"] == "Oops"
        assert d["error"]["retryable"] is False
        assert "request_id" in d["error"]

    def test_error_with_original(self):
        original = ValueError("original")
        err = AppError(
            ErrorCode.MODEL_ERROR,
            "Model failed",
            original_error=original,
        )
        assert err.original_error is original


class TestFormatError:
    def test_basic(self):
        result = format_error(ErrorCode.INVALID_PARAMS, "Bad params")
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_PARAMS"
        assert result["error"]["message"] == "Bad params"

    def test_with_retryable(self):
        result = format_error(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            "Unavailable",
            retryable=True,
        )
        assert result["error"]["retryable"] is True

    def test_with_request_id(self):
        result = format_error(ErrorCode.INTERNAL_ERROR, "Oops", request_id="abc")
        assert result["error"]["request_id"] == "abc"

    def test_generates_request_id(self):
        result = format_error(ErrorCode.INTERNAL_ERROR, "Oops")
        assert "request_id" in result["error"]
        assert len(result["error"]["request_id"]) > 0


class TestMapExceptionToError:
    def test_maps_to_internal_error(self):
        original = RuntimeError("Something broke")
        err = map_exception_to_error(original)
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert "unexpected" in err.message.lower()
        assert err.retryable is True
        assert err.original_error is original

    def test_preserves_request_id(self):
        err = map_exception_to_error(ValueError("x"), request_id="r123")
        assert err.request_id == "r123"


class TestStatusCodeMapping:
    def test_invalid_params(self):
        assert _status_code_for_error(ErrorCode.INVALID_PARAMS) == 400

    def test_unauthorized(self):
        assert _status_code_for_error(ErrorCode.UNAUTHORIZED) == 401

    def test_quota_exceeded(self):
        assert _status_code_for_error(ErrorCode.QUOTA_EXCEEDED) == 429

    def test_market_data_unavailable(self):
        assert _status_code_for_error(ErrorCode.MARKET_DATA_UNAVAILABLE) == 503

    def test_model_error(self):
        assert _status_code_for_error(ErrorCode.MODEL_ERROR) == 503

    def test_chart_error(self):
        assert _status_code_for_error(ErrorCode.CHART_ERROR) == 500

    def test_no_patterns_found(self):
        assert _status_code_for_error(ErrorCode.NO_PATTERNS_FOUND) == 200

    def test_internal_error(self):
        assert _status_code_for_error(ErrorCode.INTERNAL_ERROR) == 500

    def test_not_implemented(self):
        assert _status_code_for_error(ErrorCode.NOT_IMPLEMENTED) == 404

    def test_unknown_code(self):
        assert _status_code_for_error("UNKNOWN_CODE") == 500


class TestErrorHandlers:
    @pytest.fixture
    def app(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        register_error_handlers(app)
        return app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_app_error_handler(self, client, app):
        @app.route("/test-app-error")
        def raise_app_error():
            raise AppError(ErrorCode.INVALID_PARAMS, "Test error")

        resp = client.get("/test-app-error")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAMS"
        assert data["error"]["message"] == "Test error"

    def test_app_error_handler_retryable(self, client, app):
        @app.route("/test-retryable")
        def raise_retryable():
            raise AppError(
                ErrorCode.MARKET_DATA_UNAVAILABLE,
                "Unavailable",
                retryable=True,
            )

        resp = client.get("/test-retryable")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["error"]["retryable"] is True

    def test_unexpected_error_handler(self, client, app):
        @app.route("/test-unexpected")
        def raise_unexpected():
            raise RuntimeError("Unexpected!")

        resp = client.get("/test-unexpected")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "request_id" in data["error"]

    def test_404_handler(self, client):
        resp = client.get("/not-found")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_IMPLEMENTED"

    def test_bad_request_handler(self, client, app):
        @app.route("/test-bad-request", methods=["POST"])
        def bad_request():
            # Force a 400 by returning None without response
            from flask import abort

            abort(400)

        resp = client.post("/test-bad-request")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAMS"


class TestLogRequestMiddleware:
    @pytest.fixture
    def app(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        log_request_middleware(app)
        return app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_request_id_set(self, client, app):
        @app.route("/test")
        def test_route():
            from flask import request as flask_request

            assert hasattr(flask_request, "request_id")
            assert len(flask_request.request_id) > 0
            return "ok"

        resp = client.get("/test")
        assert resp.status_code == 200

    def test_start_time_set(self, client, app):
        @app.route("/test")
        def test_route():
            from flask import request as flask_request

            assert hasattr(flask_request, "start_time")
            assert flask_request.start_time > 0
            return "ok"

        resp = client.get("/test")
        assert resp.status_code == 200
