# Plan: OKX Agent Trade Kit 整合 — v2（经审计修订）

> 把 `github.com/dex-original/okx-agent-trade-kit`（101★ MIT，TypeScript，145 MCP tools / 11 modules）接入 cryptoagg loop-engineering，作为 freqtrade_dev_mcp 之上的**第二下游验证层 + 实盘执行层**。
>
> v2 — 经 `docs/plans/okx-agent-trade-kit-integration-audit-report.md` 二阶审计修订（应用 23 项修复：6 F + 12 M + 3 P + 5 D）。
>
> 用户已确认 8 个开放问题答案（见 §10），全部翻译为 ADR-0011 决策。

---

## 1. Context

### 1.1 上游现状

cryptoagg 当前 loop-engineering 已有 freqtrade（ADR-0010）这一**单一**下游验证层：

```
cryptoagg signal loop
    │  HarmonicSignal
    ▼
app/services/freqtrade/translator.py
    │
    ▼
freqtrade_dev_mcp (MIT, pinned commit, Python via MCP stdio)
    │  backtest_result
    ▼
app/loop/tuning_promotion.py gate
    │  human PR + SIGHUP
    ▼
TUNING 生效
```

freqtrade 是**回测级**验证（无实盘、paper 模式）。OKX 整合引入**实盘执行 + 多市场 + 多资产类型**能力，是与 freqtrade 互补的下游层。

### 1.2 目标项目 OKX Agent Trade Kit

| 维度 | 值 |
|---|---|
| 仓库 | `github.com/dex-original/okx-agent-trade-kit` |
| 协议 | MIT |
| 规模 | 145 MCP tools / 11 modules |
| 语言 | TypeScript / ESM / Node.js >= 18 |
| 形态 | `okx-trade-mcp`（stdio JSON-RPC）+ `okx-trade-cli`（终端）|
| npm | `@okx_ai/okx-trade-mcp@1.0.4`（**v2 用户已确认锁 1.0.4 长期**）|
| Star / Fork | 101★ / 2298 forks |
| Auth | OK-ACCESS-* 头 + ISO timestamp + HMAC-SHA256 + **passphrase**（3 要素）|
| 安全机制 | `--read-only` flag、per-module filtering、client-side token bucket rate limiter |

### 1.3 关键差异 vs freqtrade

| 维度 | freqtrade | OKX Agent Trade Kit |
|---|---|---|
| 语言 | Python | TypeScript |
| 形态 | pin 到 commit + import 翻译层 | npm 全局 + 薄 Python 客户端（**v2 决策：不用 submodule**）|
| 角色 | 回测验证 | 行情 / paper 模拟盘 / 实盘（读 + 写）|
| 凭据 | exchange key/secret | OKX API key + secret + **passphrase**（3 要素）|
| 凭据源 | macOS Keychain `cryptoagg-freqtrade` | macOS Keychain `cryptoagg-okx`（**新增 service**，3 accounts）|
| 写操作 | 无（仅回测） | 有（spot 写 Phase 1，swap/futures/option 写后续 phase）|
| 风险等级 | L2（gate 拦截） | **L3+**（动真金，三重门）|
| upstream 治理 | pin commit SHA | 锁 npm 版本 `1.0.4` 长期 |
| audit log | 无 | **必填**（append-only，crash-safe outbox，10 字段 schema）|

### 1.4 整合价值

1. **行情补全**：当前 cryptoagg 行情走 `app/infra/marketdata.py` (Binance REST via curl_cffi)。OKX market 模块含 funding rate、OI、mark price — **secondary source**（v2 不替代 Binance）
2. **多账户支持**：cryptoagg 用户常同时持 OKX + Binance 账户
3. **可执行信号**：freqtrade 给"信号是否合理"，OKX 给"实盘能不能成交"
4. **智能资金信号**：`smartmoney` 模块（5 个 tool，read-only）— 链上大户共识信号（Phase 2）
5. **网格/DCA bot**：freqtrade 只能跑自己的策略；OKX 提供 exchange-native 网格/DCA

---

## 2. Goals

### 2.1 必做（Phase 0-4）

