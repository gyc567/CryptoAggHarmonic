# Pyharmonics-GPT 后端 Go 迁移评估 + 重构设计方案

> 日期: 2026-07-23
> 当前架构: Python/Flask + Supabase + Redis/RQ
> 目标架构: AI-Native Quantitative Trading Intelligence Engine
>
> 审计修订: 2026-07-23（基于代码事实核对）
> - 修正端点统计（实际 18 个，原写 14 个）
> - 修正 pyharmonics 依赖描述（PyPI 开源包，非闭源 wheel）
> - 补充图表渲染（Plotly/Kaleido）迁移障碍——Go 无等价物
> - 修正行动项中仓库路径矛盾（新 repo vs monorepo）
> - 新增：8.4 替代方案对比、8.5 风险清单、8.6 决策建议
> - 新增：认证/配额/取消机制等被遗漏模块的迁移说明
> - 新增：3.7 Risk Engine 止损体系（PRZ + Invalidation Point + ATR，Harmonic 交易核心）
> - 终审：统一 Phase 1 浮点验收标准、2.1 目录与行动项路径、成本表总计；新增文首 TL;DR

---

## TL;DR 最终方案

**决策：分两步走，不做一次性全量重写。**

1. **第一步（4-6 周，方案 B 混合架构）**：只把纯数学层（ZigZag → Fibonacci → Harmonic + **Risk Engine**）迁为 Go 微服务，放在本 repo `backend/go/`。Python 主服务通过 `PATTERN_ENGINE_URL` 零重构接入，`POST /detect` 响应直接带 **PRZ + Invalidation Point + 三档 ATR 止损**，Python 侧不做二次风险计算。
2. **第二步（条件触发，方案 C/D）**：仅当实测触发条件满足（Vibe SSE 并发瓶颈 / Python 服务账单占比 > 40% / Go 引擎稳定运行 1 个月），才迁 API 与 Vibe，且 Phase 3 前必须做 1-2 天 `openai-go` spike。

三条不可妥协的设计红线：
- **止损 = PRZ 失效位 + ATR 缓冲**，禁止固定百分比止损，禁止 AI 输出裸止损价格（见 3.7）
- **图表渲染永留 Python**（Plotly/Kaleido 无 Go 等价物），中期改前端渲染彻底解耦（见 3.8）
- **任何端点可独立切回 Python**（Strangler Fig 路径切流），任何时刻可回滚（见 Phase 6）

---

## 战略定位升级

当前项目定位只是 **Harmonic Pattern Scanner**。正确的目标应该是：

> **AI-Native Quantitative Trading Intelligence Engine**

```
市场数据 (Market Data)
    │
    ▼
技术分析引擎 (Technical Analysis Engine)
    │
    ▼
Harmonic Pattern Engine  ←── 纯数学，Go 实现
    │
    ▼
AI Reasoning Layer       ←── Multi-Agent，Go 实现
    │
    ▼
Risk Decision Engine     ←── Go 实现（纯数学止损 RiskEngine + AI 决策融合，见 3.7）
    │
    ▼
Trading Execution
```

最终产品形态：
- TradingView 的图表能力
- Harmonic Scanner 的模式识别
- ChatGPT 的分析推理
- Quant Engine 的回测能力

---

## 1. 当前代码审计

### 1.1 规模总览

| 维度 | 数值 |
|------|------|
| Python 后端文件数 | 49 个 .py 模块 |
| Python 后端代码量 | ~7,381 LOC（app/ 目录） |
| 测试代码量 | ~4,141 LOC（19 个文件） |
| Pydantic 模型数 | ~25 个 |
| API 端点数 | 18 个（SaaS 8 + Vibe 10） |
| 环境变量数 | 20+ 个（OpenAI/Supabase/Redis/Vibe 调参） |
| 数据库表 | 10 张 |
| 工具函数 | 6 个（vibe tools） |
| Vibe 模块代码量 | ~2,068 LOC（app/services/vibe/，占后端 28%） |

### 1.2 核心问题识别

#### 问题 1：Algorithm 和 AI 强耦合

当前架构中，`AnalysisOrchestrator` 直接调用 `query_openai`，导致 AI 层和算法层耦合。

```
当前错误设计：

Scanner → GPT
```

应该：

```
Pattern Engine (纯数学)
    ↓
AI Layer (解释和决策)
    ↓
Strategy (交易决策)
```

#### 问题 2：Pattern Engine 依赖交易逻辑

当前 `signal_engine.py` 混入了交易决策逻辑。Pattern 应该只负责检测，返回 `PatternEvent`，由独立的 Strategy 层决定是否交易。

#### 问题 3：缺少统一 Domain Model

当前 Pydantic 模型分散在 `domain/schemas.py` 和 `domain/vibe_schemas.py`，没有形成统一的 Ubiquitous Language。

#### 问题 4：pyharmonics 库是单点依赖

整个系统依赖 `pyharmonics`（PyPI 开源包，当前钉死 `==1.4.3`），无法在 Go 中直接使用，且版本演进受其上游节奏约束。它的传递依赖链还有历史包袱：requirements 中为兼容它被迫钉死 `alpaca-trade-api==3.2.0` / `yfinance==0.2.57` / `websockets==10.4`。

#### 问题 5：图表渲染依赖 Plotly + Kaleido（迁移最大障碍）

当前图表由 pyharmonics 的 `HarmonicPlotter` 生成 Plotly figure，经 Kaleido 序列化为 PNG（`app/infra/pyharmonics_adapter.py:185-213`）。Go 生态没有等价的 Plotly/Kaleido 渲染能力，该链路无法直接迁移，必须保留 Python 渲染服务或更换前端渲染方案（见 3.8）。

---

## 2. 目标架构设计

### 2.1 项目结构

