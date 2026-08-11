### 10. Freqtrade Strategy Loop

> Part of `docs/loop-state/LOOP.md`. 注册由 `loop/loop_sync.py add-loop` 维护。

## 六维定义

| 属性 | 值 | 说明 |
|---|---|---|
| **Cadence** | 每周一次（周日 10:00 UTC）或 Pareto 前沿突破时触发 | 与 Code Health Audit 同 cadence |
| **Trigger** | GitHub Actions `schedule` + `push`(main) Pareto signal | |
| **Skill** | `freqtrade-strategy-loop` | 见 `skills/freqtrade-strategy-loop/SKILL.md` |
| **State** | `.scratch/loop_state/freqtrade/` + `docs/loop-state/STATE.md` | |
| **Input** | `tuning_snapshots/pareto-{sha}.yaml`（来自 cryptoagg CMA-ES loop） | |
| **Output** | `freqtrade/backtest_results/{uuid}.json` + `freqtrade/pending_issues/` | |
| **Gate** | L3 — 自动执行 within constraints；promotion 必须经 human PR | |

##  Maturity Timeline

| 阶段 | 目标 | 验收 |
|---|---|---|
| Phase 1 | L1/L2 — 报告+建议 | `freqtrade-strategy-loop.yml` 存在 |
| Phase 2 | L2 — 端到端跑通 | translator + mcp_client + handshake 全通 |
| Phase 3 | L3 — 自动 within constraints | 自动执行 + promotion gate |

## Process

```
1. 读取 cryptoagg tuning snapshot
2. Signal → FreqtradeStrategy 翻译（translator.py）
3. freqtrade download_candles（MCP tool）
4. freqtrade backtest_strategy（MCP tool）
5. extract_backtest_data → 解析结果
6. 若 performance > 阈值 → suspicious_to_human → pending_issues/
7. hyperopt_strategy（可选，Phase 3）
8. extract_hyperopt_data → handshake.write_hyperopt_to_history()
9. promotion_checklist() 评估是否建议 TUNING promotion
```

## Constraints

- 每个 MCP tool 调用 `timeout=1800s`
- 每 generation 最多 5 个 backtest 候选
- hyperopt 结果必须走 `HISTORY.jsonl`（`source: freqtrade_hyperopt`），不得直接改 TUNING
- promotion 必须 PR + human review + SIGHUP
