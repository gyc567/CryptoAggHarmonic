# Audit Report — Freqtrade Dev MCP 整合

> Loop Engineering 视角对 `docs/plans/freqtrade-mcp-integration.md` 的二阶审计。
> 参考：`docs/loop-engineering-plan.md` §16 审计范式、`docs/loop-state/LOOP.md`、
> `docs/loop-state/gate.yaml`、`AGENTS.md` North Star + Ponytail 约束范围。
>
> 审计日期：2026-08-11  
> 审计者：loop-audit (auto)  
> 标的版本：plan v1（PLANS.md 登记在案，未落地代码）

---

## 0. 审计摘要

| 维度 | 评分 | 备注 |
|------|------|------|
| 与已有 loop-engineering 框架的一致性 | **D** | 与 ADR-0003 Decision 9/10、`tuning_promotion.py` 已存在事实冲突 |
| 路径 / 命名 / Denylist 合规 | **C** | 1 处 denylist 违规（LOOP.md 列入 Modify），2 处命名冲突 |
| L 等级成熟度目标合理性 | **F** | 项目已在 L3 (100/100)，计划却瞄准 L2 — YAGNI 倒退 |
| 安全门（drawdown / shadow / 回滚） | **D** | 缺 drawdown guardrail、shadow mode、回滚路径 |
| 反馈环闭合度 | **D** | hyperopt → Pareto/HISTORY 写入路径未定义 |
| 凭据 / 依赖治理 | **D** | 无版本 pin、无 license 审查、无凭据管理器接入 |
| 验证完整性 | **C** | 5 项验证，缺端到端回环与 gate-violation 自动化测试 |

**总体结论**：**不通过**。在 P0/P1 问题修复前不应进入 Phase 2。最低修复集见 §6。

---

## 1. 与现有基础设施的冲突（事实层）

### F1. `freqtrade_promotion.py` 与已存在的 `tuning_promotion.py` 重复

**事实**：`app/loop/tuning_promotion.py` 已落地（48 行），含 `promotion_allowed_for_files()`、
`is_live_tuning_path()`、`promotion_checklist()`，正是 ADR-0003 Decision 9 的代码实现。

**计划第 30 行**：`Create app/loop/freqtrade_promotion.py (TUNING gate, 强制不允许直接 apply_tuning)`。

**冲突**：两份 gate 在语义上完全重叠（都是"不允许直接改 live TUNING"），将形成
两套并行的 promotion 路径，需要人工协调谁生效。

**修复**：删除 `freqtrade_promotion.py` 计划。复用 `tuning_promotion.py` + 在
`docs/adr/0010-freqtrade-mcp-integration.md` 中声明"freqtrade hyperopt 结果
经 `tuning_promotion.promotion_allowed_for_files()` 拦截"。

### F2. `docs/loop-state/LOOP.md` 出现在 Modify 列表 — 违反 denylist

**事实**：`docs/loop-state/gate.yaml` 第 16 行将 `docs/plans/` 列入 denylist，
且 `LOOP.md` 自身声明 "由 `loop/loop_sync.py` 与本文件保持一致"（即由 sync 工具自动维护，
不是手工修改）。LOOP.md 同样不在 denylist 中，但惯例是循环定义文件由 sync 工具生成，
手工 PR 应只改 `docs/plans/` 下的计划文件。

**计划第 120 行**：`Modify docs/loop-state/LOOP.md — 增加 Freqtrade Strategy Loop`。

**冲突**：手工 PR 修改 LOOP.md 会绕过 `loop/loop_sync.py` 一致性检查。

**修复**：
- 在 `docs/plans/freqtrade-mcp-integration.md` 的 Phase 3 增加一项："通过
  `loop/loop_sync.py add-loop` 命令注册 Freqtrade Strategy Loop"
- 删除 "Modify docs/loop-state/LOOP.md" 任务

### F3. `app/loop/` 是 Ponytail 排除区 — 翻译层放错位置

**事实**：`LOOP.md` "Ponytail Integration" 节明确：
- ❌ `app/loop/`（CMA-ES 信号搜索）— 不接受 ponytail 简化
- ✅ `app/services/`、`app/api/`、`loop/`（CLI）

**计划**：`app/loop/signal_to_freqtrade.py` + `app/loop/freqtrade_discovery.py` +
`app/loop/freqtrade_integration_state.py`（共 3 个文件）放入 `app/loop/`。

