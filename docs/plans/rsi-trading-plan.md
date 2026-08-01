# RSI 策略页改造：从「信号扫描」到「分析 + 交易计划」

> 分支: `feat/rsi-trading-plan`（worktree: `/private/tmp/rsi-plan-worktree`）
> 页面: `http://localhost:3000/rsi-strategy`
> 状态: **设计稿 v2**（审计修订，尚未实现）
> 目标: 把「开始扫描」升级为「分析并给出明确的交易策略与交易计划」，以 **4h ticker 为主要分析数据**

---

## 0. 审计修订记录

| 修订 | 级别 | 问题 | 修正 |
|---|---|---|---|
| R1 | P0 | AI 解读的 LLM 复用路径有假假设——vibe orchestrator 的 OpenAI 是内部方法，无独立 public client | **新增 §4.5.1**：`app/services/llm_client.py` 独立 LLM 客户端（不依赖 vibe）、配置独立 API key |
| R2 | P0 | position 配置读取同样存在假假设——`_load_position` 是 vibe orchestrator 的私有方法 | **新增 §4.4.1**：`app/services/position_reader.py` 公共工具（复用 Supabase 查询，不耦合 vibe） |
| R3 | P0 | `trend_strength` 只有文字描述无公式 | **修订 §4.2.1**：给出具体公式（EMA 斜率 + 收盘距 EMA50 的位置） |
| R4 | P0 | 历史参考存在 IS 偏倚——用 plan 分析用的同一批数据算胜率 | **修订 §3**：history 字段只包含「有统计意义」的信息，加 CI 标记，附时间错位警告 |
| R5 | P1 | watch 场景输出未定义——用户不知道在等什么 | **新增 §3**：watch 场景专用字段 `watch_for` |
| R6 | P1 | LLM 调用无粒度控制——用户频繁换 symbol 会累积成本 | **新增 §4.5.2**：缓存策略 + 限流（同 symbol+interval 每 4h 最多调一次） |
| R7 | P1 | plan 新建独立 API，复用了 scan 80% 逻辑但没有抽取公共层 | **修订 §4.6 + 新增 §4.6.1**：plan 内部调用 `_scan_core()` 公共函数，避免代码分叉 |
| R8 | P1 | 缺少多周期分析能力——4h 为主、但 1h 入场细化可以提升计划质量 | **新增 §3**：`multi_tf` 可选字段（设 phase 2 实现，不阻塞 v1） |
| R9 | P2 | 6 个卡片组件拆太细——内聚信息拆碎后维护成本高 | **修订 §5.2**：合并为 3 个卡片（MarketOverview、Decision+Plan 合一、AI Insight） |
| R10 | P2 | confidence 权重 ad-hoc（0.35×趋势 + 0.30×质量分 + ...） | **修订 §4.2.1**：新增权重校准说明 + 提取为常量 + 标注「alpha 值需回测校准」 |

**修订后的实施步骤调整**：步骤 0 新增两个公共服务（llm_client / position_reader），步骤 1 前须有 `_scan_core()` 重构。

---

## 1. 背景与目标

### 现状问题

当前 `/rsi-strategy` 页面的「信号扫描」tab 只做两件事：

1. 展示当前市场状态快照（趋势 / EMA200 偏离 / RSI / 收盘价 / EMA）
2. 列出最近 ≤10 个入场信号（方向 / 入场 / 止损 / 目标 / RSI / 质量分）

**它不给用户「下一步做什么」**。唯一的"计划"是一行硬编码文字：
> 建议单笔风险控制在总资金的 0.5%–1%，仓位 = 可承受亏损 ÷（入场价 − 止损价）。

用户拿到一堆信号后仍需自己判断：现在该不该交易？仓位多大？止损放哪？失效条件是什么？

### 目标

把「信号扫描」tab 替换为「智能分析」tab，输出一份**结构化的交易计划**：

- ✅ 明确的市场研判（趋势 / 动量 / 波动率 / 是否值得交易）
- ✅ 明确的交易决策（trade / watch / no-trade + 理由）
- ✅ 具体的交易计划（入场触发、止损、三档目标、R:R、**具体仓位**）
- ✅ 失效条件与风险管理
- ✅ AI 解读（规则引擎为主，LLM 做定性补充）
- ✅ 以 4h 为默认主分析周期

