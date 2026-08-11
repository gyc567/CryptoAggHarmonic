# Plan: Binance CLI 整合 — Loop #12

> 将 `binance-cli`（`@binance/binance-cli`，binance-skills-hub 官方 skill）接入 cryptoagg loop-engineering，作为**行情数据补全层**，补充现有 Binance REST（`app/infra/marketdata.py`）。

---

## 1. Context

### 1.1 当前行情架构

cryptoagg 当前 Binance 行情来源：

```
app/infra/marketdata.py
    └── curl_cffi → Binance REST /api/v3/*
```

- 仅覆盖 Spot klines、ticker、orderbook
- **无**：funding rate、OI、mark price、premium index、algo order、portfolio margin

### 1.2 Binance CLI skill 能提供什么

`~/.agents/skills/binance` 安装的是 `@binance/binance-cli`，含 40+ 子命令，覆盖：

| 模块 | 主要功能 | 整合价值 |
|------|---------|---------|
| `spot` | Spot 交易、余额、订单 | 读（行情补全） |
| `futures-usds` | USD-M Futures（OI、funding rate、mark price） | **Secondary source** |
| `algo` | Algo order（SMT、TWAP、ASO） | 写（未来 L3） |
| `margin-trading` | 保证金数据 | 读（余额/负债） |
| `wallet` | 充值地址、dust | 读 |
| `convert` | 现货兑换 | 读 |
| `staking` / `simple-earn` | 理财 | 读 |

### 1.3 与现有 downstream 层的关系

```
cryptoagg signal loop
    │  HarmonicSignal
    ▼
┌─────────────────────────────────────────┐
│  downstream verification layers         │
│                                         │
│  freqtrade_dev_mcp → 回测验证（无实盘）  │  Loop #10（L3）
│  okx-trade-mcp → 实盘执行（paper/live）  │  Loop #11（L3，待真凭据）
│  binance-cli → 行情补全（read-only）     │  Loop #12（L2 建议）
└─────────────────────────────────────────┘
    │
    ▼
app/loop/tuning_promotion.py gate
```

**定位差异**：

| 层 | 能力 | 风险 |
|----|------|------|
| freqtrade_dev_mcp | 回测/ hyperopt | 低（read-only 回测） |
| okx-trade-mcp | 实盘 spot/futures 写 | 高（三重门） |
| **binance-cli** | **行情读（funding/OI/mark price）** | **极低（read-only）** |

### 1.4 为什么不复用 OKX market 模块

OKX 整合计划（ADR-0011）明确：OKX market 是 OKX 交易所数据。`app/infra/marketdata.py` 走 Binance。两个独立 exchange data source 是有意设计，不重复。

---

## 2. Goals

### 2.1 必做

- [ ] **Phase 0**：基线测量 — `app/infra/marketdata.py` 当前延迟记录入库 `[binance-baseline-01]`
- [ ] **包安装验证**：`npm list -g @binance/binance-cli` 确认已装
- [ ] **凭据配置**：binance-cli profile 走 `binance-cli profile create`（API key/secret 存 local profile，**不**进 git）
- [ ] **数据源封装**：`app/services/binance/data_source.py`（read-only market data，funding rate、OI、mark price）
- [ ] **handshake 层**：`app/services/binance/handshake.py`（market event → HISTORY.jsonl `source: binance_market`）
- [ ] **扩展 tuning_promotion**：`is_market_data_source()` + `market_data_allowed_for_tools()`（read-only，故 gate 宽松）
- [ ] **Loop #12 注册**：`docs/loop-state/BINANCE-LOOP.md` 六维定义 + `loop/loop_sync.py add-loop`
- [ ] **ADR-012**：`docs/adr/0012-binance-cli-integration.md`（6 条 Decision）
- [ ] **测试**：100% 覆盖（AGENTS.md 强制）

### 2.2 必不做

- ❌ **不**用 binance-cli 写操作（algo order、spot trade）— 需要独立 promotion gate，Phase 2 再议
- ❌ **不**修改 `app/infra/marketdata.py`（Binance REST 主路径不变）
- ❌ **不**用 binance-cli 替代现有任何功能 — 仅补全
- ❌ **不**在未确认凭据隔离的情况下上线写操作

---

## 3. Architecture

### 3.1 路径布局

```
app/services/binance/
    ├── __init__.py
    ├── data_source.py     # binance-cli market data → python dict
    ├── handshake.py       # market event → HISTORY.jsonl (source: binance_market)
    └── metrics.py         # binance_market_fetch_total / latency

.scratch/loop_state/binance/   # gitignore
    └── HISTORY.jsonl           # append-only
```

**Ponytail 排除区**：✅ `app/services/binance/` 在 Ponytail 范围内

### 3.2 数据流

```
binance-cli (CLI, installed)
    │
    ├── binance-cli market FundingRate  → data_source.py parse
    ├── binance-cli market OpenInterest → data_source.py parse
    └── binance-cli market MarkPrice    → data_source.py parse
              │
              ▼
    app/services/binance/data_source.py
              │
              ▼
    app/services/binance/handshake.py → HISTORY.jsonl (source: binance_market)
              │
              ▼
    tuning_promotion.is_market_data_source() → 宽松 gate
```

### 3.3 与 freqtrade/OKX 的 source mutex

