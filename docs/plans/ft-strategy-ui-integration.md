# Plan: FT 策略中心 — 前端 UI + Loop Engineering 整合

> 将 `freqtrade_dev_mcp` + `FREQTRADE-LOOP.md`（Loop #10）已成熟的 L3 自动循环，包装成人类可观测、可干预、可触发的策略开发工作台。

> **v4 — 2026-08-12**，基于三阶审计修复：
> - P0-01: 新增 `FT-STRATEGY-LOOP.md` 六维定义（内联到 §10）
> - P0-02: ADR-0012 内联到 §11（25 条 D-FT 决策正式化）
> - P0-04: 新增 §15（阶段依赖 + 上游引用）
> - P1-01: Gate 数量统一为 9 项（原 §6.5 实际数量）
> - P1-02: `robust_sharpe_min` 阈值统一为 ≥ 0.0（promotion 目标 ≥ 1.0 显式分档）
> - P1-03: Auto-Quant 引用全部固定到 commit SHA
> - P1-04: `capabilities` 示例补全 `STAGNATION_ROUNDS`
> - P1-05: §8 改为 checklist 格式（标注存在状态）
> - P1-06: 编号统一（D-FT-25 TBD）
> - P2-02: `supabase/migrations/` 修正
> - 移除 "v2 audit report" 引用（v1/v2 审计报告单独保留）

> **v3 — 2026-08-12**，参考 Auto-Quant V1/V2 新增 7 项关键能力
> **v2 — 2026-08-12**，二阶审计（`ft-strategy-ui-integration-audit-report.md`）
> **v1 — 2026-08-12**，初稿

## Context

cryptoagg 是 harmonic pattern 信号 SaaS（Flask + Supabase + Upstash Redis，前端 Next.js 14 on Vercel）。
`freqtrade_dev_mcp` 已完成 Phase 1-3 整合（`app/services/freqtrade/{translator,mcp_client,handshake,loop_runner}.py` + Loop #10 + `tuning_promotion.promotion_checklist()`）。
用户当前无法直接观察和触发 freqtrade 策略的运行过程——循环在后台全自动执行，人类只能通过 `HISTORY.jsonl` 或 CI logs 查看结果。

**v4 重新校准的目标**：FT 策略中心不是简单地把 Loop #10 包一层壳。参考 [TraderAlice/Auto-Quant-V2](https://github.com/TraderAlice/Auto-Quant-V2/tree/v0.4.1) 的 Agent-native 工作台模型，本计划把策略工作台拆成四个持久化层次，让 LLM 与人类能并行迭代而不互相覆盖：

| 层次 | 角色 | 持久化 | 可变性 |
|------|------|--------|--------|
| **Strategy** | 一个意图（Idea → deploy） | `ft_strategies` | 命名空间 + version bump |
| **Run** | 一次不可变执行 | `ft_strategy_runs` | append-only；唯一 mutable: status/progress；`result` 字段写入后不可 UPDATE |
| **Cache** | 最新视图 | `ft_strategies.latest_result` | mutable summary，**不是** evidence |
| **Report** | 一次分析产出 | `ft_strategy_reports` | 草稿不可 deploy；Final = audit-grade |

三件套配套（Auto-Quant V2 §"The Agent-operable research loop"）：
1. **`results.tsv`**（gitignored，per-strategy）—— `commit | event | strategy_name | sharpe | max_dd | note`，事件类型 `create|evolve|stable|fork|kill`，survive `git reset --hard`
2. **KEEP/REVERT/CRASH 不可变实验**—— 每次 refine 记一次 KEEP/REVERT/CRASH verdict + reason 到 `ft_strategy_experiments` 表
3. **clarify-first 研究简报**—— 创建策略前强制走 `ft_strategies.research_md` 字段（英文 Markdown），调用方填意图 / 约束 / 失败模式，agent 才能动手生成代码

**不绕过**：Loop #10 握手协议、`tuning_promotion`、HISTORY.jsonl source mutex、Phase 4 shadow mode 7 天观察期、`durable-facts.md` append-only（AutoQuant V2 §Invariants 严格应用到本计划）。

## 与已有资产的关系

| 资产 | 状态 | 本计划动作 |
|------|------|-----------|
| `app/services/freqtrade/translator.py` | ✅ 已完成 | 不改动 |
| `app/services/freqtrade/mcp_client.py` | ✅ 已完成 | 复用，**不重写 async 路径** |
| `app/services/freqtrade/handshake.py` | ✅ 已完成 | **不引入新 `source` key**（D-FT-12） |
| `app/loop/tuning_promotion.py` | ✅ 已完成 | 不改动；UI 调用 `promotion_checklist()` |
| `freqtrade_dev_mcp/` | ✅ pin `04a26d7f` | 不改动 |
| `.github/workflows/freqtrade-strategy-loop.yml` | ✅ 已完成 | 不改动 |
| `docs/loop-state/FREQTRADE-LOOP.md` | ✅ Loop #10 | 不改动 |
| `app/loop/state.SourceMutexError` | ✅ `freqtrade_hyperopt` ↔ `okx_*` 互斥 | **新增 `ft_strategy_ui` 也纳入互斥矩阵**（D-FT-12） |
| `app/loop/` CMA-ES/Pareto/Maker-Checker | ✅ 已有 | **不改动**（Ponytail 排除区） |
| `outerloop-protocol.md` §handshake | ✅ | §4 复用为本计划握手协议顶层 |

---

## Goals

- [ ] **Phase 0** — Baseline + ADR-0012 + durable-facts 占位 + loop 文档骨架
- [ ] **Phase 1** — DB + API 骨架（**v4 修正**：events.tsv + reports + experiments 四表 + migrations 文件）
- [ ] **Phase 2** — RQ Worker + MCP 集成
- [ ] **Phase 3** — 前端页面（clarify-first brief 表单 + orient 摘要条）
- [ ] **Phase 4** — Promotion Gate UI + Deploy（多目标 9 项 gate + preflight）
- [ ] **Phase 5** — Loop #13 注册 + 入库
- [ ] **Phase 6** — Agent-native 增值：orient 端点 + capabilities 自描述 + KEEP/REVERT/CRASH 实验 + Audit-grade Report

---

## 0. v4 增量来源：Auto-Quant 经验映射（reference patterns，commit-pinned）

本计划 v3/v4 增量直接借鉴 Auto-Quant V1/V2。每条增量都在以下固定 commit 上有对应出处：

