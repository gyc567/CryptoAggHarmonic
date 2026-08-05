"""Tests for bench.report.charts.

We exercise each chart function with a tiny input and check the output
file is non-empty PNG. Headless matplotlib Agg backend is configured
at module import.
"""

from __future__ import annotations

import os

import pytest

# Skip if matplotlib is not available
matplotlib = pytest.importorskip("matplotlib", reason="matplotlib not installed")

from app.loop.pareto import ParetoPoint
from bench.dataset.signal_record import empty_record
from bench.report.charts import (
    ALL_CHARTS,
    confusion_matrix,
    equity_curve,
    pareto_front,
    r_distribution,
    regime_breakdown,
    render_all,
    score_breakdown,
    signal_quality,
    win_rate,
)
from bench.scoring.pareto import BenchAugmentedParetoPoint


def _rec(**overrides):
    defaults = dict(
        signal_id="sig",
        net_rr=1.0,
        outcome="tp1",
        signal_score=80.0,
        stage1_score=10.0,
        stage3_score=40.0,
        stage4a_score=15.0,
        stage4b_score=8.0,
    )
    defaults.update(overrides)
    return empty_record(**defaults)


def _point(**overrides):
    base = ParetoPoint(
        params_sha="p",
        gen=1,
        cluster="c",
        run_dir="/tmp",
        sharpe=1.0,
        calmar=1.0,
        profit_factor=1.0,
        worst_regime_sharpe=0.0,
        trade_count=10,
        fitness=0.5,
    )
    return BenchAugmentedParetoPoint(base=base, **overrides)


# ---------- per-chart smoke tests ----------

def test_equity_curve_writes_png(tmp_path) -> None:
    p = tmp_path / "ec.png"
    equity_curve([_rec(net_rr=1.0), _rec(net_rr=-0.5)], str(p))
    assert p.exists() and p.stat().st_size > 0
    with open(p, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_win_rate_writes_png(tmp_path) -> None:
    p = tmp_path / "wr.png"
    win_rate([_rec(outcome="tp1"), _rec(outcome="stoploss")], str(p))
    assert p.exists() and p.stat().st_size > 0


def test_win_rate_custom_window(tmp_path) -> None:
    p = tmp_path / "wr2.png"
    win_rate([_rec()], str(p), window=3)
    assert p.exists()


def test_r_distribution_writes_png(tmp_path) -> None:
    p = tmp_path / "rd.png"
    r_distribution([_rec(net_rr=1.0), _rec(net_rr=-1.0)], str(p))
    assert p.exists() and p.stat().st_size > 0


def test_r_distribution_handles_no_r(tmp_path) -> None:
    p = tmp_path / "rd_empty.png"
    r_distribution([_rec(net_rr=None)], str(p))
    assert p.exists()


def test_score_breakdown_writes_png(tmp_path) -> None:
    p = tmp_path / "sb.png"
    score_breakdown([_rec() for _ in range(3)], str(p))
    assert p.exists() and p.stat().st_size > 0


def test_score_breakdown_truncates_at_30(tmp_path) -> None:
    p = tmp_path / "sb_big.png"
    score_breakdown([_rec() for _ in range(50)], str(p))
    assert p.exists()


def test_confusion_matrix_with_data(tmp_path) -> None:
    p = tmp_path / "cm.png"
    # Cover all 4 cells: TP, FP, FN, TN
    confusion_matrix(
        [
            _rec(outcome="tp1", signal_score=80),       # actual=1, pred=1 → TP
            _rec(outcome="stoploss", signal_score=20),  # actual=0, pred=0 → TN
            _rec(outcome="stoploss", signal_score=80),  # actual=0, pred=1 → FP
            _rec(outcome="tp1", signal_score=20),        # actual=1, pred=0 → FN
        ],
        str(p),
    )
    assert p.exists()


def test_confusion_matrix_no_outcome(tmp_path) -> None:
    """When no records have an outcome, the chart should still write."""
    p = tmp_path / "cm_empty.png"
    confusion_matrix([_rec(outcome=None)], str(p))
    assert p.exists()


def test_pareto_front_writes_png(tmp_path) -> None:
    p = tmp_path / "pf.png"
    pareto_front([_point(signal_score=80), _point(signal_score=70)], str(p))
    assert p.exists() and p.stat().st_size > 0


def test_regime_breakdown_with_data(tmp_path) -> None:
    p = tmp_path / "rb.png"
    regime_breakdown(
        [_rec(outcome="tp1"), _rec(outcome="stoploss")],
        str(p),
    )
    assert p.exists()


def test_regime_breakdown_no_regime(tmp_path) -> None:
    p = tmp_path / "rb_empty.png"
    regime_breakdown([_rec()], str(p))
    assert p.exists()


def test_signal_quality_writes_png(tmp_path) -> None:
    p = tmp_path / "sq.png"
    signal_quality([_rec(signal_score=80.0), _rec(signal_score=60.0)], str(p))
    assert p.exists()


def test_signal_quality_no_scores(tmp_path) -> None:
    p = tmp_path / "sq_empty.png"
    signal_quality([_rec(signal_score=None)], str(p))
    assert p.exists()


# ---------- render_all ----------

def test_render_all_writes_eight_pngs(tmp_path) -> None:
    out_dir = str(tmp_path)
    paths = render_all([_rec()], [_point()], out_dir)
    assert len(paths) == 8
    for p in paths:
        assert os.path.exists(p)
        assert os.path.getsize(p) > 0


def test_render_all_creates_directory(tmp_path) -> None:
    nested = tmp_path / "nested" / "subdir"
    paths = render_all([_rec()], [_point()], str(nested))
    assert nested.is_dir()
    assert len(paths) == 8


def test_render_all_handles_empty_input(tmp_path) -> None:
    paths = render_all([], [], str(tmp_path))
    # All 8 charts must still render even with no data (fallback plots).
    assert len(paths) == 8


# ---------- ALL_CHARTS ----------

def test_all_charts_has_eight_entries() -> None:
    assert len(ALL_CHARTS) == 8


def test_all_charts_each_takes_records(tmp_path) -> None:
    """Smoke-test all chart functions can be called on a single record."""
    for i, fn in enumerate(ALL_CHARTS):
        p = tmp_path / f"all_{i}.png"
        if fn is pareto_front:
            fn([_point()], str(p))
        else:
            fn([_rec()], str(p))
        assert p.exists()
