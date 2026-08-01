# RSI 策略页改造：从「信号扫描」到「分析 + 交易计划」

> 分支: `feat/rsi-trading-plan`（worktree: `/private/tmp/rsi-plan-worktree`）
> 页面: `http://localhost:3000/rsi-strategy`
> 状态: **设计稿**（v0，尚未实现）
> 目标: 把「开始扫描」升级为「分析并给出明确的交易策略与交易计划」，以 **4h ticker 为主要分析数据**

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
2. **已有可复用的 position 模块**（`frontend/lib/position/defaults.ts` + 后端 `profiles.position_config`）：
   - `DEFAULT_CONFIG.totalCapitalWu`（总资金，WU 单位，1U = 10000WU）
   - `RECOMMENDATIONS` 风险偏好预设（conservative/balanced/aggressive × small/medium/large）
   - `createDefaultBalance()` 分账户资金
   - 后端 `app/services/vibe/tools/position_check.py` 已有「计划仓位合理性校验」逻辑
3. **已有 AI 通道**：vibe 助手用 OpenAI 输出结构化 `signal` / `position_check` 卡片（`app/services/vibe/`），可复用其 LLM client。
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

  // ── 1. 市场概况 ─────────────────────────────────────────
  "market_overview": {
    "trend": "bullish",                // bullish / bearish / range
    "trend_strength": 0.72,            // 0-1，EMA 斜率/价格分布推导
    "close": 68000,
    "ema200": 64000,
    "ema50": 65500,
    "deviation_pct": 6.2,              // close 相对 EMA200 偏离
    "rsi": 58.3,
    "atr": 1200,
    "atr_pct": 1.76,                   // ATR / close，波动率档位
    "volatility_regime": "normal",     // low / normal / high
    "entangled": false,                // EMA50/EMA200 缠绕警告
    "notes": ["价格站上 EMA200 且 EMA50 上行，趋势健康"]  // 规则生成的短句
  },

  // ── 2. 交易决策 ─────────────────────────────────────────
  "decision": {
    "action": "trade",                 // trade / watch / no_trade
    "direction": "long",               // long / short / null
    "confidence": 0.66,                // 0-1
    "reasons": [                       // 规则引擎给的理由（中文短句）
      "RSI 从 26.8 上穿 30 区间，触发超卖反转信号",
      "价格位于 EMA200 上方，顺势做多",
      "质量分 78，高于 60 阈值"
    ],
    "warnings": ["ATR 占价格 1.76%，波动率偏高，建议仓位减半"]
  },

  // ── 3. 交易计划（仅在 action=trade 时有意义）────────────
  "plan": {
    "entry": {
      "price": 68120,
      "trigger": "现价挂单或回踩 EMA50 附近分批入场",   // 入场触发条件
      "entry_type": "market"            // market / limit
    },
    "stop": {
      "price": 66200,
      "logic": "信号K线低点 - 1.0×ATR",
      "distance_atr": 1.6
    },
    "targets": [                        // 三档目标（新增，替代单目标）
      { "level": "tp1", "price": 69500, "rr": 1.15, "weight": 0.5 },  // 50% 仓位
      { "level": "tp2", "price": 70900, "rr": 2.3,  "weight": 0.3 },
      { "level": "tp3", "price": 72800, "rr": 3.9,  "weight": 0.2 }
    ],
    "risk_reward": 2.3,                // 加权 R:R
    "position": {                       // 接入 position 模块
      "risk_per_trade_pct": 1.0,        // 单笔风险占总资金比例（读用户配置）
      "total_capital_wu": 100000,       // 用户总资金（WU）
      "risk_amount_wu": 1000,           // 可承受亏损
      "position_size_wu": 52631,        // 建议仓位 = risk_amount / (entry-stop)/entry
      "position_size_u": 5.26,          // 换算 U（WU_UNIT=10000）
      "sizing_note": "波动率偏高，已按 0.5 系数减仓"
    },
    "management": {
      "breakeven_after": "tp1",         // 到 TP1 后移损至保本
      "trailing_stop": true,
      "time_stop": "48 根 4h K线未达 TP1 则手动评估"
    }
  },

  // ── 4. 失效条件（Invalidation）──────────────────────────
  "invalidation": [
    "收盘价跌破 EMA200 → 趋势失效，无条件离场",
    "4h 收盘跌破 66200（止损位）→ 止损离场",
    "RSI 重新跌破 30 且价格跌破信号K线低点 → 信号无效"
  ],

  // ── 5. 历史参考（该参数近端表现）───────────────────────
  "history": {
    "signals_count": 12,               // 近 500 根K线内的信号数
    "win_rate": 0.58,
    "avg_r": 1.42,
    "profit_factor": 1.9,
    "note": "最近 12 个同类信号按 1:2 止盈止损模拟"
  },

  // ── 6. AI 解读 ─────────────────────────────────────────
  "ai_insight": {
    "summary": "4h 级别多头趋势结构完好，RSI 超卖修复后动能回升……",
    "risk_note": "若 4h 收盘失守 EMA200 且伴随放量，反弹逻辑失效",
    "disclaimer": "本分析由 AI 辅助生成，不构成投资建议"
  }
}
```

---

## 4. 后端设计

### 4.1 新增文件

```
app/domain/rsi_trend_plan.py       # TradingPlan 数据结构 + 决策规则引擎（纯函数，可测）
app/services/rsi_trend_plan_service.py  # build_plan(): 编排数据拉取 → 决策 → 计划 → AI
```

### 4.2 决策规则引擎（`app/domain/rsi_trend_plan.py`）

纯函数、无 I/O，输入 `state` + 最新信号 + 质量分，输出决策。四层过滤：

```
┌─ L1 趋势过滤 ─────────────────────────────────────────────┐
│  close > EMA200          → 只考虑 long                      │
│  close < EMA200          → 只考虑 short                     │
│  |deviation_pct| > 15%   → 追高风险，降级 watch             │
│  entangled               → 降级 watch（方向不明）            │
├─ L2 动量触发 ─────────────────────────────────────────────┤
│  最新信号时间距今 ≤ 3 根 4h K线 → 新鲜信号，可 trade        │
│  4 < 距今 ≤ 12            → 信号仍有效但已走了一段，watch   │
│  > 12                     → 无新鲜信号，no_trade/等回调     │
├─ L3 质量过滤 ─────────────────────────────────────────────┤
│  quality_score ≥ min_quality_score → 通过                   │
│  另设 hard 阈值（如 50）：低于则 no_trade                   │
├─ L4 波动率检查 ────────────────────────────────────────────┤
│  atr_pct < 0.8%  → low：正常仓位                            │
│  0.8%–3%         → normal                                   │
│  > 3%            → high：仓位 ×0.5，警告                    │
└────────────────────────────────────────────────────────────┘
输出: action(trade/watch/no_trade) + direction + confidence + reasons + warnings
```

置信度合成（示例，可调）：

```
confidence = 0.35×趋势强度 + 0.30×质量分/100 + 0.20×RSI动量分 + 0.15×新鲜度分
```

### 4.3 三档目标生成

现有 `detect_signals` 只产单目标。在 plan 层扩展：

```
TP1 = entry + 1.0 × risk      （ATR 1 倍止损距离，50% 仓位）
TP2 = entry + 2.0 × risk      （2 倍，30%）
TP3 = entry + 3.5 × risk      （3.5 倍，20%）
```

权重（partial_mode 语义与回测引擎的 `partial_mode` 对齐：到 TP1 平 50% + 移保本）。

### 4.4 仓位计算（接入 position 模块）

后端读取用户 `profiles.position_config`（`app/services/vibe/orchestrator.py:389-397` 已有读取逻辑）：

```
risk_amount_wu   = totalCapitalWu × risk_per_trade_pct
position_size_wu = risk_amount_wu ÷ (risk_per_unit)
                 = risk_amount_wu ÷ ((entry - stop) / entry)
