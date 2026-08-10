# 自动进化回测与优化方案 — Backtest Loop Engineering

> **状态**：Draft
> **日期**：2026-08-10
> **与 Loop Engineering Plan 的关系**：本文档是 `docs/loop-engineering-plan.md` 的**交易回路专项扩展**，
> 专注于将 `.scratch/backtest` 从形态检测工具升级为能产出稳定正向收益的交易策略系统。
> 所有新增模块均接入已有 `app/loop/` CMA-ES + Pareto + Maker-Checker 框架。

---

## 1. 背景与问题陈述

### 1.1 当前系统能力

cryptoagg 现有核心能力：

| 能力 | 现状 | 评估 |
|------|------|------|
| Harmonic pattern detection (v4) | 17+ 形态类型 | 基础，胜率有限 |
| GPT signal analysis | Maker-Checker LLM 验证 | 已有框架 |
| Loop feedback | CMA-ES 遗传搜索 + Pareto 前沿 | 已有框架 |
| Backtest harness | `.scratch/backtest/` 多目标、YAML、hot-swap | 临时目录，非生产级 |
| TradingView bridge | 实时推送信号 | 已有 |

### 1.2 核心问题

**纯和谐形态检测胜率有限**（行业实测 40-65%，视品种和过滤而定），
要产生稳定正向收益，必须补齐：

1. **过滤不足** — 当前"检测到形态就发信号"，无 confluence 确认
2. **风控缺失** — 无标准化 SL/TP/仓位规则
3. **回测不严** — 无 walk-forward、无多资产验证、无真实成本
4. **执行无闭环** — 回测结果未反馈到 loop 参数优化

### 1.3 目标

把 cryptoagg 从 **"形态检测工具"** 升级为 **"自进化的交易策略信号系统"**：

```
形态检测 → 信号打分 → Confluence 过滤 → 标准交易规则 → Walk-forward 回测
     ↑                                                                 ↓
     ←──────────────── Loop 反馈（GPT Agent 驱动）──────────────────────
```

---

## 2. 整合架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         cryptoagg BACKTEST LOOP ENGINEERING                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │         LAYER 1: Signal Quality — Confluence Filter + Scoring        │    │
│  │                                                                      │    │
│  │  Pattern Detector ──→ Confidence Scorer ──→ Confluence Filter        │    │
│  │         │                    │                     │                  │    │
│  │         ▼                    ▼                     ▼                  │    │
│  │  (forming/          Score 0-100           HTF Trend + RSI Div        │    │
│  │   formed)           ≥70 才输出              Volume Spike +            │    │
│  │                                          ADX Filter                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    +                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │         LAYER 2: Trading Rules — Standard Strategy Protocol          │    │
│  │                                                                      │    │
│  │  Entry: Price in PRZ + Confirmation candle close                     │    │
│  │  SL:    X points outside OR 20-30% of pattern height                 │    │
│  │  TP:    TP1=0.382 CD / TP2=C point / TP3=1.272-1.618 extension       │    │
│  │  TS:    Move SL to cost after TP1 hit                                │    │
│  │  Size:  Fixed risk 0.5-1.5% equity + ATR-based position sizing       │    │
│  │  Max:   N concurrent positions + correlation filter                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    +                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │         LAYER 3: Production Backtest (Walk-Forward)                  │    │
│  │                                                                      │    │
│  │  bench/                                                              │    │
│  │  ├── run_backtest_v3.py          # 已有，升级成生产级                 │    │
│  │  ├── walk_forward.py             # 滚动窗口训练 + 样本外验证           │    │
│  │  ├── multi_asset_runner.py       # 多资产、多时间框架同时测试          │    │
│  │  └── cost_model.py               # 手续费、滑点、资金费率               │    │
│  │                                                                      │    │
│  │  Core Metrics: Profit Factor / Expectancy / Sharpe / Sortino /       │    │
│  │                Max Drawdown / Calmar / Win Rate / Avg R-multiple      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    +                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │         LAYER 4: Loop Feedback — CMA-ES + GPT Agent                  │    │
│  │                                                                      │    │
│  │  Backtest Result ──→ GPT Agent 分析 ──→ 建议新过滤参数 / 形态权重      │    │
│  │         │                              │                             │    │
│  │         ▼                              ▼                             │    │
│  │  app/loop/ (已有)              Pareto Front 更新                      │    │
│  │  CMA-ES Search                 New candidates generated               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    +                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │         LAYER 5: Freqtrade Integration (Execution Layer)             │    │
│  │                                                                      │    │
│  │  freqtrade_compat/                                                   │    │
│  │  ├── strategy_generator.py      # 把 harmonic+confluence 导出为       │    │
│  │  │                              #   Freqtrade IStrategy              │    │
│  │  ├── hyperopt_runner.py         # 大规模参数优化                      │    │
│  │  └── paper_trading.py           # 纸盘跟踪信号表现                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Signal Quality Layer（信号质量层）

