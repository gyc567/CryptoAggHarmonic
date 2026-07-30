# Watchlist Design v3 — Audited + Verified Binance TradeFI Source

> Status: design v3, post-audit. Ready for implementation.
> Audit pass: 2026-07-30, contract-dev + frontend-design dual perspective.
> Verified against `https://fapi.binance.com/fapi/v1/exchangeInfo` (851 USDⓈ-M symbols).

## 1. User requirements (recap)

1. Independent "自选币种 (Watchlist)" module — sidebar item **above 趋势RSI策略**.
2. Symbol search source **must be Binance US stock perpetual contracts** (TradeFI category).
   - User's own examples: `MUUSDT` (Micron), `ORCLUSDT` (Oracle).
3. Per-user persistence; **50-item cap**; one `note` field per item (≤280 chars); flat list, no groups.
4. Drag-to-reorder; **no sparkline** in v1; backend gateway for symbol search.

## 2. Verified data source (live curl evidence)

| `contractType`       | count | meaning                                            |
|----------------------|------:|----------------------------------------------------|
| `PERPETUAL`          | 697   | crypto perpetuals                                  |
| `TRADIFI_PERPETUAL`  | **150** | US stocks, commodities, KR/HK stocks, Pre-IPO     |
| `CURRENT_QUARTER`    | 2     | dated futures                                      |
| `NEXT_QUARTER`       | 2     | dated futures                                      |

**Confirmed MUUSDT / ORCLUSDT** exist with `contractType=TRADIFI_PERPETUAL`,
`underlyingType=EQUITY`, `underlyingSubType=["TradFi"]`, `quoteAsset=USDT`,
`marginAsset=USDT`, `status=TRADING`.

Live klines test:
- `GET /fapi/v1/klines?symbol=MUUSDT&interval=1h&limit=2` → 200, MU ~$735.

Reachability (CN host):
| URL                                                | Result                                  |
|----------------------------------------------------|-----------------------------------------|
| `https://fapi.binance.com/fapi/v1/exchangeInfo`    | ✅ 200 (Python urllib + webfetch). `curl` ❌ TCP-blocked |
| `https://api.binance.me/fapi/v1/exchangeInfo`      | ❌ 404 (api.binance.me is spot-only)    |
| `https://data-api.binance.vision/fapi/v1/exchangeInfo` | ❌ 404                              |
| `https://fapi.binance.us/fapi/v1/exchangeInfo`     | ❌ DNS NXDOMAIN                         |

Authoritative path: backend's `BINANCE_FUTURES_REST_URL` (defaults to
`https://fapi.binance.com`, already used by `app/infra/futures_data_source.py`).

## 3. Architecture (v3 — audit-improved)

```
   ┌───────────────┐         ┌─────────────────────┐         ┌──────────────────────┐
   │  Next.js page │  fetch  │  Flask blueprint    │  fetch  │  fapi.binance.com    │
   │  /watchlist   │ ──────► │  /api/watchlist/*   │ ──────► │  /fapi/v1/exchangeInfo│
   │               │         │  /api/markets/...   │         │  /fapi/v1/ticker/24hr │
   └───────────────┘         │                     │         │  /fapi/v1/premiumIndex│
                             │  + symbol-cache     │         └──────────────────────┘
                             │    (file + 7d TTL)  │
                             │  + Supabase adapter │
                             │  + in-memory fallback (DISABLE_AUTH)
                             └─────────────────────┘
```

### 3.1 Backend — `app/api/watchlist_routes.py`