| Auto-Quant 出处 | 本计划落地 | 解决的问题 |
|---|---|---|
| V2 [`docs/ARCHITECTURE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/ARCHITECTURE.md) Project/Study/Session/Run/Report 五层 | **§4 Strategy/Run/Cache/Report 四表** | 平铺 `ft_strategies` 表的 result 覆盖历史 |
| V1 [`program.md@1a7cc56#L...`](https://github.com/TraderAlice/Auto-Quant/blob/1a7cc56/program.md) + `results.tsv` | **§4.4 `ft_results.tsv`** + Gitignore 规则 | agent 改一行导致结果崩了的回溯 |
| V1 [`program.md@1a7cc56` §"stagnation rule"] | **§1.5 Stagnation discipline** | 策略空转不收敛 |
| V1 [`program.md@1a7cc56` §"LLM decides keep/kill"] | **§3.5 Report endpoint 暴露 raw JSON** | UI 不能只看 summary 数字 |
| V1 [`program.md@1a7cc56` v0.4.1] `robust_sharpe = min(sharpe across timeranges)` + `profit_floor` + `pareto_dominated_by` | **§6.5 多目标 Promotion gate** | Sharpe 单标量被 Goodhart |
| V1 v0.4.1 per-pair reporting | **§3.5 BacktestReport 必含 per_pair** | 单标的遮蔽 portfolio DD 不对称 |
| V2 [`docs/OPERATOR_GUIDE.md@83f9d3a` `aq orient`] | **§3.4 `GET /api/ft-strategy/orient`** | UI 不知道"现在该做什么" |
| V2 [`docs/OPERATOR_GUIDE.md@83f9d3a` `aq capabilities --json`] | **§3.4 `GET /api/ft-strategy/capabilities`** | endpoint 必须硬编码 |
| V2 [`docs/OPERATOR_GUIDE.md@83f9d3a` "Clarify before quantifying"] | **§2.3 创建前必有 brief step** | plan-and-shoot 导致策略不符合原意 |
| V2 [`docs/OPERATOR_GUIDE.md@83f9d3a` §"Bounded feedback"] | **§6.6 Preflight Gate** | 30 min hyperopt 后才知列名错 |
| V2 [`docs/STATUS.md@83f9d3a` "honest boundary" 节] | **§16 Honest Boundary** | 营销文风格风险 |
| V2 [`docs/ARCHITECTURE.md@83f9d3a` §"Resumability"] + append-only reports | **§4.6 ft_strategy_reports** | 草稿与结论混存，结论丢失 |
| V2 [`docs/OPERATOR_GUIDE.md@83f9d3a` §"KEEP/REVERT/CRASH Experiments"] | **§4.5 ft_strategy_experiments** | refine 没有 trail 可查 |

---

## 1. 用户工作流（与 Loop #10 同源）

```
┌─────────────────────────────────────────────────────────────────┐
│                    FT 策略中心 — 用户视角                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  💡 Idea          用户描述策略思路（自然语言 / 参数模板）            │
│     │                                                        │
│     ▼                                                        │
│  🔧 Code         LLM 生成 IStrategy 文件（复用 Loop #10 翻译器） │
│     │            调用 `freqtrade_dev_mcp.create_strategy`        │
│     ▼                                                        │
│  ⚡ Hyperopt     后台 RQ worker 调 `hyperopt_strategy`            │
│     │            progress 写 Redis (TTL 7d)                       │
│     ▼                                                        │
│  📊 Backtest     后台 RQ worker 调 `backtest_strategy`            │
│     ▼                                                        │
│  🔍 Analyze      渲染 Win Rate / Sharpe / Drawdown / Calmar        │
│     │            checklist 由 `promotion_checklist()` 生成        │
│     ▼                                                        │
│  🔄 Refine       用户修改 → version+1 → 重跑 ⚡📊🔍               │
│     ▼                                                        │
│  🚀 Deploy       通过 PR 触发 → 人类审核 → SIGHUP → "deployed"   │
│                                                                   │
│  ───────────────────────────────────────────────────────────    │
│                                                                   │
│  🚧 强制门槛（不绕过）:                                            │
│     · 任何策略上线必经 `promotion_allowed_for_files()` 检查         │
│     · 必经 Phase 4 shadow mode 7 天观察（durable-facts 标记）     │
│     · 必经 SIGHUP 手工操作，不允许 in-app 上线                     │
│     · HISTORY.jsonl 新增 source=`ft_strategy_ui` 必须与现有      │
│       `freqtrade_hyperopt` 互斥（D-FT-12）                        │
└─────────────────────────────────────────────────────────────────┘
```

## 1.5. Stagnation Discipline + 事件流（Auto-Quant inspired）

Auto-Quant V1 `program.md@1a7cc56` §"Stagnation rule"："A strategy can't sit idle for more than 3 consecutive stable rounds — agent must evolve, fork, or kill it. With only 3 slots, dead weight is expensive."

本计划移植（参数化，不强制 3 槽）：

| 规则 | 默认值 | 落地 |
|------|--------|------|
| **Hard cap** 同 strategy 同 stage 同 version 同时只 1 个 run | 默认 yes | `ft_strategy_runs` 上加 partial unique idx `(strategy_id, version, stage)` WHERE `status IN ('queued','running')` |
| **Stagnation rule** | 3 轮 stable 必须 evolve / fork / kill；可配 | `ft_strategy_events` 计 `event='stable'` 连续计数；≥3 时 POST /:id/refine 强制要求 `event` 字段非空 |
| **Event log** | 必写 | `.scratch/loop_state/ft_strategy/{strategy_id}.tsv`，gitignored，列：commit \| event \| strategy_name \| sharpe \| max_dd \| note |
| **Event taxonomy** | `create\|evolve\|stable\|fork\|kill`（同 Auto-Quant） | UI action → event；worker 自动追加 stable |

### 1.6 事件流时序

```
用户点 [✏ 编辑参数]
       │
       ▼
UI → POST /api/ft-strategies/:id/refine
body: { params_delta, intended_event: "evolve" | "fork" | "kill" }
       │
       ▼
Refine Gate（v4 新）
├─ if stagnation >= 3 → 要求 intended_event 非空
├─ if intended_event == "fork" → 复制 strategy → 新 strategy_id（reasoning 字段要求填）
└─ if intended_event == "kill" → status='rejected', 不再 enqueue
       │
       ▼
version = current_version + 1（SQL 表达式）
enqueue ft_hyperopt + ft_backtest
       │
       ▼
worker 完成 → writer.run 落库 + append .tsv （event='evolve' 或 'stable'）
如果是 keep/revert/crash → 落 ft_strategy_experiments.verdict + reasoning
```

---

## 2. 前端 UI 设计

### 2.1 路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/ft-strategy` | 策略列表 | 用户所有策略的状态总览（轮询 30s） |
| `/ft-strategy/new` | 创建策略 | 💡 Idea 阶段 |
| `/ft-strategy/:id` | 策略详情 | 七阶段进度 + 最新结果（轮询 10s，job active 时） |
| `/ft-strategy/:id/backtest` | 回测报告 | 📊 Backtest + 🔍 Analyze 详情 |

> **D-FT-13**：Phase 3 取消 `/log` 独立页——`/ft-strategy/:id` 已含 stdout 折叠面板（hyperopt/backtest tail）。日志聚合是噪音来源，详情页足够。

### 2.2 策略列表页 `/ft-strategy`

```
┌──────────────────────────────────────────────────────┐
│ FT 策略                    [+ 新建策略]              │
├──────────────────────────────────────────────────────┤
│ 筛选: [全部▼]  排序: [更新时间▼]                     │
├──────────────────────────────────────────────────────┤
│  [Card] 我的RSI策略 v2                                │
│  💡→🔧→⚡→📊→🔍→🔄   状态: 📊 Backtest 完成           │
│  Win Rate 64% | Sharpe 1.94 | Drawdown 7.8%          │
│  更新 12m ago | [查看] [重新回测] [删除]              │
├──────────────────────────────────────────────────────┤
│  [Card] Bollinger 突破策略 v1                         │
│  💡→🔧→⚡→⏳   状态: ⚡ Hyperopt 23%                 │
│  创建 1d ago | [查看] [终止]                         │
└──────────────────────────────────────────────────────┘
```

### 2.3 创建策略页 `/ft-strategy/new`

```
┌──────────────────────────────────────────────────────┐
│ 💡 创建新 FT 策略                                      │
├──────────────────────────────────────────────────────┤
│                                                       │
│  策略名称   [___________________________]              │
│                                                       │
│  市场类型   [Binance Futures ▼]                        │
│  交易对    [BTC/USDT ▼]                                │
│  时间周期  [5m ▼]                                      │
│                                                       │
│  ── 策略思路 ──                                        │
│  ○ 模板策略   [RSI 均值回归 ▼]                          │
│  ○ 自然语言   [_____________________________]         │
│  ○ 从现有策略复制  [__ ▼]                              │
│                                                       │
│  ── 高级选项（折叠） ──                                 │
│  · hyperopt 时长（默认 30 min，必须 ≤ 1800s 上限）      │
│  · 最大候选数（默认 5，受 MAX_BACKTEST_PER_GEN 约束）    │
│  · 回测时间范围（默认近 90 天）                          │
│                                                       │
│                        [💡 生成策略 →]                │
└──────────────────────────────────────────────────────┘
```

> **D-FT-04**：高级选项的默认值来源于代码常量而非 UI 表单 hardcode。

### 2.4 策略详情页 `/ft-strategy/:id`

```
┌──────────────────────────────────────────────────────┐
│ ← 返回   我的RSI策略 v2            [▶ 继续] [✏ 编辑]  │
├──────────────────────────────────────────────────────┤
│  七阶段进度                                            │
│  💡 ──🔧 ──⚡ ──📊 ──🔍 ──🔄 ──🚀                    │
│  (done)(done)(active)(waiting)                        │
│                                                       │
│  ─── ⚡ Hyperopt 运行中 ───                            │
│  Elapsed 12m / 30m   Candidates 127 / 500              │
│  Best profit 8.2%   Best trades 342                   │
│  [██████████░░░░░░░░] 23%                            │
│  [日志展开▼]（折叠，保持详情页轻量）                   │
│                                                       │
│  ─── 📊 最新 Backtest 结果 v1.3 ───                    │
│  Win 64.2% | Sharpe 1.94 | DD 7.8% | Calmar 2.1       │
│  vs Baseline: DD ✅ (7.8% < 15.6%) | Calmar ✅         │
│                                                       │
│  [📊 查看详细报告]  [🔄 重新回测]  [🚀 申请部署 PR]    │
│                                                       │
└──────────────────────────────────────────────────────┘
```

> **D-FT-13**：`[🚀 申请部署 PR]` 不直接上线。点击后：(1) 服务端把 `promotion_checklist()` 渲染给前端；(2) 若全 ✅ → 创建 GitHub PR；(3) 状态置 `pending_review`，等人类合 PR → SIGHUP 后由 Loop #10 的 `Outerloop` 自动把策略状态置 `deployed`。

---

## 3. 后端 API 设计

### 3.1 REST Endpoints

| 方法 | 路径 | 说明 | Auth |
|------|------|------|------|
| `GET` | `/api/ft-strategies` | 列表（分页 + 筛选） | Supabase JWT |
| `POST` | `/api/ft-strategies` | 创建策略（💡 Idea）→ enqueue `ft_strategy_create` | Supabase JWT |
| `GET` | `/api/ft-strategies/:id` | 详情（七阶段状态 + 最近 run） | Supabase JWT |
| `DELETE` | `/api/ft-strategies/:id` | 删除策略（CASCADE `ft_strategy_runs`） | Supabase JWT |
| `GET` | `/api/ft-strategies/:id/jobs` | 后台 job 列表（含 progress） | Supabase JWT |
| `POST` | `/api/ft-strategies/:id/refine` | 提交修改 → version+1 → enqueue `ft_hyperopt` + `ft_backtest` | Supabase JWT |
| `GET` | `/api/ft-strategies/:id/backtest-report` | 最新回测报告数据（含 baseline 对比） | Supabase JWT |
| `POST` | `/api/ft-strategies/:id/deploy` | **仅创建 PR**：失败时返回 `promotion_checklist()` 字符串 | Supabase JWT |
| `GET` | `/api/ft-strategies/:id/history` | 完整运行历史（含 HISTORY.jsonl source=`ft_strategy_ui` 的子集） | Supabase JWT |

> **D-FT-01**：所有 endpoint 经 `require_auth` 装饰器（复用 `app/api/auth.py`），不重新发明鉴权。
> **D-FT-02**：`POST /:id/deploy` 服务端调用 `promotion_allowed_for_files()` 检查 PR diff 是否触碰 `app/config/tuning.py`，是则 422 拒绝（避免 UI 帮用户绕红线）。
> **D-FT-03**：路由注册 `app/api/routes.py` 末尾 `app.register_blueprint(ft_strategy_bp)`。

### 3.2 RQ 队列

```
队列名              │ 处理内容                   │ 并发度   │ 既有约束
───────────────────┼───────────────────────────┼─────────┼────────────
ft_strategy_create  │ 💡→🔧 Code 生成 → enqueue │ 1（per strategy）│ 调用 `MCP()` 1800s 上限
ft_hyperopt         │ ⚡ Hyperopt               │ 1        │ MAX_BACKTEST_PER_GEN=5
ft_backtest         │ 📊 Backtest               │ 2        │ MAX_BACKTEST_PER_GEN=5
ft_analyze          │ 🔍 Analyze + durable-facts│ 4        │ 同步 ≤ 30s
```

> **D-FT-05**：worker 不重写 mcp_client 的 1800s timeout 或 5-backtest cap；如需更长 → 改 `MCP_TIMEOUT_SECONDS` 常量并经 PR。
> **D-FT-06**：worker 调 `MCP()` 同步上下文，复用 `extract_backtest_data` / `extract_hyperopt_data`，不发明 asyncio.create_task 写法。

**Job 元数据**：Redis（TTL 7d）

```json
// Redis: ft_job:{job_id}
{
  "strategy_id": "uuid",
  "stage": "hyperopt",
  "status": "running",
  "progress_pct": 23,
  "candidates_evaluated": 127,
  "best_profit": 0.082,
  "started_at": "2026-08-12T...",
  "result_summary": {},
  "error": null,
  "source": "ft_strategy_ui"
}
```

### 3.3 触发流程（与 Loop #10 同源）

```
POST /api/ft-strategies
   │
   ▼
1. INSERT ft_strategies (status='draft', idea_source=..., idea_payload=...)
2. enqueue `ft_strategy_create` (TTL 7d)
   │
   ▼
3. RQ Worker: ft_strategy_create
   a. LLM 生成 IStrategy 文件（OpenAI，调 infra/llm_client）
   b. await FreqtradeMCPClient.create_strategy(...)
   c. UPDATE strategy_file_path + status='code_generated'
   d. enqueue `ft_hyperopt`
   │
   ▼
4. RQ Worker: ft_hyperopt
   a. MCP hyperopt_strategy(...)
   b. progress 写 Redis ft_job:{id}
   c. extract_hyperopt_data → parse_hyperopt_yaml → HyperoptResult
   d. handshake.write_hyperopt_to_history()  // D-FT-12 source mutex
   e. enqueue `ft_backtest`
   │
   ▼
5. RQ Worker: ft_backtest
   a. MCP backtest_strategy(...)
   b. extract_backtest_data → INSERT ft_strategy_runs (stage='backtest')
   c. enqueue `ft_analyze`
   │
   ▼
6. RQ Worker: ft_analyze
   a. 对比 baseline（[freqtrade-baseline-01]）/ 当前结果
   b. UPDATE ft_strategies.latest_result, status='analyzed'
   c. 前端轮询下一帧看到新状态
```

> **D-FT-12**：`handshake.write_hyperopt_to_history()` 当前 `source` 字段默认值是 `"freqtrade_hyperopt"`（`app/services/freqtrade/handshake.py:62`）。本计划**不修改**该默认值；UI 路径额外写入 `app/infra/ft_strategy_audit.py`，独立 append-only `.scratch/loop_state/ft_strategy/audit.jsonl`，**不污染 HISTORY.jsonl 互斥矩阵**。

### 3.4 Agent Orient + Capabilities 端点

参考 Auto-Quant V2 `aq orient` 与 `aq capabilities --json`（[`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md)）：

| 方法 | 路径 | 返回 | 用途 |
|------|------|------|------|
| `GET` | `/api/ft-strategy/capabilities` | `{ endpoints: [...], queue_names: [...], constants: {MCP_TIMEOUT_SECONDS:1800, MAX_BACKTEST_PER_GEN:5, STAGNATION_ROUNDS:3}, hard_limits: {strategies_hard_cap:null, max_hyperopt_minutes:30, max_backtest_per_gen:5} }` | UI 启动时拉一次，省 hardcode |
| `GET` | `/api/ft-strategy/orient` | `{ current_user_strategies: N, stagnation_hits: [{strategy_id,count}], blockers: [...], next_actions: [{strategy_id, action, reason, deadline?}], loop_health: {...} }` | Dashboard 顶部 banner；agent 扫描复用 |
| `GET` | `/api/ft-strategy/:id/orient` | `{ strategy_id, current_stage, last_run_id, stagnation_count, next_action: {type: "wait_backtest"|"refine"|"apply_deploy_pr"|"complete_shadow", reason}, hard_blockers: [...] }` | 详情页顶部"现在该做什么" |
| `GET` | `/api/ft-strategy/.scratch/tsv/:strategy_id` | raw TSV body | UI 提供下载；LLM agent 用 `cat` 拉历史 |

> **D-FT-15**：`orient` 不取代 normal endpoints；它只是元信息，never mutates。
> **D-FT-16**：`capabilities` 暴露的 `constants` 必须 **真值来自代码常量**，不允许从环境变量或 config 文件二次包装（避免 UI 看到一份、后端跑另一份）。

### 3.5 BacktestReport raw JSON 形态

Auto-Quant V1 v0.3.0+ per-pair reporting 必须在 report schema 里可读取，不能仅在 UI 上聚合。`GET /api/ft-strategies/:id/backtest-report` 返回：

```json
{
  "run_id": "uuid",
  "strategy_id": "uuid",
  "version": 3,
  "aggregate": {
    "sharpe": 1.94, "max_dd": 0.078, "calmar": 2.1,
    "win_rate": 0.642, "profit_pct": 0.123, "trades": 287,
    "robust_sharpe_min": 0.31
  },
  "per_pair": {
    "BTC/USDT": {"sharpe": 1.20, "max_dd": 0.05, "trades": 80, "profit_pct": 0.18},
    "ETH/USDT": {"sharpe": 0.85, "max_dd": 0.07, "trades": 70, "profit_pct": 0.11},
    "SOL/USDT": {"sharpe": -0.10,"max_dd": 0.15, "trades": 50, "profit_pct": -0.05},
    "BNB/USDT": {"sharpe": 1.50, "max_dd": 0.04, "trades": 47, "profit_pct": 0.20}
  },
  "per_timerange": {
    "bull_2021": {"sharpe": 2.1, "max_dd": 0.05},
    "winter_2022": {"sharpe": 0.31, "max_dd": 0.12},
    "recovery_2023": {"sharpe": 1.50, "max_dd": 0.08},
    "full_5y": {"sharpe": 1.94, "max_dd": 0.078}
  },
  "raw_blocks": "--- raw freqtrade stdout blocks per strategy ---\n...",
  "baseline_comparison": { ... },
  "promotion_checklist": [ ... promotion_checklist() 字符串 ... ]
}
```

> **D-FT-17**：UI 永远不"代理解读" raw_backtest；展示原始 num + agent 帮人类解读是后续 Phase 6+ 工作。Phase 1–5 UI 只画已有 aggregate + per_pair，其余 raw_blocks 存 JSONB，UI 提供"下载"按钮。

---

## 4. 数据库 Schema（Supabase）

> **D-FT-07**：DDL 走 `supabase/migrations/001_ft_strategies.sql`（Phase 1 创建）；不在 runtime 自动执行。

### 4.1 `ft_strategies` 表

```sql
CREATE TABLE ft_strategies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id),
  name TEXT NOT NULL,
  description TEXT,
  market_type TEXT DEFAULT 'futures' CHECK (market_type IN ('futures')),
  pair TEXT DEFAULT 'BTC/USDT',
  interval TEXT DEFAULT '5m',
  idea_source TEXT DEFAULT 'template' CHECK (idea_source IN ('template', 'natural_language', 'clone')),
  idea_payload JSONB NOT NULL,
  research_md TEXT,                          -- v4 新增：clarify-first brief（≥ 200 字符）
  last_event TEXT,                          -- v4 新增：mirror of last ft_strategy_events.event
  stagnation_count INT DEFAULT 0,           -- v4 新增
  status TEXT DEFAULT 'draft' CHECK (status IN (
    'draft', 'code_generated', 'hyperopt_running', 'backtest_running',
    'analyzed', 'refining', 'pending_review', 'deployed', 'rejected'
  )),
  current_version INT DEFAULT 1,
  strategy_file_path TEXT,
  latest_result JSONB,
  baseline_comparison JSONB,
  deployment_pr_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE ft_strategies ENABLE ROW LEVEL SECURITY;
CREATE POLICY ft_strategies_user_isolation ON ft_strategies
  FOR ALL TO authenticated
  USING (user_id = auth.uid());
```

### 4.2 `ft_strategy_runs` 表

```sql
CREATE TABLE ft_strategy_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT NOT NULL,
  stage TEXT NOT NULL CHECK (stage IN ('code','hyperopt','backtest','analyze')),
  job_id TEXT,
  status TEXT DEFAULT 'queued' CHECK (status IN ('queued','running','finished','failed','cancelled')),
  progress_pct INT DEFAULT 0,
  result JSONB,
  params JSONB,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  source TEXT DEFAULT 'ft_strategy_ui',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (strategy_id, version, stage)
);
```

### 4.3 `ft_strategy_insights` 表

```sql
CREATE TABLE ft_strategy_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  insight_type TEXT NOT NULL CHECK (insight_type IN (
    'baseline_drift', 'param_anomaly', 'shadow_signal',
    'cross_strategy_pattern', 'win_rate_outlier'
  )),
  content TEXT NOT NULL,
  evidence JSONB,
  confidence TEXT DEFAULT 'medium' CHECK (confidence IN ('low','medium','high')),
  durable_fact_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### 4.4 `ft_strategy_events` 表（`results.tsv` 持久层）

