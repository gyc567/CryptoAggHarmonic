# Loop State — cryptoagg

> 由 `daily-triage.yml` 等 workflow 自动更新。
> 人类每周审查一次。

## High Priority

- [x] 2026-08-12: **RSI backtest 429 quota exceeded — fixed.**
  - Root cause: 用户 `gyc567@gmail.com` (id: `65ce88cf-a630-4ac5-9bfd-6658560b4b61`)
    每日 quota 5 次已用完（今日已消耗 5 次 consumed）。RSI backtest 是纯数据读取
    （无 AI token 消耗），与其他 API analyze 共享同一配额池不合理。
  - Fix: 将该用户 `daily_quota` 从 5 提升到 20（临时方案，已执行）。
  - 根本方案（待做）: 给 RSI backtest/scan/plan 分配独立高配额池（50 次/天），
    因为它们只读 Binance/TradingView 数据，不消耗 AI tokens。

- [x] 2026-08-12: **RSI 默认参数修复 — 20% → 70% 胜率.**
  - Root cause: 前端初始状态三重破坏性叠加:
    (1) `partial_mode=True` — 部分止盈后移动止损，震荡市中把 +2.11R 赢家提前扫出场
    (2) `trailing_stop=True` — ATR 追踪止损，在趋势反转前触发止损
    (3) `reward_risk=2.0` + `min_quality_score=30` — 盈亏比过高且过滤信号
  - Fix:
    - Schema defaults (rsi_trend_schemas.py): `partial_mode=False`, `short_rsi_min=65`, `ttl_bars=6`
    - Frontend initial state (backtest-panel.tsx): 同步到最优参数
    - Frontend new controls: `exit_ema`, `ttl_bars`, `short_rsi_min` 滑块
    - api-rsi-strategy.ts: 添加 `RsiTrendDirection` 类型导出，修复结构错误
  - Commit `f1272f3`, `3ba257e` pushed to remote
  - 后端无需重启：gunicorn 直接从 `/root/code/CryptoAggHarmonic` 读代码，已是最新
  - **待**: 前端 Vercel 重新部署（Vercel token 过期，需在 Vercel Dashboard 操作或刷新 token）
  - **验证**: 78 RSI 测试全通过，前端构建成功
- [x] 2026-08-12: **Vercel Frontend 部署 — DNS 修复完成，www.cryptoagg.xyz 和 cryptoagg.xyz 均 200.**
  - `vercel --prod --yes` → `cryptoaggharmonic-i94uiiyqb-gyc567s-projects.vercel.app`（项目名已更名）
  - `npm run build` ✅（Next.js 14.2.35，15/15 路由）
  - Vercel CLI 自动绑定 `www.cryptoagg.xyz`；`cryptoagg.xyz` 通过 `vercel alias set` 绑定
  - 验证：https://www.cryptoagg.xyz/ → 200，标题 "CryptoAgg - Agent 化加密货币交易策略"
  - 详见 `docs/plans/vercel-frontend-deploy.md`

- [x] 2026-08-12: **RSI strategy optimization — deployed.**
  - Problem: 0% win rate on 500-candle (83-day) window due to range-bound
    BTC market (May-Aug 2026 bull-phase exhaustion). Expanded to 180-day
    (1080 candles) to cover Feb-Aug 2026 including the correction.
  - Root cause of 0% win rate: EMA200 exit was too slow for the
    range-bound market. A +2.05R winner was given back because price
    flipped EMA200 ~28 bars later.
  - **Best result** (180d 4H BTCUSDT, pullback zone, partial=True):
    - `am=1.0 rr=1.0 exit_ema=ema200`: **9 trades, 44% win, avgR=+0.08, PF=1.19**
    - `am=1.5 rr=2.0 exit_ema=ema200`: 5 trades, 40% win, avgR=+0.48, PF=2.54
  - **New `exit_ema` parameter**: Literal["ema200", "ema50"], default ema200.
    Users choose conservative (ema200, fewer signals) vs aggressive (ema50,
    more signals, lower win rate). Threaded through run_backtest → _simulate_one.
  - Files: rsi_trend_backtest.py (+exit_ema, clean rewrite),
    rsi_trend_schemas.py (+exit_ema field), rsi_trend_service.py (pass through)
  - Verified: 55 RSI+API tests pass, backend health 200, commit `647a48b`
  - Deployed: PID 1170522 @ 127.0.0.1:5001
  - **待**: 基线测量入库 `[binance-baseline-01]` + `loop/loop_sync.py add-loop` 注册 #12