**冲突**：
1. `signal_to_freqtrade.py` 是 domain translation（HarmonicSignal → IStrategy），
   属于业务逻辑，**不属于交易循环驱动**，应放 `app/services/` 或新 `app/services/freqtrade/`。
2. `app/loop/freqtrade_integration_state.py` 与现有 `app/loop/state.py` 命名冲突，
   会让读者误以为是同一类。
3. Ponytail 永远不会审查这些新文件，违背 AGENTS.md "代码质量标准"。

**修复**：
- `app/services/freqtrade/translator.py`（替代 `app/loop/signal_to_freqtrade.py`）
- `app/services/freqtrade/mcp_client.py`（替代 `app/loop/freqtrade_discovery.py`）
- 状态管理直接复用 `app/loop/state.py` + `.scratch/loop_state/freqtrade/` 子目录，
  不新建 `freqtrade_integration_state.py`

### F4. 项目已在 L3 (100/100)，计划却瞄准 L2

**事实**：`docs/loop-state/STATE.md` 第 105 行：
> **Loop readiness**: L3 (100/100) — daily-triage loop + harness foundry initialized today.

11 个 GitHub Actions workflow 全部存在（audit、changelog-drafter、ci-sweeper、ci、
code-health-audit、daily-triage、debt-harvesting、dependency-sweeper、issue-sync、
issue-triage、post-merge-cleanup、pr-babysitter）。

**计划第 4 行（Goals）**：`freqtrade-strategy-loop.yml 上线（L2 辅助模式）`。

**冲突**：项目已 L3，新循环从 L1 起步合理，但目标是 L2 反而倒退。

**修复**：将 loop 目标改为 **L3**（与其他 9 个 loop 对齐 — 见 F2 修复后注册为
loop #10），并在 `FREQRADE-LOOP.md` 定义中声明 "Cadence: event-driven,
Gate: human-in-the-loop, MCP: read-write with promotion gate"。

---

## 2. 缺失的关键设计要素

### M1. 无 hyperopt → cryptoagg 反馈环协议

**计划第 10 行**：`结果反馈给 cryptoagg 调参`。

**问题**：hyperopt 结果**如何**写回 `app/loop/`？当前未定义：
- 写入 `HISTORY.jsonl` 哪条 schema？与现有 accepted/rejected decision 字段如何对齐？
- 写入 `PARETO.json` 是否触发 5-D 前沿更新？4-D/5-D 迁移已完成（`loop-engineering-plan` §15 问题 4），
  freqtrade fitness 是 5 维（win_rate / Sharpe / Calmar / max_drawdown / trade_count）
  与现有 fitness 空间是否同维？
- 是否走 `suspicious_to_human` → `pending_issues/` 路径（`loop-engineering-plan` §6.2 已设计）？
- salt 是否在 freqtrade 候选上重新生成？

**修复**：在 `docs/loop-state/outerloop-protocol.md` 新增"§7 Freqtrade Handshake"节，
定义：
- 文件格式：`freqtrade_hyperopt_results/{gen}.yaml`（已有）→ 解析为 `Candidate` 对象
- 决策路径：与 `app/loop/maker_checker/arbiter.py` 的 `MergeResult` 对齐
- 写入位置：`.scratch/loop_state/HISTORY.jsonl` 新增 `source: "freqtrade_hyperopt"` 字段
- 不允许的路径：直接修改 `app/config/tuning.py`（已在 gate.yaml denylist）

### M2. 缺 Drawdown Guardrail

**事实**：`loop-engineering-plan.md` §16.13 明确要求 drawdown guardrails：
> `max_drawdown < 2x baseline` 才允许 promotion
> `Calmar ratio > X` 才允许 promotion

**计划**：完全未提 drawdown / Calmar 约束。`promotion_checklist()` 仅说"Review backtest metrics"，
无量化门。

**修复**：在 `tuning_promotion.promotion_checklist()` 中追加：
- `[ ] max_drawdown ≤ 2 × baseline_drawdown`
- `[ ] Calmar ratio ≥ 阈值（待 Phase 0 基线测量确定）`
- `[ ] Shadow mode 运行 N 天无回撤异常`

### M3. 缺 Shadow Mode / Paper Trading 过渡层

**事实**：freqtrade 支持 dry-run / live 两种模式。直接 dry-run → live 跳变是
cryptoagg 这类 SaaS 的常见失误来源。

**修复**：在 Phase 3 之后追加 Phase 4 "Shadow Mode（1-2 周）"：
- freqtrade 启用 dry-run，与 live 并行 7 天
- 比较 dry-run 信号 vs live 实际成交差异
- 仅在差异 < 阈值时允许切 live

