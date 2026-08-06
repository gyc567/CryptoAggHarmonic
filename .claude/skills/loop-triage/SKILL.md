# SKILL.md — loop-triage

## Trigger Condition

- GitHub Actions `daily-triage.yml` runs daily at 09:00 UTC
- Can also be run manually: `python -m loop.loop doctor .`

## Input

Reads:
- `docs/loop-state/LOOP.md` — loop definitions
- `docs/loop-state/STATE.md` — current state
- `docs/agents/triage-labels.md` — triage label definitions
- `docs/agents/issue-tracker.md` — issue tracker conventions

## Output

Writes:
- `docs/loop-state/STATE.md` — updated High Priority / Watch List / Recent Noise

May also post GitHub comments on issues/PRs (L1 — suggestions only, no action).

## Rules

1. **Only triage, don't act**. This skill generates recommendations, not commits.
2. Respect the five-state triage: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
3. Use the issue tracker (GitHub Issues via `gh`) as the authoritative source.
4. Always explain WHY a recommendation is made, not just what to do.
5. Never auto-close issues or apply labels without human approval.

## Verification

- Run `python -m loop.loop audit . --suggest` to verify loop readiness
- Check that STATE.md was updated correctly before posting any comments