| Method | Path                                  | Purpose                                                   |
|--------|---------------------------------------|-----------------------------------------------------------|
| GET    | `/api/markets/futures/symbols`        | Cached `exchangeInfo` filtered to `status=TRADING`, `quoteAsset=USDT`, optional `?q=` substring filter |
| GET    | `/api/markets/futures/quote`          | Batch quote (max 100 symbols), merged from `ticker/24hr` + `premiumIndex` |
| POST   | `/api/admin/markets/futures/refresh`  | Force-refresh the symbol cache (admin only)                |
| GET    | `/api/watchlist`                      | List current user's items (ordered by `sort_index` ASC, then `created_at` ASC) |
| POST   | `/api/watchlist`                      | Add symbol (≤50/user; **409 on duplicate**; **422 on 51st**) |
| POST   | `/api/watchlist/reorder`              | Bulk-update sort_index for an array of `{id, sort_index}`  |
| PATCH  | `/api/watchlist/:id`                  | Update note / single sort_index                            |
| DELETE | `/api/watchlist/:id`                  | Remove symbol                                              |

All endpoints go through `require_auth`. `DISABLE_AUTH=1` falls back to fixed
`local-dev-user`.

#### 3.1.1 Symbol cache — `app/infra/futures_symbols_cache.py`

- File-backed JSON at `app/cache/futures_symbols.json` (path configurable via
  `WATCHLIST_SYMBOLS_CACHE_PATH`, **gitignored**).
- Bootstrap: if file missing → fetch synchronously, write to disk, return.
- Steady-state: read from file; if mtime > 7 days → fetch in background
  (worker thread, `threading.Lock` to dedupe across gunicorn workers
  via advisory file lock), keep serving stale data meanwhile.
- Server-side filters applied **before** writing the cache (so the API serves
  a clean list, not a 1MB blob):
  ```python
  # pseudocode
  keep = (
      sym["status"] == "TRADING"
      and sym["quoteAsset"] == "USDT"
      and sym["contractType"] in ("PERPETUAL", "TRADIFI_PERPETUAL")
  )
  ```
- Cached schema per symbol (lean):
  ```jsonc
  {
    "symbol": "MUUSDT",
    "baseAsset": "MU",
    "quoteAsset": "USDT",
    "contractType": "TRADIFI_PERPETUAL",
    "underlyingType": "EQUITY",
    "underlyingSubTypes": ["TradFi"],
    "pricePrecision": 3,
    "quantityPrecision": 0,
    "onboardDate": 1716240000000,
    "isTradfi": true
  }
  ```

#### 3.1.2 Quote endpoint — `/api/markets/futures/quote`

- Accepts `?symbols=BTCUSDT,MUUSDT,...` (max 100; client should batch 80).
- Backend calls **two** fapi endpoints in parallel and merges:
  - `GET /fapi/v1/ticker/24hr?symbols=[...]` → `lastPrice`, `priceChangePercent`, `quoteVolume`
  - `GET /fapi/v1/premiumIndex?symbols=[...]` → `markPrice`, `fundingRate`, `nextFundingTime`
- Retry-with-backoff (0.5s / 1s / 2s) for 429/5xx (added to
  `app/infra/futures_data_source.py` as a shared helper).
- Response envelope:
  ```jsonc
  {
    "serverTime": 1785369616311,
    "quotes": [
      {
        "symbol": "MUUSDT",
        "lastPrice": "735.04",
        "markPrice": "735.06",
        "priceChangePercent": "1.42",
        "quoteVolume": "33363786.45",
        "fundingRate": "0.000100",
        "nextFundingTime": 1785374400000,
        "isTradfi": true,
        "status": "TRADING"
      }
    ]
  }
  ```
- Missing quote (delisted mid-session) → entry returns `status="DELISTED"`,
  `lastPrice=null`, frontend shows greyed-out row with badge.

#### 3.1.3 Validation rules (enforced at store layer)

| Rule                                        | Failure response                                |
|---------------------------------------------|--------------------------------------------------|
| Symbol not in cached whitelist              | 422 `INVALID_PARAMS` (code=WATCHLIST_UNKNOWN_SYMBOL) |
| User already has this `(market, symbol)`    | 409 `DUPLICATE_SYMBOL`                            |
| User already has 50 items                   | 422 `WATCHLIST_LIMIT_REACHED`                     |
| Note > 280 chars                            | 422 `INVALID_PARAMS`                              |
| Reorder: missing item from list             | 422 `INVALID_PARAMS`                              |
| `id` not owned by user (any op)             | 404 `NOT_FOUND`                                   |