### 3.1 Confidence Score（0-100）

每个检测到的形态计算综合分数：

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| Fibonacci 误差 | 25% | 误差越小分数越高（误差 ≤ 0.5% → 100分） |
| 形态完成度 | 20% | `formed` = 100分，`forming` = 60分 |
| 历史同类型胜率 | 20% | 从 backtest 数据集查询同类形态 win rate，加权 |
| PRZ 收盘确认 | 15% | 触及 PRZ 后收盘在区域内 = 100分 |
| 成交量确认 | 10% | Volume spike at completion = 100分 |
| HTF 趋势一致 | 10% | 4H/日线趋势与信号方向一致 = 100分 |

**输出门槛**：Score ≥ 70 才输出信号；forming 形态只发"预警"不触发入场。

### 3.2 Confluence Filter（强制硬过滤）

所有过滤条件必须同时满足：

```
IF (
    HTF_trend_aligned      AND     # 4H/日线 EMA20 方向与信号方向一致
    RSI_not_oversold       AND     # RSI 14 不在超卖区（做多）或超买区（做空）
    volume_confirmed       AND     # 形态完成时成交量 > 20日均值 1.2x
    ADX_filter_passed      AND     # ADX > 20（排除震荡市）
    price_in_prz           AND     # 收盘价在 PRZ 内
    NOT choppy_market              # ATR 比率过滤，排除横盘
)
THEN signal = ENABLED
ELSE signal = SUPPRESSED
```

**实现位置**：`app/domain/signals.py` 新增 `ConfluenceFilter` 类。

### 3.3 Pattern Priority（形态优先级）

根据公开回测数据，设置不同形态的默认权重：

| 优先级 | 形态 | 默认权重 | 启用状态 |
|--------|------|----------|----------|
| P0 | Shark | 1.2 | 默认启用 |
| P0 | Cypher | 1.1 | 默认启用 |
| P0 | Butterfly | 1.0 | 默认启用 |
| P1 | Gartley | 0.9 | 默认启用 |
| P1 | Bat | 0.9 | 默认启用 |
| P2 | Crab | 0.7 | 默认禁用，需手动开启 |
| P2 | Deep Crab | 0.6 | 默认禁用 |

**配置位置**：`patterns/registry.yaml` 增加 `default_weight` 和 `default_enabled` 字段。

### 3.4 Lookahead Bias 防护

```
规则：
1. 只在蜡烛收盘后确认形态（close price 确认）
2. forming 形态最多用于"预警"（不触发入场）
3. 入场信号必须等待确认蜡烛（confirmation candle）
```

---

## 4. Trading Rules Layer（交易规则层）

### 4.1 标准化入场 / 出场规则（基于 Scott Carney）

