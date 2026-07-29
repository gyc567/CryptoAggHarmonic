"""Tests for the local chart serving route GET /api/charts/<name>.png."""

from unittest.mock import patch

import pytest

from app.main import app

VALID_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestServeChart:
    def test_serves_existing_chart(self, client, tmp_path):
        (tmp_path / f"{VALID_ID}.png").write_bytes(PNG)
        with patch("app.services.chart_store.CHART_DIR", tmp_path):
            resp = client.get(f"/api/charts/{VALID_ID}.png")
        assert resp.status_code == 200
        assert resp.content_type.startswith("image/png")
        assert resp.data == PNG

    def test_missing_chart_returns_404(self, client, tmp_path):
        with patch("app.services.chart_store.CHART_DIR", tmp_path):
            resp = client.get(f"/api/charts/{VALID_ID}.png")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_invalid_name_returns_404(self, client, tmp_path):
        with patch("app.services.chart_store.CHART_DIR", tmp_path):
            resp = client.get("/api/charts/NOT-VALID.png")
        assert resp.status_code == 404

    def test_traversal_blocked(self, client):
        # Even if the URL layer decodes traversal sequences, the name
        # whitelist rejects them before any file access happens.
        resp = client.get("/api/charts/..%2F..%2Fetc%2Fpasswd.png")
        assert resp.status_code in (404, 400)