#### 3.1.4 Persistence

**Production** (Supabase):
```sql
CREATE TABLE watchlist_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'futures',
    symbol TEXT NOT NULL,
    base_asset TEXT,
    quote_asset TEXT,
    contract_type TEXT,
    underlying_type TEXT,
    underlying_sub_types TEXT[] DEFAULT '{}',
    price_precision SMALLINT,
    quantity_precision SMALLINT,
    is_tradfi BOOLEAN DEFAULT false,
    note VARCHAR(280) NOT NULL DEFAULT '',
    sort_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, market, symbol)
);
```
Migration: `migrations/20260730_005_watchlist_items.sql`.
RLS: `FOR ALL USING (auth.uid() = user_id)`.

**Dev (`DISABLE_AUTH=1`)**: in-process store mirroring
`VibeSessionStore` — bounded `MemoryCache` keyed by user, single
process (fine for local dev only).

### 3.2 Frontend

- New page `frontend/app/watchlist/page.tsx` (Next.js app router).
- New sidebar item **at NAV_ITEMS[0]**:
  ```ts
  const NAV_ITEMS = [
    { href: "/watchlist", label: "自选币种", icon: Star },  // NEW
    { href: "/rsi-strategy", label: "趋势RSI策略", icon: TrendingUp },
    // ...rest unchanged
  ];
  ```
- New wrapper `frontend/lib/api-watchlist.ts` (mirrors `api-rsi-strategy.ts`).
- New hook `frontend/hooks/use-watchlist.ts`.
- New components in `frontend/components/watchlist/`:
  - `symbol-search.tsx` — combobox, debounced 200ms, ≤2 chars shows trending
    suggestion, ≥2 chars filters. Matches `symbol` + `baseAsset`
    (case-insensitive). Highlights matching substring. Groups results by
    `underlyingType` (美股 / 加密 / 港股 / 韩国股票 / 大宗 / 指数), 8 per group
    + "查看更多 N 条"展开。
  - `watchlist-table.tsx` — desktop table layout (≥768px).
  - `watchlist-card.tsx` — mobile card layout (<768px).
  - `reorder-controls.tsx` — up/down arrow buttons (keyboard a11y + mobile);
    HTML5 native drag-and-drop on desktop.
- `frontend/components/watchlist/quote-cell.tsx` — renders last price + 24h%
  using symbol's `pricePrecision`. Shows TradFi weekend hint badge.
- `frontend/components/watchlist/empty-state.tsx` — onboarding copy.

#### 3.2.1 Layout & states

| State             | UI                                                                    |
|-------------------|-----------------------------------------------------------------------|
| Empty             | "还没有自选，搜索 MUUSDT / AAPLUSDT / NVDAUSDT / BTCUSDT 添加第一个"  |
| Loading (initial) | 6-row skeleton                                                        |
| Search no match   | "没有匹配 '{q}' 的合约，试试 BTC / NVDA / XAU"                       |
| Stale data        | Footer: "数据于 HH:MM:SS 更新 · 每 30s 自动刷新"                      |
| Delisted symbol   | Row greyed out, badge "已下线", no price                              |
| 409 on dup add    | Toast: "{symbol} 已在自选中"                                          |
| 422 on 51st       | Toast: "自选最多 50 个，请先删除一些再添加"                          |

#### 3.2.2 Drag-to-reorder behavior

- Drag handle visible on row hover (desktop); arrow buttons always visible (mobile + a11y).
- During drag: pure local state, optimistic UI (rows swap immediately).
- On drop OR arrow click: single `POST /api/watchlist/reorder` with full
  `[{id, sort_index}]` array.
- On reorder failure: revert local state, toast "排序保存失败，请重试".

