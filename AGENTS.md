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
- [ADR-001: Decision (placeholder)](docs/adr/0001-adr-placeholder.md)

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

### Implementation rules

1. **不保留向后兼容** — 过时的直接删，别加兼容层、别写migration、别留fallback。
2. **选能满足当前需求的最简单实现** — 不要预防性抽象，不要多此一举的配置层。
3. **系统分层长** — 先跑通一个最小的端到端版本，再往上加东西。绝不为了未完成的复杂度拆掉能跑的东西。
4. **组件保持模块化** — 关注点分离。
5. **优先用成熟的、有人维护的库** — 没有明确理由别自己重写。
6. **先翻项目里已有的依赖能做什么** — 再考虑加新包或自己写。别上来就假设库里没有。
7. **架构决策往长了做** — 不接受"先这样以后再换"的临时方案。
8. **先看成熟产品怎么解决同一个问题** — 用已验证的模式，别从零发明。

### Testing workflow

Before any feature work:
- Write tests first (TDD) or alongside implementation
- Run existing tests to establish baseline
- After changes: run full test suite

After any feature work:
- Verify all tests pass (`pytest` or `npm test`)
- Generate coverage report
- Document test results in PR or plan doc

---

## Loop engineering

This project uses loop-engineering principles. See `docs/loop-engineering-plan.md` for the full plan.

### Core files

| File | Purpose |
|------|---------|
| `docs/loop-state/LOOP.md` | 7 loop definitions (cadence, skill, gate) |
| `docs/loop-state/STATE.md` | Current operational state (auto-updated) |
| `docs/loop-state/gate.yaml` | Path denylist + auto-merge rules |
| `loop/` | Python CLI tools (`loop.py`, `loop_gate.py`, etc.) |

### Loop CLI

```bash
python -m loop.loop doctor .     # Check core files exist
python -m loop.loop status .    # Show state summary
python -m loop.loop audit . --suggest  # Compute readiness score
python -m loop.loop gate check . # Check gate.yaml violations
python -m loop.loop sync check . # Check LOOP/STATE consistency
```

### Loop maturity levels

- **L1**: Report only — loop generates reports, humans decide
- **L2**: Assist — loop suggests, humans decide
- **L3**: Autonomous — loop acts within hard constraints

### Key constraints

1. **TUNING promotion**: Never call `apply_tuning()` to modify the live gunicorn worker's TUNING. Promotion requires a PR editing `app/config/tuning.py` + SIGHUP restart.
2. **No auto-merge without gate**: Check `gate.yaml` before any automated PR.
3. **Memory hygiene**: Follow the four-tier memory policy in `docs/loop-state/MEMORY.md`.

### Skills

- **Agent skills** (mattpocock): Use `skills-lock.json`
- **Project skills**: Use `skills/` directory (loop-triage, loop-handoff, etc.)
- **Loop skills**: Use `.claude/skills/` directory

---

## Ponytail — Lazy Senior Dev Mode

> Sourced from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT license).
> Installed as skills: `.claude/skills/ponytail/`, `/ponytail-review`, `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`, `/ponytail-help`.

Before writing any code, stop at the first rung that holds:

1. **Does this need to exist at all?** Speculative need = skip it, say so in one line. (YAGNI)
2. **Already in this codebase?** A helper, util, type, or pattern that already lives here → reuse it. Look before you write.
3. **Stdlib does it?** Use it.
4. **Native platform feature covers it?** `<input type="date">` over a picker lib, CSS over JS, DB constraint over app code.
5. **Already-installed dependency solves it?** Use it. Never add a new one for what a few lines can do.
6. **Can it be one line?** One line.
7. **Only then:** the minimum code that works.

**Bug fix = root cause, not symptom.** Grep every caller of the function you're about to touch. One guard in the shared function is a smaller diff than a guard in every caller.

### Rules

- No unrequested abstractions: no interface with one implementation, no factory for one product.
- No boilerplate, no scaffolding "for later".
- Deletion over addition. Boring over clever.
- Shortest working diff wins — but only once you understand the problem.
- Mark deliberate simplifications with a `ponytail:` comment naming the ceiling and upgrade path.
- Non-trivial logic leaves ONE runnable check behind (an assert-based demo or one small test file).

### Commands

| Command | Description |
|---------|-------------|
| `/ponytail [lite\|full\|ultra]` | Set intensity (default: full) |
| `/ponytail-review` | Review current diff for over-engineering |
| `/ponytail-audit` | Whole-repo audit for bloat |
| `/ponytail-debt` | Harvest `ponytail:` comments into debt ledger |
| `/ponytail-gain` | Show benchmark scoreboard |
| `/ponytail-help` | Quick reference |

### When NOT to be lazy

Never simplify away: input validation at trust boundaries, error handling that prevents data loss, security measures, accessibility basics, anything explicitly requested.