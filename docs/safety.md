# Safety — Loop Engineering

## Denylists

### Path Denylist
- `app/config/tuning.py` — Never auto-modify; tuning promotion requires PR + human review
- `AGENTS.md` — Core agent behavior spec; no auto-edit
- `.claude/MEMORY-STATE.md` — Session memory; manual edits only

### Action Denylist
- No `apply_tuning()` calls in auto-fix loops
- No direct `git push` from loop agents
- No external API key rotation without human approval

## Auto-Merge Policy

| Condition | Action |
|-----------|--------|
| Score < 58 | Block all loop-generated changes; require human PR |
| Score 58–79 | Suggest changes; human approves before merge |
| Score ≥ 80 | Auto-merge low-risk changes (docs, comments, tests) |
| Any high-risk path touched | Always require human review |

## MCP Scopes

This project uses the following MCP tools:
- **File operations** (Read, Write, Edit, Bash) — Standard workspace access
- **No external MCP servers** configured for this loop pattern

MCP usage is documented per-skill in `.grok/skills/*/SKILL.md`.

## Kill Switch

- Command: `loop-pause-all`
- Effect: Pauses all schedulers, notifies human
- Resume: Human manually re-enables via `/loop` or scheduler command

## Emergency Rollback

1. Identify the last healthy commit: `git log --oneline -10`
2. Hard reset to previous state: `git reset --hard <commit-hash>`
3. Notify team in Slack/notification channel
4. Document incident in `loop-run-log.md`