#### 3.2.3 Quote refresh

- `useEffect` runs `setInterval(refresh, 30000)`; pauses on
  `document.visibilitychange` (hidden tab → no refresh).
- On 429 / network error: exponential backoff 30s → 60s → 90s (cap), then
  resume normal cadence on next successful fetch.

### 3.3 Smoke verification plan

1. **`scripts/check_watchlist_sources.py`**:
   - Print cache stats: total symbols, breakdown by `contractType`,
     `underlyingType`.
   - Assert `MUUSDT`, `ORCLUSDT`, `AAPLUSDT`, `NVDAUSDT`, `TSLAUSDT`,
     `BTCUSDT` are in cache.
   - One `/fapi/v1/premiumIndex?symbol=MUUSDT` HTTP 200, capture
     `markPrice`, `fundingRate`, `nextFundingTime`.

2. **`scripts/smoke_watchlist.sh`** (curl):
   ```
   GET  /api/markets/futures/symbols?q=MU
   GET  /api/markets/futures/symbols?q=ORCL
   GET  /api/markets/futures/quote?symbols=MUUSDT,ORCLUSDT
   POST /api/watchlist  {symbol:"MUUSDT",...}
   GET  /api/watchlist
   POST /api/watchlist/reorder [{id,sort_index},...]
   PATCH /api/watchlist/{id} {note:"半导体周期反转"}
   DELETE /api/watchlist/{id}
   ```

3. **Vitest unit tests** (frontend):
   - Search filter: case-insensitive substring on `symbol` + `baseAsset`.
   - Grouping: results split by `underlyingType`, max 8 per group.
   - 50-item cap: 51st add → toast copy matches design.
   - Duplicate: 409 response → toast "{symbol} 已在自选中".
   - Reorder: arrow buttons update local state + fire PATCH.
   - Refresh: tab hidden → no fetch for 60s.
   - Delisted: null `lastPrice` → grey row + badge.

4. **Backend tests** (pytest):
   - `WatchlistStore.create_item` raises `LimitReachedError` at 51st.
   - `WatchlistStore.create_item` raises `DuplicateError` on second add.
   - `WatchlistStore.reorder` writes all items atomically.
   - `WatchlistStore` rejects unknown symbols against the cached whitelist.

5. **Browser smoke** (Playwright, optional): add `MUUSDT`, drag row 3 → 1,
   reload, verify order preserved.

6. **Baseline**: backend test suite stays at 131/132 (1 pre-existing
   `signal-card` failure is unrelated).

### 3.4 Files to create / change

```
migrations/20260730_005_watchlist_items.sql                        [new]
app/infra/futures_symbols_cache.py                                 [new]
app/infra/watchlist_store.py                                       [new]
app/api/watchlist_routes.py                                        [new]
app/main.py                                                        [+1 line: register bp]
app/infra/futures_data_source.py                                  [+ retry helper]

frontend/lib/api-watchlist.ts                                      [new]
frontend/hooks/use-watchlist.ts                                    [new]
frontend/app/watchlist/page.tsx                                    [new]
frontend/app/watchlist/loading.tsx                                 [new]
frontend/app/watchlist/error.tsx                                   [new]
frontend/components/watchlist/symbol-search.tsx                    [new]
frontend/components/watchlist/symbol-search.test.tsx               [new]
frontend/components/watchlist/watchlist-table.tsx                  [new]
frontend/components/watchlist/watchlist-card.tsx                   [new]
frontend/components/watchlist/reorder-controls.tsx                 [new]
frontend/components/watchlist/quote-cell.tsx                       [new]
frontend/components/watchlist/empty-state.tsx                      [new]
frontend/components/layout/sidebar.tsx                             [edit NAV_ITEMS[0]]

scripts/check_watchlist_sources.py                                 [new]
scripts/smoke_watchlist.sh                                         [new]
.gitignore                                                         [+ app/cache/]
```

## 4. Implementation order (commit-friendly slices)

