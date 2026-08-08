"""Loop audit — compute Loop Readiness Score.

Scores the project on L0-L3 maturity across 10 dimensions.
Designed to be run in CI and post results as a PR comment.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path

LOOP_STATE_ROOT = Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state"))
LOOP_DOCS = Path("docs/loop-state")


class Dimension:
    """One scoring dimension."""

    def __init__(
        self,
        name: str,
        weight: float,
        checks: Sequence[dict],
    ):
        self.name = name
        self.weight = weight
        self.checks = checks

    def score(self) -> float:
        """Return 0-100 for this dimension."""
        if not self.checks:
            return 0.0
        passed = sum(1 for c in self.checks if c["passed"])
        return (passed / len(self.checks)) * 100


def check_file_exists(path: Path, min_size: int = 10) -> dict:
    """Check if a file exists and has meaningful content."""
    return {
        "name": f"exists: {path}",
        "passed": path.exists() and path.stat().st_size >= min_size,
        "details": str(path),
    }


def check_workflow(name: str) -> dict:
    """Check if a GitHub Actions workflow exists."""
    wf_path = Path(f".github/workflows/{name}")
    return {
        "name": f"workflow: {name}",
        "passed": wf_path.exists(),
        "details": str(wf_path),
    }


def check_skill(name: str) -> dict:
    """Check if a skill directory exists."""
    skill_path = Path(f"skills/{name}/SKILL.md")
    return {
        "name": f"skill: {name}",
        "passed": skill_path.exists(),
        "details": str(skill_path),
    }


def check_gate_yaml() -> dict:
    """Check if gate.yaml is valid YAML with required keys."""
    gate = Path("docs/loop-state/gate.yaml")
    if not gate.exists():
        return {"name": "gate.yaml", "passed": False, "details": "not found"}
    import yaml

    try:
        with open(gate) as f:
            cfg = yaml.safe_load(f) or {}
        has_keys = all(k in cfg for k in ("denylist", "auto_merge_allowlist", "loop_paused"))
        denylist = cfg.get("denylist") or []
        has_tuning_gate = any("tuning.py" in str(p) for p in denylist)
        return {
            "name": "gate.yaml valid",
            "passed": has_keys and has_tuning_gate,
            "details": str(gate) if has_tuning_gate else "missing app/config/tuning.py denylist",
        }
    except Exception as e:
        return {"name": "gate.yaml valid", "passed": False, "details": str(e)}


def check_budget_defaults_enforced() -> dict:
    """Operational: search loop budget defaults match loop-budget.md."""
    search_py = Path("app/loop/search.py")
    if not search_py.exists():
        return {"name": "budget_defaults", "passed": False, "details": "app/loop/search.py missing"}
    text = search_py.read_text()
    ok = "DEFAULT_WEEKLY_BUDGET_USD = 25" in text and "DEFAULT_DOLLARS_PER_CPU_SECOND = 0.0001" in text
    return {
        "name": "budget_defaults",
        "passed": ok,
        "details": "weekly=25 cpu=0.0001" if ok else "defaults not aligned with loop-budget.md",
    }


def check_strategy_version_module() -> dict:
    """Operational: strategy_version (not skills_version) is the live module."""
    new = Path("app/loop/strategy_version.py").exists()
    old = Path("app/loop/skills_version.py").exists()
    return {
        "name": "strategy_version_module",
        "passed": new and not old,
        "details": "app/loop/strategy_version.py" if new and not old else "rename incomplete",
    }


def check_pending_issues_writer() -> dict:
    """Operational: state.write_pending_issue exists for outerloop."""
    state_py = Path("app/loop/state.py")
    if not state_py.exists():
        return {"name": "pending_issues_writer", "passed": False, "details": "state.py missing"}
    ok = "def write_pending_issue" in state_py.read_text()
    return {
        "name": "pending_issues_writer",
        "passed": ok,
        "details": "write_pending_issue" if ok else "writer missing",
    }


def check_memory_tiers() -> list[dict]:
    """Check memory tier files."""
    base = Path("docs/loop-state")
    return [
        check_file_exists(base / "MEMORY.md"),
        check_file_exists(base / "MEMORY-STATE.md"),
        check_file_exists(base / "memory-budget.md"),
    ]


def check_loop_files() -> list[dict]:
    """Check all LOOP.md required sections."""
    loop_md = Path("docs/loop-state/LOOP.md")
    if not loop_md.exists():
        return [check_file_exists(loop_md)]
    content = loop_md.read_text()
    required_sections = [
        "Daily Triage",
        "Issue Triage",
        "PR Babysitter",
        "CI Sweeper",
        "Dependency Sweeper",
        "Post-Merge",
        "Changelog Drafter",
    ]
    checks: list[dict] = []
    for section in required_sections:
        checks.append({
            "name": f"loop_section: {section}",
            "passed": section in content,
            "details": section,
        })
    return checks


# The 10 scoring dimensions with their weights
DIMENSIONS: list[Dimension] = [
    Dimension("LOOP.md", 10, [
        check_file_exists(LOOP_DOCS / "LOOP.md"),
        *check_loop_files(),
    ]),
    Dimension("STATE.md", 10, [
        check_file_exists(LOOP_DOCS / "STATE.md"),
    ]),
    Dimension("Memory", 10, [
        check_file_exists(LOOP_DOCS / "MEMORY.md"),
        check_file_exists(LOOP_DOCS / "memory-budget.md"),
        *check_memory_tiers(),
    ]),
    Dimension("Skills", 10, [
        check_skill("loop-triage"),
        check_skill("loop-handoff"),
        check_skill("backtest-verify"),
        check_skill("signal-eval"),
    ]),
    Dimension("GitHub Actions", 15, [
        check_workflow("daily-triage.yml"),
        check_workflow("ci-sweeper.yml"),
        check_workflow("changelog-drafter.yml"),
        check_workflow("audit.yml"),
        check_workflow("issue-triage.yml"),
    ]),
    Dimension("Worktree Isolation", 5, [
        check_file_exists(Path("loop/loop_worktree.py")),
    ]),
    Dimension("Token Budget", 10, [
        check_file_exists(Path("docs/loop-state/loop-budget.md")),
        check_gate_yaml(),
        check_budget_defaults_enforced(),
    ]),
    Dimension("Gate.yaml", 10, [
        check_gate_yaml(),
        check_file_exists(Path("app/loop/tuning_promotion.py")),
    ]),
    Dimension("CLI Tools", 10, [
        check_file_exists(Path("loop/loop.py")),
        check_file_exists(Path("loop/loop_gate.py")),
        check_strategy_version_module(),
        check_pending_issues_writer(),
    ]),
    Dimension("ADR", 10, [
        check_file_exists(Path("docs/adr/0003-loop-engineering-integration.md")),
    ]),
]


def compute_score() -> tuple[float, str]:
    """Compute overall Loop Readiness Score (0-100)."""
    total_weight = sum(d.weight for d in DIMENSIONS)
    weighted_sum = sum(d.score() * d.weight for d in DIMENSIONS)
    raw = weighted_sum / total_weight if total_weight else 0

    # Map to L0-L3
    if raw >= 85:
        level = "L3"
    elif raw >= 58:
        level = "L2"
    elif raw >= 30:
        level = "L1"
    else:
        level = "L0"

    return round(raw, 1), level


def format_json(score: float, level: str) -> str:
    """Format audit result as JSON."""
    details = []
    for d in DIMENSIONS:
        s = d.score()
        details.append({
            "dimension": d.name,
            "weight": d.weight,
            "score": round(s, 1),
            "checks": d.checks,
        })
    return json.dumps({
        "score": score,
        "level": level,
        "dimensions": details,
    }, indent=2)


def format_text(score: float, level: str) -> str:
    """Format audit result as human-readable text."""
    lines = [
        f"Loop Readiness Score: {score}/100 [{level}]",
        "",
    ]
    for d in DIMENSIONS:
        s = d.score()
        bar = "█" * int(s / 10) + "░" * (10 - int(s / 10))
        lines.append(f"  {d.name:<22} {bar} {s:5.1f}%")
    lines.append("")
    lines.append(f"Overall: {score}/100 [{level}]")
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Compute Loop Readiness Score")
    parser.add_argument("path", nargs="?", default=".", help="Repo root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--suggest", action="store_true", help="Show copy commands for gaps")
    args = parser.parse_args()

    os.chdir(args.path)

    score, level = compute_score()

    if args.json:
        print(format_json(score, level))
    else:
        print(format_text(score, level))

    if args.suggest:
        print("\n--- Suggestions ---\n")
        for d in DIMENSIONS:
            failed = [c for c in d.checks if not c["passed"]]
            for c in failed:
                print(f"  # {d.name}: {c['name']}")
                print(f"    {c['details']}\n")

    # Exit code: 0 if L2+, 1 if below
    return 0 if score >= 58 else 1


if __name__ == "__main__":
    sys.exit(main())
