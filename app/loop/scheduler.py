"""Adaptive heartbeat scheduler.

The loop runs in the background on a developer's machine (or a cron-like
service). We don't want it to spin on a fixed 30-minute cadence — that
wastes cycles when nothing's changing and starves when the operator
manually feeds new candidates. The scheduler picks the next wake time
based on:

* how long since the last Pareto improvement
* local "market hours" (skip overnight + weekends for crypto it's almost
  always live, but equities would be 9:30–16:00 ET Mon-Fri)
* a configurable max interval (default 60 minutes)

Decision logic (simplified):

* If ``plateau_count`` (consecutive gens without Pareto movement) ≥ 5,
  skip until tomorrow morning (anti-plateau back-off).
* Else, schedule the next wake in:
    - 5 minutes   if there's a pending operator action in NEXT_QUEUE.md
    - 15 minutes  if last improvement was within 24 hours
    - 30 minutes  if last improvement was within a week
    - 60 minutes  otherwise

This is intentionally simple. Real-world deployments will refine the
heuristics based on observed throughput.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.loop.state import DEFAULT_ROOT


# --- Configuration -----------------------------------------------------------


@dataclass
class SchedulerConfig:
    """Tunable knobs for :func:`next_wake_at`."""

    max_interval_minutes: int = 60
    plateau_backoff_gens: int = 5
    # Crypto is 24/7 but the operator probably sleeps — back off overnight.
    quiet_hours_start: int = 23  # 23:00 local
    quiet_hours_end: int = 7  # 07:00 local
    weekend_skip: bool = False  # crypto never sleeps; set True for equities


# --- Plateau / Pareto inspection ---------------------------------------------


def plateau_count_from_history(history_path: Path) -> int:
    """Count consecutive trailing generations where Pareto did not grow.

    A Pareto "growth" event is one where the new candidate's
    ``decision=="accepted"`` AND its fitness was strictly higher than the
    previous best on the same cluster.

    The function reads HISTORY.jsonl from the end and counts backwards
    until it finds a generation with Pareto movement. Returns 0 if all
    recent gens had growth.
    """
    if not history_path.exists():
        return 0
    # Walk all lines (file is bounded by the rotation logic). Build a map
    # gen → max fitness.
    best_per_gen: dict[int, float] = {}
    with open(history_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                import json
                rec = json.loads(line)
            except Exception:
                continue
            gen = rec.get("gen")
            fit = rec.get("fitness") or 0.0
            if rec.get("decision") == "accepted":
                if gen not in best_per_gen or fit > best_per_gen[gen]:
                    best_per_gen[gen] = fit
    if not best_per_gen:
        return 0
    # Count trailing gens without fitness improvement.
    gens_sorted = sorted(best_per_gen.keys())
    plateau = 0
    prev_fit = best_per_gen[gens_sorted[0]]
    for g in gens_sorted[1:]:
        if best_per_gen[g] > prev_fit:
            prev_fit = best_per_gen[g]
            plateau = 0
        else:
            plateau += 1
    return plateau


# --- Market hours / quiet hours ----------------------------------------------


def _in_quiet_hours(now: _dt.datetime, cfg: SchedulerConfig) -> bool:
    h = now.hour
    if cfg.quiet_hours_start < cfg.quiet_hours_end:
        return cfg.quiet_hours_start <= h < cfg.quiet_hours_end
    # Wraps midnight (e.g. 23 → 7).
    return h >= cfg.quiet_hours_start or h < cfg.quiet_hours_end


def _is_weekend(now: _dt.datetime, cfg: SchedulerConfig) -> bool:
    if not cfg.weekend_skip:
        return False
    return now.weekday() >= 5  # Sat=5, Sun=6


# --- Next-wake decision ------------------------------------------------------


@dataclass
class WakeDecision:
    """What the scheduler decided."""

    wake_at: _dt.datetime
    reason: str
    plateau_count: int
    last_improvement_age_hours: Optional[float]


def next_wake_at(
    *,
    now: Optional[_dt.datetime] = None,
    cfg: Optional[SchedulerConfig] = None,
    history_path: Optional[Path] = None,
    pending_operator_action: bool = False,
) -> WakeDecision:
    """Return when the loop should next wake up.

    ``now`` defaults to local time; tests can pin it. ``history_path``
    defaults to ``loop_state/HISTORY.jsonl`` under
    :data:`app.loop.state.DEFAULT_ROOT`.
    """
    now = now or _dt.datetime.now()
    cfg = cfg or SchedulerConfig()
    history_path = history_path or (Path(DEFAULT_ROOT) / "HISTORY.jsonl")

    plateau = plateau_count_from_history(history_path)

    # Quiet hours / weekend — back off to the start of the next active window.
    if _in_quiet_hours(now, cfg) or _is_weekend(now, cfg):
        wake = _next_active_window(now, cfg)
        return WakeDecision(
            wake_at=wake,
            reason=f"quiet hours/weekend (plateau={plateau})",
            plateau_count=plateau,
            last_improvement_age_hours=None,
        )

    # Operator wants action soon — 5 minutes.
    if pending_operator_action:
        return WakeDecision(
            wake_at=now + _dt.timedelta(minutes=5),
            reason="operator action pending in NEXT_QUEUE.md",
            plateau_count=plateau,
            last_improvement_age_hours=None,
        )

    # Plateau back-off — once we cross the threshold, skip until tomorrow
    # morning even within active hours.
    if plateau >= cfg.plateau_backoff_gens:
        wake = _next_active_window(now, cfg)
        return WakeDecision(
            wake_at=wake,
            reason=(
                f"plateau reached {plateau} gens ≥ {cfg.plateau_backoff_gens} "
                f"threshold — anti-plateau back-off"
            ),
            plateau_count=plateau,
            last_improvement_age_hours=None,
        )

    # Otherwise: scale by recent improvement recency.
    last_age = _last_improvement_age_hours(history_path, now=now)
    if last_age is not None and last_age < 24:
        delta = _dt.timedelta(minutes=15)
        reason = "last improvement < 24h"
    elif last_age is not None and last_age < 24 * 7:
        delta = _dt.timedelta(minutes=30)
        reason = "last improvement < 7d"
    else:
        delta = _dt.timedelta(minutes=cfg.max_interval_minutes)
        reason = f"no recent improvement (max {cfg.max_interval_minutes}m)"

    return WakeDecision(
        wake_at=now + delta,
        reason=reason,
        plateau_count=plateau,
        last_improvement_age_hours=last_age,
    )


def _next_active_window(now: _dt.datetime, cfg: SchedulerConfig) -> _dt.datetime:
    """Return the start of the next active window (post-quiet-hours)."""
    candidate = now
    for _ in range(48):  # up to 48h lookahead
        candidate += _dt.timedelta(hours=1)
        if not _in_quiet_hours(candidate, cfg) and not _is_weekend(candidate, cfg):
            # Snap to the hour boundary.
            return candidate.replace(minute=0, second=0, microsecond=0)
    # Fallback: 24h from now, no snap.
    return now + _dt.timedelta(hours=24)


def _last_improvement_age_hours(
    history_path: Path, *, now: _dt.datetime,
) -> Optional[float]:
    """Find the most recent Pareto-growth event in HISTORY.jsonl and
    return the age in hours. ``None`` means never improved or no file.
    """
    if not history_path.exists():
        return None
    best_per_gen: dict[int, float] = {}
    last_ts_per_gen: dict[int, float] = {}
    import json
    with open(history_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            gen = rec.get("gen")
            fit = rec.get("fitness") or 0.0
            ts = rec.get("ts")
            if rec.get("decision") != "accepted" or gen is None or ts is None:
                continue
            if gen not in best_per_gen or fit > best_per_gen[gen]:
                best_per_gen[gen] = fit
                last_ts_per_gen[gen] = ts
    if not best_per_gen:
        return None
    # Latest growth = max gen with strictly increasing fitness.
    gens = sorted(best_per_gen.keys())
    last_growth_ts = None
    prev = best_per_gen[gens[0]]
    last_growth_ts = last_ts_per_gen[gens[0]]
    for g in gens[1:]:
        if best_per_gen[g] > prev:
            prev = best_per_gen[g]
            last_growth_ts = last_ts_per_gen[g]
    if last_growth_ts is None:
        return None
    delta = now - _dt.datetime.fromtimestamp(last_growth_ts)
    return delta.total_seconds() / 3600.0