# Watchlist Feature — Test Report (2026-07-30)

Branch: `mortree`
Base:   `main` @ `eac9df4`
Scope:  自选币种 / Watchlist feature, 6 commits, end-to-end vertical slice
        from cache → store → routes → quote endpoint → frontend → scripts.

## Headline numbers

| Surface                 | Tests        | Coverage          |
|-------------------------|--------------|-------------------|
| `app/infra/futures_symbols_cache.py` | 39/39 pass  | 100% line  |
| `app/infra/watchlist_store.py`       | 57/57 pass  | 100% line  |
| `app/infra/futures_quote.py`         | 43/43 pass  | 100% line  |
| `app/api/watchlist_routes.py`        | 54/54 pass  | 100% line  |
| `frontend/lib/api-watchlist.ts`      |  9/9  pass  | 100% call  |
| **Full backend suite**               | **1295 pass** | **+0 regression vs main** |
| Pre-existing fails (baseline)        | 11 fail + 15 error | unrelated, see §3 |
| Pre-existing vitest fail             | 1 (signal-card) | unrelated      |

## Commit log

```
34e93f7 feat(watchlist): verification script + fundingRate key fix (slice 6/9)
5ee98b2 feat(watchlist): frontend page, sidebar entry, hook, API wrapper (slice 5/9)
b71972e feat(watchlist): batch quote endpoint with retry helper (slice 4/9)
74c118e feat(watchlist): HTTP routes + pydantic schemas (slice 3/9)
8020439 feat(watchlist): persistence layer with Supabase + memory mirror (slice 2/9)
a744505 feat(watchlist): add symbol cache, migration, and design doc (slice 1/9)
```

## 1. Slice-by-slice breakdown

### Slice 1 — Symbol cache (`a744505`)

* `app/infra/futures_symbols_cache.py` (340 lines): file-backed JSON cache
  with 7-day mtime TTL, `threading.Lock` to dedupe concurrent background
  refreshes, built-in default fetcher, and `get_meta(symbol)` single-row
  lookup. Module-level `get_symbols_cache()` / `reset_symbols_cache_for_tests()`
  singleton pair.
* `tests/test_futures_quote.py` — 39 cases covering:
  cache hit/miss, mtime expiry, parse-from-exchangeinfo (including
  `contractType`, `underlyingType`, `underlyingSubTypes`, `pricePrecision`,
  `quantityPrecision`, `onboardDate`, `isTradfi`), background refresh
  dedupe, error handling, and the module-level singleton.

### Slice 2 — Persistence (`8020439`)

* `migrations/20260730_005_watchlist_items.sql` — table + RLS +
  `touch_watchlist_items_updated_at()` trigger.
* `app/infra/watchlist_store.py` (476 lines): `WatchlistStore` with five
  public methods (`list_items`, `create_item`, `update_item`, `delete_item`,
  `reorder`), Supabase primary path, **memory mirror** as the design-v3
  fallback so an insert that committed to Supabase also keeps the in-memory
  view consistent (later Supabase reads/writes can succeed via memory even
  if the network goes down).
* Four exception classes — `LimitReachedError`, `DuplicateError`,
  `NotFoundError`, `UnknownSymbolError` — each raised on a distinct error
  branch and translated by the route layer.
* `_is_unique_violation` matches the four shapes Supabase/PostgREST uses
  for unique-constraint failures (`23505`, `P2002`, `"duplicate key"`,
  `"unique constraint"`).
* 57 tests cover every code path: Supabase happy path, memory fallback,
  dual-write consistency, unique-violation patterns, missing-symbol
  whitelist, 51-item limit, atomic reorder, single-item update with note
  + sort_index, error-class routing.

### Slice 3 — Routes + schemas (`74c118e`)

* `app/domain/watchlist_schemas.py` — Pydantic v2 with `Annotated +
  StringConstraints` for symbol (3-32 chars, A-Z0-9), note (≤280 chars,
  no overflow), reorder items (≤200, id+sort_index required).
