"""Review — CLI for human review of ``suspicious_to_human`` candidates.

This is the v1 human-in-the-loop interface (audit §2.6). It is
intentionally minimal: list pending candidates, show the three columns
(Maker reasoning | Checker report | raw metrics), and accept one of
``a`` (accept), ``r`` (reject), ``m`` (mark as reviewed-no-action).

Persistence: appends decisions to ``HUMAN_REVIEW_LOG.jsonl`` in the
loop state root. The format is one JSON object per line.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOG_FILENAME = "HUMAN_REVIEW_LOG.jsonl"


@dataclass(frozen=True)
class HumanReviewDecision:
    """One decision recorded by a human reviewer."""

    candidate_id: str
    decision: str  # "accept" | "reject" | "no_action"
    reviewer: str
    timestamp: str
    notes: str = ""

    VALID_DECISIONS = ("accept", "reject", "no_action")

    def __post_init__(self) -> None:
        if self.decision not in self.VALID_DECISIONS:
            raise ValueError(f"decision must be one of {self.VALID_DECISIONS}; " f"got {self.decision!r}")
        if not self.candidate_id:
            raise ValueError("candidate_id is required")
        if not self.reviewer:
            raise ValueError("reviewer is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp,
            "notes": self.notes,
        }


def _log_path(state_root: Path) -> Path:
    return state_root / LOG_FILENAME


def append_decision(state_root: Path, decision: HumanReviewDecision) -> None:
    """Append ``decision`` to the human review log (atomic per line)."""
    state_root.mkdir(parents=True, exist_ok=True)
    path = _log_path(state_root)
    line = json.dumps(decision.to_dict(), sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def load_pending(
    state_root: Path,
) -> list[dict[str, Any]]:
    """Return all pending decisions from the log that haven't been acted on.

    For v1 the log only records **decisions**, not pending items; the
    pending list comes from ``STATE.md`` (or the caller passes them in).
    This helper exists for symmetry and future expansion.
    """
    path = _log_path(state_root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ---- CLI ------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maker-checker-review",
        description="Human review CLI for suspicious_to_human candidates.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path(".scratch/loop_state"),
        help="Loop state root directory (default: .scratch/loop_state).",
    )
    parser.add_argument(
        "--reviewer",
        default="human",
        help="Reviewer identifier (recorded in HUMAN_REVIEW_LOG).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recorded decisions.")
    p_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent entries to show.",
    )

    p_record = sub.add_parser(
        "record",
        help="Record a decision for a candidate.",
    )
    p_record.add_argument("--candidate-id", required=True)
    p_record.add_argument(
        "--decision",
        choices=HumanReviewDecision.VALID_DECISIONS,
        required=True,
    )
    p_record.add_argument("--notes", default="")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.cmd == "list":
        entries = load_pending(args.state_root)
        entries = entries[-args.limit :]
        if not entries:
            print("(no decisions recorded yet)")
            return 0
        for entry in entries:
            print(f"{entry['timestamp']}  {entry['reviewer']:<10}  " f"{entry['decision']:<10}  {entry['candidate_id']}")
            if entry.get("notes"):
                print(f"    notes: {entry['notes']}")
        return 0

    if args.cmd == "record":
        decision = HumanReviewDecision(
            candidate_id=args.candidate_id,
            decision=args.decision,
            reviewer=args.reviewer,
            timestamp=datetime.now(timezone.utc).isoformat(),
            notes=args.notes,
        )
        append_decision(args.state_root, decision)
        print(f"recorded: {decision.candidate_id} -> {decision.decision} " f"by {decision.reviewer}")
        return 0

    parser.print_help()  # pragma: no cover  # argparse with required=True already exits 2
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
