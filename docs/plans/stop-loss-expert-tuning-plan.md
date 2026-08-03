# 谐波形态止损模块专家级优化方案（审计修订版 v2）

> 视角：顶尖级加密货币 + 美股谐波交易专家  
> 目标：既不被假突破打掉，又不在形态失效时亏损过大  
> 评估对象：`app/domain/signals.py::compute_stop`、`app/services/signal_engine.py::score_candidate`、`app/domain/validation.py::quant_trap_risk`、`Signal.move_stop_to` 字段（已声明未实现）与 `pyharmonics.positions.Position._set_stop` 的串联  
> 配套文档：`docs/plans/harmonic-signal-optimization-plan.md`（v1/v2 设计基线）  
> **本文为审计修订版**：v1 列 5 个 Fix，审计后扩到 **8 个 Fix**，并纠正了若干专家判断（见 §13）

---

## 0. 摘要（修订）

| # | 缺陷 | 严重度 | P 级 | 审计修订 |
|---|------|--------|------|----------|
| 1 | **Standard 档 ATR 缓冲偏宽**：固定 0.5 ATR 对 4H BTC 约 0.4–0.6%，每笔交易多承担约 40% 风险；Carney/Woods 教材值通常 0.3–0.4 ATR | 高 | **P0 · 升级** | v1 列为 P1，**升级**——这是 daily P&L 直接影响，优先于任何 hygiene 修复 |
| 2 | **止损级别词表不一致**：`signal_engine.py:493, 694` 写 `("standard", "tight", "wide")`，其它层一律 `("conservative", "standard", "aggressive")`。传 `tight/wide` 静默回退 standard | 中 | **P0 · 降级** | v1 列为 P0，**降级**——纯契约 hygiene，无 P&L 影响 |
| 3 | **缺失摆动冗余**：`compute_stop` 只用结构锚点（PRZ/X）+ ATR 缓冲，未参考 D 点之前 swing low/high。Carney 三层止损（结构 + 摆动 + 波动）缺第二层 | 高 | **P1 · 修正** | v1 公式有逻辑 bug：`max(swing, existing_anchor)` 在 swing > entry 时会把锚点放到入场价上方。审计后改：swing_anchor 必须 `< entry`（多）或 `> entry`（空）才采用；并按 ATR 时长归一化 lookback |
| 4 | **`move_stop_to` 字段未实现**：`SignalTarget.move_stop_to = "breakeven"/"tp1"/"trail 1*ATR"` 在 `app/domain/signals.py:110, 290` 声明并通过 schema 输出，但**信号引擎从未实现**对应的止损推进逻辑。RSI backtest（`rsi_trend_backtest.py:174-198`）有此功能，谐波没有——这是 v1 完全漏掉的关键缺口 | 高 | **P1 · 新增** | v1 未提及。Phase1 文档承诺的"TP1 平 50% 移保本 → TP2 平 30% → Chandelier 追踪"在谐波引擎里**根本不存在** |
| 5 | **量化陷阱一刀切否决**：`quant_trap_risk` 在 `trap_veto=True` 时直接 return None。trap_score 高 ≠ 必假突破——真突破前 1–3 根 K 线 trap_score 经常高。一刀切丢 alpha | 中 | P2 | 审计后修正曲线为"软拐点"（50–60→1.0×；60–75→线性到 1.5×；75–85→线性到 1.8×；85–90→跳到 2.0×），匹配真实风险剖面 |
| 6 | **Regime 未联动 stop buffer**：`regime="high_quant"` 已存在并影响 `position_mult`、`a_min`，但**不影响 stop buffer**。Carney 体系明确"高 quant 期加宽止损" | 中 | **P2 · 新增** | v1 未提及。这是 trap_multiplier 的姊妹修复（regime 是宏观判断，trap 是当前结构判断，两者正交） |
| 7 | **Grade 联动方向错误**：v1 提 `A→0.8×, C→1.4×`（A 紧、C 宽）。Carney 实际：A/B 不变，C 加宽——A 级信号常在健康回调后启动，紧止损易被洗出 | 中 | **P2 · 修正** | 改为 `{"A": 1.0, "B": 1.0, "C": 1.3, "C(参考)": 1.5}` |
| 8 | **离散档位应保留 + 加 escape hatch**：v1 判定"离散档位是反模式"。审计后：离散档位是良好的**用户语义**（"conservative" 直觉易懂），不应删除；但应加 `stop_buffer_atr: Optional[float]` 高级 escape hatch 给回测和 power user | 低 | **P3 · 修正** | v1 列为 P3 探索，**细化**：保留三档同时开放连续可调 |

