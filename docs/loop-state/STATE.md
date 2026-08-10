# Loop State — cryptoagg

> 由 `daily-triage.yml` 等 workflow 自动更新。
> 人类每周审查一次。

## High Priority

<!-- 由循环自动填充 -->

- [ ] 2026-08-10: **Backtest Evolution Plan — IN PROGRESS.** Designed
  auto-evolution backtest + optimization system using loop engineering
  methodology. Output: `docs/plans/2026-08-10-backtest-evolution-plan.md`.
  Covers: Confluence Filter + Confidence Score + standard SL/TP rules +
  Walk-forward backtest + Freqtrade integration (Phase 1-4 roadmap).
  Registered in `PLANS.md`. Next step: Phase 1 implementation
  (ConfluenceFilter in `app/domain/signals.py`).
- [x] 2026-08-10: **Backtest feedback loop — CLOSED (deployed).**
  Daily pipeline: cron 20:00 UTC → run_backtest.py → backtest_results.json
  + tuning_snapshots/daily_*.yaml (candidate) → human PR → tuning.py.
  Fixes found: (1) _load_history ignored start/end — walked the full
  17521-row cache (720 windows ≈ 6min); now date-slices (31d backtest 14s);
  (2) score_candidate overflow: Q4 pattern bump pushed confluence score
  past 100 → grade() @require violations skipped valid signals; clamped;
  (3) confluence weights were hardcoded and TUNING.confluence_weights was
  inert — wired to tuning + grid_search_weights() with sum-to-100
  constraint; (4) liquidity-sweep gate added (D-bar volume > 3x 20-bar
  mean → trap marker, not veto); (5) shebang pinned to .venv (PATH python3
  is a 3.12 dist-scripts 'scripts' package that shadows repo module);
  (6) multiprocessing returns per-symbol summaries, not raw records.
  Verified: 252 signal/backtest tests pass; real-data grid-search runs;
  3-symbol parallel dry-run 4s. Known env failures (unrelated): futures/
  kline datasource tests need external network feeds.
- [x] 2026-08-10: **Backend 401 — CLOSED (deployed).** Frontend reported
  401 on /api/analyze and /api/history. Root cause: SUPABASE_ANON_KEY
  uses the new `sb_publishable_...` format which supabase-py 2.15.0
  rejects at create_client (Invalid API key) — verify_user_token
  returned None for every request. Fixed by upgrading to
  supabase-py 2.31.0 (accepts publishable keys). Secondary fixes found
  while verifying: (1) routes.py reserved quota BEFORE creating the
  analyses row — usage_ledger.analysis_id FK 23503 → reordered to
  create record first, added delete_analysis_record cleanup on quota
  rejection; (2) analysis_type/market/interval/status now normalized
  to live schema CHECK constraints (auto→forming placeholder,
  futures→binance, 1m/5m→15m, failed→failed_upstream) + resolved_type
  written back on completion; (3) result.timing.get() AttributeError
  (TimingInfo is a pydantic model, not dict) — token counts not
  tracked yet, pass None. Verified live: /api/history 200 with real
  token; /api/analyze passes auth+quota (reserve_quota 200, release
  on failure), only remaining blocker is Yahoo rate-limit 503 (external).
- [x] 2026-08-08: GitHub Issues **enabled** on `gyc567/cryptoagg` (smoke #1 closed)
- [x] 2026-08-08: Triage + loop labels created (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `maker-checker`, `release-prep`, `code-health`, `dependencies`, `automated`, `loop`)
- [x] 2026-08-08: #3 apply_tuning Path A (get_tuning live reads)
- [x] 2026-08-09: **Loop engineering v3 follow-ups** — wired 14-metric /metrics
  (private CollectorRegistry), closed `MIN_CANDLES` setattr bug via
  `TuningScope` in `scripts/backtest_harmonic_lib`, fixed
  `loop.loop_context.load_episodic` UnboundLocal, added
  `get_min_candles` / `get_atr_window` / `get_rsi_window` accessors
  consumed by `signal_engine.build_signal`. 24 new tests pass; full
  loop / maker-checker / signal-engine suites green (407/407).
- [x] 2026-08-09: **Vercel frontend T1 recovery** — plan T1 (ESLint + RSI
  strategy types) was never on main, so the git-based redeploy at
  22:14 UTC+8 errored with the original 9 ESLint errors. Commit
  `1e36b71` shipped the working-tree fixes; auto-deployed
  `pyharmonics-mhry7rpjx` is Ready. Discovered and PATCHed
  `ssoProtection=null` on the project (was redirecting every
  request to `vercel.com/sso-api`). Public site now serves the new
  deploy at `https://www.cryptoagg.xyz` (T5 fully verified: `/`,
  `/login`, `/dashboard`, `/rsi-strategy`, `/api/health`,
  `/api/markets` all 200, no client-side backend-host leak).
- [x] 2026-08-10: **Backend auth 500 — CLOSED (deployed).** Ran the
  loop-audited ``scripts/deploy-backend-auth-fix.sh`` on the server.
  Audit found 4 env deltas vs the original script (non-git rsync
  deploy dir, origin/main moved past c6c2d0e, systemd-managed
  gunicorn, missing pytest) — script adapted accordingly.
  Post-restart probes: ``/api/analyze`` no-auth=401, Bearer=401,
  ``/api/history`` Bearer=401 (was 500). ``tests/test_auth.py``
  15/15. Durable fact `[v3auth01]` verified closed.
- [x] 2026-08-09: **Backend auth 500 — fixed in repo, awaits backend
  redeploy.** ``app/api/auth.py`` referenced ``ErrorCode``,
  ``verify_user_token``, and ``reserve_user_quota`` without
  importing them. Any authenticated request to
  ``/api/analyze`` or ``/api/history`` raised ``NameError`` and the
  Flask global error handler returned 500 (the public-facing
  symptom reported by the user). Unauthenticated traffic returned
  401 normally, so the bug was invisible to unauthenticated
  probes. Added the three imports in this commit; added a
  ``TestAuthEndToEnd.test_valid_token_reaches_handler`` regression.
  Suite: 1772/0. The live backend at ``hapi.cryptoagg.xyz`` still
  runs the pre-fix code; **redeploy required** to clear the 500.
  Durable fact `[v3auth01]`.
  instead of `www.cryptoagg.xyz`.~~ Supabase project
  `piomgijwxpbsvnigtbmt` Auth → URL Configuration now has
  ``Site URL = https://www.cryptoagg.xyz`` and
  ``Additional Redirect URLs`` containing the production origin.

  Verified by ``POST /auth/v1/admin/generate_link`` — action_link
  now contains ``redirect_to=https://www.cryptoagg.xyz``. Durable
  fact `[v3ver02]` carries the verification log.

---

_Maintained by: `.github/workflows/daily-triage.yml`_
_See also: `docs/loop-state/LOOP.md`_