```
backend/go/
├── cmd/
│   ├── api-server/              # HTTP API 服务
│   ├── scanner/                 # 离线扫描工具
│   └── backtester/              # 回测引擎
├── internal/
│   ├── domain/                  # 核心领域模型（与框架无关）
│   │   ├── candle.go            # K线数据
│   │   ├── swing.go             # 摆点定义
│   │   ├── pattern.go           # 形态事件
│   │   ├── prz.go               # 潜在反转区
│   │   ├── signal.go            # 交易信号
│   │   ├── enums.go             # 枚举类型
│   │   └── errors.go            # 领域错误
│   ├── marketdata/              # 市场数据层
│   │   ├── provider.go          # 接口定义
│   │   ├── binance.go           # Binance 实现
│   │   ├── yahoo.go             # Yahoo 实现
│   │   └── cache.go             # 本地缓存
│   ├── zigzag/                  # ZigZag 引擎
│   │   ├── engine.go            # 核心算法
│   │   └── params.go            # 参数配置
│   ├── fibonacci/               # 斐波那契引擎
│   │   ├── ratios.go            # 比率定义
│   │   ├── levels.go            # 价位计算
│   │   └── prz.go               # PRZ 计算
│   ├── harmonic/                # 谐波模式引擎
│   │   ├── detector.go          # 接口定义
│   │   ├── patterns/
│   │   │   ├── gartley.go
│   │   │   ├── bat.go
│   │   │   ├── crab.go
│   │   │   ├── butterfly.go
│   │   │   ├── shark.go
│   │   │   └── cypher.go
│   │   ├── validator.go         # 有效性验证
│   │   └── rule_engine.go       # 规则引擎
│   ├── indicator/               # 技术指标
│   │   ├── atr.go
│   │   ├── rsi.go
│   │   ├── ema.go
│   │   ├── macd.go
│   │   └── volume.go
│   ├── strategy/                # 策略层
│   │   ├── engine.go            # 策略引擎
│   │   ├── risk.go              # 风险管理
│   │   └── position.go          # 仓位管理
│   ├── ai/                      # AI Agent 层
│   │   ├── agent.go             # Agent 接口
│   │   ├── pattern_analyst.go   # Pattern Analyst Agent
│   │   ├── context_agent.go     # Market Context Agent
│   │   ├── risk_agent.go        # Risk Agent
│   │   └── reasoning.go         # Reasoning Engine
│   ├── execution/               # 执行层
│   │   ├── broker.go            # 券商接口
│   │   ├── binance.go           # Binance 实现
│   │   └── sim.go               # 模拟交易
│   ├── storage/                 # 存储层
│   │   ├── candle_store.go      # K线存储
│   │   ├── pattern_store.go     # 形态存储
│   │   └── trade_store.go       # 交易记录存储
│   ├── infra/                   # 基础设施
│   │   ├── supabase/            # Supabase 客户端
│   │   ├── redis/               # Redis 客户端
│   │   └── llm/                 # LLM 提供者
│   └── vibe/                    # Vibe 对话系统
│       ├── orchestrator.go
│       ├── tools.go
│       └── stream.go
├── pkg/
│   ├── exchange/                # 交易所通用接口
│   ├── logger/                  # 日志封装
│   └── config/                  # 配置管理
├── configs/
│   └── patterns.yaml            # Pattern 规则 DSL
├── migrations/                  # 数据库迁移
│   └── 001_initial.sql
├── go.mod
└── go.sum
```

### 2.2 核心领域模型

```go
// Candle represents a single OHLCV candle
type Candle struct {
    Time   time.Time
    Open   float64
    High   float64
    Low    float64
    Close  float64
    Volume float64
}

// SwingPoint represents a ZigZag swing point
type SwingPoint struct {
    Index  int
    Price  float64
    Type   SwingType // High or Low
    Strength float64
}

// PatternEvent is the core domain event from pattern detection
type PatternEvent struct {
    ID          string
    Symbol      string
    Timeframe   string
    Pattern     PatternType  // Gartley, Bat, Crab, etc.
    Direction   Direction    // Bullish or Bearish
    SwingPoints []SwingPoint // X, A, B, C, D
    PRZ         PRZ
    Confidence  float64
    DetectedAt  time.Time
    RawData     interface{} // Original pattern data from pyharmonics
}

// PRZ represents the Potential Reversal Zone
// 核心原则：D 点 ≠ 止损点。D 点是入场观察区域，PRZ 外才是交易失效区域。
type PRZ struct {
    Upper             float64
    Lower             float64
    TP1               float64 // Take Profit 1（对应 C 点区域）
    TP2               float64 // 对应 A 点区域
    TP3               float64
    InvalidationPoint float64 // 形态失效点（如 1.0 XA），价格突破则结构破坏
    Strength          float64
}

// StopMode 止损档位（见 3.7）
type StopMode string

const (
    StopConservative StopMode = "conservative" // PRZ 外 + 1×ATR，胜率高、RR 低
    StopStandard     StopMode = "standard"     // D 点外 0.5~1×ATR（推荐默认）
    StopAggressive   StopMode = "aggressive"   // D 点附近小止损，RR 高、易被扫
)

// Signal is the output of the Strategy Engine
type Signal struct {
    ID            string
    PatternEvent  *PatternEvent
    Decision      Decision      // LONG, SHORT, SKIP
    EntryZone     [2]float64    // 入场区间（PRZ 内），而非单一价格
    StopLoss      float64       // = PRZ外 + ATR 缓冲（由 RiskEngine 计算）
    StopMode      StopMode
    StopReason    string        // 可解释：如 "Price broke PRZ and invalidated Gartley structure"
    InvalidationPoint float64    // 结构失效点（与止损联动）
    ATRAtEntry    float64       // 入场时 ATR，复盘与滑点分析用
    Targets       []Target
    RiskReward    float64
    PositionSize  float64
    Confidence    float64
    Reasoning     string
    CreatedAt     time.Time
}
```

### 2.3 关键接口设计

```go
// MarketDataProvider is the interface for market data sources
type MarketDataProvider interface {
    GetCandles(ctx context.Context, symbol, timeframe string, limit int) ([]Candle, error)
    GetHistorical(ctx context.Context, symbol, timeframe string, start, end time.Time) ([]Candle, error)
}

// PatternDetector is the interface for harmonic pattern detection
type PatternDetector interface {
    Detect(candles []Candle) ([]PatternEvent, error)
    Validate(event *PatternEvent) (bool, string) // returns valid, reason
}

// ZigZagEngine extracts swing points from OHLC data
type ZigZagEngine interface {
    Compute(candles []Candle) []SwingPoint
}

// FibonacciEngine provides Fibonacci calculations
type FibonacciEngine interface {
    Retracement(a, b float64) []FibLevel
    Extension(a, b, c float64) []FibLevel
    PRZ(swingPoints []SwingPoint, pattern PatternType) (*PRZ, error)
}

// StrategyEngine makes trading decisions
type StrategyEngine interface {
    Evaluate(event *PatternEvent, context *MarketContext) (*Signal, error)
}

// RiskEngine computes structure-based stop loss (见 3.7)
// 设计约束：止损必须可解释、可复算，不允许 AI 直接拍一个价格
type RiskEngine interface {
    // ComputeStop 基于 PRZ 失效位 + ATR 波动缓冲计算止损
    ComputeStop(event *PatternEvent, atr float64, mode StopMode) (stop float64, reason string)
    // Invalidated 判断当前价格是否已突破形态失效点
    Invalidated(event *PatternEvent, currentPrice float64) bool
    // PositionSize 按固定风险百分比计算仓位
    PositionSize(accountEquity, riskPct, entry, stop float64) float64
}

// AIReviewer provides AI-based pattern analysis
type AIReviewer interface {
    AnalyzePattern(ctx context.Context, event *PatternEvent) (*AIReview, error)
    ExplainSignal(ctx context.Context, signal *Signal) (string, error)
}

// AIReview is the output of AI pattern analysis
type AIReview struct {
    Interpretation string
    Confidence     float64
    KeyFactors     []string
    RiskFactors    []string
    MarketContext  string
}
```