```

- `risk_per_trade_pct` 从用户配置的风险偏好推导（conservative 0.5% / balanced 1% / aggressive 1.5%，缺省 1%）
- `volatility_regime == high` 时 ×0.5
- 输出 `position_size_u = position_size_wu / 10000`

### 4.5 AI 解读（规则为主，AI 为辅）

复用 vibe 的 LLM client（`app/services/vibe/` 内的 OpenAI 封装），prompt 输入：

```
市场概况（trend/deviation/RSI/ATR/entangled）
决策结果（action/direction/confidence/reasons/warnings）
计划摘要（entry/stop/targets/position）

要求输出：≤120字 summary + ≤80字 risk_note（中文）
```

- **失败兜底**：LLM 调用失败/超时 → `ai_insight` 置 null，计划主体不受影响（规则引擎已给出全部信息）
- **成本控制**：仅 `action=trade` 或 `watch` 时调用，`no_trade` 不调

### 4.6 API

新增 `GET /api/rsi-trend/plan`（保留 scan/backtest 不动，向后兼容）：

```
GET /api/rsi-trend/plan?market=binance&symbol=BTCUSDT&interval=4h&...（同 scan 参数）
→ 200 { TradingPlan }
```

- `require_auth` + 配额记账（复用 scan 同一配额单元）
- 参数校验复用 `RsiTrendScanRequest` schema
- **数据量**：拉取 `PLAN_CANDLES = 1000` 根（比 scan 的 500 多，覆盖更长趋势背景；TV bridge 上限 5000，无压力）

---

## 5. 前端设计

### 5.1 页面结构（替换扫描为分析）

```
frontend/app/rsi-strategy/page.tsx
  ├─ Tab「智能分析」（原信号扫描）→ AnalysisPanel（新）
  ├─ Tab「历史回测」              → BacktestPanel（保留）
