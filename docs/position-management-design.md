# 仓位管理页面设计方案（已审计版）

> 状态：已审计，可直接进入编码  
> 目标：作为独立新页面 `/position` 完全融入现有 CryptoAgg SaaS 前端  
> 参考来源：
> - https://www.liandu24.com/aihub/cwbox/cangwei.html（WU 仓位单位、账户隔离、风控等级、what-if 模拟）  
> - https://x.com/CryptoMetac/status/2063434459207303365（访问受限，已预留情绪/纪律检查模块）  
> 风格：延续 `docs/frontend-design-2026-07-14.md` 深色科技风 + 玻璃拟态

---

## 0. 审计结论

本方案与当前项目（Next.js 14 前端 + Supabase Auth/Postgres + Flask Python 后端）可完全融合，无需改动现有业务核心（分析 API、额度系统、认证流）。新增内容仅限：

1. 一个前端页面 `app/position/page.tsx` 及配套组件；
2. 前端类型、计算 hooks、本地/Supabase 持久化封装；
3. 数据库 `profiles` 表新增两个 JSONB 字段，以及两张新表 `long_term_holdings`、`trade_readiness_logs`；
4. `Sidebar` 增加“仓位”导航项。

所有 UI 均可复用现有设计令牌与组件类（`glass-card`、`btn-primary`、`input-surface`、`badge`、`shimmer`），只需补充少量仓位专用样式。

---

## 1. 设计目标

把仓位管理从“凭感觉”变成“按规则执行”。页面需要帮助用户：

1. 按统一单位（WU）看清总资金结构。
2. 在交易前自动评估这笔交易会触发几级风控阻力。
3. 通过“设备隔离 + 账户拆分”制造操作摩擦，降低冲动交易。
4. 交易后实时模拟余额变化，确认没有超配。
5. 长期价值仓独立记录，避免与短线仓位混淆。
6. 与现有 Pyharmonics 分析工作台形成闭环：分析 → 仓位检查 → 下单决策。

---

## 2. 核心概念与计算规则

### 2.1 单位定义

| 概念 | 说明 |
|------|------|
| **WU（万 U）** | 1 WU = 10,000 USDT，所有仓位与金额默认以 WU 显示，悬停可显示原始 U 额 |
| **总资金** | 用户当前可用于交易的总本金 |
| **切割仓位** | 长期价值标的独立冻结部分，不参与短线仓位管理 |
| **常规管理资金** | `总资金 − 切割仓位` |
| **救命钱** | 黑天鹅备用金，原则上不可动用 |
| **BTC 趋势仓** | 大账户，低换手，长线趋势仓位 |
| **山寨币仓** | 中账户 + 小账户合计，风险高于 BTC |
| **中账户** | 高流动性、大市值山寨 |
| **小账户** | 新币 / 小币合约 / 高风险仓 |
| **小账户可交易比例** | 小账户内可立即动用的比例（默认 70%） |
| **小账户备用比例** | `1 − 可交易比例`，需要额外操作才能动用 |

### 2.2 默认仓位公式

```text
常规管理资金 = 总资金 − 切割仓位

救命钱      = 常规管理资金 × 救命钱比例
BTC 趋势仓  = 常规管理资金 × BTC 目标比例
山寨币上限  = 常规管理资金 × 山寨币上限比例
  ├─ 中账户 = 山寨币上限 × 中账户比例
  └─ 小账户 = 山寨币上限 × 小账户比例
       ├─ 可交易 = 小账户 × 小账户可交易比例
       └─ 备用   = 小账户 × 小账户备用比例
```

### 2.3 大资金模式

当 `总资金 > 大资金门槛`（默认 1,000 WU）时自动切换：

- 山寨币上限下调为 **大资金模式·山寨上限**（默认 10%）。
- BTC 目标比例建议调整为 **大资金模式·BTC 参考**（默认 65%）。
- 触发更高风控等级所需金额阈值相应提高。

---

## 3. 用户流程

