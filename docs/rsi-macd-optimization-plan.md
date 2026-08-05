# RSI + MACD 优化方案 — 提高谐波形态胜率

**目标**：通过细化 RSI/MACD 的使用方式，将4H周期谐波形态交易的胜率从当前水平显著提升。

**核心问题**：现有实现将 RSI 和 MACD 作为简单的"有无背离"二元开关，忽略了背离类型、价格结构强度、指标位置等关键维度。

---

## 一、现状问题分析

### 问题1：背离类型未区分（CRITICAL）

**文件**：`app/services/signal_engine.py` 第 392-393 行、第 372-378 行

```python
# 当前代码
factors["macd"] = 10 if any(bool(d.get("bullish")) == candidate.bullish for d in macd_divs) else 0
```

`DivergenceSearch` 返回三种背离：

| 类型 | 含义 | 对谐波反转交易的价值 |
|------|------|---------------------|
| **Regular** | 价格创新低/高，指标未跟随 → **真正反转信号** | ✅ 有效 |
| **Hidden** | 价格延续，指标回撤 → **持续信号** | ❌ 误导 |
| **Exaggerated** | 极端价格行为 | ⚠️ 弱信号 |

当前代码对两种背离一视同仁，Hidden 背离给了 +10 分实际上在帮倒忙。

### 问题2：MACD 零线过滤缺失（CRITICAL）

MACD 线位置本身是极重要的过滤器：

- 看多形态 + MACD 在零轴下方 → 超卖区 MACD 转多 → **强**
- 看多形态 + MACD 在零轴上方 → MACD 已经走强 → **弱**（行情可能已走完）

现有代码完全没有用到 MACD 线的绝对位置。

### 问题3：MACD 柱状图强度未使用

pyharmonics 返回的 MACD 实际上是 MACD 直方图（macd_diff），其绝对值大小反映动量强度。现有代码只检查"有无背离"，不检查背离力度。

### 问题4：RSI 极值区逻辑不够精细

现有逻辑：
```
RSI ≤ 35 (看多) → +7
RSI ≤ 45 (看多) → +4
```

问题：
- RSI 在 40-45 的"反弹区"范围很大，没有区分是持续下行后的反弹还是刚进入该区域
- RSI 正在**上升**（改善中） vs RSI **下降**（恶化中）—— 完全没区分
- RSI 中线（50）附近的交叉确认没有使用

### 问题5：没有双指标共振验证

当 RSI + MACD 同时出现 Regular 背离时，信号强度远超单一指标，但现有权重体系只是简单相加（RSI 15 + MACD 10），没有"双确认加成"。

### 问题6：背离质量未评估

一次跨越 60 根 K 线的背离 vs 跨越 10 根 K 线的背离，质量差异巨大。现有代码不区分。

### 问题7：MACD 线与 Signal 线交叉未使用

MACD 线从下方穿越 Signal 线（金叉）= 动量由空转多，是独立于背离的重要信号。现有代码完全没有用到。

---

## 二、优化方案

### 优化1：背离类型过滤（最高优先级）

**改动位置**：`app/services/signal_engine.py` → `confluence_score()`

```python
# --- RSI 背离：只计算 Regular 背离，Hidden 忽略或惩罚 ---
rsi_regular_bull = [d for d in rsi_divs if d.get("type") == "Regular" and d.get("bullish") == True]
rsi_regular_bear = [d for d in rsi_divs if d.get("type") == "Regular" and d.get("bullish") == False]
rsi_hidden = [d for d in rsi_divs if d.get("type") == "Hidden"]

if candidate.bullish and rsi_regular_bull:
    rsi_score += 8  # Regular 底背离
elif candidate.bullish and rsi_hidden:
    rsi_score -= 5  # Hidden 底背离 → 行情可能继续跌

# --- MACD 背离：同样只认 Regular ---
macd_regular_bull = [d for d in macd_divs if d.get("type") == "Regular" and d.get("bullish") == True]
macd_regular_bear = [d for d in macd_divs if d.get("type") == "Regular" and d.get("bullish") == False]
macd_hidden = [d for d in macd_divs if d.get("type") == "Hidden"]

factors["macd"] = 10 if (candidate.bullish and macd_regular_bull) or (not candidate.bullish and macd_regular_bear) else 0
if candidate.bullish and macd_hidden:
    factors["macd"] = -5  # Hidden 背离说明行情在延续
```

> **预期效果**：过滤掉 Hidden 背离假信号，胜率提升 5-10%。

---

### 优化2：MACD 零线过滤（高优先级）

**新增字段**：`DivergenceSearch` 返回的 `Divergence` 对象需要增加 `macd_line` 位置字段。

在 `confluence_score()` 中增加：

```python
def _macd_zero_filter(candidate: Candidate, macd_line: float) -> float:
    """MACD 线在零轴上方还是下方，作为动量过滤器。"""
    if candidate.bullish:
        # 看多时 MACD 在零轴下方 = 超卖区反弹，更可靠
        return 8 if macd_line < 0 else -4
    else:
        # 看空时 MACD 在零轴上方 = 超买区转空，更可靠
        return 8 if macd_line > 0 else -4
```

