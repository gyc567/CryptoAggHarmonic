# Durable Facts — pyharmonics-gpt

> Append-only log of durable project facts.
> NEVER delete entries — mark superseded with `superseded_by`.
> Format: JSON-ish per entry.

## Entries

<!-- Entries are append-only. Format:

### [uuid] — {fact summary}
- **Created**: {date}
- **Content**: {description}
- **Source**: {git commit or decision reference}
- **superseded_by**: {uuid if applicable}

-->

### [v3fup01] — Loop engineering v3 follow-ups shipped
- **Created**: 2026-08-09
- **Source**: docs/loop-engineering-plan.md §7.2 + §10.7 + §16
- **Content**: Closed 4 outstanding v3 follow-ups.
  1. ``/metrics`` publishes all 14 plan §7.2 metrics
     (private ``CollectorRegistry``; producers in driver / worker / runner).
  2. ``scripts/backtest_harmonic_lib._maybe_relax_filters`` no longer
     mutates ``signal_engine.MIN_CANDLES`` via setattr — uses
     ``TuningScope`` (ADR-0003 D9).
  3. ``loop.loop_context.load_episodic`` no longer raises
     ``UnboundLocalError``.
  4. ``app.config.tuning`` exposes ``get_min_candles`` / ``get_atr_window``
     / ``get_rsi_window`` consumed by ``signal_engine.build_signal`` hot
     path.
  24 new tests pass; 407/407 in loop / maker-checker / signal scope.
- **superseded_by**: _none_

### [v3ver01] — Vercel frontend T1 recovery + ssoProtection fix
- **Created**: 2026-08-09
- **Source**: docs/plans/vercel-frontend-deploy.md + commit 1e36b71
- **Content**: Vercel production was broken because (1) plan T1 (9 ESLint
  fixes + RSI strategy API/types) was sitting uncommitted and (2) the
  Vercel project had `ssoProtection` enabled, redirecting every
  request to `vercel.com/sso-api`. Recovery: commit `1e36b71` ships
  T1 + RSI alignment, git-integration auto-deployed
  `pyharmonics-mhry7rpjx` (Ready, 12 routes, 0 ESLint errors); then
  PATCH `https://api.vercel.com/v9/projects/prj_5uBO03IVLLmj3jdhHu3VsWKR1HKf`
  with `{"ssoProtection": null}` to disable SSO. T5 fully verified at
  `https://www.cryptoagg.xyz` (no client-side backend-host leak).
- **superseded_by**: _none_

### [v3ver02] — Magic-link email uses localhost:3000 instead of www.cryptoagg.xyz
- **Created**: 2026-08-09 (updated 2026-08-09 22:55 UTC+8 after verification)
- **Source**: Supabase project piomgijwxpbsvnigtbmt + frontend/hooks/use-auth.ts:60-69
- **Content**: Supabase Auth → URL Configuration has
  ``site_url=http://localhost:3000`` and empty
  ``additional_redirect_urls``. The frontend
  ``useAuth.signInWithOtp`` correctly passes a per-request
  ``emailRedirectTo`` (``${window.location.origin}/dashboard``) but
  the project-level ``site_url`` wins, so the magic-link email
  template renders ``http://localhost:3000/?code=...`` regardless of
  where the user clicked "登录" from. Code is correct; **the fix is
  in the Supabase dashboard** (Authentication → URL Configuration):
  set ``site_url=https://www.cryptoagg.xyz`` and add
  ``https://www.cryptoagg.xyz`` and ``https://www.cryptoagg.xyz/dashboard``
- **Verification (2026-08-09 22:55 UTC+8, RE-RUN 23:05)**: ran
  ``POST /auth/v1/admin/generate_link`` with the service role key
  passing four different ``redirect_to`` values
  (``https://www.cryptoagg.xyz/dashboard``,
  ``https://www.cryptoagg.xyz``, ``http://localhost:3000``,
  ``https://evil.example.com/steal``). All four returned
  ``action_link`` with ``redirect_to=http://localhost:3000``. The
  dashboard change did NOT take effect, or it was applied to a
  different project.
- **Final verification (2026-08-09 23:05 UTC+8, PASSED)**: re-ran the
  same probe after the user re-applied the dashboard change. The
  action_link now contains ``redirect_to=https://www.cryptoagg.xyz``
  for every production-origin request. ``http://localhost:3000``
  and unknown origins are also rewritten to
  ``https://www.cryptoagg.xyz`` (Supabase's new open-redirect
  default). Magic-link emails will now land on the production
  origin. **Bug closed.**
