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
### 2026-08-09T23:05:00Z [pr-babysitter] loop=1 candidates=7 cost=0.00 outcome=success probe=admin-generate_link results=action_link-redirect_to-https-www-cryptoagg-xyz-for-every-input conclusion=supabase-dashboard-fix-verified fix_closed=v3ver02
### 2026-08-09T23:20:00Z [issue-triage] loop=1 candidates=2 cost=0.00 outcome=escalated scope=api-auth-500-affected=/api/analyze-/api/history root_cause=app-api-auth-missing-imports file=app/api/auth.py missing=ErrorCode-verify_user_token-reserve_user_quota
### 2026-08-09T23:21:00Z [code-health-audit] loop=1 candidates=1 cost=0.00 outcome=success fix=add-three-imports tests_added=2 auth_tests=15-15 total_tests=1772-0 status=ready-for-backend-redeploy
### 2026-08-09T23:30:00Z [dependency-sweeper] loop=1 candidates=0 cost=0.00 outcome=success deploy_artifact=scripts/deploy-backend-auth-fix.sh plan=docs/plans/backend-auth-500-fix.md waiting_on=human-ssh-redeploy-of-hapi.cryptoagg.xyz
### 2026-08-10T08:42:00Z [issue-triage] loop=1 candidates=0 cost=0.00 outcome=escalated user_reported_500_persists_after_fix_pushed root_cause=fix-not-deployed-to-backend fix_status=code-in-main-deploy-pending status=human-action-required
### 2026-08-10T09:00:00Z [backend-redeploy] loop=1 candidates=0 cost=0.00 outcome=success tool=scripts/deploy-backend-auth-fix.sh env_deltas=4 non-git-dir origin-moved systemd-managed missing-pytest probes=no-auth-401 bearer-401 history-401 auth_tests=15-15 health=ok durable=v3auth01 closed=auth-500
### 2026-08-10T09:30:00Z [backend-redeploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-auth-401 root_cause=supabase-py-2.15.0-rejects-publishable-anon-key fix=upgrade-supabase-2.31.0 secondary=quota-fk-order+check-constraint-normalize+timing-attr probes=history-200 auth-passed quota-reserve-200 remaining=yahoo-rate-limit-503
### 2026-08-10T07:00:00Z [backtest-feedback-loop] loop=1 candidates=1 cost=0.00 outcome=success scope=backtest-feedback-loop fixes=6(date-slice+score-clamp+weights-wiring+liquidity-sweep+shebang+mp-summaries) tests=252-pass probes=31d-backtest-14s grid-search-real-data parallel-dryrun-3sym-4s remaining=none env_failures=futures-kline-datasource-tests-need-network
### 2026-08-10T13:40:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=hapi.cryptoagg.xyz-local-deployment finding=this-machine-is-backend-server old=systemd-pyharmonics-service-varlwwwpyharmonics new=local-repo-varlcodecryptoaggharmonic strategy=PYTHONPATH-override-using-old-venv-deps cert_status=lets-encrypt-valid-until-2026-11-07 caddy_config=already-present proxied_to=localhost:5001 health_check=api-health-200-version-0.2.0-markets-200-history-200 analyze-422-params-validation-no-500 auth500_closed=true supabase_health=degraded-dns-fail-on-this-vps-not-code-issue scripts=deploy-local-backend.sh+stop-old-backend.sh plan=docs/plans/local-backend-deployment.md
### 2026-08-10T14:00:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=git-push commit=1cbd45a files=7(+513/-3) added=docs/plans/local-backend-deployment.md+docs/test-report-hapi-domain-2026-08-10.md+scripts/deploy-local-backend.sh+scripts/stop-old-backend.sh modified=PLANS.md+docs/loop-state/STATE.md+docs/loop-state/loop-run-log.md branch=main pushed_to=origin/main remote_url=git@github.com:gyc567/CryptoAggHarmonic.git
### 2026-08-10T15:30:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=binance-451-geo-block-fix file=app/infra/marketdata.py(+20/-3) root_cause=binance.com-HTTP-451-in-us-vps fix=DirectBinanceCandleData-get_candles-451-fallback-to-Binance.US verified=BTCUSDT-analyze-200-success-ETHUSDT-analyze-200-success pushed=e43dda7
### 2026-08-11T15:35:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-restart-new-code script=scripts/deploy-local-backend.sh fix=remove-DISABLE_AUTH_from-prod-fix reason=RuntimeError-on-boot DISABLE_AUTH-blocked-in-production health=/api/health-200-supabase-ok-redis-ok-tvbridge-ok analyze_bearer=401-auth-required pushed=7afab39
### 2026-08-11T15:50:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=rsi-trend-429-fix-attempt-1 root_cause=wrong-hypothesis-HTTP-409-pg_advisory_lock (later corrected) file=app/infra/supabase_client.py(+27/-8) fix=extract-_reserve_quota_rpc-with-409-retry-attempt1 verified=backend-ok-health-supabase-ok pushed=7cad618 note=attempt-did-not-fix-issue-real-root-cause-found-in-entry-2026-08-11T17:05
### 2026-08-11T16:24:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-restart-new-code script=scripts/deploy-local-backend.sh health=api-health-200-supabase-ok-redis-ok-tvbridge-ok version=0.2.0
### 2026-08-11T17:05:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=rsi-trend-plan-429-fix root_cause=APIError-23503-FK-violation-analysis_id-not-in-analyses-table file=app/infra/supabase_client.py-app/api/rsi_trend_routes.py-migrations/20260811_001_nullable_analysis_id.sql-tests/test_supabase_client.py fix=drop-FK-usage_ledger-analysis_id-pass-null-analysis_id-retry-on-23xxx-40xxx verified=5/5-TestQuotaFunctions-passed-111-related-tests-passed pushed=f5c149c
### 2026-08-11T18:20:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-restart-new-code script=scripts/deploy-local-backend.sh health=api-health-200-supabase-ok-redis-ok-tvbridge-ok version=0.2.0
### 2026-08-12T00:25:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=quota-429-fix-complete root_cause=APIError-23503-routes.py-vibe_routes.py-still-using-UUID-analysis_id-after-record-creation-fails file=app/api/routes.py-app/api/vibe_routes.py fix=routes.py-pass-null-when-create_analysis_record-returns-None-vibe_routes.py-pass-null-always verified=60-tests-passed pushed=f51db71 note=completes-rsi-trend-plan-429-fix-loop
### 2026-08-12T00:40:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-restart-new-code script=scripts/deploy-local-backend.sh health=api-health-200-supabase-ok-redis-ok-tvbridge-ok version=0.2.0
### 2026-08-12T00:55:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=migration-verified root_cause=APIError-23503-FK-violation-migration=20260811_001_nullable_analysis_id_sql verification=grep-23503-no-errors-grep-analyze-no-errors-health-200 version=0.2.0
### 2026-08-12T01:10:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=df_index-fix root_cause=AttributeError-CachedCandleData-no-attribute-df_index-reset_index-called-before-attribute-set file=app/infra/pyharmonics_adapter.py(+4/-2) fix=pass-index='dts'-explicitly-to-reset_index verified=50-tests-passed health=api-health-200 pushed=62d1b55
### 2026-08-12T01:20:00Z [backend-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=backend-restart-new-code script=scripts/deploy-local-backend.sh health=api-health-200-supabase-ok-redis-ok-tvbridge-ok version=0.2.0
### 2026-08-12T13:44:00Z [code-health-audit] loop=1 candidates=1 cost=0.00 outcome=success scope=domain-refactor-regression regression=test_rsi_trend-ImportError-atr_series-NotExported file=app/domain/rsi_trend.py(+3) fix=add-ema_series-rsi_series-atr_series-to-re-export-list-of-strategy_core root_cause=commit-160e769-strategy_core-refactor-omitted-primitive-re-exports verified=test_rsi_trend-28/28-full-suite-2187/6-skipped pushed=65c27e7
### 2026-08-12T13:46:00Z [code-health-audit] loop=1 candidates=3 cost=0.00 outcome=success scope=loop-13-ft-strategy-ui-local-commit-sweep files=41 state=untracked-at-session-start plan=v4 backend=Phase-0-5 frontend=Phase-3 docs=PLANS-LOOP-durable-facts-ADR-0012 plan_added=freqtrade-strategy-bidirectional-compat-v1 pushed=a84c252+b2cae6a+4d411a1 awaiting=push-to-origin-human-approval readiness=100-L3
### 2026-08-12T13:48:00Z [code-health-audit] loop=1 candidates=0 cost=0.00 outcome=success scope=frontend-tc-ft-strategy-clean verified=npx-tsc-ft-strategy-errors=0 unrelated=21-test-file-errors-pre-existing
### 2026-08-12T14:36:00Z [git-push] loop=1 candidates=0 cost=0.00 outcome=success scope=push-8-commits branch=main commits=8 ahead_of_origin=8 pushed_cb374a5_to_8a1be59 user_approval=received
### 2026-08-12T14:37:00Z [binance-cli-install] loop=1 candidates=0 cost=0.00 outcome=success scope=loop-12-prerequisite installed=@binance/binance-cli-v1.3.0 packages=127 user_approval=received smoke=mark-price+open-interest+funding-history-all-ok
### 2026-08-12T14:38:00Z [vercel-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=ft-strategy-ui-deploy-1 url=frontend-b30q24swb build=29s deploy=47s alias=www.cryptoagg.xyz status=200-ok issue=api-ft-strategies-404-no-env-var
### 2026-08-12T14:40:00Z [vercel-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=ft-strategy-ui-deploy-2 url=frontend-4rp3zasqb build=36s deploy=52s fix=next.config-rewrite-+-vercel-env-NEXT_PUBLIC_API_BASE=https://hapi.cryptoagg.xyz alias=www.cryptoagg.xyz status=200-ok
### 2026-08-12T14:42:00Z [vercel-deploy] loop=1 candidates=0 cost=0.00 outcome=success scope=vercel-alias-update alias=www.cryptoagg.xyz target=frontend-4rp3zasqb-gyc567s-projects.vercel.app verify=https://www.cryptoagg.xyz/ft-strategy-200
```
| Value | Meaning |
