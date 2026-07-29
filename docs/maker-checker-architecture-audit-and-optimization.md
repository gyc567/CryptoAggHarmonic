# 谐波回测系统 Maker-Checker 分离架构 —— 审计报告与优化方案

> **文档状态**: v1.1（经审计优化）
> **v1.0 → v1.1 关键变更**（详见 §四 审计建议摘要）：
> - 明确 Maker LLM 输出 **mutation operations** 而非 raw parameter values（防止 LLM 破坏几何不变量）
> - 明确 `maker_norm_score` 来源（= 归一化的 `expected_impact.sharpe`，落 [0,1]）
> - 澄清 Checker 与 M4 启发式 `app/loop/checker.py` 的边界（**互补不重复**）
> - 5 维 Pareto 向后兼容规则（旧点 `checker_confidence=None` → 当作 -∞ 最差处理）
> - 增加 Phase 0（基线测量）和 Phase 5（校准与上线门禁）
> - 增加 §2.7 信息隔离层、§2.8 校准与回归测试、§2.9 回滚与特性开关、§2.10 成功度量
> - config.yaml 新增 `prompt_version`、`isolation_level`、`calibration_set_id`、`run_mode`、`MAKER_CHECKER_ENABLED` 开关
> - 所有集成点补充文件:行号引用
>
> **参考**: Loop Engineering 最佳实践 — Maker（创作者）与 Checker（检查者）必须为独立的 AI 代理/系统，使用不同的提示词和不同的模型，配置放在一个固定文件中随时调整。

---

## 一、现状审计

### 1.1 核心发现：Maker-Checker 完全耦合

当前系统将**信号生成者（Maker）**和**验证检查者（Checker）**的角色完全耦合在同一个流程中。调优循环（`app/loop/`）、信号引擎（`app/services/signal_engine.py`）和回测脚本（`.scratch/backtest/run_backtest_v3.py`）三者紧密交织，没有任何独立代理介入验证。

### 1.2 四大耦合点

#### 耦合点 A：调优循环直接调用回测脚本

**文件**: `app/loop/worker.py` 第 92–101 行

```python
cmd = [
    sys.executable,
    ".scratch/backtest/run_backtest_v3.py",
    "--symbol-set", symbol_set,
    ...
    "--tuning-yaml", str(tuning_path),
]
```

Maker 生成的参数集被同一个回测脚本评估，没有独立的 Checker 介入。

#### 耦合点 B：回测使用生产环境的信号管线

**文件**: `.scratch/backtest/run_backtest_v3.py` 第 283 行

```python
signal = build_signal(sub, "4h", [cand])
```

回测调用**生产环境完全相同的** `build_signal()` 函数生成信号和执行交易。Maker 的偏见（例如 Gartley 模式 +5 分倾斜）直接影响回测结果，Checker 没有机会用独立标准重新评估。

#### 耦合点 C：回测内 monkey-patch 评分函数

**文件**: `.scratch/backtest/run_backtest_v3.py` 第 258–278 行

```python
import app.services.signal_engine as _se_module
_original_grade = _se_module.grade
def _backtest_grade(...):
    # 回测专用评分（monkey-patch）
    ...
_se_module.grade = _backtest_grade
```

回测使用与生产不同的评分逻辑，但在同一个进程中完成，无独立 Checker。

#### 耦合点 D：TuningConstants 单一配置

**文件**: `app/config/tuning.py`

虽然 `TuningConstants` 设计精巧（冻结数据类、热替换、`__post_init__` 验证），但它是一套单一配置。Maker 和 Checker 如果共享同一套参数，则"检查"毫无意义。

### 1.3 现有"伪独立"组件审计

| 组件 | 看起来像 Checker | 实际性质 |
|------|------------------|---------|
| `app/loop/checker.py`（M4 启发式 checker） | 候选审核（低样本/制度失衡/熊市极端/健身-交易权衡） | **启发式规则引擎**，非 LLM 代理；本方案中的 Checker LLM 应作为它的**增强层**（捕捉 LLM 能看到的模式层面的问题），不是替代品。两者判定均需通过才能进入帕累托 |
| `app/domain/validation.py`（四支柱验证） | 对候选信号做有效性检查 | 同一 pipeline 中的环节，非独立代理 |
| `stability_verdict()`（多窗口重检测） | 跨窗口验证形态稳定性 | 与信号生成共享同一套 `TuningConstants` |
| `app/loop/pareto.py`（帕累托前沿） | 多目标择优 | 所有候选由同一回测脚本评估，无第二意见 |
| `app/loop/regime_buckets.py`（M5 制度聚合） | 牛/熊/震荡分组评估 | 纯量化指标，无独立判断 |

### 1.4 关键缺失

1. **无独立的 Checker LLM 代理** — 现有 `app/loop/checker.py` 只跑规则，没有 LLM 视角
2. **无固定的 Maker/Checker 配置文件** — Maker 和 Checker 的模型配置应集中管理、随时可调
3. **Maker 创意层缺失** — 当前只有数学变异，没有 LLM 驱动的有意图变异
4. **无对抗性验证** — 无法发现 Maker 的过度拟合或参数漂移
5. **无人类审查切入点** — 优化循环完全自动化，关键决策点无人类介入
6. **无基线测量** — 上线新架构前不知道当前系统表现，无法证明改进
7. **无回滚开关** — 如果新架构效果更差，无法快速回退

---

