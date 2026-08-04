# AGENTS.md

Repo-local instructions for AI coding agents (jcode, GitHub Copilot, Cursor,
Aider, Claude Code, etc.). Edit this file when a behaviour applies to **every**
agent touching this repo, not just one tool.

## Agent skills

This repo uses the mattpocock/skills engineering skills. They read these
configuration files before doing anything:

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five-state triage: `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. Read `CONTEXT.md` at the repo root and `docs/adr/` before
exploring. See `docs/agents/domain.md`.

---

## Project plans

All work-in-progress plans live in `plans/` directory with an index in `PLANS.md`.

### Plan lifecycle

1. **Create**: Write plan in `plans/xxx.md` before starting work
2. **Index**: Add entry to `PLANS.md`
3. **Execute**: Follow the plan
4. **Complete**: Delete `plans/xxx.md` and remove from `PLANS.md`
5. **Archive**: Git history preserves the plan permanently

### Plan template

```markdown
# Plan: [What we're building]

## Context
Why this is needed.

## Goals
- [ ] Goal 1
- [ ] Goal 2

## Tasks
- [ ] Task 1
- [ ] Task 2

## Verification
How to confirm success.
```

---

## Documentation

All documentation lives in `docs/` directory with an index in `DOCS.md`.

### Doc rules

- Docs are **permanent** (never delete after creation)
- Use multi-level indexes to prevent file bloat
- Cross-link related docs from `DOCS.md`

### Doc index structure

```markdown
# Documentation Index

## Architecture
- [ADR-001: Decision](docs/adr/adr-001.md)

## Guides
- [Setup](docs/guides/setup.md)

## References
- [API](docs/reference/api.md)
```

---

## Optimization disciplines

For areas with clear feedback loops, agents **must** follow discipline-specific guidelines.

### Frontend optimization
- Verify changes visually in browser
- Test on actual browser, not just code review
- See `PLANS.md` → Frontend Optimization Guide

### Backtest evaluation
- Use quantitative metrics (win rate, Sharpe, drawdown)
- Validate against historical data
- See `PLANS.md` → Backtest Evaluation Guide

### Performance tuning
- Measure before/after with benchmarks
- Set explicit latency targets
- See `PLANS.md` → Performance Tuning Guide

---

## North Star metrics

All AI work should advance these metrics. When making decisions, prefer changes that improve these scores.

### Primary metrics

| Metric | Target | Why |
|--------|--------|-----|
| API latency | < 2s p95 | User experience |
| Analysis accuracy | > 80% pattern recognition | Core value |
| Cache hit rate | > 70% | Cost efficiency |

### Decision framework

When uncertain, ask:
1. Does this improve a North Star metric?
2. Does this maintain current metrics while adding value?
3. If neither, should this be a separate task?

### Metric tracking

Log metric changes in plan docs and PR descriptions. Improvements should be **quantified**, not just described.

---

## Code quality standards

All AI-generated code must adhere to these principles:

### Design principles

1. **KISS (Keep It Simple, Stupid)** — Prefer the simplest solution that works. Avoid over-engineering.
2. **High cohesion, low coupling** — Group related code together; minimize dependencies between modules. Use clean design patterns (not excessive patterns).
3. **100% test coverage for new code** — All new functionality must include tests. No new code without tests.
4. **Non-regression** — Changes must not break unrelated existing functionality.
5. **Preserve test suite** — Keep all test cases. Include test reports in documentation.

### Testing workflow

Before any feature work:
- Write tests first (TDD) or alongside implementation
- Run existing tests to establish baseline
- After changes: run full test suite

After any feature work:
- Verify all tests pass (`pytest` or `npm test`)
- Generate coverage report
- Document test results in PR or plan doc