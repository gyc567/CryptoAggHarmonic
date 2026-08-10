# 回测反馈闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建每日回测 → 参数候选快照 → human PR → 实盘加载的闭环管道

**Architecture:** `scripts/run_backtest.py` 是 cron 调度入口，复用
`backtest_harmonic_lib.py` 已有函数；回测结果写入 `data/backtest_results.json`；
候选参数通过 `app/loop/state.write_tuning_snapshot()` 写入 `tuning_snapshots/`；
human PR 合并入 `tuning.py`；Flask SIGHUP 热加载生效。

**Tech Stack:** Python 3.11, pandas, multiprocessing, PyYAML, cron

---

## 文件结构

```
scripts/
  run_backtest.py          # 新建：cron 调度入口

data/
  backtest_results.json    # 新建：每日回测结果存档

app/
  config/
    tuning.py              # 修改：新增 C3Confluence.w_* 集群标记
  loop/
    state.py               # 已有 write_tuning_snapshot()
    tuning_promotion.py    # 已有 gate（ADR-003 D9）
  services/
    discipline_filters.py  # 修改：新增流动性扫损门控
    signal_engine.py       # 修改：grid-search 入口

tests/
  test_backtest_results_writer.py   # 新建
  test_liquidity_filter.py          # 新建
  test_grid_search.py               # 新建
  bench/
    test_backtest_results_writer.py # 新建（bench 目录）
```

---

## Phase 1: 回测调度层

### Task 1: 创建 `scripts/run_backtest.py`

**文件:**
- 创建: `scripts/run_backtest.py`