```python
class HarmonicStrategy:
    # 入场条件
    def entry_signal(self, pattern, confluence) -> bool:
        return (
            pattern.status == "formed" and
            pattern.score >= 70 and
            confluence.all_passed() and
            pattern.prz.contains(pattern.completion_price)
        )

    # 止损
    def stop_loss(self, pattern) -> float:
        # X 点之外 或 形态高度的 20-30%
        x_distance = abs(pattern.X - pattern.completion_price)
        pattern_height = abs(pattern.D - pattern.completion_price)
        return min(
            pattern.completion_price - x_distance,  # X 点外
            pattern.completion_price - pattern_height * 0.25  # 形态高度 25%
        )

    # 分批止盈
    def take_profit(self, pattern, tier: int) -> float:
        cd_leg = abs(pattern.D - pattern.C)
        if tier == 1:
            return pattern.completion_price + cd_leg * 0.382
        elif tier == 2:
            return pattern.completion_price + cd_leg * 0.618  # C 点
        else:
            return pattern.completion_price + cd_leg * 1.272  # 扩展

    # 移动止损
    def trailing_stop(self, pattern, current_pnl: float) -> float:
        if current_pnl >= 1.0:  # 达到 TP1
            return 0  # 移到成本价
        return self.stop_loss(pattern)
```

### 4.2 仓位管理规则

```python
class PositionSizing:
    RISK_PER_TRADE = 0.01  # 1% 账户权益
    MAX_CONCURRENT = 3
    CORRELATION_THRESHOLD = 0.7

    def size_position(self, account_equity: float, stop_loss_distance: float, atr: float) -> float:
        risk_amount = account_equity * self.RISK_PER_TRADE
        return risk_amount / stop_loss_distance

    def correlation_filter(self, new_signal: Signal, open_positions: list) -> bool:
        """BTC/ETH 不能同时满仓同方向"""
        # 计算与现有持仓的相关性，超过阈值则拒绝
        pass
```

### 4.3 StrategyProtocol 接口

为后续 Freqtrade 兼容，所有规则封装为统一接口：

```python
from typing import Protocol

class StrategyProtocol(Protocol):
    def entry_signal(self, pattern, confluence) -> bool: ...
    def stop_loss(self, pattern) -> float: ...
    def take_profit(self, pattern, tier: int) -> float: ...
    def trailing_stop(self, pattern, current_pnl: float) -> float: ...
    def size_position(self, account_equity: float, stop_loss_distance: float, atr: float) -> float: ...
```

---

## 5. Backtest Layer（回测与验证体系）

### 5.1 目录升级

```
bench/                           # 从 .scratch/backtest 移出，正式纳入项目
├── run_backtest_v3.py           # 已有，修复后纳入
├── walk_forward.py              # 滚动窗口优化（已有 in app/loop/，需迁移）
├── multi_asset_runner.py        # 多资产、多时间框架测试 [NEW]
├── cost_model.py                # 真实成本模型 [NEW]
├── metrics_collector.py         # 核心指标计算 [NEW]
└── report_generator.py          # HTML 回测报告 [NEW]
```

### 5.2 必须实现的指标

| 指标 | 公式 | 合格门槛 |
|------|------|----------|
| Profit Factor | Gross Profit / Gross Loss | > 1.3 |
| Expectancy | Win% × Avg Win - Loss% × Avg Loss | > 0 |
| Sharpe Ratio | (Return - Rf) / StdDev | > 0.8 |
| Sortino Ratio | (Return - Rf) / DownsideStdDev | > 1.0 |
| Max Drawdown | Peak - Trough | < 15% |
| Calmar Ratio | Annual Return / Max DD | > 1.0 |
| Win Rate | Winning trades / Total trades | > 40% |
| Avg R-Multiple | Avg Win / Avg Loss | > 1.2 |

### 5.3 Walk-Forward Optimization

```
训练窗口：6 个月
测试窗口：2 个月
步进：1 个月

训练集 ──────────────→ 测试集
     6M        2M
              训练集 ──────────────→ 测试集
                   6M        2M
```

**验收标准**：样本外 Sharpe > 0.8，MaxDD < 15%，连续 3 个窗口达标。

### 5.4 多资产、多时间框架验证

测试范围：
- **资产**：BTC、ETH、SOL + 主流山寨（ADA、DOT、AVAX）
- **时间框架**：15m、1H、4H
- **市场环境**：趋势市、震荡市、high volatility

### 5.5 真实成本模型