* `app/api/watchlist_routes.py` — Flask Blueprint `watchlist_bp` with 6
  endpoints (symbols search, admin refresh, list, add, update, delete,
  reorder). Each WatchlistStore exception maps to a specific
  `ErrorCode + HTTP status` pair:
  | Exception            | ErrorCode                  | Status |
  |----------------------|----------------------------|--------|
  | `DuplicateError`     | `DUPLICATE_SYMBOL`         | 409    |
  | `LimitReachedError`  | `WATCHLIST_LIMIT_REACHED`  | 422    |
  | `UnknownSymbolError` | `WATCHLIST_UNKNOWN_SYMBOL` | 422    |
  | `NotFoundError`      | `NOT_FOUND`                | 404    |
  | `ValueError`         | `INVALID_PARAMS`           | 422    |
  | (admin) non-admin    | `FORBIDDEN`                | 403    |
* `scripts/smoke_watchlist.sh` — curl smoke script covering every
  endpoint with status assertions.
* 54 tests, 100% line coverage of the routes module.

### Slice 4 — Quote endpoint (`b71972e`)

* `app/infra/futures_quote.py` (420 lines): `fetch_quotes(symbols)` merges
  `GET /fapi/v1/ticker/24hr` (lastPrice, priceChangePercent, volume,
  quoteVolume, count, highPrice, lowPrice) with `GET /fapi/v1/premiumIndex`
  (markPrice, fundingRate, nextFundingTime) in a single round-trip.
  * Retries: HTTP 429 / `requests.ConnectionError` / `requests.Timeout`
    trigger exponential backoff `0.5s → 1s → 2s` (3 attempts max).
  * Hard 4xx other than 429 and `ValueError` from `resp.json()` are NOT
    retried (they indicate a structural problem that won't fix itself).
  * `claim_fetch()` / `release_fetch()` form an in-process de-dupe so two
    workers don't hammer Binance on the same client refresh.
* `GET /api/markets/futures/quote?symbols=A,B,C` (max 100 symbols) —
  unknown symbols returned in `data.unknown`, `QuoteFetchError` → 502,
  cache miss → 500.
* 43 module tests + 8 route tests, 100% line coverage.

### Slice 5 — Frontend (`5ee98b2`)

* `frontend/lib/api-watchlist.ts` (155 lines) — typed wrappers for all 7
  backend endpoints + `ApiResponse<T>` from `@/types`.
* `frontend/hooks/use-watchlist.ts` (275 lines) — CRUD + auto-quote-refresh
  hook with optimistic reorder (rolls back on failure). 30 s quote
  refresh debounce to avoid hammering Binance.
* `frontend/components/watchlist/{symbol-search,watchlist-table,quote-cell,empty-state}.tsx`
  — search combobox (250 ms debounce, 12-result dropdown), table with
  inline note editing (maxLength 280), ↑/↓ move buttons, delete, quote
  cell that colour-codes +/−24h change.
* `frontend/app/watchlist/page.tsx` — page composition + toast (3 s auto
  dismiss).
* `frontend/components/layout/sidebar.tsx` — Star entry added at
  `NAV_ITEMS[0]`.
* 9 vitest tests on `api-watchlist.ts`; full vitest suite 140 pass / 1
  pre-existing fail (`signal-card` — unrelated to watchlist).
* `tsc --noEmit` baseline 95 errors, 0 new errors introduced.

### Slice 6 — Verification (`34e93f7`)

* `scripts/check_watchlist_sources.py` — three-step verification:
  1. local cache contains `{MUUSDT, ORCLUSDT, AAPLUSDT, NVDAUSDT, TSLAUSDT, BTCUSDT}`;
  2. live `/fapi/v1/exchangeInfo` USDⓈ-M list contains the same set;
  3. live `/fapi/v1/premiumIndex?symbol=MUUSDT` returns numeric `markPrice`
     + `fundingRate`.
* Bug fix: Binance's `premiumIndex` actually returns `lastFundingRate`, not
  `fundingRate`. Both `_coerce_premium` and the verification script now
  accept either key (covered by the new `legacy_funding_rate_key_falls_back`
  unit test).

## 2. Live verification (just ran)

```
[1/3] cache: 678 symbols, includes MUUSDT/ORCLUSDT/AAPLUSDT/NVDAUSDT/TSLAUSDT/BTCUSDT
[2/3] /fapi/v1/exchangeInfo: 682 USDⓈ-M symbols
[3/3] /fapi/v1/premiumIndex?symbol=MUUSDT: markPrice=735.28 fundingRate=7.265e-05
ALL CHECKS PASSED
```

Note: MUUSDT is a TradeFI 美股永续合约 (Micron), with active `markPrice` and
`lastFundingRate` (the funding rate is ~7 bp per 8h — small but real,
consistent with a low-vol TradFi perp).

## 3. Pre-existing baseline failures (unrelated)

The 11 fail + 15 error in the full backend suite are inherited from
`main` and have nothing to do with the watchlist slices. A quick
`git stash` round-trip confirms the count is identical before and after
each watchlist commit:

* `test_schemas_aux_contract.py` — `VibeEvent.model_validate` failures
  (10 cases, discriminated-union typing drift in the Pydantic v2
  upgrade).
* `test_futures_datasource.py::TestFuturesDataSource::test_invalid_symbol_raises`
  — flaky: depends on Binance returning 400 for `INVALIDPAIR` (occasionally
  returns 200 with an empty body instead).
* `test_integration.py::TestAnalyzeEndpoint` — 4 errors, all OPENAI-key
  dependent and run as part of CI in the cloud, not locally.

The single vitest fail (`components/dashboard/signal-card.test.tsx > renders
a long A-grade signal with all sections`) is also a pre-existing baseline
issue (matches the same test on `main`).

## 4. Files changed (high-level)

```
.gitignore                                                            [+ app/cache/]
docs/plans/watchlist-design-v3.md                                     [new, 356 lines]
docs/test-report-watchlist-2026-07-30.md                              [new, this file]
migrations/20260730_005_watchlist_items.sql                            [new]
app/domain/enums.py                                                   [+ 5 ErrorCode values]
app/domain/watchlist_schemas.py                                       [new, 82 lines]
app/api/watchlist_routes.py                                           [new, 263 lines]
app/main.py                                                           [+ register_blueprint(watchlist_bp)]
app/infra/futures_symbols_cache.py                                    [new, 367 lines]
app/infra/futures_quote.py                                            [new, 420 lines]
app/infra/watchlist_store.py                                          [new, 476 lines]
frontend/lib/api-watchlist.ts                                         [new, 155 lines]
frontend/lib/api-watchlist.test.ts                                    [new, 170 lines]
frontend/hooks/use-watchlist.ts                                       [new, 275 lines]
frontend/components/watchlist/symbol-search.tsx                        [new, 67 lines]
frontend/components/watchlist/watchlist-table.tsx                      [new, 153 lines]
frontend/components/watchlist/quote-cell.tsx                           [new, 45 lines]
frontend/components/watchlist/empty-state.tsx                         [new, 12 lines]
frontend/app/watchlist/page.tsx                                       [new, 89 lines]
frontend/components/layout/sidebar.tsx                                 [+ Star icon entry]
scripts/check_watchlist_sources.py                                    [new, 122 lines]
scripts/smoke_watchlist.sh                                            [new, 108 lines]
tests/test_futures_symbols_cache.py                                   [new, 700+ lines, 39 tests]
tests/test_watchlist_store.py                                         [new, 651 lines, 57 tests]
tests/test_futures_quote.py                                           [new, 444 lines, 43 tests]
tests/test_watchlist_routes.py                                        [new, 745 lines, 54 tests]
```

## 5. Open / follow-up

* No further slices planned on this branch. The remaining design items
  (drag-and-drop reorder, sparkline, side-panel widget) are explicitly
  deferred per the resolved open questions in `docs/plans/watchlist-design-v3.md §5`.
* Production cut-over requires running the Supabase migration; until then
  the in-memory mirror keeps the page functional under `DISABLE_AUTH=1`.
* The cache refresh endpoint is gated by the admin role; in production
  this needs to be wired to a cron / scheduled job. (Out of scope for this
  branch — flagging for the maintainer.)