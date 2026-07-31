"""8 matplotlib charts for the bench report.

Each chart takes either a Sequence[SignalRecord] (per-signal charts)
or a Sequence[BenchAugmentedParetoPoint] (front-level charts), plus
an output path. Charts write to a file via ``matplotlib``'s Agg
backend so they can be rendered headlessly in CI.

Per v3 changelog item 17 the 8 charts are:
 1. equity_curve        — cumulative r over signals
 2. win_rate            — rolling win rate (window=10)
 3. r_distribution      — histogram of r_multiple
 4. score_breakdown     — stacked bar: stage1/3/4a/4b per signal
 5. confusion_matrix    — predicted vs actual outcomes
 6. pareto_front        — Sharpe vs bench_total scatter
 7. regime_breakdown    — win rate per regime (placeholder)
 8. signal_quality      — signal_score histogram
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt  # noqa: E402

from bench.dataset.signal_record import SignalRecord
from bench.scoring.pareto import BenchAugmentedParetoPoint  # noqa: E402


def _save(fig, path: str) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def equity_curve(records: Sequence[SignalRecord], path: str) -> None:
    """Cumulative r_multiple across signals (in given order)."""
    cum = []
    s = 0.0
    for r in records:
        if r.net_rr is not None:
            s += r.net_rr
        cum.append(s)
    fig, ax = plt.subplots()
    ax.plot(range(len(cum)), cum, marker="o", markersize=2)
    ax.set_xlabel("signal index")
    ax.set_ylabel("cumulative R")
    ax.set_title("Equity Curve")
    ax.axhline(0, color="grey", linewidth=0.5)
    _save(fig, path)


def win_rate(records: Sequence[SignalRecord], path: str, window: int = 10) -> None:
    """Rolling win rate over a sliding window."""
    outcomes = [1 if r.outcome in ("tp1", "tp2", "tp3") else 0 for r in records]
    rolling = []
    for i in range(len(outcomes)):
        lo = max(0, i - window + 1)
        win = outcomes[lo:i + 1]
        rolling.append(sum(win) / len(win))
    fig, ax = plt.subplots()
    ax.plot(range(len(rolling)), rolling, marker="o", markersize=2)
    ax.set_xlabel("signal index")
    ax.set_ylabel(f"win rate (window={window})")
    ax.set_title("Rolling Win Rate")
    ax.set_ylim(0, 1)
    _save(fig, path)


def r_distribution(records: Sequence[SignalRecord], path: str) -> None:
    """Histogram of r_multiple."""
    rs = [r.net_rr for r in records if r.net_rr is not None]
    fig, ax = plt.subplots()
    ax.hist(rs, bins=30, edgecolor="black")
    ax.set_xlabel("r_multiple")
    ax.set_ylabel("count")
    ax.set_title("R-Multiple Distribution")
    ax.axvline(0, color="red", linewidth=0.5)
    _save(fig, path)


def score_breakdown(records: Sequence[SignalRecord], path: str) -> None:
    """Stacked bar: stage1/3/4a/4b per signal (top 30 to keep it legible)."""
    sample = list(records[:30])
    s1 = [r.stage1_score or 0 for r in sample]
    s3 = [r.stage3_score or 0 for r in sample]
    s4a = [r.stage4a_score or 0 for r in sample]
    s4b = [r.stage4b_score or 0 for r in sample]
    fig, ax = plt.subplots()
    x = range(len(sample))
    ax.bar(x, s1, label="stage1")
    ax.bar(x, s3, bottom=s1, label="stage3")
    ax.bar(x, s4a, bottom=[a + b for a, b in zip(s1, s3)], label="stage4a")
    ax.bar(
        x, s4b,
        bottom=[a + b + c for a, b, c in zip(s1, s3, s4a)],
        label="stage4b",
    )
    ax.set_xlabel("signal index")
    ax.set_ylabel("score")
    ax.set_title("Score Breakdown")
    ax.legend(loc="best", fontsize=8)
    _save(fig, path)


def confusion_matrix(records: Sequence[SignalRecord], path: str) -> None:
    """Predicted (signal_score >= 50) vs actual outcome."""
    actual = []
    predicted = []
    for r in records:
        if r.outcome is None:
            continue
        actual.append(1 if r.outcome in ("tp1", "tp2", "tp3") else 0)
        predicted.append(1 if (r.signal_score or 0) >= 50 else 0)

    if not actual:
        # Empty fallback: just write a placeholder chart
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "no data", ha="center", va="center")
        ax.axis("off")
        _save(fig, path)
        return

    # Build 2x2 counts
    tp = fp = tn = fn = 0
    for a, p in zip(actual, predicted):
        if a and p:
            tp += 1
        elif a and not p:
            fn += 1
        elif not a and p:
            fp += 1
        else:
            tn += 1

    matrix = [[tn, fp], [fn, tp]]
    fig, ax = plt.subplots()
    ax.imshow(matrix, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, matrix[i][j], ha="center", va="center", color="black")
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(["pred loss", "pred win"])
    ax.set_yticklabels(["actual loss", "actual win"])
    ax.set_title("Confusion Matrix")
    _save(fig, path)


def pareto_front(points: Sequence[BenchAugmentedParetoPoint], path: str) -> None:
    """Sharpe (x) vs bench_total (y) scatter."""
    fig, ax = plt.subplots()
    xs = [p.base.sharpe for p in points]
    ys = [p.bench_total for p in points]
    ax.scatter(xs, ys, s=20, alpha=0.7)
    ax.set_xlabel("Sharpe (live fitness)")
    ax.set_ylabel("bench_total")
    ax.set_title("Pareto Front: Sharpe × bench_total")
    ax.axhline(50, color="grey", linewidth=0.5, linestyle="--")
    _save(fig, path)


def regime_breakdown(records: Sequence[SignalRecord], path: str) -> None:
    """Win rate per regime. v3 spec uses a placeholder regime field;
    if empty, draw a 'no regime data' notice."""
    regimes = {}
    for r in records:
        regime = getattr(r, "regime", None) or "unknown"
        regimes.setdefault(regime, []).append(
            1 if r.outcome in ("tp1", "tp2", "tp3") else 0
        )
    fig, ax = plt.subplots()
    if not regimes:
        ax.text(0.5, 0.5, "no regime data", ha="center", va="center")
        ax.axis("off")
    else:
        labels = sorted(regimes)
        wrs = [sum(regimes[k]) / len(regimes[k]) for k in labels]
        ax.bar(labels, wrs)
        ax.set_ylabel("win rate")
        ax.set_ylim(0, 1)
        ax.set_title("Win Rate by Regime")
    _save(fig, path)


def signal_quality(records: Sequence[SignalRecord], path: str) -> None:
    """signal_score histogram."""
    scores = [r.signal_score for r in records if r.signal_score is not None]
    fig, ax = plt.subplots()
    if scores:
        ax.hist(scores, bins=20, edgecolor="black")
    else:
        ax.text(0.5, 0.5, "no scores", ha="center", va="center")
        ax.axis("off")
    ax.set_xlabel("signal_score")
    ax.set_ylabel("count")
    ax.set_title("Signal Quality Distribution")
    _save(fig, path)


ALL_CHARTS = (
    equity_curve,
    win_rate,
    r_distribution,
    score_breakdown,
    confusion_matrix,
    pareto_front,
    regime_breakdown,
    signal_quality,
)


def render_all(
    records: Sequence[SignalRecord],
    points: Sequence[BenchAugmentedParetoPoint],
    out_dir: str,
) -> List[str]:
    """Render all 8 charts into ``out_dir``. Returns the list of paths."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []
    # per-signal charts
    for fn, name in (
        (equity_curve, "equity_curve"),
        (win_rate, "win_rate"),
        (r_distribution, "r_distribution"),
        (score_breakdown, "score_breakdown"),
        (confusion_matrix, "confusion_matrix"),
        (regime_breakdown, "regime_breakdown"),
        (signal_quality, "signal_quality"),
    ):
        p = os.path.join(out_dir, f"{name}.png")
        fn(records, p)
        paths.append(p)
    # front-level
    p = os.path.join(out_dir, "pareto_front.png")
    pareto_front(points, p)
    paths.append(p)
    return paths