### M4. 缺凭据管理方案

**事实**：`AGENTS.md` "凭据：只走凭据管理器" 规则禁止硬编码 / 配置文件 / 日志输出凭据。

**计划**：仅提 `FREQTRADE_MCP_PATH` 环境变量。freqtrade 实际运行需要：
- Exchange API key/secret（binance / okx 等）
- freqtrade 配置文件 `user_data/config.json` 中的 `exchange.key` / `exchange.secret`
- MCP server 可能需要的 API key（如果 freqtrade_dev_mcp 内部用了外部 LLM）

**修复**：在 Phase 1 增加：
- 在凭据管理器新建条目：`freqtrade-exchange-key`、`freqtrade-exchange-secret`、
  `freqtrade-mcp-token`（如有）
- 启动脚本从凭据管理器读取并写入临时文件（chmod 600），不写入 repo
- 增加 pre-commit hook 检查 `user_data/config.json` 不在 git 中

### M5. 缺依赖治理

**计划第 26 行**：`克隆 freqtrade_dev_mcp 到项目根目录 freqtrade_dev_mcp/`。

**缺失**：
- 第三方仓库 `github.com/gyc567/freqtrade_dev_mcp` 的 license 未审查
- commit SHA 未 pin（应 pin 到具体 commit 或 tag）
- 依赖列表（freqtrade、ta-lib、pandas-ta 等大件）未审计
- 安全扫描（`pip-audit`）未列入验收

**修复**：Phase 1 增加：
- `[ ] 审查 freqtrade_dev_mcp LICENSE，确认为 MIT/Apache/BSD`
- `[ ] pin 到具体 commit SHA（非 main 分支最新）`
- `[ ] 记录依赖清单到 docs/adr/0010 中`
- `[ ] 运行 pip-audit freqtrade_dev_mcp/ 提交结果`

### M6. ADR-0010 仅是 TODO，无草案

**计划第 32 行**：`Create docs/adr/0010-freqtrade-mcp-integration.md（ADR）`。

**缺失**：计划本身不含 ADR 草案内容，违反 loop-engineering-plan §13 模式
（ADR-0003 直接列了 10 个 Decision）。

**修复**：在 Phase 1 完成前，至少给出 Decision 候选：
- D1：复用 `tuning_promotion.py`，不新建 `freqtrade_promotion.py`
- D2：翻译层放 `app/services/freqtrade/`，不放 `app/loop/`
- D3：freqtrade loop 目标 L3（非 L2）
- D4：hyperopt 结果走 HISTORY.jsonl（`source: freqtrade_hyperopt`），不直接改 TUNING
- D5：drawdown / Calmar guardrails 列入 promotion checklist
- D6：shadow mode 1 周过渡期
- D7：依赖 pin commit SHA + license 审查

### M7. 缺 Loop #10 完整定义

**事实**：`LOOP.md` 现 9 个循环，每个含 Cadence / Trigger / Skill / State / Gate / Output 六维。

**计划**：`docs/loop-state/FREQTRADE-LOOP.md` 仅作"loop 定义文档"提及，无六维定义草案。

**修复**：在 Phase 1 完成前给出六维草案（沿用 LOOP.md 表格格式）。

### M8. 缺回滚路径

**问题**：freqtrade 整合上线后回滚策略未定义：
- 删除 `freqtrade_dev_mcp/` 是否会让 cron / workflow 崩溃？
- `app/services/freqtrade/` 移除后依赖它的代码如何处理？
- `app/config/tuning.py` 在 freqtrade 路径下若被误改，recovery 流程是什么？

**修复**：Phase 3 验收增加：
- `[ ] 删除 freqtrade_dev_mcp/ 后，CI/workflow 不崩溃（graceful skip）`
- `[ ] freqtrade-strategy-loop.yml 在缺失 server 时 exit 0 with warning`
- `[ ] 回滚 PR 模板：移除 4 个新文件 + 1 个 workflow，不修改 tuning.py`

### M9. 缺 MCP 调用限速与超时

**问题**：12 个 MCP tools 在 cron 中无脑轮询可能：
- 触发 freqtrade_dev_mcp 上游 rate limit
- 单次 backtest 跑几小时未设超时，会卡死 workflow runner（GitHub Actions 默认 6h 上限）

