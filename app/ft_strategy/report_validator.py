"""Report final-state validator (D-FT-20).

Pure function mirroring the Postgres DB CHECK constraint
``ft_strategy_reports_final_check``. Used both:
- Pre-write: in ``FtStrategyRepo.publish_report()`` before UPDATE
- Post-write: in tests to verify a manually-INSERTed final row that the SQLite
  CHECK trigger would also enforce

Schema check (per ADR-0012 D4 / supabase/migrations/...):
    authoring_state='draft' OR
    (authoring_state='final'
     AND reserved_finding IS NOT NULL
     AND reserved_finding NOT LIKE 'TODO:%'
     AND published_at IS NOT NULL)
"""

from __future__ import annotations

from dataclasses import dataclass

# Public schema keys — keep in sync with supabase/migrations/*ft-strategy-ui-7tables.sql
DRAFT: str = "draft"
FINAL: str = "final"
ALLOWED_AUTHORING_STATES: tuple[str, ...] = (DRAFT, FINAL)


@dataclass(frozen=True)
class ReportFinalCheck:
    ok: bool
    state: str
    errors: tuple[str, ...] = ()


def validate_report_final(
    *,
    authoring_state: str,
    reserved_finding: str | None,
    published_at: str | None,
) -> ReportFinalCheck:
    """D-FT-20: enforce the DB CHECK invariants on report rows.

    Returns a structured result; never raises for legitimate false returns.
    Only raises if input types are wrong (defense).
    """
    if not isinstance(authoring_state, str):
        return ReportFinalCheck(
            ok=False, state="", errors=("authoring_state must be str",)
        )

    if authoring_state not in ALLOWED_AUTHORING_STATES:
        return ReportFinalCheck(
            ok=False,
            state=authoring_state,
            errors=(f"authoring_state must be one of {ALLOWED_AUTHORING_STATES}; got {authoring_state!r}",),
        )

    if authoring_state == DRAFT:
        # Draft requires only that it's NOT in the final-locked invariants;
        # no further constraints (per D-FT-20: draft rows can have any reserved_finding).
        return ReportFinalCheck(ok=True, state=authoring_state)

    # === authoring_state == FINAL ===
    errors: list[str] = []

    if reserved_finding is None:
        errors.append("reserved_finding must be NOT NULL when authoring_state='final'")
    elif not isinstance(reserved_finding, str) or reserved_finding.strip() == "":
        errors.append("reserved_finding must be a non-empty string")
    elif reserved_finding.startswith("TODO:"):
        errors.append("reserved_finding must not start with 'TODO:'")

    if published_at is None:
        errors.append("published_at must be NOT NULL when authoring_state='final'")

    return ReportFinalCheck(
        ok=not errors,
        state=authoring_state,
        errors=tuple(errors),
    )


# ---- SQLite CHECK trigger for parity with Postgres ----
#
# SQLite does not support ``BEFORE INSERT OR UPDATE`` action lists; we install
# one trigger per action. Both fire the same WHEN expression mirroring the
# Postgres CHECK constraint in supabase/migrations/.../ft-strategy-ui-7tables.sql.

_SQLITE_TRIGGER_WHEN_AND_BODY = """
FOR EACH ROW
WHEN (
  NEW.authoring_state = 'final'
  AND (
    NEW.reserved_finding IS NULL
    OR NEW.reserved_finding = ''
    OR NEW.reserved_finding LIKE 'TODO:%'
    OR NEW.published_at IS NULL
  )
)
BEGIN
  SELECT RAISE(ABORT, 'ft_strategy_reports_final_check violated: final row requires reserved_finding (non-TODO) and published_at');
END;
"""

SQLITE_TRIGGER_SQL_INSERT = "CREATE TRIGGER IF NOT EXISTS ft_strategy_reports_final_insert\nBEFORE INSERT ON ft_strategy_reports\n" + _SQLITE_TRIGGER_WHEN_AND_BODY

SQLITE_TRIGGER_SQL_UPDATE = "CREATE TRIGGER IF NOT EXISTS ft_strategy_reports_final_update\nBEFORE UPDATE ON ft_strategy_reports\n" + _SQLITE_TRIGGER_WHEN_AND_BODY

# Legacy alias used by tests; points to the INSERT half. Both must be installed
# together for full parity.
SQLITE_TRIGGER_SQL = SQLITE_TRIGGER_SQL_INSERT


def install_sqlite_check_trigger(conn) -> None:
    """Install SQLite triggers equivalent to the Postgres CHECK constraint.

    Run after ``apply_sqlite_schema`` so the table exists. Idempotent
    (``IF NOT EXISTS`` guards in SQL).
    """
    conn.execute(SQLITE_TRIGGER_SQL_INSERT)
    conn.execute(SQLITE_TRIGGER_SQL_UPDATE)
    conn.commit()