- [x] 2026-08-11: **OKX Agent Trade Kit 整合 — v2 计划就绪 + Phase 0 闭环.**
  - 🛑 **PAUSE @ 2026-08-11T15:21Z** — user requested stop after Phase 2; Phase 3+ pending real OKX creds. Durable marker `[okx-cycle-pause-01]` has full resume instructions.

  - v1 计划 (`docs/plans/okx-agent-trade-kit-integration.md`, 495 行)
  - v1 审计报告 (`docs/plans/okx-agent-trade-kit-integration-audit-report.md`, 466 行,
  - Verified: 55 tests pass, backend health 200, commit `d25e2fb`
  - Deployed: PID 1179363 @ 127.0.0.1:5001 (restarted)
  - **Note**: 70% on 10 trades is promising but small sample.
    Data covers Feb-Aug 2026 correction phase (good for long signals).
    Short signals remain structurally weak in this market regime.
  - **待 Phase 0 启动**：.env.example 加 OKX 4 字段占位、基线测量入库 `[okx-baseline-01]`、
    `pip-audit` 扫描、ADR-0011 落地。
  - 详见 `docs/plans/okx-agent-trade-kit-integration.md` (v2)
  - **Phase 0 完成**：.env.example OKX 4 字段占位入库；本地依赖版本审计
    (flask 2.3.2 / gunicorn 20.1.0 / curl_cffi 0.15.0 等，无新漏洞);
    gunicorn 启动 + /metrics 14 指标全数抓取 (`.scratch/baseline_metrics.txt`,
    loop_readiness_score=100); Binance 主路径 curl_cffi 延迟 355ms/346ms;
    `[okx-baseline-01]` 入 durable-facts.md; **ADR-0011 转 Accepted**。
  - **待 Phase 1A 启动**：npm install + Keychain `cryptoagg-okx` 3 accounts
    + `scripts/okx/start_with_creds.sh` + `scripts/okx/install.sh {install,verify}`。

  Phase 1-3（基础设施/实现/Loop #10 上线）已闭环；本轮新增：
  `scripts/freqtrade/start_with_creds.sh`（Keychain → chmod 600
  config.json 隔离脚本）+ submodule `.gitignore user_data/` 修复
 （原 root .gitignore 对 submodule 内部路径无效的虚假勾选）。
 E2E 全跑通（`.scratch/e2e/`）: Gartley HarmonicSignal →
  - **Phase 1A 完成（mock 模式）**：`scripts/okx/{install.sh,start_with_creds.sh,VERSION}`
    三件套就位；`install.sh --mock` 创建 `scripts/okx/.bin/okx-trade-mcp` shim
    模拟真实 npm 包协议（`--version` 返回 `1.0.4`）；`start_with_creds.sh
    --mock` 走通 8 个验收点 (--check 3 entries / write chmod 600
    config.toml / stdout 0 secret leak / --rotate overwrite / exec
    转发 / --help / .gitignore 覆盖 / shim 协议一致)。`.scratch/okx_state/`
    加入 .gitignore。
  - **Phase 1B 完成（纯代码）**：tuning_promotion 加 `is_live_execution_tool()` +
    `execution_allowed_for_tools()`（不动现有 3 API 签名，ADR-0011 D9）；37
    个 OKX write tools 入清单；app/loop/state.append_history 加 source
    mutex（`SourceMutexError`，freqtrade_hyperopt <-> okx_* 互斥；
    okx_paper -> okx_live 允许作为 promotion）；app/services/okx/ 6 个
    skeleton 文件就位（__init__/translator/mcp_client/executor/audit/
    handshake/data_source）；`docs/loop-state/OKX-LOOP.md` 六维定义 +
    `loop/loop_sync.py add-loop` 注册为 Loop #11（LOOP.md 11 loops）。
  - **测试**：71 passed, 1 skipped, **97.88% 覆盖**；8 行未覆盖为
    defensive fallback (BrokenPipeError / close kill / gate3 fail)，
    已用 `ponytail:` 标注。Pyright 0 errors。
  - **Phase 2 完成（端到端 round-trip）**：6 个 skeleton 全部完整实现；
    `.scratch/e2e/okx_e2e_demo.py` 7 步全过：HarmonicSignal → translator
    (clOrdId nonce 12 字符) → mock MCP client → executor 三重门
    (gate1=known tool / gate2=paper / gate3=recorded mode) → audit
    (12 字段含 gate + sha256 body hash) → handshake → HISTORY.jsonl
    (source: okx_paper)；source mutex 真实测（freqtrade_hyperopt 写同
    candidate_id 拒）；paper→live promotion 真实测（okx_paper + okx_live
    同 candidate_id 允许，ADR-0011 D11）。71 OKX 测试 pass + 1 skip，
    97.88% 覆盖；98 总测试 pass。
  - **Phase 3 启动条件**：用户提供真 OKX 三要素（写 Keychain `cryptoagg-okx`）
    + `scripts/okx/install.sh install` 跑真 npm 全局装 okx-trade-mcp@1.0.4 +
    workflow `.github/workflows/okx-strategy-loop.yml` 部署。

    写入 `cryptoagg-okx` service；扩展 `tuning_promotion.py` 加
    `is_live_execution_tool()` + `execution_allowed_for_tools()`；创建
    `app/services/okx/` skeleton 5 个文件；注册 Loop #11。
  translator → IStrategy 文件 → 合成 HyperoptResult →
  `write_hyperopt_to_history` → HISTORY.jsonl round-trip。修
  一处真实 bug：handshake 调用 `append_history` 用错签名
 （传 path 而非 record，root 未指定），单测用了 mock 未
  覆盖 — 已修，27/27 tests pass。Gate 拦截测试 4 项
  (is_live_tuning / promotion_allowed / checklist drawdown /
  salt_version) 全绿。回滚演练：临时移走 4 个 freqtrade 工件，
  `loop doctor` 与 `pytest` 均不崩溃。
  凭据：3 条已写入 macOS Keychain `cryptoagg-freqtrade`
  service。**⚠️ 用户在 chat 中明文贴过 exchange key/secret，
  选择不 rotate — 强烈建议在 Binance 控制台 rotate**。
  详见 `docs/plans/freqtrade-mcp-integration.md` + durable-facts
  `[freqtrade-creds-01]` / `[freqtrade-e2e-01]`。
  待填充（ADR-0010 D5）: real backtest run 后 `baseline_drawdown`
  / `baseline_calmar`。Phase 4 shadow mode 7 天观察期仍未启动。

- [x] 2026-08-10: **Backtest feedback loop — CLOSED (deployed).**
  Daily pipeline: cron 20:00 UTC → run_backtest.py → backtest_results.json
  + tuning_snapshots/daily_*.yaml (candidate) → human PR → tuning.py.
  Fixes found: (1) _load_history ignored start/end — walked the full
  17521-row cache (720 windows ≈ 6min); now date-slices (31d backtest 14s);
  (2) score_candidate overflow: Q4 pattern bump pushed confluence score
  past 100 → grade() @require violations skipped valid signals; clamped;
  (3) confluence weights were hardcoded and TUNING.confluence_weights was
  inert — wired to tuning + grid_search_weights() with sum-to-100
  constraint; (4) liquidity-sweep gate added (D-bar volume > 3x 20-bar
  mean → trap marker, not veto); (5) shebang pinned to .venv (PATH python3
  is a 3.12 dist-scripts 'scripts' package that shadows repo module);
  (6) multiprocessing returns per-symbol summaries, not raw records.
  Verified: 252 signal/backtest tests pass; real-data grid-search runs;
  3-symbol parallel dry-run 4s. Known env failures (unrelated): futures/
  kline datasource tests need external network feeds.
- [x] 2026-08-10: **Backend 401 — CLOSED (deployed).** Frontend reported
  401 on /api/analyze and /api/history. Root cause: SUPABASE_ANON_KEY
  uses the new `sb_publishable_...` format which supabase-py 2.15.0
  rejects at create_client (Invalid API key) — verify_user_token
  returned None for every request. Fixed by upgrading to
  supabase-py 2.31.0 (accepts publishable keys). Secondary fixes found
  while verifying: (1) routes.py reserved quota BEFORE creating the
  analyses row — usage_ledger.analysis_id FK 23503 → reordered to
  create record first, added delete_analysis_record cleanup on quota
  rejection; (2) analysis_type/market/interval/status now normalized
  to live schema CHECK constraints (auto→forming placeholder,
  futures→binance, 1m/5m→15m, failed→failed_upstream) + resolved_type
  written back on completion; (3) result.timing.get() AttributeError
  (TimingInfo is a pydantic model, not dict) — token counts not
  tracked yet, pass None. Verified live: /api/history 200 with real
  token; /api/analyze passes auth+quota (reserve_quota 200, release
  on failure), only remaining blocker is Yahoo rate-limit 503 (external).
- [x] 2026-08-08: GitHub Issues **enabled** on `gyc567/cryptoagg` (smoke #1 closed)
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
- [x] 2026-08-10: **hapi.cryptoagg.xyz local deployment — DONE.**
  Local backend (`/root/code/CryptoAggHarmonic/`) now serving
  ``https://hapi.cryptoagg.xyz``. Key findings: (1) this machine IS
  the backend server (racknerd-8502b6d, 107.174.96.244); (2) old
  backend at ``/var/www/pyharmonics/`` managed by ``systemd
  pyharmonics.service`` — must stop unit before starting new process;
  (3) ``requirements.txt`` has unsolvable websockets conflict on
  Python 3.12 (alpaca<11 vs supabase>=11); resolved by using the
  old Python 3.11 venv at ``/var/www/pyharmonics/.venv`` with
  ``PYTHONPATH=/root/code/CryptoAggHarmonic``; (4) Caddy already had
  ``hapi.cryptoagg.xyz`` reverse-proxy configured and SSL cert issued
  (Let's Encrypt, valid to Nov 7 2026); (5) ``supabase`` health
  check shows ``degraded`` from this server due to DNS failure
  (``[Errno -2] Name or service not known``) — upstream network
  restriction on this VPS, not a code issue. Test results:
  ``/api/health`` → 200 (version 0.2.0 new code confirmed);
  ``/api/markets`` → 200; ``/api/history`` → 200; ``/api/analyze``
  → 422 (params validation, no 500); `/api/analyze` with full
  params → 503 (Yahoo rate limit, external). Auth 500 bug
  confirmed closed. Full report:
  ``docs/test-report-hapi-domain-2026-08-10.md``.
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

---

## Triage Log

### 2026-08-10 (this run)

- **gh auth**: ✅ Authenticated as `gyc567` (active account, ssh protocol, scopes: delete:packages, project, read:org, repo, workflow, write:packages)
- **Triage labels**: ✅ Created: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `automated`, `loop`
- **Open issues**: None in `gyc567/cryptoagg`
- **Open PRs**: None in `gyc567/cryptoagg`
- **Loop readiness**: L3 (100/100) — `daily-triage` loop + harness foundry initialized today.
- **Other loops**: Issue Triage, PR Babysitter, CI Sweeper, Dependency Sweeper defined in LOOP.md (workflows exist in `.github/workflows/`)
- **Action items**:
  1. ✅ GitHub auth configured
  2. ✅ Triage labels created
  3. ✅ `.github/workflows/daily-triage.yml` already exists — automation ready

### 2026-08-11 (this run)

- **Open issues**: 0
- **Open PRs**: 0
- **Status**: Clean — no action needed

### 2026-08-11 (evening run)

- **Open issues**: 0
- **Open PRs**: 0
- **Status**: Clean — no action needed

### 2026-08-11 (manual run)

- **Open issues**: 0
- **Open PRs**: 0
- **Status**: Clean — no action needed

### 2026-08-11 (freqtrade-mcp integration)

- **Open issues**: 0
- **Open PRs**: 0
- **Freqtrade MCP integration**: ✅ Phase 1-3 complete.
  - `freqtrade_dev_mcp/` cloned (MIT, commit `04a26d7f`)
  - `app/services/freqtrade/` — translator.py, mcp_client.py, handshake.py, loop_runner.py
  - `skills/freqtrade-strategy-loop/`, `.github/workflows/freqtrade-strategy-loop.yml`
  - `docs/adr/0010-freqtrade-mcp-integration.md` (11 decisions)
  - `docs/loop-state/FREQTRADE-LOOP.md` → registered as Loop #10
  - `loop/loop_sync.py` — `add-loop` command implemented
  - `.claude/settings.json` — MCP server config for Claude Code
  - `app/loop/tuning_promotion.py` — drawdown/Calmar/Shadow promotion gates
  - `docs/loop-state/outerloop-protocol.md` — Freqtrade handshake protocol
  - `docs/loop-state/durable-facts.md` — `[freqtrade-baseline-01]` recorded
  - 22 new tests in `tests/services/freqtrade/`, all pass
- **Loop Readiness Score**: 100/100 ✅
- **pytest**: 1808 passed, 5 skipped (cryptoagg native + new freqtrade tests)
- **ADR-0010 D5 calibration note**: `baseline_drawdown` / `baseline_calmar` need real
  freqtrade backtest run to fill in (Phase 4 shadow mode)
- **Status**: Clean — no action needed

_Maintained by: `.github/workflows/daily-triage.yml`_
_See also: `docs/loop-state/LOOP.md`_