---

## 3. 模块分层设计

### 3.1 Layer 1: Market Data Layer（市场数据层）

```
职责：统一市场数据获取接口
位置：internal/marketdata/

支持：
- Binance (原生 REST API)
- Yahoo Finance
- 可扩展：OKX, Coinbase, 股票 API
```

```go
type MarketDataService struct {
    providers map[string]MarketDataProvider
    cache     *cache.Cache
}

func (s *MarketDataService) GetCandles(symbol, tf string, limit int) ([]Candle, error) {
    provider := s.providers[s.detectExchange(symbol)]
    candles, err := provider.GetCandles(symbol, tf, limit)
    if err != nil {
        return nil, err
    }
    s.cache.Set(symbol, tf, candles)
    return candles, nil
}
```

### 3.2 Layer 2: ZigZag Engine（锯齿形引擎）

```
职责：从 OHLC 数据中提取摆点（X, A, B, C, D）
位置：internal/zigzag/

这是 Harmonic Pattern 的核心前置步骤。
```

核心算法参数：
- `Deviation`: 过滤微小波动（默认 0.05）
- `Depth`: 最少 K 线数（默认 12）
- `Backstep`: 相邻同向摆点最小间距（默认 3）

### 3.3 Layer 3: Fibonacci Engine（斐波那契引擎）

```
职责：独立计算斐波那契比率和价位
位置：internal/fibonacci/

注意：不要把 Fibonacci 逻辑写在 Pattern 中
```

```go
type FibRatio struct {
    Name      string
    Value     float64
    Tolerance float64
}

// 标准比率
var StandardRatios = []FibRatio{
    {"0.382", 0.382, 0.03},
    {"0.500", 0.500, 0.02},
    {"0.618", 0.618, 0.03},
    {"0.786", 0.786, 0.05},
    {"0.886", 0.886, 0.03},
    {"1.272", 1.272, 0.05},
    {"1.414", 1.414, 0.05},
    {"1.618", 1.618, 0.03},
}
```

### 3.4 Layer 4: Harmonic Pattern Engine（谐波模式引擎）

```
职责：检测 Harmonic Pattern
位置：internal/harmonic/

设计原则：
1. Pattern Detection 和 Pattern Validation 分离
2. 使用 YAML 规则 DSL，而非硬编码
3. Pattern 结果是 PatternEvent，不包含交易决策
```

#### Pattern Rule Engine (YAML DSL)

```yaml
# configs/patterns.yaml
patterns:
  Gartley:
    description: "Most reliable harmonic pattern"
    rules:
      - name: AB_XA
        type: retracement
        target: 0.618
        tolerance: 0.03
      - name: BC_AB
        type: retracement
        target: [0.382, 0.886]
        tolerance: 0.05
      - name: CD_BC
        type: extension
        target: 1.272
        tolerance: 0.05
      - name: AD_XA
        type: retracement
        target: 0.786
        tolerance: 0.05
    prz:
      TP1: 0.382        # 第一目标：C 点区域
      TP2: 0.618        # 第二目标：A 点区域
      TP3: 1.272
    invalidation:       # 形态失效规则（止损的结构锚点，见 3.7）
      beyond: XA_100    # 价格突破 1.0 XA（X 点）则结构破坏
      atr_buffer:       # 各档止损的 ATR 缓冲倍数
        conservative: 1.0   # PRZ 外 + 1×ATR
        standard: 0.5       # D 点外 0.5~1×ATR（默认）
        aggressive: 0.2     # D 点附近小止损

  Bat:
    rules:
      - name: AB_XA
        type: retracement
        target: 0.382
        tolerance: 0.03
      - name: BC_AB
        type: retracement
        target: [0.382, 0.500]
        tolerance: 0.05
      - name: CD_BC
        type: extension
        target: 1.618
        tolerance: 0.05
      - name: AD_XA
        type: retracement
        target: 0.886
        tolerance: 0.03
```

### 3.5 Layer 5: AI Agent Layer（AI 代理层）

```
职责：Multi-Agent 架构做交易决策
位置：internal/ai/

Agent 设计：
1. Pattern Analyst - 解释形态为什么成立
2. Market Context Agent - 分析市场环境（趋势、成交量、波动率）
3. Risk Agent - 最终决策：是否交易、仓位、止损、目标
```

```go
// AIReviewer implements multi-agent analysis
type AIReviewer struct {
    patternAnalyst  PatternAnalyst
    contextAgent    MarketContextAgent
    riskAgent       RiskAgent
    llmProvider     LLMProvider
}

type PatternAnalyst struct {
    llm LLMProvider
}

// AnalyzePattern explains why a pattern is valid
func (a *PatternAnalyst) Analyze(ctx context.Context, event *PatternEvent) (*PatternAnalysis, error) {
    prompt := fmt.Sprintf(`
分析以下 Harmonic Pattern：

形态: %s
方向: %s
置信度: %.2f
X点: %.2f
A点: %.2f
B点: %.2f
C点: %.2f
D点: %.2f
PRZ区间: [%.2f, %.2f]

请解释：
1. 这个形态成立的理由
2. 关键验证点
3. 可能失败的情形
`, event.Pattern, event.Direction, event.Confidence,
        event.SwingPoints[0].Price, event.SwingPoints[1].Price,
        event.SwingPoints[2].Price, event.SwingPoints[3].Price,
        event.SwingPoints[4].Price, event.PRZ.Lower, event.PRZ.Upper)

    return a.llm.Chat(ctx, prompt)
}

type MarketContextAgent struct {
    llm LLMProvider
}

// AnalyzeContext evaluates market conditions
func (a *MarketContextAgent) Analyze(ctx context.Context, candles []Candle, pattern *PatternEvent) (*ContextAnalysis, error) {
    // 分析趋势、成交量、波动率、相关性
}

type RiskAgent struct {
    llm LLMProvider
}

// EvaluateRisk makes the final trading decision
// 注意：AI 只输出决策/档位/理由，止损价格由 RiskEngine 计算（见 3.7 的 AI 输出契约）
func (a *RiskAgent) Evaluate(ctx context.Context, pattern *PatternEvent, context *ContextAnalysis) (*RiskDecision, error) {
    // 输出: LONG/SHORT/SKIP, stop_mode, 仓位建议, 理由
    // 禁止输出: 裸止损价格（不可复算）
}
```