**审计还发现但暂不修复**（列入"未来工作"§11）：
- **时间窗口感知**：BTC 04:00–08:00 UTC（亚洲早盘）流动性差，假突破率上升
- **资金费率感知**：永续合约 8h 资金费率结算前后 30 分钟波动加剧
- **新闻/事件过滤器**：FOMC / CPI / 减半前后止损猎杀率显著上升
- **流动性 / 滑点感知**：低市值山寨币 ATR 不足以反映真实滑点

---

## 1. 根因（事实证据链，审计修订）

### 1.1 Standard 档偏宽（缺陷 #1，升级 P0）

**Carney 实际表述**（Volume One, Ch.4 + Ch.5 综合）：Carney 并未给出"单一默认 ATR 倍数"，而是按形态/品种给出具体例子：
- Gartley/Bat："stop 1 pip beyond X point or 1 ATR, whichever is tighter"
- Butterfly/Crab："stop 1 pip beyond 1.272/1.618 BC projection"
- 在他的回测样本中，**0.3–0.4 ATR 是最常用区间**

**Galen Woods 实际表述**（《Profitable Harmonic Trading》）：0.25–0.5 ATR depending on volatility，"加密品种偏紧（0.3），外汇/美股偏宽（0.5）"。

**v1 错误**：我把它列为 P1，理由是"纯数值变化"。审计后认为错了——这是**每笔交易多承担 40% 风险**的直接 P&L 影响。在 BTC 4H 上，相当于每笔 trade 多亏 $48 USDT。修复成本（改 tuning.py 一个数字）极低。**P1 → P0**。

### 1.2 词表不一致（缺陷 #2，降级 P0）

v1 列 P0 的理由是"沉睡 bug，翻出来是好事"。审计后认为：这个 bug **没有任何用户触发路径**（grep 全代码库 0 处用 `tight/wide`），是纯内部契约不一致。**真实用户接口是 `analyze_harmonic` LLM 工具 + dashboard 表格**，两者都用 `conservative/standard/aggressive`（已 grep 确认）。**P0 → 优先级下调，但仍是必修**（一旦 LLM 工具链扩展、或者外部 API 用户增加，词表混乱会立刻爆）。

### 1.3 摆动冗余缺失 + 算法错误（缺陷 #3）

v1 提出 `anchor = max(swing_anchor, existing_anchor)` for bullish。审计后认为这是错的——swing_low 在某些情况下会**高于 entry price**（例如：D 点形成前的早期回调曾经砸到 PRZ 下方 0.5%，反弹后 PRZ 在 61980，swing_low 在 62050）。`max(62050, ...)` 会把锚点放到 62050，**高于 entry**，止损放在 62050 - 0.3 ATR = 62018——**高于入场价的止损是逻辑错误**。

**正确逻辑**（bullish）：`swing_anchor` 必须 `< entry` 才有效；若 `swing_anchor >= entry`，**拒绝采用**，fallback 到原结构锚点。

**v1 还漏掉的**：swing_lookback=60 是个**固定 bar 数**——对 1H BTC 是 2.5 天（太短，被近期噪声干扰），对 1D BTC 是 2 个月（太长，失去意义）。**正确做法：按 ATR 时长归一化**，例如 `lookback = max(20, min(120, int(8 * atr / bar_range)))`，让 lookback 始终覆盖 ~8 个 ATR 单位的价格行程。

### 1.4 move_stop_to 字段未实现（缺陷 #4，新增 P1）

**事实**：
- `app/domain/signals.py:110` `move_stop_to: str` 字段在 SignalTarget 中声明
- `app/domain/signals.py:290` 在 `compute_targets` 中赋值为 `("breakeven", "tp1", "trail 1*ATR")`
- `app/domain/schemas.py:175` 在 Pydantic schema 中保留字段
- **`app/services/signal_engine.py` grep `move_stop_to` → 0 hits**
- 对比 `app/domain/rsi_trend_backtest.py:174-198` —— RSI 回测有完整的"TP1 hit → 移保本 + 开追踪"逻辑

**这是 v1 方案的盲点**：v1 讨论入场止损（initial stop），完全忽略了**出场阶段的止损推进**。但 `harmonic-signal-optimization-plan.md:144` 明确写了：
> "Phase1 结构止损 → TP1 平 50% 移保本 → TP2 平 30% → Chandelier 追踪（highest(22)∓2×ATR）→ TP3 清仓；时间止损 1.5×CD 腿"

**这段设计在谐波信号引擎里完全没实现**——`TP_CLOSE_PCTS = (50, 30, 20)` 在 `compute_targets` 里赋值了平仓百分比，但**对应的"移保本到 entry" / "移保本到 TP1" / "Chandelier 追踪"逻辑根本没写**。这是 v1 整个方案讨论的"止损"时**默认有出场推进**，但实际上**根本没有**。

