# Audit Report: FT 策略中心 UI 整合

> 二阶审计，针对 `docs/plans/ft-strategy-ui-integration.md` v1。
> 修复并入计划 v2（见 `docs/plans/ft-strategy-ui-integration.md`）。
> 来源方法：loop-engineering 文档一致性 + ADR-0010/0011 既有约束 + 文件结构现状。

## 一、Loop-Engineering 合同缺位（P0 — 7 项）

| # | 问题 | 引用 | 严重度 |
|---|------|------|--------|
| P-01 | 没有 Phase 0（基线 + ADR + durable-facts） | `binance-cli-integration.md` §0、`okx-agent-trade-kit-integration.md` §0 | P0 |
| P-02 | Loop #13 六维定义字段不齐（缺 Worktree/MCP 行，Trigger 描述含糊） | `docs/loop-state/OKX-LOOP.md`、`FREQTRADE-LOOP.md` | P0 |
| P-03 | 没有 `docs/loop-state/FT-STRATEGY-LOOP.md` 文件路径，分节在主计划里就出现 | `LOOP.md` §9–13 模式 | P0 |
| P-04 | `loop_sync.py add-loop` 验证步骤引用错误（用 `--filename` 而非 bare path） | `loop/loop_sync.py` | P1 |
| P-05 | 没有 durable-facts 占位条目（基线、shadow mode 等） | `durable-facts.md` §`[freqtrade-baseline-01]` 模式 | P1 |
| P-06 | 没有外环协议引用（`outerloop-protocol.md` §handshake） | `docs/loop-state/outerloop-protocol.md` | P1 |
| P-07 | 没有 Phase 4 Shadow prerequisite 联锁 | `ADR-0010 D5`、`FREQTRADE-LOOP.md` Constraints | P0 |

---

## 二、Promotion Gate 红线越权（F — 3 项）

| # | 问题 | 引用 |
|---|------|------|
| F-01 | Plan §6 Promotion Gate 叙述把"申请上线"做成 UI 一步走完 → 实际 `promotion_checklist()` 仅生成 checklist 字符串，**不是** blocking 函数 | `app/loop/tuning_promotion.py:41-66` |
| F-02 | "申请上线" → "创建 PR → SIGHUP" 缺少 `promotion_allowed_for_files()` 旁路检查 | `app/loop/tuning_promotion.py:29-38` |
| F-03 | UI 可点"上线"按钮绕过 `app/services/freqtrade/loop_runner.py` 的 snapshot→handshake 路径，导致 `HISTORY.jsonl` 与 `tuning_snapshots/pareto-{sha}.yaml` 双源不一致 | ADR-0010 D4、`outerloop-protocol.md` |

---

## 三、错误地多源/MCP 集成（M — 5 项）

| # | 问题 | 引用 |
|---|------|------|
| M-01 | `HISTORY.jsonl` 来源枚举：`freqtrade_hyperopt` / `okx_*`，**没有** `ft_strategy_ui`；plan 添加新 source key 但不与 `SourceMutexError` 协调 | `app/loop/state.py`、`durable-facts.md` `[okx-cycle-pause-01]` §Phase 1B |
| M-02 | MCP tool 12 个，plan 未把 `create_strategy` 与 `create_strategy_wireframe` 区分；实际用法里 wireframe 是空壳（不需要参数） | `ADR-0010 §MCP Tool Schema` |
| M-03 | `extract_backtest_data` / `extract_hyperopt_data` 跑在 worker 端而非 MCP 端；架构图把它们画成 worker 步骤 5，实际 `loop_runner.py` 也调它们 | `app/services/freqtrade/loop_runner.py:97-105` |
| M-04 | `MCP_TIMEOUT_SECONDS=1800` / `MAX_BACKTEST_PER_GEN=5` 在 plan 中只字未提，会被 worker 默认覆盖或破坏既有约束 | `app/services/freqtrade/mcp_client.py:31-32` |
| M-05 | `mcp_client` 是 stdlib subprocess 同步 / 异步混合；`job_dispatcher` 想做 async 必须复用其 `MCP()` 上下文管理器接口 | `mcp_client.py:164-175` |

---

## 四、Phase D 拆分与 SLA 不合理（D — 4 项）

| # | 问题 | 引用 |
|---|------|------|
| D-01 | Phase A–H 八阶段过细：A 的 DB/API 与 B 的 worker 实际耦合（POST → enqueue 在同一请求内） | AGENTS.md §KISS |
| D-02 | Phase C/D 互相重叠（D 依赖 C 的创建页触发）；应合为单一可流过式页面 | 既有 vibe 页面分页模式 `frontend/app/vibe/` |
| D-03 | Refine 阶段没定义幂等 / version bump 规则，导致回测参数覆盖 `current_version` 语义不清 | §4.1 strategies schema |
| D-04 | Deploy 阶段没要求"refine → re-backtest → re-analyze" 链路反复串行校验，gate 是单次评估 | `FREQTRADE-LOOP.md` Process §9 |

---

## 五、可观测/可干预承诺未兑现（O — 3 项）

| # | 问题 | 引用 |
|---|------|------|
| O-01 | WebSocket 在 Vercel Serverless 上不支持，plan 默认走 WebSocket → 实际只能降级 | 既有 Vercel 部署、`docs/plans/vercel-frontend-deploy.md` |
| O-02 | "10s 轮询"未与 `/metrics` 的 `mcp_call_timeout_total` 等埋点对齐 | `app/api/metrics_routes.py:14` |
| O-03 | AI Learning 写 `durable-facts.md` 没有任何写入策略（哪个 agent 触发？星期几？hygiene loop 接哪一项？） | `MEMORY.md` §Promotion 流程 |

---