- [ ] Phase 0：基线测量入库（`[okx-baseline-01]`）+ ADR-0011 草案
- [ ] **凭据隔离**：OKX 三要素走 macOS Keychain `cryptoagg-okx` service（3 accounts）+ `scripts/okx/start_with_creds.sh`
- [ ] **包管理**：`scripts/okx/VERSION`（1 行 `1.0.4`，不新建 package.json）+ `scripts/okx/install.sh {install,verify}` 幂等
- [ ] **MCP 客户端薄封装**：`app/services/okx/mcp_client.py`（tool discovery + 1800s timeout + per-gen cap=3 + rate limit retry）
- [ ] **信号翻译层**：`app/services/okx/translator.py`（HarmonicSignal → OKX spot order params；**Phase 1 仅 spot**）
- [ ] **握手层**：`app/services/okx/handshake.py`（OKX fill → HISTORY.jsonl `source: okx_paper`）
- [ ] **数据源**：`app/services/okx/data_source.py`（read-only market 封装，**不动** `app/infra/marketdata.py`）
- [ ] **执行器**：`app/services/okx/executor.py`（写操作：gate 拦截 + audit log + clOrdId nonce）
- [ ] **审计**：`app/services/okx/audit.py`（10 字段 schema + outbox 模式 crash-safe）
- [ ] **三重门扩展**：`app/loop/tuning_promotion.py` 追加 `is_live_execution_tool()` + `execution_allowed_for_tools()` + checklist 加 audit log 强制项（**不修改**现有 3 API）
- [ ] **L3 红线**：写操作必须经三重门 — MCP 启动参数 `--read-only` + env `OKX_PAPER_MODE` + 运行时 `execution_allowed_for_tools()` 拦截
- [ ] **Loop #11 注册**：`docs/loop-state/OKX-LOOP.md` + `loop/loop_sync.py add-loop`
- [ ] **ADR-0011**：`docs/adr/0011-okx-agent-trade-kit-integration.md`（12 条 Decision）
- [ ] **gate.yaml** 加 OKX denylist + always_exclude（`app/services/okx/executor.py` + `**/okx-audit.log`）
- [ ] **5 场景回滚演练** + 5 测试 + **端到端双层**（mock 集成 + 真实 paper 脚本）
- [ ] **测试 100% 覆盖**（AGENTS.md 强制）

### 2.2 必不做（非目标 / 显式排除）

- ❌ **不**直接调用 OKX REST API（绕开 MCP）— 全部走 MCP server
- ❌ **不**用 OKX 写操作替换 TUNING（**写只走 paper 模式 + 三重门**）
- ❌ **不**把 OKX 数据源作为 cryptoagg analyze API 的默认 — 永远可选
- ❌ **不**改 `app/loop/` 既有 API（仅扩展）
- ❌ **不**改 `app/infra/marketdata.py`（Binance 主路径不变）
- ❌ **不**改 Supabase schema
- ❌ **不**支持 OKX 全部 145 tools — 只实现本计划选定的子集（见 §3.8）
- ❌ **不**引入 Python TS bridge — Node.js 与 Python 进程通过 MCP stdio
- ❌ **不**新建 `package.json`（**v2 修订**：异构 Python 仓库，1 文件 VERSION 即可）
- ❌ **不**做 swap / futures / option / earn / event 写操作（**v2 修订**：Phase 1 仅 spot paper，模块扩张后置）
- ❌ **不**自动重装 npm 全局包（`install.sh verify` 报错后**必须**人审）
- ❌ **不**自动 promote audit log rotate（90 天滚动是决策，待 §10 文档化）

---

## 3. 关键设计决策

### 3.1 决策 D1：OKX 写操作的三重门（**v2 修正边界**）

OKX 写操作涉及真金白银（与 freqtrade 的回测本质不同）。必须**三重门**才能下单：

```
OKX write request
    │
    ▼
[Gate 1: MCP 启动参数]  --modules market,account,spot --read-only
    │                    ↑ .claude/settings.json 静态配
    │                    ↑ Phase 1 仅 spot 写；swap/futures/option 写**禁用**（M8 决策）
    │
    ▼
[Gate 2: env]  OKX_PAPER_MODE=true             ← 默认 true（最严）
              OR OKX_ALLOW_LIVE=1 (显式 opt-in)
    │            ↑ 运行时切换（同一进程从 paper 升 live）
    │
    ▼
[Gate 3: code]  execution_allowed_for_tools()  ← 与 is_live_tuning_path 同模式但语义不同
              → 拒绝 spot_place_order 等写 tool
              → 写操作只能通过 executor.py（带 audit log）
              → audit log 走 outbox 模式（crash-safe）
    │
    ▼
[Gate 4: human] promotion_checklist() 全门：
              □ max_drawdown ≤ 2× baseline
              □ Calmar ratio ≥ 阈值
              □ Shadow mode ≥ 7 天
              □ salt_version traceable
              □ audit log 完整无缺口
              □ 每次实盘下单走 audit log 记录（不可删）
```

**v2 关键修正**：
- 三重门**外加** Phase 4 human checklist = **四门**
- Gate 1（启动参数）与 Gate 2（env）的关系：Gate 1 是**模块级**（决定哪些 tool 可用），Gate 2 是**模式级**（决定写操作是否真发到 OKX 服务器）
- Gate 3（运行时 tool gate）与 Gate 4（PR-level 路径 gate）**不混用**：
  - `is_live_tuning_path()` = PR review 路径检查（**不动**）
  - `is_live_execution_tool()` = runtime 写 tool 检查（**新增**，与前者解耦）
  - `promotion_checklist()` = human review（**扩展**，追加 audit 强制项）

### 3.2 决策 D2：包管理 = npm 全局安装 + 单文件 VERSION（**v2 修订**）

| 方案 | 优点 | 缺点 | 决策 |
|---|---|---|---|
| **A. npm 全局** | 占用最小；升级容易 | 多机部署需每机装；版本漂移 | ✅ 选 |
| B. git submodule | 跟 freqtrade 一致 | 异构 Python 仓库不友好 | ❌ |
| C. tarball vendored | 完全自包含 | 升级困难 | ❌ |
| D. pnpm workspace | monorepo 友好 | 与 Python 异构配置复杂 | ❌ |

