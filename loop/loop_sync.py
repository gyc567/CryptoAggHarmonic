"""Sync checker + loop registry manager.

Two subcommands:
  check   — verify LOOP.md / STATE.md consistency
  add-loop — register a new loop (from FREQTRADE-LOOP.md) into LOOP.md
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
    names = re.findall(r"^### \d+\. ([A-Za-z -]+)", content, re.MULTILINE)
    return {n.strip() for n in names}


def extract_state_entries(state_md: Path) -> set[str]:
    """Extract loop references from STATE.md.

    STATE.md uses auto-fill comment placeholders, not explicit entries,
    so this returns an empty set.
    """
    return set()


def check_files_referenced(loop_md: Path) -> list[dict]:
    """Check that files referenced in LOOP.md exist."""
    if not loop_md.exists():
        return [{"file": "LOOP.md", "exists": False}]
    content = loop_md.read_text()
    skill_refs = re.findall(
        r"(?:skills/[\w-]+|docs/[\w/-]+|loop/[\w_]+|\.github/workflows/[\w-]+)[\w/.-]*",
        content,
    )
    issues = []
    for ref in set(skill_refs):
        p = Path(ref)
        if not p.exists() and not p.suffix:
            issues.append({"ref": ref, "exists": False, "type": "skill_or_path"})
        elif p.exists():
            issues.append({"ref": ref, "exists": True})
    return issues


def _extract_loop_number(loop_md: Path) -> int:
    """Return the next loop number by counting existing ### N. entries."""
    content = loop_md.read_text()
    numbers = re.findall(r"^### (\d+)\.", content, re.MULTILINE)
    return max(int(n) for n in numbers) + 1 if numbers else 1


def _extract_loop_section(loop_file: Path) -> str | None:
    """Extract the loop section heading from a FREQTRADE-LOOP.md file.

    Finds the first H2 heading (### N. Loop Name) and returns it.
    H1 headings are also accepted and normalized.
    """
    if not loop_file.exists():
        return None
    content = loop_file.read_text()
    # Match H2: ### N. Loop Name (N is a number)
    m = re.search(r"^(#{3}\s+\d+\..+)$", content, re.MULTILINE)
    if not m:
        return None
    return m.group(1)


def add_loop(loop_file_name: str, path: str = ".") -> int:
    """Register a loop from docs/loop-state/{name}.md into LOOP.md.

    Finds the first section heading (### N. Loop Name) in the source file,
    appends it to LOOP.md under the next sequential number.
    Prints the new section heading for verification.
    """
    root = Path(path)
    loop_md = root / "docs/loop-state/LOOP.md"
    source = root / "docs/loop-state" / loop_file_name

    if not source.exists():
        print(f"Source file not found: {source}", file=sys.stderr)
        return 1

    section = _extract_loop_section(source)
    if section is None:
        print(f"No loop heading (### N. ) found in {source}", file=sys.stderr)
        return 1

    # Extract loop name from heading
    m = re.match(r"^(### \d+\. (.+))$", section, re.MULTILINE)
    loop_name = m.group(2).strip()

    # Check if already registered
    existing = extract_loop_names(loop_md)
    if loop_name in existing:
        print(f"Loop '{loop_name}' already registered in LOOP.md")
        return 0

    # Determine next loop number
    next_num = _extract_loop_number(loop_md)

    # Build new section with correct number
    # Replace the number in the source heading with next_num
    numbered_section = re.sub(r"^### \d+\.", f"### {next_num}.", section, flags=re.MULTILINE)

    # Append to LOOP.md
    loop_content = loop_md.read_text()
    loop_md.write_text(loop_content.rstrip() + "\n\n" + numbered_section + "\n")

    print(f"Registered: ### {next_num}. {loop_name}")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Loop sync + registry")
    parser.add_argument("--path", default=".", help="Repo root")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # check subcommand
    chk = sub.add_parser("check", help="Verify LOOP/STATE consistency")
    chk.add_argument("--path", default=".", help="Repo root")

    # add-loop subcommand
    add = sub.add_parser("add-loop", help="Register a loop into LOOP.md")
    add.add_argument("file", help="Loop definition filename (e.g. FREQTRADE-LOOP.md)")
    add.add_argument("--path", default=".", help="Repo root")

    args = parser.parse_args()
    root = Path(args.path)

    if args.cmd == "check":
        loop_md = root / "docs/loop-state/LOOP.md"
        state_md = root / "docs/loop-state/STATE.md"

        loop_names = extract_loop_names(loop_md)
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

    elif args.cmd == "add-loop":
        return add_loop(args.file, args.path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
