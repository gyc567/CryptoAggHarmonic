# Loop Run Log — pyharmonics-gpt

> Append-only log of all loop executions.
> Format: logfmt

## Log Format

```
### {timestamp} [{loop_name}] loop={N} candidates={N} cost={USD} outcome={result} [{extra_kv}]
```

## Examples

```
### 2026-08-05T09:00:00Z [daily-triage] loop=1 candidates=0 cost=0.00 outcome=success
### 2026-08-05T14:32:00Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success
### 2026-08-05T15:00:00Z [gen-047] loop=1 candidates=10 cost=0.12 outcome=success accepted=3 rejected=6 errors=1
### 2026-08-09T13:30:00Z [code-health-audit] loop=1 candidates=26 cost=0.00 outcome=success scope=loop-engineering-v3-followups merged=24-tests metrics=14/14 readiness=100
### 2026-08-09T13:45:00Z [gen-048] loop=1 candidates=20 cost=0.00 outcome=success accepted=20 rejected=0 errors=0 dry_run=0 cluster=C1-Geometry
### 2026-08-09T13:50:00Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success commit=v3-followups files=12 tests=24 status=green
```

## Outcomes

| Value | Meaning |
|-------|---------|
| `success` | Loop completed without errors |
| `accepted=N` | N candidates accepted (gen loop) |
| `rejected=N` | N candidates rejected |
| `errors=N` | N candidates errored |
| `paused` | Loop paused due to budget or gate |
| `escalated` | Required human intervention |
