# ADR-0011: OKX Agent Trade Kit 整合

**状态**: Accepted (Phase 0 闭环)
**日期**: 2026-08-11
**v1 计划**: `docs/plans/okx-agent-trade-kit-integration.md` (620 行, 63 tasks)
**v1 审计报告**: `docs/plans/okx-agent-trade-kit-integration-audit-report.md` (466 行, 23 项修复: 6 F + 12 M + 3 P + 5 D)
**v2 计划**: 同 v1 文件 (应用 23 项修复后修订版)
**基线**: `[okx-baseline-01]` in `docs/loop-state/durable-facts.md`
**12 Decision**: 8 来自用户答案 + 4 派生 (D8 三重门+第四门 / D9 promotion 扩展不动 / D10 audit outbox 模式 / D11 source mutex / D12 --rotate flag)
> 继承 ADR-0010（Freqtrade 整合）的设计模式：路径隔离、状态文件位置、crash-safe、Ponytail 排除、promotion gate 复用。

---

## Decision 1: 包管理 = npm 全局安装 + `scripts/okx/VERSION` 单文件

```
npm i -g @okx_ai/okx-trade-mcp@1.0.4
scripts/okx/VERSION: "1.0.4"  (单文件)
```

**不**新建 `package.json`（Python 仓库异构）。版本锁 1.0.4 长期；升级路径需新 ADR 修订本文件。

**理由**:
- upstream 已是 npm-published + MIT + 101★/active，trust-on-first-use 风险低
- 黑盒 MCP 用法，不需要看/改 upstream 源码（freqtrade 不同，需要翻译层）
- 与 Python 异构最小化：1 文件 VERSION 足够

---

## Decision 2: Phase 1 节奏 0.5 周，拆 1A + 1B

| 子阶段 | 周 | 内容 |
|---|---|---|
| 1A | 0.25 | npm install + Keychain + 凭据脚本 + .env 占位 |
| 1B | 0.25 | tuning_promotion 扩展 + executor.py skeleton + Loop #11 注册 + ADR-0011 |

**理由**: 用户答 0.5 周；13 子任务一次性跑会崩，拆 A/B 后每段 4-5 子任务可控。

---

## Decision 3: 首笔实盘 limit 单 ≤ $10 USDT 等价

Phase 4 shadow 7 天后，**首笔实盘**:
- instrument: spot（**不** swap/futures/option）
- 数量: ≤ $10 USDT 等价
- ordType: limit（**不** market — 防滑点失控）
- 人工触发 + 截图 + 写 `[okx-first-live-01]` durable-fact

**理由**: 用户答 $10。最小资金暴露 + 真实 fill 验证 + 不可逆（事后改不回去）。

---

## Decision 4: npm 锁 1.0.4 长期，升级需新 ADR

```
scripts/okx/VERSION: "1.0.4"
.claude/settings.json okx.command 假定 PATH 中有 okx-trade-mcp 1.0.4
```

升级路径（如需）:
1. 写新 ADR（`0012-okx-1.0.5-upgrade.md`）说明 upstream 改动 + 测试结果
2. 改 VERSION + `install.sh install @1.0.5` 幂等升级
3. 重跑所有 Phase 1-3 验收

**理由**: 用户答锁 1.0.4。避免 npm upstream 改动签名/格式导致 auth 突崩。

---

## Decision 5: Phase 1 模块仅 market + account + spot (paper)

| Module | Phase 1 行为 |
|---|---|
| market | ✅ read-only（默认启动）|
| account | ✅ read + write 但仅本机的 `account_get_balance` 验证 |
| spot | ✅ write — **仅 paper mode**（MCP 启动 `--demo`）|

其他模块（swap/futures/option/earn/event/bot/news/smartmoney）**显式不在** Phase 1 范围。

**理由**: 用户答 Phase 1 仅市场 + 账户 + 模拟盘 spot。风险最低。

---

## Decision 6: audit log 90 天滚动（**不**自动清）

```
.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl
```

90 天后**人工**归档（不自动清）。**append-only** + 10 字段 schema（见 Decision 10）。

**理由**: 用户答 90 天。自动清 = 不可逆数据丢失；人工归档 = 显式决策。

---

## Decision 7: Keychain `cryptoagg-okx` service + 3 accounts

| Account | 用途 |
|---|---|
| `api-key` | OKX API key |
| `secret-key` | OKX secret key |
| `passphrase` | OKX passphrase（**OKX 独有**）|

**不**放 `paper-mode`（是部署决策，env variable）。

启动期验证: `executor.py` 启动时调 `account_get_balance`，成功 = 三要素正确；失败 = 报错退出（**fail-fast，不 silent fallback**）。