---

## 2. 现状代码分析

### 2.1 前端链路

| 文件 | 职责 |
|---|---|
| `frontend/app/rsi-strategy/page.tsx` | 页面容器：两个 tab（信号扫描 / 历史回测），渲染 `MethodologyCard` + `ScanPanel` / `BacktestPanel` |
| `frontend/components/rsi-strategy/scan-panel.tsx` | 扫描面板：参数表单 + 状态卡片 + 最新信号卡片 + 最近信号表格 |
| `frontend/components/rsi-strategy/params-form.tsx` | 参数表单（market / symbol / interval / ATR-mult / RSI-zone / reward-risk / quality / EMA50 / candle-color） |
| `frontend/components/rsi-strategy/backtest-panel.tsx` | 回测面板（保留不动） |
| `frontend/hooks/use-rsi-strategy.ts` | 状态 + AbortController + 调用 API |
| `frontend/lib/api-rsi-strategy.ts` | API wrapper：`scanRsiTrend()` / `backtestRsiTrend()` + 类型 |

### 2.2 后端链路

| 文件 | 职责 |
|---|---|
| `app/api/rsi_trend_routes.py` | `GET /api/rsi-trend/scan`、`POST /api/rsi-trend/backtest`（require_auth + 配额记账） |
| `app/services/rsi_trend_service.py` | `scan()`: 拉 500 根K线 → `current_state()` + `detect_signals()` → state + latest + recent(10)；`backtest()`: 拉历史 → 信号 → `run_backtest()` |
| `app/domain/rsi_trend.py` | `enrich()`（ema200/ema50/rsi/atr）、`detect_signals()`（RSI 穿越 zone + EMA200 过滤 + 质量分）、`current_state()`（trend/deviation/entangled） |
| `app/domain/rsi_trend_backtest.py` | `run_backtest()`：逐 bar 模拟（止损 → 1:R 目标 → 部分平仓 → EMA200 翻转退出） |
| `app/domain/rsi_trend_schemas.py` | 请求校验（market↔interval 组合：crypto 1h/4h/1d，stock 1d/1w） |

### 2.3 关键发现

1. **scan 无仓位、无决策、无多档目标**：`detect_signals` 只产出单目标（`close + reward_risk * risk`），止损 = 信号K线极值 ± `atr_mult * ATR`。
2. **已有可复用的 position 模块**（`frontend/lib/position/defaults.ts` + Supabase `profiles.position_config`）：
   - `DEFAULT_CONFIG.totalCapitalWu`（总资金，WU 单位，1U = 10000WU）
   - `RECOMMENDATIONS` 风险偏好预设（conservative/balanced/aggressive × small/medium/large）
   - `createDefaultBalance()` 分账户资金
   - **审计 R2**：后端 `orchestrator._load_position()` 是 vibe 的内部方法（`app/services/vibe/orchestrator.py:389-397`），使用 Supabase service_role 读 `profiles.position_config`，不可跨模块直接调用——需要抽取为公共工具 `app/services/position_reader.py`。
3. **AI 通道不是独立服务**：vibe 内的 OpenAI 调用封装在 orchestrator 内部，无独立 LLM client 模块。
   - **审计 R1**：需要新建 `app/services/llm_client.py`，与其他模块解耦，接受独立 API key。
4. **4h 数据链路**：TradingView bridge（`4h → '240'`，最多 5000 根）→ `fetch_market_data()`；RSI 策略当前只暴露 binance spot + yahoo（`rsi_trend_schemas.py` 限制 futures 不可选）。
5. **`current_state()`** 输出 trend / deviation_pct / entangled —— 决策引擎的直接输入。

---

## 3. 核心概念：TradingPlan（交易计划）

新增一个结构化产出物 `TradingPlan`，是本次改造的核心。它由**后端生成**（规则引擎 + AI 解读），前端只负责渲染。

