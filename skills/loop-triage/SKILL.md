# SKILL.md — loop-triage

## Trigger Condition

Invoked by `daily-triage.yml` GitHub Action (daily at 09:00 UTC).
Can also be triggered manually.

## Input

- GitHub Issues via `gh` CLI (needs-triage, needs-info labels)
- Open Pull Requests (draft, review requested)
- `docs/agents/triage-labels.md` — triage label definitions
- `docs/agents/issue-tracker.md` — issue tracker conventions

## Output

1. Updates `docs/loop-state/STATE.md` with High Priority / Watch List / Recent Noise
2. Posts GitHub comments on issues (suggesting labels, requesting info)
3. Does NOT apply labels or close issues — only suggests

## Rules

1. **L1 — Report only**. Do not take action, only report recommendations.
2. Use five-state triage: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
3. Classify each issue with a reason: why does it need the suggested label?
4. Flag issues older than 7 days with no response as "stale".
5. Log all triage decisions to `docs/loop-state/STATE.md`.

## Example Triage Output

```
### Issue: #123 - Pattern detection failing on BTC
- Suggested labels: `bug`, `needs-info`
- Reason: "bug label because reporter shows error output; needs-info because missing timeframe"
- Priority: medium
- Stale: false
```
