"""Flask middleware for error handling and request logging."""

import logging
import time
import uuid

from flask import jsonify, request

from app.api.errors import AppError, ErrorCode, map_exception_to_error

logger = logging.getLogger(__name__)


def register_error_handlers(app):
    """Register global error handlers on Flask app.

    Args:
        app: Flask application instance.
    """

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        """Handle structured AppError exceptions."""
        logger.warning(
            "AppError: code=%s message=%s request_id=%s",
            error.code.value,
            error.message,
            error.request_id,
        )
        return jsonify(error.to_dict()), _status_code_for_error(error.code)

    @app.errorhandler(400)
    def handle_bad_request(error):
        """Handle Flask 400 errors."""
        req_id = str(uuid.uuid4())[:8]
        logger.warning("BadRequest: %s request_id=%s", error.description, req_id)
        return (
            jsonify(
                {
                    "success": False,
                    "error": {
                        "code": ErrorCode.INVALID_PARAMS.value,
                        "message": "Invalid request format.",
                        "retryable": False,
                        "request_id": req_id,
                    },
                }
            ),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(error):
        """Handle Flask 404 errors."""
        req_id = str(uuid.uuid4())[:8]
        return (
            jsonify(
                {
                    "success": False,
                    "error": {
                        "code": ErrorCode.NOT_IMPLEMENTED.value,
                        "message": "Endpoint not found.",
                        "retryable": False,
                        "request_id": req_id,
                    },
                }
            ),
            404,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Catch-all for unhandled exceptions."""
        req_id = str(uuid.uuid4())[:8]
        logger.exception("Unexpected error: request_id=%s", req_id)
        app_error = map_exception_to_error(error, req_id)
        return jsonify(app_error.to_dict()), 500


def _status_code_for_error(code: ErrorCode) -> int:
    """Map error code to HTTP status code.

    Args:
        code: Error code enum.

    Returns:
        HTTP status code.
    """
    mapping = {
        ErrorCode.INVALID_PARAMS: 400,
        ErrorCode.UNAUTHORIZED: 401,
        ErrorCode.QUOTA_EXCEEDED: 429,
        ErrorCode.MARKET_DATA_UNAVAILABLE: 503,
        ErrorCode.MODEL_ERROR: 503,
        ErrorCode.CHART_ERROR: 500,
        ErrorCode.NO_PATTERNS_FOUND: 200,
        ErrorCode.INTERNAL_ERROR: 500,
        ErrorCode.NOT_IMPLEMENTED: 404,
    }
    return mapping.get(code, 500)


def log_request_middleware(app):
    """Register request logging middleware.

    Args:
        app: Flask application instance.
    """

    @app.before_request
    def before_request():
        request.start_time = time.time()
        request.request_id = str(uuid.uuid4())[:8]

    @app.after_request
    def after_request(response):
        duration = (time.time() - getattr(request, "start_time", 0)) * 1000
        logger.info(
            "%s %s %s %d %.2fms request_id=%s",
            request.method,
            request.path,
            request.remote_addr,
            response.status_code,
            duration,
            getattr(request, "request_id", "unknown"),
        )
        return response