```python
class CostModel:
    def __init__(
        self,
        maker_fee: float = 0.001,      # 0.1% 做市商手续费
        taker_fee: float = 0.002,       # 0.2% taker 手续费
        slippage_bp: float = 5,          # 5 basis points 滑点
        funding_rate: float = 0.0001,   # 合约资金费率（每小时）
    ): ...
```

---

## 6. Loop Feedback — 闭环接入

### 6.1 回测结果 → Loop 参数更新

```
Walk-forward 结果（样本外 Sharpe、MaxDD、Profit Factor）
        │
        ▼
GPT Agent 分析 ──→ 建议调整：
  - confluent filter 阈值（RSI、ADX、volume）
  - 形态权重（Shark↑ / Crab↓）
  - SL/TP 比例
        │
        ▼
Pareto Front 更新（app/loop/ 已有框架）
        │
        ▼
新候选进入 CMA-ES 搜索
```

### 6.2 关键差异：Backtest Loop vs 已有 Trading Loop

| 维度 | 已有 Trading Loop（app/loop/） | Backtest Loop（本文档） |
|------|-------------------------------|------------------------|
| 优化目标 | M4 fitness（Sharpe/Expectancy/MaxDD） | 样本外 Profit Factor + Sharpe |
| 变异来源 | CMA-ES 遗传变异 | 回测结果 GPT 分析 |
| 候选来源 | 随机生成 + 边界变异 | 新过滤规则 + 形态权重调整 |
| 验证方式 | 样本外验证（oos_validator） | Walk-forward 滚动验证 |
| 上线门槛 | Loop Readiness Score ≥ 58 | Profit Factor > 1.3 + 样本外 Sharpe > 0.8 |

### 6.3 Outerloop 握手协议

```
Backtest Loop 检测到：
  - 某形态在某市场环境下持续亏损（样本外连续 3 个 window）
  → 建议禁用该形态该环境组合
  → 写入 docs/loop-state/STATE.md Watch List
  → GPT Agent 评估是否接受

Backtest Loop 检测到：
  - 新过滤规则使 Profit Factor 从 1.2 → 1.5（样本外）
  → 写入 tuning_snapshots/
  → 触发 TUNING promotion gate（必须 PR + 人工审查）
```

---

## 7. Freqtrade Integration（执行与优化引擎）

### 7.1 目录结构

```
freqtrade_compat/
├── __init__.py
├── strategy_generator.py       # HarmonicStrategy → Freqtrade IStrategy [NEW]
├── hyperopt_runner.py          # Hyperopt 参数优化 [NEW]
└── paper_trading.py            # Paper trading 引擎 [NEW]
```

### 7.2 Strategy Generator

```python
# 把 harmonic + confluence 策略自动生成 Freqtrade IStrategy 文件
def generate_freqtrade_strategy(
    harmonic_config: HarmonicStrategy,
    confluence_config: ConfluenceFilter,
    output_path: Path,
) -> None:
    """
    生成的 IStrategy 包含：
    - populate_indicators(): harmonic patterns + confluence filters
    - entry_signal(): 标准 entry rules
    - exit_signal(): SL/TP/TS rules
    - timeframe = '1h'（可配置）
    """
```

### 7.3 Hyperopt 集成

使用 Freqtrade Hyperopt 对以下参数做大规模优化：
- Confluence filter 阈值（RSI、ADX、volume 倍数）
- SL/TP 比例（0.382 / 0.5 / 0.618 / 1.272 / 1.618）
- 形态权重组合
- 时间框架组合

### 7.4 上线门槛

```
Dry-run / Paper Trading 至少 1-3 个月
↓
连续 30 天正期望值
↓
小资金实盘（≤ 10% 账户权益）
↓
监控 3 个月仍保持正向
↓
正式上线
```

---

## 8. 实施路线图