```text
首次进入
  └─ 设置总资金、选择资金规模（小户/中户/大户）与风险偏好（保守/平衡/激进）
     └─ 一键套用智能参数推荐
        └─ 进入仓位管理主页

日常进入
  └─ 查看当前仓位结构卡片与风控评分
     └─ 输入“计划交易金额”
        ├─ 系统实时判定风控触发等级
        ├─ 展示需要跨越的阻力与建议等待时间
        └─ 用户完成冷静检查清单
           ├─ 未通过：提示暂停并记录原因
           └─ 已通过：可继续到 Dashboard 执行分析/下单

交易后
  └─ 输入“实际成交金额”
     └─ what-if 瀑布消耗模拟更新各账户余额
```

---

## 4. 页面信息架构

```
┌─────────────────────────────────────────────────────────────┐
│  Topbar（复用现有，标题为“仓位管理”）                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 总览卡片区                                           │   │
│  │  总资金 · 常规管理资金 · 风控评分 · 当前触发等级     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────┐  ┌─────────────────────────┐ │
│  │ 参数配置面板              │  │ 智能风控评分            │ │
│  │  总资金 / 单位 / 计划交易 │  │  当前等级 + 区间说明    │ │
│  │  救命钱 / BTC / 山寨比例  │  │  阻力指数进度条         │ │
│  │  中/小账户比例            │  │                         │ │
│  │  小账户可交易/备用比例    │  │ 冷静检查清单            │ │
│  │  大资金门槛与模式参数     │  │  买入理由 / 非 FOMO     │ │
│  │  [一键套用推荐参数]       │  │  [确认通过]             │ │
│  └──────────────────────────┘  └─────────────────────────┘ │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 仓位结构 & 账户拆分（实时可视化）                    │   │
│  │  堆叠进度条 / 账户卡片 / 设备隔离标签                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 交易后余额模拟 what-if                               │   │
│  │  实际成交金额 → 瀑布消耗 → 各账户剩余余额            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────┐  ┌─────────────────────────┐ │
│  │ 参数校验区                │  │ 智能体检诊断            │ │
│  │  4 项核心约束实时状态     │  │  隐患提醒 + 优化建议    │ │
│  └──────────────────────────┘  └─────────────────────────┘ │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 切割仓位统计 + 长期价值记录表（高级）                │   │
│  │  标的 / 买入价 / 仓位 / 卖出条件 / 复盘日期 / 操作   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 功能模块详细设计

### 5.1 参数配置面板

| 字段 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| 总资金 | 10,000 WU | > 0 | 用户总本金 |
| 单位 | WU | 只读 | 1 WU = 10,000 U |
| 计划交易金额 | 0.5 WU | ≥ 0 | 用于测试风控触发等级 |
| 救命钱比例 | 30% | 0%–50% | 黑天鹅备用 |
| BTC 目标比例 | 50% | 0%–80% | 趋势仓 |
| 山寨币上限比例 | 20% | 0%–50% | 中 + 小 |
| 中账户比例 | 15% | 0%–山寨上限 | 高流动性大市值 |
| 小账户比例 | 5% | 0%–山寨上限 | 高风险 |
| 小账户可交易比例 | 70% | 0%–100% | 小账户内可立即动用 |
| 小账户备用比例 | 30% | 自动 = 1 − 可交易 | 需要额外操作 |
| 大资金门槛 | 1,000 WU | ≥ 100 | 触发大资金模式 |
| 大资金模式·山寨上限 | 10% | 0%–50% | 大资金下自动切换 |
| 大资金模式·BTC 参考 | 65% | 0%–80% | 大资金下建议 |
| 切割仓位金额 | 0 WU | ≥ 0 | 长期价值仓冻结额 |

**交互规则：**

- 所有比例输入带滑块 + 数字输入框，修改后全表实时联动。
- 当 `总资金 > 大资金门槛` 时：
  - 自动弹出提示“已进入大资金模式”。
  - 山寨上限若高于大资金模式值，标红并提示下调。
- 提供“智能参数推荐”快捷按钮：
  - 规模：小户 / 中户 / 大户
  - 风险偏好：保守 / 平衡 / 激进
  - 一键套用后展示推荐参数摘要。

### 5.2 仓位结构 & 账户拆分可视化

以卡片 + 堆叠进度条组合呈现：

```
常规管理资金 10,000 WU
├─ 救命钱          3,000 WU  30.0%  [家里电脑 / 理财]
├─ BTC 趋势仓      5,000 WU  50.0%  [家里电脑]
└─ 山寨币上限      2,000 WU  20.0%
   ├─ 中账户       1,500 WU  15.0%  [手机 1]
   └─ 小账户         500 WU   5.0%
      ├─ 可交易      350 WU   3.5%  [手机 2]
      └─ 备用        150 WU   1.5%  [手机 2 / 理财]