```sql
CREATE TABLE ft_strategy_events (
  id BIGSERIAL PRIMARY KEY,
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT,
  event TEXT NOT NULL CHECK (event IN ('create','evolve','stable','fork','kill','shadow_start','shadow_end')),
  sharpe NUMERIC,
  max_dd NUMERIC,
  note TEXT,
  recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ft_strategy_events_strategy_idx ON ft_strategy_events(strategy_id, recorded_at DESC);

-- 配套 gitignored 文件（worker 镜像）：
--   .scratch/loop_state/ft_strategy/{strategy_id}.tsv
-- header: commit | event | strategy_name | sharpe | max_dd | note
-- worker 在写表同时 append 这份 tsv（survives git reset --hard — AutoQuant V1）
```

> **D-FT-18**：event 入库与 .tsv append 是同一事务内的两次写入，失败回滚；不允许只写其一。

### 4.5 `ft_strategy_experiments` 表（KEEP/REVERT/CRASH）

```sql
CREATE TABLE ft_strategy_experiments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version_from INT NOT NULL,
  version_to INT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('keep','revert','crash')),
  reasoning TEXT NOT NULL,           -- 强制非空；agent / human 必须写原因
  metrics_delta JSONB,               -- {sharpe_from, sharpe_to, dd_from, dd_to, ...}
  decided_by UUID REFERENCES auth.users(id) NULL,  -- NULL = system decided (auto-KEEP 自动)
  recorded_at TIMESTAMPTZ DEFAULT now(),
  CHECK (version_to = version_from + 1)
);
```