```

### 5.2 新组件

```
frontend/components/rsi-strategy/
  ├─ analysis-panel.tsx      # 主面板（替代 scan-panel.tsx，可删除原文件）
  ├─ params-form.tsx         # 复用（interval 默认改 "4h"，label 加"主分析周期"提示）
  ├─ market-overview-card.tsx  # 市场概况
  ├─ decision-card.tsx         # 决策（trade/watch/no_trade + 理由 + 置信度）
  ├─ plan-card.tsx             # 交易计划（entry/stop/targets 三档/仓位/管理）
  ├─ invalidation-card.tsx     # 失效条件
  └─ ai-insight-card.tsx       # AI 解读
```

### 5.3 交互流程

```
1. 用户选 symbol（默认 BTCUSDT）+ 参数（interval 默认 4h）
2. 点击「生成交易计划」
3. Loading（展示骨架屏）
4. 渲染 TradingPlan 卡片：
   - decision=trade   → 完整计划卡（高亮方向色）
   - decision=watch   → 概要 + 触发条件卡（等待什么信号）
   - decision=no_trade→ 原因卡 + 市场概况（不展示 plan）
5. 底部附「历史参考」迷你表（同参数近期信号表现）
```

### 5.4 position 模块接入

- 前端读取用户资金配置：复用 `frontend/hooks/use-position-config.ts`（或 `profiles.position_config` API）
- 若用户**未配置资金**：仓位区显示提示"前往 仓位管理 页面设置总资金与风险偏好"，并给默认值示例
- 展示 `position_size_u`（U）为主，`position_size_wu` 为辅

### 5.5 API wrapper

`frontend/lib/api-rsi-strategy.ts` 新增：

```ts
export interface RsiTrendPlanResponse { ... TradingPlan 类型 ... }
export function analyzeRsiTrend(token, params, signal?): Promise<ApiResponse<RsiTrendPlanResponse>>
```

---

## 6. 实施步骤（后续实现顺序）

| # | 步骤 | 内容 | 验证 |
|---|---|---|---|
| 1 | 后端 domain | `rsi_trend_plan.py`：TradingPlan 数据类 + 决策引擎 + 目标生成 | pytest 单测（纯函数） |
| 2 | 后端 service | `rsi_trend_plan_service.py`：build_plan() 编排 + position 读取 + AI 解读 | pytest（mock 数据/AI） |
| 3 | 后端 API | `GET /api/rsi-trend/plan` 路由 + 配额 | pytest 集成 |
| 4 | 前端 API | api-rsi-strategy.ts 类型 + `analyzeRsiTrend()` | vitest |
| 5 | 前端组件 | AnalysisPanel + 各卡片组件 | vitest + 手动 |
| 6 | 前端页面 | page.tsx 替换 tab + hook 改造 | e2e（Playwright） |
| 7 | 文档 | 更新 README / 页面说明 | — |

### 测试要点

- **决策引擎**：四种典型场景（强趋势新鲜信号 / 强趋势陈旧信号 / 震荡 entangled / 极端偏离）各断言 action
- **仓位计算**：不同 risk_per_trade_pct × 不同 volatility_regime 的组合
- **AI 兜底**：LLM 抛异常时 plan 仍完整返回、ai_insight=null
- **向后兼容**：`/scan`、`/backtest` 响应结构不变

---

## 7. 风险与注意点

1. **AI 解读延迟**：LLM 调用可能 2-5s，前端需独立 loading；建议 AI 解读与主体并行返回（或后置加载）
2. **4h 数据量**：plan 拉 1000 根，TV bridge 单次可给 5000，无问题；但 yahoo 股票数据可能不足，需 `_require_enough_bars` 兜底
3. **position 配置缺失**：未配置资金的用户必须有降级 UI（提示 + 示例），不能白屏
4. **决策引擎阈值**：confidence 权重、偏离度 15%、新鲜度窗口 3/12 根 —— 均提取为常量（后续可进 `TuningConstants` 风格配置，或本模块顶部常量 + 注释）
5. **futures 数据**：RSI 策略 schema 仍限 binance spot + yahoo；若后续要支持 U 本位合约 4h，需放开 `rsi_trend_schemas.py` 并确认 TV bridge 的 `BINANCE:SYMBOL` 前缀（另行评估，不在本次范围）

---

## 8. 交付物清单（最终状态）

- [ ] `app/domain/rsi_trend_plan.py`（数据结构 + 决策引擎）
- [ ] `app/services/rsi_trend_plan_service.py`（编排）
- [ ] `app/api/rsi_trend_routes.py`（+`/plan` 路由）
- [ ] `frontend/components/rsi-strategy/analysis-panel.tsx` + 5 个子卡片
- [ ] `frontend/lib/api-rsi-strategy.ts`（+类型 +analyzeRsiTrend）
- [ ] `frontend/hooks/use-rsi-strategy.ts`（+plan 状态）
- [ ] `frontend/app/rsi-strategy/page.tsx`（tab 替换）
- [ ] 测试：domain / service / api / 组件 / e2e