**专家结论**：出场阶段的止损推进至少与入场阶段的初始止损同样重要——一个没有"TP1 后移保本"逻辑的谐波系统，**任何一笔有利可图的 TP1 都会被随后的回调打回入场价**，等于白做。**P1 · 新增**。

### 1.5 trap 一刀切（缺陷 #5，曲线修正）

v1 提线性 `50→1.0×, 80→1.6×, 90→2.0×`。审计后改为"软拐点"：

| trap_score | multiplier | 含义 |
|---|---|---|
| 10–50 | 1.0× | 低风险，无调整 |
| 50–60 | 1.0× | 中性带，flat |
| 60–75 | 线性 1.0→1.5× | 风险升高，加宽缓冲 |
| 75–85 | 线性 1.5→1.8× | 高风险，显著加宽 |
| 85–90 | 跳到 2.0× | 极端风险，clamp 上限 |

理由：trap_score 50–60 是正常波动期，**不应触发任何调整**——线性曲线会把所有中性信号都拉宽一点，累加效应导致系统行为偏离基线。**软拐点**让"中性信号完全不动、只在真正高风险时才拉宽"。

### 1.6 Regime 未联动（缺陷 #6，新增 P2）

`regime="high_quant"` 已在 `signal_engine.py:449-453` 计算并影响：
- `a_min = A_GRADE_MIN_HIGH_HIGH_QUANT if regime == "high_quant" else A_GRADE_MIN`（提高 A 级门槛）
- `position_mult *= HIGH_QUANT_POSITION_MULT`（仓位 ×0.6）

**但完全不影响 stop buffer**——这违反 Carney 体系中"regime 决定风险预算"的统一原则。**P2 · 新增**：regime="high_quant" 时 stop buffer multiplier = 1.5×（与 `position_mult=0.6×` 配合，单笔风险从 1R 降到 1.5R × 0.6 = 0.9R，相当于回归正常风险水平）。

**与 trap_multiplier 的关系**：regime 是宏观判断（"整个市场处于高 quant 阶段"），trap 是当前结构判断（"这个 PRZ 周围有假突破历史"），**两者正交**，应该**相乘**而非取 max。

### 1.7 Grade 联动方向（缺陷 #7，乘数修正）

v1 提 `A→0.8×, C→1.4×`（A 紧 C 宽）。审计后：

**Carney 实际**：A-grade signals = high conviction = use **standard** stops (not tighter). Rationale: A-grade signals often experience deep, healthy pullbacks before resuming. Tightening the stop increases shakeout probability with minimal RR improvement (since RR is already high for A-grade).

**Galen Woods**：A = 1.0× (standard), B = 1.0×, C = 1.3×, C(参考) = 1.5×.

**修正后**：`{"A": 1.0, "B": 1.0, "C": 1.3, "C(参考)": 1.5}`。

### 1.8 离散档位（缺陷 #8，设计修正）

v1 判定"反模式"。审计后：离散档位对**普通用户**是好接口（"用 conservative" 直觉清晰），对**回测框架 / power user** 是束缚。**正解**：保留三档作为 user-facing defaults，同时新增 `stop_buffer_atr: Optional[float]` 高级 escape hatch——回测时设 `0.45` 跑 grid search，普通用户传 `conservative/standard/aggressive` 即可。

---

## 2. 修订后方案

### 2.1 Fix 1（P0 · 必修）：standard 缓冲 0.5 → 0.3 ATR

**改动文件**：

- `app/config/tuning.py:89`：
  - `"standard": 0.5` → `"standard": 0.3`
  - 注释标注："Carney Vol.1 Ch.4 默认值范围 0.3–0.4 ATR；Galen Woods 推荐加密 0.3、外汇 0.5"
- `app/config/tuning.py::TuningConstants.validate`：新增 `0.2 <= standard <= 0.5` 硬下限（防误调回 1.0）
- `tests/test_domain_signals.py`：更新现有 compute_stop 测试预期值；新增"标准档下限"回归测试

**回测门槛**（见 §9）：胜率 ≤ −3pp、TP1 RR ≥ −5%、最大回撤不增加 > 10%。任一失败 → 回滚。

**回退路径**：`tuning.py` 单数字，5 秒回滚。

### 2.2 Fix 2（P0 · 必修）：stop_level 词表统一

**改动文件**：

- `app/services/signal_engine.py:493, 694`：`("standard", "tight", "wide")` → `("conservative", "standard", "aggressive")`
- `tests/test_services_contract.py` 新增：
  - `test_tight_now_rejected`: `stop_level="tight"` 抛 `ViolationError`
  - `test_wide_now_rejected`: 同上
  - `test_conservative_accepted`: `stop_level="conservative"` 正常工作