> **D-FT-19**：`verdict='crash'` 时 worker 强制 status=`rejected` + 不进 next_action；UI 详情页把 crash 单独高亮（红色 banner），不允许"再试一次"按钮直接绕过。`reasoning` 字段禁止空白；空 → 422。

### 4.6 `ft_strategy_reports` 表（Audit-grade 产物）

```sql
CREATE TABLE ft_strategy_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT NOT NULL,
  authoring_state TEXT NOT NULL DEFAULT 'draft' CHECK (authoring_state IN ('draft','final')),
  reserved_finding TEXT,             -- scaffold 写入；final 时必被非占位文字替换
  report_json JSONB NOT NULL,        -- 不可变：final 状态后只能 read
  report_md TEXT,
  metrics_snapshot JSONB,
  baseline_snapshot JSONB,
  published_at TIMESTAMPTZ,          -- 写入"final"那一刻
  published_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  CHECK (
    (authoring_state = 'draft') OR
    (authoring_state = 'final' AND reserved_finding IS NOT NULL
     AND reserved_finding NOT LIKE 'TODO:%'
     AND published_at IS NOT NULL)
  )
);
```

> **D-FT-20**：final 状态的 Report 即 audit-grade；只允许创建新 draft，不允许 UPDATE final 行。Deploy checklist 必须显式引用某条 `report.id IN (authoring_state='final')`，否则 `POST /:id/deploy` → 422（不允许在 draft 上 deploy）。

