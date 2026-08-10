# Loop State — pyharmonics-gpt

> 由 `daily-triage.yml` 等 workflow 自动更新。
> 人类每周审查一次。

## High Priority

<!-- 由循环自动填充 -->

- [x] 2026-08-08: GitHub Issues **enabled** on `gyc567/pyharmonics-gpt` (smoke #1 closed)
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
