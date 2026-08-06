# Loop Engineering 整合方案 — pyharmonics-gpt 自进化框架

> 本文件是 `app/loop/` 现有 M4 交易信号进化系统的**增量补充**，而非重新发明。
> 所有已完成的模块（scheduler、pareto、oos_validator、walk_forward 等）在对应的"现状"节已标注"已存在"，
> 实施任务只记录**尚未完成的工作**。

## 状态

- **文件路径**：`docs/loop-engineering-plan.md`
- **版本**：v3.0（二次审计优化版）
- **与 PLANS.md 关系**：本计划已登记入 `PLANS.md`
- **前提条件**：已阅读 `AGENTS.md`、`app/loop/maker_checker/` 包文档、`app/loop/state.py` 状态管理说明

---

## 目录

1. [背景与现状](#1-背景与现状)
2. [整合架构总览](#2-整合架构总览)
3. [文件结构](#3-文件结构)
4. [七大开发循环设计](#4-七大开发循环设计)
5. [Memory Engineering 整合](#5-memory-engineering-整合)
6. [交易循环与开发循环握手协议](#6-交易循环与开发循环握手协议)
7. [观测体系](#7-观测体系)
8. [Skills 系统](#8-skills-系统)
9. [安全加固](#9-安全加固)
10. [成本与性能](#10-成本与性能)
11. [Phase 0：基线测量](#11-phase-0基线测量)
12. [实施路线图](#12-实施路线图)
13. [关键决策登记（ADR）](#13-关键决策登记adr)
14. [验收标准](#14-验收标准)
15. [未解决问题](#15-未解决问题)
16. [二次审计新增问题](#16-二次审计新增问题)

---

## 1. 背景与现状

### 1.1 loop-engineering 框架核心

loop-engineering 的核心哲学：**"Stop prompting. Design the loop. Get a score."**

不是制作单个 prompt，而是设计**控制系统的循环**，让 AI Agent 在时间轴上自主运转。

五大构建块 + Memory：
1. **Automations / Scheduling** — 按节奏发现 + 分类
2. **Worktrees** — 安全并行执行
3. **Skills** — 持久化项目知识
4. **Plugins & Connectors (MCP)** — 接入真实工具
5. **Sub-agents** — Maker / Checker 分工
6. **+ Memory / State** — 对话外持久化的脊柱

### 1.2 pyharmonics-gpt 已有资产

| 资产 | 现状 | 与 loop-engineering 的关系 |
|------|------|--------------------------|
| `app/loop/` | CMA-ES 遗传搜索 + Pareto 前沿 + Maker-Checker LLM 验证 | **已有领域循环，不改动** |
| `app/loop/scheduler.py` | Anti-plateau back-off、自适应唤醒（23-07 local） | 已存在，参照使用 |
| `app/loop/pareto.py` | 4-D / 5-D Pareto 前沿维护 | 已存在，参照使用 |
| `app/loop/state.py` | STATE.md / HISTORY.jsonl / PARETO.json / fcntl 锁 | 已存在，**需增强崩溃恢复** |
| `app/loop/oos_validator.py` | 样本外验证 | 已存在 |
| `app/loop/walk_forward.py` | Walk-forward 验证 | 已存在 |
| `app/loop/regime_buckets.py` | 市场机制分桶 | 已存在 |
| `app/loop/sensitivity.py` | 敏感性 σ 校准 | 已存在 |
| `app/loop/mutation.py` | 遗传变异逻辑 | 已存在 |
| `app/loop/worker.py` | 进程池 fan-out | 已存在，**需增强类型检查** |
| `app/loop/checker.py` | 启发式 M4 checker | 已存在 |
| `app/loop/maker_checker/` | LLM Maker + Checker + Arbiter | 已存在，**需完善 salt 管理** |
| `app/config/tuning.py` | `TUNING` 全局单例、`apply_tuning()` 运行时替换 | **关键：与 gunicorn worker 共享存在隐患** |
| `app/services/signal_engine.py` | 模块级别名（`ATR_WINDOW = TUNING.atr_window` 等） | **关键：`apply_tuning()` + 进程池 fork 有竞态条件** |
| `bench/` | Backtest benchmark 基础设施 | 与 `app/loop/` 协作，需协调 |
| `AGENTS.md` | AI agent 规范、代码质量标准、NORTH STAR 指标 | 保留并增强 |
| `skills-lock.json` | mattpocock/skills 38 个技能的 SHA-256 锁定 | 继续使用，新增项目技能独立管理 |
| `docs/agents/` | issue-tracker、triage-labels、domain docs | 继续使用 |
| `PLANS.md` | 计划生命周期管理 | 保留，本计划登记入内 |

### 1.3 关键命名冲突（必须修复）

| 概念 | 当前名称 | 正确名称 | 原因 |
|------|----------|----------|------|
| Python 源文件版本哈希 | `skills_version.py` | `strategy_version.py` | 区分 agent skill 与策略文件版本 |
| HISTORY.jsonl 中的字段 | `skills_version` | `strategy_version` | 与上统一 |
| JSONL 迁移字段 | — | 读取时兼容 `skills_version` 和 `strategy_version` | 现有 HISTORY.jsonl 包含旧字段名 |
| 策略文件列表 | `DEFAULT_STRATEGY_FILES` | （保留，已正确命名） | — |
| loop 候选计数器 | `loop_candidates_total` | `tuning_proposals_total` | 避免与交易信号 `Candidate` 混淆 |

**操作**：重命名 `app/loop/skills_version.py` → `app/loop/strategy_version.py`，更新所有引用（含 HISTORY.jsonl 字段读写兼容层）。

### 1.4 项目缺失的关键 Loop Engineering 组件

| 组件 | 优先级 | 备注 |
|------|--------|------|
| GitHub Actions 驱动的自动化循环（全部 7 个 workflow 均需新建） | P0 | 当前 `.github/workflows/` 只有 `ci.yml` |
| Memory Engineering（记忆分层） | P1 | |
| Loop State 文件（`.claude/` 存放位置需解决 gitignore 冲突） | P0 | **`.claude/` 已被 gitignore，无法直接提交** |
| Loop Readiness Score 审计 | P1 | |
| Git Worktree 隔离机制 | P1 | |
| MCP 连接器集成 | P2 | |
| 跨平台文件锁（当前 `fcntl.flock` 仅 POSIX） | P1 | 但项目本质是 POSIX-only，WSL 支持更务实 |
| CI 扩展（mypy/pyright 覆盖 `app/loop/`） | P1 | |
| Issue Tracker 集成（`suspicious_to_human` → gh issue） | P1 | 需要解耦网络调用 |
| 观测体系（`/metrics` 端点不存在） | P2 | Flask app 中无此路由 |
| 崩溃恢复（outbox 模式） | P1 | |
| `apply_tuning()` + 进程池竞态条件修复 | P0 | **存在真实 bug，影响结果确定性** |
| Gunicorn worker 与 TUNING 单例同步 | P0 | **Promotion 不影响运行中的 worker** |

---

## 2. 整合架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                    pyharmonics-gpt LOOP ENGINEERING                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │            LAYER 1: 开发循环 (Loop Engineering) — 新增            │  │
│  │                                                                 │  │
│  │  Daily Triage ──→ Issue Triage ──→ PR Babysitter               │  │
│  │        │               │              │                          │  │
│  │        ▼               ▼              ▼                          │  │
│  │  docs/loop-state/  docs/loop-state/  worktree/                   │  │
│  │  (tracked)         (tracked)                                    │  │
│  │                                                                 │  │
│  │  CI Sweeper ────→ Dependency Sweeper ───→ Post-Merge           │  │
│  │        │                  │                    │                 │  │
│  │        ▼                  ▼                    ▼                 │  │
│  │  audit.yml           gate.yaml           docs/loop-state/        │  │
│  │                                                                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              +                                         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │            LAYER 2: 交易信号循环 (已有，保留并增强)               │  │
│  │                                                                 │  │
│  │  CMA-ES Search + Pareto Front + Maker-Checker Verifier          │  │
│  │  → .scratch/loop_state/ (STATE.md, HISTORY.jsonl, PARETO)      │  │
│  │                                                                 │  │
│  │  Outerloop 握手: 交易 Pareto 突破 → 开发循环 Issue 创建            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              +                                         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │            LAYER 3: Memory Engineering — 持久层                  │  │
│  │                                                                 │  │
│  │  Scratch (会话) → Episodic (天-周) → Durable (项目级事实)        │  │
│  │  .claude/MEMORY.md + .claude/MEMORY-STATE.md                    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              +                                         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │            LAYER 4: 观测与治理 (Observability)                   │  │
│  │                                                                 │  │
│  │  Loop Readiness Score ≥ 58 (CI-gated)                           │  │
│  │  Token Budget + cost tracking                                    │  │
│  │  docs/loop-state/loop-run-log.md (append-only)                  │  │
│  │  app/api/metrics_routes.py → /metrics                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

**核心设计原则**：

1. **不重复造轮子**：`app/loop/` 现有系统完整保留，作为 Outerloop 的信号源
2. **命名隔离**：`skills_version` → `strategy_version`，消除与 mattpocock skills 的歧义
3. **状态文件放在 `docs/loop-state/`**：`.claude/` 已被 `.gitignore`，不可提交；`docs/loop-state/` 为可追踪的共享状态
4. **Crash-safe**：Maker/Checker 工件使用 outbox 模式，支持从 HISTORY.jsonl 重放
5. **CI-gated**：mypy/pyright/pytest 覆盖 `app/loop/` 全套件
6. **交易安全**：backtest → live promotion 有硬性 gate，不允许自动覆盖 `TUNING`
7. **POSIX-only**：Loop 在 macOS/Linux 上运行，不支持 Windows（WSL 是允许的路径）

---

## 3. 文件结构

> ⚠️ **审计发现**：`.claude/` 在 `.gitignore` 第 181-182 行已被声明为"Local AI assistant tooling (not project code)"，
> 不能提交。所有共享的循环状态放在 `docs/loop-state/`（可追踪），`.claude/` 仅作为本机记忆存储。

```
pyharmonics-gpt/
├── .github/
│   └── workflows/
│       ├── daily-triage.yml         # L1: 工作日每天 → 更新 docs/loop-state/STATE.md  [NEW]
│       ├── ci-sweeper.yml           # L2: CI 失败自动分析                       [NEW]
│       ├── changelog-drafter.yml    # L1: 每周一 → 生成 CHANGELOG 草稿           [NEW]
│       ├── audit.yml                # L1: 每个 PR → Loop Readiness Score          [NEW]
│       ├── star-history.yml         # L1: 每日 star history 自动 PR             [NEW]
│       ├── ci.yml                  # 扩展：mypy/pyright 覆盖 app/loop/           [MODIFY]
│       ├── issue-sync.yml          # NEW: 将 .scratch/loop_state/pending_issues/  [NEW]
│       │                            # 中的待处理 issue 同步到 GitHub
│       └── pr-babysitter.yml       # NEW: PR 状态监控                          [NEW]
│
├── docs/
│   ├── loop-state/                  # ★ 共享循环状态（git 追踪）
│   │   ├── LOOP.md                 # 7 个循环完整定义
│   │   ├── STATE.md                # 循环运营状态
│   │   ├── MEMORY.md               # 记忆分层策略
│   │   ├── MEMORY-STATE.md         # 当前记忆目录
│   │   ├── memory-budget.md         # 各层 token/条目上限
│   │   ├── memory-constraints.md    # 禁止存储内容
│   │   ├── loop-budget.md          # Token 预算上限
│   │   ├── loop-constraints.md     # 约束规则
│   │   ├── loop-run-log.md         # 追加式运行日志
│   │   ├── gate.yaml               # 路径 denylist + 自动合并白名单
│   │   └── outerloop-protocol.md   # 两层循环握手协议
│   └── loop-engineering-plan.md    # 本文件
│
├── .claude/                         # ★ 本机记忆（gitignore，不提交）
│   ├── MEMORY.md                   # 策略（可软链到 docs/loop-state/MEMORY.md）
│   ├── MEMORY-STATE.md             # 本机记忆
│   └── skills/                     # Loop-specific skills
│       ├── loop-triage/SKILL.md
│       ├── loop-context/SKILL.md
│       ├── loop-memory/SKILL.md
│       └── loop-verifier/SKILL.md
│
├── loop/                            # Python CLI 工具
│   ├── __init__.py
│   ├── loop.py                     # 统一 CLI: doctor | status | audit | cost
│   ├── loop_audit.py               # Loop Readiness Score 计算
│   ├── loop_sync.py                # docs/loop-state/ 下文件一致性检查
│   ├── loop_gate.py                # gate.yaml 机械执行
│   ├── loop_worktree.py            # Git worktree 隔离管理
│   ├── loop_context.py             # Scratch → Episodic promotion
│   └── strategy_version.py          # 重命名自 skills_version.py（含 JSONL 兼容层）
│
├── skills/                          # 项目级 Skills（独立于 skills-lock.json）
│   ├── loop-triage/
│   ├── loop-handoff/
│   ├── backtest-verify/
│   └── signal-eval/
│
├── patterns/                        # 循环模式注册表（新增）
│   ├── registry.yaml
│   ├── daily-triage.md
│   ├── pr-babysitter.md
│   ├── ci-sweeper.md
│   ├── dependency-sweeper.md
│   ├── post-merge-cleanup.md
│   └── changelog-drafter.md
│
├── .scratch/                       # 本机临时状态（gitignore）
│   └── loop_state/                  # 交易循环状态（已有）
│       ├── STATE.md
│       ├── HISTORY.jsonl
│       ├── PARETO.json
│       ├── NEXT_QUEUE.md
│       ├── runs/<uuid>/
│       ├── outbox/                 # Maker/Checker 工件 outbox
│       ├── pending_issues/         # 待同步到 GitHub 的 issue
│       └── salt.json               # Salt 持久化
│
├── CLAUDE.md                        # Claude Code 全局指令（新建）
├── AGENTS.md                        # 增强：加入 loop agent 配置节
├── PLANS.md                         # 登记本计划
│
├── docs/
│   ├── adr/                        # 架构决策登记（新建）
│   │   └── 0003-loop-engineering-integration.md
│   └── loop-engineering-plan.md    # 本文件
│
└── app/
    ├── api/
    │   └── metrics_routes.py      # NEW: prometheus /metrics 端点
    └── loop/
        ├── strategy_version.py      # 重命名自 skills_version.py
        ├── maker_checker/
        │   ├── salt_store.py       # 新增：salt 持久化管理（含 rotate_salt 修复）
        │   └── arbiter.py          # 增强：MergeResult 需含 agreement 字段
        └── tuning_promotion.py     # NEW: TUNING 单例 promotion 安全 gate
```

---

## 4. 七大开发循环设计

> ⚠️ **审计发现**：项目是单开发者交易项目（git 历史为单一作者），
> "Daily Triage 09:00 UTC"、"PR Babysitter 每 15 分钟" 等 YAGNI 特征已标注。

### 4.1 Daily Triage（L1 — 报告模式）

**触发频率**：工作日每天 09:00 UTC（**当前项目为 YAGNI，建议降低为"按需"**）  
**解决的问题**：每天早上人工梳理 issue/PR/测试报告

| 维度 | 设计 |
|------|------|
| **输入** | GitHub Issues (needs-triage, needs-info)、PR、最近的 Pareto 移动 |
| **Skill** | `loop-triage` → 读取 `docs/loop-state/STATE.md`，写回分类建议 |
| **State** | `docs/loop-state/STATE.md` 更新 High Priority / Watch List / Recent Noise |
| **输出** | Issue 评论（建议 label）、PR 评论（建议 reviewer） |
| **Handoff** | 人类决定行动，循环不自动执行 |
| **工具** | GitHub Actions + `gh` CLI |
| **YAGNI 注** | 单开发者项目无需每日报告，建议改为"状态快照按需生成" |

### 4.2 PR Babysitter（L2 — 辅助模式）

**触发频率**：PR 打开时触发（非 cron，**YAGNI**）  
**解决的问题**：PR 长期无人 review、blocking 状态被遗忘

| 维度 | 设计 |
|------|------|
| **输入** | Open PRs、review comments、CI status |
| **Skill** | `loop-pr` → 分析 blocking 原因，添加评论提醒 |
| **Worktree** | 每个 PR 分析在独立 worktree 中运行（`loop_worktree.py`） |
| **验证** | `loop-verifier` 检查建议合理性 |
| **Gate** | L2：建议报告，人类决定是否采纳，不自动合并 |

### 4.3 CI Sweeper（L2 — 谨慎模式）

**触发频率**：CI 失败后自动触发  
**解决的问题**：CI 红色但无人认领、flaky test 反复出现

| 维度 | 设计 |
|------|------|
| **输入** | GitHub Actions runs、test failures |
| **Skill** | `loop-ci-sweep` → 分析失败原因，分类（regression / flaky / infra） |
| **Flaky 检测** | `pytest-rerunfailures` 加入 `requirements-dev.txt`；flaky 历史存入 `.scratch/loop_state/test-flakes.jsonl`；阈值：同一测试 2 次失败 / 10 次运行 |
| **Worktree** | 在隔离 worktree 中复现并尝试修复 |
| **Gate** | 人类 gate：major 变更不自动合并，仅 patch 可自动合并 |

### 4.4 Dependency Sweeper（L2 — 仅 patch）

**触发频率**：每 6 小时或每天  
**解决的问题**：依赖落后、已知 CVE 未修

| 维度 | 设计 |
|------|------|
| **输入** | `pyproject.toml`、`requirements*.txt`、Dependabot PRs |
| **Skill** | `loop-dep-sweep` → 检查可更新的依赖，跳过 denylisted |
| **验证** | `pip install -e . && pytest` 在 worktree 中通过 |
| **Gate** | patch + low-risk CVE 才可自动合并；major 依赖人类批准 |

### 4.5 Post-Merge Cleanup（L1 — 峰值外执行）

**触发频率**：合并后 1-6 小时（低峰期）  
**解决的问题**：合并后遗留的临时文件、过时代码、dead imports

| 维度 | 设计 |
|------|------|
| **输入** | 刚合并的 main 分支 diff |
| **Skill** | `loop-cleanup` → 检测临时文件、dead code、废弃 import |
| **输出** | `cleanup-PR` 草稿，人类批准后合并 |
| **Gate** | L1：仅建议，不自动合并 |

### 4.6 Changelog Drafter（L1 — 草稿模式）

**触发频率**：每周一 或 release tag 时（**需先建立版本规范**）  
**解决的问题**：手动维护 CHANGELOG 容易遗漏

| 维度 | 设计 |
|------|------|
| **前提** | 项目需建立版本规范（`VERSION` 文件或 `pyproject.toml [project] version`） |
| **Skill** | `loop-changelog` → 生成 `RELEASE_NOTES_DRAFT.md` |
| **输出** | GitHub Issue 草稿，标记 `release-prep` label |
| **Gate** | 人类审核后才发布 |

### 4.7 Issue Triage（L1 — 仅建议）

**触发频率**：新 issue 到达时触发（event-driven，非 cron）  
**解决的问题**：新 issue 没有分类、缺标签、缺上下文

| 维度 | 设计 |
|------|------|
| **输入** | 新 open 的 issues |
| **Skill** | `loop-issue-triage` → 读取 `docs/agents/triage-labels.md`，应用五态分类 |
| **输出** | Issue 评论（建议的 label + triage state），附加上下文请求 |
| **Gate** | 人类决定，不自动操作 |

---

## 5. Memory Engineering 整合（四层记忆）

### 5.1 四层定义

| Tier | 生命周期 | 信任级 | pyharmonics-gpt 示例 | 存储位置 |
|------|----------|--------|---------------------|---------|
| **Scratch** | 本次会话 | 低 | Agent 调试时的临时笔记、open questions | `.claude/MEMORY-STATE.md` scratch 节 |
| **Episodic** | 天-周 | 中 | 上一次调参的决策、Pareto 移动记录 | `.claude/MEMORY-STATE.md` episodic 节 |
| **Durable Facts** | 持续到撤销 | 高 | 参数范围约束、当前最优 Pareto 解、代码 owner 关系 | `docs/loop-state/durable-facts.md`（可追踪） |
| **Retrieved** | 每次推理 | 变化 | 从 HISTORY.jsonl 按需提取的历史实验记录 | 查询时生成，不持久化 |

### 5.2 记忆写入策略

**Durable Facts 为追加式**：更新时不删除旧条目，而是追加 `superseded_by` 指向新条目。
审计脚本读取所有 Durable Facts，检测未解决的矛盾。

**Budget 强制执行**：由 `loop/loop_audit.py` 在每次审计时执行，检测任何层超限则告警。

**Token 计数**：使用 `tiktoken` 库（`requirements.txt` 需加入 `tiktoken`）。

### 5.3 文件清单

| 文件 | 角色 | 可追踪 |
|------|------|--------|
| `docs/loop-state/MEMORY.md` | 策略：各层写入规则、promotion 节奏、budget | ✅ |
| `.claude/MEMORY-STATE.md` | 本机当前记忆目录（按 tier 组织） | ❌ |
| `docs/loop-state/memory-budget.md` | 各层最大条目数 / token 上限 | ✅ |
| `docs/loop-state/memory-constraints.md` | 禁止存储内容 | ✅ |
| `docs/loop-state/durable-facts.md` | Durable Facts 追加日志 | ✅ |

---

## 6. 交易循环与开发循环握手协议

### 6.1 Outerloop 定义

```
交易循环 (app/loop/)                    开发循环
┌─────────────────────┐          ┌─────────────────────┐
│ Pareto Front 更新    │          │ Daily Triage         │
│ 找到新的非劣解        │──────────│ 报告信号质量下降      │
│ fitness 突破阈值     │          │ 提出新的 backtest    │
└─────────────────────┘          └─────────────────────┘
         │                                │
         ▼                                ▼
┌─────────────────────────────────────────────────────┐
│                 Outerloop Protocol                   │
│                                                      │
│  触发条件:                                           │
│  - Pareto 前沿连续 N 代无移动                          │
│    → docs/loop-state/STATE.md Watch List 追加         │
│                                                      │
│  - 新 signal 模式被发现 (新 cluster)                  │
│    → changelog-drafter 触发                          │
│                                                      │
│  - suspicious_to_human verdict 触发                   │
│    → 写入 .scratch/loop_state/pending_issues/        │
│    → issue-sync.yml 同步到 GitHub                     │
│                                                      │
│  文件: docs/loop-state/outerloop-protocol.md         │
└─────────────────────────────────────────────────────┘
```

### 6.2 suspicious_to_human → Issue 自动上升（解耦设计）

> ⚠️ **审计发现**：`gh issue create` 要求 runner 有 `gh` CLI、网络和认证。
> `driver.py` 在开发者机器上后台运行时这些不可用。

**架构**：
```
driver.py (backtest machine)
  → 写入 .scratch/loop_state/pending_issues/<uuid>.json
  → （不调用 gh CLI）

.github/workflows/issue-sync.yml (CI runner)
  → 扫描 pending_issues/
  → gh issue create
  → 删除已处理的 <uuid>.json
```

**pending_issues/ 中的 JSON 格式**：
```json
{
  "uuid": "...",
  "created_at": "2026-08-06T...",
  "candidate_id": "...",
  "params_sha": "...",
  "decision": "suspicious_to_human",
  "fitness": 0.123,
  "verdict": { ... }
}
```

**Rate limiting**：每个 generation 最多创建 1 个 issue；verdicts 批量到一个 weekly digest issue。

---

## 7. 观测体系

### 7.1 Loop Readiness Score（L0-L3）

| 维度 | L0 (0-29) | L1 (30-57) | L2 (58-84) | L3 (85-100) |
|------|-----------|-----------|-----------|-------------|
| **LOOP.md** | 无 | 存在但不完整 | 完整定义 | 持续更新 |
| **STATE.md** | 无 | 手动维护 | 自动更新 | 自动 + 历史追踪 |
| **Memory** | 无 | Scratch only | Scratch+Episodic | 四层完整 |
| **Skills** | 无 | 1-2 个 | 3-5 个，覆盖主要循环 | 全部循环覆盖 |
| **GitHub Actions** | 无 | 1 个 workflow | 3-5 个 | 全部 7 个循环 |
| **Worktree 隔离** | 无 | 手动 | 半自动 | 全自动 |
| **Token Budget** | 无 | 有但不执行 | 有并监控 | 有 + 告警 + kill switch |
| **Gate.yaml** | 无 | 存在 | 完整 | 持续更新 |
| **CI 类型覆盖** | 无 | pytest | pytest + mypy | pytest + mypy + pyright 全覆盖 |
| **Issue 集成** | 无 | 手动 | pending_issues → issue | 全部 verdicts → weekly digest |

**CI 集成**：`audit.yml` 在每个 PR 上运行 `loop/loop_audit.py`，将分数报告为 PR comment。
分数 < 58 不阻塞合并，但会在 PR 上留下一条警告性评论。

### 7.2 观测指标（必须实现）

| 指标 | 类型 | 说明 |
|------|------|------|
| `tuning_proposals_total` | Counter | 总候选数，按 decision 分维（重命名自 `loop_candidates_total`） |
| `loop_generation_duration_seconds` | Histogram | 每代耗时分布 |
| `llm_maker_calls_total` | Counter | Maker LLM 调用次数 |
| `llm_checker_calls_total` | Counter | Checker LLM 调用次数 |
| `llm_tokens_total` | Counter | token 消耗（input + output） |
| `llm_latency_seconds` | Histogram | 单次 LLM 延迟分布 |
| `llm_cost_usd_total` | Counter | LLM 费用（USD） |
| `llm_cache_hit_total` | Counter | LLM 响应缓存命中次数 |
| `pareto_front_size` | Gauge | 当前 Pareto 前沿规模 |
| `mc_agreement_rate` | Gauge | Maker-Checker 一致率（**需代码修改：MergeResult.agreement 字段**） |
| `suspicious_to_human_rate` | Gauge | 需要人工审查的比例 |
| `worker_timeout_total` | Counter | Worker 超时次数 |
| `runs_disk_bytes` | Gauge | `runs/` 目录磁盘占用 |

**实现方式**：
1. `app/api/metrics_routes.py`（新建）：`prometheus_client.make_wsgi_app()` 通过 `app.add_url_rule('/metrics', ...)` 挂载
2. 在 `app/loop/worker.py` 和 `app/loop/maker_checker/runner.py` 中埋点
3. `MergeResult` 需增加 `agreement: bool` 字段（`maker_self_score` 与 `checker_score` 之差 < 阈值时为 True）

### 7.3 运行日志（logfmt 格式）

> ⚠️ **审计发现**：原始方案中 `outcome=accepted=3_rejected=6_errors=1` 含空格，KV 解析困难。
> 修正为标准 logfmt 格式：

```logfmt
## Run Log

### 2026-08-05T09:00:00Z [daily-triage] loop=1 candidates=0 cost=0.00 outcome=success
### 2026-08-05T14:32:00Z [pr-babysitter] loop=1 candidates=0 cost=0.00 outcome=success
### 2026-08-05T15:00:00Z [gen-047] loop=1 candidates=10 cost=0.12 outcome=success accepted=3 rejected=6 errors=1
```

---

## 8. Skills 系统

### 8.1 与 skills-lock.json 的关系

> ⚠️ **重要**：`skills-lock.json` 锁定 **mattpocock agent skills**，本方案 loop skills **不进入** `skills-lock.json`。

**设计决策**：
- `skills-lock.json` 继续独立管理 mattpocock/skills（不做任何改动）
- 新增的 loop skills 放在项目根目录的 `skills/` 目录（与 `skills-lock.json` 平级）
- Loop skills **不**进入 `skills-lock.json`（因为它们是项目特定的，不是通用技能）

### 8.2 新增 Loop Skills

| Skill | 职责 | 关键规则 |
|-------|------|---------|
| `loop-triage` | 分类 issue/pr/ci 状态 | 读取 `docs/agents/triage-labels.md`，只建议不行动 |
| `loop-handoff` | 会话间上下文传递 | 写入 `.claude/MEMORY-STATE.md`，遵循四层策略 |
| `loop-verifier` | 验证修复建议的合理性 | 检查测试覆盖、向后兼容性 |
| `loop-context` | 管理 scratch → episodic promotion | 每周触发，token budget 内执行 |
| `loop-issue-triage` | 应用五态分类到新 issue | 读取 `docs/agents/triage-labels.md` |
| `backtest-verify` | 验证调参修改的 backtest 结果 | 读取 `PLANS.md` Backtest Evaluation Guide |
| `signal-eval` | 评估新检测到的 harmonic pattern | 量化 win rate / Sharpe / Calmar |

### 8.3 Skill 模板

```markdown
# SKILL.md — {skill_name}

## 触发条件
何时调用此 skill。

## 输入
此 skill 读取哪些文件/状态。

## 输出
此 skill 写入哪些文件/状态。

## 规则
1. ...

## 验证
如何确认此 skill 的输出是正确的。
```

---

## 9. 安全加固

### 9.1 Salt 管理

> ⚠️ **审计发现**：`rotate_salt()` 示例代码有 bug — 返回 `get_or_create_salt()` 结果，
> 而后者在文件存在时直接返回旧 salt，未生成新值。

**修复后的实现**：
```python
# salt_store.py
SALT_FILE = Path(".scratch/loop_state/salt.json")

def get_or_create_salt() -> str:
    if SALT_FILE.exists():
        return json.loads(SALT_FILE.read_text())["salt"]
    return _write_salt(make_salt())

def _write_salt(salt: str) -> str:
    SALT_FILE.write_text(json.dumps({"salt": salt, "created_at": time.time()}))
    return salt

def rotate_salt() -> str:
    """手动 rotation，用于安全事件响应。生成新 salt 并覆盖。"""
    return _write_salt(make_salt())
```

**Salt 位置**：`SALT_FILE = Path(".scratch/loop_state/salt.json")`  
**注意**：`.scratch/loop_state/` 在 `.gitignore` 中，salt 不会提交到 git。Salt 用于会话内隔离，而非跨机器重现。

**Rotation 政策**：
- 仅在安全事件响应时手动触发
- Salt 版本号记录在 HISTORY.jsonl 每条记录：`"salt_version": N`
- 重现性验证按 salt_version + salt_value + params_sha 组合

### 9.2 符号链接攻击防护

> ⚠️ **审计发现**：`state.make_run_dir()` 未使用 `O_NOFOLLOW`。

**修复**：
```python
# state.py — make_run_dir()
os.makedirs(root / "runs", exist_ok=True)
# Path.mkdir 默认 follow_symlinks=False (Python 3.6+)
d = root / "runs" / uuid.uuid4().hex[:12]
d.mkdir(parents=True, exist_ok=True)
```

### 9.3 Subprocess 注入防护

**规则**：
- 所有 `subprocess.run` 调用必须使用 `shell=False` + argv-list 格式
- 禁止字符串拼接注入
- 需在 `# noqa: S603` 处注明防护措施

### 9.4 LLM 输出溯源

**HISTORY.jsonl 每条记录必须包含**：
```json
{
  "llm_backend": "openai",
  "model_version": "gpt-4o-2024-05-13",
  "prompt_version": "maker-checker-v2",
  "salt": "...",
  "salt_version": 1
}
```

**注入位置**：`app/loop/driver.py:201` 附近，在构造 dict 时加入 salt 字段。

### 9.5 Secrets 清理

`tuning_snapshots/` 预发提交前检查：
```bash
grep -E "(api_key|secret|password|token)" .scratch/loop_state/tuning_snapshots/*.yaml && exit 1 || exit 0
```

---

## 10. 成本与性能

### 10.1 成本安全护栏（当前为死代码）

> ⚠️ **审计发现**：`search.py:136` 中 `over_budget = cfg.weekly_budget_usd > 0 and …`
> 默认 `weekly_budget_usd=0` 导致护栏永远不触发。

**修复后默认值**：

| 参数 | 原默认值 | 修复后默认值 | 说明 |
|------|----------|------------|------|
| `weekly_budget_usd` | `0.0` | `25.0` | 每周 $25 上限（含 LLM + CPU） |
| `dollars_per_cpu_second` | `0.0` | `0.0001` | 激活 CPU 成本监控 |

**LLM 成本测算**：
- 每代 20 个候选 × (1 Maker + 1 Checker) = 40 LLM 调用
- 每个 LLM 调用约 $0.01-0.05
- 每代 LLM 成本：$0.40 - $2.00
- 若每天 2 代，每周 7 天：$5.60 - $28.00
- **结论**：$10 太紧，**$25/周** 是更合理的默认值

### 10.2 并行度控制

```python
import multiprocessing
RESERVED_CORES = 2
MAX_WORKERS = max(1, multiprocessing.cpu_count() - RESERVED_CORES)
```

### 10.3 LLM 调用缓存

- 缓存 key：`hash(maker_prompt_content)` → LLM output
- 存储：内存中（同一代内），不持久化
- 命中率记录到 `llm_cache_hit_total` 指标

### 10.4 重试策略

LLM 调用遇 HTTP 429 / 5xx 时：指数退避 1s → 2s → 4s → 8s（最多 4 次）；超时不重试。

### 10.5 HISTORY.jsonl 读取优化

> ⚠️ **审计发现**：`scheduler.py:74-89` 和 `scheduler.py:217-263` 每次调度 tick 读取完整 HISTORY.jsonl。

**修复**：
1. `state.append_history()` 在写入"accepted"记录时，同时更新 `last_improvement.jsonl` 旁文件（原子操作）
2. Scheduler tick 只读取 `last_improvement.jsonl` + 最近 1000 行
3. `replay_from_history()` 全量重放仅在显式调用时执行

### 10.6 Disk-space 管理

| 目录 | 策略 |
|------|------|
| `runs/<uuid>/` | Pareto 提升后保留 2 代，旧的移入 `archive/` |
| `REJECTED/` | 30 天后 gzip 压缩，超过 90 天删除 |
| `HISTORY*.jsonl.gz` | 永久保留（用于 replay） |
| `outbox/` | 启动时 GC：删除 > 7 天或已被 HISTORY.jsonl 引用之外的条目 |
| `tuning_snapshots/` | Pareto 快照永久保留（已有） |

### 10.7 `apply_tuning()` + 进程池竞态条件（关键 bug）

> ⚠️ **审计发现**：`signal_engine.py` 使用模块级别名（`ATR_WINDOW = TUNING.atr_window`），
> `apply_tuning()` 在主进程修改这些别名后，子进程 fork 时继承当时的值。
> 在 `ProcessPoolExecutor` 中，候选 N 的子进程可能在主进程已切换到候选 N+1 后仍读取旧别名。

**根因**：`worker.py` 通过 `subprocess.run` 调用外部 harness（`run_backtest_v3.py`），
每个候选在独立子进程中运行。子进程通过 pickle 反序列化 TuningConstants，但 `signal_engine.py` 的模块级别名
在子进程导入时绑定到当时的 `TUNING` 单例值，而不是候选的值。

**修复路径（二选一）**：
- **路径 A（推荐）**：将 `signal_engine.py` 中的模块级别名改为函数调用 `get_atr_window()`，
  每次 `score_candidate()` 执行时从参数读取，而非从全局状态读取。
- **路径 B**：`worker.py` 在启动子进程前，将 TuningConstants pickle 序列化后通过 stdin 传给 harness，
  harness 在设置全局状态后立即执行 backtest，不依赖模块级别名。

### 10.8 Gunicorn Worker 与 TUNING 单例同步

> ⚠️ **审计发现**：Gunicorn 启动 4 个 worker，每个都是独立进程，有自己那份 `TUNING` 副本。
> `apply_tuning()` 在主进程修改 `TUNING`，worker 进程不会自动看到新值。

**Promotion 流程**（必须遵守）：
```
accepted 候选 → 写入 tuning_snapshots/pareto-{sha}.yaml
→ 人工审查 PR（修改 app/config/tuning.py）
→ gunicorn 收到 SIGHUP 或重启
→ 新 TUNING 值生效
```

**禁止**：不允许 `apply_tuning()` 在 loop 进程中直接修改运行中 gunicorn worker 的 `TUNING`。

---

## 11. Phase 0：基线测量

Phase 0 是所有后续改进的**前提条件** — 没有基线，无法衡量改进是否有效。

### 0.1 基线指标采集（预计 2-3 天）

在关闭 LLM checker（`MAKER_CHECKER_ENABLED=false`）的情况下，运行 **完整的一代**（建议 20-50 个候选）：

```bash
# 基线运行
python -m app.loop.driver \
  --candidates candidates-baseline.json \
  --state-root .scratch/loop_state \
  --workers 4 \
  --use-maker-checker=false
```

### 0.2 采集指标

| 指标 | 基线值 | 目标改进方向 |
|------|--------|-------------|
| 平均 fitness | X.XXX | 提升 |
| Pareto 前沿大小 | N | 增大 |
| 每候选平均耗时 | T 分钟 | 缩短 |
| 每代总 CPU 时间 | H 小时 | 缩短 |
| LLM 费用（基线为 0） | $0.00 | < $5/代 |
| MC 一致率（基线为 N/A） | — | ≥ 60% |
| suspicious_to_human 率 | — | < 10% |

### 0.3 Phase 0 验收

- [ ] 至少 20 个候选完整运行
- [ ] HISTORY.jsonl 包含所有候选记录
- [ ] PARETO.json 包含非劣解
- [ ] STATE.md 正确反映当前最优解
- [ ] `/metrics` 端点可访问（需先实现 `app/api/metrics_routes.py`）
- [ ] `tuning_proposals_total` 指标正常暴露

---

## 12. 实施路线图

> ⚠️ **审计发现**：当前 `.github/workflows/` 只有 `ci.yml` 一个文件，
> 所有 workflow（daily-triage、ci-sweeper、changelog-drafter、audit 等）均需新建。

### 阶段 1：Foundation（第 1-2 周）

**目标**：建立 Loop Engineering 基础设施，达到 L1

| 任务 | 验收 | 优先级 |
|------|------|--------|
| 重命名 `skills_version.py` → `strategy_version.py`，含 JSONL 字段兼容层 | `grep -r "skills_version" app/` 返回 0 | P0 |
| 创建 `docs/loop-state/` 目录结构（LOOP.md、STATE.md、MEMORY.md 等） | 目录可追踪，`.gitignore` 不覆盖 | P0 |
| 创建 `CLAUDE.md` | 加载 `docs/loop-state/` 记忆、注入项目上下文 | P0 |
| 创建 `gate.yaml` | 路径 denylist 包含 `test-report-*.md`、`__pycache__/` 等 | P0 |
| 创建 `skills/loop-triage/SKILL.md` | 至少覆盖 needs-triage / needs-info 分类 | P1 |
| 增强 `AGENTS.md` | 添加 loop agent 配置节 | P1 |
| 实现 `loop/loop.py` CLI | `doctor` 和 `status` 子命令可用 | P1 |
| 实现 `loop/loop_gate.py` | 检查 `gate.yaml` 违规 | P1 |
| 创建 `docs/adr/0003-loop-engineering-integration.md` | 记录关键决策 | P1 |
| 修复 `app/loop/maker_checker/salt_store.py` 中 `rotate_salt()` bug | 测试验证新旧 salt 不同 | P0 |
| 修复 `signal_engine.py` 的 `apply_tuning()` + 进程池竞态条件 | 运行两代候选验证无竞态 | P0 |
| 添加 `MergeResult.agreement` 字段到 `arbiter.py` | `mc_agreement_rate` 指标可计算 | P1 |
| 创建 `app/api/metrics_routes.py` | `/metrics` 端点可用 | P1 |

### 阶段 2：自动化循环（第 3-4 周）

**目标**：上线 L1 报告循环，达到 L2

| 任务 | 验收 | 优先级 |
|------|------|--------|
| 部署 `daily-triage.yml` | 工作日 9:00 UTC 运行，`docs/loop-state/STATE.md` 更新 | P0 |
| 部署 `changelog-drafter.yml` | 每周一运行，生成 RELEASE_NOTES_DRAFT.md | P1 |
| 部署 `audit.yml` | 每个 PR 运行，发布 Loop Readiness Score | P0 |
| 实现 `loop/loop_audit.py` | Readiness Score 计算正确 | P1 |
| 实现 `loop/loop_sync.py` | `docs/loop-state/` 下文件一致性检查 | P2 |
| 部署 `issue-sync.yml` | `pending_issues/` 文件同步到 GitHub | P1 |
| 创建 `skills/loop-issue-triage/SKILL.md` | 五态分类逻辑正确 | P1 |
| CI 扩展：mypy 覆盖 `app/loop/` | `mypy app/loop/` 通过 | P1 |
| CI 扩展：pyright 覆盖 `app/loop/` | `pyright app/loop/` 通过 | P1 |

### 阶段 3：L2 辅助循环（第 5-6 周）

**目标**：启用建议型循环，达到 L2 成熟度

| 任务 | 验收 | 优先级 |
|------|------|--------|
| 部署 `pr-babysitter.yml`（event-driven，非 cron） | PR 打开时触发，评论 blocking 原因 | P1 |
| 部署 `ci-sweeper.yml` | CI 失败时触发，分析并报告 | P1 |
| 实现 `loop/loop_worktree.py` | Git worktree 隔离管理正常 | P1 |
| 实现 `loop/loop_context.py` | Scratch → Episodic promotion 正确 | P2 |
| 集成 GitHub MCP（read-only） | Issue discovery 可用 | P2 |
| 添加 `pytest-rerunfailures` 到 `requirements-dev.txt` | Flaky test 自动重跑 | P1 |

### 阶段 4：Memory + 观测（第 7-8 周）

**目标**：达到 L3，连接交易循环与开发循环

| 任务 | 验收 | 优先级 |
|------|------|--------|
| 实现完整四层 Memory（含 Durable Facts 追加式和 supersed_by 链） | Durable Facts 矛盾检测正确 | P1 |
| 创建 `docs/loop-state/outerloop-protocol.md` | 两层循环握手协议定义 | P1 |
| `suspicious_to_human` → `pending_issues/` | 自动 issue 文件创建 | P0 |
| Salt 持久化（`salt_store.py`） | Salt 在同一会话内保持一致 | P1 |
| HISTORY.jsonl 读取优化（`last_improvement.jsonl` 旁文件） | Scheduler tick 不再读全量文件 | P2 |
| 观测指标埋点（所有 13 个指标） | `/metrics` 端点暴露全部指标 | P1 |
| 成本护栏激活（`dollars_per_cpu_second=0.0001`） | 预算超限触发 `LoopPausedException` | P1 |
| Disk-space GC 策略（outbox/、archive/、REJECTED/） | 自动化清理 | P2 |

### 阶段 5：依赖 + 清理 + 收尾（第 9-10 周）

**目标**：达到 L3 完整

| 任务 | 验收 | 优先级 |
|------|------|--------|
| 部署 `dependency-sweeper.yml` | 每 6 小时运行，patch 自动合并 | P2 |
| 部署 `post-merge-cleanup.yml` | 峰值外运行，cleanup-PR 正确 | P2 |
| LLM 调用缓存实现 | 缓存命中率指标 > 0 | P2 |
| Pre-commit hook 添加（Secrets 扫描） | 快照提交前检查 | P2 |
| Phase 0 基线测量完成 | 基线指标入库 | P0 |
| TUNING promotion gate 实现（见 §10.8） | Promotion 必须经 PR + SIGHUP | P0 |
| Loop Readiness Score ≥ 85 | 达到 L3 | P1 |

---

## 13. 关键决策登记（ADR）

### ADR-0003：Loop Engineering 整合决策

**状态**：已批准  
**日期**：2026-08-06

#### Decision 1：命名隔离
`skills_version.py` → `strategy_version.py`，HISTORY.jsonl 读写时同时兼容旧字段名。

#### Decision 2：保留 `app/loop/` 现有系统
不对已有交易信号进化系统进行重构，仅通过 Outerloop 协议与之握手。

#### Decision 3：Salt 持久化
Salt 存储在 `.scratch/loop_state/salt.json`，同一会话复用，安全事件时手动 rotation。
`salt_version` 记录在 HISTORY.jsonl 中用于溯源。

#### Decision 4：成本护栏默认值
`weekly_budget_usd` 默认 `$25`（非 $10），`dollars_per_cpu_second` 默认 `0.0001`。

#### Decision 5：CI 类型覆盖扩展
mypy + pyright 覆盖全部 `app/loop/` 代码（包括 maker_checker/）。

#### Decision 6：suspicious_to_human → Issue（解耦）
不直接调用 `gh issue create`，而是写入 `pending_issues/<uuid>.json`，
由 `issue-sync.yml` 在 CI 中统一同步。单个 generation 最多 1 个 issue。

#### Decision 7：Loop 为 POSIX-only
不支持 Windows；WSL 是允许的路径。不引入 `portalocker`。

#### Decision 8：状态文件位置
共享循环状态放在 `docs/loop-state/`（可追踪）；`.claude/` 仅作为本机记忆（gitignore）。

#### Decision 9：TUNING Promotion Gate
`apply_tuning()` 不直接修改运行中 gunicorn worker 的 `TUNING`。
Promotion 必须经过：tuning snapshot → PR → human review → SIGHUP restart。

#### Decision 10：`apply_tuning()` 竞态修复
采用路径 A：函数调用替代模块级别名（`get_atr_window()` 函数），消除进程池 fork 竞态。

---

## 14. 验收标准

### 14.1 Loop Readiness Score

| 阶段 | 目标分数 | 说明 |
|------|----------|------|
| 阶段 1 结束 | ≥ 30 (L1) | 基础文件就位 |
| 阶段 2 结束 | ≥ 58 (L2) | L1 循环全部上线 |
| 阶段 4 结束 | ≥ 85 (L3) | Memory + 观测完整 |

### 14.2 功能验收

每个循环上线前必须通过：

```bash
# 1. Gate check
python loop/loop.py gate check .

# 2. Sync check
python loop/loop.py sync check

# 3. Loop readiness audit
python loop/loop.py audit . --json > score.json

# 4. 集成测试（在 staging 环境）
gh run watch

# 5. /metrics 端点
curl http://localhost:5000/metrics | grep tuning_proposals
```

### 14.3 回归验收

- [ ] `pytest tests/` 全部通过
- [ ] `mypy app/loop/` 无错误
- [ ] `pyright app/loop/` 无错误
- [ ] Phase 0 基线指标的改进方向正确

---

## 15. 未解决问题

| # | 问题 | 影响 | 建议处理方式 |
|---|------|------|------------|
| 1 | `.scratch/backtest/run_backtest_v3.py` 是否应该在 git 中追踪？（CI 不会运行它，但 loop 需要它） | 可重现性 | 将 v3 harness 移到 `bench/` 目录并加入 git |
| 2 | `metrics.json` → `summary.json` 迁移（`worker.py:135-137` 的兼容逻辑） | 代码丑学 | 确定迁移节奏，在 HISTORY.jsonl 中记录 schema 版本 |
| 3 | 多机并发写 HISTORY.jsonl | 数据一致性 | v2 引入 SQLite 或 PostgreSQL；v1 声明 POSIX-only 单机 |
| 4 | 4-D → 5-D Pareto 迁移完成标准 | 运营 | HISTORY.jsonl 中 4-D 记录 < 5% 时，删除兼容逻辑 |
| 5 | `CONTEXT.md`（术语表）缺失 | Agent 理解 | 在 `docs/agents/domain.md` 中补充术语表节，或创建 `docs/agents/glossary.md` |
| 6 | `docs/adr/` 目录不存在，但 `DOCS.md` 引用了 `ADR-001`、`ADR-002` | 规范完整性 | 创建目录，将 ADR-001、ADR-002 内容实际写入，或在 DOCS.md 中修正引用 |
| 7 | `bench/` 与 `app/loop/` 关系未在方案中明确 | 集成风险 | 在 §3 文件结构中标注 `bench/` 为 backtest harness，`app/loop/` 为驱动层 |
| 8 | Drawdown guardrails 完全缺失 | 交易风险 | 见 §16 新增问题 E1 |

---

## 16. 二次审计新增问题

> 以下为二次深度审计发现的新问题，已全部纳入方案正文。

### 16.1 架构冲突：`.claude/` 被 gitignore（问题 A1 + F1）

`.gitignore` 第 181-182 行：
```
# Local AI assistant tooling (not project code)
.agents/
.claude/
```

**影响**：方案将共享状态放在 `.claude/LOOP.md`、`.claude/STATE.md`，但这些文件无法提交到 git。

**解决**：所有共享状态移至 `docs/loop-state/`（可追踪）；`.claude/` 仅作为本机记忆存储（gitignore）。

### 16.2 Salt store 路径与 gitignore 冲突（问题 A3）

`salt.json` 放在 `.scratch/loop_state/`（已在 gitignore 中），意味着 salt 不跨机器持久化。
这与"会话复用"的语义匹配，但与"跨机器重现"矛盾。

**解决**：Salt 用于会话内隔离（语义正确）；跨机器重现通过 `salt_version` + `params_sha` 实现。

### 16.3 Live Trading vs 代码发布的安全门不一样（问题 C1 + E3）

**核心问题**：backtest → live promotion 没有 gate。

当前流程：
```
accepted → apply_tuning() → TUNING 单例 → gunicorn worker（每个有自己副本）
```

**解决**：
1. `accepted` verdict 只写入 `tuning_snapshots/pareto-{sha}.yaml`
2. Promotion 必须 PR 修改 `app/config/tuning.py`
3. Gunicorn 通过 SIGHUP 重新加载配置

### 16.4 `apply_tuning()` + ProcessPoolExecutor 竞态条件（问题 D1）

**根因**：模块级别名在 fork 时绑定到当时的 `TUNING` 值。

**解决**：路径 A（推荐）—— 函数调用替代模块级别名。

### 16.5 Gunicorn worker 不感知 TUNING 变化（问题 D6）

**根因**：每个 gunicorn worker 是独立进程，`apply_tuning()` 在主进程的修改不传播。

**解决**：Promotion 必须走 PR + SIGHUP（已在 Decision 9 中记录）。

### 16.6 `/metrics` 端点不存在（问题 B2）

**解决**：在 `app/api/metrics_routes.py` 中实现，mount 到 `/metrics`。

### 16.7 `gh issue create` 假设 runner 有 gh CLI（问题 C5）

**解决**：pending_issues 旁文件 + `issue-sync.yml` 解耦。

### 16.8 CI workflow 全部需要新建（问题 A2）

当前 `.github/workflows/` 只有 `ci.yml`。所有 workflow 均需新建，已在 §12 中标注 [NEW]。

### 16.9 Salt 注入 HISTORY.jsonl 位置不明（问题 B1）

**解决**：在 `app/loop/driver.py:201` 附近显式注入 salt 字段（已在 §9.4 修复方案中明确）。

### 16.10 `last_improvement.jsonl` 需由 `append_history()` 自己维护（问题 B4）

**解决**：`append_history()` 在写入"accepted"记录时，同时原子更新旁文件。

### 16.11 `rotate_salt()` 示例代码有 bug（问题 I3）

**解决**：实际生成新 salt 并覆盖文件（已修复，见 §9.1）。

### 16.12 JSONL 字段迁移：`skills_version` → `strategy_version`（问题 I1）

**解决**：读取时兼容两个字段名；写入时使用新字段名；BACKFILL 脚本将旧文件一次性迁移。

### 16.13 Drawdown guardrails 缺失（问题 E1）

交易系统的成本不是 API 账单，而是 **drawdown**。

**解决**：在 Backtest Evaluation Guide 中增加：
- `max_drawdown < 2x baseline` 才允许 promotion
- `Calmar ratio > X` 才允许 promotion
- 建议增加 shadow mode：新 tuning 与 live 并行，但不实际下单

### 16.14 `mc_agreement_rate` 指标在代码中未定义（问题 E2）

**解决**：`MergeResult` 增加 `agreement: bool` 字段，定义：当 `|maker.self_score - checker.score| < threshold` 时为 True。

### 16.15 Log 格式含空格无法解析（问题 B5）

**解决**：改用标准 logfmt 格式（见 §7.3）。

### 16.16 Memory Budget 强制执行机制缺失（问题 C4）

**解决**：`loop/loop_audit.py` 在每次审计时执行 token 计数（via `tiktoken`），超限则告警。

### 16.17 Flaky test 检测未指定（问题 C3）

**解决**：`pytest-rerunfailures` + `@pytest.mark.flaky(reruns=2)` + 阈值：2 fails / 10 runs（已在 §4.3 实现方案中明确）。

### 16.18 Windows 支持 ADR 为过度工程（问题 A5）

项目是 POSIX-only（gunicorn + fcntl），WSL 是官方支持的 Windows 路径。

**解决**：删除 portalocker ADR，声明 POSIX-only。

### 16.19 Changelog Drafter 依赖不存在的版本规范（问题 G3）

项目无 `VERSION` 文件，无 `CHANGELOG.md`。

**解决**：阶段 1 先建立版本规范（`pyproject.toml [project] version`），再上线 Changelog Drafter。

### 16.20 Single-developer 项目的 YAGNI 特征（问题 G1-G4）

Daily Triage at 09:00 UTC、PR Babysitter every 15 min 对单开发者项目是 YAGNI。

**解决**：已标注；PR Babysitter 改为 event-driven（PR open 时触发），Daily Triage 降低优先级。

### 16.21 HISTORY.jsonl 部分写入 corruption 处理缺失（问题 D7）

`state.py:96-106` rotation 失败时静默吞掉异常。

**解决**：添加 CRC32 校验；`replay_from_history()` 报告最后有效行号并 quarantine 损坏行到 `.scratch/loop_state/quarantine/`。

### 16.22 Durable Facts 无 downgrade 保护（问题 I2）

**解决**：Durable Facts 追加式；更新时写新条目 + `superseded_by` 字段，不删除旧条目。

---

## 附录 A：与原始方案的差异清单

| # | 优化项 | 审计来源 |
|---|--------|---------|
| 1 | 命名冲突：`skills_version` → `strategy_version` + JSONL 兼容层 | 一次+二次 |
| 2 | `.claude/` 移至 `docs/loop-state/`（gitignore 冲突解决） | 二次 |
| 3 | Salt 路径与 gitignore 冲突解决 | 二次 |
| 4 | YAGNI 特征标注（PR cron → event-driven，Daily Triage 降低优先级） | 二次 |
| 5 | `rotate_salt()` bug 修复 | 二次 |
| 6 | JSONL 字段迁移（含 BACKFILL 脚本） | 二次 |
| 7 | `pending_issues/` + `issue-sync.yml` 解耦 gh CLI 依赖 | 二次 |
| 8 | `last_improvement.jsonl` 由 `append_history()` 自己维护 | 二次 |
| 9 | `/metrics` 端点实现（`app/api/metrics_routes.py`） | 二次 |
| 10 | CI workflow 全部标注 [NEW]（只有 ci.yml 存在） | 二次 |
| 11 | `apply_tuning()` 竞态条件修复（路径 A） | 二次 |
| 12 | Gunicorn worker TUNING 同步问题解决 | 二次 |
| 13 | TUNING Promotion Gate（三步流程） | 二次 |
| 14 | MC agreement_rate 需代码修改（`MergeResult.agreement`） | 二次 |
| 15 | Drawdown guardrails 新增 | 二次 |
| 16 | Memory Budget 强制执行（tiktoken） | 二次 |
| 17 | Flaky test 检测详细方案（阈值 + rerun） | 二次 |
| 18 | Windows 支持 ADR 删除，改为 POSIX-only 声明 | 二次 |
| 19 | Changelog Drafter 需先建立版本规范 | 二次 |
| 20 | Logfmt 格式修正 | 二次 |
| 21 | HISTORY.jsonl corruption 处理（CRC32 + quarantine） | 二次 |
| 22 | Durable Facts 追加式 + superseded_by | 二次 |
| 23 | Phase 0 验收新增 `/metrics` 端点要求 | 二次 |
| 24 | $10/week → $25/week（LLM 成本测算） | 二次 |
| 25 | `loop_candidates_total` → `tuning_proposals_total` | 二次 |
| 26 | ADR-0003 新增 Decision 8-10 | 二次 |