### 3.6 Layer 6: Strategy Engine（策略引擎）

```
职责：整合 Pattern Detection + AI Review → Signal
位置：internal/strategy/

注意：这里只做策略执行，不做形态检测
```

```go
type StrategyEngine struct {
    detector     PatternDetector
    aiReviewer   AIReviewer
    riskManager  RiskManager
    positionSizer PositionSizer
}

func (e *StrategyEngine) Evaluate(symbol, timeframe string, candles []Candle) (*Signal, error) {
    // 1. Pattern Detection
    patterns, err := e.detector.Detect(candles)
    if err != nil {
        return nil, err
    }

    // 2. AI Analysis
    for _, pattern := range patterns {
        aiReview := e.aiReviewer.Analyze(pattern)

        // 3. Risk Decision（止损价格由 RiskEngine 计算，AI 只给决策和档位，见 3.7）
        decision := e.riskManager.Evaluate(pattern, aiReview)
        if decision.Decision == SKIP {
            continue
        }

        // 4. Build Signal（强制校验最低 RR ≥ 2:1，不满足则跳过）
        signal := e.buildSignal(pattern, decision)
        return signal, nil
    }

    return nil, nil // No valid signals
}
```

### 3.7 Layer 7: Risk Engine（止损引擎，Harmonic 交易核心）

```
职责：基于结构（而非价格百分比）计算止损与仓位
位置：internal/strategy/risk.go

一句话原则：
  D 点 ≠ 止损点。D 点是入场观察区域，PRZ 外才是交易失效区域。
  止损 = PRZ 失效位 + 市场波动空间（ATR）

为什么独立成层：
  Harmonic Trading 最容易学的是画 XABCD，最难的是止损。
  大多数人亏损不是找不到形态，而是止损放错导致连续小亏或一次大亏。
  止损逻辑必须是纯数学、可单测、可复算的，不依赖 LLM。
```

#### 设计要点

**1. 禁止固定百分比止损**

不同市场波动不同（BTC 日波 5%、黄金 1%、股票 3%），止损必须基于**结构 + ATR**，不允许 `跌 3% 止损` 这类规则进入代码库。

**2. 计算流水线（第一版只实现这个，优先级高于堆形态数量）**

```
PatternEvent（含 PRZ）
    │
    ▼
Invalidation Point    ← 形态失效点：价格突破则结构破坏
    │                    （Gartley: 1.0 XA；由 patterns.yaml 的 invalidation.beyond 声明）
    ▼
ATR Adjustment        ← 按 StopMode 加波动缓冲，自动适应市场
    │
    ▼
Stop Loss + StopReason ← 输出价格 + 可解释原因
```

**3. 三档止损（StopMode）**

| 档位 | 规则 | 特点 | 适用 |
|------|------|------|------|
| Conservative | PRZ 外 + 1×ATR | 胜率高、RR 低 | 新手/默认回测基准 |
| Standard（默认） | D 点外 0.5~1×ATR | 平衡 | 大多数信号 |
| Aggressive | D 点外 ~0.2×ATR | RR 高、易被扫 | 有确认信号（K线反转/RSI背离/缩量）时 |

```go
// ComputeStop 实现示例（Bullish 形态）
func (e *RiskEngine) ComputeStop(event *PatternEvent, atr float64, mode StopMode) (float64, string) {
    prz := event.PRZ
    switch mode {
    case StopConservative:
        stop := math.Min(prz.Lower, prz.InvalidationPoint) - atr*1.0
        return stop, fmt.Sprintf("Price broke PRZ [%.2f, %.2f] + 1xATR buffer; %s structure invalidated",
            prz.Lower, prz.Upper, event.Pattern)
    case StopAggressive:
        stop := prz.Lower - atr*0.2
        return stop, fmt.Sprintf("Tight stop below D at PRZ lower bound %.2f", prz.Lower)
    default: // StopStandard
        stop := prz.Lower - atr*0.5
        return stop, fmt.Sprintf("Price broke PRZ lower %.2f with 0.5xATR buffer; %s invalidated",
            prz.Lower, event.Pattern)
    }
}
// Bearish 形态取镜像（Upper + buffer），由 Direction 驱动
```

**4. 止盈采用结构目标，而非固定倍数**

谐波的优势不是高胜率，而是小止损大目标。TP 直接锚定结构位：
- TP1 = C 点区域，TP2 = A 点区域（patterns.yaml 的 prz.TP1/TP2 即此意）
- 部分止盈：TP1 平 50%，剩余移动止损到成本价
- 信号必须满足最低 RR（建议 ≥ 2:1）才放行，在 `buildSignal` 里强制校验

**5. AI 输出契约：可解释，不允许直接拍价格**

Risk Agent / Signal 的 AI 输出必须是结构化 JSON，止损由 RiskEngine 计算，AI 只给决策和理由：

```json
{
  "entry_zone": [60000, 60200],
  "prz_zone": [59800, 60300],
  "invalidation_point": 59000,
  "stop_mode": "standard",
  "stop_reason": "Price broke PRZ and invalidated Gartley structure"
}
```

反模式（禁止）：`{"stop": 59000}` —— AI 直接输出裸价格，不可复算、无法审计。

### 3.8 Layer 8: Chart Rendering（图表渲染，Python Sidecar）

```
职责：Harmonic 图表 PNG 渲染
位置：保留独立 Python 微服务（不迁移）

原因：Plotly + Kaleido 在 Go 中无等价物，重写成本高、收益低。
```

方案：
1. 将现有 `app/services/chart.py` + `pyharmonics_adapter.py` 的渲染部分抽成独立的 `chart-renderer` Flask/FastAPI 微服务（单端点 `POST /render`）
2. Go 后端通过 HTTP 调用，配合本地/Redis 缓存（图表内容可由 symbol+timeframe+pattern hash 做缓存键）
3. 该服务资源消耗大（Kaleido 需要 headless Chromium），独立部署便于单独扩缩容
4. 中期可评估前端渲染替代：把形态点位数据直接下发给前端，用 Lightweight Charts / ECharts 在浏览器端画，彻底下线 Kaleido

