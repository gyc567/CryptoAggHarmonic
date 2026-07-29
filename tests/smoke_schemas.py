"""Smoke check for Pydantic schema files.

Why this exists
---------------
black has a known interaction with multi-line
``Annotated[Optional[X], Field(...)]`` annotations in Pydantic schemas: its
line-splitter occasionally pushes a closing parenthesis outside the
``Annotated[...]`` brackets, producing code that **looks fine** but blows up
at import time with ``TypeError`` or ``SyntaxError``.

We removed every occurrence of that bug in commit ``960877d`` and pinned
black in ``9330e27``. This script is the cheap belt-and-braces check: it
ensures the three schema modules that matter most still parse and import
after every black run.

Run from repo root::

    python tests/smoke_schemas.py

Exit code is 0 when all checks pass, 1 otherwise — safe to wire into CI
right after ``black --check app/ tests/``.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

# These three modules are the highest-risk ones for the
# ``Annotated[..., Field(...)]`` mangling bug. Adding more here is fine,
# but each extra module pulls in extra runtime deps, so prefer keeping
# this list tight.
TARGETS: tuple[str, ...] = (
    "app.domain.schemas",
    "app.domain.vibe_schemas",
    "app.domain.rsi_trend",
)


def _file_for(module_name: str) -> Path:
    return Path(module_name.replace(".", "/") + ".py")


def _ast_parse_ok(module_name: str) -> None:
    """Raise SyntaxError if the source is unparseable."""
    path = _file_for(module_name)
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_ok(module_name: str) -> None:
    importlib.import_module(module_name)


def main() -> int:
    failures: list[tuple[str, str, str]] = []  # (module, stage, message)

    for name in TARGETS:
        for stage, fn in (("ast.parse", _ast_parse_ok), ("import", _import_ok)):
            try:
                fn(name)
            except SyntaxError as exc:
                failures.append((name, stage, f"SyntaxError: {exc}"))
            except Exception as exc:  # noqa: BLE001 — we want all errors
                failures.append((name, stage, f"{type(exc).__name__}: {exc}"))

    for name, stage, msg in failures:
        print(f"FAIL [{name}] {stage}: {msg}", file=sys.stderr)

    if failures:
        print(
            f"\n{len(failures)} smoke check(s) failed out of "
            f"{len(TARGETS) * 2} checks across {len(TARGETS)} modules.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(TARGETS)} schema modules AST-parsed and imported cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
