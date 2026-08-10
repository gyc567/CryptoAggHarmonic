# 回测反馈闭环平台 — 设计文档

**状态**：草稿
**创建**：2026-08-10
**目标**：搭建「历史数据回测 → 参数自动优化 → 实盘信号复用」的每日闭环

---

## 1. 背景与目标

谐波形态分析系统（Harmonic Pattern + Divergence）目前有独立的回测框架
（`scripts/backtest_harmonic_lib.py`），但存在以下问题：

- 回测是手动触发的一次性脚本，无定时执行机制
- 回测结果以临时 JSON 为主，无结构化存储
- 历史表现数据未与实盘分析流程打通
- 谐波形态识别代码（PRZ 投影、纪律过滤、评分权重）有优化空间

**目标**：实现双向反馈闭环——每日收盘后自动跑回测、将候选参数变更写入
`tuning_snapshots/` 待审区、经 human PR 确认后合并入 `tuning.py`（遵守 ADR-003 D9），
实盘分析通过 SIGHUP 热加载新参数。

---

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                     每日收盘后触发（crontab）                       │
│           20:00 UTC 执行 scripts/run_backtest.py                   │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              回测 Pipeline (scripts/run_backtest.py)              │
│                                                               │
│  输入：品种列表 × 时间范围 × 参数网格                              │
│  流程：walk-forward → 候选过滤 → 信号评分 → 模拟交易               │
│  输出：backtest_results.json (详细记录)                           │
│        tuning_snapshots/YYYY-MM-DD_candidate.yaml (候选参数)       │
│        git commit + push (候选快照自动记录)                          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              实盘分析流程 (AnalysisOrchestrator)                   │
│                                                               │
│  K线 → 形态检测 → 纪律过滤 → 信号评分 → Signal                    │
│              ↑                                                  │
│      从 app/config/tuning.py 加载当前最优参数                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 组件设计

### 3.1 回测 Pipeline (`scripts/run_backtest.py`)

**职责**：每日定时执行完整回测流程，判定是否更新参数。

**输入**：
- 品种列表：`BTC/USDT`, `ETH/USDT`, `BNB/USDT`, `SOL/USDT`, `XRP/USDT`（可配置）
- 时间范围：默认近 2 年
- 并行度：CPU 核心数（`os.cpu_count()`）

**流程**：

```
1. load_candidates(symbol, interval, start, end)
      → 调用 pyharmonics_adapter 加载历史 K 线
      → 执行 HarmonicSearch + DivergenceSearch

2. for each 候选窗口 in walk_forward(windows):
      → discipline_filter()  — 路径完整性 / TTL / TP2 边界
      → signal_engine.extract_candidates()
      → score_candidate()
      → simulate_trades(long/short, stop/TP1/TP2)
      → 记录每笔交易结果

3. aggregate_results(all_trades)
      → 按 (symbol, pattern, interval) 分组
      → 计算：胜率、 avg_R、 max_drawdown、 total_trades、 avg_bars_held

4. compare_with_baseline(new_results, existing_json)
      → 若新结果显著优于基线（见 3.2 判定规则）→ 触发参数更新

5. write_results_json(results, path)
      → 追加到 backtest_results.json（带 timestamp）
```

**输出**：
- `data/backtest_results.json` — 全量历史结果（含每次运行的 snapshot）
- `app/config/tuning.py`（条件更新）
- Git commit + push（参数变更时）

### 3.2 参数更新机制

**判定规则**：以下条件**同时满足**才更新 `tuning.py`：

| 指标 | 条件 | 说明 |
|------|------|------|
| 胜率提升 | 新胜率 > 基线胜率 + 5% | 排除随机波动 |
| 样本量 | 新样本数 ≥ 30 笔 | 保证统计显著性 |
| 最大回撤 | 新 max_drawdown < 基线 | 风险不恶化 |