---

## 4. 数据库设计（PostgreSQL + TimescaleDB）

### 4.1 核心表结构

```sql
-- Candles with TimescaleDB hypertables
CREATE TABLE candles (
    id BIGSERIAL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18,8) NOT NULL,
    high NUMERIC(18,8) NOT NULL,
    low NUMERIC(18,8) NOT NULL,
    close NUMERIC(18,8) NOT NULL,
    volume NUMERIC(18,8) NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

SELECT create_hypertable('candles', 'timestamp');

-- Patterns detected
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    x_price NUMERIC(18,8),
    a_price NUMERIC(18,8),
    b_price NUMERIC(18,8),
    c_price NUMERIC(18,8),
    d_price NUMERIC(18,8),
    prz_upper NUMERIC(18,8),
    prz_lower NUMERIC(18,8),
    invalidation_point NUMERIC(18,8), -- 形态失效点（与 signals 表联动审计）
    confidence NUMERIC(5,4),
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timeframe, pattern_type, detected_at)
);

-- Trading signals
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id UUID REFERENCES patterns(id),
    decision TEXT NOT NULL, -- LONG, SHORT, SKIP
    entry_zone_low NUMERIC(18,8),
    entry_zone_high NUMERIC(18,8),
    stop_loss NUMERIC(18,8),
    stop_mode TEXT NOT NULL, -- conservative, standard, aggressive
    stop_reason TEXT,        -- 可解释止损原因（审计必需）
    invalidation_point NUMERIC(18,8),
    atr_at_entry NUMERIC(18,8),
    tp1 NUMERIC(18,8),
    tp2 NUMERIC(18,8),
    tp3 NUMERIC(18,8),
    risk_reward NUMERIC(5,2),
    position_size NUMERIC(18,8),
    ai_reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades executed
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID REFERENCES signals(id),
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price NUMERIC(18,8),
    exit_price NUMERIC(18,8),
    quantity NUMERIC(18,8),
    pnl NUMERIC(18,8),
    status TEXT NOT NULL, -- OPEN, CLOSED, CANCELLED
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

-- Backtests
CREATE TABLE backtests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    config JSONB NOT NULL,
    results JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.2 与现有 Supabase 的关系（补充）

当前生产数据库是 **Supabase 托管 Postgres**（含 Auth、quota ledger、audit log、vibe session 等 10 张表）。引入 TimescaleDB 需要明确：

1. **不要新建独立数据库**。Supabase 支持启用 TimescaleDB 扩展（`CREATE EXTENSION IF NOT EXISTS timescaledb`），优先在同一实例上启用，避免双库运维。
2. **存量表保留在 Supabase**：auth/quota/session/audit 等继续用 Supabase REST + RLS；只有 `candles` / `patterns` / `signals` / `trades` 等时序新表走 Go 服务直连 PG（`pgx`）。
3. **数据迁移**：现有 10 张表无需迁移；TimescaleDB hypertable 只用于新增的 candles 表。candles 初期可以不落库（直接从交易所 API 拉取 + Redis 缓存），等回测引擎（Phase 4）真正需要历史数据时再建 hypertable，避免提前优化。
4. 注意 Supabase 免费/低配档位对扩展和连接数的限制，直连 PG 需配连接池上限（`pgxpool`，建议 max 10）。

### 4.3 被遗漏的现有模块（必须在 Go 侧覆盖）

原设计遗漏了以下已在生产使用的模块，Go 侧必须等价实现：

| 现有模块 | 职责 | Go 迁移方案 |
|---------|------|------------|
| `app/api/auth.py` | Supabase JWT 验证（@require_auth） | 从 Supabase JWKS endpoint 拉公钥，用 `github.com/golang-jwt/jwt/v5` 验证 RS256；保留 `DISABLE_AUTH` dev bypass |
| quota ledger（`consume_ledger_quota`） | 用户配额扣减 | 继续走 Supabase REST/RPC，Go 侧做薄客户端；迁移期与 Python 共用同一 ledger 表 |
| `app/api/vibe_routes.py` 的取消机制 | RQ `send_stop_job_command` + Redis 取消标志 | Go 侧用 `context.CancelFunc`（内存注册表 runID→cancel）+ Redis Pub/Sub 广播，支持多实例部署时的跨实例取消 |
| Vibe 调参环境变量（`VIBE_MAX_ITERATIONS` 等 8 个） | 运行时行为调优 | `internal/pkg/config` 集中声明，保持同名环境变量，避免运维切换成本 |
| `/query` 旧端点 + `/` chat_ui | 旧版 GPT function-calling | **建议废弃不迁移**，迁移前用访问日志确认无流量后下线 |
| `/api/history`、`/api/analysis/<id>` | 占位端点（返回空/404） | 不迁移，待产品确认需求后再实现 |

---

## 5. Vibe 对话系统设计

### 5.1 Vibe 在新架构中的位置

Vibe 是用户与 AI Trading Engine 对话的界面。它调用 AI Agent Layer 获取分析结果。

```
User → Vibe (Frontend) → Vibe API (Go) → AI Agent Layer → Pattern Engine + LLM
```

### 5.2 Vibe Tools（对应 Python 实现）

| Tool | 职责 | 调用链 |
|------|------|--------|
| `analyze_harmonic` | 分析当前市场形态 | PatternDetector → AIReviewer |
| `build_trade_signal` | 生成交易信号 | StrategyEngine |
| `position_check` | 检查仓位和风险 | RiskManager |
| `backtest_signal` | 回测信号 | BacktestEngine |
| `explain_market` | 市场解释 | AIReviewer |
| `save_to_journal` | 保存交易日志 | TradeStore |

### 5.3 SSE 流式（Go 原生优势）

```go
func (h *VibeHandler) StreamEvents(runID string, w http.ResponseWriter, r *http.Request) {
    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "SSE not supported", http.StatusInternalServerError)
        return
    }

    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")

    events := h.eventStore.Subscribe(runID)
    for {
        select {
        case <-r.Context().Done():
            return
        case evt := <-events:
            data, _ := json.Marshal(evt)
            fmt.Fprintf(w, "event: %s\ndata: %s\n\n", evt.Type, data)
            flusher.Flush()
        }
    }
}
```

---

## 6. 迁移路线（Phase-by-Phase）

### Phase 0: Golden Test + Pattern Fixtures（1-2 周）

**目标**：建立回归测试基准，防止后续重写破坏现有逻辑

修正说明：Phase 0 是整个迁移的**质量地基**，原方案只有一个空壳代码片段，需要补强为三层：

```bash
# 1. Pattern 层：导出历史形态作为算法 Golden Tests
mkdir -p testdata/fixtures
# 注意：fixtures 必须连同输入 candles 一起导出（candles → pattern 的完整输入输出对），
# 只导出 pattern 结果无法做确定性重放。建议每个 (symbol, timeframe) 导出：
#   - candles.json（OHLCV 输入）
#   - patterns.json（pyharmonics 输出，含 swing points / PRZ / confidence）
# 目标 100+ 个有代表性的输入输出对即可，10000 个无必要且维护成本高。