```jsonc
{
  "symbol": "BTCUSDT",
  "interval": "4h",
  "generated_at": "2026-08-01T12:00:00Z",
  "plan_non_prod": true,               // 强制标记，前端始终渲染免责声明

  // ── 1. 市场概况 ─────────────────────────────────────────
  "market_overview": {
    "trend": "bullish",                // bullish / bearish / range
    "trend_strength": 0.72,            // ⬆️ R3 已定义公式见 §4.2.1
    "close": 68000,
    "ema200": 64000,
    "ema50": 65500,
    "deviation_pct": 6.2,              // close 相对 EMA200 偏离
    "rsi": 58.3,
    "atr": 1200,
    "atr_pct": 1.76,
    "volatility_regime": "normal",     // low / normal / high
    "entangled": false,                // EMA50/EMA200 缠绕警告
    "notes": ["价格站上 EMA200 且 EMA50 上行，趋势健康"]
  },

  // ── 2. 交易决策 ─────────────────────────────────────────
  "decision": {
    "action": "trade",                 // trade / watch / no_trade
    "direction": "long",               // long / short / null
    "confidence": 0.66,                // 0-1，⬆️ R10 权重常量可校准
    "reasons": [
      "RSI 从 26.8 上穿 30 区间，触发超卖反转信号",
      "价格位于 EMA200 上方，顺势做多",
      "质量分 78，高于 60 阈值"
    ],
    "warnings": ["ATR 占价格 1.76%，波动率偏高，建议仓位减半"],

    // ⬆️ R5: watch 场景专用字段（action=watch 时包含）
    "watch_for": "等待 RSI 回调至 40 附近且不破 EMA200，或等待 4h 收盘突破当前整理区间上沿"
  },

  // ── 3. 交易计划（仅在 action=trade 时有意义）────────────
  "plan": {
    "entry": {
      "price": 68120,
      "trigger": "现价挂单或回踩 EMA50 附近分批入场",
      "entry_type": "market"
    },
    "stop": {
      "price": 66200,
      "logic": "信号K线低点 - 1.0×ATR",
      "distance_atr": 1.6
    },
    "targets": [
      { "level": "tp1", "price": 69500, "rr": 1.15, "weight": 0.50 },
      { "level": "tp2", "price": 70900, "rr": 2.30, "weight": 0.30 },
      { "level": "tp3", "price": 72800, "rr": 3.90, "weight": 0.20 }
    ],
    "risk_reward": 2.30,
    "position": {
      "risk_per_trade_pct": 1.0,
      "total_capital_wu": 100000,
      "risk_amount_wu": 1000,
      "position_size_wu": 52631,
      "position_size_u": 5.26,
      "sizing_note": "波动率偏高，已按 0.5 系数减仓",
      "configured": true                // ⬆️ R2: false = 用户未设置资金，前端需降级
    },
    "management": {
      "breakeven_after": "tp1",
      "trailing_stop": true,
      "time_stop": "48 根 4h K线未达 TP1 则手动评估"
    }
  },

  // ⬆️ R8: 多周期分析（v2 实现，v1 可选 null）
  "multi_tf": null,

  // ── 4. 失效条件（Invalidation）──────────────────────────
  "invalidation": [
    "收盘价跌破 EMA200 → 趋势失效，无条件离场",
    "4h 收盘跌破 66200（止损位）→ 止损离场",
    "RSI 重新跌破 30 且价格跌破信号K线低点 → 信号无效"
  ],

  // ── 5. 历史参考 ────────────────────────────────────────
  // ⬆️ R4: 增加统计质量标记
  "history": {
    "signals_count": 12,
    "win_rate": 0.58,
    "win_rate_ci_lower": 0.42,         // ⬆️ R4: Wilson 95% CI 下界（12 样本时很宽）
    "avg_r": 1.42,
    "profit_factor": 1.9,
    "note": "最近 12 个同类信号按 1:2 止盈止损模拟",
    "data_warning": "⚠️ 样本量仅 12 个，且取自与当前分析相同的 K 线窗口——信号表现不代表未来"  // ⬆️ R4
  },

  // ── 6. AI 解读 ─────────────────────────────────────────
  "ai_insight": {
    "summary": "4h 级别多头趋势结构完好，RSI 超卖修复后动能回升……",
    "risk_note": "若 4h 收盘失守 EMA200 且伴随放量，反弹逻辑失效",
    "disclaimer": "本分析由 AI 辅助生成，不构成投资建议",
    "cached": true                     // ⬆️ R6: 是否命中缓存
  }
}
```

