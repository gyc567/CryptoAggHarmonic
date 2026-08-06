# SKILL.md — loop-memory

## Trigger Condition

- Weekly as part of the memory hygiene loop
- Called by `loop-context` when promoting episodic notes

## Input

Reads:
- `.claude/MEMORY-STATE.md` — current memory state
- `docs/loop-state/memory-budget.md` — tier limits
- `docs/loop-state/memory-constraints.md` — prohibited content
- `docs/loop-state/MEMORY.md` — strategy definition

## Output

Writes:
- `.claude/MEMORY-STATE.md` — cleaned/promoted memory
- `docs/loop-state/durable-facts.md` — promoted durable facts (append-only)

## Hygiene Checklist

1. Count entries per tier. Alert if > 80% of tier limit.
2. Delete Episodic entries older than 14 days.
3. Check for violations of `memory-constraints.md` (secrets, raw LLM outputs).
4. Promote eligible Episodic entries to Durable Facts (human-verified).
5. Verify Durable Facts consistency with current code (run `git log` check).
6. Log hygiene run to `.claude/MEMORY-STATE.md` hygiene log.

## Durable Facts Rules

1. **Append only**. Never delete a Durable Fact. Mark superseded with `superseded_by`.
2. **Human gate or verifier**. Promotion requires human review or `loop-verifier`.
3. **Source traced**. Every Durable Fact should cite the `git commit` or decision it came from.

## Verification

```bash
python -m loop.loop audit . --suggest | grep -i memory
```
