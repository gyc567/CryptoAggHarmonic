# Ponytail × Loop Engineering 整合方案

> 分析日期：2026-08-06
> 审计版本：v2（针对 v1 方案进行审计优化）
> 前提：已安装 ponytail skills（`.claude/skills/ponytail*`），已有完整 loop-engineering 基础设施（L3，100/100）

---

## 审计发现（v1 方案问题）

以下问题在 v2 方案中已全部修正：

| # | v1 方案问题 | 审计结论 | v2 修正 |
|---|-----------|---------|---------|
| A1 | `patterns/registry.yaml` 引用 `skills/ponytail-audit`，但这些 skill 在 `.claude/skills/` 而非 `skills/` | **架构性错位**：skill 注册路径与实际路径不匹配 | ponytail skills 保留在 `.claude/skills/`（slash 命令式）；不修改 registry；新增循环使用 `github-script` 而非 skill |
| A2 | `ponytail-daily`（每日检查当前 diff）| **YAGNI**：diff 存在时才需要 ponytail，cron 检查无意义 | 删除 |
| A3 | `ponytail:` 注释依赖人工编写，Debt Harvesting 假设注释已存在 | **前提不成立**：代码库里没有 `ponytail:` 注释，Debt Harvesting 永远收不到数据 | Debt Harvesting 改为"代码行数趋势报告"，不依赖注释 |
| A4 | PR Babysitter 评论用 checklist 违反 ponytail 精神 | **建议本身过度工程化** | 删除 checklist，只保留一句话 bloat 警告 |
| A5 | Ponytail Debt 的 `Status` 字段与 Durable Facts 的 `superseded_by` 重复 | **字段冗余** | 统一用 `superseded_by`，不需要 Status |
| A6 | `ponytail-audit` 全量扫描成本高（上次 136K tokens）| **资源浪费**：每周全量扫没有增量价值 | 改为增量 diff 扫描（只扫最近一周变更的文件） |
| A7 | 方案说 `ponytail-review` 可以替代 `loop-cleanup` | **功能错配**：`ponytail-review` 查代码体积，`loop-cleanup` 查临时文件/死代码 | 两者互补，不替代 |
| A8 | `ponytail-review` 调查结果需要人工验证 | **安全要求**：上次审计把 ADR-0003 要求的 `strategy_version.py` 重命名误判为"重复文件" | 循环输出加 `⚠️ 需要人工确认` 前缀 |
| A9 | `app/loop/` 排除范围不完整 | **遗漏**：`bench/`、`tests/` 未说明 | 明确排除列表 |
| A10 | `ponytail ultra` 删除测试的规则与 `AGENTS.md` 100% 覆盖要求冲突 | **规则冲突** | ponytail 约束范围不含 `tests/`，ultra 不适用测试代码 |

---

## 一、两个系统的关系分析

### 1.1 系统定位对比

| 维度 | Loop Engineering | Ponytail |
|------|----------------|-----------|
| **解决的问题** | 开发流程自动化（哪些事要重复做） | 代码质量标准（做这件事用什么最小路径） |
| **作用层次** | **流程层** — 循环、调度、状态持久化 | **执行层** — 每次写代码时的决策约束 |
| **触发方式** | 时间驱动（cron）或事件驱动（PR opened） | 人机交互驱动（`/ponytail` 命令）或循环触发 |
| **输出** | Issue/PR 评论、状态文件更新、自动合并 | 更少的代码、更短的 diff |
| **成熟度模型** | L1 报告 → L2 建议 → L3 自动 | lite → full → ultra（强度档位） |
| **记忆系统** | 四层（Scratch/Episodic/Durable/Retrieved） | 无持久化（ponytail-debt 是按需生成） |

**本质关系**：Loop Engineering 是节奏控制，Ponytail 是体积控制。两者正交，叠加增益。

### 1.2 约束范围界定（关键）

Ponytail 的 YAGNI 阶梯有明确的**不适用区域**：