```

**视觉：**

- 每个账户一张玻璃拟态卡片，显示金额、占比、存放设备。
- 进度条用不同颜色区分：救命钱（紫 `#8a7cf4`）、BTC（青 `#00d4ff`）、中账户（蓝 `#3b82f6`）、小账户可交易（橙 `#ffb029`）、小账户备用（灰 `#607085`）。
- 悬停卡片显示原始 U 额与占总资金比例。

### 5.3 风控触发等级

根据“计划交易金额”自动判定：

| 等级 | 触发区间（WU） | 需要跨越的麻烦 | 建议等待 |
|------|----------------|----------------|----------|
| 0 级 | 0 ~ 小账户可交易金额 | 无额外麻烦 | 至少确认逻辑 |
| 1 级 | 小账户可交易 ~ 小账户总额 | 需划转小账户备用 | 暂停 5 分钟 |
| 2 级 | 小账户总额 ~ 山寨币上限 | 换账户 / 换手机 | 暂停 15 分钟 |
| 3 级 | 山寨币上限 ~ BTC 趋势仓 | 必须回家电脑操作 | 隔夜复盘 |
| 4 级 | BTC 趋势仓 ~ 常规管理资金 | 再次从理财资管划转 | 原则上禁止 |
| 5 级 | > 常规管理资金 | 无法覆盖 | 禁止 |

**展示：**

- 顶部大字号显示当前等级（例如“2 级”）。
- 等级条 0–5，当前等级高亮，超过当前等级的部分置灰。
- 下方表格自动高亮当前所在行。
- 文案提示具体操作建议。

### 5.4 冷静检查清单

交易前必须勾选：

1. ✓ 写下买入理由与卖出条件（任何交易前必做）
2. ✓ 确认这不是被 KOL / 社群情绪推动的 FOMO
3. ✓ 计划金额在风控等级可接受范围内
4. ✓ 已检查账户余额，不会动用救命钱

**交互：**

- 未全部勾选时，底部“前往分析/下单”按钮禁用或显示强提示。
- 勾选后记录本次通过时间，写入 `trade_readiness_logs`。

### 5.5 交易后余额模拟（what-if）

| 字段 | 说明 |
|------|------|
| 实际成交金额 | 默认跟随“计划交易金额”，可单独修改以模拟真实成交 |
| 已消耗（瀑布） | 按小账户可交易 → 小账户备用 → 中账户 → BTC 趋势仓 → 救命钱的顺序消耗 |
| 剩余可动用 | 总资金 − 实际成交 − 切割仓位 |

**展示：**

- 各账户原余额、消耗、剩余余额三列。
- 若消耗触及救命钱，标红并禁止归档。
- 模拟结果可一键“确认归档”，更新 `profiles.position_balance`。

### 5.6 参数校验

实时 4 项校验，全部通过显示“4/4 通过”：

1. **三类仓位合计 = 100%**  
   `救命钱 + BTC + 山寨 = 100%`
2. **中账户 + 小账户 = 山寨上限**  
   `中比例 + 小比例 = 山寨上限比例`
3. **小账户内部 = 100%**  
   `可交易比例 + 备用比例 = 100%`
4. **常规管理资金非负**  
   `总资金 − 切割仓位 ≥ 0`

未通过项用红色说明错误原因。

### 5.7 智能体检诊断

实时扫描配置隐患：

- **救命钱比例过低**（< 20%）→ 建议提高到 30%
- **大资金模式下山寨超配** → 建议下调至 ≤ 10%
- **小账户可交易比例过高** → 建议保留更多备用
- **切割仓位未设置** → 提示长期价值仓独立管理的好处
- **BTC 权重偏离参考** → 提示可考虑调整

每条诊断带图标（! 提醒 / i 建议）和可执行按钮。

### 5.8 长期价值切割仓位

独立模块，默认折叠（高级）。

