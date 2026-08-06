# Loop Definitions — pyharmonics-gpt

> 本文件定义了 pyharmonics-gpt 项目中所有开发循环的行为规范。
> 由 `loop/loop_sync.py` 与本文件保持一致。

## 循环成熟度等级

| 等级 | 说明 |
|------|------|
| L1 | 报告模式 — 循环生成报告，人类决定行动 |
| L2 | 辅助模式 — 循环提供建议，人类决定是否采纳 |
| L3 | 自动模式 — 循环在约束内自动执行 |

---

## 循环清单

### 1. Daily Triage（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 工作日每天 09:00 UTC |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `loop-triage` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | Issues (needs-triage, needs-info)、PRs (draft, review requested)、测试报告、最近 Pareto 移动 |
| **输出** | Issue 评论（建议 label）、PR 评论（建议 reviewer）、内部状态更新 |
| **Gate** | 人类决定行动，循环不自动执行 |
| **Worktree** | 不使用 |
| **MCP** | 可选，read-only |

### 2. Issue Triage（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 新 issue 到达时触发（event-driven） |
| **Trigger** | GitHub Actions `issues.opened` |
| **Skill** | `loop-issue-triage` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | 新 open 的 issues |
| **输出** | Issue 评论（建议的 label + triage state） |
| **Gate** | 人类决定，不自动操作 |

### 3. PR Babysitter（L2）

| 属性 | 值 |
|------|---|
| **Cadence** | PR 打开时触发（event-driven，非 cron） |
| **Trigger** | GitHub Actions `pull_request.opened` |
| **Skill** | `loop-pr` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | Open PRs、review comments、CI status |
| **输出** | PR 评论（blocking 原因 + 建议） |
| **Gate** | 建议报告，人类决定是否采纳 |
| **Worktree** | `loop/loop_worktree.py` 隔离管理 |

### 4. CI Sweeper（L2）

| 属性 | 值 |
|------|---|
| **Cadence** | CI 失败后自动触发 |
| **Trigger** | GitHub Actions `workflow_run` (conclusion: failure) |
| **Skill** | `loop-ci-sweep` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | GitHub Actions runs、test failures、flaky test history |
| **输出** | PR 评论（失败原因 + 分类） |
| **Gate** | 人类 gate：major 变更不自动合并 |
| **Worktree** | 在隔离 worktree 中复现并尝试修复 |

### 5. Dependency Sweeper（L2）

| 属性 | 值 |
|------|---|
| **Cadence** | 每 6 小时 |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `loop-dep-sweep` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | `pyproject.toml`、`requirements*.txt`、Dependabot PRs |
| **输出** | 自动合并 patch PR（patch + low-risk CVE） |
| **Gate** | major 依赖人类批准 |

### 6. Post-Merge Cleanup（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 合并后 1-6 小时（低峰期） |
| **Trigger** | GitHub Actions `push` (main) |
| **Skill** | `loop-cleanup` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | 刚合并的 main 分支 diff |
| **输出** | `cleanup-PR` 草稿 |
| **Gate** | 人类批准后合并 |

### 7. Changelog Drafter（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 每周一 或 release tag 时 |
| **Trigger** | GitHub Actions schedule / release |
| **Skill** | `loop-changelog` |
| **State** | `docs/loop-state/STATE.md` |
| **输入** | 过去一周的 commit history、PR titles、Conventional Commits |
| **输出** | GitHub Issue 草稿（`release-prep` label） |
| **Gate** | 人类审核后才发布 |
| **前提** | `pyproject.toml [project] version` 已定义 |

---

## 安全规则

### 路径 Denylist

以下路径不接受自动合并或循环修改：
- `test-report-*.md`
- `__pycache__/`
- `*.pyc`
- `.git/`
- `docs/plans/`（计划文件由人类维护）
- `frontend/node_modules/`
- `.scratch/`（运行时临时状态）

### 自动合并白名单

以下满足条件时可自动合并：
- 仅包含 `pyproject.toml` 或 `requirements*.txt` 的 patch 更新
- `Dependabot` 来源
- CI 全部通过

---

## 调度协调

循环优先级（高→低）：
CI Sweeper → PR Babysitter → Dependency Sweeper → Post-Merge / Changelog → Daily Triage

详见：`docs/loop-state/outerloop-protocol.md`