```
┌─────────────────────────────────────────────────────────────┐
│ Ponytail 适用区域                                            │
│  app/services/   — 业务逻辑                                 │
│  app/api/        — API 路由和中间件                         │
│  loop/           — CLI 工具（loop.py 等）                   │
│  skills/         — 项目级 skills                           │
│  patterns/        — 循环模式注册                           │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ Ponytail 不适用区域（明确排除）                               │
│  app/loop/       — CMA-ES 信号搜索、参数探索（科学实验）    │
│  bench/          — Backtest harness（实验代码）            │
│  tests/           — 测试代码（YAGNI 不适用于测试，见 AGENTS.md）││
│  .claude/         — Agent 记忆和配置                       │
│  .scratch/        — 运行时临时状态                         │
└─────────────────────────────────────────────────────────────┘
```

**规则**：ponytail 的 ultra 档位对 `tests/` 同样不适用。`AGENTS.md` 要求 100% 测试覆盖，ponytail 的"删除测试"建议被安全护栏拦截。

### 1.3 协同增益点

| Ponytail 能力 | 增强的 Loop Engineering 组件 |
|--------------|------------------------------|
| `/ponytail-audit` | CI Sweeper → 失败分类增加"over-engineering 导致的复杂度"维度 |
| `/ponytail-audit` | Daily Triage → 代码健康度趋势报告（行数净减少） |
| `/ponytail-review` | PR Babysitter → 增加一句话 bloat 警告（非 checklist） |
| `/ponytail-debt`（增量版）| Memory Hygiene → 代码行数趋势作为 Durable Facts 追踪 |
| Ponytail 规则 | 所有循环的文本输出遵循最短表述原则 |

---

## 二、Ponytail 在 Loop Maturity 模型中的位置

Ponytail **不是**一个 Loop，是叠加在所有循环上的**输出质量层**。

