"""Integration tests for ft_strategy REST routes (Phase 4).

Boots a minimal Flask app with the ft_strategy blueprint, injects an
in-memory SQLite repo via set_repo_factory, exercises each endpoint.
"""

from __future__ import annotations

import sqlite3

import pytest
from flask import Flask, g

from app.api.ft_strategy_routes import (
    ft_strategy_bp,
    set_repo_factory,
)
from app.ft_strategy._schema_sqlite import apply_sqlite_schema
from app.ft_strategy.report_validator import install_sqlite_check_trigger
from app.ft_strategy.supabase_repo import FtStrategyRepo


@pytest.fixture
def repo():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    apply_sqlite_schema(c)
    install_sqlite_check_trigger(c)
    r = FtStrategyRepo(c)
    set_repo_factory(lambda: r)
    yield r
    c.close()


@pytest.fixture
def client(repo, monkeypatch):
    """Build a Flask app with the blueprint.

    require_auth bypass: set DISABLE_AUTH=1 so is_local_dev_mode() returns True.
    The route decorator then short-circuits to LOCAL_DEV_USER.
    """
    monkeypatch.setenv("DISABLE_AUTH", "1")
    app = Flask(__name__)
    app.register_blueprint(ft_strategy_bp)
    return app.test_client()


def _auth_headers(user_id="u1"):
    return {"X-User-Id": user_id}


def _good_brief():
    return (
        "## Decision\nbuy on RSI<30 and price touches Bollinger lower\n"
        "## Question\nDoes mean-reversion work on BTC 5m futures?\n"
        "## Motivation\nTest basic thesis with paper-trading rigor\n"
        "## Universe\nBTC/USDT 5m\n"
        "## Constraints\nleverage=1\n"
        "## Failure modes\nDD > 12% means halt\n"
        "## Open Qs\n4h regime context useful?\n" + ("x" * 200)
    )


# ---------------------------------------------------------------------------
# Capabilities (no auth)
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_get(self, client):
        r = client.get("/api/ft-strategy/capabilities")
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"]
        assert "constants" in body["data"]
        assert "MCP_TIMEOUT_SECONDS" in body["data"]["constants"]


# ---------------------------------------------------------------------------
# Orient
# ---------------------------------------------------------------------------


class TestOrient:
    def test_root_empty_ids(self, client):
        r = client.get("/api/ft-strategy/orient")
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"]
        assert body["data"]["stagnation_hits"] == []

    def test_root_with_unknown_ids(self, client):
        r = client.get(
            "/api/ft-strategy/orient?ids=does-not-exist-1,does-not-exist-2"
        )
        assert r.status_code == 200
        body = r.get_json()
        # Nonexistent ids are silently skipped
        assert body["data"]["total_strategies"] == 2
        assert body["data"]["stagnation_hits"] == []

    def test_one_unknown_strategy(self, client):
        r = client.get("/api/ft-strategy/no-such-id/orient")
        assert r.status_code == 200
        body = r.get_json()
        assert body["data"]["error"] == "not_found"


# ---------------------------------------------------------------------------
# Create strategy (D-FT-21)
# ---------------------------------------------------------------------------