# 2. API 层：契约测试。对现有 8 个 SaaS 端点录制请求/响应快照
#    （可用 pytest + vcr.py 或直接 curl 录制），Go 版 API 必须逐字节兼容。

# 3. Vibe 层：导出典型会话的 tool-call 序列（vibe_traces/ 已有 trace 落盘能力，
#    VIBE_TRACE_DIR 可直接复用），作为 Go 版 orchestrator 的行为基准。

# 4. 导出 prompt 模板
cp prompt_intent.yaml configs/prompt_template.yaml
```

交付物：
- `testdata/fixtures/` 包含 candles+patterns 输入输出对（100+ 组）
- API 契约测试快照（可在 CI 中对 Go 服务回放）
- `configs/prompt_template.yaml` 作为 AI prompt 模板
- 现有 Python 后端可继续运行，不冻结

### Phase 1: Go Core - Market Data + ZigZag + Fibonacci + Pattern（2-4 周）

**目标**：用 Go 实现纯数学算法层，无外部依赖

前置提醒：Go 版算法与 pyharmonics 输出**不可能 bitwise 一致**（浮点累加顺序、ZigZag 边界处理差异）。验收标准应定义为"业务等价"而非"完全相等"：
- 形态类型、方向一致率 ≥ 99%
- PRZ/TP/SL 价格误差在 `InDelta(price * 0.001)` 以内
- 差异案例必须逐个归类原因（边界 candle 处理 / 浮点 / 参数语义），记录在 `testdata/KNOWN_DIFFS.md`

```
internal/
├── domain/
├── marketdata/
├── zigzag/
├── fibonacci/
├── harmonic/
├── indicator/            # ATR 是 Risk Engine 的前置依赖
└── strategy/
    └── risk.go           # Risk Engine 随 Phase 1 一起交付（方案 B 要求）
```

关键交付物：
```go
// 验证 Go 实现与 Python 输出业务等价
func TestPatternDetection(t *testing.T) {
    candles := loadFixture("btc_4h_2024.json")
    
    // Python 输出
    pythonResult := loadFixture("gartley_btc_4h.json")
    
    // Go 输出
    goResult, _ := detector.Detect(candles)
    
    // 断言业务等价（与上方验收标准一致：相对误差 0.1%）
    assert.Equal(t, pythonResult.Pattern, goResult.Pattern)
    assert.InDelta(t, pythonResult.PRZ.Upper, goResult.PRZ.Upper, pythonResult.PRZ.Upper*0.001)
}
```

### Phase 2: Go API - Scanner Service（1-2 周）

**目标**：用 Go 实现 `/api/analyze` 等端点

```
cmd/api-server/
├── main.go
└── internal/
    ├── api/
    │   ├── router.go
    │   ├── handlers/
    │   └── middleware/
    └── infra/
        ├── supabase/
        └── redis/
```

关键交付物：
- `/api/health`
- `/api/markets`
- `/api/analyze` → 调用 Go Pattern Engine
- `/api/charts/<name>.png` → **反向代理到 chart-renderer Python 微服务**（见 3.8）
- JWT 认证中间件 + quota ledger 客户端（见 4.3，原方案遗漏）

### Phase 3: AI Agent + Vibe（2-3 周）

**目标**：Vibe Multi-Agent 系统用 Go 重写

```
internal/ai/
├── agent.go
├── pattern_analyst.go
├── context_agent.go
└── risk_agent.go

internal/vibe/
├── orchestrator.go
├── tools/
└── stream.go
```

关键交付物：
- Vibe SSE streaming（Go 原生）
- 6 个 Tool 实现
- LLM 集成（OpenAI/MiniMax）
- 取消机制（context + Redis Pub/Sub，见 4.3）

风险提示：Go 的 LLM 生态（tool calling、structured output、streaming 的 SDK 成熟度）明显弱于 Python。`openai-go` 官方 SDK 已可用，但 MiniMax 等国产模型需手写 HTTP 客户端。这是全文档中**技术风险最高的 Phase**，建议：
1. 先用 1-2 天做 spike：用 `openai-go` 实现一个带 tool calling 的最小 agent 循环，验证可行性后再排期
2. 如 spike 不顺，Vibe 层保留 Python 是可接受的终态（见 8.4 方案 C）

### Phase 4: Backtesting Engine（1-2 周）

**目标**：纯 Go 回测引擎

```
internal/backtest/
├── engine.go
├── strategy.go
└── metrics.go
```

### Phase 5: Trading Execution（可选，1-2 周）

**目标**：连接 Binance 等券商

```
internal/execution/
├── broker.go
├── binance.go
└── sim.go
```

### Phase 6: 部署（1 周）

修正说明：当前生产是**单容器 Docker（gunicorn，端口 5000）**，docker-compose 里不含 Redis/worker（RQ worker 依赖外部 Redis）。直接跳到 Cloud Run 跨度过大，建议分两步：

**Step 1（必做）：容器化 Go 服务，与现有 Python 服务并存**

```dockerfile
# 多阶段构建，最终镜像 < 20MB
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /bin/pyharmonics-api ./cmd/api-server

