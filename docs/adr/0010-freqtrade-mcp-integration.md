# ADR-0010: Freqtrade Dev MCP 整合

**状态**: Accepted
**日期**: 2026-08-11
**来源**: `docs/plans/freqtrade-mcp-integration.md`

---

## Decision 1: 复用 `tuning_promotion.py`，不新建 `freqtrade_promotion.py`

freqtrade hyperopt 的 TUNING promotion 必须经过 `app/loop/tuning_promotion.py` 定义的 gate。
禁止在 freqtrade 循环中直接调用 `apply_tuning()` 或修改 gunicorn worker 的 TUNING 单例。

**理由**: 已有 gate 实现完整（ADR-0003 D9），复用避免重复代码。

---

## Decision 2: 翻译层放 `app/services/freqtrade/`，不放 `app/loop/`

所有 freqtrade 集成代码放在 `app/services/freqtrade/`（translator.py, mcp_client.py, handshake.py）。
`app/loop/` 是 Ponytail 排除区（AGENTS.md §Ponytail Constraint Scope），不得新增业务逻辑。

---

## Decision 3: Loop #10 目标 L3（自动模式）

`docs/loop-state/FREQTRADE-LOOP.md` 定义的 Freqtrade Strategy Loop 成熟度目标为 L3。
Phase 1 先实现为 L1/L2，Phase 3 达到 L3。

---

## Decision 4: hyperopt 结果走 HISTORY.jsonl（source: freqtrade_hyperopt）

freqtrade hyperopt 结果**不直接修改 TUNING**。
写入 `HISTORY.jsonl` 追加 `source: "freqtrade_hyperopt"` 字段，通过 `handshake.write_hyperopt_to_history()` + outbox 模式实现。
Promoted 参数必须经 tuning snapshot → human PR → SIGHUP。

---

## Decision 5: drawdown / Calmar / Shadow 列入 promotion checklist

`promotion_checklist()` 新增三项量化门：
- `max_drawdown ≤ 2 × baseline_drawdown`
- `Calmar ratio ≥ 阈值（Phase 0 确定）`
- `Shadow mode 运行 ≥ 7 天无回撤异常`

---

## Decision 6: freqtrade_dev_mcp 依赖 pin commit SHA + license 审查

```
克隆: git clone https://github.com/gyc567/freqtrade_dev_mcp.git --depth 1
Pin: 04a26d7f8a0e82bf76d301e1823368dbd4b0d32f
License: MIT (Freqtrade MCP Team, 2024) — 兼容
```

---

## Decision 7: 凭据走凭据管理器，user_data 不入 git

Exchange API key/secret 仅运行时从凭据管理器读取。
启动脚本写入 `chmod 600` 临时 `user_data/config.json`（已在 `.gitignore`）。

凭据条目名（向凭据管理员申请）:
- `freqtrade-exchange-key`
- `freqtrade-exchange-secret`
- `freqtrade-mcp-token`（如有）

---

## Decision 8: MCP tool 调用约束

| 约束 | 值 | 理由 |
|---|---|---|
| `MCP_TIMEOUT_SECONDS` | 1800 | 30 min — backtest/hyperopt 可能很长 |
| `MAX_BACKTEST_PER_GEN` | 5 | 每个 generation 最多 5 个 backtest 候选 |
| Rate limit | per-gen counter reset | 防止一个 generation 耗尽所有 backtest budget |

---

## Decision 9: freqtrade_dev_mcp 作为 MCP server 接入 Claude Code

在 `CLAUDE.md` 或 `.claude/settings.json` 中配置 MCP server：

```json
{
  "mcpServers": {
    "freqtrade": {
      "command": "/FULL/PATH/TO/python",
      "args": ["/ABSOLUTE/PATH/TO/freqtrade_dev_mcp/src/server.py"],
      "env": { "FREQTRADE_MCP_PATH": "/path/to/freqtrade" }
    }
  }
}
```

---

## Decision 10: 状态文件位置

| 内容 | 位置 | git 追踪 |
|---|---|---|
| Freqtrade loop 状态 | `.scratch/loop_state/freqtrade/` | ❌ (gitignore) |
| MCP server 代码 | `freqtrade_dev_mcp/` | ✅ (git 追踪) |
| Loop 定义 | `docs/loop-state/FREQTRADE-LOOP.md` | ✅ |
| ADR | `docs/adr/0010-freqtrade-mcp-integration.md` | ✅ |

---

## Decision 11: 新代码排除 Ponytail

`app/services/freqtrade/` 下的代码属于业务集成层，执行 Ponytail 规则。
（不同于 `app/loop/` 的科学实验代码区）

---

## MCP Tool Schema（12 tools）

来自 `freqtrade_dev_mcp/src/server.py` 的 `list_tools()` handler。

| Tool | 关键参数 | 用途 |
|---|---|---|
| `download_candles` | `pairs`, `timeframes`, `date_range`, `exchange` | 下载历史 K 线 |
| `backtest_strategy` | `strategy_name`, `pairs`, `timerange`, `stake_amount`, `export_trades` | 回测策略 |
| `hyperopt_strategy` | `strategy_name`, `pairs`, `timerange`, `epochs`, `spaces`, `loss_function` | 超参优化 |
| `extract_backtest_data` | `result_path`, `output_format` | 解析回测结果 |
| `extract_hyperopt_data` | `hyperopt_path`, `output_format` | 解析超参结果 |
| `create_strategy` | `strategy_name`, `template`, `timeframe`, `indicators`, `minimal_roi`, `stoploss` | 生成策略文件 |
| `create_strategy_wireframe` | `strategy_name`, `style` | 生成策略框架 |
| `create_config` | `config_path`, `template`, `exchange`, `dry_run`, `pairs` | 生成配置文件 |
| `create_userdir` | `userdir`, `reset` | 初始化工作目录 |
| `list_results` | `result_type`, `strategy`, `limit` | 列出结果 |
| `get_result` | `result_id`, `include_metadata` | 获取单个结果 |
| `search_results` | `query`, `result_type`, `min_profit`, `max_drawdown`, `min_winrate` | 搜索结果 |

**Rate limit**（来自 Decision 8）:
- `backtest_strategy`: 每 generation 最多 5 次（`MAX_BACKTEST_PER_GEN=5`）
- 所有 tool 超时 1800s（`MCP_TIMEOUT_SECONDS=1800`）
