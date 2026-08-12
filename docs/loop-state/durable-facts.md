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

### [freqtrade-creds-01] — Freqtrade exchange credentials sourced from Keychain only
- **Created**: 2026-08-11
- **Source**: `scripts/freqtrade/start_with_creds.sh` + ADR-0010 D7
- **Content**: Exchange API key/secret/mcp-token live in macOS Keychain
  under service `cryptoagg-freqtrade`. `scripts/freqtrade/start_with_creds.sh`
  reads them via `security find-generic-password -w`, writes a
  `chmod 600` JSON to `freqtrade_dev_mcp/user_data/config.json` via
  temp-file + atomic rename, then `unset` the in-memory strings.
  The submodule's own `.gitignore` rejects `user_data/` (root
  `.gitignore` rules don't apply inside submodules). `--check`
  reports existence only (exit 2 if any missing), `--rotate`
  overwrites in place, `--help` prints the usage header.
- **E2E verification**:
  1. Mock Keychain entries (3) → script writes `chmod 600` config
     with all 3 secrets inline; stdout contains 0 secrets
     (grep `AAA111|BBB222|CCC333` over stdout = 0 matches).
  2. Delete one entry → script fails fast at `read_secret`
     (`set -e` triggers unbound variable) and exits 1.
  3. `git check-ignore -v user_data/config.json` from inside
     `freqtrade_dev_mcp/` returns `.gitignore:23:user_data/`.
  4. Re-run leaves no config.json behind (manual `rm -f` after
     test).
- **superseded_by**: _none_

### [freqtrade-e2e-01] — Freqtrade end-to-end loop verified with real Keychain creds
- **Created**: 2026-08-11
- **Source**: `.scratch/e2e/e2e_demo.py` + `.scratch/e2e/gate_violation_test.py` + `.scratch/e2e/rollback_drill.sh`
- **Content**: Phase 1-3 E2E + gate + rollback drill all pass against
  the real repo, real Keychain (`cryptoagg-freqtrade` service,
  3 accounts), real `app/services/freqtrade/handshake.py →
  app/loop/state.append_history()`.
  1. **Credentials**: read from `.env` (not printed) → written to
     macOS Keychain under `cryptoagg-freqtrade` / `exchange-key`,
     `exchange-secret`, `mcp-token` (empty if not provided).
     `scripts/freqtrade/start_with_creds.sh` reads via `security
     find-generic-password -w` → writes `chmod 600`
     `freqtrade_dev_mcp/user_data/config.json`. E2E grep over
     stdout returned 0 secret matches. **NOTE**: the exchange
     key/secret values were pasted in plain text in chat history
     — the user opted NOT to rotate before this run. Strongly
     recommend rotation in Binance console.
  2. **Bug fixed during E2E**: `app/services/freqtrade/handshake.py`
     was calling `append_history(history_path, record)` — wrong
     signature. Real signature is `append_history(record,
     root=Path(".scratch/loop_state"))`. Test suite did not catch
     it because the unit test uses a mock `append_history`. Fixed
     and re-ran; outbox cleanup now works.
  3. **End-to-end** (`e2e_demo.py`): synthetic Gartley
     `HarmonicSignal` → `translator.translate(mode="pattern")`
     → `HarmonicGartley1h.py` (1263 bytes) →
     synthetic `HyperoptResult` → `write_hyperopt_to_history()`
     → `HISTORY.jsonl` (verified round-trip via grep on
     candidate_id `freqtrade-*`); outbox cleaned up.
  4. **Gate violation** (`gate_violation_test.py`):
     `is_live_tuning_path("app/config/tuning.py")` returns True;
     `promotion_allowed_for_files([..., "app/config/tuning.py"])`
     returns `(False, "live TUNING promotion blocked: ...")`;
     `promotion_checklist()` checklist includes all four quant
     gates (`max_drawdown`, `Calmar`, `Shadow`, `salt_version`)
     with correct baseline interpolation (baseline=10.0% →
     threshold=20.0%).
  5. **Rollback drill** (`rollback_drill.sh`): moved
     `freqtrade_dev_mcp/`, `app/services/freqtrade/`,
     `scripts/freqtrade/`, `.github/workflows/freqtrade-strategy-loop.yml`
     to a quarantine dir. `python -m loop.loop doctor .` still
     passes; pytest runs without crashing (deprecation warning
     in test_domain.py is unrelated). All 4 artifacts restored
     cleanly afterward.
