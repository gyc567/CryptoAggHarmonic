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
  to ``additional_redirect_urls``. Localhost can stay for dev if
  the dev entrypoint is also added.
- **Verification (2026-08-09 22:55 UTC+8)**: ran
  ``POST /auth/v1/admin/generate_link`` with the service role key
  passing four different ``redirect_to`` values
  (``https://www.cryptoagg.xyz/dashboard``,
  ``https://www.cryptoagg.xyz``, ``http://localhost:3000``,
  ``https://evil.example.com/steal``). All four returned
  ``action_link`` with ``redirect_to=http://localhost:3000``. The
  dashboard change did NOT take effect, or it was applied to a
  different project. **Open verification still required.**
- **superseded_by**: _none_