## 二、优化方案

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                  Maker-Checker 架构总览（v1.1）                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  外部调优环（Evolution Loop）                                           │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ 1. Maker 代理（批量提案 — 一次 LLM 调用输出 λ 个 proposal）       │   │
│  │    - LLM 路径（run_mode=mix 时占 60%）                          │   │
│  │      * 输出 mutation ops（cluster + direction + magnitude）      │   │
│  │      * 而非 raw parameter values（避免破坏 fib_tp1<tp2<tp3）     │   │
│  │      * 附带 self_score（= 归一化的 expected_impact.sharpe）      │   │
│  │    - 传统变异路径（占 40%，保留 app/loop/mutation.py）            │   │
│  │    - 模型：GPT-4 Turbo / Claude 3.5 Sonnet（创意型, T≈1.2）      │   │
│  │    - seed 控制：temperature>0 时按 generation seed 锁定            │   │
│  │         ↓                                                        │   │
│  │ 2. 执行层（回测引擎 — 不变）                                       │   │
│  │    - 对每个 candidate 运行 v3 回测                                │   │
│  │    - 输出：trade ledger + summary.json + by_regime blobs          │   │
│  │         ↓                                                        │   │
│  │ 3. 信息隔离层（isolation.py — NEW）                                │   │
│  │    - 剥离 Maker 的 clusters_touched / maker_intent / reasoning    │   │
│  │    - 剥离 generation 编号和 parent lineage                       │   │
│  │    - 保留：OHLCV、trades、metrics、by_regime、by_symbol            │   │
│  │         ↓                                                        │   │
│  │ 4. Checker 代理（独立验证 + LLM）                                  │   │
│  │    - LLM：用独立标准评判（跨品种一致、制度鲁棒、统计充分）           │   │
│  │    - 与 M4 启发式 checker **并行** 通过才能进入帕累托             │   │
│  │    - 输出：checker_score + confidence + flags + accept            │   │
│  │    - 评分经 calibration.py 校准到 [0,1] 实际概率                   │   │
│  │    - 模型：GPT-4o / Claude 3 Haiku（分析型, T≈0.1）              │   │
│  │         ↓                                                        │   │
│  │ 5. 裁决层（Arbiter）                                              │   │
│  │    - 合并 Maker self_score 与 Checker calibrated_score            │   │
│  │    - 分歧检测 → 自动驳回 / 加权合并 / 人类审查                    │   │
│  │    - 帕累托前沿升级为 5 维（新增 checker_confidence）              │   │
│  │    - 旧 4 维点 checker_confidence=None → 视为 -∞（不支配新点）     │   │
│  │         ↓                                                        │   │
│  │ 6. 特性门（feature flag）                                          │   │
│  │    - MAKER_CHECKER_ENABLED=false → 回退到原 driver，无 LLM 调用    │   │
│  │    - 紧急回滚开关，无需改代码                                       │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  内部信号环（Signal Pipeline — 保持现有实现不变）                       │
│  └─ 生产环境使用已有的 v4 pipeline                                      │
│     build_signal → score_candidate → rank_signals → Signal             │
│     但 Checker 可用独立逻辑对最终信号进行二次验证                         │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 新增文件结构

```
app/loop/maker_checker/
├── config.yaml                  ← Maker/Checker 固定配置（含 feature flag）
├── config_test.yaml             ← 测试用配置（小模型 + 小数据）
├── schemas.py                   ← Pydantic: Proposal, Verdict, MergeResult, MakerSelfScore
├── isolation.py                 ← 信息隔离层（从回测结果剥离 Maker 意图）
├── maker_agent.py               ← Maker：LLM batch proposal + 传统变异双路径
├── checker_agent.py             ← Checker：LLM 独立评估 + 与 M4 heuristic 共存
├── arbiter.py                   ← 裁决：分歧检测 / 加权合并 / 5 维 Pareto back-compat
├── calibration.py               ← Checker 评分校准（platt / isotonic）
├── runner.py                    ← Maker-Checker 循环入口（带 feature flag）
└── tests/
    ├── test_maker.py            ← 输出符合 mutation op schema、seed 重放稳定
    ├── test_checker.py          ← 输出符合 verdict schema、calibration 提升
    ├── test_isolation.py        ← 验证 Checker 输入不含 Maker 意图（leakage < 阈值）
    ├── test_arbiter.py          ← 仲裁决策树 + 5 维 Pareto back-compat
    ├── test_calibration.py      ← 校准曲线一致性（reliability diagram）
    └── fixtures/
        ├── maker_prompts.json       ← golden prompt → expected proposal
        ├── checker_prompts.json     ← golden price data → expected verdict
        └── calibration_set.jsonl    ← 已知分数的验证集（hand-labeled）
```

### 2.3 核心：固定的配置文件 `config.yaml`

这是 Loop Engineering 最佳实践的关键：Maker 和 Checker 的模型配置放在一个固定文件中，可随时调整，无需改动代码。

