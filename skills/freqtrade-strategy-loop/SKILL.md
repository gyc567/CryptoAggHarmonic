# SKILL.md — freqtrade-strategy-loop

## 触发条件

1. GitHub Actions `freqtrade-strategy-loop.yml` 触发（schedule 或 push）
2. Pareto 前沿突破时（cryptoagg tuning snapshot 更新）
3. 人工 `workflow_dispatch` 触发

## 输入

- `tuning_snapshots/pareto-{sha}.yaml`（来自 cryptoagg CMA-ES loop）
- `.scratch/loop_state/freqtrade/` 目录结构已建立

## 输出

- `.scratch/loop_state/freqtrade/backtest_results/{uuid}.json`
- `.scratch/loop_state/freqtrade/hyperopt_results/{uuid}.yaml`
- `.scratch/loop_state/freqtrade/pending_issues/{uuid}.json`（suspicious verdicts）

## Process

1. 读取 cryptoagg tuning snapshot → `HarmonicSignal` 对象
2. `translator.translate(signal, config, mode="pattern")` → FreqtradeStrategy Python 文件
3. MCP tool `download_candles` → 市场数据
4. MCP tool `backtest_strategy` → 回测结果
5. `extract_backtest_data` → 解析 metrics
6. 评估 `promotion_checklist()`（drawdown / Calmar / Shadow gates）
7. 若 suspicious → 写入 `pending_issues/`
8. 可选：`hyperopt_strategy` → `handshake.write_hyperopt_to_history()`

## Constraints

- `MCP_TIMEOUT_SECONDS = 1800`（每 tool call）
- `MAX_BACKTEST_PER_GEN = 5`
- hyperopt 结果走 `HISTORY.jsonl`（`source: freqtrade_hyperopt`），不直接改 TUNING
- Promotion 必须 PR + human review + SIGHUP

## TUNING Promotion 约束

**禁止**: `hyperopt → apply_tuning() → 直接生效`
**合规**: `hyperopt → tuning snapshot → human PR → gunicorn SIGHUP`
