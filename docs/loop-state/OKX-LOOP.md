### 11. OKX Agent Trade Kit Loop

> Part of `docs/loop-state/LOOP.md`. 注册由 `loop/loop_sync.py add-loop` 维护。
> ADR-0011 12 Decision 全部继承路径隔离 / 状态文件位置 / crash-safe / Ponytail 排除 / promotion gate 复用。

## 六维定义

| 属性 | 值 | 说明 |
|---|---|---|
| **Cadence** | Phase 1 L1 报告模式 (manual trigger) → Phase 3+ L3 自动 | 与 freqtrade loop 同节奏但**不**并行（同 candidate_id 互斥）|
| **Trigger** | GitHub Actions `workflow_dispatch` (Phase 1) → `schedule` + `push`(main) tuning snapshot (Phase 3) | |
| **Skill** | `okx-strategy-loop` | 见 `.github/workflows/okx-strategy-loop.yml` |
| **State** | `.scratch/okx_state/audit/{YYYY-MM-DD}.jsonl` + `docs/loop-state/STATE.md` | 与 freqtrade handshake 共用 `.scratch/loop_state/HISTORY.jsonl` |
| **Input** | `tuning_snapshots/pareto-{sha}.yaml`（来自 cryptoagg CMA-ES loop）| Phase 3+；Phase 1 仅 human 触发 |
| **Output** | OKX paper fill → `.scratch/loop_state/HISTORY.jsonl` (`source: okx_paper` 或 `okx_live`); audit log | |
| **Gate** | L3+ — 三重门（启动参数 + env + 运行时 tool gate）+ 第四门 human checklist（ADR-0011 D8）| promotion 必须经 human PR + SIGHUP |

## Maturity Timeline

| 阶段 | 目标 | 验收 |
|---|---|---|
| Phase 1A | L0 基础设施 | `install.sh` / `start_with_creds.sh` / Keychain 3 accounts / `.scratch/okx_state/` gitignored |
| Phase 1B | L0 代码骨架 | `tuning_promotion.is_live_execution_tool()` + `execution_allowed_for_tools()` + `app/services/okx/` 6 个 skeleton + state source mutex |
| Phase 2 | L1 报告模式 | translator + mcp_client + executor + audit + handshake 全通；100% 测试覆盖 |
| Phase 3 | L2 端到端 | spot paper order → fill → HISTORY.jsonl round-trip；workflow 上线 |
| Phase 4 | L3 自动 (限定) | dry-run ↔ backtest 对比 7 天 + audit 完整 + max_dd < 1.5×baseline |

## Process (Phase 3+)

```
1. 读取 cryptoagg tuning snapshot (tuning_snapshots/pareto-{sha}.yaml)
2. 三重门检查 (gate-1 MCP --read-only / gate-2 OKX_PAPER_MODE / gate-3 tool gate)
3. 第四门 (gate-4 human checklist 由 driver 验证; executor 不做)
4. Signal → OKX spot order (translator.py: pattern | indicator | regime)
5. mcp_client.invoke_tool(spot_place_order, args) — Phase 1 paper only
6. audit.py.append(outbox → atomic rename → .scratch/okx_state/audit/{date}.jsonl)
7. executor.dispatch 完成后调 handshake.write_fill_to_history
8. append_history 检测 source mutex (D11); 同 candidate_id 不允许 freqtrade_hyperopt + okx_* 共存
9. promotion_checklist() 评估是否建议 TUNING promotion (Phase 4+)
```

## Constraints

- 每个 MCP tool 调用 `timeout=1800s`
- 每 generation 最多 **3** 个 OKX 写候选（`MAX_OKX_WRITE_PER_GEN=3`，严于 freqtrade 的 5，因为写操作有副作用）
- OKX server-side rate limit 50011 → 等 5s + 单次重试
- OKX 三要素走 macOS Keychain `cryptoagg-okx` service，**不**进 repo / 配置
- audit log append-only，10 字段 schema (ADR-0011 D6)
- 90 天滚动（**不**自动清；人工归档）
- 实盘切换走 `promotion_checklist()` 全门 + `OKX_ALLOW_LIVE=1` 显式 opt-in
- **首笔实盘 limit 单 ≤ $10 USDT 等价**，人工触发 + 截图 + durable-fact

## Phase 1 模块范围

仅 `market` + `account` + `spot (paper only)` 三模块启动。`swap` / `futures` / `option` / `earn` / `event` / `bot` / `news` / `smartmoney` 在 Phase 2+ 才加入。