| 阶段 | 时间 | 重点任务 | 成功标准 |
|------|------|----------|----------|
| **Phase 1** | 2-3 周 | Confluence Filter + Confidence Score + 标准 SL/TP 规则 | 样本内 Profit Factor > 1.3 |
| **Phase 2** | 3-4 周 | Walk-forward 回测升级 + 多资产验证 | 样本外 Sharpe > 0.8，MaxDD < 15% |
| **Phase 3** | 2-3 周 | Freqtrade 兼容层 + Dry-run | 纸面交易连续 30 天正期望 |
| **Phase 4** | 持续 | Loop 反馈接入 + 前端监控 + Agent 自动优化 | 实盘 3 个月后仍保持正向 |

### Phase 1 详细任务（2-3 周）

| 任务 | 验收标准 | 优先级 |
|------|----------|--------|
| 实现 `ConfluenceFilter` 类（`app/domain/signals.py`） | HTF 趋势 + RSI + Volume + ADX 过滤通过 | P0 |
| 实现 `ConfidenceScorer` 类 | Score 计算正确，≥70 门槛生效 | P0 |
| 实现 `HarmonicStrategy`（标准交易规则） | Entry/SL/TP/TS 规则完整 | P0 |
| 实现 `PositionSizing`（仓位管理） | 0.5-1.5% 风险限制 + 相关性过滤 | P0 |
| 更新 `patterns/registry.yaml` | 形态权重 + 启用状态配置正确 | P0 |
| 修复 lookahead bias（确认蜡烛规则） | 只在收盘后确认，不使用未来数据 | P0 |
| 将 `.scratch/backtest/` 迁移到 `bench/` | 目录正式纳入项目，CI 覆盖 | P1 |

### Phase 2 详细任务（3-4 周）

| 任务 | 验收标准 | 优先级 |
|------|----------|--------|
| 实现 `CostModel`（手续费 + 滑点 + 资金费率） | 成本计算与 Binance 实际一致 | P0 |
| 实现 `walk_forward.py`（滚动窗口） | 样本外窗口 ≥ 3 个连续达标 | P0 |
| 实现 `multi_asset_runner.py` | BTC/ETH/SOL + 3 时间框架同时测试 | P1 |
| 实现 `metrics_collector.py` | 8 个核心指标全部计算正确 | P0 |
| 接入 `app/loop/` Pareto 前沿 | Backtest 结果写入 HISTORY.jsonl | P0 |
| Drawdown Guardrails | MaxDD 超过基线 2x 则拒绝 promotion | P1 |
| 实现 `report_generator.py`（HTML 报告） | Walk-forward 结果可视化 | P2 |

### Phase 3 详细任务（2-3 周）

| 任务 | 验收标准 | 优先级 |
|------|----------|--------|
| 实现 `strategy_generator.py` | 生成可运行的 Freqtrade IStrategy 文件 | P0 |
| 实现 `hyperopt_runner.py` | Hyperopt 优化完成，参数收敛 | P1 |
| 实现 `paper_trading.py` | Paper 交易引擎跟踪信号表现 | P0 |
| Dry-run 30 天验证 | 连续 30 天正期望 | P0 |
| TUNING Promotion Gate | 必须 PR + 人工审查，不自动覆盖运行中 worker | P0 |

### Phase 4 详细任务（持续）

| 任务 | 验收标准 | 优先级 |
|------|----------|--------|
| Loop 反馈接入（GPT Agent 建议 → CMA-ES） | 回测结果自动生成新候选 | P1 |
| 前端监控仪表盘 | 实时胜率、模拟 P&L、最大回撤预警 | P1 |
| TradingView Bridge 增强 | 自动画 PRZ 区域 + 警报 | P2 |
| 小资金实盘（≤ 10%） | 3 个月后仍保持正向 | P0 |
| Agent 自动优化（freqtrade_dev_mcp） | Agent 提出新假设 → 回测 → 接受/拒绝 | P2 |

---

## 9. 与现有 Loop Engineering Plan 的接口

本文档新增以下文件/目录（与 `docs/loop-engineering-plan.md` §3 对齐）：