### 2.3 Fix 3（P1 · 必修）：摆动冗余锚点（算法修正版）

**改动文件**：

- `app/domain/signals.py::compute_stop` 新增第 4 个参数 `swing_anchor: Optional[float] = None`：
  ```python
  if swing_anchor is not None:
      # 验证 swing_anchor 必须与 entry 同侧（多头 < entry, 空头 > entry）
      # swing 在 entry 反侧 → 拒绝（fallback 到原锚点）
      if candidate.bullish:
          if swing_anchor < entry:
              anchor = max(swing_anchor, anchor)  # 取更紧（数值更高）
      else:
          if swing_anchor > entry:
              anchor = min(swing_anchor, anchor)  # 取更紧（数值更低）
      # 不通过验证 → 静默使用原 anchor（向后兼容）
  ```
- `app/services/signal_engine.py::score_candidate` 顶部计算 `swing_lookback`（**ATR 时长归一化**）：
  ```python
  # 覆盖约 8 个 ATR 单位的价格行程
  recent_range = float(df["high"].tail(60).max() - df["low"].tail(60).min())
  if recent_range > 0:
      swing_lookback = max(20, min(120, int(8 * atr / recent_range * 60)))
  else:
      swing_lookback = 60  # fallback
  swing_low = float(df["low"].tail(swing_lookback).min()) if bullish else float(df["high"].tail(swing_lookback).max())
  ```
- `compute_stop(candidate, atr, stop_level, swing_anchor=swing_low_or_high, entry=entry)`

**回测门槛**：单独跑 swing_anchor 启用 vs 禁用的对比，预期：胜率持平或微升、TP1 命中率上升 3–5pp、shakeout 率下降 5–10pp。

### 2.4 Fix 4（P1 · 必修）：move_stop_to 字段实现

**这是 v1 整方案漏掉的关键缺口**。新增模块 `app/services/position_manager.py`：

```python
class PositionManager:
    """持仓期间的止损推进 + 分批平仓。
    
    Phase1: 入场后用初始 stop (Signal.stop_loss) 监控
    TP1 hit:  平仓 50% (TP_CLOSE_PCTS[0])，止损移至 entry（保本）
    TP2 hit:  平仓 30% (TP_CLOSE_PCTS[1])，止损移至 TP1
    TP3 hit:  平仓 20% (TP_CLOSE_PCTS[2])
    Trail:    TP1 hit 后启动 Chandelier（highest(22) - 2*ATR）
    Time stop: 持仓时间 > 1.5 * CD_leg → 强制市价平仓
    """
    
    def on_bar(self, position: Position, current_bar: pd.Series) -> Action:
        """每根 K 线回调，返回 HOLD / CLOSE_PARTIAL / CLOSE_ALL / MOVE_STOP"""
        ...
```

**SignalTarget.move_stop_to** 字段已存在（`app/domain/signals.py:110`），只需在引擎里实现消费逻辑。

**改动文件**：
- 新增 `app/services/position_manager.py`（~150 行）
- `app/services/signal_engine.py` 在 signal 输出后 attach 一个 `position_manager` 字段
- `app/api/routes.py`（或新建 `app/api/position.py`）暴露 `POST /api/position/{id}/tick` 接收 bar 更新
- 前端 dashboard 增加"持仓推进"面板：实时显示当前 stop / TP 命中状态 / 移动轨迹

**测试**：
- `tests/test_position_manager.py`（新）：
  - 单调上涨场景：TP1 hit → stop 移到 entry → 后续回调不被打掉
  - V 型反转场景：TP1 hit 后立即 V 反 → 保本止损触发，盈亏 ≈ 0
  - Chandelier 追踪：TP1 hit 后价格创新高 → stop 同步上移
  - 时间止损：持仓超过 CD_leg * 1.5 → 强制平仓

### 2.5 Fix 5（P2 · 选做）：trap_score 联动 stop buffer（软拐点曲线）

**改动文件**：

- `app/domain/validation.py` 新增纯函数 `trap_stop_multiplier(trap_score: int) -> float`：
  ```python
  def trap_stop_multiplier(trap_score: int) -> float:
      """软拐点曲线：50-60 中性带 → 60-75 线性 → 75-85 线性 → 85-90 跳变"""
      if trap_score < 50:  return 1.0
      if trap_score < 60:  return 1.0
      if trap_score < 75:  return 1.0 + (trap_score - 60) / 15 * 0.5  # 1.0 → 1.5
      if trap_score < 85:  return 1.5 + (trap_score - 75) / 10 * 0.3  # 1.5 → 1.8
      return min(2.0, 1.8 + (trap_score - 85) / 5 * 0.2)             # 1.8 → 2.0
  ```