```yaml
# app/loop/maker_checker/config.yaml
# Maker-Checker 分离架构的固定配置（v1.1）
# 修改此文件后 re-run 调优循环即可生效

# ===== 特性门（紧急回滚）=====
feature_flags:
  MAKER_CHECKER_ENABLED: true   # false → 完全回退到原 driver，无 LLM 调用
  MAKER_ENABLED: true            # 关闭则只跑传统变异路径
  CHECKER_ENABLED: true          # 关闭则只用 M4 启发式 checker
  CHECKER_USE_M4_HEURISTIC: true # 关闭则不要求 M4 启发式也通过（仅 LLM 通过即可）

# ===== Maker =====
maker:
  role: "Harmonic Pattern Parameter Creator"
  enabled: true
  model: "gpt-4-turbo"
  temperature: 1.2
  max_tokens: 2000
  prompt_version: "v1.1"          # 每次修改 system_prompt 需 bump 版本号
  seed_strategy: "per_generation" # per_generation | fixed | none
  fixed_seed: null                # seed_strategy=fixed 时使用

  system_prompt: |
    你是斐波那契和谐交易系统的参数创作者（Maker）。

    你的任务：
    1. 基于历史帕累托前沿和回测结果，生成 λ 个调优提案（每代一次调用）
    2. 每个提案输出 **mutation operation**（不是 raw values）：
       - clusters_touched: 变异的集群列表（单次只动一个集群）
       - diff: {field_name: signed_magnitude_pct}    # 例如 +15 表示 +15%
       - maker_intent: 自由文本意图标签
       - reasoning: 为什么这个变异应该有效（≤ 200 字）
       - expected_impact: {sharpe: "+0.3", calmar: "-0.05", worst_regime: "neutral"}
       - self_score: 0-1 之间，表示你对这次提案的信心（校准到 [0,1]）
    3. 探索参数空间中尚未充分探索的区域
    4. 你可以看到完整的帕累托前沿数据和每代的完整历史

    硬约束（违反即视为无效提案）：
      - 不要输出 raw parameter values（必须以 diff 形式表达）
      - 不要触碰 fib_tp1/tp2/tp3 相对排序
      - 不要触碰 frozen 字段（extended_patterns, htf_rule, funding_confluence_default, tp_close_pcts）
      - 单个 diff 的 magnitude 不超过 ±50%
      - 每次只变异 1 个集群
      - 输出必须是合法 JSON，可被 Pydantic Proposal schema 解析

    输出 schema（必须严格匹配）：
    {
      "proposals": [
        {
          "clusters_touched": ["C4 Macro"],
          "diff": {"extreme_deviation_pct": 15.0},
          "maker_intent": "increase_sharpe_in_bear",
          "reasoning": "...",
          "expected_impact": {"sharpe": "+0.3 in bear", "calmar": "neutral", "worst_regime": "neutral"},
          "self_score": 0.7
        }
      ]
    }

  # 传统数学变异（基线，用于 A/B 与 LLM 路径混合）
  traditional_variation:
    enabled: true
    mix_ratio: 0.4                # 每代 40% 子代走传统变异路径
    sigma_scale: 1.0
    n_mutations: 1

# ===== Checker =====
checker:
  role: "Harmonic Pattern Performance Validator"
  enabled: true
  model: "gpt-4o"                 # 必须与 maker.model 不同提供商/不同型号
  temperature: 0.1                # 低温度保证评判一致性
  max_tokens: 1500
  prompt_version: "v1.1"

  # 信息隔离级别
  isolation_level: "strict"       # strict | moderate | minimal
    # strict   — 剥离所有 Maker 痕迹（推荐）
    # moderate — 只剥离 maker_intent / reasoning，保留 lineage
    # minimal  — 几乎不隔离（仅调试用）

  # 校准集 ID（用于 calibration.py）
  calibration_set_id: "v1.1-balanced-2026Q3"
  calibration_method: "platt"     # platt | isotonic | none

  system_prompt: |
    你是斐波那契和谐交易系统的独立验证者（Checker）。

    关键规则：你只看价格数据和形态的最终表现，不知道 Maker 的创作理由。
    Maker 试图优化什么、改动了哪些参数，对你完全不透明。
    你的输入不包含 clusters_touched、maker_intent、reasoning、generation 编号。

    你的任务：
    1. 用独立标准评判参数集是否真的有效
    2. 对任何可疑的过度拟合迹象发出警告
    3. 关注跨品种一致性：BTCUSD / ETHUSD / SOLUSD 的结果是否一致？
    4. 关注制度鲁棒性：牛市 / 熊市 / 震荡市表现是否均衡？
    5. 关注统计充分性：结论是否基于足够多的交易？

    验证指标（参考值，非硬约束）：
      - 跨品种 Sharpe 变异系数 < 0.5
      - 最大回撤 R 倍数 < 10
      - 每个制度至少 10 笔交易
      - 胜率在 40%-70% 之间

    输出 schema（必须严格匹配）：
    {
      "candidate_id": "<uuid>",
      "checker_score": 0.72,        # 校准后的 [0,1] 分数
      "confidence": 0.85,           # 你对这次判断的把握
      "components": {
        "cross_symbol_consistency": 0.8,
        "regime_robustness": 0.65,
        "trade_quality": 0.75,
        "statistical_sufficiency": 0.9
      },
      "flags": [
        {"severity": "high|medium|low", "issue": "..."}
      ],
      "accept": true,
      "feedback": "自然语言审查意见（≤ 200 字）"
    }

  rejection_threshold: 0.3

# ===== 裁决 =====
arbiter:
  merge_strategy: "weighted"
  maker_weight: 0.4
  checker_weight: 0.6

  human_review_trigger:
    enabled: true
    maker_checker_gap_threshold: 0.4
    inverse_gap_threshold: 0.3
    stagnation_generations: 10
    # stagnation 定义（v1.1 细化）：
    #   - Pareto 5 维同时无改进 = 真实停滞
    #   - 仅 checker_confidence 提升不算停滞（避免被 LLM 噪声触发）
    #   - 仅 worst_regime_sharpe 提升不算停滞

  pareto_extra_dimension: "checker_confidence"
  # back-compat: 旧 Pareto 点（来自 M2-M5 的 4 维点），
  #   checker_confidence 视为 -∞，不支配任何新点，但可被新点支配。
```

### 2.4 Maker 代理设计

**新增文件**: `app/loop/maker_checker/maker_agent.py`

