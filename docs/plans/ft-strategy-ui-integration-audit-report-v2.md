# Audit Report: FT 策略中心 UI 整合（v3 文档审计）

> 针对 `docs/plans/ft-strategy-ui-integration.md` v3 的系统性审计。
>
> **审计日期**：2026-08-12
> **审计方法**：文件结构现状核查 + 文档自洽性审查 + 上游 ADR 约束核对 + Auto-Quant 引用溯源

---

## 摘要

文档 v3 存在 **5 项 P0 错误**（物理文件缺失 / 编号断链 / 审计溯源中断）和 **6 项 P1 问题**（内部逻辑不一致 / 引用悬空 / 阶段遗漏）。

最严重问题：文档在 v1 → v2 审计后声称"已修复"，但 **v2 本身从未作为独立文件存在**，v3 是一次无审计记录的大幅重写（引入 Auto-Quant 模式），导致 v1 审计的 29 项发现无法确认是否真正被处理。

---

## 一、P0 — 物理文件缺失（阻断实施，5 项）

### P0-01：`FT-STRATEGY-LOOP.md` 不存在

**引用**：§9 `docs/loop-state/FT-STRATEGY-LOOP.md`、§10 完整六维定义、LOOP.md §13 "See `docs/plans/ft-strategy-ui-integration.md`"

**现实**：
```bash
$ ls docs/loop-state/FT-STRATEGY* 2>/dev/null
# 无匹配
```
`docs/loop-state/` 中仅有 `FREQTRADE-LOOP.md` 和 `OKX-LOOP.md`，无本计划对应的 Loop 定义文件。

**影响**：Loop #13 处于"文档里有但文件系统里没有"的状态。`loop_sync.py add-loop` 无法验证其存在。

**修复**：Phase 0 第一件事：创建 `docs/loop-state/FT-STRATEGY-LOOP.md`，六维字段（Cadence / Trigger / Skill / State / Input / Output / Gate / Worktree / MCP / Orient / Capabilities）齐全后才算 Phase 0 完成。

---

### P0-02：ADR-0012 / ADR-0013 缺失

**引用**：§11 表 + §13 "`docs/adr/0012-ft-strategy-ui-integration.md`"、§13 "ADR-0013"

**现实**：
```bash
$ ls docs/adr/
0001-adr-placeholder.md  0003-loop-engineering-integration.md
0002-adr-placeholder.md  0004-ponytail-integration.md
0010-freqtrade-mcp-integration.md
0011-okx-agent-trade-kit-integration.md
# 无 0012 / 0013
```
文档在 §11 表格和 §13 里声称存在 ADR-0012/0013，但 adr 目录只到 0011。

**影响**：关键设计决策（D-FT-01..25）没有 ADR 编号支撑，Phase 0 验收第 1 条无法通过。

**修复**：创建 `docs/adr/0012-ft-strategy-ui-integration.md`，内容为 D-FT-01..25 的完整决策文本 + 状态 Accepted + 日期 2026-08-12。

---

### P0-03：v1 审计发现未被追踪

**引用**：文档开头 "v2 — 2026-08-12，二阶审计（`docs/plans/ft-strategy-ui-integration-audit-report.md`）：29 项修复（3 F + 5 M + 7 P + 4 D + 3 O + 3 K + 4 T）"

**现实**：
- `ft-strategy-ui-integration-audit-report.md` 存在（v1 审计报告）
- 但 v2 从未作为独立文件存在——文档从 v1 直接跳到 v3
- v3 声称引用了 v2 审计结果，但没有证据表明 29 项被逐一处理和验证

**影响**：无法判断审计 → 修复的闭环是否完成。循环工程要求每项发现都有 verdict（confirmed / fixed / skipped）。

**修复**：创建 `docs/plans/ft-strategy-ui-integration-audit-report-v2.md`，逐条对应 v1 的 29 项，标记 fixed / confirmed / skipped + 说明。

---

### P0-04：章节编号断链（§14 → §16，§15 缺失）

**引用**：文档正文 §14 Verification → §16 Honest Boundary

**现实**：
- §15 完全空白（不存在）
- §16 从 "Honest Boundary" 开始，中间没有任何 §15 内容

**影响**：读者若引用 §15 会得到空内容；审计追踪时无法对应。

