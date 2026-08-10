# Plan: Vercel Frontend Deployment (CLI)

## Status: PARTIAL REDEPLOY NEEDED (brand content not on live site)

**2026-08-10 audit**: Live site `https://www.cryptoagg.xyz` serves `<title>Pyharmonics</title>`
but current main (`9d7c634`) has `<title>CryptoAgg</title>` (commit `45b62bf`). Brand phase
frontend changes have NOT been deployed despite being on `main`.

**Root cause**: Git-based auto-deploy from `1e36b71` (ESLint T1 recovery) is the currently
serving production deploy. Subsequent `main` commits have not re-triggered a redeploy.

**29 commits** on main since `1e36b71`, including:
- `45b62bf` brand Phase 1: frontend UI "Pyharmonics" → "CryptoAgg"
- `ba1e171` brand Phase 4: Supabase bucket `cryptoagg-bucket` / `cryptoagg:*`
- Backend auth-fix (`c6c2d0e` → `616e701` → `a0adcda` → `17c1899`) — **already live on hapi**
- Backtest loop improvements, dependency fixes

**Action required**: `git push origin main` → Vercel auto-deploys → verify `<title>CryptoAgg`.

**Backend auth-fix**: Confirmed live — `/api/analyze` and `/api/history` return 401 (not 500).

---
*Previous status (2026-08-09)*: COMPLETED — re-validated after T1 recovery + ssoProtection fix.

Recovery note (22:35 UTC+8, same day):
the original T1 was applied to the working tree but never committed.
The git-based redeploy at 22:14 UTC+8 errored with the same 9 ESLint
errors that the original T1 had fixed locally. The custom domain
continued serving the prior 4h-old Ready deploy (`9nb2noank`) so the
public surface was not down, but the active production deploy was
Error. Two corrective actions:
1. Commit `1e36b71` — ships the 9 ESLint fixes + the RSI strategy
   `api-rsi-strategy.ts` types/hardening that the author had staged.
   The git-integration auto-deployed `pyharmonics-mhry7rpjx` and the
   build passed (12 routes, 0 ESLint errors).
2. Discovered `ssoProtection` was enabled on the project (Vercel
   Authentication → "Standard"), causing every request to 302 to
   `vercel.com/sso-api?url=...` and breaking the public site even
   after the green build. PATCHed the project via
   `https://api.vercel.com/v9/projects/prj_5uBO03IVLLmj3jdhHu3VsWKR1HKf`
   with `{"ssoProtection": null}` to disable it. Public site now
   serves the new deploy directly.

## Status