```
MakerAgent 设计思路：

功能入口：
  propose_batch(parent_yaml, history, pareto_front, config, seed) → list[Proposal]

关键设计点（v1.1 修正）：
  1. **Batch 提案**：LLM 一次调用输出 λ 个 proposal（不是每子代一次调用）
     - 大幅降低 API 成本（~1/N）
     - 允许 LLM 在多个 proposal 间做对比权衡
     - 输入 schema 强制要求 proposals 数组长度 = λ
  2. **输出 mutation ops 而非 raw values**：
     - LLM 只决定"动哪个集群 + 方向 + 幅度"
     - 由代码（app/loop/mutation.py）应用 diff，确保几何不变量
     - Pydantic schema 校验 cluster name 必须在 DEFAULT_CLUSTER_MAP 中
  3. **seed 控制**：当 seed_strategy=per_generation 时，generation seed 作为 LLM 调用
     的 deterministic seed（不同模型支持程度不同，记录但不全依赖）
  4. **self_score 来源**：Maker 输出 self_score ∈ [0,1]，后续 Arbiter 用作
     maker_norm_score。如果 LLM 不输出 self_score，calibration.py 用
     Platt scaling 从历史 (proposal, actual_fitness) 对拟合。

双路径变异策略：
  路径 A — LLM 驱动（run_mode=mix 时占 60%）：
    1. 读取历史帕累托前沿（PARETO.json）和每代 HISTORY
    2. 读取当前 TuningConstants（不暴露给 Checker）
    3. 将结构化数据打包成 LLM 上下文
    4. LLM 输出 λ 个 mutation ops
    5. 由代码应用 diff，产出 λ 个 TuningConstants 提案

  路径 B — 传统数学变异（占 40%）：
    保留现有 app/loop/mutation.py 的 sensitivity-scaled σ 变异
    作为可对比的基线，用于衡量 LLM 路径是否真的更好

A/B 测试支持（v1.1 新增）：
  - run_mode=llm_only   — 100% LLM 提案
  - run_mode=trad_only  — 100% 传统变异（= 当前行为）
  - run_mode=mix        — 默认，60% LLM + 40% 传统

预期影响跟踪（v1.1 新增）：
  - 历史记录每条 proposal 的 expected_impact vs actual_fitness_diff
  - 当 Maker 的 |expected - actual| > 0.3 连续 ≥ 5 次时，记录到 HISTORY
  - 这本身就是一种 calibration 信号
```

### 2.5 Checker 代理设计

**新增文件**: `app/loop/maker_checker/checker_agent.py`

```
CheckerAgent 设计思路：

功能入口：
  verify(candidate_id, isolated_results, config) → Verdict

严格的信息隔离（核心设计原则）：
  Checker 的输入只包含：
    ✓ 价格 OHLCV 数据（原始数据）
    ✓ 每笔交易的 symbol / 方向 / 入场价 / 止损 / 止盈 / 退出价 / r_multiple
    ✓ 按制度（牛/熊/震荡）分组的绩效汇总
    ✓ 跨品种汇总
    ✓ calibration_set_id 引用（让 Checker 知道评分口径）

  Checker 看不到（由 isolation.py 强制剥离）：
    ✗ Maker 的创作理由和意图
    ✗ 被变异的参数集群和幅度
    ✗ 历史帕累托前沿中的"血缘关系"
    ✗ 候选的 gen 编号和聚类标签

与 M4 启发式 checker 的关系（v1.1 关键澄清）：
  - 两者**并行**运行，互不替代
  - M4 checker.py 给出 heuristics_decision ∈ {promising, suspicious, rejected}
  - Checker LLM 给出 llm_decision ∈ {accept, reject}
  - 组合规则：
      * M4=rejected → 直接 reject（启发式规则视为硬约束）
      * M4=promising AND LLM=accept → accepted
      * M4=promising AND LLM=reject → rejected（LLM 看到启发式没看到的问题）
      * M4=suspicious AND LLM=accept → suspicious_to_human（人类审查）
      * M4=suspicious AND LLM=reject → rejected

独立评估标准：
  1. 跨品种一致性检验
     - Maker 可能只在 BTC 上有效，Checker 会标记
     - 每个品种的 Sharpe / Calmar / Profit Factor 的变异系数

  2. 交易序列质量检验
     - 是否存在自相关性（过度拟合的信号密度异常高）
     - 止损距离是否过于 tight

  3. 制度转换敏感性
     - 参数在 regime change（牛→熊）时的表现是否合理
     - 有无在某制度下"爆亏"但被其他制度掩盖

  4. 统计充分性
     - 每个品种的交易数量是否充足
     - 结论是否基于少数"幸运交易"

泄漏测量（v1.1 新增）：
  - 在 test_isolation.py 中，构造一组"对照"案例：
    * Case A: 真实 Maker output → Checker verdict
    * Case B: 同一 trade ledger，但 clusters_touched 改成"虚假集群名"
    * 如果 Checker verdict 显著不同 → 隔离失败
  - 用 BLEU/embedding 相似度量化 leakage rate
  - leakage_rate < 0.1 才认为 strict 隔离有效

校准（v1.1 新增）：
  - calibration_set.jsonl 是 hand-labeled 的 (metrics, true_quality) 对
  - 用 platt scaling 将 checker_score 校准到 P(true_quality_good | metrics)
  - 校准后 checker_score = 0.7 意味着"P(参数集有效) ≈ 70%"
  - reliability diagram 必须在测试中验证（test_calibration.py）

输出 Verdict 结构：
  {
    "candidate_id": "<uuid>",
    "checker_score": 0.72,
    "confidence": 0.85,
    "components": { ... },
    "flags": [ ... ],
    "accept": true/false,
    "feedback": "..."
  }
```

### 2.6 裁决层设计

**新增文件**: `app/loop/maker_checker/arbiter.py`

