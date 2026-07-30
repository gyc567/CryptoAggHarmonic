# HarmonicSignal-Bench：和谐形态交易信号回调与胜率评判基准

> 本文档是 bench/ 目录的设计蓝图。  
> 参考: QuantCode-Bench (Lime AI Lab 2026, https://limexailab.github.io/QuantCode-Bench/)  
> 集成对象: app/loop/pareto.py（四维 Pareto 优化）  
> 版本: v2（经过 AI benchmark 专家审计并重构）

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
    mae_atr_ratio: float | None     # MAE / ATR
    callback_depth: float | None    # 入场后最大回调（与预期方向相反的走势深度，单位 ATR）
    callback_bars: int | None       # 回调持续 K 线数
    callback_volume_ratio: float | None  # 回调期间均量 / 正常均量，>1 = 放量回调
    hit_stop_before_tp: bool | None # 是否先到止损区再反转
    stop_zone_touches: int | None   # 触及止损区次数
    price_efficiency: float | None  # TP 达成 K 线数 / 总持仓 K 线数（越高越好）

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

**软门槛**：总分 < 4 → 标记为 `weak_validity`，在最终报告中单独归入"低质量信号"分类，但不从数据集中删除。

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

关键公式（以多头为例）：

```
每根 K 线的运行盈利 = (low - entry) / (stop - entry)   # 负值 = 亏损
MAE = abs(min(运行盈利, 0)) × stop_distance    # 最大不利亏损额
MFE = max(高 - entry, 0)                      # 最大有利盈利额

回调深度 = max(entry - low, 0) / atr_at_entry  # 单位 ATR
回调放量 = 回调期间平均成交量 / 前 20 根平均成交量
```

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

**最终 AI 分数 = 盲判分 × 0.6 + 后见分 × 0.4**

**采样**：对每个信号做 3 次独立盲评（不同随机种子），取中位数作为最终 `ai_score`。

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

### ParetoPoint 扩展

```python
@dataclass
class BenchParetoPoint(ParetoPoint):
    """扩展原 ParetoPoint，加入 Bench 相关字段。"""
    bench_score: Optional[float]    # 原始 score
    bench_normalized: Optional[float]  # 归一化到 [0,1] 后的值
    oos_bench_score: Optional[float]   # OOS 评分
    overfit_delta: Optional[float]     # IS - OOS
    signal_count: int = 0
    low_confidence: bool = False
```

### 集成方式

在 `app/loop/driver.py` 中，每次生成新候选后：
1. 运行回测 → 得到 sharpe/calmar/profit_factor
2. 运行 Bench → 得到 bench_score
3. 将 bench_score 归一化后加入 objectives tuple
4. 调用 `pareto_set.add(bench_pareto_point)`

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
  "timestamp": "2026-07-30T12:00:00Z",
  "configs": [
    {
      "params_sha": "abc123...",
      "rank": 1,
      "config_score": 78.3,
      "oos_score": 76.1,
      "win_rate": 0.62,
      "avg_rr": 2.1,
      "total_signals": 342,
      "confidence": "high",
      "per_pattern": {
        "gartley": {"score": 82.1, "signals": 120, "win_rate": 0.68},
        "bat": {"score": 76.4, "signals": 98, "win_rate": 0.61},
        "crab": {"score": 65.2, "signals": 72, "win_rate": 0.44},
        "butterfly": {"score": 70.8, "signals": 52, "win_rate": 0.52}
      },
      "overfit_delta": 2.2,
      "pareto_front": true
    }
  ],
  "metadata": {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "timeframes": ["1h", "4h"],
    "date_range": ["2025-01-01", "2026-06-30"],
    "ai_judge_model": "gpt-4o",
    "slippage_model": "standard"
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
│   ├── signals.csv               # 全部 SignalRecord
│   ├── charts/                   # 8 张核心图表（PNG）
│   └── configs/                  # 各配置的详细评分
│       ├── abc123.../
│       │   ├── per_pattern.json  # 分 pattern 统计
│       │   └── signals.csv       # 该配置的所有信号
│       └── ...
```

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
