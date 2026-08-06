# Loop Engineering 入门教程

> 本教程面向所有想要理解并参与 pyharmonics-gpt 项目开发的工程师。
> 无需任何 AI Agent 或 GitHub Actions 经验，只需要熟悉 Python 和 Git。

## 目录

1. [什么是 Loop Engineering？](#1-什么是-loop-engineering)
2. [核心理念：三步走](#2-核心理念三步走)
3. [pyharmonics-gpt 的三层循环](#3-pyharmonics-gpt-的三层循环)
4. [快速上手：CLI 工具](#4-快速上手cli-工具)
5. [七大开发循环](#5-七大开发循环)
6. [记忆分层系统](#6-记忆分层系统)
7. [Loop Readiness Score](#7-loop-readiness-score)
8. [如何扩展新的循环](#8-如何扩展新的循环)
9. [常见问题](#9-常见问题)

---

## 1. 什么是 Loop Engineering？

**Loop Engineering** 是一种设计 AI Agent 工作流的方法论。

传统做法：每次都手动给 AI 发指令（"帮我修复这个 bug"、"帮我写这个功能"）。

Loop Engineering 做法：**设计一个循环系统，让 AI Agent 自主运转，定期完成特定任务**。

类比：传统做法像是每次手动启动汽车；Loop Engineering 像是设置好定时任务，让汽车每天早上自动热车、自动检查状态。

```
传统:  人类 → 发指令 → AI → 响应 → (结束)

Loop:  人类 → 设计循环 → AI 自主运行 → 定期报告 → 人类审核
```

**为什么重要？**

- 减少重复性工作（每日 issue 分类、PR 状态检查、CI 失败分析）
- 让 AI 在人类监督下持续工作，不需要每次都手动触发
- 通过评分体系量化 AI Agent 系统的成熟度

---

## 2. 核心理念：三步走

Loop Engineering 的哲学可以概括为三句话：

> **"Stop prompting. Design the loop. Get a score."**
>
> 别再一个一个发指令了。设计好循环，让它自己跑，然后拿分数。

**三步详解：**

### Step 1: Stop prompting（停止随机 prompt）

不要每次遇到问题就写一个新的 prompt。把重复性的工作抽取出来，定义好触发条件、输入、输出。

### Step 2: Design the loop（设计循环）

每个循环包含四个要素：

| 要素 | 说明 | 示例 |
|------|------|------|
| **触发条件** | 什么时候跑 | 每天 09:00、PR 打开时、CI 失败后 |
| **输入** | 读取什么 | GitHub Issues、PR 列表、测试报告 |
| **处理逻辑** | 做什么 | 分类 issue、标记 stale PR、分析 CI 失败原因 |
| **输出** | 写到哪里 | Issue 评论、PR 评论、更新状态文件 |

### Step 3: Get a score（拿分数）

用 **Loop Readiness Score**（满分 100）衡量循环系统的成熟度。

| 等级 | 分数 | 说明 |
|------|------|------|
| L0 | 0-29 | 完全没有循环基础设施 |
| L1 | 30-57 | 有基础，但需要人工驱动 |
| L2 | 58-84 | AI 提供建议，人类做决定 |
| L3 | 85-100 | AI 在约束内自动执行 |

---

## 3. pyharmonics-gpt 的三层循环

pyharmonics-gpt 有三层循环，它们相互协作但职责不同：

```
┌──────────────────────────────────────────────────────┐
│            Layer 1: 开发循环（Loop Engineering）       │
│                                                      │
│  负责：项目开发效率、代码质量、依赖更新、文档维护        │
│  例子：每日 issue 分类、PR 状态监控、CI 失败分析        │
└──────────────────────────────────────────────────────┘
                          ↕ 握手协议
┌──────────────────────────────────────────────────────┐
│            Layer 2: 交易信号循环（已有）               │
│                                                      │
│  负责：M4  harmonic pattern 交易信号的生成与优化        │
│  例子：CMA-ES 遗传搜索、Pareto 前沿维护、Maker-Checker │
└──────────────────────────────────────────────────────┘
                          ↕ 握手协议
┌──────────────────────────────────────────────────────┐
│            Layer 3: 记忆与状态（Memory Engineering）   │
│                                                      │
│  负责：跨会话记忆、项目事实、token 预算管理             │
│  例子：Durable Facts、Episodic 记忆、token 预算追踪   │
└──────────────────────────────────────────────────────┘
```

**Layer 1 与 Layer 2 的握手协议**：

当 Layer 2（交易信号循环）发现重大进展（如 Pareto 前沿突破），会通知 Layer 1；
当 Layer 1 发现代码质量问题，会通知 Layer 2 暂停或调整。

---

## 4. 快速上手：CLI 工具

pyharmonics-gpt 提供了一套 CLI 工具来管理循环系统。安装项目后即可使用：

```bash
# 检查核心文件是否完整
python -m loop.loop doctor .

# 查看当前循环状态
python -m loop.loop status .

# 检查 Loop Readiness Score
python -m loop.loop audit . --suggest

# 检查 gate.yaml 违规
python -m loop.loop gate check .

# 检查 LOOP.md 和 STATE.md 是否一致
python -m loop.loop sync check .
```

**`doctor` 输出示例：**

```
Checking core files...
  ✓ docs/loop-state/LOOP.md exists
  ✓ docs/loop-state/STATE.md exists
  ✓ docs/loop-state/MEMORY.md exists
  ✓ docs/loop-state/gate.yaml exists
  ✓ loop/loop.py exists
  ✓ loop/loop_gate.py exists
  ✓ loop/loop_audit.py exists

All core files present.
```

**`audit` 输出示例：**

```
Loop Readiness Score: 100.0/100 [L3]

  LOOP.md                ██████████ 100.0%
  STATE.md               ██████████ 100.0%
  Memory                 ██████████ 100.0%
  Skills                 ██████████ 100.0%
  GitHub Actions         ██████████ 100.0%
  Worktree Isolation     ██████████ 100.0%
  Token Budget           ██████████ 100.0%
  Gate.yaml              ██████████ 100.0%
  CLI Tools              ██████████ 100.0%
  ADR                    ██████████ 100.0%

Overall: 100.0/100 [L3]
```

---

## 5. 七大开发循环

pyharmonics-gpt 定义了七个开发循环，按自动化程度分为 L1-L3：

### L1：报告模式（只报告，人类决定）

| 循环名 | 触发条件 | 做什么 |
|--------|----------|--------|
| **Daily Triage** | 工作日每天 09:00 UTC | 扫描 issue/PR/测试报告，生成摘要 |
| **Issue Triage** | 新 issue 打开时 | 建议 label 和分类 |
| **Post-Merge Cleanup** | 代码合并后 | 检测临时文件、dead code |
| **Changelog Drafter** | 每周一 | 从 commit 生成 CHANGELOG 草稿 |

### L2：辅助模式（提供建议，人类决定是否采纳）

| 循环名 | 触发条件 | 做什么 |
|--------|----------|--------|
| **PR Babysitter** | PR 打开时 | 检查 CI 状态、review 进度，标记 blocking |
| **CI Sweeper** | CI 失败后 | 分析失败原因，分类（flaky / regression / infra） |
| **Dependency Sweeper** | 每 6 小时 | 检查过期依赖，建议或自动更新 patch |

### L3：自动模式（在约束内自动执行）

pyharmonics-gpt 目前没有 L3 开发循环（L3 主要用于 Layer 2 交易信号循环）。

---

## 6. 记忆分层系统

Loop Engineering 需要持久化 AI 的"记忆"，否则每次会话都是从零开始。

pyharmonics-gpt 实现了四层记忆系统：

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1: Scratch（会话级）                                    │
│  位置: 内存（程序结束时丢失）                                     │
│  用途: 调试时的临时笔记、open questions                          │
│  示例: "这个 PR 的 CI 失败原因待查"                              │
├─────────────────────────────────────────────────────────────┤
│  Tier 2: Episodic（天-周级）                                   │
│  位置: docs/loop-state/episodic-memory.jsonl                  │
│  用途: 上一次调参的决策、Pareto 移动记录                         │
│  规则: 值需要 ≥256 字符且存活 ≥24 小时才晋升                     │
├─────────────────────────────────────────────────────────────┤
│  Tier 3: Durable Facts（项目级事实）                            │
│  位置: docs/loop-state/durable-facts.md                        │
│  用途: 参数范围约束、当前最优 Pareto 解、代码 owner               │
│  规则: 追加式，不删除旧条目，用 superseded_by 链追踪             │
├─────────────────────────────────────────────────────────────┤
│  Tier 4: Retrieved（每次推理时生成）                            │
│  位置: 查询时从 HISTORY.jsonl 按需提取                           │
│  用途: 历史实验记录、过去的调参决策                               │
└─────────────────────────────────────────────────────────────┘
```

**Scratch → Episodic 晋升规则**（在 `loop/loop_context.py` 中实现）：

```python
def should_promote(key: str, value: str, first_seen: float) -> bool:
    # 条件1: 值足够长（≥256 字符）
    if len(value) < 256:
        return False
    # 条件2: 存活足够长时间（≥24 小时）
    age_hours = (time.time() - first_seen) / 3600
    if age_hours < 24:
        return False
    # 条件3: 通过 gate.yaml denylist 检查
    ...
    return True
```

---

## 7. Loop Readiness Score

Loop Readiness Score 是评估 Loop Engineering 成熟度的量化指标（满分 100）。

**评分维度（10 个）：**

| 维度 | L0 | L1 | L2 | L3 |
|------|----|----|----|----|
| LOOP.md | 无 | 存在但不完整 | 完整定义 | 持续更新 |
| STATE.md | 无 | 手动维护 | 自动更新 | 自动 + 历史 |
| Memory | 无 | Scratch Only | Scratch+Episodic | 四层完整 |
| Skills | 无 | 1-2 个 | 3-5 个 | 全覆盖 |
| GitHub Actions | 无 | 1 个 | 3-5 个 | 全部 7 个 |
| Worktree 隔离 | 无 | 手动 | 半自动 | 全自动 |
| Token Budget | 无 | 有但不执行 | 有并监控 | 有+告警 |
| Gate.yaml | 无 | 存在 | 完整 | 持续更新 |
| CLI Tools | 无 | 部分 | 完整 | 完整+测试 |
| ADR | 无 | 有 | 完整 | 持续更新 |

**当前 pyharmonics-gpt 分数：100/100 [L3]**

---

## 8. 如何扩展新的循环

假设你想添加一个新的循环，例如"测试覆盖率追踪"。

### 第一步：定义循环

在 `docs/loop-state/LOOP.md` 中添加循环定义：

```markdown
### 8. Test Coverage Tracker（L1）

| 属性 | 值 |
|------|---|
| **Cadence** | 每周五 18:00 UTC |
| **Trigger** | GitHub Actions schedule |
| **Skill** | `loop-coverage` |
| **State** | docs/loop-state/STATE.md |
| **输入** | coverage.xml、PR 列表 |
| **输出** | Coverage 趋势报告 Issue |
| **Gate** | 人类决定行动 |
```

### 第二步：创建 Skill

在 `skills/` 目录下创建 skill 目录：

```bash
mkdir -p skills/loop-coverage
touch skills/loop-coverage/SKILL.md
```

编写 `SKILL.md`：

```markdown
# SKILL.md — loop-coverage

## 触发条件
每周五 18:00 UTC 由 GitHub Actions 调用。

## 输入
- `coverage.xml`（pytest-cov 生成）
- 当前 PARETO.json

## 输出
- 更新 `docs/loop-state/STATE.md` 中的 coverage 指标
- 生成 coverage 趋势评论

## 规则
1. 只读取，不修改任何源代码
2. coverage 下降 >5% 时标记为 warning
3. 所有输出必须通过 gate.yaml 检查
```

### 第三步：创建 GitHub Actions Workflow

在 `.github/workflows/` 下创建 `coverage-tracker.yml`：

```yaml
name: Coverage Tracker

on:
  schedule:
    - cron: "0 18 * * 5"  # 每周五 18:00 UTC

jobs:
  track:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Run coverage
        run: pytest --cov=app --cov-report=xml
      - name: Analyze coverage
        run: python -c "import xml.etree.ElementTree as ET; ..."
```

### 第四步：运行验证

```bash
python -m loop.loop sync check .   # 检查一致性
python -m loop.loop audit .        # 确认分数提升
```

---

## 9. 常见问题

**Q: Loop Engineering 和普通 CI/CD 有什么区别？**

A: CI/CD 是"代码变化后做什么"（被动响应）。Loop Engineering 是"定期主动做什么"（主动运转）。CI/CD 关注代码质量，Loop Engineering 关注开发效率。

**Q: 我的 PR 被 CI Sweeper 标记为 regression，是什么意思？**

A: CI Sweeper 将失败分类为三类： `regression`（你的改动引起的）、`flaky`（测试本身不稳定）、`infra`（CI 基础设施问题）。regression 意味着你的改动很可能是罪魁祸首，需要优先修复。

**Q: 如果 Loop Readiness Score 下降了怎么办？**

A: 运行 `python -m loop.loop audit . --suggest`，它会告诉你哪个维度扣分了。例如如果 Skills 维度下降，说明某个 skill 文件被删除或格式损坏了。

**Q: Durable Facts 里的信息被 superseded 了，但旧条目还在文件里，这正常吗？**

A: 正常，这是设计使然。Durable Facts 是**追加式**的，永远不删除旧条目，而是用 `superseded_by` 字段指向新条目。这样可以保留完整的决策历史，方便审计和回溯。

**Q: Scratch 层的记忆丢失了，有办法恢复吗？**

A: 没有，因为 Scratch 就是设计为会话级丢失的。如果某个 Scratch 信息重要，应该在 24 小时后晋升到 Episodic 层。如果还没晋升就丢了，说明它其实没那么重要。

**Q: gate.yaml 的 denylist 支持正则吗？**

A: 支持。gate.yaml 中的 `denylist` 字段使用简单的子字符串匹配，不支持正则。如果需要正则，可以使用 Python 的 `fnmatch` 或 `re.search`。

---

## 附录：快速命令参考

```bash
# 检查循环基础设施
python -m loop.loop doctor .

# 查看循环状态
python -m loop.loop status .

# 计算并显示分数
python -m loop.loop audit .

# 只显示分数（JSON 格式）
python -m loop.loop audit . --json

# 检查 gate.yaml 违规
python -m loop.loop gate check .

# 检查 LOOP/STATE 一致性
python -m loop.loop sync check .

# 估算 token 成本
python -m loop.loop cost .
```

---

## 相关文档

- [Loop Engineering 完整方案](loop-engineering-plan.md)
- [Loop 定义](loop-state/LOOP.md)
- [循环状态](loop-state/STATE.md)
- [记忆策略](loop-state/MEMORY.md)
- [ADR-0003：Loop Engineering 整合决策](adr/0003-loop-engineering-integration.md)
