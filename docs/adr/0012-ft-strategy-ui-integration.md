# ADR-0012: FT 策略中心 — 前端 UI + Loop Engineering 整合

**状态**: Accepted
**日期**: 2026-08-12
**来源**: `docs/plans/ft-strategy-ui-integration.md` v3 (911 行)

---

## Decision 1: 复用 `app/loop/tuning_promotion.py`，新增 `check_promotion_v3()` 纯函数，不发明并行模块

部署 promotion gate **必须**走 `app/loop/tuning_promotion.py` 这一文件。v3 在该文件内新增一个纯函数
`check_promotion_v3(candidate: PromotionCandidate, ctx: PromotionContext) -> PromotionResult`，
与原有 `promotion_checklist()` 并存。理由：

- 既有 `promotion_checklist()` 已在 Loop #10 + 历史 E2E 用稳（ADR-0003 D9 + ADR-0010 D5）。
- v3 新加的多目标项（robust_sharpe_min / profit_floor / pareto_dominated_by）属于**量化补充**，不是新域。
- UI / agent / CLI 三方共用同一函数（D-FT-23）：避免出现"UI 看到一份 gate，后端跑另一份"的偏差。

禁止：

- 新建 `app/services/freqtrade/freqtrade_promotion.py` 或同义文件。
- 在 routes / worker / script 里手写 if-else 复刻 gate 判定。

---

## Decision 2: 新增 7 张 Supabase 表 + 1 份 .scratch tsv 文件

| 表 | 用途 | 可变性 |
|---|---|---|
| `ft_strategies` | 一个意图（Idea → deploy）的命名空间 | mutable；`current_version` 由 SQL 表达式 `+1` 维护 |
| `ft_strategy_runs` | 一次不可变执行（stage ∈ code/hyperopt/backtest/analyze） | append-only；`result` 一旦写入不可 UPDATE |
| `ft_strategy_events` | `results.tsv` 持久层（`commit \| event \| strategy_name \| sharpe \| max_dd \| note`） | append-only |
| `ft_strategy_experiments` | KEEP/REVERT/CRASH 实验 verdict + reasoning | append-only |
| `ft_strategy_reports` | Audit-grade 产出（`authoring_state ∈ draft\|final`） | final 行 DB CHECK 锁 UPDATE |
| `ft_strategy_insights` | 跨策略洞察 + durable-facts 桥接 | append-only |
| `ft_jobs` | RQ job 元数据（status / progress） | mutable summary |

外加 `.scratch/loop_state/ft_strategy/{strategy_id}.tsv`，gitignored（worker 镜像 events 表）。

---

## Decision 3: Source mutex — UI 路径**不**写 HISTORY.jsonl 新 source key

`handshake.write_hyperopt_to_history()` 的 `source` 默认值 `"freqtrade_hyperopt"`（ADR-0010 D4）。
UI worker 调 MCP 后写 HISTORY.jsonl 时**保留**该默认值，**不**新增 `source=ft_strategy_ui`。
独立 audit log 走 `.scratch/loop_state/ft_strategy/audit.jsonl`。

理由：ADR-0011 D11 已建立 `SourceMutexError` 矩阵（`freqtrade_hyperopt` ↔ `okx_*`），
新增第三种 source 必须扩展矩阵；本期 v3 不扩展，复用现有 mutex。

---

## Decision 4: 部署必须满足多目标 gate + final report + shadow mode 7 天

部署申请（`POST /api/ft-strategies/:id/deploy`）必须 8 项 gate 全过：

1. `robust_sharpe_min ≥ 0.0` — `min(per_timerange.sharpe)` ∈ {bull, winter, recovery, full_5y}
2. `robust_calmar_min ≥ 1.0`
3. `max_drawdown ≤ 2 × baseline_drawdown`（既有 ADR-0010 D5）
4. `profit_floor ≥ 0.05` — 防止 vol_target 收敛到 profit→0 退化（Auto-Quant v0.4.1 案例）
5. `min_position_size` — `trades >= 30`（与现有 accepted floor 对齐）
6. NOT `pareto_dominated_by` — 当前策略在 (sharpe, calmar, max_dd, winrate) 4 维空间不被同一 user 的 prior KEEP 主导
7. `report referenced` — 存在 `authoring_state='final'` 的 report 行
8. No crash 闭环 — `ft_strategy_experiments.verdict='crash'` 在 7 天内必须被 `decided_by` 非空处置

