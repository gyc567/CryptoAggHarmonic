"""Tests for ``app/api/metrics_routes.py``.

Covers: blueprint registration, lazy metric init, all 12 producer
helpers, and the dynamic-gauge updater (``pareto_front_size``,
``runs_disk_bytes``, ``loop_readiness_score``).
"""

from __future__ import annotations

import pytest

from app.api import metrics_routes as mr
from app.factory import get_app, reset_app


@pytest.fixture(autouse=True)
def _reset_metrics_state():
    """Reset the lazy module-level metric registry between tests."""
    mr._metrics.clear()
    mr._mc_state.clear()
    mr._suspicious_state.clear()
    mr._LOOP_REGISTRY = None
    yield
    mr._metrics.clear()
    mr._mc_state.clear()
    mr._suspicious_state.clear()
    mr._LOOP_REGISTRY = None


# ---- helpers -------------------------------------------------------------


def _init():
    mr._init_metrics()
    return mr._metrics


def _scrape() -> str:
    """Render the private metric registry as Prometheus text."""
    from prometheus_client import generate_latest

    if mr._LOOP_REGISTRY is None:
        return ""
    return generate_latest(mr._LOOP_REGISTRY).decode("utf-8")


def _value(body: str, name: str, label_substr: str | None = None) -> str:
    """Return the value of a single Prometheus sample line.

    Skips ``# HELP`` and ``# TYPE`` lines; the metric ``name`` is matched
    with a following ``{`` (labelled) or space (unlabelled). The optional
    ``label_substr`` disambiguates between multiple label values.
    """
    for line in body.splitlines():
        if line.startswith("#") or not line:
            continue
        if label_substr is not None:
            if line.startswith(f"{name}{{"):
                if label_substr in line:
                    return line.rsplit(" ", 1)[-1]
        else:
            if line.startswith(f"{name} "):
                return line.rsplit(" ", 1)[-1]
    raise AssertionError(f"no line for {name} {label_substr!r} in:\n{body}")


# ---- init / registry ----------------------------------------------------


def test_init_metrics_creates_all():
    m = _init()
    for key in (
        "tuning_proposals_total",
        "loop_generation_duration_seconds",
        "llm_maker_calls_total",
        "llm_checker_calls_total",
        "llm_tokens_total",
        "llm_latency_seconds",
        "llm_cost_usd_total",
        "llm_cache_hit_total",
        "pareto_front_size",
        "mc_agreement_rate",
        "suspicious_to_human_rate",
        "worker_timeout_total",
        "runs_disk_bytes",
        "loop_readiness_score",
    ):
        assert key in m, f"missing metric {key}"


def test_init_metrics_idempotent():
    a = _init()
    b = _init()
    assert a is b


# ---- record_proposal -----------------------------------------------------


def test_record_proposal_increments_label():
    mr.record_proposal("accepted")
    mr.record_proposal("accepted")
    mr.record_proposal("rejected")
    body = _scrape()
    assert _value(body, "tuning_proposals_total", 'decision="accepted"') == "2.0"
    assert _value(body, "tuning_proposals_total", 'decision="rejected"') == "1.0"


# ---- record_arbiter_agreement -------------------------------------------


def test_arbiter_agreement_rolling_average():
    mr.record_arbiter_agreement(True)
    mr.record_arbiter_agreement(True)
    mr.record_arbiter_agreement(False)
    body = _scrape()
    assert _value(body, "mc_agreement_rate") == "0.6666666666666666"


def test_arbiter_agreement_window_capped_at_50():
    for _ in range(60):
        mr.record_arbiter_agreement(True)
    body = _scrape()
    assert _value(body, "mc_agreement_rate") == "1.0"
    assert len(mr._mc_state["rolling"]) == 50


# ---- record_suspicious_to_human -----------------------------------------


def test_suspicious_to_human_rate():
    mr.record_suspicious_to_human("suspicious_to_human")
    mr.record_suspicious_to_human("accepted")
    mr.record_suspicious_to_human("accepted")
    body = _scrape()
    assert _value(body, "suspicious_to_human_rate") == "0.3333333333333333"


# ---- record_worker_timeout ----------------------------------------------


def test_record_worker_timeout_counter():
    mr.record_worker_timeout()
    mr.record_worker_timeout()
    body = _scrape()
    assert _value(body, "worker_timeout_total") == "2.0"


# ---- update_loop_readiness ----------------------------------------------


def test_update_loop_readiness():
    mr.update_loop_readiness(72.5)
    body = _scrape()
    assert _value(body, "loop_readiness_score") == "72.5"


# ---- record_llm_call -----------------------------------------------------


def test_record_llm_call_maker_counters():
    mr.record_llm_call("maker", tokens=100, latency=0.5, cost=0.01)
    body = _scrape()
    assert _value(body, "llm_maker_calls_total") == "1.0"
    assert _value(body, "llm_tokens_total", 'type="input"') == "50.0"
    assert _value(body, "llm_tokens_total", 'type="output"') == "50.0"
    assert _value(body, "llm_cost_usd_total") == "0.01"


