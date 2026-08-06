# CLAUDE.md — Claude Code Global Instructions

> This file is loaded by Claude Code at startup and provides persistent,
> project-wide context for all conversations.

## Project Identity

**Name**: pyharmonics-gpt
**Type**: Harmonic pattern trading signal SaaS API
**Stack**: Python 3.11, Flask, Supabase, Redis, RQ, Gunicorn

## Memory System

This project uses a **four-tier memory system** for AI agents. See `.claude/MEMORY.md` for full policy.

**At the start of each session**, read:
1. `docs/loop-state/LOOP.md` — current loop definitions and cadence
2. `docs/loop-state/STATE.md` — what's active, what's paused, what's on watch
3. `.claude/MEMORY-STATE.md` — what the previous agent remembered

**After each significant action**, update:
- `.claude/MEMORY-STATE.md` with decisions made and context needed for next session

## Loop Engineering Framework

This project is governed by **loop-engineering** principles. Read `docs/loop-engineering-plan.md` for the full plan.

Key concepts:
- **L1 loops**: Report only, humans decide
- **L2 loops**: Suggest only, humans decide
- **L3 loops**: Act autonomously within constraints
- **Loop Readiness Score**: 0-100 score measuring loop maturity (L0-L3)

**CLI tools** (`python -m loop.loop`):
```bash
python -m loop.loop doctor .     # Check core files
python -m loop.loop status .    # Show state summary
python -m loop.loop audit . --suggest  # Compute readiness score
python -m loop.loop gate check . # Check gate.yaml
python -m loop.loop sync check .  # Check LOOP/STATE consistency
```

## Skills System

- **Agent skills** (from `mattpocock/skills`): Use `skills-lock.json` to understand what's available
- **Project skills** (loop-specific): See `skills/` directory
- **Loop skills**: See `.claude/skills/` directory

## Key Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | AI agent behavior规范 |
| `docs/loop-state/LOOP.md` | Loop definitions |
| `docs/loop-state/STATE.md` | Current loop state |
| `docs/loop-state/gate.yaml` | Path denylist + auto-merge rules |
| `app/loop/` | Trading signal CMA-ES search loop |
| `app/loop/maker_checker/` | LLM-based maker-checker verifier |
| `app/config/tuning.py` | TuningConstants — the master parameter set |
| `app/domain/signals.py` | Core signal domain logic |

## Critical Safety Notes

1. **TUNING promotion**: Never directly call `apply_tuning()` to modify the live `TUNING` singleton used by gunicorn workers. Promotion requires a PR that edits `app/config/tuning.py`.

2. **Backtest vs live**: All tuning changes go through backtesting first. Never assume a backtest result predicts live performance.

3. **Loop Readiness Score gates**: When score < 58, manual review is required for all loop-generated changes.

## Development Standards

See `AGENTS.md` for the full set of coding standards, including:
- 8 implementation rules
- 100% test coverage for new code
- KISS / high cohesion / low coupling principles
- North Star metrics (API latency < 2s p95, accuracy > 80%, cache hit > 70%)

## Project Plans

All active plans are indexed in `PLANS.md`. Check it before starting significant work.
