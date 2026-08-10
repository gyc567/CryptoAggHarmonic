# 回测反馈闭环操作手册

## 目标

每日收盘后自动跑谐波形态回测，产出候选参数快照；人工审查后通过 PR
合并入 `tuning.py`，SIGHUP 热加载生效，实盘分析复用新参数。

```
每日 20:00 UTC cron
      │
      ▼
scripts/run_backtest.py --config config/backtest_symbols.yaml --snapshot
      │
      ├──► data/backtest_results.json   (全量结果存档，追加式)
      └──► tuning_snapshots/daily_*.yaml (候选参数快照，dedupe 按 sha)
                                        │
                                        ▼
                           人工审查（人类门控，ADR-003 D9）
                                        │
                   胜率提升 ≥5% 且样本 ≥30？
                                        │
                               是 ▼     否 ▼
                        PR 修改 tuning.py    丢弃（删除 YAML）
                                        │
                                        ▼
                        SIGHUP 热加载 → 实盘复用
```

## 每日流程

### 1. 自动执行

cron 行（`crontab.txt`）：
```
0 20 * * * cd /root/code/pyharmonics-gpt && ./scripts/run_backtest.py --config config/backtest_symbols.yaml --snapshot >> logs/backtest_cron.log 2>&1
```

手动执行同款命令：
```bash
cd /root/code/pyharmonics-gpt && ./scripts/run_backtest.py --config config/backtest_symbols.yaml --snapshot
```

### 2. 查看结果

```bash
# 最近一次回测汇总
python3 -c "import json; d=json.load(open('data/backtest_results.json')); r=d['runs'][-1]; print(r['run_id'], r['total_signals'], r['aggregated'])"

# 候选快照列表
ls -t tuning_snapshots/ | head -5
```

### 3. 人工审查（关键步骤）

1. 打开最新 `tuning_snapshots/daily_*.yaml`，对比 `app/config/tuning.py` 当前值
2. 判断依据（**全部满足才接受**）：
   - 胜率提升 ≥ 5%（对比同品种历史基线）
   - 样本量 ≥ 30 笔（统计显著性）
   - 最大回撤不恶化
3. 接受 → 手动将候选参数写入 `app/config/tuning.py` 对应常量，发 PR
4. 拒绝 → 删除该 YAML（`rm tuning_snapshots/daily_*.yaml`）

> **合规约束（ADR-003 D9）**：绝不自动覆盖 `tuning.py`。loop 只能产出
> 候选快照，合并必须经 human PR + SIGHUP。

### 4. 参数生效

```bash
# 部署新 tuning.py 后热加载（无需重启 Flask）
kill -SIGHUP $(cat /path/to/app.pid)
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `./scripts/run_backtest.py --help` | 查看全部参数 |
| `./scripts/run_backtest.py --symbols BTC/USDT --start 2025-06-01 --end 2025-07-01 --workers 1` | 单品种单月（调试用） |
| `./scripts/run_backtest.py --min-grade B` | 只统计 A/B 级信号 |
| `./scripts/download_backtest_data.py --symbol ETHUSDT --interval 4h` | 补充下载历史数据 |
| `python3 -m pytest tests/test_grid_search.py` | 权重搜索测试 |

## 数据缓存

- 历史 K 线缓存：`data/backtest/binance/{SYMBOL}/{interval}.parquet`
- 数据源：`data-api.binance.vision`（api.binance.com 从受限网络返回 451）
- 缓存无数据时自动网络下载；建议每周 `download_backtest_data.py` 刷新

## 故障排查

- **cron 不跑**：检查 `logs/backtest_cron.log`；确认 shebang 指向项目 venv
- **451 错误**：`_binance_stdlib` 自动 fallback 到 vision host；若仍失败
  检查出口 IP 地域限制
- **snapshot 未生成**：确认 `--snapshot` 参数；dedupe 相同参数不重复写
- **权重搜索慢**：`grid_search_weights(n_workers=N)` 当前实现是单进程
  （多进程需预导入依赖）；小数据集（`df.tail(4000)`）单组约 80s