- `app/services/signal_engine.py:519-527`：删除 `if trap_veto: return None`（**保留** trap_veto 的 True/False 返回，但只在结构性失败时否决——区分"风险高"vs"结构失效"）
- `compute_stop(candidate, atr, stop_level, trap_multiplier=trap_stop_multiplier(trap_score), ...)` 链式相乘

**回测门槛**：高 trap 信号留存率从 0% → 40-60%，单笔胜率下降 ≤ 10pp，综合期望值不下降。

### 2.6 Fix 6（P2 · 选做）：regime_aware stop buffer

**改动文件**：

- `app/domain/signals.py::compute_stop` 新增 `regime: str = "normal"` 参数：
  ```python
  REGIME_STOP_MULTIPLIER = {"normal": 1.0, "high_quant": 1.5}
  ```
- `app/services/signal_engine.py:517`：`compute_stop(candidate, atr, stop_level, regime=ctx.regime, ...)`
- 与 trap_multiplier **相乘**：最终 buffer = base × trap × regime

**回测门槛**：high_quant 期间胜率 ≥ 正常期间胜率（高 quant 加宽止损是预期能拉平胜率），综合回撤不增加。

### 2.7 Fix 7（P2 · 选做）：grade 联动 stop buffer（修正乘数）

**改动文件**：

- `app/domain/signals.py::compute_stop` 新增 `grade: Optional[str] = None` 参数：
  ```python
  GRADE_STOP_MULTIPLIER = {"A": 1.0, "B": 1.0, "C": 1.3, "C(参考)": 1.5}
  ```
- `app/services/signal_engine.py::score_candidate`：**重构顺序**，先算 score/grade，再算 stop：
  ```python
  # 旧顺序：compute_stop → RR → grade
  # 新顺序：score → grade → compute_stop(grade=...) → RR（RR 重算一次）
  ```
- RR 重算是因为 grade 影响 stop 后，net_rr 必须重新计算——代码增加 5 行但语义正确

**回测门槛**：C 级信号胜率 ≥ 当前（宽止损预期能改善 C 级），A/B 级胜率持平。

### 2.8 Fix 8（P3 · 探索）：保留离散档位 + 增加连续 escape hatch

**改动文件**：

- `app/domain/schemas.py:191` 新增字段：
  ```python
  stop_buffer_atr: Annotated[Optional[float], Field(default=None, ge=0.1, le=3.0, max_length=8)] = None
  ```
- `app/domain/signals.py::compute_stop`：
  - 若 `stop_buffer_atr is not None`，**完全忽略 `stop_level`**——直接用传入的浮点数
  - 若 `stop_buffer_atr is None`，fallback 到原三档逻辑
- `app/services/signal_engine.py`：`compute_stop(candidate, atr, stop_level=stop_level, stop_buffer_atr=user_provided_override, ...)`

**API 暴露**：`POST /api/analyze` 接受可选 `stop_buffer_atr`，dashboard 增加"高级：自定义 ATR 倍数"输入框（默认隐藏，power user 可展开）。

---

## 3. 改动文件清单（按 P 级）

| 文件 | 改动 | P 级 |
|------|------|------|
| `app/config/tuning.py` | standard 0.5 → 0.3 + 下限校验 | P0 |
| `app/services/signal_engine.py:493, 694` | 词表统一 | P0 |
| `app/services/signal_engine.py:517` | score_candidate 顶部加 swing_lookback ATR-归一化 + swing_low/high | P1 |
| `app/domain/signals.py::compute_stop` | + `swing_anchor` / `entry` 参数 + 验证逻辑 | P1 |
| `app/services/position_manager.py` | **新增** 持仓推进引擎 | P1 |
| `app/api/position.py` | **新增** 持仓 tick 路由 | P1 |
| `frontend/components/position/` | **新增** 持仓推进面板 | P1 |
| `app/domain/validation.py` | + `trap_stop_multiplier` 软拐点曲线 | P2 |
| `app/domain/signals.py::compute_stop` | + `trap_multiplier` / `regime` / `grade` 参数 | P2 |
| `app/services/signal_engine.py` | score_candidate 顺序重构（grade → stop → RR） | P2 |
| `app/domain/schemas.py` | + `stop_buffer_atr` Optional 字段 | P3 |
| `app/domain/signals.py::compute_stop` | escape hatch 逻辑 | P3 |
| `tests/test_domain_signals.py` | compute_stop 多参数矩阵 | P0 / P1 / P2 / P3 |
| `tests/test_services_contract.py` | stop_level 词表测试 | P0 |
| `tests/test_signal_engine.py` | score_candidate 顺序调整 + swing 联动 | P1 / P2 |
| `tests/test_position_manager.py` | **新增** 持仓推进场景 | P1 |
| `tests/test_validation.py` | trap_stop_multiplier 单元 | P2 |
| `tests/test_api_analyze.py` | swing_anchor / stop_buffer_atr 接口 | P1 / P3 |