任一失败 → 422 + checklist 渲染。

---

## Decision 5: UI 不提供"一键上线" — `POST /:id/deploy` 仅创建 PR

UI 永远不直接修改 `app/config/tuning.py`（AGENTS.md §第一性原理 + ADR-0003 D9）。
Phase 4 Shadow Mode 7 天观察期是 hard requirement；
`[ftstrategy-shadow-01]` durable-fact 不入库 → 隐藏"申请部署"按钮 + tooltip 明示。

PR 创建走 `gh` CLI wrapper（`app/ft_strategy/deploy_pr.py`），
PR 模板自带 tuning snapshot + report hash + salt_version。
人类合 PR → Loop #10 outerloop 检测 main 推送 → CI 触发 SIGHUP → status='deployed'。

---

## Decision 6: clarify-first research_md ≥ 200 字

`POST /api/ft-strategies` body 必须含 `research_md` ≥ 200 字符且含必填 sections：
Decision / Question / Motivation / Universe / Constraints / Failure modes / Open Qs。
缺则 422 + 模板链接。
`🔧 Code` worker 只在 `research_md` 非空时启动。

理由：Auto-Quant V2 §Operator Guide "Clarify before quantifying"；plan-and-shoot 是历史失真来源。

---

## Decision 7: 新代码位置 + Ponytail 排除

| 模块 | 路径 | 备注 |
|---|---|---|
| Pure-function gate | `app/loop/tuning_promotion_v3.py`（同目录追加） | 复用 tuning_promotion，避免 split file 风险 |
| Repo + sync helpers | `app/ft_strategy/supabase_repo.py`（计划 §8 新建目录） | 业务集成层，Ponytail 适用 |
| Event TSV writer | `app/services/freqtrade/event_log.py` | 与 handshake 同包 |
| Promotion PR wrapper | `app/ft_strategy/deploy_pr.py` | gh CLI 包装 |
| Worker | `workers/ft_strategy_worker.py`（计划 §8 顶层） | RQ 入口 |
| Tests | `tests/services/freqtrade/` + `tests/ft_strategy/` | 与既有测试相邻 |

`app/loop/tuning_promotion_v3.py` 是 `app/loop/` 内的**纯函数**文件，不引入新业务逻辑（与 ADR-0010 D2 / AGENTS.md Ponytail 约束保持一致：纯算法可写，副作用归 service 层）。

---

## Decision 8: WebSocket / SSE 不在 v3 范围

Vercel Serverless 不支持长连接；现有 backend systemd + Vercel frontend 拓扑扩 WS 需独立长连接网关。
10s 轮询（`GET /api/ft-strategies/:id/jobs`）覆盖 hyperopt/backtest（30 min+）进度需求；
WebSocket 留待 Phase 7+ 提案，**不**在 v3 范围。
（§16 Honest Boundary 第 2 行已显式列出）

---

## Decision 9: 状态文件位置

| 内容 | 位置 | git 追踪 |
|---|---|---|
| Strategy + runs DB | Supabase（计划 §4） | ✅ (DDL 由 dashboard) |
| Worker job 元数据 | Redis `ft_job:{job_id}` TTL 7d | ❌ |
| Audit log | `.scratch/loop_state/ft_strategy/audit.jsonl` | ❌ (gitignore 已加) |
| Event TSV | `.scratch/loop_state/ft_strategy/{strategy_id}.tsv` | ❌ |
| Loop 定义 | `docs/loop-state/FT-STRATEGY-LOOP.md` | ✅ |
| State 摘要 | `docs/loop-state/STATE.md`（自动填） | ✅ |
| Loop 注册 | `docs/loop-state/LOOP.md` §13（人工 review 后注册） | ✅ |
| ADR | `docs/adr/0012-ft-strategy-ui-integration.md` | ✅ |
| 计划 | `docs/plans/ft-strategy-ui-integration.md` v3 | ✅（auto-merge denylist） |