```
app/
├── domain/
│   ├── signals.py                    # [MODIFY] 新增 ConfluenceFilter + ConfidenceScorer
│   └── strategy.py                   # [NEW] HarmonicStrategy + PositionSizing

bench/                                # [MOVE from .scratch/backtest]
├── run_backtest_v3.py                # [EXISTING, to be fixed]
├── walk_forward.py                   # [EXISTING in app/loop/, to be integrated]
├── multi_asset_runner.py             # [NEW]
├── cost_model.py                     # [NEW]
├── metrics_collector.py              # [NEW]
└── report_generator.py               # [NEW]

freqtrade_compat/                     # [NEW]
├── __init__.py
├── strategy_generator.py             # [NEW]
├── hyperopt_runner.py                # [NEW]
└── paper_trading.py                  # [NEW]

patterns/
└── registry.yaml                     # [MODIFY] 新增 default_weight + default_enabled

app/loop/
├── backtest_loop.py                  # [NEW] Backtest Loop 主驱动
└── backtest_agent.py                 # [NEW] GPT Agent 分析回测结果
```

**已有模块（保留，不改动）**：
- `app/loop/scheduler.py` — 调度器
- `app/loop/pareto.py` — Pareto 前沿
- `app/loop/oos_validator.py` — 样本外验证
- `app/loop/walk_forward.py` — Walk-forward 验证
- `app/loop/maker_checker/` — LLM Maker + Checker

---

## 10. 安全门与 Promotion 规则

### 10.1 TUNING Promotion Gate（关键安全门）

```
Backtest Loop 发现新最优参数
        │
        ▼
写入 tuning_snapshots/pareto-{sha}.yaml
        │
        ▼
人工审查 PR（修改 app/config/tuning.py）
        │
        ▼
Gunicorn 收到 SIGHUP 或重启
        │
        ▼
新 TUNING 值生效（所有 worker 同步）
```

**禁止**：`apply_tuning()` 直接修改运行中 gunicorn worker 的 `TUNING`。

### 10.2 Drawdown Guardrails

| 条件 | 动作 |
|------|------|
| MaxDD > 2× baseline | 拒绝 promotion，发出告警 |
| MaxDD > 20% absolute | 自动暂停信号输出 |
| Calmar Ratio < 0.5 | 拒绝 promotion |

### 10.3 样本外验证强制

任何新过滤规则或参数变更：
1. 必须在 walk-forward 样本外数据上证明有效
2. 至少连续 3 个滚动窗口达标
3. Profit Factor 样本外 > 1.1

---

## 11. 核心原则总结

> **和谐形态只是"候选结构"，真正赚钱的是**：
> 结构 + 趋势 + 动量 + 严格风控 + 持续样本外验证

| 层次 | 作用 | 当前状态 |
|------|------|----------|
| Confluence Filter | 过滤假信号 | 待实现 |
| Confidence Score | 量化信号质量 | 待实现 |
| 标准交易规则 | 统一入场/出场/风控 | 待实现 |
| Walk-forward 回测 | 防止过拟合 | 部分实现 |
| Loop 反馈 | 自动参数进化 | 已有框架，待接入 |
| Freqtrade 执行 | 真实交易闭环 | 待实现 |

**cryptoagg 的差异化优势**：GPT + loop 的反馈机制用在参数和过滤器进化上，形成自动优化的飞轮。

---

## 12. 未解决问题

| # | 问题 | 影响 | 建议处理方式 |
|---|------|------|------------|
| 1 | `.scratch/backtest/` 是否应移出并加入 git？ | CI 覆盖、可重现性 | Phase 1 必须迁移到 `bench/` |
| 2 | Freqtrade 兼容层的 IStrategy 生成模板 | 需维护与 Freqtrade 版本兼容性 | 使用 Freqtrade 模板版本锁定 |
| 3 | 多机并发回测（多台机器同时跑 walk-forward） | 数据一致性 | v1 声明单机，v2 考虑 PostgreSQL |
| 4 | 实盘资金管理（与 paper trading 的差异） | 滑点、手续费实际更高 | 实盘前增加 1.5x 滑点系数 |
| 5 | Market regime 切换（趋势↔震荡） | 同套参数无法适应所有市场 | Phase 4 加入 regime 检测 + 动态参数切换 |

---

_Last updated: 2026-08-10_
