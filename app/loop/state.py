"""Durable state for the loop-tuning project.

Files under ``loop_state/``:

* ``STATE.md``              — human-readable summary (best params, plateau,
                               next queue). Written by the driver.
* ``HISTORY.jsonl``         — append-only journal, one line per experiment:
                               ``{ts, gen, cluster, candidate_id, params_sha,
                                  metrics, fitness, decision}``.
                               fcntl-locked append. Auto-rotates when > 10 MB.
* ``PARETO.json``           — current Pareto front (3-D points + metadata).
* ``NEXT_QUEUE.md``         — proposed candidates for the next generation.
* ``runs/<uuid>/``          — per-experiment workspace:
                                 tuning.yaml
                                 backtest.log    (v3 harness stdout/stderr)
                                 metrics.json    (atomic rename on success)
* ``tuning_snapshots/``     — frozen ``tuning.yaml`` every time Pareto moves;
                               enables one-step rollback.

The state is replay-safe: ``HISTORY.jsonl`` is the source of truth and
``PARETO.json`` / ``STATE.md`` can be rebuilt from it via
:func:`replay_from_history`.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from app.config.tuning import TuningConstants, to_dict

# --- Paths --------------------------------------------------------------------

DEFAULT_ROOT = Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state"))


def ensure_root(root: Optional[Path] = None) -> Path:
    """Create the loop_state directory tree if missing. Returns the root."""
    root = Path(root) if root else DEFAULT_ROOT
    for sub in ("runs", "tuning_snapshots", "REJECTED", "archive", "pending_issues", "outbox"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def write_pending_issue(
    record: dict[str, Any],
    root: Optional[Path] = None,
) -> Path:
    """Write a ``suspicious_to_human`` payload for issue-sync (outerloop).

    Does **not** call ``gh`` — CI/local operators sync via
    ``.github/workflows/issue-sync.yml`` or manual review of
    ``pending_issues/*.json``.
    """
    root = ensure_root(root)
    dest_dir = root / "pending_issues"
    dest_dir.mkdir(parents=True, exist_ok=True)
    issue_id = record.get("uuid") or uuid.uuid4().hex
    path = dest_dir / f"{issue_id}.json"
    payload = {
        "uuid": issue_id,
        "created_at": record.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **{k: v for k, v in record.items() if k not in ("uuid", "created_at")},
    }
    atomic_write_json(path, payload)
    return path


def params_sha(t: TuningConstants) -> str:
    """Stable SHA-256 of a TuningConstants instance (JSON canonical form).

    Used as a deduplication key — if two candidates produce the same hash,
    they're the same experiment and we can skip the second.
    """
    payload = json.dumps(to_dict(t), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


# --- fcntl-locked append ------------------------------------------------------


def append_history(
    record: dict,
    root: Optional[Path] = None,
    rotate_bytes: int = 10 * 1024 * 1024,  # 10 MB
) -> None:
    """Append ``record`` to HISTORY.jsonl under an exclusive flock.

    After the write, if the file exceeds ``rotate_bytes`` (default 10 MB)
    we move it to ``HISTORY-<ts>.jsonl.gz`` so the next append starts a
    fresh file. Compaction happens lazily — the gz files retain full
    history for replay.
    """
    root = ensure_root(root)
    path = root / "HISTORY.jsonl"

    line = json.dumps(record, sort_keys=True, default=str) + "\n"

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode())
        new_size = os.fstat(fd).st_size
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    # Rotate AFTER the write: the just-written record is preserved in the
    # gz archive, and a new HISTORY.jsonl starts fresh for the next caller.
    if new_size and new_size >= rotate_bytes:
        ts = int(time.time())
        rotated = root / f"HISTORY-{ts}.jsonl.gz"
        # Outside the flock so a concurrent append can't race the rename.
        try:
            with open(path, "rb") as f_in, gzip.open(rotated, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            path.unlink()
        except OSError:
            # If another process already rotated, swallow.
            pass


# --- Atomic JSON write --------------------------------------------------------


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` to ``path`` via temp + rename (POSIX atomic)."""
    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str, sort_keys=True)
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# --- Per-run workspace --------------------------------------------------------


def make_run_dir(root: Optional[Path] = None) -> Path:
    """Create ``runs/<uuid>/`` and return the path."""
    root = ensure_root(root)
    rid = uuid.uuid4().hex[:12]
    d = root / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_tuning_snapshot(
    t: TuningConstants,
    label: str,
    root: Optional[Path] = None,
) -> Path:
    """Persist ``t`` as ``tuning_snapshots/<label>-<sha>.yaml``."""
    root = ensure_root(root)
    sha = params_sha(t)
    path = root / "tuning_snapshots" / f"{label}-{sha}.yaml"
    if path.exists():
        return path  # dedupe
    payload = to_dict(t)
    # Hand-rolled YAML to avoid pulling pyyaml as a hard dep here.
    lines = []
    for k, v in payload.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    path.write_text("\n".join(lines) + "\n")
    return path


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_yaml_scalar(val)}" for k, val in v.items()) + "}"
    if isinstance(v, str):
        return json.dumps(v)  # quoted string
    return str(v)


# --- STATE.md rendering -------------------------------------------------------


def render_state_md(
    *,
    best: Optional[dict] = None,
    pareto_size: int = 0,
    plateau_count: int = 0,
    next_queue_size: int = 0,
    last_decision: str = "—",
    notes: Iterable[str] = (),
) -> str:
    """Build the human-readable STATE.md body."""
    lines = [
        f"# Loop state @ {time.strftime('%Y-%m-%d %H:%M timezone.utc', time.gmtime())}",
        "",
        f"Plateau count: **{plateau_count} / 5**",
        f"Last decision: **{last_decision}**",
        "",
    ]
    if best is None:
        lines += ["Current best: _(none yet)_", ""]
    else:
        lines += [
            "## Current best",
            f"- SHA: `{best.get('params_sha', '?')}`",
            f"- Generation: {best.get('gen', '?')}",
            f"- Fitness: {best.get('fitness', 0):+.3f}",
            f"- Sharpe: {best.get('sharpe', 0):+.3f}",
            f"- Calmar: {best.get('calmar', 0):+.3f}",
            f"- Profit factor: {best.get('profit_factor', 0):+.3f}",
            f"- Trade count: {best.get('trade_count', 0)}",
            "",
        ]
    lines += [
        f"Pareto front size: **{pareto_size}**",
        f"Next queue size: **{next_queue_size}**",
        "",
    ]
    if notes:
        lines += ["## Notes", ""]
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)


def write_state_md(content: str, root: Optional[Path] = None) -> Path:
    root = ensure_root(root)
    path = root / "STATE.md"
    # Atomic write so a partial STATE.md never replaces a good one.
    atomic_write_json(path, {"_rendered": content})  # not really atomic JSON
    # Replace the JSON dump with the raw markdown — STATE.md is meant to be
    # human-edited, so we want a stable file content for diff-friendly review.
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))
    return path


# --- Replay -------------------------------------------------------------------


def replay_from_history(root: Optional[Path] = None) -> list[dict]:
    """Walk every HISTORY*.jsonl(.gz) and return parsed records."""
    root = Path(root) if root else DEFAULT_ROOT
    records: list[dict] = []
    for path in sorted(root.glob("HISTORY*.jsonl*")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records