---

## 4. 后端设计

### 4.0 前置功课（审计新增 —— 公共依赖）

**⬆️ R1：独立 LLM 客户端** `app/services/llm_client.py`

```
llm_client.analyze(prompt, max_tokens) -> str | None
  - 接受独立 OpenAI-compatible API key（环境变量 RSI_PLAN_OPENAI_API_KEY）
  - 不依赖 vibe 的任何模块
  - 超时 10s，失败返回 None
```

> 为什么不复用 vibe 的 LLM？vibe orchestrator 把 OpenAI 调用内嵌在全双工流式对话中间，
> 没有暴露一个独立的 `call_llm(prompt) -> str` 接口。抽取公共客户端比强行耦合更干净。

**⬆️ R2：position 配置读取器** `app/services/position_reader.py`

```
position_reader.get_position_config(user_id) -> dict | None
  - 复刻 orchestrator._load_position() 的 Supabase 查询逻辑
  - 返回 {"position_config": {...}, "position_balance": {...}} 或 None
  - 不依赖 vibe 模块
```

> RSI plan 的 service 在计算仓位时需要读用户资金，但不应耦合到 vibe orchestrator。

**⬆️ R7：scan 公共逻辑抽取** `app/services/rsi_trend_service.py` 内新增 `_scan_core()`

```
_scan_core(req, candles=500) -> {"state":..., "signals":[...]}
  - plan() 和 scan() 共用此函数
  - plan() 调用 _scan_core(req, candles=1000)，scan() 调用 _scan_core(req, candles=500)
  - 避免两套代码分叉
```

### 4.1 新增文件

```
app/domain/rsi_trend_plan.py          # TradingPlan 数据结构 + 决策规则引擎（纯函数）
app/services/rsi_trend_plan_service.py # build_plan(): 编排 → 决策 → 目标 → 仓位 → AI
app/services/llm_client.py            # ⬆️ R1 独立 LLM 客户端
app/services/position_reader.py       # ⬆️ R2 position 配置读取
```

### 4.2 决策规则引擎（`app/domain/rsi_trend_plan.py`）

纯函数、无 I/O，输入 `state` + 最新信号 + 质量分，输出决策。四层过滤：

```
┌─ L1 趋势过滤 ─────────────────────────────────────────────┐
│  close > EMA200              → 只考虑 long                 │
│  close < EMA200              → 只考虑 short                │
│  |deviation_pct| > 15%        → 追高风险，降级 watch        │
│  entangled                    → 降级 watch（方向不明）       │
│  deviation_pct 在 ±2% 以内    → 横盘震荡，降权 confidence   │
├─ L2 动量触发 ─────────────────────────────────────────────┤
│  最新信号距今 ≤ 3 根 4h K线    → 新鲜信号，可 trade         │
│  4 < 距今 ≤ 12                → 信号有效但已有滞后，watch    │
│  > 12 且无新鲜信号            → no_trade，返回等回调建议     │
├─ L3 质量过滤 ─────────────────────────────────────────────┤
│  quality_score ≥ min_quality_score AND ≥ 50 (hard floor)   │
│  低于 hard floor → no_trade                                │
├─ L4 波动率检查 ────────────────────────────────────────────┤
│  atr_pct < 0.8%   → low volatility，正常仓位               │
│  0.8%–3%          → normal                                 │
│  > 3%             → high volatility，仓位 ×0.5 + warnings  │
└────────────────────────────────────────────────────────────┘
输出: action(trade/watch/no_trade) + direction + confidence + reasons + warnings [+ watch_for]
```

#### 4.2.1 趋势强度公式 ⬆️ R3

去掉 v1 中的模糊描述，给出具体公式：