```
Arbiter 设计思路：

决策树（v1.1 明确化）：
  1. M4=rejected                          → 自动驳回
  2. M4=promising AND LLM=reject          → 自动驳回（LLM 看到启发式没看到的问题）
  3. M4=promising AND LLM=accept          → 加权合并评分，计入 5 维 Pareto
  4. M4=suspicious AND LLM=accept         → suspicious_to_human（待人类审查）
  5. M4=suspicious AND LLM=reject         → 自动驳回
  6. M4=promising AND LLM=accept BUT gap>阈值 → 触发人类审查

加权评分公式（v1.1 修正）：
  maker_norm_score = proposal.self_score        # 来自 LLM 输出 ∈ [0,1]
  checker_score    = verdict.checker_score      # 校准后 ∈ [0,1]
  final_score      = maker_weight * maker_norm_score + checker_weight * checker_score
  其中 maker_weight + checker_weight = 1.0

  旧定义中 maker_norm_score 来源不清；v1.1 明确为 self_score。
  若 LLM 未输出 self_score，fallback 用历史平均 actual_fitness_diff 归一化到 [0,1]。

分歧触发人类审查条件（v1.1 细化）：
  - Maker 和 Checker 评分差距 > config 中 maker_checker_gap_threshold
  - 参数集落入参数空间的"高新奇度"区域且 Checker 拒绝
  - 连续 stagnation_generations 代无帕累托前沿更新（5 维同时无改进）
  - Maker self_score 与 actual_fitness_diff 偏差 > 0.3 连续 ≥ 5 次

帕累托前沿增强（v1.1 向后兼容）：
  现有 4 个目标（sharpe, calmar, profit_factor, worst_regime_sharpe）
  新增第 5 个目标：checker_confidence

  向后兼容规则：
    - 旧 4 维 Pareto 点（ParetoPoint v1）checker_confidence = None
    - 在 5 维 dominates() 函数中，None 视为 -∞：
        * 旧点不支配任何新点（None < 任何 checker_confidence）
        * 旧点可被新点支配
    - 因此新架构不会"丢掉"任何旧点，但会优先选 5 维均更好的新点
    - 升级测试见 test_arbiter.py::test_4d_to_5d_backcompat

人类审查接口（v1.1 落地化）：
  - v1：CLI 命令 `python -m app.loop.maker_checker.review --pending`
    列出所有 suspicious_to_human 候选，打印三栏对比：
    [Maker 创作理由 | Checker 验证报告 | 原始 metrics]
    操作：a/r/m（accept/reject/modify-and-resubmit）
  - v2（后续）：Web UI（暂不实现）
  - 每次审查决定记录到 HUMAN_REVIEW_LOG.jsonl
```

### 2.7 信息隔离层（NEW）

**新增文件**: `app/loop/maker_checker/isolation.py`

```
设计目标：
  在 CheckerAgent.verify() 调用之前，从回测结果中剥离所有 Maker 痕迹。

剥离规则（strict 模式）：
  - 删除顶层字段：
      * clusters_touched
      * maker_intent
      * reasoning
      * expected_impact
      * self_score
      * prompt_version
      * generation_id
      * parent_id
      * diff (相对于 parent 的 diff)
  - 重命名/哈希候选标识：
      * candidate_id 用 SHA256(original_id + salt) 替换
      * salt 每次 generation 更换一次
  - 保留字段：
      * OHLCV 原始数据
      * trade ledger 完整字段
      * summary.json 所有 metrics
      * by_regime blobs
      * by_symbol 汇总
      * calibration_set_id（让 Checker 知道评分口径）

中度隔离（moderate）：
  - 保留 candidate_id 原值（便于人工追溯）
  - 删除 clusters_touched / maker_intent / reasoning

最小隔离（minimal）：
  - 仅删除 maker_intent / reasoning
  - 用于本地调试 Checker 行为

泄漏测试（test_isolation.py）：
  - 构造 5 个真实候选 + 5 个 cluster_label_shuffled 候选
  - 对比 Checker verdict 分布：KL 散度 < 0.1 视为无泄漏
  - 阈值由 config.isolation_level 控制
```

### 2.8 校准与回归测试（NEW）

**新增文件**: `app/loop/maker_checker/calibration.py` + `tests/`

```
校准（calibration.py）：
  - 输入：calibration_set.jsonl 中 hand-labeled 案例
      {"metrics": {...}, "true_quality": "good|neutral|bad"}
  - 输出：platt scaling 参数（a, b），使 calibrated_score = sigmoid(a * raw + b)
  - 评估：
      * reliability diagram：x 轴是 calibrated_score 分桶，y 轴是真实正例率
      * Expected Calibration Error (ECE) < 0.05
      * 校准数据每季度更新一次（市场 regime 漂移会改变评分口径）

回归测试结构（tests/）：
  test_maker.py：
    - test_maker_output_matches_schema   # Pydantic Proposal schema 校验
    - test_maker_seed_replay_stable      # 同 seed + 同 temperature → 同 output
    - test_maker_respects_frozen_fields  # diff 不能触碰 frozen 字段
    - test_maker_geometric_invariants    # fib_tp1 < tp2 < tp3 永不被破坏
    - test_maker_proposal_count_matches_lambda

  test_checker.py：
    - test_checker_output_matches_schema # Pydantic Verdict schema 校验
    - test_checker_score_in_unit_interval
    - test_checker_accepts_consistent_candidate
    - test_checker_rejects_obvious_overfit

  test_isolation.py：
    - test_strict_isolation_removes_all_maker_artifacts
    - test_isolation_leakage_rate_below_threshold
    - test_isolation_preserves_required_fields

  test_arbiter.py：
    - test_decision_tree_all_paths        # 6 条分支全覆盖
    - test_weighted_merge_formula
    - test_4d_to_5d_pareto_backcompat     # 旧点 checker_confidence=None
    - test_stagnation_detection_5d

  test_calibration.py：
    - test_platt_scaling_converges
    - test_reliability_diagram_ece_below_threshold
    - test_calibration_set_size_sufficient (n >= 50)

  fixtures/：
    - maker_prompts.json    # 5-10 个 golden prompt → expected proposal
    - checker_prompts.json  # 5-10 个 golden metrics → expected verdict
    - calibration_set.jsonl # >= 50 个 hand-labeled (metrics, true_quality) 对
```