**修复**：
- 每个 MCP tool 调用设 `timeout_seconds=1800`（30 分钟硬超时）
- 单 generation 最多 5 个 backtest 候选，避免单次 cron 跑过夜
- 增加 `mcp_call_timeout_total` 指标到 `/metrics`

### M10. 缺测试用例清单

**事实**：`AGENTS.md` "100% test coverage for new code"。

**计划**：0 个测试用例。

**修复**：在 Phase 2 增加测试：
- `tests/services/freqtrade/test_translator.py`（HarmonicSignal → IStrategy 往返）
- `tests/services/freqtrade/test_mcp_client.py`（tool discovery + 错误传播）
- `tests/loop/test_freqtrade_handshake.py`（hyperopt yaml → HISTORY.jsonl 写入）
- 端到端：mock freqtrade_dev_mcp subprocess，验证 round-trip

---

## 3. Phase 排序与依赖问题

### P1. Phase 1 验收与 Phase 3 验证错位

**计划第 46 行**（Phase 3）：`验证 TUNING promotion gate 生效（freqtrade hyperopt 结果不直接修改 TUNING）`

**问题**：gate 验证放在 Phase 3，但 gate 本身在 Phase 1 就创建。中间 Phase 2 的所有
代码改动都没有 gate 保护，是 **2 周无 gate 真空期**。

**修复**：将 gate 验证移到 Phase 1 验收（`pytest tests/loop/test_tuning_promotion.py`），
Phase 3 只验证 freqtrade-specific 场景。

### P2. Phase 3 "更新 AGENTS.md + CLAUDE.md" 是 denylist 边缘

**事实**：`docs/plans/` 在 denylist，但 `AGENTS.md` / `CLAUDE.md` 不在 denylist。

**问题**：plan 修改本身就是 denylist 操作（"plan 修改由人类维护"），但 plan 又要求
"plan 完成后更新 AGENTS.md" — 形成 plan-driven AGENTS.md 修改链，缺乏 review gate。

**修复**：把"更新 AGENTS.md + CLAUDE.md"任务移出 Phase 3，作为独立 ADR 提交，
PR 标题前缀 `[docs-only]`，要求人工 review。

### P3. 缺 Phase 0 基线

**对比**：`loop-engineering-plan.md` §11 有完整 Phase 0（基线指标采集），
本计划直接跳到 Phase 1。

**修复**：在 Phase 1 之前增加 Phase 0：
- `[ ] 关闭 freqtrade 路径前，测量 cryptoagg 现状：信号转化率、回测命中率、gunicorn worker 内存`
- `[ ] 记录 baseline 到 docs/loop-state/durable-facts.md [freqtrade-baseline-01]`

---

## 4. 文档/格式问题（次要）

### D1. Architecture ASCII 图与现有 §6 重复

`loop-engineering-plan.md` §6 已有 Outerloop 协议 ASCII 图。本计划第 53-79 行
又画一份 Signal → Strategy 翻译层图，与 §6 不一致且未交叉引用。

**修复**：在 Architecture 节首行加 `> 详见 loop-engineering-plan.md §6 Outerloop 协议`，
删除重复 ASCII，仅保留 freqtrade-specific 的"TUNING Promotion Gate"小节。

### D2. "Not Modified" 列表不完整

**计划第 128-131 行**：列出 `app/loop/driver.py` 等 3 项。

**修复**：交叉引用 `loop-engineering-plan.md` §3 文件结构全表，删除本节（DRY）。

### D3. 验证项 3 与 §2.1 重复

`python -m loop.loop gate check .` 已在 loop-engineering-plan §14.2 中验证过，
本计划再次列出。

**修复**：删除验证项 3（已被上游 plan 覆盖）。

### D4. "Architecture" 节位置错误

按 PLANS.md 模板："Context / Goals / Tasks / Verification" — Architecture 不在模板中。
本计划把它放在 Tasks 之后、Files 之前 — 顺序合理但与模板不符。

**修复**：可保留（信息有用），但在节首加 `> 非模板节，仅为设计参考`。

### D5. "12 MCP tools" 无引用源

**计划第 8 行**：freqtrade_dev_mcp 提供 12 个 MCP tools（策略生成、回测、超参优化）。

**问题**：未给链接、未给 commit、未给版本。读者无法验证。

**修复**：在 Goals 节补：
- `[ ] 列出 12 MCP tools 的实际名称、参数 schema（来自 freqtrade_dev_mcp/src/server.py）`
- `[ ] 在 ADR-0010 中标注 commit SHA + 文档链接`

---