| 字段 | 说明 |
|------|------|
| 标的 | 如 BTC、ETH |
| 买入价 | 记录成本价 |
| 仓位（WU） | 长期仓大小 |
| 卖出条件 | 目标价 / 时间 / 事件 |
| 复盘日期 | 下次复盘时间 |
| 操作 | 编辑 / 删除 |

底部统计：已记录标的数、合计仓位。

---

## 6. 与现有 CryptoAgg 系统的融合

### 6.1 路由与导航

新增独立页面，与 Dashboard 平级：

- `/position` — 仓位管理主页
- `frontend/components/layout/sidebar.tsx` 的 `NAV_ITEMS` 增加：
  ```ts
  { href: "/position", label: "仓位", icon: Wallet }
  ```
  图标从 `lucide-react` 导入 `Wallet`。
- `frontend/components/providers/app-shell.tsx` 的 `getPageTitle` 增加 `/position` → “仓位管理”。

### 6.2 视觉与组件复用

| 现有资源 | 在本页面的用法 |
|----------|----------------|
| `glass-card` / `glass-card-dark` | 所有面板卡片 |
| `btn-primary` / `btn-secondary` | 保存、套用推荐、去分析、归档 |
| `input-surface` | 总资金、计划交易金额、各比例数字输入 |
| `badge` | 风险等级标签、诊断类型标签 |
| `shimmer` | 首次加载配置时的骨架屏 |
| `text-gradient` | 页面大标题 |
| Tailwind 颜色 `success` / `warning` / `danger` / `purple` / `cy` | 风险等级与账户结构配色 |
| `ChartViewer` | 不需要 |

**需补充的样式（建议写入 `frontend/app/globals.css`）：**

```css
@layer components {
  .slider-surface {
    @apply h-2 w-full cursor-pointer appearance-none rounded-lg bg-surface-2 accent-primary;
  }

  .stacked-bar-segment {
    @apply h-full transition-all duration-300 first:rounded-l-lg last:rounded-r-lg;
  }

  .risk-level-step {
    @apply flex-1 rounded-full bg-surface-2 transition-colors;
  }

  .risk-level-step-active {
    @apply shadow-glow-sm;
  }
}
```

### 6.3 数据持久化

采用 **Supabase 直接读写 + localStorage 降级** 策略，与现有认证体系天然打通。

#### 数据库变更（Supabase SQL）

```sql
-- 1. profiles 表新增仓位配置与余额快照
ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS position_config JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS position_balance JSONB DEFAULT NULL;

-- 2. 长期价值记录表
CREATE TABLE IF NOT EXISTS long_term_holdings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    entry_price NUMERIC,
    position_wu NUMERIC NOT NULL DEFAULT 0,
    exit_condition TEXT,
    review_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE long_term_holdings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own holdings" ON long_term_holdings;
CREATE POLICY "Users can manage own holdings" ON long_term_holdings
    FOR ALL USING (auth.uid() = user_id);

-- 3. 冷静清单通过记录
CREATE TABLE IF NOT EXISTS trade_readiness_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    planned_trade_wu NUMERIC NOT NULL,
    risk_level INTEGER NOT NULL,
    checklist JSONB NOT NULL DEFAULT '{}',
    passed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE trade_readiness_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own readiness logs" ON trade_readiness_logs;
CREATE POLICY "Users can read own readiness logs" ON trade_readiness_logs
    FOR ALL USING (auth.uid() = user_id);
```

#### 前端封装

- 新增 `frontend/lib/position/db.ts`：
  - `loadPositionConfig(userId)` / `savePositionConfig(userId, config)`
  - `loadPositionBalance(userId)` / `savePositionBalance(userId, balance)`
  - `listHoldings(userId)` / `createHolding(...)` / `updateHolding(...)` / `deleteHolding(id)`
  - `logTradeReadiness(...)`
  - 所有函数优先走 Supabase，失败时降级到 localStorage（键名：`pyharmonics:position:config` 等）。

### 6.4 与分析工作流联动