class TestCreateStrategy:
    def test_201_with_good_brief(self, client, repo):
        body = {
            "name": "My RSI v2",
            "research_md": _good_brief(),
            "idea_payload": {"kind": "template"},
            "pair": "BTC/USDT",
        }
        r = client.post(
            "/api/ft-strategies",
            headers=_auth_headers(),
            json=body,
        )
        assert r.status_code == 201
        data = r.get_json()["data"]
        assert data["name"] == "My RSI v2"
        assert data["status"] == "draft"
        assert data["current_version"] == 1

    def test_422_research_md_too_short(self, client, repo):
        r = client.post(
            "/api/ft-strategies",
            headers=_auth_headers(),
            json={
                "name": "Tiny",
                "research_md": "## Decision\nx",  # missing sections + short
                "idea_payload": {"kind": "template"},
            },
        )
        assert r.status_code == 422

    def test_422_missing_sections(self, client, repo):
        # Long enough but missing sections
        long = " ".join(["x"] * 300)
        r = client.post(
            "/api/ft-strategies",
            headers=_auth_headers(),
            json={
                "name": "NoSections",
                "research_md": long,
                "idea_payload": {},
            },
        )
        assert r.status_code == 422

    def test_422_pydantic_validation_error(self, client, repo):
        # Missing required fields
        r = client.post(
            "/api/ft-strategies",
            headers=_auth_headers(),
            json={"name": "x"},  # missing research_md + idea_payload
        )
        assert r.status_code == 422  # parse_request returns 422

    def test_422_invalid_market_type(self, client, repo):
        r = client.post(
            "/api/ft-strategies",
            headers=_auth_headers(),
            json={
                "name": "Bad",
                "research_md": _good_brief(),
                "idea_payload": {},
                "market_type": "spot",  # not in Literal["futures"]
            },
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# List / Get / Delete
# ---------------------------------------------------------------------------


class TestGetDelete:
    def test_list_for_user(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(),
            idea_payload={},
        )
        r = client.get("/api/ft-strategies", headers=_auth_headers("u1"))
        assert r.status_code == 200
        items = r.get_json()["data"]["items"]
        assert any(i["id"] == s.id for i in items)

    def test_list_filters_by_user(self, client, repo):
        repo.create_strategy(
            user_id="u1", name="A",
            research_md=_good_brief(), idea_payload={},
        )
        repo.create_strategy(
            user_id="u2", name="B",
            research_md=_good_brief(), idea_payload={},
        )
        r = client.get("/api/ft-strategies", headers=_auth_headers("u1"))
        items = r.get_json()["data"]["items"]
        # u1 should only see their strategies
        assert all(i["user_id"] == "u1" for i in items)

    def test_get_one(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        r = client.get(f"/api/ft-strategies/{s.id}", headers=_auth_headers())
        assert r.status_code == 200
        assert r.get_json()["data"]["id"] == s.id

    def test_get_one_missing(self, client, repo):
        r = client.get("/api/ft-strategies/no-such", headers=_auth_headers())
        assert r.status_code == 404

    def test_delete_one(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="Doomed",
            research_md=_good_brief(), idea_payload={},
        )
        r = client.delete(
            f"/api/ft-strategies/{s.id}", headers=_auth_headers()
        )
        assert r.status_code == 200

    def test_cascade_delete_removes_events(self, client, repo):
        from app.services.freqtrade.event_log import record_event_dual
        s = repo.create_strategy(
            user_id="u1", name="X",
            research_md=_good_brief(), idea_payload={},
        )
        record_event_dual(
            repo, strategy_id=s.id, event="stable",
            strategy_name="X", tsv_root=None,
        )
        client.delete(f"/api/ft-strategies/{s.id}", headers=_auth_headers())
        cur = repo.conn.execute(
            "SELECT COUNT(*) FROM ft_strategy_events WHERE strategy_id = ?",
            (s.id,),
        )
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Refine + Stagnation discipline
# ---------------------------------------------------------------------------


class TestRefine:
    def test_basic_refine(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        r = client.post(
            f"/api/ft-strategies/{s.id}/refine",
            headers=_auth_headers(),
            json={"intended_event": "evolve"},
        )
        assert r.status_code == 200
        assert r.get_json()["data"]["current_version"] == 2

    def test_stagnation_requires_event(self, client, repo):
        from app.services.freqtrade.event_log import record_event_dual
        from app.loop.tuning_promotion_v3 import STAGNATION_ROUNDS
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        for _ in range(STAGNATION_ROUNDS):
            record_event_dual(
                repo, strategy_id=s.id, event="stable",
                strategy_name="S",
            )
        # No intended_event -> 422
        r = client.post(
            f"/api/ft-strategies/{s.id}/refine",
            headers=_auth_headers(),
            json={},
        )
        assert r.status_code == 422

    def test_stagnation_with_event_passes(self, client, repo):
        from app.services.freqtrade.event_log import record_event_dual
        from app.loop.tuning_promotion_v3 import STAGNATION_ROUNDS
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        for _ in range(STAGNATION_ROUNDS):
            record_event_dual(
                repo, strategy_id=s.id, event="stable",
                strategy_name="S",
            )
        r = client.post(
            f"/api/ft-strategies/{s.id}/refine",
            headers=_auth_headers(),
            json={"intended_event": "fork"},
        )
        assert r.status_code == 200
        assert r.get_json()["data"]["current_version"] == 2


# ---------------------------------------------------------------------------
# Deploy (D-FT-09/10/22)
# ---------------------------------------------------------------------------


class TestDeploy:
    def test_no_final_report_blocks_deploy(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        repo.update_status(s.id, "analyzed")
        r = client.post(
            f"/api/ft-strategies/{s.id}/deploy",
            headers=_auth_headers(),
        )
        assert r.status_code == 422
        body = r.get_json()["data"]
        assert body["error"] == "promotion_gate_failed"

    def test_zero_metrics_blocks_deploy(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        repo.update_status(s.id, "analyzed")
        r = repo.create_report(strategy_id=s.id, version=1, report_json={})
        repo.publish_report(r.id, "Sharpe holds across all regimes tested")
        r = client.post(
            f"/api/ft-strategies/{s.id}/deploy",
            headers=_auth_headers(),
        )
        # No metrics — per_timerange missing, robust_sharpe_min fails
        assert r.status_code == 422

    def test_passed_gate_marks_pending_review(self, client, repo):
        from app.ft_strategy.supabase_repo import FtStrategyRepo
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        repo.update_status(s.id, "analyzed")
        # Provide metrics that pass all 8 items
        repo.update_latest_result(
            s.id,
            {
                "sharpe": 1.5, "max_dd": 0.05, "calmar": 2.0,
                "win_rate": 0.6, "profit_pct": 0.20, "trades": 100,
                "per_timerange": [
                    {"regime": "bull", "sharpe": 1.5, "max_dd": 0.04, "calmar": 2.5},
                    {"regime": "winter", "sharpe": 0.5, "max_dd": 0.10, "calmar": 1.5},
                    {"regime": "recovery", "sharpe": 1.0, "max_dd": 0.06, "calmar": 2.0},
                    {"regime": "full_5y", "sharpe": 1.94, "max_dd": 0.078, "calmar": 2.1},
                ],
            },
        )
        r = repo.create_report(strategy_id=s.id, version=1, report_json={})
        repo.publish_report(r.id, "Sharpe 1.94 holds across all four regimes tested")
        r = client.post(
            f"/api/ft-strategies/{s.id}/deploy",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.get_json()["data"]
        assert body["status"] == "pending_review"

    def test_unknown_strategy_returns_404(self, client, repo):
        r = client.post(
            "/api/ft-strategies/no-such-id/deploy",
            headers=_auth_headers(),
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Jobs / History / BacktestReport / Preflight
# ---------------------------------------------------------------------------


class TestMisc:
    def test_jobs_lists_recent_runs(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        repo.conn.execute(
            """
            INSERT INTO ft_jobs (job_id, strategy_id, stage, status)
            VALUES ('j1', ?, 'backtest', 'queued')
            """,
            (s.id,),
        )
        repo.conn.commit()
        r = client.get(
            f"/api/ft-strategies/{s.id}/jobs",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        assert len(r.get_json()["data"]["jobs"]) == 1

    def test_history_returns_tsv_and_runs(self, client, repo):
        from app.services.freqtrade.event_log import record_event_dual
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        record_event_dual(
            repo, strategy_id=s.id, event="create",
            strategy_name="S1",
        )
        r = client.get(
            f"/api/ft-strategies/{s.id}/history",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.get_json()["data"]
        assert len(body["events"]) >= 1

    def test_backtest_report_shape(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        repo.update_latest_result(
            s.id, {"sharpe": 1.5, "max_dd": 0.05, "per_pair": {"BTC/USDT": {"sharpe": 1.5}}}
        )
        r = client.get(
            f"/api/ft-strategies/{s.id}/backtest-report",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.get_json()["data"]
        assert body["aggregate"]["sharpe"] == 1.5
        assert "BTC/USDT" in body["per_pair"]

    def test_preflight_phase_5_stub(self, client, repo):
        s = repo.create_strategy(
            user_id="u1", name="S1",
            research_md=_good_brief(), idea_payload={},
        )
        r = client.post(
            f"/api/ft-strategies/{s.id}/preflight",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        assert r.get_json()["data"]["preflight"].startswith("pending")