**v2 落地**（**不新建** package.json）：
- `scripts/okx/install.sh`：
  - `install` 子命令：`npm i -g @okx_ai/okx-trade-mcp@1.0.4` + 写 `scripts/okx/VERSION`
  - `verify` 子命令：检查 `okx-trade-mcp --version == 1.0.4`，非破坏性，CI 用
- `scripts/okx/VERSION` 单文件 `1.0.4`（**不**提交 `package.json`，Python 仓库异构）
- `.claude/settings.json` 的 `mcpServers.okx` 段：
  - **Phase 1 default**：`"args": ["--modules", "market,account,spot", "--read-only"]`
  - **Phase 1 写启用**（仅 paper）：去掉 `--read-only` 并加 `"--demo"`
  - **实盘**：人审通过 checklist + `OKX_ALLOW_LIVE=1` 显式 opt-in
- 升级路径：写新 ADR 修订 ADR-0011 的 D-version-lock 节

### 3.3 决策 D3：凭据三层 = Keychain `cryptoagg-okx` service（**v2 修订：3 accounts**）

| Keychain service | accounts | 用途 |
|---|---|---|
| `cryptoagg-freqtrade` | exchange-key / exchange-secret / mcp-token | freqtrade 已有 |
| **`cryptoagg-okx`**（**新增**）| api-key / secret-key / passphrase | OKX 三要素 |
| `cryptoagg-supabase`（未来）| service-role-key | Supabase admin（若需要）|

**v2 修正**：
- ❌ **不**把 `paper-mode` 入 Keychain（是部署决策，env 变量）
- ✅ Keychain 3 accounts：`api-key` / `secret-key` / `passphrase`
- 启动期验证：`executor.py` 启动时调 `account_get_balance`，成功 = 三要素正确；失败 = 报错退出（**fail-fast，不 silent fallback**）

### 3.4 决策 D4：行情与 signal 翻译角色定位

cryptoagg 已有 Binance 行情路径 `app/infra/marketdata.py`。OKX 行情**不是**替代，是**补充**：

| 场景 | 用 Binance | 用 OKX |
|---|---|---|
| 主行情（cryptoagg analyze API） | ✅ | ❌（暂不接） |
| Funding rate（永续合约） | ❌（Binance 无） | ✅（swap 模块，Phase 2） |
| Open interest | ❌ | ✅ |
| Mark price | ❌ | ✅ |
| 跨交易所套利数据 | ❌ | ✅（paper 模式拿 OKX ticker） |
| Smart money 信号 | ❌ | ✅（Phase 2，read-only）|

**新文件**：`app/services/okx/data_source.py` 封装 OKX market 模块为只读数据源；**不动** `app/infra/marketdata.py`。

### 3.5 决策 D5：超严回滚条件（**v2 修订：5 场景对应 5 测试**）

| 失败场景 | 期望行为 | 测试 |
|---|---|---|
| 删除 `app/services/okx/` 全部 | loop doctor / pytest / gunicorn 全不崩 | `test_services_removed_graceful_skip` |
| Keychain 缺 `cryptoagg-okx` | 服务启动拒绝，**不是** silent fallback | `test_keychain_missing_refuses_startup` |
| MCP server 进程挂 | 30s 心跳超时 → `okx_health_down` 指标 +1 | `test_mcp_heartbeat_timeout` (mock) |
| npm 全局包被误删 | `scripts/okx/install.sh verify` 检测到 → 报错退出，**不自动重装** | `test_npm_package_missing_reports_no_autorepair` |
| passphrase 错 | `execution_allowed_for_tools()` 拦截 + audit log 记 "AUTH_FAIL" | `test_wrong_passphrase_does_not_leak_secret` |

5 个测试都跑在 `tests/services/okx/test_rollback_drill.py`，CI 收集。

### 3.6 决策 D6：写操作 audit log（**v2 修订：outbox 模式 + 10 字段 schema**）

OKX 所有写操作（不论 paper/live）必须留 audit trail。**v2 关键修正**：audit log **也走 outbox 模式**（与 HISTORY.jsonl 同），避免进程挂导致 audit 不完整。

**路径**：
```
.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl.outbox/{uuid}.json
    → atomic rename
    → .scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl
```

**10 字段 schema**（每次写 tool 调用必填）：

```json
{
  "ts": "2026-08-11T13:47:26.123456Z",
  "tool": "spot_place_order",
  "args": {"instId": "BTC-USDT", "side": "buy", ...},
  "result_code": "0",
  "result_body_hash": "sha256:...",
  "user": "loop#11",
  "salt_version": 3,
  "paper": true,
  "cl_ord_id": "OKX-LOOP-a1b2c3d4",
  "latency_ms": 234,
  "trace_id": "abc123def456"
}
```

- 失败时 `result_code` = `"EXCEPTION"` + `error_stack` 字段
- 90 天滚动（v2 用户已确认；保留 90 天后**人工**归档，**不自动清**）

### 3.7 决策 D7：与 freqtrade 整合的关系