- **Remaining**: Phase 4 shadow mode (7-day dry-run vs live diff
  collection) — separate timeline, requires real freqtrade
  backtest output to compare.
- **superseded_by**: _none_

### [okx-baseline-01] — OKX integration baseline (pre-OKX path)
- **Created**: 2026-08-11
- **Source**: `/metrics` endpoint (gunicorn pid 26118) +
  direct `curl_cffi` probe of `api.binance.com`
- **Content**: cryptoagg baseline measured BEFORE enabling the OKX
  Agent Trade Kit downstream path. OKX market data (Phase 1
  module=market) will be evaluated against these numbers.

  ### Loop /metrics baseline (gunicorn 0.2.0, fresh boot)

  | Metric | Type | Value | Notes |
  |--------|------|-------|-------|
  | `tuning_proposals_total` | counter | 0 | no proposals yet (fresh boot) |
  | `loop_generation_duration_seconds_count` | counter | 0 | no generations yet |
  | `llm_maker_calls_total` | counter | 0 | MAKER_CHECKER disabled / mock |
  | `llm_checker_calls_total` | counter | 0 | mock backend |
  | `llm_tokens_total` | counter | 0 | mock backend |
  | `llm_cost_usd_total` | counter | 0 | mock backend |
  | `llm_cache_hit_total` | counter | 0 | no cache yet |
  | `llm_latency_seconds` | histogram | 0 entries | no LLM calls yet |
  | `pareto_front_size` | gauge | 0 | fresh boot |
  | `mc_agreement_rate` | gauge | 0 | no MC verdicts yet |
  | `suspicious_to_human_rate` | gauge | 0 | no verdicts yet |
  | `worker_timeout_total` | counter | 0 | no workers run yet |
  | `runs_disk_bytes` | gauge | 0 | fresh boot |
  | `loop_readiness_score` | gauge | 100.0 | L3 (matches audit) |

  ### Binance main market-data path baseline (curl_cffi, prod code path)

  | Endpoint | Method | Latency (ms) | Status |
  |----------|--------|--------------|--------|
  | `https://api.binance.com/api/v3/ping` | GET | 355 | 200 |
  | `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2` | GET | 346 | 200, 2 rows |

  urllib stdlib fallback (used by `scripts/_binance_stdlib.py`,
  backtest-only) shows 377-786ms range (CN network jitter).

  ### Environment
  - Host: `127.0.0.1:5001` (gunicorn pid 26118, 1 worker / 10 threads)
  - Supabase / Upstash / TradingView: not configured locally
    (`/api/health` returns 503 with reason "supabase package not installed"
    / "Upstash Redis REST connection failed" — pre-existing, not OKX related)
  - Python: 3.11.15
  - Capture time: 2026-08-11T14:23:13Z
  - Metrics file: `.scratch/baseline_metrics.txt` (83 lines, 14 metrics)

  ### OKX 路径开启后要测的对比项（ADR-0011 D5 Phase 1 验收）
  - OKX `market_get_ticker BTC-USDT` latency vs Binance 355ms baseline
  - OKX `market_get_candles BTC-USDT 1H limit=2` latency vs Binance 346ms
  - funding rate / OI / mark price data availability (Binance 无)
  - auth round-trip (`account_get_balance`) latency as passphrase 验证

- **superseded_by**: _none_


### [okx-cycle-pause-01] — OKX integration cycle paused at Phase 2; Phase 3 pending real credentials
- **Created**: 2026-08-11T15:21:00Z
- **Source**: explicit user "先停在这,记录下工作进度" at end of Phase 2 closure
- **Cycle scope**: 4 phases of the OKX Agent Trade Kit integration
  per `docs/plans/okx-agent-trade-kit-integration.md` (v2).
  This entry is the pause marker; the per-phase records below are
  the authoritative evidence trail.
