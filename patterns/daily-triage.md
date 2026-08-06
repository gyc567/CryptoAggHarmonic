# Pattern: Daily Triage

## Problem
Daily manual review of issues, PRs, and test reports is time-consuming and easy to skip.

## Solution
A scheduled GitHub Action runs daily triage, classifying issues and PRs and posting suggestions.

## Cadence
Workdays at 09:00 UTC (via `.github/workflows/daily-triage.yml`)

## Skills Required
- `skills/loop-triage/SKILL.md`

## State Shape
```yaml
# docs/loop-state/STATE.md
High Priority:
  - issue #N: description
Watch List:
  - topic: description
Recent Noise:
  - ignored reason
```

## Verification
- Run `python -m loop.loop status .`
- Check GitHub for triage comments posted

## Tool-Specific Notes

### Claude Code
```
Read .claude/MEMORY-STATE.md
Run gh issue list --label needs-triage
Classify each issue
Post comments
Update STATE.md
```

### Grok
Same flow, adjust for Grok's tool syntax.