- Dashboard 的 `AnalyzeForm` / `ResultPanel` 中可增加“去仓位管理”按钮，URL 携带 `?symbol=BTCUSDT&size=0.5`。
- `/position` 页面读取 URL 参数，自动填入 `symbol`（用于长期价值记录联想）和 `plannedTrade`。
- `/position` 中“去分析”按钮跳转 `/dashboard?symbol=BTCUSDT`，保持双向闭环。
- 不涉及后端 Python API 改动。

### 6.5 权限

- 普通用户通过 RLS 仅访问 `user_id = auth.uid()` 的记录。
- 管理员可在 `/admin` 新增汇总卡片：
  - 平均救命钱比例
  - 平均风控触发等级分布
  - 今日冷静清单通过/拒绝次数

---

## 7. 类型定义

新增 `frontend/types/position.ts`：

```ts
export type FundScale = "small" | "medium" | "large";
export type RiskAppetite = "conservative" | "balanced" | "aggressive";

export interface PositionConfig {
  totalCapitalWu: number;
  emergencyRatio: number;
  btcRatio: number;
  altcoinMaxRatio: number;
  midAccountRatio: number;
  smallAccountRatio: number;
  smallTradableRatio: number;
  largeCapitalThresholdWu: number;
  largeCapitalAltcoinMaxRatio: number;
  largeCapitalBtcReferenceRatio: number;
  cutPositionWu: number;
}

export interface AccountBucket {
  key: string;
  label: string;
  amountWu: number;
  ratioOfRegular: number;
  ratioOfTotal: number;
  device: string;
  color: string;
}

export interface PositionBalance {
  emergencyWu: number;
  btcWu: number;
  midWu: number;
  smallTradableWu: number;
  smallReserveWu: number;
  cutPositionWu: number;
}

export interface RiskLevel {
  level: number;
  label: string;
  minWu: number;
  maxWu: number;
  trouble: string;
  cooldown: string;
}

export interface ColdCheckItem {
  id: string;
  label: string;
  checked: boolean;
}

export interface LongTermHolding {
  id: string;
  symbol: string;
  entryPrice?: number;
  positionWu: number;
  exitCondition?: string;
  reviewDate?: string;
  createdAt: string;
}
```

---

## 8. 计算引擎

新增 `frontend/lib/position/calculator.ts`，所有函数纯函数、可测试：

```ts
export function computeBuckets(config: PositionConfig, balance: PositionBalance): AccountBucket[];
export function computeRiskLevel(config: PositionConfig, plannedTradeWu: number): RiskLevel;
export function computeValidation(config: PositionConfig): ValidationResult[];
export function computeDiagnostics(config: PositionConfig): DiagnosticItem[];
export function simulateWhatIf(config: PositionConfig, balance: PositionBalance, tradeWu: number): WhatIfResult;
export function applyRecommendation(scale: FundScale, appetite: RiskAppetite): Partial<PositionConfig>;
```

计算结果在前端 `usePosition` hook 中缓存，避免重复计算。

---

## 9. Hooks 与状态管理

新增 `frontend/hooks/use-position.ts`：

```ts
export function usePosition(userId: string | undefined) {
  const [config, setConfig] = useState<PositionConfig | null>(null);
  const [balance, setBalance] = useState<PositionBalance | null>(null);
  const [plannedTrade, setPlannedTrade] = useState(0.5);
  const [actualTrade, setActualTrade] = useState(0.5);
  const [checklist, setChecklist] = useState<ColdCheckItem[]>(DEFAULT_CHECKLIST);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // 加载/保存 config、balance
  // 计算派生状态：buckets、riskLevel、validation、diagnostics、whatIf
  // 归档 what-if 到 balance
}
```

---

## 10. 文件结构（实现清单）

