### 13. FT Strategy UI Loop

> Part of `docs/loop-state/LOOP.md`. 注册由 `loop/loop_sync.py add-loop` 维护。
> 源于 `docs/plans/ft-strategy-ui-integration.md` v3 (911 行)，新增 ADR-0012 共 12 Decision。
> 继承路径隔离 / 状态文件位置 / crash-safe / Ponytail 排除（ADR-0010 D2-D8）+ SourceMutexError 矩阵（ADR-0011 D11）。
> **复用** `app/loop/tuning_promotion.py`：v3 在该文件内新增 `check_promotion_v3()` 纯函数（D-FT-23），不新建并行文件。

## 六维定义

| 属性 | 值 | 说明 |
|---|---|---|
| **Cadence** | 用户 HTTP 请求触发 / RQ 后台 worker 串接 | 与 Loop #10 同源（hyperopt/results/handshake 复用），但触发方式不同 |
| **Trigger** | Vercel 前端 POST + 用户点 [✏ 编辑] / [🚀 申请部署 PR] + GH Actions `workflow_dispatch` 拉起 worker | orient: `GET /api/ft-strategy/orient` 是 pseudo-trigger（D-FT-15） |
| **Skill** | `ft-strategy-ui` | 见 `.github/workflows/ft-strategy-ui.yml` |
| **State** | Supabase 7 表（strategies / runs / events / experiments / reports / insights / jobs）+ Redis `ft_job:{id}` TTL 7d + `.scratch/loop_state/ft_strategy/{strategy_id}.tsv` + `audit.jsonl` | events / experiments / reports 是 v3 新增 |
| **Input** | 用户 brief 表单 + 必填 `research_md`（≥ 200 字）+ 可选 `intended_event` ∈ {evolve, fork, kill} | clarify-first (D-FT-21) |
| **Output** | IStrategy 文件 + `HISTORY.jsonl` `source=freqtrade_hyperopt`（worker 转译，**不**新增 source key）+ `audit.jsonl` + gh PR URL + 最终态 report | final report 由 `report draft → final` 端点显式 promote |
| **Gate** | L2 强化门：后台 hyperopt / backtest / analyze 自动；Deploy 必须 8 项多目标 gate + final report ref + shadow 7 天 + 人类合 PR + SIGHUP | v3 多目标 gate（D-FT-22）替换原 5 项单标量 |
| **Worktree** | 不使用（不修改 `app/config/tuning.py`；PR 由 gh 流程管） |  |
| **MCP** | `freqtrade_dev_mcp` 12 tools，复用 Loop #10 既定协议；不重复调用 OKX exchange MCP |  |
| **Orient** | `GET /api/ft-strategy/orient` 返回 `next_actions` 列表 | v3 新增（D-FT-15） |
| **Capabilities** | `GET /api/ft-strategy/capabilities` 暴露真值常量（`MCP_TIMEOUT_SECONDS`、`MAX_BACKTEST_PER_GEN`、`STAGNATION_ROUNDS`） | v3 新增（D-FT-16） |

## Maturity Timeline

| 阶段 | 目标 | 验收 |
|---|---|---|
| Phase 0 | L0 文档基线 | ADR-0012 + FT-STRATEGY-LOOP.md + LOOP.md §13 + 3 durable-facts 占位 |
| Phase 1 | L0 纯函数 | `check_promotion_v3()` + `validate_research_md()` + 100% 测覆盖 |
| Phase 2 | L0 Schema | 7 表 DDL + `ft_strategy_repo` CRUD + RLS |
| Phase 3 | L1 事件流 + 实验 + Report | `event_log.tsv + ft_strategy_events` 同事务写 + DB CHECK final lock |
| Phase 4 | L1 API | `orient` + `capabilities` + CRUD endpoints + blueprint 注册 |
| Phase 5 | L2 端到端 | preflight 6 项 + deploy PR + RQ worker + GH workflow |
| Phase 6 | L2 Stagnation + Final | stagnation_count enforce + final report enforce + loop_sync register |

## Process (Phase 1+)

```
1. UI POST /api/ft-strategies + research_md
2. validate_research_md(research_md) → enforce ≥ 200 字 + 必要 sections (D-FT-21)
3. INSERT ft_strategies (status='draft', last_event='create', research_md=...)
4. enqueue `ft_strategy_create` (worker) → MCP().create_strategy() → strategy_file_path
5. enqueue `ft_hyperopt` → MCP().hyperopt_strategy() → progress 写 Redis
6. extract_hyperopt_data → write_hyperopt_to_history(source='freqtrade_hyperopt')  // D-FT-12
7. 同事务双写：INSERT ft_strategy_events + append .tsv  // D-FT-18
8. enqueue `ft_backtest` → MCP().backtest_strategy() → extract_backtest_data
9. enqueue `ft_analyze` → 对比 baseline → UPDATE ft_strategies.latest_result + last_event='stable' | 'evolve' | 'crash'
10. INSERT ft_strategy_experiments (verdict, reasoning)  // D-FT-19, reasoning 必填
11. UI POST /:id/deploy → check_promotion_v3(candidate, ctx) 8 项全过 → gh PR 创建 (D-FT-22)
12. 人类合 PR + SIGHUP → outerloop 检测 main 推送 → UPDATE status='deployed'
```

## Constraints

- 每 MCP tool 调用 `timeout=1800s`（既有 ADR-0010 D8，不改）
- 每 generation 最多 `MAX_BACKTEST_PER_GEN=5` 个 backtest 候选（既有 ADR-0010 D8，不改）
- 新增：`STAGNATION_ROUNDS=3`（连续 stable event 数；≥ 3 时 refine 强制要求 `intended_event`）
- 新增：`RESEARCH_MD_MIN_LENGTH=200`（POST body 校验）
- 新增：`REASONING_MIN_LENGTH=10`（experiment verdict 校验）
- 新增：`FINAL_REPORT_HASH_REQUIRED=true`（deploy 必引 final report）
- UI worker **不**修改 `app/loop/state.append_history` 签名（D-FT-12 + ADR-0011 D11）
- HF 凭据不走 plan / API；DL 限速按 `MAX_BACKTEST_PER_GEN=5`
- WebSocket / SSE 不在 v3 范围（D8，§16 Honest Boundary 第 2 行）

## Phase 1 模块范围

仅 `create_strategy` / `hyperopt_strategy` / `backtest_strategy` / `extract_*_data` + `download_candles`（preflight 触发）。
`list_results` / `get_result` / `search_results` / `create_strategy_wireframe` / `create_config` / `create_userdir` 暂不接入 UI；
Phase 6+ 再扩。