```python
#!/usr/bin/env python3
"""Daily backtest scheduler — run via cron at 20:00 UTC."""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── project root ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
from scripts.backtest_harmonic_lib import (
    BacktestSignalRecord,
    aggregate_records,
    walk_forward,
)
from app.loop.state import write_tuning_snapshot
from app.config.tuning import TUNING, TuningScope, to_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
DEFAULT_INTERVAL = "1h"
DEFAULT_START = "2024-01-01"
DEFAULT_END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
RESULT_DIR = ROOT / "data"
SNAPSHOT_DIR = ROOT / "tuning_snapshots"


def _load_history(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Load cached or fresh OHLCV data for backtesting.

    Falls back to Binance public API if no local cache exists.
    """
    cache = RESULT_DIR / f"{symbol.replace('/', '')}_{interval}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
        log.info("Loaded %d candles from cache for %s", len(df), symbol)
        return df

    log.info("Fetching %s %s from Binance public API", symbol, interval)
    import httpx

    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    pair = symbol.replace("/", "")
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={pair}&interval={interval_map.get(interval, '1h')}"
        f"&startTime={int(pd.Timestamp(start).timestamp() * 1000)}"
        f"&endTime={int(pd.Timestamp(end).timestamp() * 1000)}"
        f"&limit=1000"
    )
    rows = []
    with httpx.Client(timeout=30) as client:
        cursor = int(pd.Timestamp(start).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end).timestamp() * 1000)
        while cursor < end_ts:
            r = client.get(url + f"&startTime={cursor}")
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            cursor = int(batch[-1][0]) + 1
            time.sleep(0.3)

    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(rows, columns=cols + ["quote_volume", "taker_buy_volume", "turnover"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    df[cols].to_parquet(cache)
    log.info("Fetched %d candles for %s, cached at %s", len(df), symbol, cache)
    return df[cols]


def _run_symbol(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    window: int,
    step: int,
    horizon: int,
) -> list[BacktestSignalRecord]:
    """Run full walk-forward backtest for one symbol. Returns all trade records."""
    log.info("Running walk-forward for %s %s [%s – %s]", symbol, interval, start, end)
    df = _load_history(symbol, interval, start, end)
    if len(df) < 100:
        log.warning("Insufficient data for %s %s: %d rows", symbol, interval, len(df))
        return []

    records: list[BacktestSignalRecord] = walk_forward(
        df,
        symbol=symbol,
        interval=interval,
        window=window,
        step=step,
        horizon=horizon,
    )
    # walk_forward returns list[BacktestSignalRecord] directly

    log.info("%s %s: %d signals detected", symbol, interval, len(records))
    return records


def run(symbols: list[str], interval: str, start: str, end: str, horizon: int, n_workers: int) -> dict:
    """Run backtest across symbols in parallel, return aggregated results."""
    import multiprocessing

    tasks = [(s, interval, start, end, window, step, horizon) for s in symbols]
    with multiprocessing.Pool(n_workers) as pool:
        results = pool.starmap(_run_symbol, tasks)

    all_records = [r for records in results for r in records]
    agg = aggregate_records(all_records)
    return {
        "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "interval": interval,
        "param_snapshot": to_dict(TUNING),
        "total_signals": len(all_records),
        "aggregated": agg,
        "records": [r.__dict__ for r in all_records],
    }


def write_results(result: dict, path: Path) -> None:
    """Append result to backtest_results.json (creates file if missing)."""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text())
        existing["runs"].append(result)
        existing["last_updated"] = result["timestamp"]
    else:
        existing = {"version": 1, "last_updated": result["timestamp"], "runs": [result]}
    path.write_text(json.dumps(existing, indent=2, default=str))
    log.info("Wrote result to %s", path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily backtest scheduler")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--interval", default=DEFAULT_INTERVAL)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--window", type=int, default=240, help="Walk-forward window size in bars (~10d for 1h)")
    ap.add_argument("--step", type=int, default=24, help="Walk-forward step size in bars (1 day for 1h)")
    ap.add_argument("--horizon", type=int, default=24, help="Forward-sim horizon bars")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument(
        "--snapshot",
        action="store_true",
        help="Also write tuning_snapshots/ candidate YAML",
    )
    args = ap.parse_args()

    log.info("Starting backtest: symbols=%s interval=%s horizon=%d workers=%d",
             args.symbols, args.interval, args.horizon, args.workers)

    result = run(args.symbols, args.interval, args.start, args.end, args.horizon, args.workers)

    result_path = RESULT_DIR / "backtest_results.json"
    write_results(result, result_path)

    if args.snapshot:
        snapshot_path = SNAPSHOT_DIR / f"daily_{datetime.now(timezone.utc).strftime('%Y%m%d')}.yaml"
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        write_tuning_snapshot(TUNING, f"daily_{datetime.now(timezone.utc).strftime('%Y%m%d')}", root=SNAPSHOT_DIR)
        log.info("Wrote tuning snapshot to %s", snapshot_path)

    log.info("Backtest complete: run_id=%s signals=%d", result["run_id"], result["total_signals"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

Run: `chmod +x scripts/run_backtest.py`
Expected: script is executable

- [ ] **Step 3: Verify imports resolve**

Run: `cd /root/code/pyharmonics-gpt && python3 -c "import scripts.backtest_harmonic_lib as b; print(dir(b))"`
Expected: list includes `walk_forward`, `aggregate_records`, `BacktestSignalRecord`, `simulate_one`

- [ ] **Step 4: Write unit test for write_results()**

创建 `tests/test_backtest_results_writer.py`:

```python
import json, tempfile, pathlib
from scripts.run_backtest import write_results