- T1 ✅ ESLint blockers fixed (9 errors, 5 files) + all pre-existing TS type errors resolved; `npm run build` exit 0; `npm test` 179/179 *(fixed on main in commit 1e36b71)*
- T2 ✅ Project config via PATCH `/v9/projects/pyharmonics-gpt`: framework=nextjs, rootDirectory=frontend, nodeVersion=22.x, build/install commands null *(still good)*
- T3 ✅ Env vars set (production + preview, `type: encrypted`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_DEFAULT_MARKET` (sourced from `frontend/.env.local`), `BACKEND_API_BASE=https://hapi.cryptoagg.xyz`. `NEXT_PUBLIC_API_BASE` intentionally **not set** → same-origin rewrites (Vercel CLI never uploads `.env*.local`, verified absent from client JS)
- T4 ✅ Git-based auto-deploy via push to `main` *(was originally `vercel --prod --yes`; switched to git-integration after `vercel link` already bound at root)*
- T5 ✅ Verified: `/` 200, `/login` 200, `/dashboard` 200, `/rsi-strategy` 200, `/api/health` → backend JSON (redis ok, supabase Invalid API key = known backend-side issue, out of scope), `/api/markets` 200, no `hapi.cryptoagg.xyz` / `127.0.0.1:5000` in client chunks, status Ready

## Context

Pyharmonics SaaS: Next.js 14 frontend (`frontend/`) + Flask backend (self-hosted at
`https://hapi.cryptoagg.xyz`) + Supabase (auth/DB).

Goal: deploy the frontend to Vercel via the Vercel CLI, wiring the frontend to the
existing backend at `https://hapi.cryptoagg.xyz`.

## Findings from baseline investigation (2026-08-09)

1. **Vercel project `pyharmonics-gpt` is misconfigured.** Project settings show
   `framework: flask`, `rootDirectory: None`, no build command, no install command,
   **zero environment variables**. All 11 past production deployments errored in 3–4s —
   Vercel tried to build the Flask repo root instead of the Next.js app in `frontend/`.
2. **Local `npm run build` fails** on 9 pre-existing ESLint errors across 5 files:
   - `app/rsi-strategy/page.tsx` — unused `scanResult/scanLoading/scanError/runScan`
   - `components/dashboard/result-panel.tsx` — unescaped `"` entities (line 68)
   - `components/error-boundary/chunk-error-boundary.tsx` — unused `_info`
   - `lib/api.test.ts` — unused `beforeEach` import
   - `lib/supabase/client.ts` — `any` types (54, 65), unused `_cb` (61)
   Next.js `next build` runs ESLint by default → build fails → any Vercel deploy fails.
3. **Backend is live**: `GET https://hapi.cryptoagg.xyz/api/health` → 200
   `{"status":"degraded", redis:ok, tradingview_bridge:ok, supabase:invalid-api-key}`.
   The supabase error is a **backend-side** env problem (out of scope for frontend deploy).
4. **API wiring**: frontend `lib/api.ts` calls same-origin `/api/*`; `next.config.mjs`
   rewrites `/api/*` → `BACKEND_API_BASE`. Browser only talks to the Vercel origin, so
   **no CORS changes needed on the backend**. `NEXT_PUBLIC_API_BASE` stays empty in prod.
5. **Auth**: Supabase magic-link; `signInWithOtp` redirects to
   `${window.location.origin}/dashboard` (origin-dynamic → works on any Vercel domain).
   Supabase anon key in `frontend/.env.local` is a publishable key (safe to expose).
6. **Vercel CLI 51.0.0 installed**, authenticated as `gyc567` (scope `gyc567s-projects`).
7. **Git**: repo `gyc567/pyharmonics-gpt`, branch `main`, git-link already enabled on the
   project (`productionBranch: main`) but git-based deploys also fail for the same reasons.

## Goals

- [x] Green production deploy of the frontend via `vercel` CLI
- [x] Project config fixed (nextjs framework, rootDirectory=`frontend`, node 22.x)
- [x] Env vars set on Vercel: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
     `BACKEND_API_BASE=https://hapi.cryptoagg.xyz`, `NEXT_PUBLIC_DEFAULT_MARKET` (`NEXT_PUBLIC_API_BASE` left unset → same-origin)
- [x] `npm run build` passes locally (ESLint + TS blockers fixed)
- [x] Production URL serves the app; `/api/health` proxies through to the backend

## Tasks

### T1. Fix ESLint build blockers (pre-requisite for ANY deploy)

Fix in `frontend/`:
- `app/rsi-strategy/page.tsx` — remove unused destructured vars
- `components/dashboard/result-panel.tsx` — escape quotes on line 68
- `components/error-boundary/chunk-error-boundary.tsx` — prefix unused param or consume it
- `lib/api.test.ts` — drop unused `beforeEach` import
- `lib/supabase/client.ts` — type the mock client instead of `as any`, fix `_cb`

Verify: `cd frontend && npm run build` → exit 0.

### T2. Fix Vercel project configuration

Via API (`PATCH /v9/projects/pyharmonics-gpt`):
- `framework: "nextjs"`
- `rootDirectory: "frontend"`
- `nodeVersion: "22.x"` (matches local dev; Next 14.2 supports it)
- ensure `buildCommand`/`installCommand` left null (Next.js zero-config)
- (git-based deploys then work automatically too)

### T3. Set Vercel environment variables

Production + Preview, from `frontend/.env.local`:
- `NEXT_PUBLIC_SUPABASE_URL=https://piomgijwxpbsvnigtbmt.supabase.co`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_OUSZKe4KXufvYWkTNrcSHg_xvMk44Or`
- `BACKEND_API_BASE=https://hapi.cryptoagg.xyz`
- `NEXT_PUBLIC_API_BASE=""` (empty — keep same-origin rewrites)
- `NEXT_PUBLIC_DEFAULT_MARKET=binance`

Use `vercel env add <key> production` (and `preview`) — non-interactive with `--yes`.

### T4. Deploy via CLI

```bash
cd frontend
vercel link --yes --project pyharmonics-gpt
vercel --prod --yes
```

Capture the production URL. Confirm status `Ready` via `vercel ls` / `vercel inspect`.

### T5. Verify

1. `vercel inspect <url>` → status Ready
2. `curl -sI https://<prod-url>/` → 200, HTML
3. `curl -s https://<prod-url>/api/health` → backend JSON (proves rewrite proxy)
4. `curl -s -o /dev/null -w '%{http_code}' https://<prod-url>/login` → 200
5. No CORS involved (same-origin); confirm `NEXT_PUBLIC_API_BASE` empty at runtime
   (check built JS does not contain `hapi.cryptoagg.xyz` as browser base — it must only
   appear in server-side rewrite config)

## Verification (acceptance criteria)

- [x] `npm run build` exit 0 (lint + type clean)
- [x] Vercel project settings: framework=nextjs, rootDirectory=frontend, nodeVersion 22.x
- [x] Production deployment Ready
- [x] `GET /` 200
- [x] `GET /api/health` returns backend payload (proxy works end-to-end)
- [x] `/login` 200
- [x] No secrets leaked in repo / build output

## Rollback

- `vercel rollback <prod-url>` → previous successful deployment
- Revert project settings via same PATCH API
- Plan file lives in git history (archived after completion)

## Out of scope

- Backend supabase "Invalid API key" (backend-side env — separate fix)
- Custom domain binding (not requested)
- Redis/RQ vibe worker architecture changes (backend concern)