## 5. Loop Engineering 兼容性检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 路径 denylist 合规（gate.yaml） | ⚠️ | F2 违规：LOOP.md 列入 Modify |
| Ponytail 约束范围 | ⚠️ | F3 违规：3 文件放入排除区 |
| ADR 编号连续性 | ✅ | 0003/0004 已用，0010 合理（0005-0009 待补或跳过） |
| 命名空间隔离 | ⚠️ | F1 + F3：与现有 `tuning_promotion.py` / `state.py` 冲突 |
| 状态文件位置（gitignore） | ✅ | `.scratch/loop_state/freqtrade/` 在 gitignore |
| 自动合并白名单合规 | ✅ | 新文件不触发自动合并 |
| Salt 管理策略 | ⚠️ | 未提 freqtrade 候选的 salt 处理（应复用 maker_checker/salt_store） |
| Memory Engineering 兼容性 | ⚠️ | 未提 Durable Facts / Episodic 更新 |
| Token Budget 强制执行 | ⚠️ | MCP 调用未列入成本核算 |
| Crash-safe / outbox 模式 | ⚠️ | 未提 freqtrade workflow 中途崩溃恢复 |

---

## 6. 最低修复集（Minimum Patch Set）

要进入 Phase 2，以下 8 项必须在 Phase 1 完成：

1. **删除 `freqtrade_promotion.py` 任务**，复用 `tuning_promotion.py`（F1）
2. **删除 "Modify docs/loop-state/LOOP.md" 任务**，改走 `loop/loop_sync.py add-loop`（F2）
3. **翻译层 3 个文件移至 `app/services/freqtrade/`**（F3）
4. **loop 目标改为 L3**，与现有 9 个 loop 对齐（F4）
5. **定义 hyperopt → HISTORY.jsonl 写入协议**（M1）
6. **drawdown / Calmar guardrails 列入 promotion checklist**（M2）
7. **凭据管理：freqtrade exchange key/secret 走凭据管理器**（M4）
8. **freqtrade_dev_mcp 依赖 pin commit SHA + license 审查**（M5）

外加 2 项强烈建议：
9. **Phase 0 基线测量**（P3）— 与 loop-engineering-plan 对齐
10. **shadow mode 1 周过渡期**（M3）— 降低上线风险

---

## 7. 与原始计划的差异清单（审计补丁）

| # | 优化项 | 审计来源 |
|---|--------|---------|
| 1 | 删除 `freqtrade_promotion.py`，复用 `tuning_promotion.py` | F1 |
| 2 | `LOOP.md` 改走 `loop/loop_sync.py` 而非手工 PR | F2 |
| 3 | 翻译层 3 文件从 `app/loop/` 移至 `app/services/freqtrade/` | F3 |
| 4 | loop 目标 L2 → L3（与项目现实对齐） | F4 |
| 5 | hyperopt → HISTORY.jsonl 反馈协议（M1） | M1 |
| 6 | drawdown / Calmar guardrails（M2） | M2 |
| 7 | shadow mode 1 周过渡期（M3） | M3 |
| 8 | 凭据管理器接入 freqtrade exchange key（M4） | M4 |
| 9 | freqtrade_dev_mcp 依赖 pin + license（M5） | M5 |
| 10 | ADR-0010 草案内容（M6） | M6 |
| 11 | Loop #10 六维定义（M7） | M7 |
| 12 | 回滚路径（M8） | M8 |
| 13 | MCP 调用超时 + 单代上限（M9） | M9 |
| 14 | 100% 测试覆盖清单（M10） | M10 |
| 15 | Phase 1 gate 验证前置（P1） | P1 |
| 16 | AGENTS.md/CLAUDE.md 更新走独立 ADR PR（P2） | P2 |
| 17 | Phase 0 基线测量（P3） | P3 |
| 18 | Architecture 节交叉引用 upstream plan（D1） | D1 |
| 19 | "12 MCP tools" 引用源（D5） | D5 |

---

## 8. 审计签名

- 审计方法：loop engineering 二阶审计（与 `loop-engineering-plan.md` §16 同模式）
- 审计输入：`docs/plans/freqtrade-mcp-integration.md` v1 + `PLANS.md` +
  `LOOP.md` + `gate.yaml` + `STATE.md` + `app/loop/tuning_promotion.py` + `app/loop/state.py`
- 审计者：loop-audit (auto)
- 后续行动：本审计报告归档至 git history；plan 作者按 §6 最低修复集修订 v2

---

_Last updated: 2026-08-11_