```python
def _trend_strength(close, ema200, ema50, atr) -> float:
    """0-1, 量化趋势的强度和清晰度"""
    # 1. EMA 排列分 (0-0.5): EMA50 > EMA200 = 0.5, EMA50/EMA200 交叉 = 0
    alignment = 0.5 if (close > ema50 > ema200) or (close < ema50 < ema200) else 0.0

    # 2. 偏离强度分 (0-0.5): deviation_pct 越大越强，但 10%+ 封顶
    deviation = min(abs((close - ema200) / ema200), 0.10)
    strength = deviation / 0.10 * 0.5

    # 3. 纠缠惩罚: entangled → strength × 0.4
    if atr and abs(close - ema200) < 0.5 * atr:
        strength *= 0.4

    return round(min(alignment + strength, 1.0), 2)
```

#### 4.2.2 置信度校准 ⬆️ R10

```python
# 所有权重提取为模块级常量，标注为 alpha（需回测校准后锁死）
CONFIDENCE_WEIGHTS = {
    "trend_strength": 0.35,
    "quality_score": 0.30,
    "rsi_momentum": 0.20,
    "freshness": 0.15,
}

confidence = (
    w["trend_strength"] * trend_strength +
    w["quality_score"] * (quality_score / 100) +
    w["rsi_momentum"] * _rsi_momentum_score(rsi_now, rsi_prev, rsi_zone) +
    w["freshness"] * _freshness_score(signal_age_bars)
)
```

**注意**：这些权重未经回测验证。`rsi_momentum_score` 和 `freshness_score` 的映射函数需在实现时定义（衰减曲线 vs 分段线性）。建议在 v1 上线后运行参数扫描确定阈值。

### 4.3 三档目标生成

现有 `detect_signals` 只产单目标。在 plan 层扩展：

```
risk = entry - stop  (long)  或  stop - entry  (short)
TP1 = entry + 1.0 × risk      （50% 仓位）
TP2 = entry + 2.0 × risk      （30% 仓位）
TP3 = entry + 3.5 × risk      （20% 仓位）
```

权重与回测引擎 `partial_mode` 语义对齐：到 TP1 平 50% + 移损至保本。

### 4.4 仓位计算 ⬆️ R2

后端调用 `position_reader.get_position_config(user_id)` 读取：

```
risk_per_trade_pct: conservative=0.5% / balanced=1.0% / aggressive=1.5%
                    （从 risk_appetite 推导；未设置 → 默认 1.0%）
risk_amount_wu     = totalCapitalWu × risk_per_trade_pct
position_size_wu   = risk_amount_wu ÷ ((entry - stop) / entry)  [long]
                   = risk_amount_wu ÷ ((stop - entry) / entry)  [short]
position_size_u    = position_size_wu / 10000
```

- 用户未配置 → `position.configured = false`，其他字段为空，前端降级
- `volatility_regime == high` → `sizing_note` 标记 "波动率偏高，已按 0.5 系数减仓" 并实际 ×0.5

#### 4.4.1 ⬆️ R2：position_reader 实现要点

```
app/services/position_reader.py
  get_position_config(user_id):
    1. client = get_supabase_client(use_service_role=True)
    2. result = client.table("profiles").select("position_config, position_balance")
              .eq("id", user_id).single().execute()
    3. 返回 data.get("position_config"), data.get("position_balance") 或 None
    4. 异常 → log warning + 返回 None
```

### 4.5 AI 解读

#### 4.5.1 ⬆️ R1：独立 LLM 客户端 `app/services/llm_client.py`

```python
# 核心接口
def complete(prompt: str, max_tokens: int = 300, timeout: float = 10) -> str | None:
    """调用 LLM，超时/异常返回 None"""

# 配置
OPENAI_API_KEY: os.environ["RSI_PLAN_OPENAI_API_KEY"]
MODEL: "gpt-4o-mini"  # 便宜，足够解读
```