---

## 5. 实时进度 — Polling-only（默认）

```
前端                                         后端
  │                                             │
  │  打开策略详情页                              │
  │───────────────────────────────────────────►│
  │  GET /api/ft-strategies/:id/jobs           │
  │◄──────────────────────────────────────────│
  │  初始化状态 + 当前 running jobs              │
  │                                             │
  │  ← 每 10s GET 同 endpoint（job active 时）   │
  │  ← 每 30s 一次（idle / 分析页面）            │
```

> **D-FT-11**：**默认轮询**。WebSocket 不在本计划范围。理由：
> 1. Vercel Serverless 不支持长连接。
> 2. 当前 backend 是 systemd-managed gunicorn + Vercel frontend；后端扩 WebSocket 路径需独立长连接网关。
> 3. 10s 轮询对 UX 可接受：hyperopt/backtest 长任务进度本就慢，肉眼看 10s vs 1s 差异不大。
> 后续如需要，**v4 不在计划内**：独立 `services/ft_strategy_ws/` 进程 + ws gateway，单独 Phase 7+ 提案（不在本计划范围）。

---

## 6. Promotion Gate — 申请部署 PR（不绕过 shadow mode）

```
用户点击「🚀 申请部署 PR」
       │
       ▼
POST /api/ft-strategies/:id/deploy
       │
       ▼
1. 加载 strategy + 最新 run
2. tuning_promotion.promotion_checklist_v3(...)
   ┌────────────────────────────────────────────────┐
   │ □ max_drawdown ≤ 2 × baseline_drawdown          │
   │ □ Calmar ratio ≥ 阈值                           │
   │ □ Shadow mode ≥ 7 天（由 [ftstrategy-shadow-01] │
   │   durable-fact 标记，无则 ✗ 并要求先做 shadow）  │
   │ □ salt_version 可追溯（source=freqtrade_hyperopt │
   │   在 HISTORY.jsonl 中找到）                     │
   │ □ hyperopt 结果已写 HISTORY.jsonl               │
   └────────────────────────────────────────────────┘
       │
   任一 ✗ → 422 + checklist 渲染 → UI 显示原因
   全部 ✓ → gh pr create（PR 模板带 tuning snapshot）
       │
   ▼
3. UPDATE ft_strategies SET status='pending_review', deployment_pr_url=...
4. 等人类合 PR → Loop #10 outerloop 检测 main 推送
5. CI 触发 SIGHUP → UPDATE ft_strategies status='deployed'
```

> **D-FT-09**：UI **不提供**一键上线。`POST /:id/deploy` 只创建 PR。
> **D-FT-10**：Phase 4 shadow mode 7 天观察期是 hard requirement。`[ftstrategy-shadow-01]` durable-fact 不存在 → UI 隐藏「申请部署 PR」按钮，tooltip 显示"需先完成 7 天 shadow 回放"。
> **D-FT-12**：UI 写入 `HISTORY.jsonl` 的 source key 走原值 `freqtrade_hyperopt`（worker 转译），不增加 `source: ft_strategy_ui`。AI Learning 走独立的 `ft_strategy_audit.jsonl`。

## 6.5 多目标 Promotion Gate（9 项 — Auto-Quant v0.4.1 移植）

v2 的 `promotion_checklist()` 单看 Sharpe / Drawdown。Auto-Quant V1 v0.1.0 历史案例：agent 自己识别并 retroactively discard 了 Sharpe-18 集群（ROI-clipping 压缩 return 方差但没改善真回报）。v4 拒绝把单一 Sharpe 数字当 deploy 唯一门槛。

v4 多目标 gate（在 `tuning_promotion.check_promotion_v3()` 内聚，UI checklist 渲染同样输出）：

```
promotion_checklist_v3(strategy_id) -> dict
  ┌── 全部必过 (any false → 422) ─────────────────┐
  │ □ robust_sharpe_min ≥ 0.0                     │
  │   min(per_timerange.sharpe) across {bull,     │
  │   winter, recovery, full_5y}                  │
  │   （promotion 目标 ≥ 1.0，在 UI 上标注为"目标"）│
  │ □ robust_calmar_min ≥ 1.0                     │
  │   min(per_timerange.calmar)                    │
  │ □ max_drawdown ≤ 2 × baseline_drawdown        │
  │ □ profit_floor pass                           │
  │   profit_pct ≥ 0.05 (5%)                      │
  │ □ min_position_size pass                      │
  │   trades >= 30（与 accepted floor 对齐）       │
  │ □ NOT pareto_dominated_by                     │
  │   当前策略在 (sharpe, calmar, max_dd, winrate) │
  │   4 维空间不被同一 user 的 prior KEEP 主导    │
  │ □ Shadow mode ≥ 7 天 [ftstrategy-shadow-01]   │
  │ □ Report referenced:                           │
  │   EXISTS (SELECT 1 FROM ft_strategy_reports    │
  │            WHERE strategy_id = ?               │
  │              AND authoring_state = 'final')    │
  │ □ No crash verdict 未解决                     │
  │   NOT EXISTS (SELECT 1 FROM ft_strategy_experiments │
  │               WHERE strategy_id = ? AND verdict='crash' │
  │                 AND decided_by IS NULL          │
  │                 AND recorded_at > NOW() - INTERVAL '7 days') │
  └─────────────────────────────────────────────────┘
```

**以上共 9 项**，任意一项 false → 422 + 明细。

| 维度 | Auto-Quant v0.4.1 出处 | 本计划取值 |
|------|------------------------|------------|
| `robust_sharpe_min` | `robust_sharpe = min(sharpe across timeranges)` | floor ≥ 0.0；promotion 目标 ≥ 1.0（UI 标注） |
| `robust_calmar_min` | min(per_timerange.calmar) | ≥ 1.0 |
| `profit_floor` | v0.4.1 ≥ 0 防 vol_target 退化 | ≥ 5% total profit_pct |
| `min_position_size` | v0.4.1 加（防策略不实际下单） | trades >= 30 |
| `pareto_dominated_by` | v0.4.1 多目标 oracle | 4 维主导检查（具体 metric + 权重放 Phase 6） |
| `report-referenced` | AutoQuant V2 §Operator Guide | deploy 前必须存在 final report |

> **D-FT-25 (TBD)**：4 维 Pareto 主导空间的具体 metric 集合与权重在 Phase 6 与 `maker_checker` 同步选定；本计划不预定唯一解。

> **D-FT-23**：所有 v4 新增 gate 项（除 shadow + report ref）必须以 `tuning_promotion.check_promotion_v3()` 的纯函数形式落地，UI / agent / CLI 复用同一函数；不在 routes.py 里写 if-else。

## 6.6 Preflight Gate（bounded feedback）

Auto-Quant V2 [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) §"Bounded feedback"："An Agent should not need a five-year backtest to learn that a column is missing, a path escaped, a factor looks ahead, or a candidate violated its editable closure."

v4 preflight（enqueue 前 worker 同步跑，错误直接 422，不进 RQ）：

| 检查 | 失败信号 | 修复路径 |
|------|----------|----------|
| 策略文件 AST 解析 + 必要方法 (populate_indicators / populate_entry_trend / populate_exit_trend) | missing_method | 编辑策略文件补方法 |
| 引用 indicator（`ta.RSI`, `ta.EMA`, ...）import 校验 | ImportError | 加 import 行 |
| `@informative` 装饰器引用 timeframe ∈ {1m,5m,15m,1h,4h,1d} | invalid_tf | 改 timeframe |
| 数据文件存在（pair × timeframe CSV 在 `user_data/data/`）| missing_data | 跑 `prepare.py` |
| 参数 key ∈ hyperopt spaces 集合 | param_unknown | 更新 hyperopt spaces |
| `research_md` 字数 ≥ 200 含必要 sections | research_too_short | 回到 `/new` 表单补 brief |

