"""Loop CLI — unified front door for loop engineering tools.

Usage:
    python -m loop.loop doctor [path]
    python -m loop.loop status [path]
    python -m loop.loop audit [path] [--json] [--suggest]
    python -m loop.loop gate check [path]
    python -m loop.loop sync check [path]
    python -m loop.loop cost --pattern {pattern}
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state"))


def cmd_doctor(path: str) -> int:
    """Run loop readiness checks without scoring."""
    print("=== Loop Doctor ===")
    checks = [
        ("LOOP.md", Path(path) / "docs/loop-state/LOOP.md"),
        ("STATE.md", Path(path) / "docs/loop-state/STATE.md"),
        ("MEMORY.md", Path(path) / "docs/loop-state/MEMORY.md"),
        ("gate.yaml", Path(path) / "docs/loop-state/gate.yaml"),
        ("CLAUDE.md", Path(path) / "CLAUDE.md"),
        ("AGENTS.md", Path(path) / "AGENTS.md"),
    ]
    all_ok = True
    for name, p in checks:
        status = "✅" if p.exists() else "❌"
        print(f"  {status} {name}")
        if not p.exists():
            all_ok = False
    print()
    if all_ok:
        print("All core files present.")
        return 0
    print("Some core files are missing. Run `loop audit --suggest` for details.")
    return 1


def cmd_status(path: str) -> int:
    """Show current loop state summary."""
    from loop.loop_gate import load_gate_config

    print("=== Loop Status ===")
    state_md = Path(path) / "docs/loop-state/STATE.md"
    if state_md.exists():
        content = state_md.read_text()
        # Extract first 10 lines
        lines = content.strip().split("\n")[:10]
        print("STATE.md preview:")
        for l in lines:
            print(f"  {l}")
    else:
        print("  STATE.md not found")

    cfg = load_gate_config()
    print(f"\nloop_paused: {cfg.get('loop_paused', False)}")
    print(f"min_readiness_score: {cfg.get('min_readiness_score', 58)}")

    loop_state = Path(path) / ROOT
    if loop_state.exists():
        print(f"\nloop_state root: {loop_state}")
        entries = list(loop_state.iterdir())
        print(f"  entries: {[e.name for e in entries]}")
    return 0


def cmd_audit(path: str, json: bool = False, suggest: bool = False) -> int:
    """Run Loop Readiness Score audit."""
    os.chdir(path)
    from loop.loop_audit import main as audit_main

    sys.argv = ["loop-audit", path]
    if json:
        sys.argv.append("--json")
    if suggest:
        sys.argv.append("--suggest")
    return audit_main()


def cmd_gate(action: str, path: str) -> int:
    """Check gate.yaml."""
    from loop.loop_gate import main as gate_main

    os.chdir(path)
    sys.argv = ["loop-gate", action]
    return gate_main()


def cmd_sync(action: str, path: str, file: str | None = None) -> int:
    """Check LOOP.md / STATE.md consistency, or add a loop."""
    from loop.loop_sync import main as sync_main

    os.chdir(path)
    sys.argv = ["loop-sync", action, "--path", path]
    if action == "add-loop" and file:
        sys.argv.append(file)
    return sync_main()


def cmd_cost(pattern: str) -> int:
    """Estimate token spend for a pattern."""
    # Simple estimation based on pattern type
    estimates = {
        "daily-triage": 5000,
        "pr-babysitter": 3000,
        "ci-sweeper": 8000,
        "changelog-drafter": 15000,
        "gen": 50000,  # per generation
    }
    tokens = estimates.get(pattern, 5000)
    cost = tokens * 0.00001  # rough $0.00001/token
    print(f"Pattern: {pattern}")
    print(f"Estimated tokens: {tokens:,}")
    print(f"Estimated cost: ${cost:.4f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m loop.loop",
        description="Loop engineering CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # doctor
    d = sub.add_parser("doctor", help="Check core files exist")
    d.add_argument("path", nargs="?", default=".")

    # status
    s = sub.add_parser("status", help="Show loop state summary")
    s.add_argument("path", nargs="?", default=".")

    # audit
    a = sub.add_parser("audit", help="Compute Loop Readiness Score")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--json", action="store_true")
    a.add_argument("--suggest", action="store_true")

    # gate
    g = sub.add_parser("gate", help="Check gate.yaml")
    g.add_argument("action", nargs="?", default="check")
    g.add_argument("path", nargs="?", default=".")

    # sync
    c = sub.add_parser("sync", help="Check LOOP/STATE consistency")
    c.add_argument("action", nargs="?", default="check")
    c.add_argument("file", nargs="?", default=None)  # filename for add-loop
    c.add_argument("path", nargs="?", default=".")

    # cost
    co = sub.add_parser("cost", help="Estimate token cost")
    co.add_argument("--pattern", required=True)

    args = parser.parse_args()

    if args.cmd == "doctor":
        return cmd_doctor(args.path)
    elif args.cmd == "status":
        return cmd_status(args.path)
    elif args.cmd == "audit":
        return cmd_audit(args.path, args.json, args.suggest)
    elif args.cmd == "gate":
        return cmd_gate(args.action, args.path)
    elif args.cmd == "sync":
        return cmd_sync(args.action, args.path, args.file)
    elif args.cmd == "cost":
        return cmd_cost(args.pattern)
    return 0


if __name__ == "__main__":
    sys.exit(main())