**更新流程**：
```
1. 读取现有 tuning.py 目标常量（如 fib_tp1, fib_tp2, a_grade_min 等）
2. 用新参数值覆盖对应常量
3. 写入临时文件 → 语法检查（python -c "import ast"）
4. 替换原文件
5. git add + commit -m "chore(tuning): auto-update from backtest YYYY-MM-DD"
6. git push origin main
```

**并发保护**：使用文件锁（`fcntl.flock`），确保同一时刻只有一个进程在写入。

### 3.3 谐波/和谐形态代码优化（同步进行）

在搭 pipeline 过程中发现并修复以下代码问题：

#### 3.3.1 PRZ 投影精度

当前 PRZ 由 XA 回撤/延伸区间与 BC 腿投影区间取交集得到。
问题：两区间宽度差异大时交集过窄，容易漏掉有效形态。

**优化**：引入加权汇聚评分——当两区间中心点距离 < 区间平均宽度的 50% 时，
额外加分；距离 < 25% 时加更多分。避免因交集过严导致假阴性。

#### 3.3.2 纪律过滤器 (`app/services/discipline_filters.py`)

当前三条门控：路径完整性（PRZ 是否已被穿越）、TTL（C 点距今是否过久）、
TP2 边界（价格是否已穿越第二目标）。

**优化**：
- `max_d_age_bars` 已在 TuningConstants 中（tuning.py:114），无需移动
- `DEFAULT_TTL_BARS`（锚定 C 点，=40）和 `max_d_age_bars`（锚定 D 点，=20）是两条独立的 TTL
  门控，均已可配置；Phase 3 需确保两条门控独立调参
- 增加「流动性扫损检测」门控：若 D 点成交额 > 前 20 根 bar 均值的 3 倍，
  标记为 trap candidate，强制进入观察模式（不直接拒绝但降权）

#### 3.3.3 信号评分权重 (`app/services/signal_engine.py` confluence_score)

当前六因子权重：
- price_action(25) + htf_trend(25) + rsi(15) + structure(15) + macd(10) + funding(10)

**问题**：权重未经过回测校准，可能偏离最优分布。

**优化**：回测阶段用网格搜索测试权重组合。由于 TuningConstants 验证六因子权重和必须等于 100，实际搜索空间为 5 自由度（6 个权重，第 6 个由 100 - sum(w1..w5) 决定）。每组权重跑全量数据，取 (胜率 × 0.4 + avg_R_norm × 0.6) 综合最优的一组。结果写入 `tuning_snapshots/YYYY-MM-DD_candidate.yaml`，不直接修改 tuning.py。

#### 3.3.4 形态覆盖扩展

当前 walk-forward 仅覆盖 Gartley / Bat / Butterfly / Crab / DeepCrab。
扩展支持：
- Shark（需确认已在 `PATTERNS` 字典但被手动剔除的原因）
- RSI Divergence + MACD Divergence 单独打分
- 双指标共振（RSI Regular + MACD Regular 同时出现）的加权加成

---

## 4. 数据结构

### 4.1 `backtest_results.json` 格式

```json
{
  "version": 1,
  "last_updated": "2026-08-10T20:00:00Z",
  "runs": [
    {
      "run_id": "run_20260810",
      "timestamp": "2026-08-10T20:00:00Z",
      "symbols": ["BTC/USDT", "ETH/USDT"],
      "interval": "1h",
      "param_snapshot": { "fib_tp1": 0.382, "fib_tp2": 0.618, ... },
      "aggregated": {
        "BTC/USDT": {
          "Gartley": {
            "total_trades": 87,
            "win_rate": 0.713,
            "avg_R": 1.84,
            "max_drawdown": -0.23,
            "avg_bars_held": 12.4
          }
        }
      }
    }
  ]
}
```

### 4.2 `tuning.py` 更新字段

以下常量在回测后可能被更新（写入 `app/config/tuning.py`）：

