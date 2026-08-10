# Plan: Backend Auth 500 Fix (and Deploy)

## Status: source-side fix shipped; backend redeploy required

Production URL: **https://www.cryptoagg.xyz** (frontend, no change). Backend at `https://hapi.cryptoagg.xyz` is the only thing that needs the redeploy.

## Context

User clicked 开始分析 in the live UI and the browser dev-tools showed:

```
api/history:1   Failed to load resource: the server responded with a status of 500 ()
api/analyze:1   Failed to load resource: the server responded with a status of 500 ()
```

Both routes are decorated with `@require_auth` in `app/api/routes.py`. The decorator calls `verify_user_token(token)` once a valid Bearer token is seen, but `app/api/auth.py` referenced `verify_user_token`, `reserve_user_quota`, and `ErrorCode` without ever importing them. The first authenticated request raised `NameError`, Flask's global error handler returned 500, the frontend correctly surfaced the 500. Unauthenticated traffic short-circuited to 401 at line 65, which is why unauthenticated probes never saw it and the bug went unnoticed for so long.

The 8 previously-failing tests in `tests/test_auth.py` (and 1 in `tests/test_rsi_trend_api.py`) were the canary — they were failing in every CI run for the same reason, masked behind an `AttributeError: module 'app.api.auth' has no attribute 'verify_user_token'` from `mock.patch` import time.

## Goals

- [x] Source-side fix: add the three missing imports in `app/api/auth.py`.
- [x] Regression coverage: `test_module_level_names_resolve` and `TestAuthEndToEnd.test_valid_token_reaches_handler` guard the path.
- [x] Source fix pushed to `origin/main` (commit `c6c2d0e`).
- [x] Full test suite green: 1772 passed, 0 failed (was 1762 passed, 8 failed).
- [x] **Backend redeploy at `hapi.cryptoagg.xyz`** — done 2026-08-10 via
  `scripts/deploy-backend-auth-fix.sh` (loop-audited; 4 env deltas
  fixed: non-git deploy dir, origin/main past c6c2d0e, systemd-managed
  gunicorn, missing pytest). Probes: analyze no-auth=401, bearer=401,
  history=401. auth tests 15/15.

## Tasks

### T1. Source fix (DONE, commit `c6c2d0e`)

`app/api/auth.py` — add three imports:

```python
from app.domain.enums import ErrorCode
from app.infra.supabase_client import reserve_user_quota, verify_user_token
```

Diff size: +6 lines.

### T2. Regression tests (DONE, commit `c6c2d0e`)

`tests/test_auth.py`:
- `test_module_level_names_resolve` — module-level name resolution guard.
- `TestAuthEndToEnd.test_valid_token_reaches_handler` — full decorator → handler path; pre-fix this 500'd.

`tests/`: 1772 passed, 0 failed.

### T3. Backend redeploy (PENDING — operator action required)

Source-side fix is on `origin/main`. The live `hapi.cryptoagg.xyz` Flask process must be restarted to pick up the new `app/api/auth.py`.

Run on the backend server (via SSH):

```bash
cd /opt/pyharmonics-gpt   # or wherever the repo is checked out
./scripts/deploy-backend-auth-fix.sh
```

The script:
1. Verifies `origin/main` is at the expected commit (`c6c2d0e`).
2. `git pull --ff-only`.
3. Confirms the fix import is in `app/api/auth.py`.
4. Runs `pytest tests/test_auth.py` (15/15).
5. Restarts gunicorn (via `scripts/start-backend.sh restart`, `systemctl`, or direct `kill -TERM`).
6. Probes `https://hapi.cryptoagg.xyz/api/analyze` and `/api/history` with a dummy Bearer token; expects 401, not 500.

Exit codes:
- `0` — success, auth 500 closed.
- `2` — `origin/main` is not at the fix commit; push first.
- `3` — `app/api/auth.py` is missing the fix import (git pull failed silently).
- `4` — post-restart probe still 500s; gunicorn didn't pick up the new code (check `journalctl -u gunicorn` or gunicorn logs).

### T4. Post-deploy verification

1. `pytest tests/` on the server (1772/0).
2. Live: `curl -X POST -H 'Authorization: Bearer dummy' -d '{}' https://hapi.cryptoagg.xyz/api/analyze -w '\nstatus: %{http_code}\n'` → 401, not 500.
3. User opens the dashboard, clicks 开始分析, the dev-tools should now show 200/4xx instead of 500.

## Verification (acceptance criteria)

- [x] `pytest tests/` exit 0 (1772/0).
- [x] `app/api/auth.py` imports `ErrorCode`, `verify_user_token`, `reserve_user_quota`.
- [x] `https://hapi.cryptoagg.xyz/api/analyze` returns 401 (not 500) with a Bearer token.
      Verified 2026-08-10: bearer probe = 401, no-auth = 401, history = 401.
- [ ] User's 开始分析 action succeeds in the UI. (待用户在前端确认)

## Rollback

- `git revert c6c2d0e` → reverts to the broken state; that re-introduces the bug.
- The right rollback is: re-investigate whether the auth module ever had a real `verify_user_token` (it didn't — commit `c6c2d0e` is the correct fix). If the 500s persist after T3, the new code is not running; check gunicorn logs for import errors (e.g. a typo in the new path, missing `supabase` package on the server).

## Out of scope

- `Invalid API key` error in `/api/health` (supabase-side env on the backend, separate fix).
- Frontend deploy (already on `origin/main` via git-integration; no change).
- A direct, automated way to redeploy the backend — the backend is self-hosted, not on a managed PaaS, and the operator holds the SSH key.
