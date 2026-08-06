"""Git worktree isolation for loop experiments.

Provides isolated git worktrees per fix attempt.
Each worktree is discarded after the verifier REJECTs or the experiment escalates.

Usage:
    python -m loop.loop_worktree create my-fix
    python -m loop.loop_worktree list
    python -m loop.loop_worktree discard my-fix
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("loop.worktree")

WORKTREE_ROOT = Path(".scratch/loop_worktrees")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a git command, logging it."""
    logger.info("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, **kwargs)


def create(name: str, base_branch: str = "main") -> Path:
    """Create an isolated worktree for a fix attempt.

    Args:
        name: Identifier for this worktree
        base_branch: Branch to base the worktree on

    Returns:
        Path to the worktree directory
    """
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    worktree_path = WORKTREE_ROOT / name

    # Check if worktree already exists
    result = _run(
        ["git", "worktree", "list", "--json"],
        capture_output=True, text=True,
    )
    if worktree_path.exists() or result.returncode == 0:
        for line in result.stdout.splitlines():
            if name in line:
                raise ValueError(f"Worktree '{name}' already exists at {worktree_path}")

    # Create the worktree
    result = _run([
        "git", "worktree", "add",
        str(worktree_path),
        "-b", f"fix/{name}",
        base_branch,
    ], cwd=Path.cwd())

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create worktree: {result.stderr}")

    # Initialize the worktree with a clean state
    logger.info("Created worktree at %s", worktree_path)
    return worktree_path


def list_worktrees() -> list[dict]:
    """List all loop worktrees."""
    result = _run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True,
    )
    worktrees = []
    current: dict = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
    if current:
        worktrees.append(current)

    # Filter to only our loop worktrees
    return [
        wt for wt in worktrees
        if "fix/" in wt.get("branch", "")
    ]


def discard(name: str) -> None:
    """Discard a worktree and remove the branch.

    Args:
        name: Identifier of the worktree to discard
    """
    worktree_path = WORKTREE_ROOT / name

    if not worktree_path.exists():
        logger.warning("Worktree '%s' does not exist at %s", name, worktree_path)
        return

    branch = f"fix/{name}"

    # Remove the worktree
    result = _run([
        "git", "worktree", "remove",
        str(worktree_path),
        "--force",
    ])
    if result.returncode != 0:
        logger.error("Failed to remove worktree: %s", result.stderr)
        return

    # Remove the branch
    _run(["git", "branch", "-d", branch], capture_output=True)
    logger.info("Discarded worktree '%s'", name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Git worktree isolation for loops")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create_p = sub.add_parser("create", help="Create a worktree")
    create_p.add_argument("name", help="Worktree name")
    create_p.add_argument("--base", default="main", help="Base branch")

    list_p = sub.add_parser("list", help="List worktrees")

    discard_p = sub.add_parser("discard", help="Discard a worktree")
    discard_p.add_argument("name", help="Worktree name")

    args = parser.parse_args()

    if args.cmd == "create":
        try:
            path = create(args.name, args.base)
            print(f"Created: {path}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    elif args.cmd == "list":
        worktrees = list_worktrees()
        if not worktrees:
            print("No loop worktrees found.")
        for wt in worktrees:
            print(f"  {wt.get('path', '?')} — {wt.get('branch', '?')}")
    elif args.cmd == "discard":
        discard(args.name)
        print(f"Discarded: {args.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