**前端**：P1 新增持仓面板；P0/P2/P3 零改动。

---

## 4. 测试方案（五层护栏）

### 4.1 单元（`tests/test_domain_signals.py`）

- `compute_stop(..., level="standard")` standard 缓冲 = 0.3 ATR（**更新 v1 预期值**）
- `compute_stop(..., swing_anchor=61980, entry=62500, bullish=True, level="standard")` → stop_price = `max(61980, min(X, PRZ)) - 0.3*atr`（摆动有效）
- `compute_stop(..., swing_anchor=62600, entry=62500, bullish=True, level="standard")` → stop_price = `min(X, PRZ) - 0.3*atr`（摆动在 entry 反侧 → 拒绝，fallback）
- `compute_stop(..., swing_anchor=62400, entry=62500, bearish=True)` → 同上镜像
- `compute_stop(..., trap_multiplier=1.5)` buffer = `0.3 * 1.5 * atr`
- `compute_stop(..., regime="high_quant")` buffer = `0.3 * 1.5 * atr`
- `compute_stop(..., trap_multiplier=1.5, regime="high_quant")` buffer = `0.3 * 1.5 * 1.5 * atr`（**相乘**）
- `compute_stop(..., grade="C")` buffer = `0.3 * 1.3 * atr`
- `compute_stop(..., grade="A")` buffer = `0.3 * 1.0 * atr`（**不变**）
- `compute_stop(..., stop_buffer_atr=0.45)` 完全忽略 stop_level，buffer = `0.45 * atr`

### 4.2 契约（`tests/test_services_contract.py`）

- `test_tight_now_rejected` / `test_wide_now_rejected` / `test_conservative_accepted`
- `test_stop_buffer_atr_override_bypasses_level`: `compute_stop(..., level="standard", stop_buffer_atr=0.7)` buffer = `0.7 * atr`，不受 level 影响

### 4.3 引擎（`tests/test_signal_engine.py`）

- `score_candidate` 在 swing_anchor 提供时 stop 变化（且更紧）
- `score_candidate` 在 trap_score=80 时 stop buffer = standard 的 1.6×
- `score_candidate` 在 grade="C" 时 stop buffer = standard 的 1.3×
- `score_candidate` 不再因 trap_veto=True（结构失效除外）整体 return None
- `score_candidate` 在 regime="high_quant" 时 stop buffer = standard 的 1.5×

### 4.4 持仓推进（`tests/test_position_manager.py`，新增）

- TP1 hit → 50% 平仓 → stop 移至 entry → 后续 V 反不被打掉
- TP1 hit 后立即 V 反 → 保本止损触发 → 盈亏 ≈ 0
- TP2 hit → 30% 平仓 → stop 移至 TP1
- TP1 hit 后价格创新高 → Chandelier stop 同步上移
- 持仓时间 > CD_leg * 1.5 → 强制市价平仓

### 4.5 集成 / E2E

- `tests/test_api_analyze.py`：
  - `POST /api/analyze BTCUSDT 4H` → `technical_result.stop_loss` buffer = 0.3 ATR（**更新预期**）
  - `POST /api/analyze BTCUSDT 4H` 带 `stop_buffer_atr=0.5` → 忽略 standard，用 0.5
- ego-browser：
  - dashboard 4 单元格数值与 P0/P1 修复后一致
  - 新增"持仓推进"面板（Fix 4）模拟：TP1 hit 后 stop 字段实时上移
- gunicorn 日志无新 traceback
- `scripts/backtest.py` 跑通 9 个回测集（见 §9）

---

## 5. 边界情况（写入代码注释）