FROM gcr.io/distroless/static-debian12
COPY --from=build /bin/pyharmonics-api /pyharmonics-api
COPY configs/ /configs/
EXPOSE 8080
USER nonroot
ENTRYPOINT ["/pyharmonics-api"]
```

前端/网关按路径切流（Strangler Fig 模式）：
- `/api/markets`、`/api/analyze`、`/api/charts/*` → Go 服务（Phase 2 完成后）
- `/api/vibe/*`、`/query` → 仍走 Python 服务（Phase 3 完成后再切）
- 切流用 nginx/Caddy/云平台负载均衡的路径路由，**每个端点可独立切回**，这是回滚策略

**Step 2（可选）：迁 Cloud Run**

```bash
GOOS=linux GOARCH=amd64 go build -o pyharmonics-api ./cmd/api-server

gcloud run deploy pyharmonics-api \
  --image gcr.io/$PROJECT_ID/pyharmonics-api:latest \
  --platform managed \
  --region us-central1 \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 10
```

注意：Cloud Run 上 SSE 长连接按请求时长计费，`--min-instances 1` 保活即可；chart-renderer Python sidecar 需要单独服务（内存 ≥ 1Gi，含 Chromium）。

---

## 7. 技术栈选型

| 领域 | 选型 | 理由 |
|------|------|------|
| HTTP 框架 | `chi` | 轻量、Go style、无反射 |
| Redis | `go-redis/v9` | 最成熟，支持 Pipeline |
| Supabase | 直接 REST API | 官方 Go SDK 不完善 |
| LLM | `openai-go` 或直接 HTTP | Tool calling 需自己实现 |
| 指标计算 | `gonum/stat` + 手写 | go-talib 不完整 |
| 配置 | `gopkg.in/yaml.v3` | Pattern 规则用 YAML |
| 日志 | `log/slog` | Go 1.21+ 标准库 |
| 数据库 | PostgreSQL + TimescaleDB | 时序数据优化 |
| 部署 | Cloud Run | 冷启动快，按请求计费 |

---

## 8. 成本与收益

### 8.1 迁移成本

| 阶段 | 时间 | 人力 |
|------|------|------|
| Phase 0: Golden Tests | 1-2 周 | 1 人 |
| Phase 1: Go Core | 2-4 周 | 1-2 人 |
| Phase 2: Go API | 1-2 周 | 1 人 |
| Phase 3: AI Agent + Vibe | 2-3 周 | 1-2 人 |
| Phase 4: Backtest Engine | 1-2 周 | 1 人 |
| Phase 5: Execution | 1-2 周 | 1 人 |
| Phase 6: Deployment | 1 周 | 1 人 |
| **总计** | **9-16 周** | **1 人全职** |

> 上述估算未包含：双轨并行期的维护成本、前端 API 契约适配、chart-renderer 微服务拆分（+0.5-1 周）、Phase 3 spike（+0.5 周）。实际建议预留 **11-18 周**。Phase 0 已调整为 1-2 周。

### 8.2 收益分析

> 注意：下表为**估算值**（基于同类服务公开基准），非本项目实测。立项前建议先对现有 Python 服务做一次基线压测（冷启动、内存、并发上限），用真实数据校准。

| 维度 | Python | Go | 说明 |
|------|--------|-----|------|
| 冷启动 | ~2-5s | ~100ms | Cloud Run Go 二进制 |
| 并发 | 低（GIL） | 高（goroutine，1KB/stack） | 10x+ |
| 内存占用 | ~100MB+ | ~20MB | 1/5 成本 |
| 部署大小 | ~500MB | ~15MB | 30x 缩小 |
| SSE | 勉强（generator + GIL） | 原生（goroutine + channel） | vibe 体验提升 |
| 依赖安全 | pip 依赖树复杂 | go.sum，静态分析 | 供应链安全 |
| 算法性能 | 解释执行 | 编译执行 | 10x+ |

### 8.3 ROI 结论

**值得迁移的理由**：
1. 项目目标是 **AI-Native Quantitative Trading Intelligence Engine**，需要高性能
2. Vibe 是核心产品，SSE 体验至关重要
3. 长期需要自研量化算法库，摆脱 pyharmonics 依赖
4. 降低云计算成本 50%+

**不迁移的理由**：
1. 团队纯 Python 技术栈
2. 产品验证阶段，需要快速迭代
3. 2 个月开发时间可用于产品功能

### 8.4 替代方案对比（新增）

全量重写不是唯一选项。按投入从小到大：

| 方案 | 内容 | 投入 | 收益 | 风险 |
|------|------|------|------|------|
| **A. 不迁移，Python 优化** | Flask → FastAPI/async、RQ → arq、gunicorn → uvicorn、图表改前端渲染 | 2-3 周 | 并发 3-5x、SSE 改善、无语言切换成本 | 天花板低，GIL 仍在，算法性能无提升 |
| **B. 混合架构（推荐起步）** | 只迁 Pattern Engine（ZigZag/Fib/Harmonic，纯数学无外部依赖）为 Go 微服务，Python 保留 API/AI/Vibe | 4-6 周 | 算法性能 10x+、摆脱 pyharmonics 依赖、验证 Go 工具链 | 多一个服务要运维；进程间调用有 ~1ms 开销（对分钟级 K 线分析可忽略） |
| **C. 方案 B + Vibe/API 后置** | B 完成后，根据 spike 结果决定是否迁 API 与 Vibe | +4-6 周 | SSE/并发/部署收益全部兑现 | Go LLM 生态风险（见 Phase 3） |
| **D. 全量重写（原方案）** | Phase 0-6 全做 | 11-18 周 | 全部收益 | 双轨期长、重写期产品冻结、AI 层风险最高 |

### 8.5 风险清单与缓解（新增）

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| 1 | Go 算法输出与 pyharmonics 不一致，且差异难以归类 | 高 | 高 | Phase 0 输入输出对 fixtures + KNOWN_DIFFS.md（见 Phase 1 验收标准） |
| 2 | 图表渲染无法迁移（Plotly/Kaleido） | 确定 | 中 | 3.8 Python sidecar；中期改前端渲染彻底解耦 |
| 3 | Go LLM 生态不成熟（tool calling/MiniMax/structured output） | 中 | 高 | Phase 3 前做 spike；不行则 Vibe 留 Python（方案 C） |
| 4 | 重写期产品迭代冻结，双轨维护成本被低估 | 高 | 中 | Strangler Fig 按端点切流（Phase 6 Step 1），任何时刻可回滚 |
| 5 | 1 人全职 11-18 周的机会成本 | 确定 | 中 | 先执行方案 B（4-6 周），用真实性能数据决定是否继续 |
| 6 | goroutine 替代 RQ 丢任务（内存队列无持久化） | 中 | 中 | Vibe run 状态落 Supabase（现有 session store 已有），崩溃后可恢复/重放；或引入 `asynq`（Redis 持久队列） |
| 7 | Supabase Auth/quota 逻辑在 Go 侧行为不一致 | 低 | 高 | 4.3 节明确方案；迁移期 Python/Go 共用同一 ledger 表，契约测试覆盖 |
| 8 | TimescaleDB 引入新基础设施运维负担 | 低 | 低 | 4.2：candles 初期不落库，同一 Supabase 实例启用扩展 |

### 8.6 决策建议（新增）

**推荐：先执行方案 B（混合架构），把方案 D 降为有条件触发。**

理由：
1. 本文档识别的核心痛点（pyharmonics 单点依赖、算法/AI 耦合、缺统一 domain model）中，只有 "pyharmonics 依赖" 和 "算法性能" 必须通过 Go 解决；**耦合和 domain model 问题在 Python 里重构同样可解**。
2. 方案 B 以 1/3 的投入拿到 "摆脱 pyharmonics + 算法性能 10x" 这两个最确定的收益，且天然产出 Go 工具链与 fixtures 基础设施，后续升级到 C/D 无沉没成本。
3. SSE/部署密度等收益是否值回票价，取决于产品流量——当前阶段无实测数据支撑（8.2 为估算），先用 B 上线收集数据。

触发升级到方案 C/D 的条件（任一满足）：
- Vibe SSE 并发成为实测瓶颈（单实例 > 200 并发流）
- 云计算账单中 Python API 服务占比 > 40%
- 方案 B 的 Go Pattern Engine 已稳定运行 1 个月，团队 Go 信心建立

---

## 9. 立即行动项

> 按 8.6 的推荐（方案 B 优先），行动项已重排；如决定直接全量迁移（方案 D），Phase 顺序不变。
> 路径说明：Go 代码放在本 repo 的 `backend/go/`（monorepo），与前端/文档同仓，2.1 节目录树已按此统一。

**第一步（方案 B，4-6 周）**：

1. **创建 `backend/go/` 目录**，初始化 Go module
2. **实现 `internal/domain/candle.go`** 和 `internal/marketdata/binance.go`
3. **实现 `internal/zigzag/engine.go`**，验证与 pyharmonics 输出业务等价（见 Phase 1 验收标准）
4. **实现 `internal/fibonacci/`**，独立模块
5. **实现 `internal/harmonic/`**，Pattern Rule Engine 用 YAML DSL（含 invalidation 规则）
6. **实现 `internal/strategy/risk.go`（Risk Engine）**——第一版风险模块只做 PRZ → Invalidation Point → ATR Adjustment → Stop Loss 流水线（见 3.7），优先级高于堆形态数量；这是与普通 Harmonic Scanner 拉开质量差距的核心模块
7. **创建 `testdata/fixtures/`**，导出 100+ 组 candles→patterns 输入输出对作为 Golden Tests
8. **Go Pattern Engine 包一层薄 HTTP（`POST /detect`）**，Python 侧 `pyharmonics_adapter` 改为可切换后端（环境变量 `PATTERN_ENGINE_URL`，缺省走本地 pyharmonics）——Python 主服务零重构接入
9. **灰度切流**：按 symbol 比例切到 Go 引擎，对比两侧 pattern 输出差异并记录

注意：方案 B 阶段 Risk Engine 随 Go Pattern Engine 一起交付——`POST /detect` 响应直接带 PRZ + invalidation_point + 三档止损，Python 侧不做二次计算，避免两套风险逻辑漂移。

**第二步（视第一步结果，方案 C）**：

10. **实现 `/api/health` + `/api/markets` + JWT/quota 中间件**，验证部署流程
11. **拆分 chart-renderer Python 微服务**（见 3.8）
12. **Phase 3 spike**：`openai-go` 最小 tool-calling agent 验证（1-2 天），通过后才排期 Vibe 迁移
13. **实现 Vibe SSE streaming**，Go 原生实现

---

## 附录 A：关键文件对应关系

| Python 模块 | Go 模块 | 说明 |
|-------------|---------|------|
| `app/infra/marketdata.py` | `internal/marketdata/binance.go` | 市场数据 |
| `app/infra/pyharmonics_adapter.py` | `internal/harmonic/` | Pattern 检测 |
| `app/domain/signals.py` | `internal/domain/pattern.go` | 领域模型 |
| `app/domain/validation.py` | `internal/harmonic/validator.go` | 形态验证 |
| `app/services/signal_engine.py` | `internal/strategy/engine.go` + `risk.go` | 策略引擎 + Risk Engine（止损逻辑拆出，见 3.7） |
| `app/services/analysis.py` | `cmd/api-server` | API 入口 |
| `app/services/vibe/orchestrator.py` | `internal/vibe/orchestrator.go` | Vibe 编排 |
| `app/services/vibe/backtest_engine.py` | `internal/backtest/engine.go` | 回测引擎 |
| `app/infra/vibe_event_store.py` | `internal/infra/redis/event_store.go` | 事件存储 |
| `app/infra/vibe_session_store.py` | `internal/infra/supabase/session_store.go` | Session 存储 |
| `app/infra/supabase_client.py` | `internal/infra/supabase/client.go` | Supabase 客户端 |
| `app/services/chart.py` | 独立 Python 微服务 | 图表渲染保留 Python（Plotly/Kaleido，见 3.8） |
| `app/tasks/vibe_worker.py` | `asynq` 或 goroutine+状态落库 | RQ 替代需解决任务持久化（风险 #6） |
| `app/api/auth.py` | `internal/api/middleware/auth.go` | Supabase JWKS + jwt/v5（原方案遗漏） |
| quota ledger（supabase_client.py） | `internal/infra/supabase/quota.go` | 迁移期与 Python 共用同一 ledger 表（原方案遗漏） |
| `/query` + `/`（chat_ui） | 不迁移 | 旧端点，确认无流量后废弃 |
| `app/services/vibe/cancellation.py` | `internal/vibe/cancel.go` | context + Redis Pub/Sub |

## 附录 B：Go 代码量估算

| 模块 | 预估 Go LOC | 说明 |
|------|-------------|------|
| Domain models | 300 | 核心类型定义 |
| Market data | 400 | Binance/Yahoo provider |
| ZigZag engine | 300 | 核心算法 |
| Fibonacci engine | 200 | 比率计算 |
| Harmonic patterns | 600 | 各 pattern 实现 |
| Pattern rule engine | 300 | YAML DSL（含 invalidation 规则） |
| Indicator library | 400 | ATR, RSI, EMA, MACD |
| Risk engine | 250 | PRZ + Invalidation + ATR 止损（见 3.7） |
| Strategy engine | 300 | 信号生成 |
| AI agents | 500 | Multi-agent |
| Vibe system | 600 | Orchestrator + tools |
| Backtest engine | 400 | 回测框架 |
| API handlers | 400 | HTTP endpoints |
| Infra (Supabase/Redis) | 500 | 基础设施 |
| **总计** | **~5,450 LOC** | 比 Python 少（无 legacy） |