| 维度 | freqtrade (Loop #10) | OKX (Loop #11) |
|---|---|---|
| 角色 | 回测验证 | 实盘执行 + 行情补全 |
| TUNING 修改 | 是（hyperopt 反馈 TUNING） | **否**（OKX 写操作改交易所账户，**不直接**改 TUNING；audit log 事后分析用，**不**进 tuning snapshot）|
| 状态文件 | `.scratch/loop_state/freqtrade/` | `.scratch/loop_state/okx/` |
| promotion gate | `tuning_promotion.py` | `tuning_promotion.py`（**复用 + 扩展**，**不动**现有 API）|
| HISTORY source | `freqtrade_hyperopt` | `okx_live` / `okx_paper` |
| 风险等级 | L2 | **L3+**（写操作默认拒）|

**互斥锁**（**v2 修订：实现细节**）：
- `app/loop/state.append_history()` 检测同 `candidate_id` 是否同时含 `freqtrade_hyperopt` 和 `okx_*` source
- 若同时存在 → 抛 `SourceMutexError` 拒绝
- 测试：`tests/loop/test_append_history.py::test_source_mutex`

### 3.8 决策 D8：模块选择（**v2 修订：Phase 1 仅 market+account+spot paper**）

| Module | 工具数 | Phase | 理由 |
|---|---|---|---|
| market | 19 | **1** | 行情补全 + 70+ indicators（无需 auth）|
| account | 14 | **1** | 余额 / 仓位读取（启动期 passphrase 验证必用）|
| spot | 13 | **1**（**仅 paper**）| 主战场（最低风险）|
| swap | 17 | 2 | 永续合约 funding（Phase 2 启用写，Phase 1 仅 read-only 数据源）|
| smartmoney | 5 | 2 | 读 only，零风险可早做 |
| futures | 18 | ⏸️ 3 | 交割合约 |
| bot | 10 | ⏸️ 3 | grid/DCA |
| news | 7 | ⏸️ 3 | 情绪面 alpha |
| option | 10 | ❌ | 期权超出当前信号范畴 |
| earn | 23 | ❌ | 理财超出 harmonic 信号范畴 |
| event | 9 | ❌ | 事件合约是博彩式产品，不接 |

**Phase 1 必做**：market + account + **spot (paper only)**。
**Phase 2**：swap (read-only data source) + smartmoney + spot 升级到 `--read-only=false` 仍 paper。
**Phase 3**：bot / news（如需）。

---

## 4. Architecture

```
                     cryptoagg signal loop
                     (app/loop/ — 不变)
                            │
                            │  HarmonicSignal
                            ▼
              ┌──────────────────────────┐
              │  app/services/okx/         │
              │  translator.py            │ ← 复用 freqtrade translator 模式
              │  mcp_client.py            │ ← MCP stdio wrapper (timeout 1800s)
              │  handshake.py             │ ← OKX result → HISTORY.jsonl
              │  data_source.py           │ ← 只读行情封装（**不动** marketdata.py）
              │  executor.py              │ ← 写操作（**默认拒**）
              │  audit.py                 │ ← append-only + outbox 模式
              └────┬────────────────┬────┘
                   │                │
        read path  │                │  write path
                   ▼                ▼
        ┌────────────────┐   ┌────────────────────┐
        │ okx-trade-mcp   │   │ 三重门 (D1):         │
        │ --modules       │   │ 1. --read-only flag │
        │ market,account, │   │ 2. OKX_PAPER_MODE   │
        │ spot --read-only│   │ 3. execution_allowed│
        │   (Phase 1)     │   │   _for_tools()      │
        └────┬───────────┘   └────────┬───────────┘
             │ stdio JSON-RPC         │
             ▼                        ▼
        ┌──────────────────────────────────┐
        │   okx-trade-mcp (Node.js MCP)     │
        │   pinned: 1.0.4                  │
        │   profile: paper or live         │
        └────────────┬─────────────────────┘
                     │ HTTPS + HMAC-SHA256
                     ▼
        ┌──────────────────────────────────┐
        │     OKX REST API v5              │
        │     https://www.okx.com          │
        │     (paper: x-simulated-trading) │
        └──────────────────────────────────┘

        Promotion: app/loop/tuning_promotion.py
        (复用 + 扩展; 新增 is_live_execution_tool)
```

**v2 修订要点**：
- 三重门画完整（D1）
- spot 写仅 paper（Phase 1）；swap/futures 等写明确**不在 Phase 1 范围**
- executor.py + audit.py 走 outbox 模式（不是直接 append）

---

## 5. Phase 划分（**v2 修订：Phase 1 拆 1A + 1B**）

### Phase 0：基线 + 决策记录（0.5 周）

- [x] `.env.example` 加 OKX 4 字段占位（`OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` / `OKX_PAPER_MODE=true`）
- [x] `pip-audit` 当前 deps 无新漏洞（pip-audit 网络超时；改用本地依赖版本检查：flask 2.3.2 / gunicorn 20.1.0 / curl_cffi 0.15.0 / requests 2.32.5 / pydantic 2.13.4，supabase/yaml 未装是预期 503 根因）
- [x] **基线测量**（M1）：cryptoagg `/metrics` 当前 14 指标全数 0（fresh boot, gunicorn pid 26118）；loop_readiness_score=100
- [x] **基线测量**：Binance 主行情路径延迟 — `api.binance.com/api/v3/ping` 355ms, kline 1h limit=2 346ms（curl_cffi 生产路径）
- [x] 写入 `[okx-baseline-01]` 到 `docs/loop-state/durable-facts.md`
- [x] ADR-0011 草案（12 Decision 见 §10）→ **Accepted (Phase 0 闭环)**

### Phase 1A：依赖 + 凭据（0.25 周，~1-2 工作日）

**依赖治理**
- [x] `scripts/okx/install.sh install` — `npm i -g @okx_ai/okx-trade-mcp@1.0.4`（脚本就位；真装待用户提供凭据时跑）
- [x] `scripts/okx/install.sh verify` — `okx-trade-mcp --version == 1.0.4`（mock shim 验证 OK）
- [x] `scripts/okx/VERSION` — 单文件 `1.0.4`
- [ ] `npm audit` — 无 high/critical（真装后再跑）
- [x] Keychain 新条目：`cryptoagg-okx` service + 3 accounts（`api-key` / `secret-key` / `passphrase`）— **mock service 走通；真条目待 Phase 1B 凭据时建立**
- [x] `scripts/okx/start_with_creds.sh` — Keychain → chmod 600 config.toml（**复用 freqtrade 模式**，已 mock E2E 验证）
- [x] `start_with_creds.sh --rotate` flag（M2）— 已实现（overwrite config.toml）

**1A 验收**：
```bash
scripts/okx/install.sh verify               # 1.0.4 验证
scripts/okx/start_with_creds.sh --check      # 3 项 OK
okx-trade-mcp --modules market --read-only & # 启动 OK
```

### Phase 1B：gate 扩展 + skeleton + Loop #11（0.25 周，~1-2 工作日）

**tuning_promotion 扩展**
- [ ] `app/loop/tuning_promotion.py` 追加 `is_live_execution_tool()` + `execution_allowed_for_tools()`
- [ ] `promotion_checklist()` 追加 audit log 强制项
- [ ] **不修改**现有 3 API 签名

**模块选择 + skeleton**
- [ ] `.claude/settings.json` 的 mcpServers.okx 段（**default `--modules market,account,spot --read-only`**）
- [ ] 创建 `app/services/okx/__init__.py` + 5 个骨架文件
- [ ] `app/services/okx/executor.py` skeleton（**只**含三重门 + audit 写入 stub）
- [ ] `app/services/okx/audit.py` skeleton（outbox 模式）

**Loop #11 注册**
- [ ] `docs/loop-state/OKX-LOOP.md` 六维定义（沿用 FREQTRADE-LOOP.md 模板）
- [ ] `loop/loop_sync.py add-loop` 注册为 Loop #11

**1B 验收**：
```bash
pytest tests/services/okx/test_promotion_guard.py -k okx
python -m loop.loop doctor .          # 仍 100
python -m loop.loop gate check .      # 仍 OK
```

### Phase 2：实现 + 测试（1.5 周）

**翻译层实现**
- [x] `translator.py` — HarmonicSignal → OKX spot order params（**仅 spot**，3 模式：pattern/indicator/regime）
- [x] `mcp_client.py` — tool discovery + invocation + 1800s timeout + per-gen cap=3 + rate limit 50011 retry（M7）
- [x] `data_source.py` — read-only market data 封装（ticker/candles/funding_rate/open_interest/mark_price）
- [x] `executor.py` 完整 — write path + 三重门 (gate1/gate2/gate3) + audit 12 字段 + clOrdId nonce（M4）
- [x] `audit.py` 完整 — 12 字段 schema + outbox 模式 + sha256 body hash + 10 secret key redaction（F6）
- [x] `handshake.py` — OKX fill → HISTORY.jsonl (source: okx_paper / okx_live) + SourceMutexError propagation

**端到端 round-trip**
- [x] `.scratch/e2e/okx_e2e_demo.py` — HarmonicSignal → translator → mock MCP client → executor 三重门 → audit (12 字段) → handshake → HISTORY.jsonl；mutex 测试 (freqtrade_hyperopt vs okx_paper 同 candidate 拒) + promotion 测试 (okx_paper → okx_live 同 candidate 允许)。**不依赖真凭据、不依赖真 okx-trade-mcp subprocess**。

**测试覆盖（100%）**
- [ ] `test_translator.py`（HarmonicSignal → OKX order 往返）
- [ ] `test_mcp_client.py`（tool discovery + timeout + rate limit retry）
- [ ] `test_data_source.py`（market 工具只读封装）
- [ ] `test_executor.py`（三重门 + audit + clOrdId nonce）
- [ ] `test_audit.py`（10 字段 schema + outbox 模式 + crash-safe）
- [ ] `test_handshake.py`（OKX result → HISTORY.jsonl + outbox 恢复）
- [ ] `test_promotion_guard.py`（`is_live_execution_tool()` + `execution_allowed_for_tools()` + checklist 5 项）
- [ ] `test_rollback_drill.py`（5 场景回滚测试 — F1 + M10）

**Phase 2 验收**：
```bash
pytest tests/services/okx/ --cov=app/services/okx   # 100%
mypy app/services/okx/                              # 类型通过
```

### Phase 3：Loop 上线 + 端到端 + 回滚演练（1 周）

- [ ] `.github/workflows/okx-strategy-loop.yml`（L1 报告模式，**默认 L1 不写**）
- [ ] `loop_runner.py` — 读 tuning snapshot → spot paper order → audit → HISTORY.jsonl
- [ ] **端到端双层**（P2）：
  - **mock 集成**（CI 跑）：mock `mcp_client.invoke_tool()` 返回 fill 数据
  - **真实 paper 脚本**（本地手动）：`scripts/okx/e2e_paper.sh`（需 OKX paper 凭据）
- [ ] Gate violation：模拟 paper=false + ALLOW_LIVE=1 + 缺 checklist → 启动期拒绝
- [ ] **5 场景回滚演练**全过（见 §3.5）
- [ ] 凭据隔离：`grep -r "OKX_API_KEY\|OKX_SECRET\|OKX_PASSPHRASE" .` 必须空（除 .env，.env 已在 .gitignore）

### Phase 4：Paper + Backtest 对比 7 天（**v2 重命名，P3**）

- [ ] OKX **paper mode** vs freqtrade backtest 并行 7 天
- [ ] 收集对比：
  - OKX paper fill 数量 vs freqtrade backtest 成交数（绝对差，不是 ratio）
  - max drawdown 不超 baseline × 1.5
  - audit log 完整无缺口（100% 覆盖所有写 tool）
- [ ] 仅在 `paper_fill_count vs backtest_fill_count 偏差 < 10%` + `audit_complete=100%` + max_dd < 1.5×baseline 时允许申请实盘
- [ ] 实盘切换走 `promotion_checklist()` 全门 + `OKX_ALLOW_LIVE=1` 显式 opt-in
- [ ] **首笔实盘 limit 单 ≤ $10 USDT 等价**（**v2 用户已确认**）— 人工触发 + 截图 + durable-fact 记录

---

## 6. Files to Create / Modify

### Create

| File | Purpose | v2 修订 |
|---|---|---|
| `scripts/okx/VERSION` | 单文件 `1.0.4`（**v2 替代 package.json**）| 替代 `package.json` |
| `scripts/okx/install.sh` | `install` / `verify` 子命令 | 幂等 + verify 非破坏 |
| `scripts/okx/start_with_creds.sh` | Keychain → chmod 600 config.toml | 加 `--rotate` (M2) |
| `scripts/okx/e2e_paper.sh` | 真实 paper 端到端脚本（手动跑）| P2 修订 |
| `app/services/okx/__init__.py` | package 标记 | — |
| `app/services/okx/translator.py` | HarmonicSignal → OKX spot order params | **仅 spot** (M8) |
| `app/services/okx/mcp_client.py` | MCP stdio wrapper | per-gen cap=3 (M7) |
| `app/services/okx/handshake.py` | OKX fill → HISTORY.jsonl | — |
| `app/services/okx/data_source.py` | read-only market data | — |
| `app/services/okx/executor.py` | write path + 三重门 + clOrdId nonce | 拆分 stub + impl (D5) |
| `app/services/okx/audit.py` | 10 字段 schema + outbox 模式 | F6 修订 |
| `app/services/okx/loop_runner.py` | 跟 FREQTRADE-LOOP 同样模式 | — |
| `.github/workflows/okx-strategy-loop.yml` | Loop #11 workflow | **默认 L1** |
| `docs/loop-state/OKX-LOOP.md` | Loop #11 六维定义 | — |
| `docs/adr/0011-okx-agent-trade-kit-integration.md` | 12 Decision | M12 修订 |
| `tests/services/okx/test_translator.py` | 翻译往返 | — |
| `tests/services/okx/test_mcp_client.py` | MCP client + rate limit | M7 |
| `tests/services/okx/test_data_source.py` | read-only 封装 | — |
| `tests/services/okx/test_executor.py` | 三重门 + audit + nonce | M4 |
| `tests/services/okx/test_audit.py` | 10 字段 + outbox 模式 | F6 + M9 |
| `tests/services/okx/test_handshake.py` | OKX → HISTORY.jsonl | — |
| `tests/services/okx/test_promotion_guard.py` | tool gate + checklist 5 项 | F1 |
| `tests/services/okx/test_rollback_drill.py` | 5 场景回滚测试 | M10 + D5 |
| `tests/loop/test_append_history.py` | source mutex | M11 |

### Modify

| File | Change | v2 修订 |
|---|---|---|
| `app/loop/tuning_promotion.py` | **Extend**：追加 `is_live_execution_tool()` + `execution_allowed_for_tools()` + checklist 加 audit 强制项 | **不动现有 3 API** (F1 + F2) |
| `docs/loop-state/outerloop-protocol.md` | 新增 §8 OKX Handshake 节 | 替代 §4 ASCII 重复 (D3) |
| `docs/loop-state/durable-facts.md` | 加 `[okx-baseline-01]` + `[okx-e2e-01]` + `[okx-secret-rotate-NN]` | M1 + M2 |
| `docs/loop-state/STATE.md` | 高优先级加 OKX 整合条目 | — |
| `docs/loop-state/gate.yaml` | denylist + `"app/services/okx/executor.py"` + always_exclude `"**/okx-audit.log"` | M11 |
| `.claude/settings.json` | mcpServers.okx 段（default `--modules market,account,spot --read-only`） | — |
| `.env.example` | 加 OKX 4 字段占位 | — |
| `tests/loop/test_append_history.py`（如已存在）| 加 `test_source_mutex` | M11 |

### 不修改

- `app/loop/driver.py` / `search.py` / `pareto.py` / `state.py`（除 append_history 加 mutex 检查）
- `app/loop/maker_checker/`
- `app/services/freqtrade/`（独立）
- `app/infra/marketdata.py`（Binance 主路径不变）
- `app/config/tuning.py`（仅 human PR）
- `app/loop/tuning_promotion.py` 现有 3 个 API（`is_live_tuning_path` / `promotion_allowed_for_files` / `promotion_checklist` 现有签名）

---

## 7. Verification

### Phase 0
1. ADR-0011 写入并标 Accepted
2. `[okx-baseline-01]` 入 durable-facts.md
3. `python -m loop.loop doctor .` 仍 100

### Phase 1A
4. `okx-trade-mcp --version == 1.0.4`
5. Keychain `--check` 3 项 OK
6. `okx-trade-mcp --modules market,account,spot --read-only` 启动 OK

### Phase 1B
7. `pytest tests/services/okx/test_promotion_guard.py -k okx` — tool gate 拦截
8. `pytest tests/loop/test_append_history.py::test_source_mutex` — mutex 生效
9. `python -m loop.loop doctor .` 仍 100
10. `python -m loop.loop gate check .` 仍 OK
11. `python -m loop.loop sync check .` — LOOP.md 含 11 个 loop

### Phase 2
12. `pytest tests/services/okx/ --cov=app/services/okx` — 100% 覆盖
13. `mypy app/services/okx/` — 类型通过
14. `/metrics` 暴露 `okx_write_total{paper="true|false"}` + `okx_rate_limit_retry_total` + `okx_health_down`

### Phase 3
15. 端到端（mock 集成）：cryptoagg signal → OKX paper order mock → fill → HISTORY.jsonl round-trip
16. 端到端（真实 paper）：`scripts/okx/e2e_paper.sh` 跑通（手动 + 写 `docs/test-report-okx-paper.md`）
17. Gate violation：paper=false + ALLOW_LIVE=1 + checklist 缺一 → 启动期拒绝
18. 5 场景回滚演练全过（CI 收集）
19. 凭据隔离：`grep` .env 以外位置无 key/secret/passphrase

### Phase 4
20. Paper 7 天 `paper_fill_count vs backtest_fill_count 偏差 < 10%`
21. audit 完整 100%
22. max drawdown < 1.5×baseline
23. **首笔实盘 limit 单 ≤ $10 USDT 等价**（人工触发 + 截图 + `[okx-first-live-01]` durable-fact）

### 通用
24. `python -m loop.loop doctor .` 仍 100
25. `python -m loop.loop gate check .` 仍 OK
26. `python -m loop.loop sync check .` 仍 OK

---

## 8. 风险与回滚

| 风险 | 触发 | 回滚动作 | 决策 |
|---|---|---|---|
| OKX MCP server 进程挂 | heartbeat > 30s | 自动重启 + `okx_health_down` 告警 | — |
| npm upstream 改签名格式 | auth fail 突发 | 锁 1.0.4；不自动升 | M5 |
| 实盘爆仓 | audit log 检测到强平 | 立即 `is_live_execution_tool()` 加新阻断；写 `[okx-incident-NN]` | — |
| passphrase 错配 | 启动期 auth fail | 不进主流程；写 `[okx-auth-fail-NN]` 计数 | M6 |
| 凭据泄露 | 任何路径明文 | rotate + `git filter-repo` 清理 + 推 `[okx-secret-rotate-NN]` | M2 |
| `HISTORY.jsonl` outbox 堆积 | 进程挂 | 启动时 GC（freqtrade 已实施） | — |
| `audit/{date}.jsonl` outbox 堆积 | executor 进程挂 | 启动时 GC（复用 state.append_history 语义） | F6 |
| paper ≠ live 行为差异 | Phase 4 偏差 > 10% | 延长 shadow 至 14 天 | P3 |
| Phase 1 错误默认开 spot 写 | 配错 mcpServers | `.claude/settings.json` 强校验：`--read-only` 必填 | D1 |
| 与 freqtrade 同时改 TUNING | 两个 loop 并行 | `append_history` source mutex | D7 + M11 |
| npm 全局包被误删 | PATH 找不到 `okx-trade-mcp` | `install.sh verify` 报错；**不自动重装** | D2 + D5 |
| audit log 90 天滚动误清 | 自动清理逻辑写错 | **不**自动清；90 天后**人工**归档 | M2 用户确认 |

---

## 9. 与上游计划的引用

| 引用 | 用途 |
|---|---|
| `docs/loop-engineering-plan.md` §6 | Outerloop 协议基础（OKX 是 freqtrade 之上的第 2 个外层）|
| `docs/plans/freqtrade-mcp-integration.md` | 几乎所有 ADR-0010 决策都继承（路径隔离 / 状态文件位置 / crash-safe / Ponytail 排除）|
| ADR-0003 D9 | TUNING promotion gate（OKX 复用 + 扩展）|
| ADR-0003 D10 | `apply_tuning()` 竞态修复（OKX 不动 TUNING，规避）|
| ADR-0004 | Ponytail 排除区（`app/services/okx/` 属于业务层，执行）|
| `docs/loop-state/FREQTRADE-LOOP.md` | Loop #10 模板（六维定义直接复用结构）|
| `docs/plans/okx-agent-trade-kit-integration-audit-report.md` | v1 审计报告（23 项修复的来源）|

---

## 10. ADR-0011 决策草案（**v2 修订：12 条 = 8 用户答案 + 4 派生**）

| # | Decision | 来源 |
|---|---|---|
| **D1** | **包管理 = npm 全局安装 + `scripts/okx/VERSION` 单文件**（不新建 package.json）| 用户答案 1 (A) |
| **D2** | **Phase 1 0.5 周：先 0.5 周跑 market+account**，**spot paper 也并入 Phase 1**（用户答 3 后扩展为 market+account+spot paper）| 用户答案 3 |
| **D3** | **首笔实盘 limit 单 ≤ $10 USDT 等价**，人工触发 + 截图 + durable-fact 记录 | 用户答案 4 |
| **D4** | **npm 锁 1.0.4 长期**；升级路径需新 ADR（M5 派生）| 用户答案 5 |
| **D5** | **Phase 1 模块仅 market + account + spot (paper)**；swap/futures/option/earn/event/bot/news/smartmoney 后续 phase 启用 | 用户答案 6 |
| **D6** | **audit log 90 天滚动**（**不**自动清；90 天后人工归档）| 用户答案 7 |
| **D7** | **Keychain `cryptoagg-okx` service + 3 accounts**：`api-key` / `secret-key` / `passphrase`（**不**放 paper-mode）| 用户答案 8 |
| **D8** | **三重门**（MCP 启动参数 + env OKX_PAPER_MODE + 运行时 `execution_allowed_for_tools()`）+ **第四门 human checklist**（含 audit log 强制项）| F1 + F3 派生 |
| **D9** | **tuning_promotion 扩展不修改**：新增 `is_live_execution_tool()` + `execution_allowed_for_tools()`；现有 3 API 签名不变 | F1 + F2 派生 |
| **D10** | **写操作 audit log 走 outbox 模式**：复用 `app/loop/state.append_history` 的 outbox 语义 | F6 派生 |
| **D11** | **TUNING promotion 互斥锁**：同 `candidate_id` 不允许同时含 `freqtrade_hyperopt` 和 `okx_*` source | M11 派生 |
| **D12** | **PASS-THROUGH 凭据轮换**：`start_with_creds.sh --rotate` flag；90 天强制 rotate（与 D6 留存期一致）| M2 派生 |

---

## 11. 与 v1 的差异汇总

| 维度 | v1 | v2 |
|---|---|---|
| 决策数 | 8 | **12**（8 用户 + 4 派生）|
| 审计报告 | 无 | ✅ 17.5KB，23 项修复 |
| Phase 1 拆 1A/1B | 否 | ✅（用户答 0.5 周后必要）|
| 路径 gate vs 运行时 gate | 混用 | ✅ 拆 `is_live_tuning_path` vs `is_live_execution_tool` |
| audit log 模式 | 直接 append | ✅ outbox 模式（F6）|
| audit log schema | 6 字段 | ✅ 10 字段（M9）|
| Keychain accounts | 4（含 paper-mode）| ✅ 3（删 paper-mode，M6）|
| 启动期 passphrase 验证 | 否 | ✅ 调 `account_get_balance`（M6）|
| npm 包管理 | package.json | ✅ `scripts/okx/VERSION` 单文件（F5）|
| `install.sh verify` | 无 | ✅ 非破坏性检查（M3 + M5）|
| `--rotate` flag | 无 | ✅（M2）|
| clOrdId nonce | 无 | ✅ salt_version + uuid（M4）|
| per-gen cap | 5（freqtrade 同）| ✅ 3（OKX 写操作严于回测，M7）|
| rate limit retry | 无 | ✅ 5s 等待 + 单次重试（M7）|
| source mutex | 概念 | ✅ `append_history` 检测 + 测试（M11）|
| 端到端测试 | 单一 | ✅ 双层（mock + 真实 paper 脚本，P2）|
| Phase 4 命名 | "Shadow Mode" | ✅ "Paper + Backtest 对比 7 天"（P3）|
| Phase 4 验收指标 | diff ratio | ✅ 绝对差 < 10%（P3）|
| swap 写操作 | 列入 Phase 1 范围 | ✅ **显式排除**（M8）|
| 5 场景回滚 | 列但无测试 | ✅ 5 个 CI 收集测试（D5 + M10）|

---

_Last updated: 2026-08-11 (v2 — 经审计报告修订; 待 Phase 0 启动)_