```python
class C1Geometry(TuningConstants):
    fib_tp1: float = 0.382      # 原值，可能更新
    fib_tp2: float = 0.618      # 原值，可能更新
    fib_tp3: float = 1.272

class C2Discipline(TuningConstants):
    max_d_age_bars: int = 20     # 从硬编码改为可搜索
    staleness_atr_threshold: float = 3.0

class C3Confluence(TuningConstants):
    # confluence_score 权重（回测校准后更新）
    w_price_action: float = 25.0
    w_htf_trend: float = 25.0
    w_rsi: float = 15.0
    w_structure: float = 15.0
    w_macd: float = 10.0
    w_funding: float = 10.0

class C4Grade(TuningConstants):
    a_grade_min: float = 70.0   # 可能上调
    b_grade_min: float = 60.0
    c_grade_min: float = 45.0
    min_net_rr_tp2: float = 1.5  # 可能调整
```

---

## 5. 触发机制

### 每日定时触发

```cron
# 每天 UTC 20:00 跑回测（美股收盘后 / 加密市场流动性最好时段）
0 20 * * * cd /root/code/pyharmonics-gpt && ./scripts/run_backtest.py >> logs/backtest_cron.log 2>&1
```

### Supabase Edge Function 触发（备选）

在 Supabase 数据库新建 `scheduled_runs` 表，Edge Function 每小时检查
`next_run <= now()` 的记录并触发执行。允许人工干预触发时间。

---

## 6. 实施计划

### Phase 1: 回测框架复用 + 调度层
- [ ] 新建 `scripts/run_backtest.py` 作为调度入口
- [ ] 复用 `backtest_harmonic_lib.py` 已有函数：write_json / report / walk_forward / aggregate_records / BacktestSignalRecord DTO
- [ ] 不重写已有的 walk_forward / simulate_one / aggregate_records
- [ ] 实现 `backtest_results.json` 的读写逻辑
- [ ] 品种列表配置化（`config/backtest_symbols.yaml`）
- [ ] 单机并行化（`multiprocessing.Pool`）

### Phase 2: 参数候选区 + Human PR
- [ ] 创建 `tuning_snapshots/YYYY-MM-DD_candidate.yaml`（候选参数）
- [ ] tuning_promotion.py 已有 gate（ADR-003 D9），不覆盖 tuning.py
- [ ] 参数判定规则（胜率提升 + 样本量 + 最大回撤）→ 写入候选 YAML
- [ ] 参数判定规则实现（胜率提升 + 样本量 + 最大回撤）
- [ ] Git commit tuning_snapshots 候选 YAML（记录每次运行参数版本）
- [ ] 不 push（human PR 是主动行为，不自动合并）

### Phase 3: 谐波代码优化
- [ ] PRZ 投影汇聚评分优化
- [ ] discipline_filters 流动性扫损门控（新增，其余已可配置）
- [ ] confluence_score 权重 grid-search（5 自由度约束）
- [ ] 形态覆盖扩展（Shark / Divergence 共振）

### Phase 4: 闭环验证
- [ ] 每日 cron 接入 `scripts/run_backtest.py`
- [ ] tuning_snapshots 候选参数 → human PR → tuning.py 合并流程验证
- [ ] SIGHUP 热加载验证（参数更新后 Flask 无重启实盘分析正确）
- [ ] 回滚机制（丢弃 snapshot，Git revert tuning.py）

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 自动更新参数反而降低胜率 | 判定阈值 5% + 样本量门控（≥30）双重保护 |
| tuning.py 写入撞 gate | 不直接写 tuning.py，写入 tuning_snapshots/ + human PR |
| tuning_snapshots 并发写入冲突 | `fcntl.flock` 文件锁 |
| 回测过拟合实盘失效 | walk-forward 窗口错开 + 最大回撤约束 |
| Git push 失败（网络） | 重试 3 次，失败则写 error log 人工介入 |