preflight 单独 endpoint `POST /api/ft-strategies/:id/preflight`，也内嵌到 worker 入口幂等检查。

---

## 7. 七阶段与 Loop Engineering 的对应

| 用户阶段 | Loop #10 已实现组件 | 本计划 UI 包装 |
|----------|----------------------|-----------------|
| 💡 Idea | `translator.translate(mode=...)` | `/ft-strategy/new` 表单 |
| 🔧 Code | `mcp_client.create_strategy` | worker `ft_strategy_create` |
| ⚡ Hyperopt | `mcp_client.hyperopt_strategy` | worker `ft_hyperopt`，前端轮询 progress |
| 📊 Backtest | `mcp_client.backtest_strategy` | worker `ft_backtest` |
| 🔍 Analyze | `tuning_promotion.promotion_checklist()` | `/ft-strategy/:id/backtest` |
| 🔄 Refine | refactor params → re-run | `POST /:id/refine` |
| 🚀 Deploy | `promotion_allowed_for_files` + GH PR + SIGHUP | `POST /:id/deploy` 创建 PR（不绕过 shadow） |
| 🧠 AI Learning | `durable-facts.md` + `episodic memory` | `insight_collector` 写 `.scratch/loop_state/ft_strategy/audit.jsonl` |

> **D-FT-14**：hygiene loop 接 MEMORY.md §每周 rhythm。`insight_collector` 触发 `append_durable_fact()` 走现有 MEMORY.md Episodic → Durable 路径，不直接写 `durable-facts.md`。

---

## 8. 文件结构（Phase 0 检查清单）

> **P1-05 修复**：每项标注实际存在状态。❌ = 未创建（Phase 0 尚未开始）；✅ = 已有资产；🆕 = 本计划新增。

```
app/
├── api/
│   ├── ft_strategy_routes.py          # 🆕 [NEW] REST endpoints（蓝图中规中矩）
│   └── routes.py                      # ⬜ [改 1 行] register_blueprint(ft_strategy_bp)
│
├── infra/
│   ├── supabase_client.py            # ✅ [不改]
│   └── ft_strategy_audit.py          # 🆕 [NEW] append-only .scratch/loop_state/ft_strategy/audit.jsonl
│
├── services/freqtrade/
│   ├── translator.py                 # ✅ [不改]
│   ├── mcp_client.py                 # ✅ [不改，复用 MCP() 上下文]
│   ├── handshake.py                  # ✅ [不改，复用 write_hyperopt_to_history]
│   ├── loop_runner.py                # ✅ [不改，由 RQ worker 复用]
│   ├── insight_collector.py          # 🆕 [NEW] durable-facts 触发器
│   └── job_dispatcher.py             # 🆕 [NEW] 薄 RQ 封装（仅 enqueue/update Redis）
│
├── ft_strategy/
│   ├── __init__.py                  # 🆕 [NEW]
│   ├── models.py                     # 🆕 [NEW] Pydantic models
│   ├── supabase_repo.py             # 🆕 [NEW] 薄 CRUD（直接走 supabase_client）
│   └── deploy_pr.py                  # 🆕 [NEW] gh CLI wrapper for PR creation
│
workers/
└── ft_strategy_worker.py             # 🆕 [NEW] RQ worker 入口

.github/workflows/
└── ft-strategy-ui.yml               # 🆕 [NEW] workflow_dispatch 拉起 worker

supabase/migrations/
└── 001_ft_strategies.sql            # 🆕 [NEW] DDL（v4 新增路径）

docs/
├── adr/
│   └── 0012-ft-strategy-ui-integration.md  # 🆕 [NEW] ADR-0012（D-FT-01..25 正式 ADR）
├── loop-state/
│   ├── FT-STRATEGY-LOOP.md         # 🆕 [NEW] Loop #13 六维定义（内联于 §10）
│   ├── LOOP.md                      # ⬜ [改] 增加 `### 13.` 一节（六维完整，非占位符）
│   └── durable-facts.md             # ⬜ [改] 加 `[ftstrategy-baseline-01]` / `[ftstrategy-shadow-01]` / `[ftstrategy-deploy-01]` 占位
├── plans/
│   └── ft-strategy-ui-integration.md         # 本文件 (v4)
└── references/
    └── ft-strategy-redlines.md      # 🆕 [NEW] 标注"必须 / 禁止"的人类 glance 清单

frontend/app/ft-strategy/
    ├── page.tsx                     # 🆕 [NEW] 列表
    ├── new/page.tsx                 # 🆕 [NEW] 创建
    └── [id]/
          ├── page.tsx              # 🆕 [NEW] 详情（含日志折叠面板）
          └── backtest/page.tsx      # 🆕 [NEW] 报告

frontend/components/ft-strategy/
    ├── StrategyCard.tsx            # 🆕 [NEW]
    ├── StageProgress.tsx           # 🆕 [NEW]
    ├── BacktestChart.tsx           # 🆕 [NEW]
    ├── HyperoptProgress.tsx         # 🆕 [NEW]
    └── DeployGate.tsx              # 🆕 [NEW] checklist 渲染

frontend/lib/
└── api-ft-strategy.ts              # 🆕 [NEW] 复用现有 fetch 模式
```

图例：✅ = 已有资产不改动；🆕 = 本计划新增；⬜ = 待修改（Phase 0 开始前不存在）

---

## 9. 实施路线图（v4 — 7 阶段）

| 阶段 | 内容 | 验收（一句话） |
|------|------|----------------|
| **Phase 0** | ADR-0012 + durable-facts 占位 + Loop #13 六维 + `supabase/migrations/001_ft_strategies.sql` | `docs/adr/0012-ft-strategy-ui-integration.md` 存在；`durable-facts.md` 有 3 条占位；`FT-STRATEGY-LOOP.md` 完整六维 |
| **Phase 1** | DB（7 表）+ API 骨架 | `supabase/migrations/001_ft_strategies.sql` 执行成功；`POST /api/ft-strategies` 必须带 `research_md`（≥ 200 字符，否则 422）；`ft_strategies` RLS 启用 |
| **Phase 2** | RQ worker + MCP 集成（4 队列 + preflight） | `ft_hyperopt` 跑至 `HISTORY.jsonl` 追加 `source=freqtrade_hyperopt`；同步落 `ft_strategy_events` |
| **Phase 3** | 前端页面（轮询 + brief 表单 + orient banner） | `/ft-strategy/new` brief ≥ 200 字符才能 submit；详情页顶部 "现在该做什么" 来自 `/orient` |
| **Phase 4** | 多目标 Promotion Gate UI + Preflight + Deploy PR | `check_promotion_v3()` 9 项 + Pre-flight 6 项；任一 ✗ → 422 含明细 |
| **Phase 5** | Loop #13 注册 + capabilities/orient 端点上线 | `python -m loop.loop_sync add-loop docs/loop-state/FT-STRATEGY-LOOP.md` 成功；`GET /api/ft-strategy/capabilities` 返回真值常量 |
| **Phase 6** | Agent-native 增值：KEEP/REVERT/CRASH 实验 + Report 最终态 + Stagnation discipline | `ft_strategy_experiments.verdict='crash'` 无 NULL `decided_by` 且 `reasoning` 非空；3 轮 stable 后 refine 强制带 event 字段 |

---

## 10. Loop #13 — FT Strategy UI Loop（六维完整定义）

> **P0-01/P0-05 修复**：完整六维定义内联于此，替代 LOOP.md §13 占位符。

```markdown
### 13. FT Strategy UI Loop