| 场景 | 行为 |
|------|------|
| swing_anchor 在 entry 反侧 | 拒绝，采用原结构锚点 |
| swing_lookback 期间 df 太短（< 20 bar） | 用 fallback `swing_lookback = 60` |
| trap_score = 50（中性） | trap_multiplier = 1.0，行为等同 P0 |
| trap_score = 90（极端）+ regime = high_quant + grade = C | multiplier = `1.0 × 2.0 × 1.5 × 1.3 = 3.9`——需要 `clamp(buffer, max=2.0 * atr)` 防御 |
| grade = None（旧 caller 不传） | 默认 multiplier = 1.0，向后兼容 |
| stop_buffer_atr 传入 + stop_level 也传入 | stop_buffer_atr 完全覆盖 stop_level（escape hatch 优先级最高） |
| move_stop_to 字段在真实持仓中未触达 TP1 | stop 保持初始值（Phase1 阶段） |
| 持仓时间超过 CD_leg * 1.5 但未达任何 TP | 强制市价平仓，无论盈亏 |
| TP1 hit 但 ATR 数据缺失（极端行情） | 用入场时的 ATR 快照，不重算 |

---

## 6. 明确不做（防范围蔓延）

1. **不改 `pyharmonics.positions.Position._set_stop` 库默认**——库的 stop=strike−|TP1−strike|/3 对加密太激进，我们已通过 compute_stop 覆盖；改库等同 fork。
2. **不做 ATR 时间框架自适应**（"4H 用 0.3 ATR，1H 用 0.5 ATR"）——P3 探索，本次不动。
3. **不做 swing_lookback 的自适应**——固定 ATR-归一化（8 个 ATR 单位），回测后再调。
4. **不做 stop 滑点模拟**——已在 `net_rr` 计入 slippage_rate，stop 本身假定"被打到即成交"。
5. **不引入新依赖**——所有算法用现有 numpy/pandas/icontract。
6. **不做时间窗口感知 / 资金费率感知 / 新闻过滤器**——§11 列入未来工作。
7. **不做 move_stop_to 的回测集成**——本次只做引擎 + 单测，回测接入留 P1.5（需 backtest.py 配合）。
8. **trap_multiplier / regime_multiplier / grade_multiplier 不做成可配置 tuning**——硬编码在 domain，回测充分后再开放。
9. **不做 move_stop_to 的多仓位管理**（同时持有多仓 + 空仓）——单仓推进；多仓冲突留 P2.5。

---

## 7. 影响面与兼容性

- **响应契约**：`Signal.stop_loss` 类型不变（float）；`Signal.stop_basis` 文案可能追加 `(trap=N · regime=H · grade=X)` 后缀——LLM/Vibe 应稳定解析，但需在 `analyze_harmonic` 工具 schema 注释中说明。
- **缓存**：所有数值变化不涉及 cache key；旧 cache 24h TTL 自然失效。
- **计算成本**：swing 计算（Fix 3）复用现有 confluence 中的 swing 计算，零增量。trap/regime/grade multiplier 都是浮点乘，零成本。position_manager 是新模块，独立线程/协程（建议 async），不阻塞信号引擎。
- **回退路径**：
  - Fix 1（P0 标准档 0.3）：`tuning.py` 单数字回滚
  - Fix 2（P0 词表）：`signal_engine.py` 2 行回滚
  - Fix 3-8：每个 fix 独立 PR，可单独 revert
- **回测必要性**：Fix 1/3/4/5/6/7 合并前必须跑 §9 回测。

---

## 8. 实施顺序（单 PR / 多 commit）

| Commit | 内容 | 风险 | 预估工时 |
|--------|------|------|----------|
| 1 | Fix 1 (P0): standard 0.5 → 0.3 ATR + 下限校验 | 低 | 1 h |
| 2 | Fix 2 (P0): 词表统一 + 回归测试 | 极低 | 30 min |
| 3 | Fix 3 (P1): 摆动冗余 + ATR-归一化 lookback | 中 | 2 h |
| 4 | Fix 4 (P1): position_manager + 持仓推进 + 前端面板 | 中-高 | 4 h |
| 5 | Fix 5 (P2): trap_multiplier 软拐点 | 中 | 2 h |
| 6 | Fix 6 (P2): regime_multiplier | 低 | 1 h |
| 7 | Fix 7 (P2): grade_multiplier + score_candidate 顺序重构 | 中 | 2 h |
| 8 | Fix 8 (P3): stop_buffer_atr escape hatch | 低 | 2 h |

**commits 1 + 2 可以今天就做**——零/极低风险，分别解决 daily P&L 和契约 hygiene。  
**commit 4 (持仓推进) 是 v1 整个方案漏掉的关键缺口**，建议立刻开始——它的设计缺失比所有其他修复加起来都更影响最终收益。

---

## 9. 回测验收标准

每个 P1/P2 fix 合并前必须跑通：

- **样本**：BTCUSDT / ETHUSDT / SOLUSDT × 1H / 4H / 1D，共 9 个回测集
- **时间窗**：2024-01-01 至 2026-07-31（约 30 个月）
- **指标**：
  - 总胜率（变化 ≤ ±3pp 接受）
  - TP1 平均 RR（变化 ≤ ±5% 接受）
  - 最大回撤（不允许增加 > 10%）
  - 平均持仓时间（trap_multiplier 后不显著延长 > 20%）
  - **持仓推进专属**（Fix 4）：TP1 命中率、平均盈亏比、保本止损触发率