### 2.9 回滚与特性开关（NEW）

```
设计目标：
  Maker-Checker 架构如果上线后发现效果比原 driver 更差，必须能秒级回退。

实现：
  1. config.yaml 中的 feature_flags 段（见 §2.3）：
       MAKER_CHECKER_ENABLED: false  → runner 跳过整个子系统，直接调用原 driver
       MAKER_ENABLED: false          → 只跑传统变异路径
       CHECKER_ENABLED: false        → 只用 M4 启发式 checker
       CHECKER_USE_M4_HEURISTIC: false → 关闭 M4 硬约束，仅 LLM 决策

  2. CLI 覆盖（无需修改 yaml）：
       python -m app.loop.driver --no-maker-checker
       python -m app.loop.driver --no-llm-maker
       python -m app.loop.driver --no-llm-checker

  3. prompt 版本追踪：
       - 每次修改 system_prompt 必须 bump prompt_version
       - HISTORY 记录同时写入 prompt_version
       - skills_version 已有类似机制（app/loop/skills_version.py）

  4. 紧急回滚 SOP：
       a. git revert 最近一个引入 Maker-Checker 的 commit
       b. 或：MAKER_CHECKER_ENABLED=false + 重启 runner
       c. 检查 STATE.md 是否恢复到上次良好状态
```

### 2.10 成功度量（NEW）

```
上线门禁（Phase 5 验证用）：

  Baseline（Phase 0 测量）：
    - 当前 driver 在 5 代内 Pareto 接受率：_____ %
    - 当前 driver 的最佳 on-Pareto 点 sharpe：_____
    - 当前 driver 的 worst_regime_sharpe：_____
    - 当前 driver 的平均 cal drop：_____ (calibration drift)
    - 当前 driver 的实际成本/代（API 调用）：$ _____

  上线后目标（Phase 5 验证）：
    - Pareto 接受率不下降（±2%）
    - 最佳 on-Pareto 点 sharpe 提升 ≥ 0.1
    - worst_regime_sharpe 改善 ≥ 0.05
    - Maker self_score 与 actual_fitness_diff 平均偏差 < 0.2
    - Checker reliability diagram ECE < 0.05
    - Checker leakage rate < 0.1
    - 额外 API 成本/代 < $2.0

  持续监控（Phase 4 之后）：
    - 每周审查：Maker 创意率（每代 LLM 实际输出非平凡提案的比例）
    - 每月审查：calibration_set 是否需要更新
    - 每季度审查：是否需要更换 Maker/Checker 模型
```

### 2.11 与现有系统的集成点

| 现有组件 | 修改方式 | 影响范围 | 文件:行号 |
|---------|---------|---------|-----------|
| `app/loop/search.py` | `run_generation()` 中可选用 `MakerAgent.propose_batch()` 替代 `make_child_candidates()`；通过 `MAKER_ENABLED` 开关控制 | 局部替换，接口兼容 | `app/loop/search.py:run_generation` |
| `app/loop/driver.py` | 在 `results` 收集后插入 `CheckerAgent.verify()` + `Arbiter.resolve()` | 添加新阶段；保留原 driver 路径作为 fallback | `app/loop/driver.py:_collect_results` |
| `app/loop/worker.py` | 回测结果传递给 Checker 时调用 `isolation.strip_maker_artifacts()` | 新增数据过滤；不影响 Maker 端 | `app/loop/worker.py:_format_result` |
| `app/loop/checker.py` | M4 启发式 checker 行为不变；Arbiter 同时调用它作为并行硬约束 | 不修改；只增加调用方 | `app/loop/checker.py:check_candidate` |
| `app/loop/pareto.py` | `ParetoPoint` 新增 `checker_confidence` 字段；`dominates()` 支持 None 当 -∞ | 向后兼容（旧点 None） | `app/loop/pareto.py:ParetoPoint` |
| `app/loop/state.py` | `HISTORY` 记录新增 `prompt_version_maker` / `prompt_version_checker` / `maker_self_score` / `checker_calibrated_score` | 向后兼容（旧记录缺字段视为 None） | `app/loop/state.py:append_history` |
| `app/loop/mutation.py` | 保留为传统变异路径；Maker LLM 输出 diff 时调用 `mutate_field` 应用 | 不修改；只增加调用方 | `app/loop/mutation.py:mutate_field` |
| `app/loop/skills_version.py` | 已有；prompt_version 跟踪与之并列但独立 | 不修改 | `app/loop/skills_version.py` |
| `app/config/tuning.py` | 在 `TuningConstants` 标记哪些字段是 `frozen=True`（Checker 可读取，Maker diff 不能触碰） | 新增元数据 | `app/config/tuning.py:_ALIAS_MAP` |
| `app/services/signal_engine.py` | v4 信号生成管线；保持不动 | 不修改 | — |
| `app/domain/validation.py` | 四支柱有效性验证；保持不动 | 不修改 | — |
| `.scratch/backtest/run_backtest_v3.py` | 多目标回测框架；保持不动 | 不修改 | — |

### 2.12 优化前后对比