**与 vibe 的关系**：vibe 使用 Full-Context Conversation + Function Calling 的流式 LLM 管道，与 RSI plan 的单次摘要请求场景完全不同。强行复用 vibe 的内部管道（orchestrator → chat_session → OpenAI stream）比独立客户端更复杂且引入不必要的耦合。

#### 4.5.2 ⬆️ R6：缓存策略

避免用户频繁切换 symbol 累积 LLM 成本：

```
缓存键：{user_id}:{symbol}:{interval}:{latest_bar_timestamp}
TTL：最近一根 K 线对应的剩余时间（4h K 线 = 4h 窗口）
   - 用户在当前 K 线内多次查询 → 命中缓存
   - 新 K 线产生  → 缓存自动过期
   - ai_insight.cached 标记告知前端
```

prompt 输入（同 v1）：

```
市场概况（trend / deviation_pct / RSI / ATR / volatility_regime / entangled）
决策结果（action / direction / confidence / reasons / warnings）
计划摘要（entry / stop / TP1-TP3 / position_size_u / R:R）

要求输出 { "summary": "≤120字", "risk_note": "≤80字" }
```

- **失败兜底**：LLM 超时/异常 → `ai_insight` 置 null，计划主体不受影响
- **成本控制**：`action=no_trade` 时不调 LLM（只展示规则引擎输出）

### 4.6 API

新增 `GET /api/rsi-trend/plan`（保留 scan/backtest 不动，向后兼容）：

```
GET /api/rsi-trend/plan?market=binance&symbol=BTCUSDT&interval=4h&...
→ 200 { TradingPlan }
```

- `require_auth` + 配额记账（复用 scan 同一配额单元，每请求消耗 1 配额）
- 参数校验复用 `RsiTrendScanRequest` schema
- 数据量：`PLAN_CANDLES = 1000` 根

#### 4.6.1 ⬆️ R7：plan 与 scan 的代码共享

`rsi_trend_service.py` 重构：

```python
def _scan_core(req: RsiTrendScanRequest, candles: int) -> dict:
    """公共扫描逻辑，plan() 和 scan() 的共享底层"""
    candle_data = fetch_market_data(...)
    df = candle_data.df
    _require_enough_bars(...)
    state = current_state(df)
    signals = detect_signals(df, ...)
    return {"state": state, "signals": signals, "bars": len(df)}

def scan(req: RsiTrendScanRequest) -> dict:
    core = _scan_core(req, candles=SCAN_CANDLES)
    recent = [s.to_dict() for s in core["signals"][-RECENT_SIGNALS_LIMIT:]][::-1]
    return {..., "state": core["state"], "latest_signal": recent[0] if recent else None, ...}

def build_plan(req: RsiTrendScanRequest, user_id: str) -> dict:
    core = _scan_core(req, candles=PLAN_CANDLES)
    plan = DecisionEngine.evaluate(core["state"], core["signals"])
    plan = TargetGenerator.add_targets(plan, req.reward_risk)
    plan = PositionCalculator.add_position(plan, user_id)  # ⬆️ R2
    plan = AIInterpreter.add_insight(plan, user_id, core["state"])  # ⬆️ R1 + R6
    return TradingPlan.to_dict(plan)
```

**关键原则**：`_scan_core()` 不做计划生成——计划是 consumer 层的责任。

---

## 5. 前端设计

### 5.1 页面结构（替换扫描为分析）

```
frontend/app/rsi-strategy/page.tsx
  ├─ Tab「智能分析」（原信号扫描）→ AnalysisPanel（新）
  ├─ Tab「历史回测」              → BacktestPanel（保留）
```

### 5.2 新组件 ⬆️ R9（精简为 3 个卡片）

v1 规划了 6 个卡片，审计发现过度碎片化——plan 是一个内聚的信息块，拆太细增加维护成本。

```
frontend/components/rsi-strategy/
  ├─ analysis-panel.tsx            # 主面板（替代 scan-panel.tsx）
  ├─ params-form.tsx               # 复用（interval 默认 "4h"，加 label 说明）
  ├─ market-overview-card.tsx      # 市场概况 (=v1 不变)
  ├─ trade-plan-card.tsx           # ⬆️ R9 合并: 决策 + 计划 + 失效条件 + 历史参考
  │   ├─ decision 区（action 徽章 + 方向色带 + 置信度条）
  │   ├─ plan 区（入场/止损/三档目标 三列 + 仓位计算）
  │   ├─ invalidation 区（折叠）
  │   └─ history 区（迷你表，附 warning）
  └─ ai-insight-card.tsx           # AI 解读 (=v1 不变)
```