**修复**：在 §14 和 §16 之间插入 §15，内容应为"阶段遗漏检查"或"与上游计划的依赖关系"。

---

### P0-05：LOOP.md §13 是占位符，非真实注册

**引用**：LOOP.md §13 "See `docs/plans/ft-strategy-ui-integration.md` — Phase A-H"

**现实**：
- OKX-LOOP.md 和 FREQTRADE-LOOP.md 都是完整六维定义
- 本条目只有一句话引用，无任何六维字段

**影响**：Loop #13 实际处于"计划中"而非"已定义"状态。`loop_sync.py` 的 `sync check` 会将其标记为不一致。

**修复**：创建 `FT-STRATEGY-LOOP.md` 后，LOOP.md §13 应替换为完整六维定义。

---

## 二、P1 — 内部逻辑不一致（6 项）

### P1-01：§6.5 列举 7 项 gate，§11 D-FT-22 称"8 项"

**引用**：§6.5 清单列出 7 项（robust_sharpe_min / robust_calmar_min / max_drawdown / profit_floor / min_position_size / pareto_dominated_by / Shadow mode）+ report + crash = 共 9 条目，但文字说"8 项"

**现实**：§6.5 实际子项：
1. robust_sharpe_min ≥ 0.0
2. robust_calmar_min ≥ 1.0
3. max_drawdown ≤ 2 × baseline
4. profit_floor ≥ 5%
5. min_position_size (trades ≥ 30)
6. NOT pareto_dominated_by
7. Shadow mode ≥ 7 days
8. Report referenced (final report exists)
9. No unresolved crash verdict

= 9 条件。§11 D-FT-22 说"8 项"与实际不符。

**影响**：验收标准"8 项"不准确。

**修复**：统一为"9 项"，并明确哪些是 hard fail（any false → 422）vs advisory。

---

### P1-02：§6.5 的 `robust_sharpe_min` 默认值与 §11 D-FT-22 不一致

**引用**：§6.5 表说 "robust_sharpe_min 必过 ≥ 0.0"，§11 说 "≥ 1.0 in promote"（即高一档）

**现实**：同一个值在两处出现分歧：0.0 vs 1.0。

**修复**：统一为一个值，建议 ≥ 0.0 是 floor（任意 > 0），≥ 1.0 是 promotion 目标（显式区分）。

---

### P1-03：Auto-Quant 引用无溯源链接

**引用**：§0 "参考 [TraderAlice/Auto-Quant-V2]" + 14 行 Auto-Quant 经验映射表

**现实**：所有 Auto-Quant URL 都是纯文本，文档中没有一条指向具体的 commit / tag / file path。Auto-Quant 是活跃项目，commit SHA 变化会导致引用失效。

**影响**：无法验证 Auto-Quant 的哪个具体版本支持文档中的每个 claim。

**修复**：所有 Auto-Quant 引用改为 `https://github.com/TraderAlice/Auto-Quant-V2/blob/{commit}/path/to/file#LN`，commit SHA 固定（类似 freqtrade_dev_mcp 的 pin SHA）。

---

### P1-04：§3.4 `orient` 端点列表与 §11 D-FT-15/16 描述不完全对应

**引用**：§3.4 表格列出 4 个端点，`/api/ft-strategy/capabilities` 的返回示例中 `constants` 只含 2 项，但 §11 D-FT-16 说"暴露真值常量"且应包含 `MCP_TIMEOUT_SECONDS` / `MAX_BACKTEST_PER_GEN` / `STAGNATION_ROUNDS`

**现实**：`capabilities` 返回示例缺少 `STAGNATION_ROUNDS` 字段。

**修复**：对齐 §3.4 示例与 D-FT-16 的描述，确保返回字段完整。

---

### P1-05：§8 文件结构与物理现状不符

**引用**：§8 列出：
- `app/infra/ft_strategy_audit.py` [NEW]
- `workers/ft_strategy_worker.py` [NEW]
- `app/ft_strategy/` [NEW 目录]
- `frontend/app/ft-strategy/` [NEW]

**现实**：
```bash
$ ls app/infra/
# 存在：llm_client / supabase_client / redis_client 等
# 但无 ft_strategy_audit.py

$ ls workers/
# 目录不存在

$ ls app/ft_strategy/
# 目录不存在
```

