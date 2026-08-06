# SKILL.md — loop-handoff

## Trigger Condition

Automatically invoked at the END of each working session (before Claude Code exits).
Also invoked when an agent needs to hand off to a human or another agent.

## Input

- Current conversation context (what was worked on)
- `.claude/MEMORY-STATE.md` — current memory state
- `docs/loop-state/LOOP.md` — active loop definitions
- Open issues and PRs

## Output

Writes to `.claude/MEMORY-STATE.md`:
- What was accomplished this session
- Open questions and decisions made
- Relevant state for the next session (Pareto position, current generation, etc.)
- Any pending actions for the human to take

## Handoff Content

```
## Session Handoff — {timestamp}

### Accomplished
- ...

### Decisions
- ...

### Open Questions
- ...

### Pending Actions
- [ ] ...

### State for Next Session
- Pareto front: {N} points
- Last generation: {gen_id}
- Current strategy_version: {sha}
```