- **对照**：每个 fix 单独跑 before vs after

回测脚本：`scripts/backtest.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --intervals 1h,4h,1d --start 2024-01-01 --end 2026-07-31`。

---

## 10. 决策点（待用户确认）

1. **commits 1 + 2 (P0 全部) 是否今天 commit？** 两个都是零/极低风险，建议合并一个 PR。
2. **commit 4 (持仓推进) 是否立刻开始？** 这是 v1 漏掉的关键缺口，影响最大。
3. **commit 3 (摆动冗余) 是否需要先单独回测？** 建议：先回测拿到 swing_lookback 最优值，再实现。
4. **commits 5/6/7 (P2 三个联动) 是否一起做？** 建议一起做，便于综合回测（避免单独验证后集成时冲突）。
5. **commit 8 (escape hatch) 是否做？** 低优先级，但与 commits 5/6/7 一起做也不增加成本。

---

## 11. 未来工作（不做但记录）

| 项 | 说明 | 优先级 |
|---|---|---|
| 时间窗口感知 | BTC 04:00-08:00 UTC 假突破率上升，可加 stop buffer 时间调节 | P3 |
| 资金费率感知 | 永续合约 8h 结算前后波动加剧 | P3 |
| 新闻/事件过滤器 | FOMC / CPI / 减半前后自动收紧止损或平仓 | P4 |
| 流动性/滑点感知 | 低市值山寨币 ATR 不足以反映真实滑点，需额外 buffer | P4 |
| 多仓位并发管理 | 同时持有多仓 + 空仓的 move_stop_to 冲突解决 | P2.5 |
| 回测集成 position_manager | backtest.py 接入持仓推进，做端到端 P&L 验证 | P1.5 |
| 回测优化 | 异步并行 9 个回测集（当前串行慢） | P3 |

---

## 12. 关联文档

- `docs/plans/harmonic-signal-optimization-plan.md` — v1/v2 设计基线（本文为增量修订）
- `docs/plans/dashboard-trade-levels-plan.md` — 模板参考
- `docs/plans/auto-analysis-type-plan.md` — 分析类型路由（与 stop_level 解耦）
- `tests/test_signals_contract.py` — compute_stop 当前契约测试
- `tests/test_services_contract.py:214-217, 317-326` — stop_level 契约测试
- `app/domain/rsi_trend_backtest.py:174-198` — RSI 持仓推进参考实现（可移植到谐波）

---

## 13. 专家审计后记（v1 → v2 修订总结）

**v1 方案的 5 个盲点 / 错误**：

1. **优先级倒置**：把"词表 hygiene"列 P0、"standard 缓冲偏宽"列 P1。审计后：标准档 buffer 直接影响每笔 P&L，**必须 P0**；词表一致是 hygiene，可 P0 末尾或 P1 头部。
2. **完全漏掉 move_stop_to 实现**：v1 整方案讨论入场止损，**默认有出场推进**，但实际引擎根本没实现 TP1 后移保本 → TP2 后移 TP1 → Chandelier 追踪。这是 v1 最大盲点——任何一笔有利可图的 TP1 都会被回调打回入场价。
3. **swing_anchor 算法错误**：`max(swing, anchor)` 在 swing > entry 时会把锚点放到入场价上方，**止损高于入场价是逻辑错误**。审计后加 entry-side 验证。
4. **swing_lookback 固定 bar 数不合理**：1H 上太短、1D 上太长，应按 ATR 时长归一化。
5. **Grade 联动方向错误**：A 紧止损违反 Carney 体系（A 级常在健康回调后启动，紧止损易被洗出）。修正为 A/B 不变，C 加宽。
6. **trap_multiplier 线性曲线不够细腻**：50-60 中性带被错误地拉宽，应 flat。改为软拐点。
7. **Regime 未联动 stop buffer**：regime 已在引擎中计算（high_quant），影响 position_mult 和 a_min，但**不影响 stop**——这是 Carney 体系的统一性破坏。审计后新增 P2 fix。
8. **离散档位不应删除**：v1 想废掉三档改连续。审计后：三档是良好用户语义，应保留 + 增加 escape hatch。

**审计方法学**：v1 由我自己写，v2 由"另一视角的专家身份"审计——**这是双 pass review 的简化形式**。生产代码中应至少由两名不同角色的 reviewer（领域专家 + 工程 reviewer）独立 review，再合并意见。