**理由**: 用户答 3 accounts。`paper-mode` 放 Keychain 浪费且语义混乱。

---

## Decision 8: 三重门 + 第四门 human checklist

| 门 | 形式 | 阶段 |
|---|---|---|
| **1: MCP 启动参数** | `--modules market,account,spot --read-only` 默认 | 静态配置 |
| **2: env** | `OKX_PAPER_MODE=true` 默认 / `OKX_ALLOW_LIVE=1` opt-in | 运行时 |
| **3: code** | `execution_allowed_for_tools()` runtime 拦截 | 运行时 |
| **4: human** | `promotion_checklist()` 全门（含 audit 强制）| 评审 |

**门 1 与门 2 的关系**: 门 1 决定哪些 tool 可用（模块级）；门 2 决定写操作是否发到 OKX 服务器（模式级）。两层独立。

**门 3 与门 4 的关系**: 门 3 是 runtime 自动检查；门 4 是 human review 时的 checklist 增强（追加 audit log 强制项）。

**理由**: OKX 写操作涉及真金白银（与 freqtrade 回测本质不同），必须比 freqtrade 严 N 倍。

---

## Decision 9: `tuning_promotion.py` 扩展不修改

**新增** 2 个 API:
- `is_live_execution_tool(name: str) -> bool`
- `execution_allowed_for_tools(names: list[str], paper: bool) -> tuple[bool, str]`

**修改** 1 个 API（仅追加 checklist item，**不**改签名）:
- `promotion_checklist()` 末尾追加 `[ ] audit log 完整 (`.scratch/okx/audit/` 100% 覆盖所有写 tool)`

**不修改** 现有 3 API 签名:
- `is_live_tuning_path()` (PR-level 路径 gate)
- `promotion_allowed_for_files()` (PR-level 路径 gate)
- `promotion_checklist()` 既有 4 项 (drawdown / Calmar / Shadow / salt_version)

**理由**: 路径 gate (PR 评审) 与 tool gate (runtime 拦截) 性质不同；混在一个模块里职责过载。

---

## Decision 10: audit log 走 outbox 模式 + 10 字段 schema

路径: `.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl.outbox/{uuid}.json` → atomic rename → `.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl`

复用 `app/loop/state.append_history()` 的 outbox 语义（freqtrade 已有）。

**10 字段 schema** (每次写 tool 调用必填):

```json
{
  "ts": "2026-08-11T13:47:26.123456Z",
  "tool": "spot_place_order",
  "args": {"instId": "BTC-USDT", "side": "buy", ...},
  "result_code": "0",
  "result_body_hash": "sha256:...",
  "user": "loop#11",
  "salt_version": 3,
  "paper": true,
  "cl_ord_id": "OKX-LOOP-a1b2c3d4",
  "latency_ms": 234,
  "trace_id": "abc123def456"
}
```

**理由**: 写一半比不写更糟（事后以为有 fill 实际没有）；outbox 模式必填。

---

## Decision 11: TUNING promotion 互斥锁

`app/loop/state.append_history()` 检测同 `candidate_id` 是否同时含:
- `source: freqtrade_hyperopt` (来自 freqtrade loop)
- `source: okx_live` / `okx_paper` (来自 OKX loop)

若同时存在 → 抛 `SourceMutexError` 拒绝写入。

**理由**: 两条 loop **独立触发** + 同一 candidate 不应被两个 source 改 TUNING。

---

## Decision 12: 凭据轮换 = `start_with_creds.sh --rotate` + 90 天强制

`scripts/okx/start_with_creds.sh --rotate` flag（与 freqtrade `--rotate` 一致）:
- 重写 config.toml
- audit log 写 `[okx-secret-rotate-NN]` durable-fact

90 天强制 rotate（与 D6 留存期一致）。在 audit log 提交时检查上次 rotate 时间，超期则警告（**不**强制拒，避免和工程节奏冲突）。

**理由**: 凭据轮换是 Keychain-based 凭据的**必填操作**；90 天是 industry baseline（PCI-DSS 6.3.4 90 天 rotate）。

---

## 引用

- ADR-0010: Freqtrade Dev MCP 整合（11 Decision 全部继承路径隔离 / crash-safe / Ponytail 排除）
- ADR-0003 D9: TUNING promotion gate（OKX 复用 + 扩展）
- ADR-0003 D10: `apply_tuning()` 竞态修复（OKX 不动 TUNING）
- ADR-0004: Ponytail 排除区（`app/services/okx/` 业务层执行）
- `docs/loop-state/outerloop-protocol.md` §7 Freqtrade Handshake + §8 OKX Handshake（待写）

---

**Status: Accepted** — Phase 0 baseline `[okx-baseline-01]` 已入库；
Phase 1A（依赖 + 凭据）可启动。

