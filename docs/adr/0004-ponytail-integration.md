# ADR-0004: Ponytail × Loop Engineering Integration

**Date**: 2026-08-06
**Status**: Accepted
**Deciders**: pyharmonics-gpt team

## Context

Ponytail (DietrichGebert/ponytail) was installed to enforce a "lazy senior dev" decision ladder across the codebase. We need to integrate it with the existing loop-engineering framework without creating architectural conflicts.

## Decisions

### D1: Ponytail Constraint Scope

Ponytail YAGNI rules apply to **business logic and infrastructure only**:

- ✅ `app/services/`、`app/api/`、`loop/`（CLI tools）、`skills/`、`patterns/`
- ❌ `app/loop/` — CMA-ES signal search (scientific experiment, not business logic)
- ❌ `bench/` — Backtest harness (experiment code)
- ❌ `tests/` — AGENTS.md 100% coverage requirement takes precedence over ponytail ultra deletion suggestions

**Rationale**: CMA-ES search needs diverse parameter candidates, not minimum code. YAGNI on experiments would eliminate useful variation. The `app/loop/` code is domain-specific scientific code, not product code.

### D2: Ponytail Is a Cross-Cutting Quality Layer, Not a Loop

Ponytail does **not** enter the L1-L3 loop maturity model. It overlays all loops as an output quality constraint:

- Not registered in `patterns/registry.yaml` (ponytail skills live in `.claude/skills/`, not `skills/`)
- Loops invoke ponytail logic via `gh script` + Python scripts, not via slash commands
- L1/L2 loop text outputs (Issue comments, PR comments) must follow ponytail's "shortest statement" principle

**Rationale**: `skills/` is for file-based skills that CI can invoke. `.claude/skills/` is for slash commands that humans invoke. ponytail skills are human-facing slash commands, not CI-automatable file skills.

### D3: Code Volume Trend Tracked Instead of `ponytail:` Comment Debt

Debt Harvesting tracks **code volume trend** (objective, measurable) instead of `ponytail:` comments (depends on developer habits, not enforceable by loop).

- Weekly `cloc` or `wc -l` by module
- Append to `docs/loop-state/durable-facts.md` Code Volume Trend table
- Alert threshold: 4 consecutive weeks of net line growth → triggers code-health issue

**Rationale**: `ponytail:` comments require developer discipline that cannot be enforced by a loop. Code volume is an objective proxy for code bloat that can be measured without developer cooperation.

### D4: Code Health Audit — Incremental Diff + Human-Confirmed Findings

Code Health Audit runs **incremental diff scan** (not full repo), and all findings include a `⚠️ requires human confirmation` prefix.

- Scan only files changed since last audit commit (not full repo)
- Scope: `app/services/`、`app/api/`、`loop/`、`skills/`、`patterns/` (same as constraint scope)
- Exclude: `app/loop/`、`bench/`、`tests/`
- Every finding prefixed with `⚠️` because ponytail-audit has produced false positives (e.g., misidentified ADR-0003's `skills_version.py → strategy_version.py` rename as "duplicate file")

**Rationale**: Full repo scan costs ~136K tokens/week. Incremental diff is 10-50× cheaper. The `⚠️` prefix is required because ponytail-audit is an LLM-powered heuristic, not a mechanical rule — it can be wrong and must not drive automatic action.

## Consequences

- New GitHub Actions workflows: `code-health-audit.yml` (weekly), `debt-harvesting.yml` (monthly)
- `docs/loop-state/durable-facts.md` gains a Code Volume Trend table
- `pr-babysitter.yml` gains one line: a one-sentence bloat warning (not a checklist — checklist would itself be over-engineering)
- `patterns/registry.yaml` is **not** modified for ponytail skills (skill path mismatch)
- No `ponytail:` comment enforcement (unreliable and unhygienic)

## Alternatives Considered

- **Enforce `ponytail:` comments via pre-commit hook**: Rejected. Comments are developer habits, not enforceable. A lint rule that fails on missing comments would generate noise, not quality.
- **Full repo ponytail-audit in CI**: Rejected. ~136K tokens per run is too expensive for weekly cadence. Incremental diff is sufficient.
- **Automatic PR creation from audit findings**: Rejected. Audit has false positives. Human must confirm before any code change.
- **ponytail skills in `skills/` directory**: Rejected. Those skills are slash-command-style (`.claude/skills/`), not CI-invocable (`skills/`). Registry would reference non-existent paths.

## References

- [ponytail](https://github.com/DietrichGebert/ponytail)
- `docs/ponytail-integration-plan.md`
- `AGENTS.md` Ponytail section
- `docs/loop-engineering-plan.md`
