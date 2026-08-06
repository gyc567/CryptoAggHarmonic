# SKILL.md — loop-context

## Trigger Condition

- Automatically at the START of each Claude Code session (via CLAUDE.md)
- Also runs weekly as part of the memory hygiene loop

## Input

Reads:
- `.claude/MEMORY-STATE.md` — current memory state
- `docs/loop-state/MEMORY.md` — memory strategy
- `docs/loop-state/memory-budget.md` — budget limits
- `docs/loop-state/LOOP.md` — current loop definitions
- `docs/loop-state/STATE.md` — active state

## Output

Writes:
- `.claude/MEMORY-STATE.md` — updated with session context

## Session Start Protocol

1. Load `.claude/MEMORY-STATE.md` scratch section
2. Load any episodic notes relevant to current task
3. Check if any Durable Facts are relevant to current work
4. Pre-populate conversation context with relevant memories

## Rules

1. **Scratch is cheap to write**. Don't overthink it — write notes freely.
2. **Episodic promote at session end**. Notes that should persist go to Episodic.
3. **Durable Facts never auto-promote**. Require human gate or `loop-verifier` skill.
4. **Token budget first**. Check `memory-budget.md` before adding entries.
5. **Never write secrets** (api keys, passwords, raw LLM outputs) to any tier.

## Promotion

Scratch → Episodic:
- Trigger: Session end or when a significant decision is made
- Verify: Check token budget in `memory-budget.md`

Episodic → Durable Facts:
- Trigger: Weekly hygiene loop
- Verify: `loop-verifier` skill checks for consistency
