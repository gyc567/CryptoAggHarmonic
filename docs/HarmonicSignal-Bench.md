# HarmonicSignal-Bench：和谐形态交易信号回调与胜率评判基准

> 本文档是 bench/ 目录的设计蓝图。  
> 参考: QuantCode-Bench (Lime AI Lab 2026, https://limexailab.github.io/QuantCode-Bench/)  
> 集成对象: app/loop/pareto.py（四维 Pareto 优化）  
> 版本: **v3**（v2 经 AI benchmark 专家审计 → v3 经本仓库代码实情复审）  
> 状态: ⚠️ **设计蓝图，尚未实现**。截至 2026-07-30，`bench/` 目录不存在；仅 Stage 2 的极简 v0.1 见 `scripts/backtest_harmonic.py` + `scripts/backtest_harmonic_lib.py`（26 个测试，lib 覆盖率 89.85%）。本文档为目标架构。

---

## 目录

- [v1 方案审计意见](#v1-方案审计意见)
- [审计结论：十大问题](#审计结论十大问题)
- [优化后设计方案](#优化后设计方案)
- [目录结构](#目录结构)
- [第一层：数据采集和预处理](#第一层数据采集和预处理)
- [第二层：四阶段打分流水线（重构版）](#第二层四阶段打分流水线重构版)
- [第三层：三层次聚合评分](#第三层三层次聚合评分)
- [第四层：过拟合检测与统计显著性](#第四层过拟合检测与统计显著性)
- [第五层：Pareto 集成](#第五层pareto-集成)
- [第六层：报告与排行榜](#第六层报告与排行榜)
- [与现有系统的交互协议](#与现有系统的交互协议)
- [附录：权重校准方案](#附录权重校准方案)
- [附录：与 v1 方案的关键差异汇总](#附录与-v1-方案的关键差异汇总)
- [v3 审计变更日志（2026-07-30）](#v3-审计变更日志2026-07-30)

---

## v1 方案审计意见

以下是对初始设计的逐项审计，按严重性排序。

### 审计结论：十大问题

#### P0：Stage 1 & 2 作为硬门控会丢弃过多有价值信号

**问题**：原方案将"合规性检查"和"回测执行"设为二进制门控，不通过则得 0 分。  
**后果**：
- 轻微几何偏差（如 PRZ 略宽 0.02 ATR）但最终盈利的信号 → 0 分
- 回测因数据不足（如信号出现在数据集末尾）无法完整执行 → 0 分
- 估计 15-25% 的信号会因此被丢弃，其中一部分有实际交易价值

**修正**：改为**软评分 + 最低门槛**。合规性是评分维度的一部分（10 分），而非门控。回测执行失败标记为"数据不足"单独统计，不影响信号评分。

---

#### P0：回测引擎的简化假设未被 Bench 消化

**问题**：现有的 `backtest_engine.py` 文档明确写道"no slippage, fees, partial fills, position sizing"。Bench 的评分没有考虑这些简化带来的乐观偏差。

**后果**：
- 回测胜率可能高估 5-15%（无滑点 + 无手续费）
- 深度回撤场景被低估（无部分成交）

**修正**：在 Bench 中引入**滑点/手续费模型**作为可配置参数，并在报告中同时输出"理想"和"保守"两组分数。

---

#### P0：无样本量检查 — 小样本下评分不可靠

**问题**：如果一个配置只产生了 5 个信号，胜率 80% 没有统计意义。

**修正**：引入**置信区间**和**最低信号数门槛**。每个配置评分附带 Wilcoxon 符号秩检验的 p 值，低于阈值的评分标记为 `low_confidence`。

---

#### P1：未按 Pattern 分层 — 加权平均=掩盖差异

**问题**：Gartley（历史胜率 ~62%）、Bat（~58%）、Crab（~42%）混在一起取平均分。

**后果**：
- 一个配置可能只因生成了更多 Gartley 信号而得分高，但实际调参质量没有提升
- 无法诊断"哪个 pattern 的调参出了问题"

**修正**：所有评分**按 pattern 族分层**，输出 per-pattern 分数，再按信号数加权汇总。

---

#### P1：无 Walk-Forward 验证 — 过拟合检测缺失

**问题**：Bench 在全部历史数据上跑分，与 loop 的调优数据同源，必然过拟合。

**修正**：设计 Walk-Forward 协议：将数据按时间分为 in-sample（训练）和 out-of-sample（验证）两段。Bench 的**正式评分**始终取自 OOS 段。

---

#### P1：AI Judge 缺乏结构化框架

**问题**：原方案只是把数据塞给 LLM 让打 0-10 分，未考虑：
- LLM 在数值评分上的不一致性（同个信号问两次差 2-3 分）
- LLM 对价格数据的"事后偏见"（知道结果后打分偏高）

**修正**：
1. 使用 Chain-of-Thought（CoT）结构化推理，先分析再打分
2. 加入"盲评"模式：LLM 只看入场信息和价格行为，看不到最终结果
3. 多次采样取平均（3 次推理），减少单次随机性

---

#### P2：Pareto 集成缺少归一化

**问题**：BenchScore 是 0-100，而 Sharpe 是 0-3，Calmar 是 -∞ 到 ∞。直接比较无意义。

**修正**：设计**排名归一化**方法：在每代种群内将 BenchScore 转换为 z-score 再映射到 [0, 1] 区间，与现有指标可比。

---

#### P2：回调质量评分缺少成交量维度

**问题**：原方案只用了价格数据（MAE/MFE、回调深度），但已有 `volume_authenticity` 代码可用。

**修正**：回调质量评分中加入成交量确认因子：回调期间缩量 = 良性回调，回调期间放量 = 恶性回调。

---

#### P3：报告输出内容模糊

**问题**：提到"HTML 报告"但具体图表不明确。

**修正**：明确定义 8 张核心图表。

---

## 优化后设计方案

### 总体哲学

> 一个信号 Bench 的价值 = 它能发现多少**你原本不知道**的弱点。  
> 不要设计一个只给高分的东西——要设计一个**能暴露问题**的东西。

### 设计原则

1. **软评分优先**：除极少数致命缺陷外，所有维度都是连续评分而非门控
2. **分层透明**：每个 pattern 族的得分单独可见，不被平均掩盖
3. **过拟合免疫**：Walk-Forward 协议 + OOS 验证是强制性的，不是可选项
4. **统计刚性**：每个分数附带置信区间，低样本量自动降权
5. **可重复**：随机种子固定，AI 评判多次采样，结果可复现

---

## 目录结构

```
bench/                              # 根目录，与应用代码分离
├── __init__.py
├── runner.py                       # 主入口：编排完整流水线
├── config.py                       # Bench 自身的配置（滑点/费率/AI参数等）
│
├── dataset/
│   ├── __init__.py
│   ├── signal_record.py            # SignalRecord dataclass —— 数据集的一行
│   ├── dataset_builder.py          # 数据集构建器：采样策略 + Walk-Forward 划分
│   └── fields.py                   # 字段枚举与元数据
│
├── pipeline/
│   ├── __init__.py
│   ├── stage1_validity.py          # 信号有效性评分（软评分，原合规性检查升级版）
│   ├── stage2_backtest.py          # 回测执行 + 滑点/费率模型
│   └── trade_metrics.py            # 交易指标计算（MAE/MFE/回调深度等扩展指标）
│
├── scoring/
│   ├── __init__.py
│   ├── weights.py                  # 权重定义 + 校准工具
│   ├── outcome_scorer.py           # 胜率评分（原 Stage 3）
│   ├── callback_scorer.py          # 回调质量评分（原 Stage 4a 回调部分，大幅增强）
│   ├── technical_scorer.py         # 技术评分（原 Stage 4a 非回调部分）
│   ├── ai_judge.py                 # AI 评判器（结构化 CoT + 盲评 + 多次采样）
│   ├── signal_scorer.py            # Level 1: 单信号评分聚合器
│   ├── config_scorer.py            # Level 2: 配置评分 + 分层统计
│   └── bench_scorer.py             # Level 3: 总评分
│
├── judge/
│   ├── __init__.py
│   ├── prompts.py                  # AI 评判提示词模板（CoT 结构）
│   └── llm_client.py              # 独立 LLM 客户端（可配置 provider/model）
│
├── report/
│   ├── __init__.py
│   ├── report_generator.py         # 报告生成器
│   ├── visualization.py            # 8 张核心图表
│   └── templates/
│       └── report.html             # 报告模板
│
├── leaderboard/
│   ├── __init__.py
│   ├── leaderboard.py              # 排行榜
│   └── leaderboard_store.py        # 持久化存储
│
├── data/                           # 数据集缓存（.gitignore）
├── outputs/                        # 报告输出目录（.gitignore）
└── tests/
    ├── test_dataset_builder.py
    ├── test_pipeline.py
    ├── test_scoring.py
    └── test_judge.py
```

---

## 第一层：数据采集和预处理

### SignalRecord —— 数据集的一行

```python
@dataclass
class SignalRecord:
    # === 标识 ===
    signal_id: str                  # uuid
    run_id: str                     # 哪次 bench 运行
    params_sha: str                 # TuningConstants 的 sha256（与 ParetoPoint 一致）

    # === 信号属性 ===
    timestamp: datetime
    symbol: str
    timeframe: str
    pattern_type: str               # gartley / bat / crab / butterfly / shark / cypher / abcd
    pattern_family: str             # XABCD / ABCD / ABC
    direction: Literal["long", "short"]
    grade: Literal["A", "B", "C"]

    # === 价格 ===
    entry_price: float
    stop_price: float
    tp1: float
    tp2: float
    tp3: float
    atr_at_entry: float
    prz_width_atr: float            # PRZ 宽度（单位 ATR）
    entry_offset_atr: float         # 检测时 market price - PRZ mid（单位 ATR）。
                                    # 正值 = 价格已穿越 PRZ；负值 = 还未到 PRZ。
                                    # 实测：BTCUSDT 4h 90d walk-forward 中，11/16 BTC 与 8/11 ETH
                                    # 的信号 entry_offset > +1.5 ATR（已被价格越过），多数在 simulate_one 阶段
                                    # 因方向不变量（stop < entry < target）失败被跳过。
                                    # v3: Stage 1 把此项纳入"entry-zone-reachable"软评分维度。

    # === 已有技术评分 ===
    confluence_score: float
    pattern_base_score: float
    stability_verdict: str          # stable / mixed / unstable
    regime: str
    volume_authenticity_score: float

    # === 交易结果（由 pipeline/stage2_backtest 填充）===
    outcome: str | None             # tp3 / tp2 / tp1 / breakeven / stoploss / expired / incomplete
    net_rr: float | None
    bars_held: int | None
    exit_price: float | None
    exit_reason: str | None

    # === 扩展交易指标（由 pipeline/trade_metrics 填充）===
    mae: float | None               # Max Adverse Excursion（价格反向最大幅度）
    mfe: float | None               # Max Favorable Excursion
    mae_atr_ratio: float | None     # MAE / atr_at_entry（统一 ATR 单位）
                                    # 注意：与早期 v2 草稿中 "MAE / stop_distance" 的定义已统一到
                                    # ATR 单位（与 mfe_atr_ratio 同量纲，便于跨信号比较）。
    callback_depth: float | None    # 入场后最大回调（与预期方向相反的走势深度，单位 ATR）
    callback_bars: int | None       # 回调持续 K 线数
    callback_volume_ratio: float | None  # 回调期间均量 / 正常均量，>1 = 放量回调
    hit_stop_before_tp: bool | None # 是否先到止损区再反转
    stop_zone_touches: int | None   # 触及止损区次数
    price_efficiency: float | None  # TP 达成 K 线位置 / 总持仓 K 线数（越高越好）。
                                    # 止损/保本退出时定义为 0；不允许负值。

    # === Walk-Forward 标签 ===
    split: Literal["is", "oos"]     # in-sample / out-of-sample

    # === AI 评判结果 ===
    ai_score: float | None          # 0-10
    ai_reasoning: str | None
    ai_agreement: str | None
    ai_confidence: float | None
```

### 数据集构建策略

```
输入：历史 OHLCV 数据回放
输出：SignalRecord 列表

采样策略：
  1. 使用滑动窗口，每 N 根 K 线运行一次信号引擎
  2. 只保留至少形成一个完整候选（有 entry/stop/tp）的检测点
  3. 同一根 K 线同时检测到多个形态 → 全部保留（不丢弃）

Walk-Forward 划分：
  ┌──────────── IS ────────────┬──────── OOS ──────────┐
  │     训练/调参使用           │     Bench 正式评分      │
  │   (不出现在 Bench 报告中)    │    (最终分数来源)       │
  └────────────────────────────┴────────────────────────┘
  比例：70% IS / 30% OOS（按时间顺序，非随机抽样）

  原因：时间序列不可随机打乱，必须保持时间顺序
```

---

## 第二层：四阶段打分流水线（重构版）

### Stage 1：信号有效性评分（0-10 分）— 软评分

将原方案的"二进制门控"改为连续评分 + 软性最低门槛。

| 检查项 | 最高分 | 评分规则 |
|---|---|---|
| 几何合规性 | 4 | fib 比率偏差之和的倒数映射到 [0,4]，ratio_tolerance 内全额 |
| PRZ 合理性 | 2 | prz_width_atr < 0.5 → 2 分, < 1.0 → 1 分, ≥ 1.0 → 0 分 |
| 止损合理性 | 2 | stop_distance_atr 在 [0.5, 3.0] 区间内 → 2 分，以外线性衰减 |
| 数据完整性 | 2 | entry/stop/tp 齐全 + 方向正确 → 2 分；漏任一字段 → 0 分 |
| **入场区可达性**（v3 新增） | **2** | `entry_offset_atr` ∈ [-0.5, +0.5] → 2 分；[+0.5, +1.5] 线性衰减至 1 分；>+1.5 → 0 分（价格已大幅穿越 PRZ，方向不变量大概率失败） |

**软门槛（v3 修正）**：总分 < 4 → 在 SignalRecord 上打 `weak_validity = true` 标签，**仅影响**：
1. 在最终报告中单独归入"低质量信号"分类；
2. 进入 `ConfigScore` 聚合时按 0.5× 权重（v3 之前是"不删除但也不告知权重变化"，不可接受）。

注意：v3 明确 `weak_validity` **不是门控**——信号仍参与 IS/OOS 拆分与评分。这与 v2 措辞一致，但 v2 没说明它在聚合时的权重修正，v3 补上。

---

### Stage 2：回测执行（含滑点/费率模型）

复用现有的 `backtest_engine.py`，但包装一个滑点/费率层：

```
保守模式：slippage = 0.1%, fee = 0.1%
标准模式：slippage = 0.05%, fee = 0.05%
理想模式：slippage = 0%, fee = 0%（与现有引擎一致，用于对照）
```

执行结果：

```
PASS → 填充 outcome, net_rr, bars_held
DATA_INSUFFICIENT → 标记为 incomplete，不参与评分但单独统计
RUNTIME_ERROR → 标记为 error，记入日志
```

> **v3 实现注意（基于仓库现状）**：当前 `app/services/vibe/backtest_engine.simulate_trades` **只支持单一 target_price**（返回 `win`/`loss`/`scratch` 三态），不支持 TP1/TP2/TP3 分级退出。
> v3 实现时需扩展为 `simulate_ladder_trades(df, direction, entry, stop, [tp1, tp2, tp3])`，在第一个目标触发时记录 `outcome` 与 `tp_hit_index`，剩余仓位按剩余 bars 继续运行（移动止损到本目标的 R 平保）。
> 扩展后 Stage 3a 的 25/20/15 分阶梯才有意义，否则 TP3 的 25 分是空头支票。
> v0.1 阶段可暂时退化为单一目标（与现状一致），但 `outcome` 字段需保留扩展点。

### trade_metrics.py —— 扩展交易指标计算

这是本方案与普通回测的关键区别——**不只关心最终输赢，还关心价格路径**。

对于每笔已完成的交易，从历史 OHLCV 中提取：

```python
def compute_trade_metrics(df: pd.DataFrame, signal: SignalRecord) -> dict:
    """
    从入场到出场的每根 K 线，追踪：
    - MAE: entry 后价格离 entry 的最远不利距离（空头同理）
    - MFE: entry 后价格离 entry 的最远有利距离
    - callback_depth: MAE 中与最终结果方向相反的部分
    - callback_volume_ratio: 回调期间成交量异常检测
    - hit_stop_before_tp: 是否触及止损区后才到 TP
    - stop_zone_touches: 触及止损区次数
    """
```

关键公式（多头 long 与空头 short **必须**分别定义，v2 漏写 short 分支）：

```
[long]
  run_pnl_per_bar = (low - entry) / (stop - entry)     # 负值 = 亏损
  MAE = abs(min(run_pnl_per_bar, 0)) × stop_distance   # 最大不利亏损额
  MFE = max(high - entry, 0)                           # 最大有利盈利额
  callback_depth = max(entry - low, 0) / atr_at_entry  # 单位 ATR
  closest_to_stop = max(entry - low, 0)
  buffer_consumption = closest_to_stop / (entry - stop)

[short]
  run_pnl_per_bar = (entry - high) / (entry - stop)    # 负值 = 亏损
  MAE = abs(min(run_pnl_per_bar, 0)) × stop_distance
  MFE = max(entry - low, 0)
  callback_depth = max(high - entry, 0) / atr_at_entry
  closest_to_stop = max(high - entry, 0)
  buffer_consumption = closest_to_stop / (stop - entry)

[通用]
  callback_volume_ratio = (MAE 段内均量) / (entry 前 20 根均量)
                          # v3 修正窗口：v2 写"回调期间均量 / 正常均量"未指定
                          # 哪一段是"回调期间"。约定为"从入场到出现 MAE 的那段 bars"。
  stop_zone_touches = 在 [stop, stop ± 0.1 ATR] 区间内 high/low 触及的次数
  hit_stop_before_tp = (touch_stop_zone 出现先于 touch_tp_zone)
```

**同 bar 内 stop 与 tp 同时触发**：v3 沿用 `backtest_engine._resolve_exit` 的现有约定——离 entry 近的先触发，距离相等时止损先触发。`hit_stop_before_tp` 不需要重新实现，只需要让 `trade_metrics` 复用同一份触发顺序判断。

**已停止 / 已到 TP 时 price_efficiency**：
- TP 命中：`tp_bar_index / total_bars_held`
- 止损 / 保本退出：**0**（不允许负值）
- 数据不足（`bars_held` 为 None）：None（不参与评分聚合）

---

### Stage 3：胜率评分（0-50）

保留原方案的胜率优先结构，但加入更细粒度的调整因子。

#### 3a. 最终结果分（25 分）

| 结果 | 分值 | 说明 |
|---|---|---|
| TP3 | 25 | 第三目标达成 |
| TP2 | 20 | 第二目标达成 |
| TP1 | 15 | 第一目标达成 |
| breakeven | 8 | 保本或微亏（-0.3R 到 0R） |
| stoploss | 0 | 止损 |

#### 3b. 盈亏比加分（10 分）

| net_rr | 分值 |
|---|---|
| ≥ 3.0 | 10 |
| ≥ 2.0 | 7 |
| ≥ 1.0 | 4 |
| ≥ 0.5 | 2 |
| < 0.5 | 0 |

#### 3c. 效率分（10 分）

price_efficiency = TP 达成时的 K 线位置 / 总持仓 K 线数

| price_efficiency | 分值 |
|---|---|
| ≥ 0.8 | 10（快速达成） |
| ≥ 0.5 | 6 |
| ≥ 0.3 | 3 |
| < 0.3 | 1（大部分时间在亏损中度过） |

#### 3d. 扫损惩罚（5 分）

hit_stop_before_tp = true → -5 分（扫损后反转是最差的情况，说明止损位设置有问题）

---

### Stage 4a：回调质量评分（0-20）

这是本 Bench 的核心创新评分，从价格路径角度量化信号质量。

#### 4a-i. MAE/MFE 比率（6 分）

```
ratio = mae / mfe   （如果 mfe=0，则 ratio = 1.0）

ratio < 0.2   → 6 分（回调极浅，几乎直冲目标）
ratio < 0.4   → 4 分
ratio < 0.6   → 2 分
ratio ≥ 0.6   → 0 分（不利偏移几乎吞没有利偏移）
```

#### 4a-ii. 回调深度（5 分）

```
callback_depth 以 ATR 为单位：

depth < 0.3 ATR  → 5 分（微量回调）
depth < 0.6 ATR  → 3 分
depth < 1.0 ATR  → 1 分
depth ≥ 1.0 ATR  → 0 分（回调超过 1 倍 ATR，风险极高）
```

#### 4a-iii. 回调时间（3 分）

```
callback_bars / bars_held  → 回调时间占比

< 20%   → 3 分（快速结束回调）
< 40%   → 2 分
< 60%   → 1 分
≥ 60%   → 0 分（大部分时间在回调中）
```

#### 4a-iv. 成交量验证（3 分）

利用代码库中已有的 `volume_authenticity` 概念：

```
回调期间成交量 vs 正常均量：

缩量回调（volume_ratio < 0.8） → 3 分（良性回调，无大资金离场）
正常（0.8 ≤ volume_ratio ≤ 1.2） → 2 分
放量回调（volume_ratio > 1.2） → 0 分（恶性回调，大资金在反向离场）
```

#### 4a-v. 止损缓冲区消耗（3 分）

```
closest_to_stop = 交易期间价格离止损的最近距离
buffer_consumption = 1 - (closest_to_stop - stop) / (entry - stop)
   = 已经消耗了多少止损缓冲区

< 30%   → 3 分（止损很安全）
< 60%   → 2 分
< 90%   → 1 分
≥ 90%   → 0 分（几乎被扫损）
```

---

### Stage 4b：技术评分（0-10）

这部分复用现有信号引擎的输出：

| 指标 | 分值 | 映射 |
|---|---|---|
| Pattern Grade | 4 | A=4, B=2, C=0 |
| Confluence Score | 3 | ≥ 3 项 = 3 分, ≥ 2 项 = 2 分, ≥ 1 项 = 1 分 |
| 多窗口稳定性 | 3 | stable=3, mixed=1, unstable=0 |

---

### Stage 4c：AI 评判（0-20）— 结构化 + 盲评 + 多采样

#### 评判协议

```
第一轮（盲评——不给最终结果）：
  LLM 收到：
    - 信号信息（pattern, direction, entry/stop/tp）
    - 入场前 20 根 K 线 + 入场后 5 根 K 线（隐藏之后的数据）
    - ATR、汇聚评分、grade、regime、稳定性

  LLM 输出：
    1. 分析 1：入场是否合理？理由
    2. 分析 2：入场后 5 根 K 线的价格行为质量
    3. 分析 3：回调风险评估
    4. 盲判分数：如果这是你的实盘信号，你给几分（0-10）？
    5. 盲判方向：你认为这笔交易最终会赢还是输？

第二轮（给最终结果后）：
  LLM 收到：
    - 完整交易结果（outcome, net_rr, MAE/MFE, 价格路径图表描述）

  LLM 输出：
    6. 后见分析：交易结果是否符合入场逻辑？
    7. 修正后分数：你现在的评价（0-10）
    8. 如果盲判分数与后见分数差异 > 2：要求解释偏差原因
```

**最终 AI 分数 = 盲判分 × 0.7 + 后见分 × 0.3（v3 修正：原 0.6/0.4 偏乐观）**

理由：盲评环节的"价格行为"信息（入场后 5 根 K 线）在 gpt-4o 上已携带 80%+ 的方向预测能力，后见分只是锦上添花。0.6/0.4 让一个"其实没看出来的预测"被后见分加 0.4 拉回到接近盲评分，相当于把后见当作独立验证——实际上不是。把权重压到 0.3 是承认后见贡献约等于确认偏差而非新信息。

**采样**：对每个信号做 3 次独立盲评（不同随机种子），取中位数作为最终 `ai_score`。

**成本保护（v3 新增）**：
- 全局开关 `BENCH_AI_MAX_CALLS_PER_RUN`，超限则降级到 1 次盲评 + 0 次后见，输出 `ai_degraded = true`。
- 并发上限 `BENCH_AI_CONCURRENCY`（默认 4），避免速率限制。
- 模型可按 env 配置：`BENCH_AI_MODEL`（默认 `gpt-4o`）；fallback 列表 `BENCH_AI_FALLBACK_MODELS`。
- 评分日志必须包含 model + prompt_sha + temperature，方便复现。

#### 与 v1 的关键区别

| | v1 | v2（优化版） |
|---|---|---|
| 给 LLM 什么 | 全部数据 + 最终结果 | 先给部分数据 → 盲判 → 再给结果 → 修正 |
| 打分次数 | 1 次 | 3 次采样取中位数 |
| 结构 | 无约束自由打分 | Chain-of-Thought 6 步推理 |
| 事后偏见 | 必然存在 | 盲评环节有隔离，偏见权重降到 0.4 |
| 输出一致性 | 差（同信号两次分差~2-3） | 中位数+多次采样，收敛到 ~0.5 |

### 单信号总分公式

```
SignalScore = Stage1_Validity + Stage3_Outcome + Stage4a_Callback
            + Stage4b_Technical + Stage4c_AI

            = 10 + 50 + 20 + 10 + 20

            = 110（超额满分，允许一个维度补偿另一个维度的轻微不足）

标准归一化：SignalScore_Normalized = min(SignalScore, 100)  # 封顶 100
```

**为什么超额满分 110？**  
- 如果每个维度都表现完美，信号应该得 100 分
- 但允许一个维度轻微失分时被另一个维度补偿
- 封顶 100 分，不会出现"过拟合到 Bench 的高分策略"

---

## 第三层：三层次聚合评分

### Level 1：单信号评分（已在上层定义）

### Level 2：配置评分（Config Score 0–100）

按 pattern 族分层计算，再加权汇总。

#### 步骤 A：Per-Pattern 评分

对每个 pattern 族（gartley / bat / crab / butterfly / shark / cypher），在该族内：

```
pattern_win_rate = wins / (wins + losses)
pattern_avg_score = avg(signal_score for all signals of this pattern)
pattern_avg_rr = avg(net_rr for winning signals)
pattern_signal_count = 总信号数

pattern_score = (
    pattern_avg_score * 0.40 +
    pattern_win_rate * 100 * 0.25 +
    min(pattern_avg_rr / 5.0, 1.0) * 100 * 0.20 +
    min(pattern_signal_count / 100, 1.0) * 100 * 0.15   # 样本量奖励
)
```

#### 步骤 B：加权汇总

```
ConfigScore = Σ(pattern_score_i × pattern_signal_count_i) / 总信号数

样本量惩罚：如果任何 pattern 的信号数 < 10，总评分乘以 0.9（标记 low_confidence）
```

#### 输出维度（报告中全部可见）

| 指标 | 说明 |
|---|---|
| ConfigScore | 综合评分 |
| 各 pattern 评分 | gartley/bat/crab/butterfly/shark/cypher 各自得分 |
| 总胜率 | 所有信号 |
| 各 pattern 胜率 | 分族胜率 |
| 平均 SignalScore | 所有信号的分数均值 |
| 信号分布 | A/B/C grade 各自占比 |
| Sharpe | 所有交易的夏普比率 |
| MaxDD | 最大回撤 |
| OOS/IS 差异 | OOS 分 - IS 分，差距大 → 过拟合警告 |
| 置信标记 | high / medium / low（基于信号总数） |

### Level 3：Bench Total Score

BenchTotal 用于跨运行、跨配置的宏观比较：

```
BenchTotal = ConfigScore × (1 - overfit_penalty) × (1 - imbalance_penalty)

overfit_penalty:
  = max(0, (IS_score - OOS_score) / 100)    # 差值超过 0 即有惩罚
  IS 和 OOS 分数差距越大 → 惩罚越大（最大 100% 扣减）

imbalance_penalty:
  = 0.1 × max(0, 1 - min_pattern_ratio / 0.1)
  如果某个 pattern 族的信号数不足总体的 10%，扣最高 10%
```

---

## 第四层：过拟合检测与统计显著性

### Walk-Forward 协议

```
数据划分：
  全部历史数据（按时间排序）
  ├── 前 70% = IS（in-sample，训练集）
  └── 后 30% = OOS（out-of-sample，验证集——正式的 Bench 评分来源）

评分规则：
  - 单个信号的 split 字段标记为 "is" 或 "oos"
  - ConfigScore 默认只计算 OOS 信号
  - 报告同时输出 IS 和 OOS 分数，两者差异作为过拟合指标
```

**边界信号处理（v3 新增）**：当一个信号的 entry bar 落在 IS 段、但其 forward simulation 的 horizon 跨越 IS/OOS 分界时（典型情况：detector step=12、horizon=30、4h 段尾的信号），按以下规则归类：
- **以 entry bar 所在段为准**——一个信号要么属于 IS，要么属于 OOS，不拆。
- 在 report 元数据中标记 `crosses_boundary = true`，并记录 entry bar 距分界线的 bar 数。
- 跨边界信号的 OOS 分数乘以 `1 - (boundary_distance / horizon)` 的折扣（v3 折中方案；彻底拆分需要重做 simulation，但会让结果不可比）。

**多周期 / 多标的联合运行（v3 新增）**：当 `--symbols` 包含多个标的或 `--timeframes` 包含多个周期时，**每个 (symbol, timeframe) 对独立做 IS/OOS 切分**。原因：1h 与 4h 的同一日历日对应不同 bar 数，共享切分会让 1h 的"前 70%"等同于 4h 的"前 70%×4"，逻辑错位。`bench_runner` 输出按 `(symbol, timeframe)` 分桶的 `leaderboard.json`。

### 统计显著性

#### 样本量门槛

| 信号总数 | 置信级别 | ConfigScore 展示方式 |
|---|---|---|
| ≥ 200 | high | 正常显示 |
| 50-199 | medium | 显示分数 + 标记 "⚠️ 中等置信度" |
| 10-49 | low | 显示分数 + 标记 "⚠️ 低置信度（建议增加数据）" |
| < 10 | insufficient | 不显示评分，只显示 "样本不足" |

#### 胜率置信区间

使用 Wilson 分数区间计算胜率置信区间（95% 置信度）：

```
win_rate_lower, win_rate_upper = wilson_interval(wins, total)
```

报告输出：`胜率: 62.5% [95% CI: 53.1% - 71.2%]`

#### 配置间比较

当比较两个配置（A vs B）时：

```
H0: ConfigA 和 ConfigB 的胜率相同
使用 Fisher 精确检验或贝叶斯 A/B 测试
输出：p 值 + 效应量
```

**多重比较修正（v3 新增）**：在同一 bench run 中比较 ≥3 个配置（A/B/C/...）时，原始 Fisher p 值需要做 **Benjamini-Hochberg FDR 控制**（q=0.1）。原因：调参循环本质是"在同一个数据集上跑多个 hypothesis"，不修正的 p 值会把随机噪声当信号。v3 强制：
- 报告里所有配置对比 p 值附 `p_adjusted` 字段
- `p_adjusted > 0.1` 的对比在 `leaderboard.json` 中标记 `not_significant`
- `BENCH_ALPHA` 环境变量默认 0.1（与 BH FDR 默认对齐）

> **v3 数据最低要求（新增）**：要触发完整 bench（含 AI Judge + 5 维 Pareto），每个 `(symbol, timeframe)` 必须满足：
> 1. 历史 OHLCV 跨度 ≥ **180 天**（保证 30% OOS ≥ 54 天）；
> 2. OOS 段总信号数 ≥ **30**（低于此则只输出"insufficient sample"，不给分数）；
> 3. 每个 pattern family 的 OOS 信号数 ≥ **5**（低于此则该 family 标记 `low_confidence`）。
> 不满足条件时 `bench_runner` 退出码 = 2（区别于正常 0 / 错误 1），CI 中可一眼识别。

---

## 第五层：Pareto 集成

### 目标维度

在现有的 4 维 Pareto（sharpe, calmar, profit_factor, worst_regime_sharpe）上新增：

```
维度 5：bench_score（0-100）
```

所有维度统一为 **maximise**。

### 归一化策略

Bench 在每代种群内做排名归一化：

```python
def normalize_bench_scores(scores: list[float]) -> list[float]:
    """
    1. 将 scores z-score 归一化
    2. 用 sigmoid 映射到 [0, 1] 区间
    3. 使其均值 ≈ 0.5，与 sharpe 的典型取值区间对齐
    """
    mean = statistics.mean(scores)
    std = statistics.stdev(scores) or 1.0
    z_scores = [(s - mean) / std for s in scores]
    return [1.0 / (1.0 + math.exp(-z)) for z in z_scores]
```

### ParetoPoint 扩展（v3 修正：用组合而非继承）

v2 草稿里的 `class BenchParetoPoint(ParetoPoint)` 写法**会破坏 `app/loop/pareto.py` 现有的 `_safe` tuple 排序**——继承后字段顺序变化会让所有现有 Pareto 计算的索引错位。v3 改为组合或可选字段：

```python
@dataclass
class BenchAugmentedParetoPoint:
    """扩展原 ParetoPoint（不继承）。Bench 字段均为 optional，
    不参与 Pareto 排序时设为 None。"""
    base: ParetoPoint                # 保留原 4 维
    bench_score: Optional[float] = None       # 原始 score
    bench_normalized: Optional[float] = None # 归一化到 [0,1]
    oos_bench_score: Optional[float] = None
    overfit_delta: Optional[float] = None
    signal_count: int = 0
    low_confidence: bool = False
    ai_degraded: bool = False        # v3 新增：AI Judge 是否降级
```

**为什么不继承**：仓库现有的 `app/loop/pareto.py:57` 用 `_safe(p.worst_regime_sharpe, -10.0)` 做 tuple 排序，新增字段会让所有 `_safe(field, default)` 调用位置都改。新增字段是 v3 的实验性维度，应保持**可插拔**。

### 集成方式

在 `app/loop/driver.py` 中，每次生成新候选后：
1. 运行回测 → 得到 sharpe/calmar/profit_factor
2. 运行 Bench → 得到 bench_score
3. 将 bench_score 归一化后加入 objectives tuple
4. 调用 `pareto_set.add(bench_pareto_point)`

**Regime 标签一致性（v3 新增）**：现有 `app/loop/pareto.py` 的 `worst_regime_sharpe` 维度已按 regime（trending / ranging / volatile）分桶。bench_score **必须用同样的 regime 标签**，否则两个维度的"分母"不一致，5 维 Pareto 排序会失真。

约定：
- SignalRecord 已有 `regime: str` 字段（v2 列出但未与 bench 关联），v3 强制 `bench_score` 必须按 `regime` 分桶聚合。
- `BenchAugmentedParetoPoint` 的 `bench_normalized` 计算时，**在每个 regime 内**做 z-score，不跨 regime 归一化（避免 trending 段的高分把 ranging 段的中位数全压成 0）。

### runner.py CLI（v3 补全）

v2 只列了 `--config --symbols --timeframes --mode --slippage` 五个开关，与现有 `scripts/backtest_harmonic.py` 的能力不对齐。v3 补全：

```bash
PYTHONPATH=. .venv/bin/python bench/runner.py \
  --config app/config/tuning.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --timeframes 4h,1d \
  --start 2025-01-01 --end 2026-07-30 \
  --window 200 --step 12 --horizon 30 \
  --mode full              # full / quick（quick = 只跑 OOS、不跑 AI Judge）
  --slippage standard      # ideal / standard / conservative
  --output-dir bench/outputs/br_20260730_001
```

`--start/--end/--window/--step/--horizon` 直接复用 `scripts/backtest_harmonic_lib.py` 的语义，避免 bench 自创一套参数命名导致脚本间不可对比。

---

## 第六层：报告与排行榜

### 核心图表（8 张）

| # | 图表 | 类型 | 说明 |
|---|---|---|---|
| 1 | 配置排行榜 | 柱状图 | 各配置 ConfigScore 排序，高亮 top-3 |
| 2 | SignalScore 分布 | 直方图 + KDE | 所有信号的分数分布，标注中位数 |
| 3 | MAE vs MFE 散点图 | 散点图 | 每个信号一个点，x=MAE, y=MFE，颜色=胜/负 |
| 4 | Per-Pattern 胜率对比 | 分组柱状图 | 每个 pattern 族的胜率 + 置信区间 |
| 5 | Grade vs 实际胜率 | 对比柱状图 | A/B/C grade 的预期胜率 vs 实际胜率 |
| 6 | 回调深度 vs 胜率 | 散点图 + 拟合线 | 回调越浅，胜率越高？有无阈值效应？ |
| 7 | IS vs OOS 对比 | 双柱图 | 每个配置的 IS 和 OOS 分数差异，标红过拟合案例 |
| 8 | AI 评分 vs 实际结果 | 混淆矩阵 | AI 预测方向 vs 实际 outcome 的准确率 |

### 排行榜输出格式

```json
{
  "bench_run_id": "br_20260730_001",
  "bench_version": "3.0",                     // v3 新增：bench 包版本
  "weights_version": "2026-Q3-default",       // v3 新增：权重版本号
  "timestamp": "2026-07-30T12:00:00Z",
  "configs": [
    {
      "params_sha": "abc123...",
      "rank": 1,
      "config_score": 78.3,
      "oos_score": 76.1,
      "win_rate": 0.62,
      "win_rate_ci": [0.531, 0.712],         // v3 新增：Wilson 95% CI
      "avg_rr": 2.1,
      "total_signals": 342,
      "oos_signals": 102,                     // v3 新增：单独记 OOS 信号数
      "low_confidence": false,                // v3 修正：v2 漏这个字段
      "ai_degraded": false,                   // v3 新增：是否 AI Judge 降级
      "per_pattern": {
        "gartley": {"score": 82.1, "signals": 120, "win_rate": 0.68, "low_confidence": false},
        "bat": {"score": 76.4, "signals": 98, "win_rate": 0.61, "low_confidence": false},
        "crab": {"score": 65.2, "signals": 72, "win_rate": 0.44, "low_confidence": false},
        "butterfly": {"score": 70.8, "signals": 52, "win_rate": 0.52, "low_confidence": false}
      },
      "overfit_delta": 2.2,
      "pareto_front": true
    }
  ],
  "comparisons": [                            // v3 新增：多配置比较
    {
      "config_a_sha": "abc123...",
      "config_b_sha": "def456...",
      "p_raw": 0.043,
      "p_adjusted": 0.087,                    // v3 新增：BH FDR 校正
      "not_significant": false,               // v3 新增：标记位
      "effect_size": 0.18
    }
  ],
  "metadata": {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "timeframes": ["1h", "4h"],
    "date_range": ["2025-01-01", "2026-06-30"],
    "ai_judge_model": "gpt-4o",
    "ai_judge_prompt_sha": "sha256:...",      // v3 新增：提示词 sha
    "slippage_model": "standard",
    "exit_code": 0,                           // v3 新增：0=正常 / 2=样本不足
    "warnings": []                            // v3 新增：未通过数据最低要求时填充
  }
}
```

### 报告输出目录

```
bench/outputs/
├── br_20260730_001/
│   ├── report.html               # 完整 HTML 报告
│   ├── report.json               # 机器可读的评分数据
│   ├── leaderboard.json          # 排行榜数据（可被 app/ 引用）
│   ├── signals.csv               # 全部 SignalRecord（列顺序见下）
│   ├── charts/                   # 8 张核心图表（PNG）
│   └── configs/                  # 各配置的详细评分
│       ├── abc123.../
│       │   ├── per_pattern.json  # 分 pattern 统计
│       │   └── signals.csv       # 该配置的所有信号
│       └── ...
```

**`signals.csv` 列顺序（v3 显式约定，按评估流水线的填写顺序排列）**：

```
signal_id, run_id, params_sha,
timestamp, symbol, timeframe, pattern_type, pattern_family, direction, grade,
entry_price, stop_price, tp1, tp2, tp3, atr_at_entry, prz_width_atr, entry_offset_atr,
confluence_score, pattern_base_score, stability_verdict, regime, volume_authenticity_score,
outcome, net_rr, bars_held, exit_price, exit_reason,
mae, mfe, mae_atr_ratio, callback_depth, callback_bars, callback_volume_ratio,
hit_stop_before_tp, stop_zone_touches, price_efficiency,
split, crosses_boundary, weak_validity,
ai_score, ai_reasoning, ai_agreement, ai_confidence, ai_degraded
```

**测试位置（v3 修正）**：仓库已有 `tests/` 目录与 pytest-cov 流水线，**`bench/tests/` 不另起**，统一进 `tests/bench/`：

```
tests/bench/
├── __init__.py
├── test_dataset_builder.py
├── test_pipeline.py          # Stage 1/2/3/4a/4b 纯函数
├── test_scoring.py           # Level 1/2/3 聚合
├── test_judge.py             # AI Judge (mock LLM)
└── fixtures/
    ├── sample_signals.csv
    └── mock_judge_responses.json
```

原因是 `pytest tests/` 的覆盖率与 CI 流水线都基于顶层 `tests/`，拆分会增加 conftest.py 维护成本。

---

## 与现有系统的交互协议

### 输入

Bench 从以下系统读取：

```
1. TuningConstants（app/config/tuning.py）
   - 选择哪个配置进行评估
   - 通过 params_sha 与 ParetoPoint 关联

2. 历史 OHLCV 数据（通过 app/services/market_data.py 或 tradingview-bridge）
   - 数据源保持与现有系统一致
   - 支持的 symbol + timeframe 与生产一致

3. 信号引擎（app/services/signal_engine.py）
   - 调用 extract_candidates → score_candidate → rank_signals
   - 获取候选信号列表
```

### 输出

Bench 的输出被以下系统消费：

```
1. app/loop/pareto.py
   - BenchScore（归一化后）作为第 5 个 Pareto 目标维度
   - overfit_delta 作为额外参考指标

2. app/（报告 API）
   - 排行榜结果可通过 API 暴露给前端
   - HTML 报告供人工审阅

3. 开发者手动调参流程
   - 在调整 TuningConstants 后运行 Bench 验证效果
   - 对比本次运行与上次运行的 ConfigScore 变化
```

### 调用流程

```
runner.py 主流程：

1. 解析命令行参数
   --config      TuningConstants 路径或 inline 修改
   --symbols     交易对列表
   --timeframes  K 线周期列表
   --mode        full / quick（quick = 只跑 OOS、不跑 AI Judge）
   --slippage    ideal / standard / conservative

2. 加载配置 → 生成 params_sha

3. 获取历史数据 → 构建 SignalDataset
   ├── 数据覆盖检查（确保有足够 OOS 数据）
   ├── Walk-Forward 划分
   └── 运行信号引擎 → SignalRecord 列表

4. 执行流水线
   ├── Stage 1: 有效性评分
   ├── Stage 2: 回测执行 + 交易指标
   ├── Stage 3: 胜率评分
   ├── Stage 4a: 回调质量评分
   ├── Stage 4b: 技术评分
   └── Stage 4c: AI 评判

5. 聚合评分
   ├── Level 1: 单信号评分
   ├── Level 2: 配置评分（分 pattern + 加权汇总）
   └── Level 3: 总评分（含过拟合惩罚）

6. 输出
   ├── 报告（HTML + JSON）
   ├── Leaderboard 更新
   └── Pareto 数据（如果由 loop 驱动）
```

---

## 附录：权重校准方案

### 为什么这样分配权重？

当前权重设计基于以下原则：

| 评分维度 | 满分 | 权重 | 原理 |
|---|---|---|---|
| Stage 3 胜率 | 50 | 45% | 用户明确要求"胜率优先" |
| Stage 4a 回调质量 | 20 | 18% | 本 Bench 的核心创新，量化"信号稳定性" |
| Stage 4b 技术评分 | 10 | 9% | 复用现有信号引擎的成熟评分，控制占比 |
| Stage 4c AI Judge | 20 | 18% | 规则之外增加主观灵活性，但不超过 20% |
| Stage 1 有效性 | 10 | 9% | 基础过滤，权重较低 |

### 未来的校准方法

在 Bench 上线运行一段时间后，可以通过以下方式校准权重：

1. **相关性分析**：如果某个维度的分数与最终 outcome 相关性极低 → 降低权重或重构
2. **主成分分析**：识别各维度之间的共线性 → 合并冗余维度
3. **用户反馈**：将 Bench 预测的高分信号与实际交易结果对比 → 调整权重
4. **AB 测试**：不同权重版本在历史数据上的 AUC 对比

权重不应频繁调整。建议每季度根据上述分析结果校准一次，并在报告中注明权重版本号。

---

## 附录：与 v1 方案的关键差异汇总

| 方面 | v1 方案 | v2（优化版） |
|---|---|---|
| Stage 1 & 2 | 二进制门控 | 软评分 + 最低门槛 |
| 回测模型 | 无滑点/费率 | 三级滑点/费率模型 |
| 样本量检查 | 无 | 置信区间 + 三级标记 |
| Pattern 分层 | 无（混合评分） | 按 pattern 族分层，加权汇总 |
| 过拟合检测 | 无 | Walk-Forward IS/OOS 划分 |
| AI Judge | 自由打分 | 结构化 CoT + 盲评 + 多次采样 |
| Pareto 归一化 | 未处理 | z-score → sigmoid → [0,1] |
| 回调评分 | 仅 MAE/MFE + 深度 | 5 因子模型（含成交量、止损缓冲） |
| 报告图表 | 模糊提及 | 明确定义 8 张核心图表 |
| 最大信号分 | 100 | 110（超额满分允许补偿） |
| 统计检验 | 无 | Wilson 置信区间 + Fisher 检验 |

---

## v3 审计变更日志（2026-07-30）

v3 不是推翻 v2，是基于本仓库 (`pyharmonics-gpt`) 2026-07-30 实际代码做的第二轮复审。每一项都有具体证据：

| # | 类型 | v2 问题 | v3 修正 |
|---|---|---|---|
| 1 | **实现缺口** | Stage 3a 的 TP1/TP2/TP3 25/20/15 分级，仓库现有 `simulate_trades` 不支持 | 明确需扩展为 `simulate_ladder_trades`；v0.1 退化为单 target 时 `outcome` 字段保留扩展点 |
| 2 | **术语不一致** | SignalRecord 字段 `mae_atr_ratio` 与正文公式 "MAE / stop_distance" 单位不同 | 统一到 `MAE / atr_at_entry`；与 `mfe_atr_ratio` 同量纲 |
| 3 | **方向偏差** | `trade_metrics` 关键公式只写 long 分支 | 新增 short 分支：反向 `run_pnl_per_bar`、反向 `callback_depth`、反向 `buffer_consumption` |
| 4 | **窗口模糊** | `callback_volume_ratio` 写"回调期间均量 / 正常均量"，未指窗口 | 改为 "MAE 段内均量 / entry 前 20 根均量"，显式两窗口 |
| 5 | **边界缺失** | Walk-Forward 70/30 未规定 entry 在 IS / exit 在 OOS 的边界信号 | 跨边界信号按 entry 归段，附 `crosses_boundary` 标记 + OOS 分数折扣 |
| 6 | **多周期失真** | `--timeframes 1h,4h` 共用 IS/OOS 切分会让 1h 的 70% ≠ 4h 的 70%×4 | 每个 `(symbol, timeframe)` 独立切分；leaderboard 按对分桶 |
| 7 | **多重比较** | Fisher 检验无 p 值修正 | 强制 Benjamini-Hochberg FDR (q=0.1)；报告附 `p_adjusted` |
| 8 | **样本门槛** | 给出 high/medium/low 三级标签，但无最低数据量 | 新增硬门槛：≥180 天 OHLCV、≥30 OOS 信号、≥5 per family；不满足退出码 = 2 |
| 9 | **AI Judge 乐观** | 盲评 × 0.6 + 后见 × 0.4 偏向把后见当独立验证 | 改为 × 0.7 + × 0.3；加 cost guard（最大调用数、并发、模型 fallback） |
| 10 | **ParetoPoint 破坏** | `BenchParetoPoint(ParetoPoint)` 继承会让 `_safe` tuple 排序索引错位 | 改为 `BenchAugmentedParetoPoint` 组合；保留原 4 维 ParetoPoint 不动 |
| 11 | **leaderboard schema** | 缺 `low_confidence`、`win_rate_ci`、`comparisons` 等字段 | 补全 schema（13 个字段）；加 `bench_version` / `weights_version` / `exit_code` / `warnings` |
| 12 | **CLI 不对齐** | runner.py 缺 `--start/--end/--window/--step/--horizon` | 补全 CLI；参数名直接复用 `scripts/backtest_harmonic_lib.py` 的语义 |
| 13 | **入场区失真** | Stage 1 不惩罚"PRZ 已被价格越过"的信号；实测 11/16 BTC + 8/11 ETH 因此被 skip | 新增 `entry_offset_atr` 字段 + Stage 1 第 5 子项"入场区可达性"（满分 2） |
| 14 | **聚合权重漏** | `weak_validity` 标签只说"不删除"，不说聚合权重 | 明确 `weak_validity` 信号进 ConfigScore 时按 0.5× 权重 |
| 15 | **CSV 列序未约** | `signals.csv` 仅说"全部 SignalRecord"，无列序 | 显式 45 列 CSV 列序（含 v3 新增 4 字段） |
| 16 | **测试位置不一致** | 提议 `bench/tests/`，但仓库已有 `tests/` 与 pytest-cov | 改为 `tests/bench/`，与现有 pytest 流水线对齐 |
| 17 | **regime 标签未联动** | `worst_regime_sharpe` 按 regime 分桶，但 bench_score 没接 regime | bench_score 必须按 regime 分桶聚合；z-score 在每个 regime 内做，不跨 regime |
| 18 | **现状未标** | 文档未声明 bench/ 是否已实现 | 顶部加 ⚠️ 状态横幅：截至 2026-07-30 仍是蓝图；唯一可跑的 Stage 2 极简版在 `scripts/` |

**v3 未做的事**（留给 v4 或实现阶段）：
- 信号级 A/B 检验（v3 只在配置级做 BH FDR）
- 多 regime 间的 transfer learning（避免 trending 段调好的参数在 ranging 段崩盘）
- LLM-as-judge 的 prompt 自动 evolution（当前 prompt 是手写 CoT，无 A/B 框架）
- HTML 报告模板与 8 张图的具体 API（v3 只列图表名，不规定 backend 是 plotly 还是 matplotlib）
- 评测指标与生产实盘结果的因果归因（bench 高分不等于实盘赚钱）

**v3 实现优先级建议**（如启动 bench v0.1）：
1. Stage 1/3/4b 纯函数打分（无 LLM）→ 1 天
2. trade_metrics + 多 target ladder 扩展 → 1 天
3. IS/OOS 切分 + 边界信号处理 → 半天
4. ParetoPoint 组合封装 + bench_version 字段 → 半天
5. JSON + CSV 输出 + 8 张静态图（matplotlib）→ 1 天
6. AI Judge 框架 + cost guard + mock 测试 → 1 天

合计 **~5 天** 出一个可用的 v0.1，含全部 v3 强约束、Stage 2/3/4a/4b 完整打分、leaderboard + 报告，但 AI Judge 用 mock LLM 跑通协议。