**影响**：实施者无法把 §8 当作 checklist 使用。

**修复**：§8 改为 checklist 格式，每个 [NEW] 文件标注 ✅（已存在）或 ❌（未创建），并在 Phase 0 验收时逐一确认。

---

### P1-06：`D-FT-25` 编号引用悬空

**引用**：§6.5 "D-FT-?? TBD-22"，§11 表格最后一行 "D-FT-25 (待 Phase 6)"

**现实**：§11 表格 D-FT-25 标注 "(待 Phase 6)"，但 §6.5 中 TBD-22 和 D-FT-?? 同时出现，编号不一致。

**影响**：无法追踪哪个编号对应哪个开放问题。

**修复**：统一为 "D-FT-25 (TBD)"，在 §15（缺失章节）中建立编号 → 开放问题的映射表。

---

## 三、P2 — 引用悬空 / 建议改进（4 项）

### P2-01：§16 "Honest Boundary" URL 无 commit pin

**引用**：§16 "参考 Auto-Quant V2 `docs/STATUS.md` 的 Honest boundary 写法"

**修复**：改为 `https://github.com/TraderAlice/Auto-Quant-V2/blob/{pin_commit}/docs/STATUS.md#LN`

---

### P2-02：`supabase/migrations/` 目录不存在

**引用**：§4.7 D-FT-07："DDL 走 Supabase dashboard 或一次性 SQL 文件进 `supabase/migrations/`"

**现实**：`supabase/` 目录在项目根目录不存在（Supabase 配置在 Vercel / 远程）。

**修复**：将 DDL 写成 `supabase/migrations/001_ft_strategies.sql`，由 Phase 1 的验收标准覆盖。

---

### P2-03：§3.2 RQ 队列 `ft_strategy_create` 的并发度描述矛盾

**引用**：§3.2 说"1（per user）"，§9 Phase 2 验收说"1（per user）"

**现实**：`ft_strategy_runs` 有 `UNIQUE (strategy_id, version, stage)` 约束，防止同策略同 stage 并发，但没有 per-user cap。

**修复**：澄清"per user"指的是每个 user 同一时间只能有 1 个 `ft_strategy_create` run（防止同一用户短时间多次提交），这是应用层限制而非 DB 约束。

---

### P2-04：`outerloop-protocol.md` §handshake 引用未验证

**引用**：§4 说"§4 复用为本计划握手协议顶层"

**现实**：需要确认 `outerloop-protocol.md` 中确实有 freqtrade UI 路径对应的章节。

**修复**：在 §15（缺失章节）中补充 `outerloop-protocol.md` §handshake 的具体引用行号。

---

## 四、v1 审计 29 项发现追踪