| 属性 | 值 | 说明 |
|---|---|---|
| **Cadence** | 用户 HTTP 请求触发 / RQ 后台 worker 串接 | 与 Loop #10 同 input 来源（但触发方式不同） |
| **Trigger** | Vercel 前端 POST + 用户点 [✏ 编辑] / [🚀 申请部署 PR] + GH Actions `workflow_dispatch` 拉起 worker | orient: `GET /api/ft-strategy/orient` 是伪 trigger |
| **Skill** | `ft-strategy-ui` | 见 `.github/workflows/ft-strategy-ui.yml` |
| **State** | Supabase 7 表（strategies / runs / events / experiments / reports / insights） + Redis ft_job TTL 7d + .scratch tsv + audit.jsonl | events / experiments / reports 是 v4 新增 |
| **Input** | 用户 brief + research_md + 可选 intended_event（evolve/fork/kill） | clarify-first |
| **Output** | IStrategy 文件 + HISTORY.jsonl source=freqtrade_hyperopt（worker 转译）+ audit.jsonl + PR URL + 最终态 report | 不直接生成 final Report；走 report draft → final endpoint |
| **Gate** | L2；Deploy 必须：多目标 9 项 v4 gate + final report ref + shadow 7 天 + 人类合 PR + SIGHUP | v4 多目标 gate 替换原单标量 |
| **Worktree** | 不使用 | 不修改 app/config/tuning.py |
| **MCP** | freqtrade_dev_mcp 12 tools，复用 Loop #10 既定协议 | 不重复调 OKX exchange MCP |
| **Orient** | GET /api/ft-strategy/orient 返回 next_actions | v4 新增 |
| **Capabilities** | GET /api/ft-strategy/capabilities 暴露真值常量 | v4 新增 |
```

注册后 LOOP.md §13 替换为以上内容。

---

## 11. 关键设计决策（v4 — 25 项，D-FT-01..25）

> **P0-02 修复**：ADR-0012 正式化。以下为 ADR-0012 决策全文。

| # | 决策 | 理由 | Auto-Quant 来源 |
|---|------|------|----------------|
| D-FT-01 | 所有 endpoint 经 `require_auth` | 复用 `app/api/auth.py`，KISS | — |
| D-FT-02 | `POST /:id/deploy` 仅创建 PR | UI 不能绕过 `promotion_allowed_for_files` | — |
| D-FT-03 | `app/api/routes.py` 末尾 register_blueprint 一行 | 不重写注册逻辑 | — |
| D-FT-04 | 高级选项默认值走代码常量，不硬编码到 UI | AGENTS.md §执行风格 | — |
| D-FT-05 | worker 不修改 `MCP_TIMEOUT_SECONDS=1800` / `MAX_BACKTEST_PER_GEN=5` | 既有 ADR-0010 D8 约束 | — |
| D-FT-06 | worker 复用 `MCP()` 同步上下文，不发明 asyncio | mcp_client 自身是 sync/async 混合 | — |
| D-FT-07 | DDL 走 `supabase/migrations/001_ft_strategies.sql`，不在 runtime 自动执行 | 简化交付 + 可审计 | — |
| D-FT-08 | `version` refine 时由 SQL 表达式 `+1` 而非应用层读改写 | 原子性 + 防止 lost update | — |
| D-FT-09 | UI 不提供"一键上线" | Promotion gate 是人类责任 | — |
| D-FT-10 | Shadow mode 7 天是 hard requirement | ADR-0010 D5 + outerloop Phase 4 | — |
| D-FT-11 | 默认 polling-only；WebSocket 不在 v4 范围 | Vercel Serverless 物理限制 | — |
| D-FT-12 | UI 不写 `HISTORY.jsonl` 新 source key；走独立 audit.jsonl | SourceMutexError 锁 + ADR-0010 D4 | — |
| D-FT-13 | 取消独立 `/log` 路由；详情页有折叠面板 | KISS | — |
| D-FT-14 | AI Learning 走 MEMORY.md 既有 hygiene 节奏 | MEMORY.md §Promotion 流程 | — |
| D-FT-15 | `GET /api/ft-strategy/orient` 返回 next_actions 列表 | Auto-Quant V2 `aq orient` | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-16 | `GET /api/ft-strategy/capabilities` 暴露真值常量（`MCP_TIMEOUT_SECONDS` / `MAX_BACKTEST_PER_GEN` / `STAGNATION_ROUNDS`） | Auto-Quant V2 `aq capabilities` | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-17 | BacktestReport raw 永远不"代理解读"；存 JSONB + 暴露 raw_blocks 字段 | Auto-Quant V1 v0.3.0+ per-pair reporting | [`program.md@1a7cc56`](https://github.com/TraderAlice/Auto-Quant/blob/1a7cc56/program.md) |
| D-FT-18 | `ft_strategy_events` 入库 + .tsv append 是同一事务两步 | Auto-Quant V1 results.tsv survives reset | [`program.md@1a7cc56`](https://github.com/TraderAlice/Auto-Quant/blob/1a7cc56/program.md) |
| D-FT-19 | `ft_strategy_experiments.verdict='crash'` 高亮 + `reasoning` 必填 | Auto-Quant V2 KEEP/REVERT/CRASH | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-20 | `ft_strategy_reports.authoring_state='final'` 不可 UPDATE；deploy 必须引用 final report | Auto-Quant V2 draft / publish | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-21 | `POST /api/ft-strategies` 必须含 ≥ 200 字 `research_md`；不达标 422 | Auto-Quant V2 "Clarify before quantifying" | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-22 | 部署 gate 升级为多目标 9 项（robust_sharpe_min / robust_calmar_min / max_drawdown / profit_floor / min_position / pareto / shadow / report ref / crash 闭环） | Auto-Quant V1 v0.4.1 multi-objective oracle | [`program.md@1a7cc56`](https://github.com/TraderAlice/Auto-Quant/blob/1a7cc56/program.md) |
| D-FT-23 | `tuning_promotion.check_promotion_v3()` 单一纯函数；UI / agent / CLI 复用 | Auto-Quant V2 single Core multiple projections | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-24 | Preflight Gate 6 项在 enqueue 前同步跑，错 422 不进 RQ | Auto-Quant V2 "bounded feedback" | [`OPERATOR_GUIDE.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/OPERATOR_GUIDE.md) |
| D-FT-25 (TBD) | 4 维 Pareto 主导空间 metric 集合 / 权重 与 `maker_checker` 同步 | 与 [okx-baseline-01] trade 分布统计同源 | Phase 6 |

---

## 12. 禁止事项（红线）

```
✗ 不能改：app/loop/ 现有 CMA-ES/Pareto/Maker-Checker 系统

✗ 不能绕过：tuning_promotion.promotion_checklist() / promotion_allowed_for_files()
✗ 不能绕过：apply_tuning() 不能直改 gunicorn worker TUNING
✗ 不能绕过：hyperopt 结果必须写 HISTORY.jsonl，不得直改 TUNING
✗ 不能绕过：Phase 4 shadow mode 7 天观察，UI 不允许在未标记 durable-fact 时申请 deploy
✗ 不能新写：source=freqtrade_ui 进入 HISTORY.jsonl；走 audit.jsonl
✗ 不能不写：所有 RQ worker 入口必须进 .github/workflows/，不裸跑 cron
✗ 不能改：freqtrade_dev_mcp/ 子模块（pin commit）
```

---

## 13. 与上游计划的引用

| 引用 | 用途 |
|------|------|
| `docs/loop-engineering-plan.md` §6 | Outerloop 协议基础 |
| `docs/plans/freqtrade-mcp-integration.md` | freqtrade_dev_mcp Phase 1-3 已有资产（Loop #10） |
| `docs/loop-state/FREQTRADE-LOOP.md` | Loop #10 六维定义（被 #13 复用 `MCP()` 上下文） |
| `docs/loop-engineering-plan.md` §16.13 | drawdown guardrails（本计划 D-FT-10 落地） |
| ADR-0003 D9 | TUNING promotion gate（本计划 D-FT-09 复用） |
| ADR-0010 D4 | hyperopt 结果 source = freqtrade_hyperopt（D-FT-12 守住） |
| ADR-0011 D11 | SourceMutexError 矩阵（D-FT-12 同源） |
| ADR-0012 | 本计划专属 ADR（D-FT-01..25） |

