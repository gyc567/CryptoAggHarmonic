# Memory Strategy — pyharmonics-gpt

> 本文件定义项目的四层记忆策略。
> 遵循 memory-engineering 的规范。

## 四层定义

| Tier | 生命周期 | 信任级 | 示例 | 存储位置 |
|------|----------|--------|------|---------|
| **Scratch** | 本次会话 | 低 | Agent 调试笔记、open questions | `.claude/MEMORY-STATE.md` scratch 节 |
| **Episodic** | 天-周 | 中 | 上次调参决策、Pareto 移动记录 | `.claude/MEMORY-STATE.md` episodic 节 |
| **Durable Facts** | 持续到撤销 | 高 | 参数范围约束、当前最优 Pareto 解 | `docs/loop-state/durable-facts.md` |
| **Retrieved** | 每次推理 | 变化 | 从 HISTORY.jsonl 提取的历史记录 | 查询时生成 |

---

## 写入规则

1. **Scratch**：任何 agent 可自由写入，无需验证
2. **Episodic**：每天结束时 promote，需简单确认
3. **Durable Facts**：必须经过 human gate 或 `loop-verifier` skill 验证
4. **Retrieved**：按需生成，不持久化

## Promotion 流程

### Scratch → Episodic

- **触发**：每次会话结束
- **验证**：`loop-context` skill 检查 token budget
- **记录**：`.claude/MEMORY-STATE.md` episodic 节追加

### Episodic → Durable Facts

- **触发**：每周 hygiene loop
- **验证**：`loop-verifier` skill 验证一致性
- **记录**：追加新条目（Durable Facts 为追加式，含 `superseded_by` 链）

---

## Hygiene 节奏

每周运行一次 memory hygiene loop：
1. 检查各层条目数量是否超 `memory-budget.md` 中的限制
2. 清理过期的 Episodic 条目（> 14 天）
3. 验证 Durable Facts 与代码一致性
4. 生成 `.claude/MEMORY-STATE.md` 新快照

---

## Budget

| Tier | 最大条目数 | Token 上限 |
|------|-----------|-----------|
| Scratch | 50 | 10,000 |
| Episodic | 100 | 50,000 |
| Durable Facts | 200 | 100,000 |

详见：`docs/loop-state/memory-budget.md`

---

## Code Volume Trend（来自 ponytail-audit）

### 来源

每周 Code Health Audit（`code-health-audit.yml`）运行后，自动追加到 `docs/loop-state/durable-facts.md`。

### 追踪指标

- 按模块统计代码行数（`app/services`、`app/api`、`loop`、`skills`、`patterns`）
- 每周净增减 + 累计趋势
- **不依赖** `ponytail:` 注释（注释是开发习惯，循环无法强制）

### 告警条件

连续 4 周净增长 → 触发 code-health issue（已在 `code-health-audit.yml` 中实现）

### 文件

- 快照：`docs/loop-state/PONYTAIL-DEBT.md`（每月 debt-harvesting.yml 更新）
- 趋势表：`docs/loop-state/durable-facts.md` Code Volume Trend 节
