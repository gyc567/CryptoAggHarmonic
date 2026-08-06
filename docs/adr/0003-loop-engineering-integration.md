# ADR-0003: Loop Engineering Integration

**Date**: 2026-08-06
**Status**: Accepted
**Deciders**: pyharmonics-gpt team

## Context

pyharmonics-gpt has a mature trading signal loop (`app/loop/`) that runs CMA-ES
genetic search with Pareto optimization and LLM-based maker-checker verification.
We want to add a **development loop** (issue triage, CI automation, changelog
drafter, etc.) inspired by the loop-engineering framework, without rebuilding
the existing trading loop.

## Decisions

### D1: Naming Isolation

Rename `app/loop/skills_version.py` → `app/loop/strategy_version.py`.
Rename HISTORY.jsonl field `skills_version` → `strategy_version`.
Add read-compatibility for `skills_version` in existing records.

**Rationale**: Avoid collision with mattpocock/skills agent skills in `skills-lock.json`.

### D2: State File Location

Shared loop state (LOOP.md, STATE.md, gate.yaml) lives in `docs/loop-state/` (git-tracked).
Per-machine memory state lives in `.claude/` (gitignored).

**Rationale**: `.claude/` was already gitignored. Putting shared state in `docs/` ensures
CI and collaborators can access it.

### D3: Salt Persistence

Salt stored at `.scratch/loop_state/salt.json` (gitignored).
Persists across loop runs on same machine for reproducibility audits.
Rotated manually (security event only), not automatically.

**Rationale**: Salt enables reproducible isolation. Reusing per session is correct
for reproducibility; automatic rotation would break it.

### D4: Cost Guardrail Defaults

`weekly_budget_usd` defaults to `$25.00`.
`dollars_per_cpu_second` defaults to `0.0001`.

**Rationale**: $10 was too tight (实测 $0.40-2.00/gen × 14 gens/week). $25 allows
2x safety margin for typical usage.

### D5: CI Type Coverage

mypy + pyright extended to cover `app/loop/` and `app/loop/maker_checker/`.

**Rationale**: These were explicitly excluded from CI. They contain complex financial
logic that deserves type safety.

### D6: suspicious_to_human → Issue (Decoupled)

Write to `.scratch/loop_state/pending_issues/<uuid>.json`.
GitHub Actions (`issue-sync.yml`) syncs to GitHub Issues.
Single generation limited to 1 issue.

**Rationale**: `driver.py` runs on developer machines without guaranteed `gh` CLI
or network access. Decoupling via filesystem is more reliable.

### D7: POSIX-Only

Loop runs on macOS/Linux only. Windows users must use WSL.

**Rationale**: Project uses gunicorn + fcntl + multiprocessing throughout. Windows
support is not a current priority. No `portalocker` dep added.

### D8: TUNING Promotion Gate

`apply_tuning()` does NOT modify gunicorn workers' TUNING.
Promotion requires: tuning snapshot → PR editing `app/config/tuning.py` → SIGHUP restart.

**Rationale**: Gunicorn workers are forked processes. A mutation in the loop process
does not propagate to workers. Manual PR review is the correct safety gate.

### D9: `apply_tuning()` Race Condition Fix (Path A)

Replace module-level aliases (`ATR_WINDOW = TUNING.atr_window`) with getter functions.
Workers read TUNING at call time, not at import time.

**Rationale**: ProcessPoolExecutor fork + `apply_tuning()` mutation created a race
condition where child processes could read stale aliases. Path A (function accessors)
is the minimal, least-risky fix.

### D10: Salt Store Bug Fix

`rotate_salt()` now actually generates and writes a new salt (was returning the
existing one via `get_or_create_salt()`).

**Rationale**: The bug meant "rotation" was a no-op, defeating the security purpose.

## Consequences

- New directory `docs/loop-state/` created (git-tracked)
- New CLI `python -m loop.loop` created
- `app/loop/skills_version.py` renamed to `strategy_version.py`
- HISTORY.jsonl records gain `strategy_version` and `salt` fields
- `app/api/metrics_routes.py` added for `/metrics` endpoint
- `app/loop/maker_checker/salt_store.py` added

## Alternatives Considered

- **portalocker for Windows**: Rejected. Too much complexity for no immediate benefit.
- **SQLite for multi-machine state**: Deferred. Single-machine for now.
- **Direct `gh issue create` from driver**: Rejected. Too many environment dependencies.

## References

- [loop-engineering](https://github.com/cobusgreyling/loop-engineering)
- [memory-engineering](https://github.com/cobusgreyling/memory-engineering)
- `docs/loop-engineering-plan.md`