---

## 14. Verification

### Phase 0 验收

1. `git log -1 docs/adr/0012-ft-strategy-ui-integration.md` 显示 ADR-0012 Accepted
2. `docs/loop-state/FT-STRATEGY-LOOP.md` 存在，匹配 OKX-LOOP.md 模板字段 + 包含 §10 列出的 11 字段
3. `durable-facts.md` 出现 `[ftstrategy-baseline-01]` / `[ftstrategy-shadow-01]` / `[ftstrategy-deploy-01]` 三条占位
4. `supabase/migrations/001_ft_strategies.sql` 存在且 DDL 语法正确

### Phase 1 验收

5. `supabase db push` 跑 `001_ft_strategies.sql`：**7 表**（strategies / runs / insights / events / experiments / reports） + RLS 启用
6. `POST /api/ft-strategies`（**必带 research_md ≥ 200 字**）→ 201；缺 research_md → 422；存在后 `ft_strategies.last_event='create'` 且 .tsv 第一行写入

### Phase 2 验收

7. `python -m workers.ft_strategy_worker` 启动后消费 `ft_strategy_create`：调 `MCP().create_strategy()` 成功，`strategy_file_path` 写回
8. `ft_hyperopt` 跑通到 `handshake.write_hyperopt_to_history()` + `ft_strategy_events` 同步追加一行 `event='stable'` + `.scratch/loop_state/ft_strategy/{id}.tsv` 同步追加

### Phase 3 验收

9. `/ft-strategy/new` 表单必须先填 brief（clarify-first），缺则 submit 按钮 disabled；提交后详情页顶部 banner 显示 `GET /:id/orient` 返回的 `next_action`
10. 详情页 10s 轮询 `progress_pct`；Backtest 完成时 `latest_result` 含 Sharpe / Drawdown / per_pair / per_timerange / robust_sharpe_min

### Phase 4 验收

11. `POST /:id/deploy`：**9 项** v4 gate 任一 ✗ → 422 + 明细（包括 final report ref + crash 闭环 + robust_sharpe_min + profit_floor）
12. 全部 ✓ 时 → gh PR URL；status 字段 → `pending_review`
13. `POST /:id/preflight` 暴露 6 项；任一 ✗ → 422 不进 RQ

### Phase 5 验收

14. `python -m loop.loop_sync add-loop docs/loop-state/FT-STRATEGY-LOOP.md` 成功；`LOOP.md` 出现 `### 13.` 完整六维定义
15. `GET /api/ft-strategy/capabilities` 返回的 `constants.{MCP_TIMEOUT_SECONDS, MAX_BACKTEST_PER_GEN, STAGNATION_ROUNDS}` 与代码真值完全一致（**diff 测试**）
16. `GET /api/ft-strategy/orient` 返回的 `next_actions` 至少有 1 项当存在 stagnation_count ≥ 3 的 strategy

### Phase 6 验收

17. 制造 3 个连续 `event='stable'` → POST `/:id/refine` 不带 `intended_event` → 422 + "stagnation rule" 错误
18. 制造 `verdict='crash'` 行（`reasoning` 为空白）→ 422
19. 制造 `authoring_state='final'` 的 report 行 → 试图 UPDATE `reserved_finding` → DB CHECK 触发失败
20. 制造 draft Report → POST `/:id/deploy` → 422 "report not final"

---

## 15. 阶段依赖与上游引用（v4 新增章节）

> **P0-04 修复**：补充缺失章节。

### 15.1 阶段前置依赖

```
Phase 0
  └─► Phase 1: ADR-0012 必须先 Accepted
  └─► Phase 5: FT-STRATEGY-LOOP.md 必须先存在
Phase 1
  └─► Phase 2: supabase/migrations/001_ft_strategies.sql 必须先执行
  └─► Phase 3: API routes 必须先可调
Phase 2
  └─► Phase 4: RQ worker 必须先跑通
Phase 3
  └─► Phase 4: 前端 polling 必须先工作
Phase 4
  └─► Phase 5: deploy PR 必须可创建
Phase 5
  └─► Phase 6: capabilities/orient 必须先上线
```

### 15.2 outerloop-protocol.md 引用

`outerloop-protocol.md` §handshake 与本计划的关系：
- §7（Freqtrade Handshake）定义了 `source=freqtrade_hyperopt` → `HISTORY.jsonl` 路径
- 本计划 D-FT-12 规定 UI 路径不写新 source key，遵守 §7 的互斥矩阵
- `outerloop-protocol.md` §handshake 第 12-15 行定义了 `handshake.write_hyperopt_to_history()` 的调用上下文

---

## 16. Honest Boundary（Auto-Quant V2 §STATUS 模式）

> **来源**：[`docs/STATUS.md@83f9d3a`](https://github.com/TraderAlice/Auto-Quant-V2/blob/83f9d3a/docs/STATUS.md)

本节声明本计划在 v4 review 周期内**已知不工作**的事项，区别于"v4 完成后"才工作的事项。

| 不工作 | 何时变工作 | 原因 |
|--------|-----------|------|
| 真实数据下载（`download_candles` 超大 pair × 长 timerange） | 接入 `freqtrade_dev_mcp` 真实 exchange 凭据后 | Phase 0 已 stub，Phase 1 才能动 |
| WebSocket / SSE 实时推送 | 引入独立 `services/ft_strategy_ws/` 网关后（v4 不在计划内） | Vercel Serverless 物理限制 |
| Pareto 主导 4 维空间的具体 metric + 权重 | Phase 6 与 `maker_checker` 同步后 | 与 [okx-baseline-01] trade 分布统计同源；本计划留 D-FT-25 占位 |
| AI agent 替代 UI 点 `refine` / `deploy`（autonomous loop） | Auto-Quant V2 "Researcher Campaigns" 等价物落地后 | 当前 Loop #13 是 L2（人确认），不是 L3（autonomous） |
| 跨策略横向 port（"把 A 的 profitable 参数 fork 到 B"） | Phase 7+（不在 v4） | 需要 stable cross-strategy 接口；当前 `cross_strategy_pattern` insight 仍停在 record-only |
| in-app 报表可视化（Sharpe / DD 时序图 / 资金曲线图） | Phase 6 UI 增量 | 当前 §3.5 BacktestChart 仅画 aggregate + per_pair；不画时序曲线 |

---

## 17. 复审纪录

| 日期 | 版本 | 触发 | 修改 |
|------|------|------|------|
| 2026-08-12 | v1 | 初稿 | 576 行 |
| 2026-08-12 | v2 | 二阶审计（`ft-strategy-ui-integration-audit-report.md`） | +7 决策 + 1 phase + durable-facts + 独立 loop 文档 |
| 2026-08-12 | v3 | 参考 Auto-Quant V1/V2 三阶修订 | +11 字段 Loop #13 + 7 表 schema + 4 端点 + 多目标 gate + preflight + events.tsv + experiments + reports + honest boundary + Phase 6 |
| 2026-08-12 | v4 | 三阶审计（`ft-strategy-ui-integration-audit-report-v2.md`） | P0-01: §10 Loop #13 六维内联；P0-02: ADR-0012 内联为 §11；P0-04: 新增 §15；P1-01: Gate 统一 9 项；P1-02: robust_sharpe 阈值统一；P1-03: Auto-Quant 全部 commit SHA pin；P1-04: capabilities 含 STAGNATION_ROUNDS；P1-05: §8 改 checklist；P1-06: D-FT-25 TBD；P2-02: migrations 路径修正 |

---

_Last updated: 2026-08-12_