def test_record_llm_call_checker_hit():
    mr.record_llm_call("checker", hit=True)
    body = _scrape()
    assert _value(body, "llm_checker_calls_total") == "1.0"
    assert _value(body, "llm_cache_hit_total") == "1.0"


def test_record_llm_call_unknown_type_only_tokens_recorded():
    """Unknown call_type only records tokens, not the maker/checker counter."""
    before = _scrape()
    mr.record_llm_call("other", tokens=10)
    body = _scrape()
    # The maker and checker counters are unchanged (still 0.0).
    assert _value(body, "llm_maker_calls_total") == "0.0"
    assert _value(body, "llm_checker_calls_total") == "0.0"
    assert _value(body, "llm_tokens_total", 'type="input"') == "5.0"
    assert body != before


# ---- record_generation ---------------------------------------------------


def test_record_generation_observation():
    mr.record_generation(12.5)
    body = _scrape()
    assert _value(body, "loop_generation_duration_seconds_count") == "1.0"


# ---- dynamic gauges ------------------------------------------------------


def test_dynamic_pareto_and_runs_gauge(monkeypatch, tmp_path):
    """Dynamic gauges are populated by the /metrics view's updater."""
    # Lay down a fake PARETO.json and a runs/ tree.
    from app.loop.pareto import ParetoPoint, ParetoSet, save

    save(
        tmp_path / "PARETO.json",
        ParetoSet(
            points=[
                ParetoPoint(
                    params_sha=f"p{i}", gen=0, cluster="C1", run_dir="/tmp",
                    sharpe=0.1, calmar=0.2, profit_factor=1.1, worst_regime_sharpe=0.0,
                    trade_count=10, fitness=1.0,
                )
                for i in range(3)
            ]
        ),
    )
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "a.txt").write_text("hi")
    monkeypatch.setenv("LOOP_STATE_ROOT", str(tmp_path))
    reset_app()
    body = get_app().test_client().get("/metrics").get_data(as_text=True)
    assert _value(body, "pareto_front_size") == "3.0"
    assert _value(body, "runs_disk_bytes") == "2.0"


def test_dynamic_loop_readiness_gauge_updates_on_scrape(monkeypatch):
    """``loop.loop_audit.compute_score`` is invoked on each scrape."""
    import sys

    calls = {"n": 0}

    def fake_compute_score():
        calls["n"] += 1
        return 88.0, "L3"

    monkeypatch.setitem(
        sys.modules,
        "loop.loop_audit",
        type("M", (), {"compute_score": staticmethod(fake_compute_score)})(),
    )
    reset_app()
    body = get_app().test_client().get("/metrics").get_data(as_text=True)
    assert calls["n"] >= 1
    assert _value(body, "loop_readiness_score") == "88.0"


# ---- /metrics endpoint ---------------------------------------------------


def test_metrics_endpoint_returns_prometheus_text():
    reset_app()
    c = get_app().test_client()
    r = c.get("/metrics")
    assert r.status_code == 200
    assert r.content_type.startswith("text/plain")
    body = r.get_data(as_text=True)
    assert "tuning_proposals_total" in body


# ---- record_binance_market_fetch --------------------------------------------


def test_record_binance_market_fetch_ok():
    """Successful fetch increments counter and observes latency."""
    _init()
    before = _scrape()
    mr.record_binance_market_fetch("mark_price", "ok", 0.123)
    body = _scrape()
    assert (
        _value(
            body,
            'binance_market_fetch_total{endpoint="mark_price",status="ok"}',
        )
        == "1.0"
    )
    assert (
        _value(
            body,
            "binance_market_latency_seconds_count",
            'endpoint="mark_price"',
        )
        == "1.0"
    )
    assert body != before


def test_record_binance_market_fetch_timeout_and_cli_error():
    """Status label distinguishes timeout vs cli_error outcomes."""
    _init()
    mr.record_binance_market_fetch("open_interest", "timeout", 5.0)
    mr.record_binance_market_fetch("open_interest", "cli_error", 0.5)
    body = _scrape()
    assert (
        _value(
            body,
            'binance_market_fetch_total{endpoint="open_interest",status="timeout"}',
        )
        == "1.0"
    )
    assert (
        _value(
            body,
            'binance_market_fetch_total{endpoint="open_interest",status="cli_error"}',
        )
        == "1.0"
    )


def test_record_binance_market_fetch_safe_with_unknown_label():
    """An unknown endpoint label still emits (Prometheus auto-creates it)."""
    _init()
    # Prometheus client lazily creates new label combinations.
    mr.record_binance_market_fetch("weird_endpoint", "ok", 0.001)
    body = _scrape()
    assert (
        _value(
            body,
            'binance_market_fetch_total{endpoint="weird_endpoint",status="ok"}',
        )
        == "1.0"
    )