```
┌──────────────────────────────────────────────────────────────┐
│               Ponytail（输出质量约束层）                        │
│                                                              │
│  Every loop output: 遵循最短表述原则                          │
│  Every skill rule: 最小化 diff 约束                         │
│  Every audit:     增量扫描 + 人工确认前置                    │
└──────────────────────────────────────────────────────────────┘
                            ↕
┌──────────────────────────────────────────────────────────────┐
│               Loop Engineering（流程自动化层）                  │
│                                                              │
│  L1: Daily Triage / Issue Triage / Post-Merge / Changelog    │
│  L2: PR Babysitter / CI Sweeper / Dependency Sweeper          │
│  L3: Trading Signal Loop (app/loop/)                          │
└──────────────────────────────────────────────────────────────┘
                            ↕
┌──────────────────────────────────────────────────────────────┐
│               Memory Engineering（记忆持久层）                  │
│                                                              │
│  Scratch → Episodic → Durable Facts → Retrieved                │
│  代码行数趋势（来自 ponytail-audit） → Durable Facts          │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、新增循环设计

### 循环 8：Code Health Audit（L1）

**背景**：ponytail-audit 全量扫描发现 ~2400 行可精简代码。但全量扫描成本高（136K tokens/次），且上次审计包含误判（把 ADR-0003 要求的重命名判断为"重复文件"）。改为**增量 diff 扫描**更实用。

**增量扫描逻辑**：
1. 读取上次 audit 的 commit hash
2. 计算从该 commit 至今的 diff 范围
3. 只扫描变更触及的文件（排除 `app/loop/`、`bench/`、`tests/`）
4. 人工确认环节：所有发现标注 `⚠️ 需要人工确认`

| 属性 | 值 |
|------|---|
| **Cadence** | 每周日 10:00 UTC（低峰期） |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `.claude/skills/ponytail-audit`（slash 命令，通过 `gh script` 调用） |
| **State** | `docs/loop-state/STATE.md`（记录上次 commit hash） |
| **输入** | 全仓库 diff（自上次 audit 以来变更的文件） |
| **输出** | GitHub Issue 草稿（`code-health` 标签） |
| **Gate** | L1 — 报告模式，人类决定是否采纳；所有发现带 `⚠️ 需要人工确认` |
| **Scope** | `app/services/`、`app/api/`、`loop/`（CLI）、`skills/`、`patterns/` |

**Ponital Debt 追踪替代方案**：不依赖 `ponytail:` 注释，改为追踪**代码行数趋势**：
- 每周记录 `cloc` 或 `wc -l` 结果
- 作为 Durable Facts 追加到 `docs/loop-state/durable-facts.md`
- 趋势持续恶化（如连续 4 周净增行数）才触发 issue

### 循环 9：Debt Harvesting（增强版，L1）

**v1 问题**：原方案依赖代码中已有的 `ponytail:` 注释，但代码库里目前没有这类注释。

**v2 方案**：Debt Harvesting 改为**代码行数债务报告**，不依赖注释：

| 属性 | 值 |
|------|---|
| **Cadence** | 每月 1 日（与版本 release 对齐） |
| **Skill** | `.claude/skills/ponytail-debt` |
| **触发条件** | GitHub Actions schedule 或手动 |
| **输入** | `docs/loop-state/durable-facts.md` 中的代码行数趋势 |
| **输出** | `PONYTAIL-DEBT.md`（债务报告）+ Durable Facts 追加 |
| **Gate** | L1 — 报告模式，人类决定是否处理 |
| **格式** | 按文件/模块列出 top 5 体积增长，不依赖注释 |

**说明**：`ponytail:` 注释是开发习惯问题，不是循环能强制要求的。Debt Harvesting 改为追踪行数趋势后，可操作性强，也符合 ponytail"减少代码"的核心目标。

### 循环 10（增强）：PR Babysitter + Ponytail 警告（L2）

**现状**：PR Babysitter 检查 CI 状态和 blocking 原因，不检查代码体积。

**增强设计**：PR 打开时，在评论底部追加一句话 bloat 警告（非 checklist，遵循 ponytail 最短表述原则）：

```
### Code Health (ponytail)
⚠️ diff 超过 300 行时请确认无 YAGNI 抽象。查看方式：/ponytail-review
```

**不是 checklist**（ponytail 精神：不要制造比代码本身还复杂的管理工具）。

---

## 四、Skill 整合方案（修正版）

### 4.1 关键修正：Skill 路径不匹配问题

**问题**：`patterns/registry.yaml` 引用 `skills/ponytail-audit` 等，但 ponytail skills 实际在 `.claude/skills/`（slash 命令式），不在 `skills/`（文件式）。

**分析**：

| Skill 位置 | 调用方式 | 适用场景 | 与 registry 的关系 |
|-----------|---------|---------|-----------------|
| `skills/` | 文件读取，循环自动调用 | GitHub Actions workflow 自动触发 | registry.yaml 可以引用 |
| `.claude/skills/` | slash 命令，人工触发 | 人机交互的 skill | registry.yaml **不能**引用（因为循环不是人） |

**结论**：ponytail skills 是为人机交互设计的（`/ponytail-audit`），不是为循环自动执行设计的（循环不能 slash 触发）。循环调用 ponytail 需要通过 `gh script` 或 Python 脚本间接调用 skill 逻辑。

**整合方式**：
- 新增循环使用 `github-script` + Python 脚本调用 ponytail 逻辑
- 不在 `patterns/registry.yaml` 中新增 ponytail pattern（skill 路径不存在）
- 不创建 `skills/ponytail-audit/` 等目录（不需要）

### 4.2 与现有 Skills 的关系（修正）

| 现有 Skill | 与 Ponytail 的关系 | 整合方式 |
|-----------|-----------------|---------|
| `loop-triage` | **互补**，不是替代 | 不变；triage 处理 issue/PR 状态，ponytail 处理代码体积 |
| `loop-cleanup` | **互补**，`ponytail-review` 增强清理精度 | Post-Merge Cleanup 输出中引用 ponytail-review 发现 |
| `loop-handoff` | 无冲突，正交 | 不变 |
| `loop-memory` | 代码行数趋势 → Durable Facts | Durable Facts 追加代码行数记录（不依赖 `ponytail:` 注释） |
| `loop-verifier` | 无冲突 | 不变 |
| `loop-context` | 无冲突 | 不变 |

---

## 五、Memory 系统整合（修正版）

### 5.1 代码行数趋势 → Durable Facts

**不依赖 `ponytail:` 注释**（注释是开发习惯，循环无法强制），改为追踪可客观测量的指标：代码行数。

```
每周 ponytail-audit 扫描（增量 diff）
        ↓