> **预期效果**：避免在 MACD 零线另一侧开反向仓，胜率提升 3-8%。

---

### 优化3：MACD 柱状图强度评分

**改动位置**：`_prepare_score_context()` → 新增 `macd_histogram` 字段传入 `confluence_score()`

```python
# 在 _prepare_score_context 中获取 MACD 直方图
macd_histogram = float(df["macd"].iloc[-1])  # pyharmonics 的 MACD 列是直方图
macd_histogram_prev = float(df["macd"].iloc[-2])

# 直方图正在扩大 = 动量正在增强
histogram_strength = 0
if candidate.bullish:
    if macd_histogram > 0 and macd_histogram > macd_histogram_prev:
        histogram_strength = 6  # 多头动量正在加速
elif not candidate.bullish:
    if macd_histogram < 0 and macd_histogram < macd_histogram_prev:
        histogram_strength = 6  # 空头动量正在加速

factors["histogram"] = histogram_strength
```

> **预期效果**：识别动量正在扩张的形态，胜率提升 2-5%。

---

### 优化4：RSI 动态区域评分

**改动位置**：`confluence_score()` 中 RSI 评分部分

```python
def _rsi_zone_score(rsi: float, candidate_bullish: bool, rsi_series: pd.Series) -> float:
    """RSI 极值 + RSI 趋势方向双重确认。"""
    score = 0

    # RSI 趋势：最近 N 根 K 线 RSI 在上升还是下降
    rsi_lookback = 5
    rsi_recent = rsi_series.tail(rsi_lookback).values
    rsi_rising = len(rsi_recent) >= 2 and rsi_recent[-1] > rsi_recent[0]

    if candidate_bullish:
        # 极值区
        if rsi <= 30:
            score += 7
        elif rsi <= 40:
            score += 5
        elif rsi <= 50:
            score += 2

        # RSI 正在改善（上升）= 额外确认
        if score > 0 and rsi_rising:
            score += 3

        # RSI 从超买区回落 → 警惕（行情可能还没跌透）
        if rsi >= 60:
            score -= 3
    else:
        # 看空
        if rsi >= 70:
            score += 7
        elif rsi >= 60:
            score += 5
        elif rsi >= 50:
            score += 2

        if score > 0 and not rsi_rising:  # RSI 在下降 = 恶化中
            score += 3

        if rsi <= 40:
            score -= 3

    return score
```

> **预期效果**：RSI 改善中的超卖形态额外加分，区分"刚进极值区"和"极值区停留很久"，胜率提升 2-4%。

---

### 优化5：背离质量（跨度和强度）

**改动位置**：`DivergenceSearch` 或 `confluence_score()` 中处理 `found` 字典

```python
def _divergence_quality(divergence: Divergence, df: pd.DataFrame) -> float:
    """评估背离的质量：跨度越长、指标幅度差异越大 = 质量越高。"""
    x_indices = divergence.x  # 价格峰值/低谷的 bar 索引

    if len(x_indices) < 2:
        return 0.0

    # 跨度：两个价格峰值之间的距离（bar 数）
    price_span = abs(x_indices[1] - x_indices[0])

    # 价格变动幅度
    price_change = abs(df.iloc[x_indices[1]]["close"] - df.iloc[x_indices[0]]["close"])

    # 指标变动幅度
    indicator_values = divergence.y  # [y1, y2]
    if len(indicator_values) < 2:
        return 0.0

    indicator_change = abs(indicator_values[1] - indicator_values[0])

    # 质量分数：跨度 * 指标幅度差异（归一化）
    span_score = min(price_span / 40.0, 1.0) * 5  # 40 bar 满分 5 分
    magnitude_score = min(indicator_change / 20.0, 1.0) * 5  # 20 单位满分 5 分

    return span_score + magnitude_score  # 最高 10 分
```

在 `confluence_score()` 中：
```python
# 高质量背离额外加分（最高 +5）
rsi_quality_bonus = max((_divergence_quality(d, df) for d in rsi_regular_bull), default=0)
if rsi_quality_bonus > 6:
    rsi_score += 5
elif rsi_quality_bonus > 3:
    rsi_score += 2
```

> **预期效果**：长周期背离比短周期背离权重更高，减少假信号，胜率提升 2-4%。

---

### 优化6：双指标共振加成

**改动位置**：`confluence_score()`

```python
# RSI + MACD 同时出现 Regular 背离 = 双重确认
if rsi_regular_bull and macd_regular_bull:
    factors["dual_confirmation"] = 8  # 额外 +8 分
elif rsi_regular_bear and macd_regular_bear:
    factors["dual_confirmation"] = 8
# 只有一个指标有 Regular 背离
elif rsi_regular_bull or macd_regular_bull:
    factors["dual_confirmation"] = 3
else:
    factors["dual_confirmation"] = 0
```