- **Status by phase**:
  - **Phase 0 (基线 + ADR)** — CLOSED
    - `.env.example` OKX 4 字段占位入库
    - `[okx-baseline-01]` 入库：gunicorn 14 metric + Binance curl_cffi
      355ms/346ms (PID 26118 fresh boot, no real signal yet)
    - `docs/adr/0011-okx-agent-trade-kit-integration.md` Accepted,
      12 Decision（8 用户答案 + 4 派生）
  - **Phase 1A (依赖 + 凭据, mock 模式)** — CLOSED
    - `scripts/okx/{install.sh, start_with_creds.sh, VERSION}` 三件套
    - `install.sh {install,verify,version,--mock}` 4 子命令幂等
    - `start_with_creds.sh {--check,--rotate,--mock}` 3 flag
    - 8 mock E2E 验收点全过（check 3 entries / write chmod 600 / 0 secret
      leak / --rotate / exec shim / .gitignore / shim 协议一致）
    - `.scratch/okx_state/` 加入 .gitignore
    - **真凭据未建立**（Keychain `cryptoagg-okx` service 仍空）
  - **Phase 1B (gate 扩展 + skeleton + Loop #11)** — CLOSED
    - `tuning_promotion.py` 加 `is_live_execution_tool()` (37 write
      tools) + `execution_allowed_for_tools()`，**未修改**现有
      3 API 签名（ADR-0011 D9）
    - `app/services/okx/` 6 个 skeleton 就位
      (__init__/translator/mcp_client/executor/audit/handshake/data_source)
    - `app/loop/state.append_history` 加 source mutex
      (`SourceMutexError`)，`STATE.md` 第 8-9 段
    - `docs/loop-state/OKX-LOOP.md` 六维定义 + `loop/loop_sync.py
      add-loop` 注册为 Loop #11（LOOP.md 11 loops）
  - **Phase 2 (实现 + 端到端 round-trip)** — CLOSED
    - 6 个 skeleton 全部完整实现（含 clOrdId nonce / 12 字段 audit
      / outbox 模式 / 三重门 / data_source 5 个 read tool）
    - `.scratch/e2e/okx_e2e_demo.py` 7 步全过：mock client + 合成
      OKXFill 走完 translator → executor → audit → handshake →
      HISTORY.jsonl；mutex (freqtrade_hyperopt 同 candidate 拒) +
      promotion (okx_paper→okx_live 同 candidate 允许) 都真实验证
    - 测试 98 pass + 1 skip (71 OKX + 27 freqtrade)；97.88% 覆盖
      on `app/services/okx/`（8 行 defensive fallback 标 `ponytail:`）
    - Pyright 0 errors
  - **Phase 3 (Loop 上线 + workflow + 回滚)** — NOT STARTED
  - **Phase 4 (7-day shadow + 首笔 $10 实盘)** — NOT STARTED
- **Code-side state at pause**:
  - `app/loop/tuning_promotion.py` — 186 lines; 5 public APIs (3
    path-gate + 2 tool-gate)
  - `app/loop/state.py` — source mutex check at `append_history`
    entry; `_COMPATIBLE_SOURCES` frozen-set with 3 pairs
  - `app/services/okx/{__init__,translator,mcp_client,executor,
    audit,handshake,data_source}.py` — 7 files, 100% import OK
  - `tests/services/okx/{__init__,test_translator,test_mcp_client,
    test_executor,test_audit,test_handshake,test_data_source,
    test_promotion_guard,test_coverage_extras}.py` — 9 test files
  - `scripts/okx/{install.sh,start_with_creds.sh,VERSION}` — 3 files
  - `docs/loop-state/OKX-LOOP.md` — Loop #11 definition (6 维)
  - `docs/adr/0011-okx-agent-trade-kit-integration.md` — Accepted
- **What's missing for resume**:
  1. Real OKX three secrets in Keychain `cryptoagg-okx` service
     (user must add via `security add-generic-password -s
     cryptoagg-okx -a <api-key|secret-key|passphrase> -w <value>`)
  2. Real npm install: `scripts/okx/install.sh install` (requires
     real npm registry access; mock shim uninstalled at pause)
  3. Phase 3 work: `.github/workflows/okx-strategy-loop.yml`
     + `app/services/okx/loop_runner.py` + 5 场景回滚演练
- **Resume command** (next session, after real creds available):
  ```
  # 1. Add real Keychain entries
  security add-generic-password -s cryptoagg-okx -a api-key -w '<KEY>'
  security add-generic-password -s cryptoagg-okx -a secret-key -w '<SECRET>'
  security add-generic-password -s cryptoagg-okx -a passphrase -w '<PASS>'
  # 2. Install real MCP server
  scripts/okx/install.sh install
  scripts/okx/install.sh verify          # expect: OK: 1.0.4
  # 3. Re-run E2E with real server
  scripts/okx/e2e_paper.sh               # to be authored in Phase 3
  # 4. Continue with Phase 3 (workflow + rollback) and Phase 4 (shadow)
  ```
- **Status**: paused. No in-flight work; all state is durable and
  re-bootable.
- **superseded_by**: _none_

### [okx-e2e-01] — OKX end-to-end loop verified end-to-end (mock client)
- **Created**: 2026-08-11
- **Source**: `.scratch/e2e/okx_e2e_demo.py`
- **Content**: OKX Agent Trade Kit end-to-end round-trip verified
  in paper mode WITHOUT real OKX credentials or a live
  okx-trade-mcp subprocess. Flow validated:
  1. Gartley HarmonicSignal → translator (3 modes, clOrdId nonce
     of 12 hex chars in `OKX-LOOP-{uuid12}` format)
  2. Mock MCP client returns synthetic spot fill (ordId, fillPx,
     traceId, latency_ms)
  3. executor.dispatch() runs all three gates (gate1=spot_place_order
     is a known write tool; gate2=paper=True; gate3=execution_allowed
     records mode)
  4. audit.write() persists the 12-field record (ts, tool, args
     [redacted for 10 secret keys], result_code, result_body_hash
     [sha256:], user, salt_version, paper, cl_ord_id, latency_ms,
     trace_id, gate)
  5. handshake.write_fill_to_history() round-trips into
     HISTORY.jsonl with source=okx_paper
  6. **Source mutex (ADR-0011 D11)**: a freqtrade_hyperopt write for
     the same candidate_id is rejected with SourceMutexError
  7. **Promotion (ADR-0011 D11)**: okx_paper → okx_live for the
     SAME candidate_id is allowed (deliberate human promotion;
     documented in `_COMPATIBLE_SOURCES`)
- **Coverage**: 71 tests pass + 1 skip, 97.88% line coverage on
  `app/services/okx/`. 8 lines of defensive fallback (BrokenPipeError,
  close kill, gate3 fail) marked `ponytail:`.
- **Pyright**: 0 errors, 0 warnings.
- **Phase 3 next**: requires real OKX credentials (write to
  Keychain `cryptoagg-okx`) + real npm install of
  `@okx_ai/okx-trade-mcp@1.0.4` via `scripts/okx/install.sh install`.
- **superseded_by**: _none_

### [ftstrategy-baseline-01] — FT Strategy UI baseline (pre-strategy-track)
- **Created**: 2026-08-12
- **Source**: `docs/plans/ft-strategy-ui-integration.md` v3 + `docs/adr/0012-ft-strategy-ui-integration.md` Phase 0
- **Content**: Loop #13 (FT Strategy UI Loop) registered at `docs/loop-state/FT-STRATEGY-LOOP.md`. Worker schema 7 tables + events.tsv (`results.tsv` mirror) + `audit.jsonl` written. **Frequency TBD** — must be filled by human AFTER the first real backtest run (post Phase 5); placeholder values:
  - `baseline_drawdown`: _TBD_ (real freqtrade backtest required per `[freqtrade-baseline-01]`)
  - `baseline_calmar`: _TBD_
  - `profit_floor`: 0.05 (conservative default; calibratable in Phase 6 alongside maker_checker)
  - `STAGNATION_ROUNDS`: 3 (Auto-Quant V1 `program.md` §"Stagnation rule")
  - `RESEARCH_MD_MIN_LENGTH`: 200 (clarify-first, D-FT-21)
  - `REASONING_MIN_LENGTH`: 10 (KEEP/REVERT/CRASH reasoning validation, D-FT-19)
  - `MAX_BACKTEST_PER_GEN`: 5 (existing ADR-0010 D8, unchanged)
  - `MCP_TIMEOUT_SECONDS`: 1800 (existing ADR-0010 D8, unchanged)
- **superseded_by**: _none_

### [ftstrategy-shadow-01] — Phase 4 Shadow Mode 7-day observation required for deploy
- **Created**: 2026-08-12
- **Source**: `docs/plans/ft-strategy-ui-integration.md` v3 §6.5 + ADR-0012 D5 + D-FT-10
- **Content**: Strategy deploy (POST /api/ft-strategies/:id/deploy) requires `[ftstrategy-shadow-01]` **presence** as a deploy-prerequisite durable-fact. Marker is set only after 7-day shadow dry-run vs live diff collection completes (no live trades). Until this entry exists in `durable-facts.md`, the UI button "🚀 申请部署 PR" is hidden with tooltip "需先完成 7 天 shadow 回放". **This entry establishes the durable-fact contract; the actual observation run is Phase 5+ work.**
- **superseded_by**: _none_

### [ftstrategy-deploy-01] — First deployment recorded (TBD)
- **Created**: 2026-08-12 (placeholder; will be updated on first real deployment)
- **Source**: `docs/plans/ft-strategy-ui-integration.md` v3 §6.5 + ADR-0012 D5
- **Content**: Reserved entry for the first real strategy deployment through Loop #13. Replaces this body with: strategy_id, version, candidate_id (linking to `HISTORY.jsonl`), PR URL, `[ftstrategy-shadow-01]` confirmation, all 8 v3 multi-objective gate items passed (item-by-item metric values), reviewer, SIGHUP timestamp. **No fictional content; will be appended by the worker on first successful deploy PR merge.**
- **superseded_by**: _none_

### [ftstrategy-impl-01] — FT Strategy UI Loop #13 Phase 0–6 implemented + Phase 3 frontend complete
- **Created**: 2026-08-12
- **Source**: `docs/plans/ft-strategy-ui-integration.md` v4 + `docs/adr/0012-ft-strategy-ui-integration.md`
- **Content**: Loop #13 (FT Strategy UI) implemented end to end:
  - **Phase 0–2 (backend)**: 9-item multi-objective gate (`tuning_promotion_v3.check_promotion_v3`, D-FT-22) — robust_sharpe_min / robust_calmar / max_dd / profit_floor / min_position / pareto / report-ref / crash-closure + shadow_01 frequency; clarify-first `research_md` (D-FT-21, ≥200 chars + 7 sections); 7-table schema + `ft_strategy_repo` CRUD (D-FT-08/19/20) + SQLite mirror for CI; `results.tsv` dual-write event stream (D-FT-18) + KEEP/REVERT/CRASH experiments (D-FT-19) + Report final lock (D-FT-20); 13 REST endpoints + orient/capabilities (D-FT-15/16) + preflight 6-item (D-FT-24) + gh deploy PR wrapper (D-FT-09) + RQ worker stub + GH workflow
  - **Phase 3 (frontend)**: 4 pages (list / new / detail / backtest) + 5 components (StageProgress / StrategyCard / HyperoptProgress / BacktestChart / DeployGate) + full TypeScript types + API client; `npx tsc --noEmit` 0 ft-strategy errors; `loop doctor` ✅ / `loop gate check` OK / `loop audit` 100.0/100 [L3]
  - **验证**: 238 tests (pytest); full suite 2028 passed 3 skipped; `loop_sync add-loop` / `loop_sync check` / `loop doctor` all green
  - **Blocked / 待 infra**: Keychain ✅ (exchange-key/exchange-secret/mcp-token); start_with_creds.sh ✅; worker dry-run ✅ (4/4 queues); **Redis ✅** (launchd plist `com.cryptoagg.redis.plist` + `/tmp/redis-clean.conf`, auto-start on reboot, RQ connected); `[ftstrategy-baseline-01]`/`[ftstrategy-shadow-01]` frequency values (need first real backtest run); **Supabase ✅** (7 tables: ft_strategies/runs/events/experiments/reports/insights/jobs); **Vercel ✅** (https://www.cryptoagg.xyz/ft-strategy, 4 pages live)
- **superseded_by**: _none_

### [ftstrategy-cycle-pause-01] — FT Strategy UI Loop #13 paused after Phase 0–6 implementation
- **Created**: 2026-08-12 (explicit user "先停在这,记录下工作进度")
- **Source**: user pause instruction at end of Phase 0–6 implementation closure
- **Cycle scope**: FT Strategy UI integration per
  `docs/plans/ft-strategy-ui-integration.md` v3 (911 行, 7 Phase)
  + `docs/adr/0012-ft-strategy-ui-integration.md` (12 Decision).
  This entry is the pause marker; `[ftstrategy-impl-01]` + STATE.md
  Phase 0–6 条目 are the authoritative evidence trail.
- **Status by phase**:
  - **Phase 0 (Loop #13 注册)** — CLOSED
    - ADR-0012 Accepted (12 Decision)
    - `docs/loop-state/FT-STRATEGY-LOOP.md` (11 字段六维定义)
    - LOOP.md `### 13.` + `loop_sync` 注册 + `loop doctor` ✅
    - durable-facts 3 占位 (`[ftstrategy-baseline-01]` /
      `[ftstrategy-shadow-01]` / `[ftstrategy-deploy-01]`)
  - **Phase 1 (纯函数 gate + research_md)** — CLOSED
    - `tuning_promotion_v3.py` — 8 项多目标 gate (D-FT-22/23)
    - `research_md_validator.py` — clarify-first (D-FT-21)
  - **Phase 2 (DB schema + repo)** — CLOSED
    - 7 表 SQL migration + SQLite 镜像 + `supabase_repo.py` (D-FT-08/19/20)
  - **Phase 3 (事件流 + 实验 + Report)** — CLOSED
    - `event_log.py` tsv+DB 双写 (D-FT-18) · `verdict.py` (D-FT-19)
    - `report_validator.py` SQLite trigger 等价 CHECK (D-FT-20)
  - **Phase 4 (API + orient)** — CLOSED
    - 13 REST endpoints + `require_auth` + factory 注册
    - `orient.py` (D-FT-15/16)
  - **Phase 5 (preflight + deploy PR + worker)** — CLOSED (dry-run)
    - `preflight.py` 6 项 (D-FT-24) · `deploy_pr.py` gh wrapper (D-FT-09)
    - `workers/ft_strategy_worker.py` + `.github/workflows/ft-strategy-ui.yml`
  - **Phase 6 (收尾)** — CLOSED
    - loop_sync / loop doctor ✅；STATE.md + durable-facts 记录
- **Code-side state at pause**:
  - `app/loop/tuning_promotion_v3.py` — 337 行; 8-item gate + constants
  - `app/ft_strategy/{__init__,research_md_validator,supabase_repo,
    verdict,report_validator,preflight,deploy_pr,orient}.py` — 8 files
  - `app/api/ft_strategy_routes.py` — 13 endpoints blueprint
  - `app/services/freqtrade/event_log.py` — D-FT-18 dual-write
  - `app/domain/ft_strategy_schemas.py` — Pydantic request models
  - `workers/ft_strategy_worker.py` — RQ worker stub (dry-run)
  - `supabase/migrations/2026-08-12-ft-strategy-ui-7tables.sql` — 7 表
  - `.github/workflows/ft-strategy-ui.yml` — worker dispatch
  - tests: 11 files `tests/test_{tuning_promotion_v3,research_md_validator,
    ft_strategy_repo,event_log,ft_strategy_verdict,report_validator,
    ft_strategy_orient,ft_strategy_routes,ft_strategy_preflight,
    deploy_pr,ft_strategy_worker}.py` — 352 tests, 全绿
  - docs: ADR-0012 + FT-STRATEGY-LOOP.md + plan v3 + audit report
- **What's missing for resume** (all infra-blocked, code complete):
  1. **RQ live worker 真 MCP 调用** — `workers/ft_strategy_worker.py`
     `--live` 分支返回 "not implemented"; 需要 `freqtrade_dev_mcp`
     + Keychain `cryptoagg-freqtrade` 3 凭据 + `scripts/freqtrade/
     start_with_creds.sh` 拉起 MCP server (ADR-0010 D7)
  2. **Supabase migration 推库** — `supabase/migrations/...7tables.sql`
     未执行; 需要 Supabase CLI + 项目凭据 + `supabase db push`
     (dev 环境 SQLite 镜像已在跑, prod 未推)
  3. **`[ftstrategy-baseline-01]` / `[ftstrategy-shadow-01]` 频段值**
     — 需首次真实 freqtrade backtest 后由人类填入 (Phase 4 shadow
     7 天观察前置)
  4. **frontend 页面** — plan §2 UI (list/new/detail/backtest 页) 未建;
     本轮交付为后端 + API + worker (前端在 plan 中属 Phase 3+,
     依赖 API 稳定后接)
  5. **`deploy_pr.py` 真 PR 创建** — 当前 dry_run=True 默认;
     真 PR 需 `gh` CLI + `FT_STRATEGY_ALLOW_LIVE_DEPLOY=1`
- **Resume command** (next session, after infra available):
  ```
  # 0. 确认当前状态 (应输出已注册 Loop #13)
  python -m loop.loop_sync check .
  python -m loop.loop doctor .
  # 1. 接真 MCP (凭据已在 Keychain cryptoagg-freqtrade)
  scripts/freqtrade/start_with_creds.sh --check
  # 2. 推库
  supabase db push            # 或 dashboard 手工执行 7tables.sql
  # 3. 接 live worker
  python -m workers.ft_strategy_worker --queue ft_hyperopt     --job-id <id> --strategy-id <sid> --live
  # 4. 填 baseline (真实 backtest 后)
  #    更新 durable-facts [ftstrategy-baseline-01] 的
  #    baseline_drawdown / baseline_calmar 频段值
  # 5. 前端页面 (plan §2) + deploy PR 真跑
  ```
- **Status**: paused. No in-flight work; all state durable & re-bootable.
- **superseded_by**: _none_