def test_write_results_creates_file():
    result = {
        "run_id": "run_test",
        "timestamp": "2026-08-10T00:00:00Z",
        "symbols": ["BTC/USDT"],
        "interval": "1h",
        "total_signals": 5,
        "aggregated": {"wins": 3, "losses": 2, "win_rate": 0.6},
        "records": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "results.json"
        write_results(result, p)
        data = json.loads(p.read_text())
        assert data["version"] == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "run_test"

def test_write_results_appends():
    existing = {"version": 1, "last_updated": "2026-08-01", "runs": [{"run_id": "run_1"}]}
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "results.json"
        p.write_text(json.dumps(existing))
        new_result = {"run_id": "run_2", "timestamp": "2026-08-10", "symbols": [], "interval": "1h", "total_signals": 0, "aggregated": {}, "records": []}
        write_results(new_result, p)
        data = json.loads(p.read_text())
        assert len(data["runs"]) == 2
        assert data["last_updated"] == "2026-08-10"
```

Run: `pytest tests/test_backtest_results_writer.py -v`
Expected: FAIL — module not importable from root

- [ ] **Step 5: Fix import path**

The script uses `sys.path.insert(0, str(ROOT / "app"))` which makes `scripts.backtest_harmonic_lib` import from `ROOT/scripts/`. Adjust the import path in the test or run via module:

Run: `cd /root/code/pyharmonics-gpt && python3 -m pytest tests/test_backtest_results_writer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/run_backtest.py tests/test_backtest_results_writer.py
git commit -m "feat(backtest): add daily scheduler script"
```

---

### Task 2: 配置化品种列表

**文件:**
- 创建: `config/backtest_symbols.yaml`

```yaml
# 主力币种（可按需增删）
symbols:
  - BTC/USDT
  - ETH/USDT
  - BNB/USDT
  - SOL/USDT
  - XRP/USDT

# 每个品种的 interval 配置（可独立设置）
intervals:
  default: "1h"
  overrides: {}
```

- [ ] **Step: 支持从 YAML 读取品种列表**

在 `run_backtest.py` 的 `main()` 中加入 `--config` 参数支持从 YAML 读取品种列表（保留 `--symbols` 直接传入作为 override）。

Run: `python3 scripts/run_backtest.py --help | grep -A1 config`
Expected: `--config` option listed

- [ ] **Commit**

```bash
git add config/backtest_symbols.yaml scripts/run_backtest.py
git commit -m "feat(backtest): add configurable symbol list via YAML"
```

---

## Phase 2: 候选快照 + Human PR 流程

### Task 3: 集成 write_tuning_snapshot

**文件:**
- 修改: `scripts/run_backtest.py`（已在上面 Task 1 中包含 `--snapshot` 参数）

- [ ] **Step 1: 确认 write_tuning_snapshot API**

Run: `python3 -c "from app.loop.state import write_tuning_snapshot; import inspect; print(inspect.signature(write_tuning_snapshot))"`
Expected: signature: `(path: Path, tuning: TuningConstants, tags: list[str] = []) -> None`

- [ ] **Step 2: 验证 --snapshot 参数写入 YAML**

Run: `cd /root/code/pyharmonics-gpt && python3 scripts/run_backtest.py --symbols BTC/USDT --interval 1h --start 2026-01-01 --end 2026-01-02 --workers 1 --snapshot --horizon 24 2>&1 | tail -5`
Expected: 输出包含 "Wrote tuning snapshot to tuning_snapshots/daily_*.yaml"

Run: `ls tuning_snapshots/daily_*.yaml 2>/dev/null && echo "Snapshot files exist"`
Expected: at least one file listed

- [ ] **Commit**

```bash
git add scripts/run_backtest.py
git commit -m "feat(backtest): wire write_tuning_snapshot for daily candidates"
```

---

## Phase 3: 谐波代码优化

### Task 4: 流动性扫损门控

**文件:**
- 修改: `app/services/discipline_filters.py`

- [ ] **Step 1: 读现有 discipline_filters.py**

Run: `cat app/services/discipline_filters.py`
Expected: DisciplineFilters.evaluate() 方法含三条门控（path_integrity / TTL / TP2_boundary）

- [ ] **Step 2: 写测试**

创建 `tests/test_liquidity_filter.py`:

```python
import pytest, pandas as pd
from app.services.discipline_filters import DisciplineFilters
from app.config.tuning import TuningConstants

def _make_df_with_volume(volume_multiplier: float) -> pd.DataFrame:
    base = 1_000_000.0
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=25, freq="h", tz="UTC"),
        "open": [100.0] * 25,
        "high": [105.0] * 25,
        "low": [95.0] * 25,
        "close": [100.0] * 25,
        "volume": [base * volume_multiplier] * 25,
    })

