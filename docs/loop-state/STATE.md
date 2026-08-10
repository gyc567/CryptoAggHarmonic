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

## Watch List

- **[!] Auth: magic-link email STILL uses `localhost:3000` — Supabase
  dashboard change did not take effect.**
  ``POST /auth/v1/admin/generate_link`` with the service role key
  confirms: for any ``redirect_to`` value
  (``https://www.cryptoagg.xyz``, ``https://www.cryptoagg.xyz/dashboard``,
  even ``https://evil.example.com/steal``), Supabase returns
  ``action_link`` with ``redirect_to=http://localhost:3000``.
  Project `piomgijwxpbsvnigtbmt` ``site_url`` is still
  ``http://localhost:3000`` and ``additional_redirect_urls`` is
  empty (or doesn't include ``www.cryptoagg.xyz``). Possible causes:
  (a) dashboard change saved to a different project / wrong org,
  (b) cache/propagation delay, (c) page submitted but the dialog
  wasn't confirmed. Re-open
  https://supabase.com/dashboard/project/piomgijwxpbsvnigtbmt/auth/url-configuration
  and re-save. Durable fact `[v3ver02]`.
- Validate `loop-init` scaffolds on fresh projects across all patterns

## Recent Noise (ignored this run)

<!-- 由循环自动填充 -->

---

_Maintained by: `.github/workflows/daily-triage.yml`_
_See also: `docs/loop-state/LOOP.md`_