| 维度 | 当前系统 | 优化后 |
|------|---------|--------|
| **抗过拟合** | 无防护 — 参数可自由追逐噪音 | Maker-Checker 分歧检测 + 信息隔离 + 泄漏测量 |
| **参数探索质量** | 纯数学变异（高斯噪声） | LLM 有意图变异（mutation ops）+ 数学变异双路径 + run_mode A/B |
| **评估客观性** | 同一管线评估自己 | 独立 Checker 用不同模型/不同提供商 + 校准后的概率评分 |
| **人类可审计** | 只能看 metrics.json | Checker 产生自然语言审查报告 + HUMAN_REVIEW_LOG |
| **配置灵活性** | 单一 TUNING 实例 | Maker 和 Checker 可独立配置模型/温度/提示词/版本 |
| **跨品种校验** | 只做聚合 metrics | Checker 强制逐品种一致性检查 + 变异系数指标 |
| **发现隐藏问题** | 仅有量化指标 | Checker 可发现逻辑层面的问题（止损太近、信号密集等） |
| **与已有 checker 协同** | M4 启发式独立运行 | M4 启发式作为硬约束 + LLM 作为增强层，明确决策树 |
| **基线可对比** | 无基线 | Phase 0 测量 + 5 维 Pareto 可回溯 |
| **回滚能力** | 无 | feature flag + CLI 覆盖 + prompt_version 追踪 |
| **测试覆盖** | 单元测试为主 | 增加 isolation / calibration / arbiter / 端到端回归测试 |

### 2.13 分阶段实施路线

```
Phase 0 — 基线测量（半天）
  ├── 在当前 driver 上跑 5 代纯传统变异，记录：
  │   - Pareto 接受率
  │   - 最佳 sharpe / worst_regime_sharpe
  │   - 平均 cal drop
  │   - API 成本/代
  └── 写入 docs/maker-checker-baseline-2026Q3.md

Phase 1 — 基础设施（1-2 天）
  ├── 创建 app/loop/maker_checker/ 包结构
  ├── 创建 config.yaml + config_test.yaml（带 feature flag）
  ├── 创建 schemas.py（Pydantic Proposal/Verdict/MergeResult）
  └── 实现 MakerAgent 骨架（batch proposal + 传统变异路径）

Phase 2 — Checker 核心（2-3 天）
  ├── 实现 isolation.py（strict/moderate/minimal 三档）
  ├── 实现 CheckerAgent.verify() + LLM 调用
  ├── 实现 calibration.py（platt scaling）
  ├── hand-label 50+ calibration_set 案例
  └── test_isolation.py 通过（leakage < 0.1）

Phase 3 — 仲裁与人类审查（1-2 天）
  ├── 实现 Arbiter 决策树（含 M4 启发式并行分支）
  ├── 实现 5 维 Pareto back-compat
  ├── CLI review 命令（suspicious_to_human 列表）
  └── HUMAN_REVIEW_LOG.jsonl 写入

Phase 4 — 集成与回归（1-2 天）
  ├── search.py / driver.py 接入（带 feature flag）
  ├── 全量回归：712+ 测试零修改通过
  ├── fixtures 下放 golden prompts
  └── 端到端：跑 3 代对比 Phase 0 baseline

Phase 5 — 校准与上线门禁（1 天）
  ├── calibration 训练集 + 验证集拆分
  ├── reliability diagram 验证 ECE < 0.05
  ├── A/B 测试：llm_only vs trad_only vs mix 三种 run_mode
  ├── 对比 §2.10 成功度量：所有指标满足即上线
  └── 不满足则进入 Phase 6 调优循环

Phase 6 — 迭代优化（持续）
  ├── 在不同模型组合间实验（GPT-4/Claude/Gemini 交叉验证）
  ├── 优化 temperature 和 system_prompt
  ├── 调优 arbiter 权重和分歧阈值
  └── 季度更新 calibration_set
```

### 2.14 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM 调用延迟增加调优循环时间 | Checker 调用可异步执行（asyncio.gather），不阻塞回测流程 |
| LLM 输出不稳定（JSON 解析失败） | Pydantic schema 校验 + try/except + fallback 到传统变异路径 |
| LLM 输出破坏几何不变量 | Maker 输出 mutation ops 而非 raw values；由 mutation.py 应用 |
| Maker self_score 不准确 | calibration.py 用历史数据 Platt scaling；连续偏差触发调优 |
| Checker 过于保守抑制创新 | arbiter 权重可调；分歧触发人类审查而非直接拒绝 |
| 信息隔离难以完全实现 | isolation.py 提供 strict/moderate/minimal 三档；泄漏测试定量监控 |
| 额外 API 成本 | Maker 一次调用输出 λ 个 proposal（vs 每子代一次）；每代总成本 < $2 |
| 上线后效果比当前差 | feature flag + CLI 覆盖 + git revert 三重回滚保障 |
| Pareto 5 维升级破坏旧点 | back-compat 规则：旧点 checker_confidence=None 视为 -∞ |
| prompt 漂移导致不可复现 | prompt_version 强制 bump + HISTORY 记录 + seed 控制 |
| M4 启发式与 LLM 冲突 | 决策树明文化：M4=rejected 视为硬约束；suspicious 走人工 |

---

## 三、附录：当前代码库关键文件速查

