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