cloc 或 wc -l 统计（按模块分组）
        ↓
与上周对比，计算净增减
        ↓
净减少 → 记录到 durable-facts.md（positive fact）
净增加 → 记录到 durable-facts.md（债务fact，需关注）
        ↓
连续 4 周净增加 → 触发 code-health issue
```

**durable-facts.md 新增节**：

```markdown
## Code Volume Trend

<!-- 由 loop-memory skill 维护，code-health-audit 驱动 -->

| Date | Module | Lines | Weekly Δ | Cumulative Δ |
|------|--------|-------|----------|-------------|
| 2026-08-03 | app/services/ | 4821 | -12 | -47 |
| 2026-08-03 | app/api/ | 1204 | +3 | +3 |
```

### 5.2 删除 Ponytail Debt 节（v1 方案冗余）

v1 方案在 durable-facts.md 中新增 `### Ponytail Debt` 节，但：
- `ponytail:` 注释在代码中不存在
- Durable Facts 已有 `superseded_by` 字段表示状态变迁
- 独立 Status 字段与 Durable Facts 设计冗余

**删除此节**。代码行数趋势足以作为代码健康度的代理指标。

---

## 六、Patterns Registry 更新

### 6.1 修正：ponytail pattern 不进入 registry

ponytail skills 是人机交互工具，不适合循环自动调用。**不修改** `patterns/registry.yaml` 的 skill 引用。

### 6.2 不新增 pattern markdown 文件

`patterns/daily-triage.md` 是 YAML entry 的说明文档。ponytail audit/debt 通过 GitHub Actions workflow 直接执行，不需要对应的 `patterns/ponytail-*.md`。

---

## 七、Workflow 新增（v2）

| Workflow | 触发 | 职责 | Skill 路径 |
|----------|------|------|-----------|
| `code-health-audit.yml` | 每周日 10:00 UTC | 增量 diff ponytail-audit + cloc 行数统计 + Durable Facts 更新 | 不引用 skill（通过 `gh script` 调用） |
| `debt-harvesting.yml` | 每月 1 日 | 汇总月度代码行数趋势，生成 PONYTAIL-DEBT.md | 同上 |

**PR Babysitter 更新**：在现有 `pr-babysitter.yml` 中增加一行 ponytail 警告注释（见循环 10）。

---

## 八、ADR 建议（更新版）

```markdown
### ADR-0004：Ponytail × Loop Engineering 整合

**Decision 1：Ponytail 约束范围**
- 适用：`app/services/`、`app/api/`、`loop/`（CLI 工具）、`skills/`、`patterns/`
- 明确排除：`app/loop/`（CMA-ES 信号搜索）、`bench/`（实验代码）、`tests/`（测试代码）
- `tests/` 的 YAGNI 豁免：AGENTS.md 的 100% 覆盖要求优先于 ponytail ultra 删除建议

**Decision 2：ponytail 是横切质量层，不是 Loop**
- 不在 `patterns/registry.yaml` 中新增 ponytail pattern
- 不创建 `skills/ponytail-audit/` 等文件（skill 在 `.claude/skills/`）
- 循环通过 `github-script` + Python 脚本调用 ponytail 逻辑

**Decision 3：代码行数趋势替代 ponytail: 注释债务**
- Debt Harvesting 追踪代码行数（客观可测量），不依赖 `ponytail:` 注释（开发习惯）
- 代码行数写入 `docs/loop-state/durable-facts.md` 的 Code Volume Trend 节
- 连续 4 周净增长触发 code-health issue

**Decision 4：Code Health Audit 增量扫描 + 人工确认前置**
- 只扫描自上次 audit 以来的变更文件（diff 增量）
- 所有发现标注 `⚠️ 需要人工确认`（ponytail-audit 存在误判先例）
- 不基于 audit 结果自动创建 PR
```

