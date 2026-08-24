"""Smoke test for Vibe ``send_message`` endpoint (audit T1).

Verifies the NameError-on-run_id bug stays fixed: the endpoint must accept a
real message and not crash on the run record creation.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from flask import Flask

from app.api.vibe_routes import vibe_bp


@pytest.fixture
def client(monkeypatch):
    """Build a Flask app with vibe blueprint + DISABLE_AUTH=1 (local dev)."""
    monkeypatch.setenv("DISABLE_AUTH", "1")
    # Avoid hitting real Redis / RQ by mocking the enqueue path.
    monkeypatch.setenv("VIBE_MAX_RUN_MINUTES", "1")
    app = Flask(__name__)
    app.register_blueprint(vibe_bp)
    return app.test_client()


def test_send_message_does_not_500_on_run_id(monkeypatch, client):
    """Audit T1: ``run_id`` must be defined before the run_record literal.

    We stub the session store + enqueue path so the test exercises only the
    NameError-fix surface, not the full agent loop.
    """
    from app.infra import vibe_session_store as vss

    fake_session = {"id": "s1", "user_id": "local-dev-user"}
    fake_run = {"id": "run-xxx", "session_id": "s1", "user_id": "local-dev-user", "status": "running"}

    monkeypatch.setattr(vss.VibeSessionStore, "get_session", lambda self, sid, uid: fake_session)
    monkeypatch.setattr(vss.VibeSessionStore, "create_run", lambda self, r: r)
    monkeypatch.setattr(vss.VibeSessionStore, "update_run", lambda self, rid, patch_: None)
    monkeypatch.setattr(vss.VibeSessionStore, "get_run", lambda self, rid, uid: fake_run)

    # Stub enqueue to return True (don't actually start a thread).
    with patch("app.api.vibe_routes._enqueue_or_run_sync", return_value=True):
        r = client.post(
            "/api/vibe/sessions/s1/messages",
            json={"content": "hello"},
        )

    # Before the fix this raised NameError → 500. After the fix, it returns 200.
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["success"] is True
    assert "run_id" in body["data"]