---

## Decision 10: 强制门 vs L2 自主门

| 阶段 | L 等级 | 谁触发 | 谁确认 |
|---|---|---|---|
| 💡 → 🔧 Code | L2 | UI POST | worker 同步验证 research_md → 非空即开工 |
| ⚡ Hyperopt | L3 | worker 后台 | 不需要人类；progress 写 Redis |
| 📊 Backtest | L3 | worker 后台 | 同上 |
| 🔍 Analyze | L3 | worker 后台 | 同上 |
| 🔄 Refine | L2 | UI 点 [✏] | 人类写 intended_event（非 stagnation 状态下可选） |
| 🚀 Deploy | L2（强制升级为多目标 gate） | UI 点 [🚀 申请部署 PR] | 全 8 项 gate 通过 → gh PR 链接 |
| 人类合 PR | 人类 | GitHub | 必看 PR diff → merge |
| SIGHUP | 人类 | 后端 | 必 SSH / systemctl 操作 |

Loop #13 整体 `L2`；Deploy 是 **L2 强化门**（8 项 gate 比 L3 自动 constraint 严格得多）。

---

## Decision 11: 与现有 Loop 的资源隔离

- Loop #13 worker 跑在独立 RQ queue 名空间：`ft_strategy_*`
- Redis key 前缀：`ft_job:`（TTL 7d），与 Loop #10 的 `ft_hyperopt:*` 同 namespace 但**不**重叠
- Loop #10 的 `HISTORY.jsonl` source key 不变；UI worker 转译写入复用 mutex 矩阵
- 不修改 `app/loop/state.append_history` 签名（D-FT-12）

---

## Decision 12: 单元 / E2E / Loop 验收

每 Phase 验收独立可执行（计划 §14 已列出 19 项）：
- Phase 0：ADR + loop 文档 + LOOP.md + STATE.md + durable-facts 三条占位
- Phase 1：纯函数 + tests（不依赖 DB，pytest 必绿）
- Phase 2：SQL migrations 用 sqlite / pg_dump 比对（dev 环境无 Supabase，用 sqlite 模拟）
- Phase 3-6：service / API / worker 各自测，最后一条 smoke 把全部串起来

底线：**任何 Phase 不准"为了进度而删测试"**（AGENTS.md §100% coverage）。

---

## 与上游 ADR 的关系

- 继承 ADR-0003 D9：TUNING promotion gate 复用
- 继承 ADR-0010 D2-D8：路径隔离、状态文件、Ponytail 排除、MCP_TIMEOUT_SECONDS=1800、MAX_BACKTEST_PER_GEN=5
- 继承 ADR-0011 D11：SourceMutexError 矩阵（不动）
- 与 ADR-0012 D-FT-NN：一一对应，已并入对应章节

---

## 状态机（strategy_lifecycle）

```
draft
  │ POST /api/ft-strategies (+ research_md)
  ▼
code_generated ←──┐
  │ enqueue ft_strategy_create (worker)
  ▼               │
hyperopt_running │
  │               │
  ▼               │
backtest_running │  worker / user action
  ▼               │
analyzed ─────────┘  → refining → backtest_running → analyzed
  │
  ▼
refining (only when stagnation ≥ 3; required intended_event)
  │
  ▼
pending_review (PR created, awaiting human merge)
  │ 人类合 PR + SIGHUP → CI hooks
  ▼
deployed
  │
  ▼ (rejected branch)
rejected (verdict='crash' OR STAGNATION + missing ref)
```

不能从 `deployed` 直接转回任意状态；只能通过新策略 `clone`。