## 六、Ponytail/AGENTS 一致性（K — 3 项）

| # | 问题 | 引用 |
|---|------|------|
| K-01 | `app/ft_strategy/` 不是 Ponytail 排除区（仅 `app/loop/`、`bench/`、`tests/` 是）—— plan 文件结构正确，属业务层 | AGENTS.md §Ponytail Constraint Scope |
| K-02 | 新建 `app/api/ft_strategy_routes.py` 必须 `app/api/routes.py` 显式 `register_blueprint`；plan §3.1 没显示这一行 | `app/api/routes.py` 末尾 |
| K-03 | plan 提到 `site_url` 等运行时配置，但没有进入 `.env.example` 与 AGENTS.md §KISS §"参数写在头部或读环境变量" | AGENTS.md §执行风格 |

---

## 七、Phase A–H 校验码碎裂（T — 4 项）

| # | 问题 | 引用 |
|---|------|------|
| T-01 | Phase A 验收写 `supabase db push` —— 项目**没有** Supabase 迁移 CLI（用的是 `db.sqlite` 或 Supabase dashboard migration）；Phase A 验收码写错工具 | 已确认无 `.scratch/` migration |
| T-02 | Phase H 引用 `loop/loop_sync.py add-loop FT-STRATEGY-LOOP.md` —— 实际命令形如 `python -m loop.loop_sync add-loop docs/loop-state/FT-STRATEGY-LOOP.md` | `loop/loop_sync.py` CLI |
| T-03 | Phase B 验收要求 `handshake.write_hyperopt_to_history()` 写 `source: ft_strategy_ui` —— 实际 dataclass 字段 `source: str = "freqtrade_hyperopt"` 是写死默认值；要么改 dataclass（违反 ADR-0010 D4 单源约束）要么不做 UI 路径写 HISTORY | `handshake.py:62` |
| T-04 | Phase D 验收"`Hyperopt 运行中详情页每 10s 更新一次 progress bar`"—— Vercel 限制 SSE 连接时长（10 分钟 serverless），应改为轮询而非定时推送 | Vercel docs |

---

## 统计

| 等级 | 数量 |
|------|------|
| F — 破坏约束 | 3 |
| M — 错误集成 | 5 |
| P — loop 合同缺失 | 7 |
| D — 设计/拆分 | 4 |
| O — 可观测/可干预 | 3 |
| K — Ponytail/AGENTS | 3 |
| T — 验收/路径错误 | 4 |
| **总计** | **29** |

---

## v2 修复策略

- 计划版本号升至 v2（本轮自审）
- 引入 **Phase 0**（基线 + ADR-0013 + durable-facts 占位条目）
- 把 Phase A–H 折成 **4 个真正可串行的阶段**（API+Schema / Worker+MCP / Frontend 页面 / Promotion & Deploy），每阶段验收一条
- 引入独立 loop 文档 `docs/loop-state/FT-STRATEGY-LOOP.md`，与 `FREQTRADE-LOOP.md`、`OKX-LOOP.md` 对齐
- 新增 **D-FT-1 — Decided D12/D13/D14**（source mutex / Phase 4 shadow 强门槛 / RQ worker 等效 GitHub workflow）
- 把 WebSocket 明确从方案里删去：默认 polling（10s），有独立 long-running 后端时再加 SSE
- Promotion Gate **只看 checklist 渲染 + PR 创建触发**，**不**做 in-app "上线"
- Durable-Facts 占位条目：`[ftstrategy-baseline-01]`、`[ftstrategy-shadow-01]`、`[ftstrategy-deploy-01]`

详见 `docs/plans/ft-strategy-ui-integration.md` v2。

---

## v3 增量（2026-08-12，三阶修订）

v2 修复已落地 29 项（见上）。v3 不重做 v1→v2 修复；它叠加第三层：参考 [TraderAlice/Auto-Quant](https://github.com/TraderAlice/Auto-Quant) + [Auto-Quant-V2](https://github.com/TraderAlice/Auto-Quant-V2) 的 Agent-native 工作台模式。

v3 新增 7 项能力（每项都能在 Auto-Quant 现有代码 / 文档找到一手出处）：

1. **Strategy/Run/Cache/Report 四层持久化** — 7 表 schema，把"最新 result"与"不可变 evidence"分开
2. **`results.tsv` 事件流**（`.scratch/loop_state/ft_strategy/{id}.tsv`，gitignored）— 同 Auto-Quant V1 `results.tsv` survives reset
3. **多目标 Promotion Gate** — `robust_sharpe_min` / `robust_calmar` / `profit_floor` / `min_position_size` / `pareto_dominated_by` — Auto-Quant V1 v0.4.1 同款
4. **`orient` + `capabilities` 端点** — Auto-Quant V2 `aq orient` / `aq capabilities` 直接对应
5. **KEEP/REVERT/CRASH 不可变实验** — `ft_strategy_experiments` 表 + crash 强制 reasoning 非空
6. **clarify-first `research_md`** — POST /api/ft-strategies 必须带 ≥ 200 字 brief（Auto-Quant V2 §Operator Guide "Clarify before quantifying"）
7. **Honest Boundary 节** — v3 review 周期内**已知不工作**的 6 项逐项列出（Auto-Quant V2 `docs/STATUS.md` "Honest boundary" 模式）

v3 新增 11 条决策：D-FT-15..24 + 1 占位（D-FT-25 等 Phase 6 与 `maker_checker` 同步）

v3 不在范围：WebSocket（Phase 7+ 提案）、autonomous agent 替换 UI、L3→L4 进化、`maker_checker` 4 维主导空间具体 metric。详见 §16 Honest Boundary。

详见 `docs/plans/ft-strategy-ui-integration.md` v3（911 行）。