1. **Backend skeleton + symbol cache** — `futures_symbols_cache.py`,
   `GET /api/markets/futures/symbols` end-to-end. Verify with curl.
2. **Persistence layer** — migration + `WatchlistStore` (Supabase +
   in-memory fallback). Pytest.
3. **Watchlist CRUD routes** — list/add/update/delete/reorder.
   `scripts/smoke_watchlist.sh` passes.
4. **Quote endpoint** — `GET /api/markets/futures/quote` with retry helper.
5. **Frontend page + sidebar entry** — page loads, empty state, search
   combobox wired to `/api/markets/futures/symbols`.
6. **Watchlist table/card + quote refresh + add/delete** — full CRUD UX.
7. **Reorder (drag + arrows) + ReorderControls** — full sort UX.
8. **Vitest + Playwright** — full coverage.
9. **Docs**: this file → commit; update `docs/session-handoff-2026-07-30.md`.

## 5. Open questions — RESOLVED (per user 2026-07-30)

| # | Question                                  | Decision                          |
|---|-------------------------------------------|-----------------------------------|
| 1 | Search scope                              | All USDT-m + chip filter (全部/美股/加密/港股/韩国/大宗/指数) |
| 2 | Non-USDT-m symbol                         | Reject 422                         |
| 3 | Sort behavior                             | Drag-to-reorder                   |
| 4 | Sparkline                                 | Skip v1                            |
| 5 | Backend gateway vs direct fapi            | Backend gateway                   |

## 6. Audit deltas from v2 → v3

| # | v2 had                            | v3 adds                                                                                          |
|---|-----------------------------------|--------------------------------------------------------------------------------------------------|
| 1 | (no status filter)                | Cache filters `status=TRADING`                                                                   |
| 2 | `lastPrice + priceChangePercent`  | + `markPrice`, `fundingRate`, `nextFundingTime`, `quoteVolume`, `serverTime`                      |
| 3 | (no TradFi weekend hint)          | `isTradfi` flag + frontend badge                                                                 |
| 4 | (no precision storage)            | `pricePrecision`, `quantityPrecision` columns + frontend formatter                                |
| 5 | (no sort_index policy)            | max+1 on add; bulk reorder endpoint; no compact on delete                                         |
| 6 | (unclear 50-cap enforcement)      | Store layer enforced, 422 with `WATCHLIST_LIMIT_REACHED`                                          |
| 7 | (silent duplicate)                | 409 `DUPLICATE_SYMBOL`                                                                           |
| 8 | `note TEXT`                       | `note VARCHAR(280)`                                                                              |
| 9 | (no empty state)                  | `empty-state.tsx` with example symbols                                                           |
|10 | (drag only)                       | + arrow buttons for touch + a11y                                                                  |
|11 | (assumed real-time PATCH)         | Optimistic local state + single batch reorder                                                    |
|12 | (no visibility/429 handling)      | `document.hidden` pause + exponential backoff                                                    |
|13 | (table only)                      | `<768px` switches to card layout                                                                  |
|14 | (flat search results)             | Grouped by underlyingType, 8/group + expand                                                       |
|15 | (no highlight)                    | Match substring highlighted in dropdown                                                          |
|16 | (no freshness indicator)          | Footer "数据于 HH:MM:SS 更新"                                                                    |
|17 | (unspecified cache path)          | `app/cache/futures_symbols.json`, gitignored                                                      |
|18 | (assumed cron)                    | mtime-based lazy refresh with `threading.Lock` + file advisory lock                              |
|19 | (no retry)                        | 0.5s/1s/2s backoff for 429/5xx                                                                   |
|20 | (no batch limit)                  | Max 100 per request, client batches 80                                                            |
|21 | (no timezone note)                | `nextFundingTime` epoch ms → browser local timezone                                               |
|22 | (no Next.js conventions)          | `metadata.title`, `loading.tsx`, `error.tsx`                                                      |