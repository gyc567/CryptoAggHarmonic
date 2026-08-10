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
### 2026-08-09T22:14:00Z [ci-sweeper] loop=1 candidates=0 cost=0.00 outcome=error scope=vercel-deploy dpl=pyharmonics-n687p3cw5 build_failed=eslint errors=9 blocks=T1
### 2026-08-09T22:14:30Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success commit=vercel-t1-recovery files=9 ready_for=vercel-prod
### 2026-08-09T22:15:00Z [gen-049] loop=1 candidates=1 cost=0.00 outcome=success vercel=vercel-prod alias=www.cryptoagg.xyz
### 2026-08-09T22:35:00Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success ssoProtection=disabled vercel_get=/ status=200 health=/api/health=200 leak_check=0
### 2026-08-09T22:36:00Z [dependency-sweeper] loop=1 candidates=0 cost=0.00 outcome=success deleted_project=prj_T0D6PXcUQ6HLlA1jSQjkWM5xWdII reason=accidental-via-cd-frontend
### 2026-08-09T22:50:00Z [issue-triage] loop=1 candidates=1 cost=0.00 outcome=escalated scope=auth-magic-link-redirect bug=email-uses-localhost site_url=piomgijwxpbsvnigtbmt fix_owner=human required=supabase-dashboard-auth-url-config
### 2026-08-09T22:51:00Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success code_review=use-auth.ts signInWithOtp_passes_emailRedirectTo=correct verdict=not-a-code-bug
### 2026-08-09T22:55:00Z [pr-babysitter] loop=1 candidates=4 cost=0.00 outcome=error probe=admin-generate_link results=requested-www-cryptoagg-xyz-but-redirect_to-still-localhost-3000 conclusion=supabase-dashboard-change-did-not-take-effect fix_owner=human
```

| Value | Meaning |
| `errors=N` | N candidates errored |
| `paused` | Loop paused due to budget or gate |
| `escalated` | Required human intervention |
