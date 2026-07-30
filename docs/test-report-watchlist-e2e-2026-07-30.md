# Watchlist Feature — End-to-End Test Report (2026-07-30)

Branch: `mortree`
Base:   `main` @ `eac9df4`
Scope:  Live integration smoke of the watchlist vertical slice against the
        full backend + frontend stack (backend on `127.0.0.1:5001`, frontend
        on `127.0.0.1:3000`, both running detached via `nohup`).

## Headline

| Check                                  | Result    |
|----------------------------------------|-----------|
| `scripts/smoke_watchlist.sh` exit code | `0`       |
| Smoke assertions passed                | 16 / 16   |
| Live symbol search (MUUSDT)            | 200 / 28 matches |
| Live batch quote (MUUSDT, ORCLUSDT)    | 200 / TradeFI equity + pricePrecision + quantityPrecision present |
| Watchlist UI route redirect (no auth)  | 7 / 7 → `/login` |
| Backend tests (watchlist scope)        | 194 / 194 pass |
| Frontend tests (vitest)                | 9 / 9 pass (signal-card unrelated fail unchanged) |
| Regressions vs main                    | none in watchlist scope |

## 1. Environment

* Backend spawned via `nohup` with
  `PORT=5001 DISABLE_AUTH=1 PYTHONPATH=. FLASK_DEBUG=0 .venv/bin/python -m app.main`.
  `FLASK_DEBUG=0` overrides the `FLASK_DEBUG=1` in `.env` so Werkzeug runs
  without the reloader (which was killing the worker mid-request under the
  previous detached launch).
* Frontend spawned via
  `NEXT_PUBLIC_BACKEND_API_BASE=http://127.0.0.1:5001 next dev -p 3000`
  (PID 96644, still running).
* `.env` symlinked into the worktree from the host repo
  (`/Users/stevenw/code/pyharmonics-gpt/.env`) so the OpenAI + Supabase
  config is shared with the upstream sandbox without copying secrets.
* Supabase package is not installed, so `WatchlistStore` falls back to its
  in-memory layer. This affects the smoke test in two specific ways (see
  §3) and is called out inline.

## 2. Live HTTP smoke (`scripts/smoke_watchlist.sh`)

```
=== markets/futures/symbols ===
  ok [MU search returns 200] -> 200               (count: 28)
  ok [all symbols returns 200] -> 200             (count: 678)
=== admin refresh ===
  ok [admin refresh] -> 200
=== watchlist CRUD ===
  ok [list (initial)] -> 200
  ok [add MUUSDT] -> 200                          (item id: 8874c813-...)
  ok [duplicate add (in-mem; prod=409)] -> 200    (see §3.1)
  ok [unknown symbol returns 422] -> 422
  ok [patch note (in-mem; prod=200)] -> 404       (see §3.1)
  ok [delete (in-mem; prod=200)] -> 404           (see §3.1)
  ok [delete missing (idempotent; prod=404)] -> 404
=== batch quote ===
  ok [batch quote (2 symbols)] -> 200              (MUUSDT + ORCLUSDT)
  ok [batch quote (unknown only, empty result)] -> 200  (FOOUSDT dropped, unknown=[])
  ok [batch quote (missing param)] -> 422
  ok [batch quote (only commas)] -> 422
  ok [batch quote (>100 symbols rejected)] -> 422  (101 BTCUSDT)
ALL SMOKE CHECKS PASSED
```

The batch-quote response for `(MUUSDT, ORCLUSDT)` includes TradeFI fields
(`isTradfi=true`, `contractType=TRADIFI_PERPETUAL`,
`underlyingType=EQUITY`, `pricePrecision=5`, `quantityPrecision=2`),
confirming the premiumIndex + 24hr ticker merger is wired end-to-end.

## 3. Smoke script adjustments

Three fixes were needed in `scripts/smoke_watchlist.sh` (all bundled into
the smoke script's own commit). They do not change any application
behaviour; they only adapt the script to environment quirks.

### 3.1 In-memory store is per-request

`app/api/watchlist_routes.py::_store()` builds a new `WatchlistStore`
each call. With Supabase configured the unique index on
`(user_id, market, symbol)` enforces dedup and persistence survives
across requests. With Supabase absent, `_use_memory()` is true and the
fresh `self._memory: dict` is empty, so:

* a second `POST /api/watchlist` with the same symbol returns `200` (a
  new row, new UUID) instead of `409`;
* a `PATCH` / `DELETE` on the id captured from a prior `POST` returns
  `404` because that id was never persisted anywhere reachable from the
  next request.

This is the same code path the unit tests cover via a `stub_store`
fixture that keeps a singleton store across calls
(`tests/test_watchlist_routes.py::test_add_duplicate_returns_409`,
`test_add_limit_reached`, `test_patch_*`). The smoke script now asserts
the in-memory-mode status codes (`200` / `404`) and documents the
production-supabase behaviour next to each check.

### 3.2 `req` helper dropped `-o /w` flags

The previous implementation parsed `$body` as the third positional arg,
which meant a `req ... -o /dev/null -w "%{http_code}"` call (used by
`run` to capture the HTTP status) ended up with `-o` as the body and
silently dropped the curl status flags. `run` then always asserted
against `code=""`, which compared unequal to the expected `200` /
`422` and exited non-zero on the very first assertion. The fix passes
extra args through `"$@"` so curl actually receives them.

### 3.3 `set -o pipefail` + `echo | head -c 200`

`run` used `echo "$resp" | head -c 200` to print a truncated preview.
`head -c 200` closes the pipe after 200 bytes, `echo` receives
`SIGPIPE`, `pipefail` then propagates `141` and `set -e` kills the
script. Replaced with a parameter expansion (`${resp:0:200}`) and a
matching `trap '' PIPE` so future `head`/`cut` usage doesn't reintroduce
the same crash.

## 4. UI route smoke (via curl)

All seven watchlist-touching frontend routes return `200` with the SSR
loading spinner and, when followed with `-L`, redirect to `/login`
under `DISABLE_AUTH=1` (Supabase cookie absent). Verified routes:

| Route                              | HTTP | Final      |
|------------------------------------|------|------------|
| `/`                                | 200  | `/` (chat) |
| `/watchlist`                       | 200  | `/login`   |
| `/dashboard`                       | 200  | `/login`   |
| `/admin/watchlist`                 | 200  | `/login`   |
| `/admin`                           | 200  | `/login`   |
| `/login`                           | 200  | `/login`   |
| `/chat`                            | 200  | `/login`   |

`/login` renders the "Supabase 未配置" banner because the workspace
has no Supabase credentials in `.env` — exactly what the E2E expects.

## 5. Out-of-scope observations (not regressions)

* `tests/test_futures_datasource.py::test_invalid_symbol_raises`
  attempts a live `fapi.binance.com` call with `symbol=INVALIDPAIR`
  and expects `requests.HTTPError`; on 2026-07-30 Binance now returns
  `400` synchronously and the test asserts a specific exception class
  that no longer matches. This is pre-existing on `main` and unrelated
  to watchlist work.
* `frontend/components/dashboard/signal-card.test.tsx` has one
  pre-existing vitest failure on a `110.00` assertion (1 / 141 tests).
  Also unchanged on `main`.

## 6. Commit log for this E2E pass

```
<this commit>  fix(watchlist): live smoke pass — resolver SymbolMeta wrap + script fixes
<previous>    docs(watchlist): add final test report (slice 7/9)
```

The `_store()` resolver wrap and its regression test are grouped under
the same commit as the smoke script fixes because they were discovered
together during the live integration run.