```
frontend/
├── app/
│   └── position/
│       └── page.tsx                       # 页面入口
├── components/
│   ├── layout/
│   │   └── sidebar.tsx                    # 增加仓位导航（改现有文件）
│   ├── providers/
│   │   └── app-shell.tsx                  # 增加页面标题（改现有文件）
│   ├── position/
│   │   ├── position-header.tsx            # 总览卡片区
│   │   ├── position-config-panel.tsx      # 参数配置面板
│   │   ├── input-slider.tsx               # 滑块 + 数字输入组合
│   │   ├── recommendation-modal.tsx       # 一键套用推荐参数
│   │   ├── account-structure.tsx          # 仓位结构可视化
│   │   ├── risk-level-panel.tsx           # 风控触发等级
│   │   ├── cold-checklist.tsx             # 冷静检查清单
│   │   ├── what-if-simulator.tsx          # 交易后余额模拟
│   │   ├── validation-panel.tsx           # 参数校验
│   │   ├── diagnosis-panel.tsx            # 智能诊断
│   │   └── long-term-holdings.tsx         # 长期价值记录表
│   └── ui/
│       └── progress-stacked.tsx           # 可复用堆叠进度条
├── hooks/
│   └── use-position.ts                    # 仓位状态与持久化
├── lib/
│   └── position/
│       ├── calculator.ts                  # 纯函数计算引擎
│       ├── defaults.ts                    # 默认配置与推荐模板
│       └── db.ts                          # Supabase + localStorage 持久化
├── types/
│   └── position.ts                        # 类型定义
└── app/
    └── globals.css                        # 补充 slider-surface 等样式（改现有文件）
```

---

## 11. 后端影响

- **无需改动 Flask Python 后端**：仓位管理是纯前端 + Supabase 数据功能。
- **需要执行一次 Supabase SQL 迁移**（见 6.3）。
- 如未来需要把仓位分析结果写入 `analyses` 或 `usage_ledger`，可再扩展，当前方案不涉及。

---

## 12. 视觉与交互规范

### 12.1 沿用现有设计令牌

- 背景：`--background`（深 Navy `#020817`）
- 卡片：`--surface-1` + `backdrop-blur-xl` + `border`
- 主色：`--primary`（青色 `#00d4ff`）
- 成功/警告/危险：`--success` / `--warning` / `--danger`
- 圆角：`--radius`（1rem）
- 字体：Geist Sans

### 12.2 风险等级配色

| 等级 | 颜色 |
|------|------|
| 0 级 | 成功绿 `#20df66` |
| 1 级 | 信息青 `#00d4ff` |
| 2 级 | 警告橙 `#ffb029` |
| 3 级 | 深橙 `#ff7a00` |
| 4 级 | 危险红 `#ff527a` |
| 5 级 | 危险红 + 禁用态 |

### 12.3 动画

- 参数修改时金额数字平滑过渡（CSS `transition`）。
- 风控等级变化时等级条高亮过渡。
- 卡片 hover 边框发光（复用现有 `hover:border-border-hover`）。

### 12.4 响应式

- **桌面**：`grid-cols-12`，左侧配置占 5，右侧风控占 7；结构占 12。
- **平板**：配置与风控上下堆叠。
- **手机**：单列全宽，参数面板可折叠，账户结构垂直卡片。

---

## 13. 待确认问题（已给出建议默认值）

| 问题 | 建议 |
|------|------|
| 1. 资金单位是否允许切换？ | 第一阶段固定 WU，悬停显示 U；第二阶段可切换 |
| 2. 是否必须登录保存？ | 必须登录保存到 Supabase；未登录时显示占位引导 |
| 3. 是否同步到 usage_ledger / analyses？ | 不同步；仅作为独立仓位管理数据 |
| 4. 风控等级阈值是否可自定义？ | 默认模板不可改；高级设置中允许自定义（v2） |
| 5. 长期价值仓是否需要复盘提醒？ | 需要，复盘日期到期前 3 天高亮 |
| 6. 是否连接交易所 API？ | 否，纯手动维护余额；交易所接入列为后续增强 |

---

## 14. 实现顺序建议

1. **数据库迁移**：执行 6.3 SQL。
2. **类型与计算引擎**：`types/position.ts` + `lib/position/calculator.ts` + 单元测试。
3. **持久化层**：`lib/position/db.ts` + `defaults.ts`。
4. **核心 Hook**：`hooks/use-position.ts`。
5. **UI 组件**：按 5.1–5.8 逐个实现，先参数配置与账户结构，再风控与 what-if。
6. **页面组装**：`app/position/page.tsx`。
7. **导航与标题**：改 `sidebar.tsx`、`app-shell.tsx`。
8. **联调与构建**：`npm run build`、`npm run lint`。

---

*本方案已完成审计，样式、组件、数据层、权限均可与现有项目无缝融合，可直接进入编码。*