| 文件 | 用途 | 优化中角色 |
|------|------|-----------|
| `app/loop/search.py` | 1+λ 进化策略搜索环 | 可选用 MakerAgent.propose_batch |
| `app/loop/driver.py` | 单代分发 + 状态持久化 | 插入 Checker 验证 + Arbiter 阶段 |
| `app/loop/worker.py` | 回测子进程包装 | 输出经 isolation.py 过滤 |
| `app/loop/checker.py` | M4 启发式 checker | **保留**，作为 Arbiter 并行硬约束 |
| `app/loop/pareto.py` | 帕累托前沿维护 | 升级为 5 维；back-compat |
| `app/loop/state.py` | 循环状态持久化 | HISTORY 新增 prompt_version / self_score / checker_score 字段 |
| `app/loop/mutation.py` | 分簇变异器 | 保留为传统变异路径；Maker diff 也用它应用 |
| `app/loop/skills_version.py` | skills 版本跟踪 | 与 prompt_version 并列但独立 |
| `app/loop/sensitivity.py` | 灵敏度扫描 | 不修改 |
| `app/loop/scheduler.py` | 自适应心跳 | 不修改 |
| `app/config/tuning.py` | TuningConstants + 热替换 | 新增 `frozen=True` 元数据 |
| `app/services/signal_engine.py` | v4 信号生成管线 | 保持不动 |
| `app/domain/validation.py` | 四支柱有效性验证 | 保持不动 |
| `.scratch/backtest/run_backtest_v3.py` | 多目标回测框架 | 保持不动 |

**新增文件**（v1.1 实施时创建）：

| 文件 | 用途 |
|------|------|
| `app/loop/maker_checker/__init__.py` | 包入口 |
| `app/loop/maker_checker/config.yaml` | Maker/Checker 固定配置（含 feature flag） |
| `app/loop/maker_checker/config_test.yaml` | 测试用配置 |
| `app/loop/maker_checker/schemas.py` | Pydantic schema: Proposal/Verdict/MergeResult |
| `app/loop/maker_checker/isolation.py` | 信息隔离层 |
| `app/loop/maker_checker/maker_agent.py` | Maker：LLM batch + 传统变异双路径 |
| `app/loop/maker_checker/checker_agent.py` | Checker：LLM 独立验证 |
| `app/loop/maker_checker/arbiter.py` | 裁决：分歧检测 + 5 维 Pareto back-compat |
| `app/loop/maker_checker/calibration.py` | Checker 评分校准 |
| `app/loop/maker_checker/runner.py` | Maker-Checker 循环入口（带 feature flag） |
| `app/loop/maker_checker/review.py` | CLI 人类审查入口 |
| `tests/test_maker_checker/test_maker.py` | Maker 输出 + seed + 不变量 |
| `tests/test_maker_checker/test_checker.py` | Checker 输出 + schema |
| `tests/test_maker_checker/test_isolation.py` | 隔离 + 泄漏测量 |
| `tests/test_maker_checker/test_arbiter.py` | 决策树 + 5 维 back-compat |
| `tests/test_maker_checker/test_calibration.py` | reliability diagram + ECE |
| `tests/test_maker_checker/fixtures/*.json` | golden prompts + calibration set |
| `docs/maker-checker-baseline-2026Q3.md` | Phase 0 基线测量报告 |

---

## 四、审计建议摘要（NEW）

本轮审计（v1.0 → v1.1）发现的关键问题及修复位置：

| # | 发现 | 严重度 | 修复位置 |
|---|------|--------|---------|
| 1 | Maker LLM 输出 raw values 会破坏几何不变量（fib_tp1<tp2<tp3） | 🔴 高 | §2.3 maker.system_prompt + §2.4 双路径设计 + test_maker_geometric_invariants |
| 2 | Maker self_score 来源未定义，Arbiter 加权公式失效 | 🔴 高 | §2.4 self_score 来源 + §2.6 加权公式 + §2.10 校准指标 |
| 3 | Checker 与 M4 启发式 checker 边界不清，易重复或冲突 | 🔴 高 | §1.3 表 + §2.5 共存规则 + §2.6 决策树 |
| 4 | 5 维 Pareto 升级未考虑 back-compat（4 维旧点处理） | 🟡 中 | §2.6 裁决层 + §2.11 集成点 + test_4d_to_5d_backcompat |
| 5 | 无基线测量，无法证明改进 | 🟡 中 | §2.10 成功度量 + Phase 0 + docs/maker-checker-baseline-*.md |
| 6 | 无回滚开关，上线后风险无法快速控制 | 🟡 中 | §2.3 feature_flags + §2.9 回滚与特性开关 |
| 7 | prompt 漂移无版本控制，无法复现 | 🟡 中 | §2.3 prompt_version + §2.9 prompt 追踪 |
| 8 | 信息隔离规则不具体，"approximate isolation" 无法验证 | 🟡 中 | §2.7 信息隔离层 + §2.5 泄漏测量 |
| 9 | 无校准机制，checker_score=0.7 含义不明 | 🟡 中 | §2.5 校准 + §2.8 calibration.py + test_calibration.py |
| 10 | 测试结构缺失，无法回归 AI 驱动的子系统 | 🟡 中 | §2.2 tests/ + §2.8 回归测试结构 |
| 11 | Maker 每子代一次 LLM 调用成本高 | 🟢 低 | §2.4 Batch 提案（一次调用输出 λ 个） |
| 12 | 单 config.yaml 不支持 A/B 测试 | 🟢 低 | §2.4 run_mode + config_test.yaml |
| 13 | Maker 预期影响无跟踪，难评估创意质量 | 🟢 低 | §2.4 预期影响跟踪 + §2.10 校准指标 |
| 14 | 人类审查接口（Web UI）过于模糊 | 🟢 低 | §2.6 CLI review 命令（v1 落地） |
| 15 | stagnation 检测在 5 维下未细化 | 🟢 低 | §2.6 stagnation 细化规则 |

**后续跟踪项**（v1.2 候选）：
- Web UI 人类审查界面（v2）
- 多 calibration_set 跨市场（BTC / ETH / SOL 分开校准）
- Maker/Checker 模型自动切换（按 generation 性能指标选择）
- Checker LLM 自一致性检验（同 candidate 跑两次，IAA > 0.8 才采用）

---

> **文档结束**。Phase 0 是最低成本的起点 — 先测基线，再决定是否值得投入 Phase 1-5。