---

## 九、与现有 Loop Engineering 文档的一致性更新

### 9.1 `docs/loop-state/LOOP.md` 新增循环

```markdown
### 8. Code Health Audit（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 每周日 10:00 UTC |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `.claude/skills/ponytail-audit`（通过 gh script 调用） |
| **State** | `docs/loop-state/STATE.md`（记录上次 audit commit） |
| **输入** | 全仓库增量 diff（排除 app/loop/、bench/、tests/） |
| **输出** | GitHub Issue 草稿（`code-health` 标签）+ Durable Facts 更新 |
| **Gate** | L1：报告模式，人类决定行动；所有发现带 ⚠️ 需确认 |

### 9. Debt Harvesting（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 每月 1 日 |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `.claude/skills/ponytail-debt`（通过 gh script 调用） |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | `docs/loop-state/durable-facts.md` 代码行数趋势 |
| **输出** | `PONYTAIL-DEBT.md` + Durable Facts 追加 |
| **Gate** | L1：报告模式，人类决定行动 |
```

### 9.2 `docs/loop-state/MEMORY.md` 更新

在"Hygiene 节奏"章节新增：

```markdown
### Code Volume Trend（来自 ponytail-audit）

- **触发**：每周 Code Health Audit 运行后
- **来源**：cloc/wc -l 按模块统计（不依赖 ponytail: 注释）
- **记录**：追加到 `docs/loop-state/durable-facts.md` 的 Code Volume Trend 节
- **告警**：连续 4 周净增长 → 触发 code-health issue
```

### 9.3 `CLAUDE.md` 更新

```markdown
## Ponytail（约束范围：不含 app/loop/、bench/、tests/）

ponytail 是代码质量横切层，不是循环。
ponytail skills 在 `.claude/skills/`，通过 slash 命令调用。

### 约束范围
- ✅ `app/services/`、`app/api/`、`loop/`（CLI）、`skills/`、`patterns/`
- ❌ `app/loop/`（CMA-ES 信号搜索）
- ❌ `bench/`（实验代码）
- ❌ `tests/`（100% 覆盖要求优先于 ponytail ultra）

### 循环集成
- Code Health Audit（L1，每周日）：`.github/workflows/code-health-audit.yml`
- Debt Harvesting（L1，每月）：`.github/workflows/debt-harvesting.yml`
- PR Babysitter：底部追加一句话 bloat 警告
```

---

## 十、实施优先级（更新版）

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | 界定 ponytail 约束范围 | 在 AGENTS.md 中明确排除列表 |
| **P0** | ADR-0004 创建 | 记录整合决策（含 Skill 路径修正） |
| **P1** | Code Health Audit workflow | 增量 diff + cloc + Durable Facts |
| **P1** | PR Babysitter 一句话警告 | 在现有 workflow 中加一行 |
| **P2** | Debt Harvesting workflow | 月度代码行数趋势报告 |
| **P3** | Durable Facts Code Volume Trend 节 | 建立行数基线 |
| **P3** | LOOP.md、STATE.md、MEMORY.md 更新 | 文档一致性 |

---

## 十一、风险与缓解（更新版）

| 风险 | 影响 | 缓解 |
|------|------|------|
| ponytail-audit 误判（上次把 ADR-0003 要求重命名判为重复） | 浪费人工确认时间 | 所有发现带 ⚠️；不自动创建 PR |
| Code Health Audit 全量扫描 token 成本高 | 每周 136K tokens，过度消耗 | 改为增量 diff 扫描 |
| `ponytail:` 注释不存在，Debt Harvesting 收不到数据 | 循环失效 | 改为代码行数趋势（客观可测量） |
| ponytail ultra 删除测试的规则与 AGENTS.md 冲突 | 测试覆盖被蚕食 | 明确排除 `tests/`，ultra 对测试代码不适用 |
| ponytail skills 在 `.claude/skills/`，不在 `skills/` | registry 引用无效 | 不修改 registry；循环通过 gh script 间接调用 |