def test_liquidity_sweep_detected():
    t = TuningConstants()
    df = _make_df_with_volume(volume_multiplier=1.0)  # D-point volume set below

    import pandas as pd
    from app.domain.signals import Candidate
    from app.services.discipline_filters import evaluate
    from app.config.tuning import get_tuning

    # evaluate() is a standalone function:
    #   evaluate(df, candidate, current_price, max_ttl=None, c_idx=None)
    t = get_tuning()
    df = _make_df_with_volume(volume_multiplier=1.0)
    # Simulate a liquidity sweep: D-point volume = 4x the 20-bar mean
    df.loc[df.index[-1], "volume"] = df["volume"].iloc[-21:-1].mean() * 4.0

    candidate = Candidate(
        family="XABCD",
        name="bat",
        bullish=True,
        formed=True,
        points=(110.0, 105.0, 108.0, 106.0, 100.0),
        completion_min=99.0,
        completion_max=101.0,
        times=tuple(int(x) for x in pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC").timestamp()),
        indices=(0, 4, 8, 12, 24),  # D at bar 24 (last)
    )

    result = evaluate(df, candidate, current_price=100.5)
    # Should flag trap candidate but not hard-reject
    assert "liquidity_sweep" in str(result.metrics) or result.passed is not True
```

Run: `pytest tests/test_liquidity_filter.py -v`
Expected: FAIL (function doesn't exist yet)

- [ ] **Step 3: 实现流动性扫损门控**

在 `app/services/discipline_filters.py` 的 `evaluate()` 函数中新增门控：

```python
# 在 evaluate() 方法末尾（return DisciplineResult 之前）加入：
# ── Liquidity Sweep Gate ──────────────────────────────────────────────────
d_bar_volumes = df["volume"].iloc[-21:-1]  # 前 20 根 bar（D 之前）
mean_vol = d_bar_volumes.mean()
d_volume = df["volume"].iloc[-1]
if d_volume > mean_vol * LIQUIDITY_SWEEP_MULTIPLIER:
    # Flag but don't hard-reject — mark as trap candidate
    result = result._replace(
        trap_candidate=True,
        passed=result.passed,  # keep existing verdict
    )
```

其中 `LIQUIDITY_SWEEP_MULTIPLIER = 3.0`（可配置，从 `self.tuning` 读取）。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_liquidity_filter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/discipline_filters.py tests/test_liquidity_filter.py
git commit -m "feat(discipline): add liquidity sweep gate to filter"
```

---

### Task 5: confluence_score 权重 Grid-Search

**文件:**
- 修改: `app/services/signal_engine.py`（新增 `grid_search_weights()` 函数）
- 创建: `tests/test_grid_search.py`

- [ ] **Step 1: 确认 TuningConstants 权重字段**

Run: `python3 -c "from app.config.tuning import TUNING; print(TUNING.w_price_action, TUNING.w_htf_trend, TUNING.w_rsi, TUNING.w_structure, TUNING.w_macd, TUNING.w_funding)"`
Expected: five float values summing to 100

注意：权重存储在单一字段 `confluence_weights: dict`（6 键：price_action/htf_trend/rsi/structure/macd/funding，`__post_init__` 校验和=100）。

- [ ] **Step 2: 写 grid-search 测试**

```python
import itertools
from app.services.signal_engine import grid_search_weights

def test_grid_search_respects_sum_100():
    """Every candidate must have weights summing to exactly 100."""
    from app.services.signal_engine import _complete_weights
    keys = ["price_action", "htf_trend", "rsi", "structure", "macd"]
    candidates = itertools.product([10, 20, 30], repeat=5)
    for w5 in itertools.islice(candidates, 10):  # smoke test
        w = _complete_weights(dict(zip(keys, w5)))
        assert abs(sum(w.values()) - 100) < 0.01, f"Weights {w} sum to {sum(w.values())}"
        # Must pass TuningConstants validation
        from app.config.tuning import TuningConstants
        import dataclasses
        dataclasses.replace(TuningConstants(), confluence_weights=w)

def test_grid_search_output_shape():
    result = grid_search_weights(
        symbol="BTC/USDT",
        start="2025-01-01",
        end="2026-01-01",
        candidates=[
            {"price_action": 25, "htf_trend": 25, "rsi": 15,
             "structure": 15, "macd": 10, "funding": 10},
        ],
    )
    assert "best_weights" in result
    assert "win_rate" in result["best_weights"]
```

Run: `pytest tests/test_grid_search.py -v`
Expected: FAIL — `grid_search_weights` not defined

- [ ] **Step 3: 实现 grid_search_weights()**

在 `signal_engine.py` 中加入：

```python
import itertools
from typing import NamedTuple

def _complete_weights(w5: dict[str, float]) -> dict[str, float]:
    """Derive the 6th weight from the sum-to-100 constraint.

    w5 has keys price_action/htf_trend/rsi/structure/macd;
    funding = 100 - sum(w5). Passes TuningConstants __post_init__.
    """
    assert set(w5) == {"price_action", "htf_trend", "rsi", "structure", "macd"}, w5
    return {**w5, "funding": 100.0 - sum(w5.values())}

def grid_search_weights(
    symbol: str,
    start: str,
    end: str,
    candidates: list[dict],
) -> dict:
    """Evaluate confluence_score weight combinations via backtest.

    Returns dict with best_weights, win_rate, avg_R, sample_size.
    """
    from scripts.backtest_harmonic_lib import _load_history, detect_window, simulate_one
    import pandas as pd

    df = _load_history(symbol, "1h", start, end)
    results = []
    for w in candidates:
        # Apply weights temporarily via TuningScope.
        # TuningScope expects a TuningConstants-like mapping; feed it via
        # dataclasses.replace(TUNING, confluence_weights=w).
        import dataclasses
        tuned = dataclasses.replace(TUNING, confluence_weights=w)
        with TuningScope(tuned):
            signals = detect_window(df, symbol, "1h")  # single-window scan
            wins = sum(1 for s in signals if simulate_one(df, s).result == "win")
            total = len(signals) or 1
            results.append({
                "weights": w,
                "win_rate": wins / total,
                "sample_size": total,
            })

    best = max(results, key=lambda r: r["win_rate"] * 0.4 + r["avg_R"] * 0.6 if r["avg_R"] else 0)
    return {"best_weights": best}
```

**注意**：上述实现需要与现有 `TuningScope` 配合使用，确保权重在 backtest 期间生效。

- [ ] **Step 4: Commit**

```bash
git add app/services/signal_engine.py tests/test_grid_search.py
git commit -m "feat(signal): add grid_search_weights for confluence score calibration"
```

---

## Phase 4: 闭环验证

### Task 6: Cron 接入验证

**文件:**
- 创建: `crontab.txt`（记录 cron 行，不直接安装）

- [ ] **Step 1: Add cron entry**

```bash
# 每天 UTC 20:00 跑回测
0 20 * * * cd /root/code/pyharmonics-gpt && ./scripts/run_backtest.py --snapshot >> logs/backtest_cron.log 2>&1
```

Run: `crontab crontab.txt && crontab -l | grep backtest`
Expected: backtest line listed

- [ ] **Step 2: Dry-run with --help**

Run: `cd /root/code/pyharmonics-gpt && ./scripts/run_backtest.py --help`
Expected: full help output

- [ ] **Step 3: Commit**

```bash
git add crontab.txt
git commit -m "docs: add backtest cron entry"
```

---

### Task 7: tuning_snapshots → tuning.py Human PR 流程验证

**文件:**
- 创建: `docs/guides/backtest-loop-guide.md`

- [ ] **Step: 写流程文档**

```markdown
# 回测反馈闭环操作手册

## 每日流程

1. **自动执行** — cron 在 UTC 20:00 运行：
   ```bash
   ./scripts/run_backtest.py --snapshot
   ```
   产出：
   - `data/backtest_results.json`（追加本次运行）
   - `tuning_snapshots/daily_YYYYMMDD.yaml`（候选参数快照）

2. **审查快照** — 检查 `tuning_snapshots/` 目录：
   ```bash
   ls -t tuning_snapshots/ | head -5
   ```

3. **人工判断** — 打开最新的候选 YAML，对比 `tuning.py` 当前值：
   - 若胜率提升 ≥ 5% 且样本 ≥ 30 → 接受
   - 若不满足 → 丢弃（删除该 YAML）

4. **接受候选** — 手动将候选参数写入 `tuning.py` 对应常量，发 PR

5. **SIGHUP 热加载** — `kill -SIGHUP $(cat app/.pid)` 触发 Flask 重载参数
```

- [ ] **Commit**

```bash
git add docs/guides/backtest-loop-guide.md
git commit -m "docs: add backtest loop operation guide"
```