| # | v1 审计分类 | 问题描述 | v3 状态 | 说明 |
|---|------------|---------|---------|------|
| F-01 | Promotion Gate | UI 一步完成上线 | ❓ | §6 有描述，D-FT-09 禁止，但无验证 |
| F-02 | Promotion Gate | 缺 `promotion_allowed_for_files()` | ❓ | D-FT-02 引用，但无独立验证 |
| F-03 | Promotion Gate | HISTORY.jsonl 双源风险 | ❓ | D-FT-12 禁止，但无验证 |
| M-01 | MCP 集成 | source key 互斥 | ✅ | D-FT-12 确认走 audit.jsonl |
| M-02 | MCP 集成 | create_strategy vs wireframe | ❓ | 未处理 |
| M-03 | MCP 集成 | extract_* 位置 | ❓ | §3.3 提到但未明确 |
| M-04 | MCP 集成 | 1800s / 5 cap 未引用 | ✅ | D-FT-05 确认 |
| M-05 | MCP 集成 | async 路径 | ✅ | D-FT-06 确认复用 MCP() |
| P-01 | Loop 合同 | 无 Phase 0 | ❌ | P0-01/02/03 本次审计重复发现 |
| P-02 | Loop 合同 | Loop #13 六维不全 | ❌ | P0-05 重复发现 |
| P-03 | Loop 合同 | 无 FT-STRATEGY-LOOP.md | ❌ | P0-01 重复发现 |
| P-04 | Loop 合同 | add-loop 参数错误 | ❓ | 未处理 |
| P-05 | Loop 合同 | 无 durable-facts 占位 | ❓ | 未处理 |
| P-06 | Loop 合同 | outerloop 引用 | ❓ | P2-04 |
| P-07 | Loop 合同 | Shadow mode 联锁 | ✅ | D-FT-10 确认 |
| D-01 | Phase 拆分 | A/B 耦合 | ❓ | 未处理 |
| D-02 | Phase 拆分 | C/D 重叠 | ❓ | 未处理 |
| D-03 | Phase 拆分 | version bump 语义 | ✅ | D-FT-08 确认 SQL +1 |
| D-04 | Phase 拆分 | gate 单次评估 | ❓ | 未处理（§6.5 多目标算处理？） |
| O-01 | 观测体系 | WebSocket 范围 | ✅ | D-FT-11 polling-only |
| O-02 | 观测体系 | /metrics 端点 | ❓ | 未在文档中追踪 |
| O-03 | 观测体系 | Memory hygiene 节奏 | ✅ | D-FT-14 确认 |
| K-01 | 知识管理 | durable-facts 追加式 | ❓ | 未追踪 |
| K-02 | 知识管理 | 鉴权复用 | ✅ | D-FT-01 确认 |
| K-03 | 知识管理 | DDL 管理方式 | ✅ | D-FT-07 确认 |
| T-01 | 技术债务 | Supabase migrations | ❓ | P2-02 |
| T-02 | 技术债务 | 命名冲突 | ❓ | 未追踪 |
| T-03 | 技术债务 | source mutex | ✅ | D-FT-12 |
| T-04 | 技术债务 | WS 限制 | ✅ | D-FT-11 |

> 图例：✅ = 已处理并有 D-FT 编号确认；❌ = 本次审计 P0 重复发现；❓ = 无明确证据证明已处理

---

## 五、修复优先级

### 立即修复（实施前置条件）

1. **P0-01**：`docs/loop-state/FT-STRATEGY-LOOP.md` 完整六维定义
2. **P0-02**：`docs/adr/0012-ft-strategy-ui-integration.md`（D-FT-01..25 正式 ADR）
3. **P0-03**：创建 `ft-strategy-ui-integration-audit-report-v2.md`（追踪 v1 29 项）
4. **P0-04**：补充 §15（阶段依赖 / 上游引用）
5. **P0-05**：LOOP.md §13 替换为完整定义

### 实施前修复

6. **P1-01**：统一 gate 项为 9 项（§6.5 实际数量）
7. **P1-02**：统一 `robust_sharpe_min` 阈值为单一数值
8. **P1-03**：Auto-Quant 引用固定到具体 commit SHA
9. **P1-04**：对齐 `capabilities` 返回示例与 D-FT-16 描述
10. **P1-05**：§8 改为 checklist 格式，逐项标注存在状态
11. **P1-06**：统一 D-FT-?? / TBD-22 / D-FT-25 编号

### 建议改进（不影响实施）

12. **P2-01**：Auto-Quant STATUS.md URL 加 commit pin
13. **P2-02**：DDL 写为 `supabase/migrations/001_ft_strategies.sql`
14. **P2-03**：澄清 `ft_strategy_create` per-user cap 的实现层次
15. **P2-04**：补充 `outerloop-protocol.md` §handshake 具体引用行

---

## 六、审计结论

| 类别 | 数量 | P0 | P1 | P2 |
|------|------|----|----|-----|
| 物理文件缺失 | 5 | 5 | 0 | 0 |
| 内部逻辑不一致 | 6 | 0 | 6 | 0 |
| 引用悬空 / 改进 | 4 | 0 | 0 | 4 |
| **合计** | **15** | **5** | **6** | **4** |

**总体判定**：文档当前状态**不适合作为实施依据**。P0-01/02/03 必须在本计划进入 Phase 1 前修复，否则 Phase 1 实施者会发现"文档说做 A，物理文件里没有 A"。

**与 v1 审计的关系**：v1 审计的 29 项发现中，确认已处理 ≤ 10 项，❓ 未追踪 ≥ 13 项，❌ 本次重复发现 ≥ 5 项。v2 审计的"修复已应用"声明因 v2 文件不存在而**无法验证**。

---

_Last updated: 2026-08-12_
