"""Flask application factory.

All side effects (dotenv loading, YAML parsing, orchestrator creation) are
isolated here so they can be controlled and tested independently.

Usage::

    from app.factory import create_app

    app = create_app()
    app.run()
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml
from dotenv import load_dotenv
from flask import jsonify, request

if TYPE_CHECKING:
    from flask import Flask

# Lazily-initialized singletons (set once, read many).
_app: "Flask | None" = None
_orchestrator: "AnalysisOrchestrator | None" = None
_prompt_context: dict | None = None

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Load .env file into environment. Idempotent."""
    load_dotenv()


def _load_prompt_context() -> dict:
    """Load prompt_intent.yaml. Called once at startup."""
    yaml_path = Path("prompt_intent.yaml")
    if yaml_path.exists():
        with open(yaml_path) as f:
            return yaml.safe_load(f) or {}
    logger.warning("prompt_intent.yaml not found; using empty context")
    return {}


def _create_app() -> "Flask":
    """Build and configure the Flask application."""
    global _app

    from flask import Flask

    from app.api.middleware import log_request_middleware, register_error_handlers

    # Initialize Flask app.
    app = Flask(__name__)

    # Production safety: refuse to start with auth bypass or debug enabled.
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        if os.getenv("DISABLE_AUTH") == "1":
            raise RuntimeError("DISABLE_AUTH=1 is not allowed in production")
        if app.debug or os.getenv("FLASK_DEBUG") == "1":
            raise RuntimeError("FLASK_DEBUG is not allowed in production")

    # Register middleware.
    register_error_handlers(app)
    log_request_middleware(app)

    # Import and register blueprints lazily to avoid circular imports.
    from app.api.routes import api_bp
    from app.api.rsi_trend_routes import rsi_trend_bp
    from app.api.vibe_routes import vibe_bp
    from app.api.watchlist_routes import watchlist_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(vibe_bp)
    app.register_blueprint(rsi_trend_bp)
    app.register_blueprint(watchlist_bp)

    # Loop engineering: Prometheus metrics endpoint
    try:
        from app.api.metrics_routes import make_metrics_blueprint
        app.register_blueprint(make_metrics_blueprint())
    except Exception:
        logger.warning("Failed to register metrics blueprint; prometheus_client may not be installed")

    # Simple CORS support for local dev / preview origins.
    _add_cors(app)

    _app = app
    return app


def _add_cors(app: "Flask") -> None:
    """Add CORS headers for localhost preview origins."""

    @app.before_request
    def before_request_cors():
        origin = request.headers.get("Origin", "")
        allowed_origins = {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5001",
            "http://127.0.0.1:5001",
        }
        if origin in allowed_origins:
            request._cors_origin = origin  # type: ignore[attr-defined]
        if request.method == "OPTIONS":
            return jsonify({"status": "ok"}), 200

    @app.after_request
    def after_request_cors(response):
        from flask import request

        origin = getattr(request, "_cors_origin", None)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


def get_app() -> "Flask":
    """Get or create the Flask application singleton."""
    global _app
    if _app is None:
        _load_dotenv()
        _app = _create_app()
    return _app


def get_orchestrator() -> "AnalysisOrchestrator":
    """Get or create the AnalysisOrchestrator singleton."""
    global _orchestrator, _prompt_context

    if _orchestrator is None:
        _load_dotenv()
        if _prompt_context is None:
            _prompt_context = _load_prompt_context()

        from app.services.analysis import AnalysisOrchestrator

        _orchestrator = AnalysisOrchestrator(prompt_context=_prompt_context)

    return _orchestrator


def reset_app() -> None:
    """Reset all singletons. For testing only."""
    global _app, _orchestrator, _prompt_context
    _app = None
    _orchestrator = None
    _prompt_context = None
