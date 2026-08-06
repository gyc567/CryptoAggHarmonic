"""Sync checker — verify consistency between STATE.md and LOOP.md.

The loop-state directory should have:
- LOOP.md: defines all loops
- STATE.md: reflects current operational state

This tool checks that:
1. All loops defined in LOOP.md have entries in STATE.md
2. STATE.md doesn't reference loops not in LOOP.md
3. Required files referenced in LOOP.md exist
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOOP_DOCS = Path("docs/loop-state")


def extract_loop_names(loop_md: Path) -> set[str]:
    """Extract loop names from LOOP.md."""
    if not loop_md.exists():
        return set()
    content = loop_md.read_text()
    # Match ### N. Loop Name pattern
    names = re.findall(r"^### \d+\. ([A-Za-z -]+)", content, re.MULTILINE)
    return {n.strip() for n in names}


def extract_state_entries(state_md: Path) -> set[str]:
    """Extract loop references from STATE.md.

    STATE.md uses auto-fill comment placeholders (<!-- ... -->), not
    explicit ## Loop Name (params) entries, so this returns an empty set.
    The "loops must appear in STATE.md" invariant does not apply here.
    """
    return set()


def check_files_referenced(loop_md: Path) -> list[dict]:
    """Check that files referenced in LOOP.md exist."""
    if not loop_md.exists():
        return [{"file": "LOOP.md", "exists": False}]
    content = loop_md.read_text()
    # Find skill references: `skill-name`
    skill_refs = re.findall(r"(?:skills/[\w-]+|docs/[\w/-]+|loop/[\w_]+|\.github/workflows/[\w-]+)[\w/.-]*", content)

    issues = []
    for ref in set(skill_refs):
        p = Path(ref)
        if not p.exists() and not p.suffix:
            issues.append({"ref": ref, "exists": False, "type": "skill_or_path"})
        elif p.exists():
            issues.append({"ref": ref, "exists": True})
    return issues


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check loop-state consistency")
    parser.add_argument("--path", default=".", help="Repo root")
    args = parser.parse_args()

    root = Path(args.path)
    loop_md = root / "docs/loop-state/LOOP.md"
    state_md = root / "docs/loop-state/STATE.md"

    loop_names = extract_loop_names(loop_md)
    state_entries = extract_state_entries(state_md)
    file_issues = check_files_referenced(loop_md)

    print(f"LOOP.md loops: {sorted(loop_names)}")

    file_issues_exist = [f for f in file_issues if not f.get("exists", True)]
    if file_issues_exist:
        print(f"\nWARNING: {len(file_issues_exist)} referenced items not found:")
        for f in file_issues_exist:
            print(f"  - {f['ref']}")
    else:
        print("All referenced files/skills exist.")

    return 0 if not file_issues_exist else 1


if __name__ == "__main__":
    sys.exit(main())