### 5.3 交互流程

```
1. 用户选 symbol（默认 BTCUSDT）+ 参数（interval 默认 4h）
2. 点击「生成交易计划」
3. Loading（骨架屏：趋势卡片 + plan 卡片占位）
4. 渲染 TradingPlan：
   - decision=trade   → 完整 market-overview + trade-plan + ai-insight 卡片
   - decision=watch   → market-overview + 简化版 plan 卡（无目标/仓位，展示 watch_for）
   - decision=no_trade→ market-overview + 原因卡（淡色，不展示 plan）
5. 底部附「历史参考」迷你表（与 plan 卡片内的 history 区复用同一数据源）
```

### 5.4 position 模块接入 ⬆️ R2

- 前端通过 TradingPlan 响应的 `plan.position.configured` 字段判断用户是否已配置资金
- `configured=true` → 正常展示仓位（`position_size_u` 为主，`position_size_wu` 为辅）
- `configured=false` → 仓位区降级为提示："尚未设置账户资金 → 前往仓位管理页面"，附带默认 1% 风险的参考值示例
- 不再需要前端独立调用 position API——后端已在 TradingPlan 中包含仓位计算结果

### 5.5 API wrapper

`frontend/lib/api-rsi-strategy.ts` 新增：

```ts
export interface RsiTrendPlanResponse { ... TradingPlan 类型 ... }
export function planRsiTrend(token, params, signal?): Promise<ApiResponse<RsiTrendPlanResponse>>
```

### 5.6 params-form 改动范围 ⬆️ R9（明确化）

- interval 默认值从用户传入 → AnalysisPanel 初始化 state 时显式设 `"4h"`
- params-form 组件**本身不写死默认值**（backtest tab 仍需 1h/1d 等灵活周期）
- label 文案：`interval 标签后追加"（交易计划建议 4h）"` 作为提示

---

## 6. 实施步骤（审计修订后）

| # | 步骤 | 内容 | 验证 |
|---|---|---|---|
| **0a** | **前置依赖** | `app/services/position_reader.py`（⬆️ R2） | pytest（mock Supabase） |
| **0b** | **前置依赖** | `app/services/llm_client.py`（⬆️ R1） | pytest（mock OpenAI） |
| **0c** | **重构** | `rsi_trend_service.py` 抽取 `_scan_core()`（⬆️ R7） | 回归 `test_rsi_trend_api` |
| 1 | 后端 domain | `rsi_trend_plan.py`：TradingPlan 数据类 + 决策引擎 + 目标生成 | pytest（4 种场景 × 4 层过滤） |
| 2 | 后端 service | `rsi_trend_plan_service.py`：build_plan() 编排 + position + AI（LLM 超时兜底 + 缓存） | pytest（mock + plan 完整性断言） |
| 3 | 后端 API | `GET /api/rsi-trend/plan` 路由 + 配额 | pytest 集成 |
| 4 | 前端 API | api-rsi-strategy.ts 类型 + `planRsiTrend()` | vitest |
| 5 | 前端组件 | AnalysisPanel + 3 卡片（⬆️ R9） | vitest + 手动 |
| 6 | 前端页面 | page.tsx 替换 tab + hook 改造 | e2e（Playwright） |

> 步骤 1-3 依赖步骤 0a-0c 完成。步骤 0c 的 `_scan_core()` 重构是关键——不改现有 scan/backtest 行为但验证它们仍通过回归测试。

### 测试要点（审计完善）