更新 `confluence_weights`：
```python
confluence_weights = {
    "price_action": 20,    # -5（原 25）
    "htf_trend": 20,       # -5（原 25）
    "rsi": 12,             # -3（原 15）
    "structure": 12,       # -3（原 15）
    "macd": 8,             # -2（原 10）
    "dual_confirmation": 8, # 新增
    "histogram": 5,         # 新增（优化3）
    "funding": 10,
}
# 总计：20+20+12+12+8+8+5+10 = 95，需微调
```

> **预期效果**：双重确认信号大幅提升，胜率提升 5-10%。

---

### 优化7：MACD 线与 Signal 线交叉确认

**改动位置**：`_prepare_score_context()` 或新函数

```python
def _macd_crossover_signal(df: pd.DataFrame, bullish: bool) -> float:
    """检测 MACD 线与 Signal 线的最近交叉。"""
    macd_line = df["macd"].iloc[-1]      # pyharmonics 中 macd 列是直方图
    macd_prev = df["macd"].iloc[-2]
    signal_line = df["macd_signal"].iloc[-1] if "macd_signal" in df.columns else None

    if signal_line is None:
        return 0

    # 金叉（MACD 从下方穿越 Signal）
    if macd_prev < signal_prev and macd_line >= signal_line:
        return 8 if bullish else -4

    # 死叉
    if macd_prev > signal_prev and macd_line <= signal_line:
        return -4 if bullish else 8

    return 0
```

> **注意**：需要确认 pyharmonics 的 DataFrame 是否包含 Signal 线列。如果不包含，需要自己计算。

---

## 三、参数调优建议

### RSI 参数

| 参数 | 当前值 | 建议值 | 说明 |
|------|--------|--------|------|
| `rsi_window` | 14 | 14 | 保持不变 |
| 极值超卖阈值 | 35 | **30** | 更严格的极值要求 |
| 反弹区阈值 | 45 | **40** | 更严格 |
| 改善确认加分 | 无 | **+3** | RSI 正在上升时 |

### MACD 参数

| 参数 | 当前值 | 建议值 | 说明 |
|------|--------|--------|------|
| fast | 12 | 保持 | 标准参数 |
| slow | 26 | 保持 | 标准参数 |
| signal | 9 | 保持 | 标准参数 |
| 零线过滤 | 无 | **+8 / -4** | 关键新增 |

### 共振权重调整

```python
confluence_weights: Mapping[str, float] = field(default_factory=lambda: {
    "price_action": 18,       # -7（原 25，强反转 K 线仍然重要）
    "htf_trend": 18,          # -7（原 25）
    "rsi": 12,                # -3（原 15）
    "structure": 10,          # -5（原 15）
    "macd": 8,                # -2（原 10）
    "dual_confirmation": 8,   # 新增
    "histogram": 5,           # 新增
    "rsi_zone": 6,            # 新增（RSI 动态区域）
    "funding": 10,            # 不变
})
# 总计：18+18+12+10+8+8+5+6+10 = 95（需归一化为 100 或微调）
```

### A 档门槛调整

| 参数 | 当前值 | 建议值 |
|------|--------|--------|
| `a_grade_min` | 75 | **70**（更灵活）|
| `a_grade_min_high_quant` | 85 | **80** |

---

## 四、实施优先级和预期收益

| 优先级 | 优化项 | 改动规模 | 预期胜率提升 |
|--------|--------|----------|-------------|
| P0 | 背离类型过滤（Regular vs Hidden） | 小 | +5-10% |
| P1 | MACD 零线过滤 | 小 | +3-8% |
| P1 | RSI 动态区域评分 | 中 | +2-4% |
| P2 | 双指标共振加成 | 小 | +5-10% |
| P2 | 背离质量评分 | 中 | +2-4% |
| P3 | MACD 柱状图强度 | 小 | +2-5% |
| P3 | MACD/Signal 交叉确认 | 中 | +2-4% |

**综合预期**：在当前基础上，胜率提升 **10-20%**（取决于市场环境）。

---

## 五、风险和注意事项

1. **过度优化风险**：调整参数后需要在历史数据上做回测验证，避免过拟合
2. **Hidden 背离处理**：Hidden 背离不一定是负分，只是说明行情在延续；可设 0 分而不是 -5
3. **零线附近处理**：MACD 在零线附近（-5 ~ +5）时应视为中性，不给分也不扣分
4. **多指标冲突**：当 RSI 和 MACD 背离方向矛盾时，默认信任 RSI（更领先指标）

---

## 六、代码改动清单

需要修改的文件：

```
app/services/signal_engine.py
  - confluence_score()      → 背离类型过滤、零线过滤、双确认加分
  - _prepare_score_context() → 增加 macd_histogram 传入

app/config/tuning.py
  - confluence_weights      → 重分配权重
  - 新增 rsi_extreme_lower / rsi_pullback_lower 等阈值

app/domain/rsi_trend.py（可选）
  - 如果需要 RSI series 传入 score context

pyharmonics adapter（如果需要）
  - 返回 Divergence 对象的 type 字段
  - 可能需要添加 macd_signal 列
```

---

*生成时间：2026-08-05 | 基于 v4 pipeline 代码审查*