- **superseded_by**: _none_

### [v3auth01] — Backend /api/analyze and /api/history returned 500 due to missing imports in app/api/auth.py
- **Created**: 2026-08-09 23:21 UTC+8
- **Source**: app/api/auth.py + tests/test_auth.py
- **Content**: ``app/api/auth.py`` referenced three names without
  importing them: ``ErrorCode`` (used at three call sites),
  ``verify_user_token`` (called inside ``require_auth`` after a valid
  Bearer token is seen), and ``reserve_user_quota`` (called inside
  ``check_quota``). With no token, ``require_auth`` short-circuits to
  401 — which is what every unauthenticated probe saw. With a valid
  token (the production user flow), the decorator reached
  ``verify_user_token(token)``, raised ``NameError``, and the Flask
  global error handler returned 500. The frontend correctly surfaced
  the 500. **The bug masqueraded as "401 from the wire"** because
  unauthenticated traffic is the only thing curl/regression tests
  ever saw.
- **Fix**: added the three missing imports
  (``from app.domain.enums import ErrorCode``,
  ``from app.infra.supabase_client import reserve_user_quota, verify_user_token``)
  in commit ``<this-commit>``. The backend at ``hapi.cryptoagg.xyz``
  still runs the pre-fix code; redeploy required.
- **Tests added**: ``test_module_level_names_resolve`` (asserts the
  module-level names resolve, guards against a future regression) and
  ``TestAuthEndToEnd.test_valid_token_reaches_handler`` (full
  decorator → handler path with a valid token; pre-fix this 500'd).
- **Verification**: ``pytest tests/`` → 1772 passed, 0 failed (up
  from 1762 — the 7 prior auth-test failures + 1 rsi-trend-api
  failure are all green).
- **superseded_by**: _none_

### [freqtrade-baseline-01] — Freqtrade MCP integration baseline (pre-freqtrade path)
- **Created**: 2026-08-11
- **Source**: `docs/loop-state/phase0-baseline.md` + `docs/plans/freqtrade-mcp-integration.md`
- **Content**: cryptoagg signal loop baseline BEFORE enabling freqtrade downstream path.
  Freqtrade hyperopt results will be evaluated against these numbers.

  | Metric | Baseline value | Date | Notes |
  |--------|----------------|------|-------|
  | avg fitness | +4.267 | 2026-08-08 | mean across 20 accepted candidates |
  | max fitness | +6.377 | 2026-08-08 | params_sha `16c414e73197` |
  | Pareto size | 2 | 2026-08-08 | both points are duplicates |
  | history_records | 20 | 2026-08-08 | C1 Geometry, BTC/ETH/SOL |
  | accepted | 20 | 2026-08-08 | trade-count floor ≥ 30 |
  | LLM $ / gen | $0.00 | 2026-08-08 | MAKER_CHECKER_ENABLED=true but mock backend |

  **ADR-0010 D5 calibration needed** (to be filled after real freqtrade backtest run):
  - `baseline_drawdown`: _TBD_ (from `/metrics` after real generation)
  - `baseline_calmar`: _TBD_
  - `shadow_mode_days`: _TBD_ (Phase 4 shadow mode required before live promotion)

  Phase 0 run command:
  ```bash
  MAKER_CHECKER_ENABLED=false python -m app.loop.driver \
    --candidates candidates-baseline.json \
    --state-root .scratch/loop_state/phase0_live \
    --workers 4 --timeout 900
  curl -s localhost:5000/metrics | grep -E "(drawdown|calmar|tuning_proposals)"
  ```
- **superseded_by**: _none_