`tuning_promotion.py` 的 `SourceMutexError`（ADR-0011 D11）：

| source | 互斥 |
|--------|------|
| `freqtrade_hyperopt` | ←→ `okx_*` |
| `binance_market` | 无互斥（纯读） |

---

## 4. Security Model

### 4.1 凭据隔离

binance-cli 的凭据存储在 `~/.config/binance-cli/`（profile 模式），**不**写入 repo。

```bash
# 用户本地操作（不在 CI/server 运行）
binance-cli profile create --name cryptoagg --api-key XXX --api-secret YYY --env prod
binance-cli profile view  # 验证
```

CI / server 环境：走 `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` env var（不写入配置文件）。

### 4.2 写操作约束

当前阶段**禁止**任何写操作：

| binance-cli 命令 | 状态 |
|-----------------|------|
| `spot order` | ❌ 禁止 |
| `algo order` | ❌ 禁止 |
| `futures order` | ❌ 禁止 |
| `convert` | ❌ 禁止 |
| `market *` | ✅ 允许（read-only） |

`tuning_promotion.py` 的 `execution_allowed_for_tools()` 追加白名单，仅含 `market` 族。

### 4.3 Production Transaction 警告

binance skill SKILL.md 要求：⚠️ **Prod transactions** — always ask user to type `CONFIRM` before executing. 这是 skill 内置保护，即使写操作 Phase 2 开放，此约束继续适用。

---

## 5. Loop #12 定义

文件：`docs/loop-state/BINANCE-LOOP.md`

| 属性 | 值 |
|------|---|
| **Cadence** | 每 6 小时（与 Dependency Sweeper 同周期） |
| **Trigger** | GitHub Actions schedule |
| **Skill** | binance（`~/.agents/skills/binance`） |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | Binance funding rate、OI、mark price 实时数据 |
| **输出** | `HISTORY.jsonl`（`source: binance_market`）条目；Market Data 报告 |
| **Gate** | L2（辅助建议，不自动执行） |
| **MCP** | binance-cli（无 MCP server，CLI 直接调用） |

---

## 6. Phase 拆解

### Phase 0：基线测量（0.5 天）

- [ ] 记录 `app/infra/marketdata.py` 当前 funding rate / OI / mark price 获取延迟
- [ ] 写入 `[binance-baseline-01]` 到 `docs/loop-state/durable-facts.md`
- [ ] 确认 binance-cli 已安装：`npm list -g @binance/binance-cli`

### Phase 1：基础设施（1 周）

- [ ] 创建 `app/services/binance/`（`__init__.py`、`data_source.py`、`handshake.py`、`metrics.py`）
- [ ] `.scratch/loop_state/binance/` 目录 + `.gitignore` 覆盖
- [ ] `tuning_promotion.py` 追加 `is_market_data_source()` + `market_data_allowed_for_tools()`
- [ ] `docs/loop-state/BINANCE-LOOP.md` 六维定义
- [ ] `loop/loop_sync.py add-loop` 注册为 Loop #12
- [ ] `docs/adr/0012-binance-cli-integration.md`（6 条 Decision）
- [ ] gate.yaml 加 Binance denylist

### Phase 2：实现 + 测试（1 周）

- [ ] `data_source.py` 实现（funding rate、OI、mark price 三接口）
- [ ] `handshake.py` 实现（outbox 模式，crash-safe）
- [ ] 100% 测试覆盖（AGENTS.md 强制）
- [ ] Pyright 类型检查

### Phase 3：Loop 上线（0.5 天）

- [ ] `.github/workflows/binance-market-loop.yml`（六维对齐 Loop #12）
- [ ] 端到端测试：binance-cli market → data_source → handshake → HISTORY.jsonl
- [ ] 回滚演练

---

## 7. 与上游计划的引用

| 引用 | 用途 |
|------|------|
| freqtrade-mcp-integration plan §6 | outerloop 协议基础 |
| OKX plan ADR-0011 D11 | `SourceMutexError` 复用 |
| OKX plan §4.1 | 凭据隔离模式（Keychain profile） |
| Loop #10/#11 注册方式 | `loop/loop_sync.py add-loop` 复用 |
| AGENTS.md 100% 覆盖要求 | 测试强制要求 |

---

## 8. Risk & Rollback

| 风险 | 触发条件 | 回滚动作 |
|------|---------|---------|
| binance-cli 上游变更 | CLI 输出格式Breaking Change | 固定版本；写 parser fallback |
| API rate limit | binance-cli market 429 | 降频；切换到 REST fallback |
| 凭据泄露 | profile 文件进 git | `git filter-repo`；rotate key |

---

## 9. ADR-0012 草案

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | binance-cli 仅补全，不替代 REST 主路径 | 最小意外原则 |
| D2 | Phase 1 仅 read-only market data | 安全第一 |
| D3 | 写操作（algo/spot/futures）需独立 ADR + 三重门 | 不在本文范围 |
| D4 | profile 存 `~/.config/binance-cli/`，不进 git | 凭据隔离 |
| D5 | `source: binance_market` 入 HISTORY.jsonl，source mutex 豁免 | 纯读无互斥 |
| D6 | binance skill 版本跟随 `~/.agents/skills/binance` 安装版本 | skill 自身版本管理 |

---

_Last updated: 2026-08-11_