- **决策引擎**：6 种场景（强趋势新鲜 / 强趋势陈旧 / 震荡 entangled / 极端偏离 watch / 追高风险 / 质量分低于 threshold）
- **仓位计算**：configured=true 正常 / configured=false 降级 / volatility_regime=high ×0.5
- **AI 兜底**：LLM 超时 → ai_insight=null + cached=false；LLM 成功 → ai_insight 有值 + cached=命中状态
- **向后兼容**：`/scan`、`/backtest` 响应结构不变（步骤 0c 的回归验证）
- **配额记账**：plan 路由正常 -1 配额，异常 → release 配额（复用 scan 的 reserve-consume-release 模式）

---

## 7. 风险与注意点

1. **AI 解读延迟**：LLM 调用 2-5s。v1 用缓存策略（同 K 线内复用，⬆️ R6）大幅降低实际调用频率。首次调用时前端 skeleton 独立展示 AI 卡片。
2. **4h 数据量**：1000 根 × 4h = 166 天数据，TV bridge 上限 5000 无压力。yahoo 股票数据可能不足，`_require_enough_bars` 兜底。
3. **position 配置缺失**：`configured=false` 时 plan 无仓位数字但有止损和目标。前端不能白屏。
4. **决策引擎阈值**：所有阈值（偏离度 15%、新鲜度 3/12、hard floor 50、volatility 0.8%/3%）提取为模块级常量。**这些是 alpha 值，未经回测校准，v1 上线后应重新扫描确定最佳值。**
5. **futures 数据**：RSI 策略 schema 仍限 binance spot + yahoo。另行评估，不在本次范围。
6. **⬆️ R6：缓存碰撞风险**：同 K 线缓存意味着用户在 K 线末尾 1 秒查询得到的是 4 小时前的 AI 解读。可接受——市场概况和计划（规则引擎）是实时计算的，只有 LLM 文本可能滞后，但这与 K 线周期一致。
7. **⬆️ R7：\_scan\_core() 重构风险**：目前 scan() 只有 30 行，重构为共享函数改动不大。但 backtest() 也调 `detect_signals`，重构时需确认 without-touching backtest 路径。
8. **⬆️ R1：LLM API key 环境变量**：需要在 `app/main.py` 启动时从环境变量/Secrets 读取，加入健康检查日志（key 存在但格式校验不通过 → warn 但不阻断启动，AI 解读自动降级）。

---

## 8. 交付物清单（最终状态）⬆️ 审计修订

- [ ] `app/services/position_reader.py`（⬆️ R2）
- [ ] `app/services/llm_client.py`（⬆️ R1）
- [ ] `app/services/rsi_trend_service.py`（⬆️ R7：抽取 `_scan_core()`）
- [ ] `app/domain/rsi_trend_plan.py`（⼤数据结构 + 决策引擎 + 趋势强度 + 置信度）
- [ ] `app/services/rsi_trend_plan_service.py`（编排：plan → target → position → AI + 缓存）
- [ ] `app/api/rsi_trend_routes.py`（+ `/plan` 路由）
- [ ] `frontend/components/rsi-strategy/analysis-panel.tsx`（替代 scan-panel）
- [ ] `frontend/components/rsi-strategy/trade-plan-card.tsx`（⬆️ R9：合并决策+计划+失效+历史）
- [ ] `frontend/components/rsi-strategy/market-overview-card.tsx`
- [ ] `frontend/components/rsi-strategy/ai-insight-card.tsx`
- [ ] `frontend/components/rsi-strategy/params-form.tsx`（微调：interval label 提示）
- [ ] `frontend/lib/api-rsi-strategy.ts`（+类型 + planRsiTrend）
- [ ] `frontend/hooks/use-rsi-strategy.ts`（+ plan 状态）
- [ ] `frontend/app/rsi-strategy/page.tsx`（tab 替换）
- [ ] 测试：position_reader / llm_client / domain / service / api / 组件 / e2e
- [ ] 环境变量：`RSI_PLAN_OPENAI_API_KEY` + health check

### ⬆️ R8：phase 2 预留（不阻塞 v1）

- `multi_tf` 字段：4h 为主方向 + 1h 入场细化（比较 1h 上是否已有局部信号）。当前 v1 固定返回 null。后续实现时只需在 `build_plan` 中增加一个可选的 1h 数据拉取步骤。
