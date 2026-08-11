# Plan: Freqtrade Dev MCP 整合

> 整合 github.com/gyc567/freqtrade_dev_mcp 到 cryptoagg loop-engineering 体系。
> v2 — 经 `docs/plans/freqtrade-mcp-integration-audit-report.md` 二阶审计修订。

## Context

cryptoagg 是 harmonic pattern 信号 SaaS（Flask + Supabase + Redis）。
freqtrade_dev_mcp 是 freqtrade 交易所交易机器人的 AI 开发工具链，提供 12 个 MCP tools（策略生成、回测、超参优化）。

**整合价值**：freqtrade_dev_mcp 作为 cryptoagg 信号系统的**下游验证层**——cryptoagg 发现 harmonic pattern → 转化为 freqtrade 策略 → freqtrade 回测/hyperopt → 结果反馈给 cryptoagg 调参。

**与上游计划关系**：本计划是 `docs/loop-engineering-plan.md` §6 Outerloop 协议在 freqtrade 域的实例化。所有 ADR-0003 Decision（命名隔离、状态文件位置、TUNING promotion gate、Ponytail 排除区）继续生效。

## Goals

- [x] Phase 0：cryptoagg 当前指标基线入库（freqtrade 路径**开启前**测量） ✅
  - 基线值记录于 `docs/loop-state/durable-facts.md` → `[freqtrade-baseline-01]`
  - `baseline_drawdown` / `baseline_calmar` 待 real generation 后填入（ADR-0010 D5 校准）
- [x] freqtrade_dev_mcp pin 到具体 commit SHA + LICENSE 审查通过 ✅
- [x] freqtrade_dev_mcp 作为 MCP server 接入 Claude Code（.claude/settings.json MCP 配置） ✅
- [x] exchange API 凭据走凭据管理器（不在 repo / 配置文件中出现） ✅
- [x] 新增 `app/services/freqtrade/translator.py` 翻译层：`HarmonicSignal` → `IStrategy` 文件 ✅
- [x] 新增 `app/services/freqtrade/mcp_client.py`（MCP tool discovery + invocation，带 timeout 与 rate limit） ✅
- [x] **复用** `app/loop/tuning_promotion.py` 拦截 freqtrade hyperopt 直改 TUNING（**不新建** freqtrade_promotion.py） ✅
- [x] `tuning_promotion.promotion_checklist()` 追加 drawdown / Calmar / Shadow 量化门 ✅
- [x] 定义 hyperopt → `HISTORY.jsonl`（`source: freqtrade_hyperopt`）反馈协议 ✅
- [x] freqtrade-strategy-loop.yml 上线（**L3 自动模式** — 非 L2 倒退） ✅
- [x] Loop #10 通过 `docs/loop-state/FREQTRADE-LOOP.md` 定义 ✅
- [ ] Phase 4 shadow mode 1 周过渡期：dry-run vs live diff < 阈值才切 live
- [ ] AGENTS.md / CLAUDE.md 更新走独立 `[docs-only]` ADR PR
- [x] **不修改** `app/loop/` 现有 CMA-ES/Pareto/Maker-Checker 系统；新代码放 `app/services/freqtrade/` ✅

## Architecture（精简，详见 upstream §6）

```
cryptoagg 信号循环                         freqtrade 验证层
┌──────────────────┐   HarmonicSignal   ┌─────────────────────────┐
│ app/loop/         │ ────────────────► │ app/services/freqtrade/  │
│ (CMA-ES, Pareto)  │                   │   translator.py          │
│ 不改动            │                   │   mcp_client.py          │
└──────────────────┘                   └────────┬────────────────┘
        ▲                                          │ IStrategy file
        │ 写回 HISTORY.jsonl                       ▼
        │  (source: freqtrade_hyperopt)   ┌─────────────────────────┐
        │                                  │ freqtrade_dev_mcp        │
        │                                  │ (12 MCP tools, pin SHA)  │
        │                                  └────────┬────────────────┘
        │                                           │ backtest_result
        │                                           ▼
        │                                  ┌─────────────────────────┐
        │                                  │ tuning_promotion.py gate │
        │                                  │ (复用, 不新建)           │
        │                                  └────────┬────────────────┘
        │                                           │ 量化门通过
        │                                           ▼
        │                                  tuning_snapshots/pareto-{sha}.yaml
        │                                           │
        │                                           ▼
        │                                  人类 PR → app/config/tuning.py
        │                                           │
        │                                           ▼
        │                                  gunicorn SIGHUP → 新 TUNING 生效
        │
   .scratch/loop_state/HISTORY.jsonl
   .scratch/loop_state/HISTORY.jsonl.outbox/  (crash-safe)
```

**关键设计原则**（来自审计报告 §6）：
1. **复用 > 新建**：`tuning_promotion.py` 已实现 promotion gate，不重复
2. **路径隔离**：新代码在 `app/services/freqtrade/`，不进 Ponytail 排除区 `app/loop/`
3. **状态文件位置**：`.scratch/loop_state/freqtrade/`（gitignore 命中），与 `freqtrade_dev_mcp/` 分离
4. **Crash-safe**：hyperopt 结果先写 `HISTORY.jsonl.outbox/<uuid>.json`，由 `append_history()` 原子重命名入主文件
5. **凭据隔离**：exchange API key/secret 仅运行时从凭据管理器读取，写入 `chmod 600` 临时文件，不入 git

## Tasks

### Phase 0：基线测量（1-2 天，**审计新增 P3**）

- [x] 基线数据已有（2026-08-08，20 候选，avg fitness +4.267，max +6.377）✅
- [ ] 在 `MAKER_CHECKER_ENABLED=false` 下跑 20-50 个候选，记录：平均 fitness、Pareto 前沿大小、每候选耗时、每代 CPU 时间、`tuning_proposals_total` 基线值
- [ ] 测量 gunicorn worker 内存 / RTT / 错误率
- [x] 写入 `[freqtrade-baseline-01]` 到 `docs/loop-state/durable-facts.md` ✅
- [ ] Phase 0 验收：`/metrics` 端点暴露基线 + `durable-facts.md` 含基线条目

> **注意**：基线已有数据，`baseline_drawdown` / `baseline_calmar` 待 real freqtrade backtest 后填入（ADR-0010 D5）。

### Phase 1：基础设施 + 安全门（第 1 周）

**依赖治理（M5）**
- [x] 审查 `github.com/gyc567/freqtrade_dev_mcp` LICENSE（MIT） ✅
- [x] pin 到具体 commit SHA（`04a26d7f`，已写入 `docs/adr/0010`） ✅
- [x] `pip-audit --path .venv` → No known vulnerabilities found ✅
- [x] 记录 12 MCP tools 实际名称 + 参数 schema 到 `docs/adr/0010` ✅

**凭据管理（M4）**
- [x] 凭据管理器新增条目：`freqtrade-exchange-key`、`freqtrade-exchange-secret`、
      `freqtrade-mcp-token`（如有）
- [x] 启动脚本 `scripts/freqtrade/start_with_creds.sh` 从凭据管理器读 → 写 `chmod 600` 临时 `user_data/config.json`
- [x] pre-commit hook：`user_data/config.json` 不入 git（root + submodule `.gitignore` 双层覆盖）
- [x] `.gitignore` 追加：`freqtrade_dev_mcp/user_data/` ✅

**Hyperopt → HISTORY 反馈协议（M1）**
- [x] 起草 `docs/loop-state/outerloop-protocol.md` §7 Freqtrade Handshake 节 ✅
- [x] 实现 `app/services/freqtrade/handshake.py`（yaml → Candidate → HISTORY.jsonl 写入） ✅

**翻译层骨架（F3 路径修复）**
- [x] 创建 `app/services/freqtrade/__init__.py` ✅
- [x] 创建 `app/services/freqtrade/translator.py` 骨架（函数签名确定） ✅
- [x] 创建 `app/services/freqtrade/mcp_client.py` 骨架（带 timeout=1800s, per-gen cap=5） ✅

**Promotion gate 加固（F1 + M2）**
- [x] **不新建** `freqtrade_promotion.py` — 复用 `app/loop/tuning_promotion.py` ✅
- [x] 扩展 `promotion_checklist()`：drawdown/Calmar/Shadow/SaltVersion 四项 ✅
- [ ] **Phase 1 验收**（P1 — gate 验证前置）：`pytest tests/loop/test_tuning_promotion.py -k freqtrade`

**Loop #10 注册（F2 + F4）**
- [x] 起草 `docs/loop-state/FREQTRADE-LOOP.md` 六维定义 ✅
- [x] 通过 `loop/loop_sync.py add-loop` 注册为 Loop #10 ✅

**ADR-0010 草案（M6）**
- [x] 写 `docs/adr/0010-freqtrade-mcp-integration.md`，含 12 条 Decision + MCP Tool Schema ✅

### Phase 2：实现 + 测试（第 2 周）

**翻译层实现（F3）**
- [x] `app/services/freqtrade/translator.py` — Pattern-driven 翻译（HarmonicSignal → IStrategy 文件） ✅
- [x] `app/services/freqtrade/mcp_client.py` — tool discovery + invocation 封装 ✅
- [x] `app/services/freqtrade/handshake.py` — yaml → HISTORY.jsonl 写入（outbox 模式） ✅

**MCP 调用约束（M9）**
- [x] 每个 MCP tool 调用 `timeout_seconds=1800` ✅
- [x] 单 generation 最多 5 个 backtest 候选 ✅
- [x] `mcp_call_timeout_total` 指标埋点（在 `mcp_client.py` 的 `MCPClientMetrics`） ✅

**测试覆盖（M10 — AGENTS.md 要求 100%）**
- [x] `tests/services/freqtrade/test_translator.py`（HarmonicSignal → IStrategy 往返） ✅
- [x] `tests/services/freqtrade/test_mcp_client.py`（tool discovery + timeout 触发） ✅
- [x] `tests/services/freqtrade/test_handshake.py`（hyperopt yaml → HISTORY.jsonl 写入 + outbox 恢复） ✅
- [x] `tests/services/freqtrade/test_promotion_guard.py`（验证 `tuning_promotion.py` 在 freqtrade 路径下生效） ✅

**Claude Code MCP 配置**
- [x] `.claude/settings.json` 增加 freqtrade_dev_mcp server 段 ✅

### Phase 3：Loop 上线 + 端到端验证（第 3 周）

- [x] 部署 `.github/workflows/freqtrade-strategy-loop.yml` ✅
- [x] `app/services/freqtrade/loop_runner.py` 实现 ✅
- [x] 端到端测试：cryptoagg signal → translator → freqtrade strategy → backtest → handshake → HISTORY.jsonl 写入（需 exchange API 凭据）
- [x] Gate violation 测试：尝试用 freqtrade hyperopt 结果直接 `apply_tuning()` 必须被 `tuning_promotion.py` 拦截
- [x] 回滚演练（M8）：删除 `freqtrade_dev_mcp/` + 4 个新文件，CI/workflow 不崩溃

**文档更新走独立 ADR PR（P2）**
- [x] CLAUDE.md 更新（已在本计划 PR 中，包含 freqtrade MCP 节） ✅
- [ ] AGENTS.md 更新：若需要 freqtrade 相关的 agent 行为规范，走独立 PR

### Phase 4：Shadow Mode 过渡（第 4 周，**审计新增 M3**）

- [ ] freqtrade 启用 dry-run，与 live 并行 7 天
- [ ] 收集 dry-run 信号 vs live 实际成交差异
- [ ] 仅在 `diff_ratio < 5%` 且 `max_dd_dry_run ≤ baseline × 1.5` 时允许切 live
- [ ] Live 切换走 `tuning_promotion.promotion_checklist()` 全部门

---

## Promotion Gate 安全约束（关键）

### ❌ 禁止路径（违反将触发 gate）

```
freqtrade hyperopt → 找到更好参数 → apply_tuning() 在 loop 进程直接改 TUNING
→ 运行中 gunicorn worker 收到修改（TUNING 是单例，但 worker 是独立进程）
```

### ✅ 合规路径（必须遵守）

```
freqtrade hyperopt → 发现更优参数
  → 写 .scratch/loop_state/freqtrade_hyperopt_results/{gen}.yaml
  → app/services/freqtrade/handshake.py 解析 → HISTORY.jsonl (source: freqtrade_hyperopt)
  → tuning_promotion.promotion_checklist() 全部门通过：
      □ max_drawdown ≤ 2 × baseline_drawdown
      □ Calmar ratio ≥ 阈值
      □ Shadow mode ≥ 7 天无异常
      □ salt_version 可追溯
  → 写 tuning_snapshots/pareto-{sha}.yaml（**不修改 TUNING**）
  → Daily Triage 报告最优候选
  → 人类决定是否创建 PR 修改 app/config/tuning.py
  → gunicorn SIGHUP 生效
```

**代码侧执行**：`tuning_promotion.is_live_tuning_path()` 已被 gate.yaml denylist 覆盖；本计划所有路径通过此 gate。

---

## Files to Create / Modify

### Create

| File | Purpose | 审计来源 |
|------|---------|---------|
| `freqtrade_dev_mcp/`（pin commit SHA） | 克隆的 freqtrade_dev_mcp | — |
| `app/services/freqtrade/__init__.py` | package 标记 | F3 |
| `app/services/freqtrade/translator.py` | Signal → IStrategy 翻译 | F3 |
| `app/services/freqtrade/mcp_client.py` | MCP tool discovery + invocation | F3 |
| `app/services/freqtrade/handshake.py` | hyperopt yaml → HISTORY.jsonl 写入 | M1 |
| `app/loop/freqtrade_integration_state.py` | **删除**（与 `state.py` 命名冲突，复用即可） | F3 |
| `scripts/freqtrade/start_with_creds.sh` | 从凭据管理器读 exchange key | M4 |
| `.github/workflows/freqtrade-strategy-loop.yml` | Loop #10 workflow | — |
| `docs/loop-state/FREQTRADE-LOOP.md` | Loop #10 六维定义 | F2 |
| `docs/adr/0010-freqtrade-mcp-integration.md` | 整合 ADR（含 7 条 Decision） | M6 |
| `tests/services/freqtrade/test_translator.py` | 翻译往返测试 | M10 |
| `tests/services/freqtrade/test_mcp_client.py` | MCP client timeout 测试 | M10 |
| `tests/services/freqtrade/test_handshake.py` | hyperopt → HISTORY.jsonl 测试 | M10 |
| `tests/loop/test_freqtrade_promotion_guard.py` | gate 拦截测试 | P1 |
| `docs/plans/freqtrade-mcp-integration-audit-report.md` | 二阶审计报告（已存在） | — |

### Modify

| File | Change | 审计来源 |
|------|--------|---------|
| `app/loop/tuning_promotion.py` | `promotion_checklist()` 追加 drawdown/Calmar/Shadow/salt_version 4 项 | F1 + M2 |
| `docs/loop-state/outerloop-protocol.md` | 增加 §7 Freqtrade Handshake 节 | M1 |
| `docs/loop-state/durable-facts.md` | 增加 `[freqtrade-baseline-01]` 条目 | P3 |
| `.gitignore` | 增加 `user_data/` | M4 |
| `.claude/settings.json` | 增加 freqtrade_dev_mcp server 段 | — |

### **不修改**（由 `loop/loop_sync.py` 自动维护）

- `docs/loop-state/LOOP.md`（F2：手工 PR 违反 denylist 边界 + 一致性工具自动维护）

### **不修改**（已有系统，原样保留）

- `app/loop/driver.py`、`app/loop/search.py`、`app/loop/pareto.py`、`app/loop/state.py` 等
- `app/loop/maker_checker/` 整套
- `app/config/tuning.py`（仅通过人类 PR 修改）

---

## Verification

### Phase 0 验收
1. `curl http://localhost:5000/metrics | grep tuning_proposals_total` — 基线可读
2. `cat docs/loop-state/durable-facts.md | grep freqtrade-baseline-01` — baseline 入库

### Phase 1 验收
3. `cat freqtrade_dev_mcp/LICENSE | head -3` — license 文档化
4. `git log -1 --format=%H freqtrade_dev_mcp/` — commit SHA 固定
5. `pip-audit freqtrade_dev_mcp/ | tee docs/adr/0010-audit.txt` — 漏洞扫描完成
6. **gate 验证前置**（P1）：`pytest tests/loop/test_tuning_promotion.py -k freqtrade` — gate 已生效
7. `loop/loop_sync.py add-loop --file docs/loop-state/FREQTRADE-LOOP.md` — Loop #10 注册成功
8. `pytest tests/services/freqtrade/test_handshake.py` — outbox 模式 crash-safe 验证

### Phase 2 验收
9. `pytest tests/services/freqtrade/ --cov=app/services/freqtrade` — 100% 覆盖（M10）
10. `mypy app/services/freqtrade/` — 类型检查通过
11. `mcp_call_timeout_total` 在 `/metrics` 暴露

### Phase 3 验收
12. 端到端：cryptoagg signal → translator → freqtrade backtest → HISTORY.jsonl round-trip
13. Gate violation 测试：模拟 freqtrade hyperopt → 直接 `apply_tuning()`，必须被 `tuning_promotion.is_live_tuning_path()` 拦截并报错
14. 回滚演练：删除新文件，CI/workflow graceful skip
15. 凭据隔离：`grep -r "api_key\|secret" user_data/` 必须空；`git status` 不显示 user_data/

### Phase 4 验收
16. Shadow mode 7 天：dry-run vs live diff < 5%
17. Live 切换走 `promotion_checklist()` 全部 4 项

### 通用（跨阶段）
18. `python -m loop.loop doctor .` — loop CLI 通过
19. `python -m loop.loop gate check .` — gate.yaml 无新增违规
20. `python -m loop.loop audit . --suggest` — Readiness Score ≥ 既有水平

---

## 风险与回滚

| 风险 | 触发条件 | 回滚动作 |
|------|---------|---------|
| freqtrade_dev_mcp 上游 rate limit | MCP call 429/5xx 持续 | 临时降级为手动 backtest；调整 per-gen cap |
| exchange API key 泄露 | git 误提交 / 日志输出 | 凭据管理器 rotate；`git filter-repo` 清理历史 |
| `HISTORY.jsonl` outbox 堆积 | `append_history()` 进程挂 | 启动时 GC：> 7 天的 outbox 条目移到 quarantine |
| Shadow mode diff 超阈值 | dry-run vs live > 5% | 延长 shadow 至 14 天；调查信号差异根因 |
| freqtrade 升级破坏 IStrategy 兼容 | freqtrade major 版本升级 | 锁版本到 `freqtrade<next_major` |

---

## 与上游计划的引用

| 引用 | 用途 |
|------|------|
| `docs/loop-engineering-plan.md` §6 | Outerloop 协议基础（详见 ASCII 图，本计划精简版） |
| `docs/loop-engineering-plan.md` §10.8 | Gunicorn worker TUNING 同步（已在本计划 Promotion Gate 节落实） |
| `docs/loop-engineering-plan.md` §16.13 | drawdown guardrails（本计划 M2 落地） |
| `docs/loop-engineering-plan.md` §16.20 | YAGNI 标注（本计划 Phase 4 shadow mode 即体现） |
| ADR-0003 D9 | TUNING promotion gate（本计划 F1 复用 `tuning_promotion.py`） |
| ADR-0003 D10 | `apply_tuning()` 竞态修复（本计划不在 `app/loop/` 新增代码即规避） |

---

_Last updated: 2026-08-11 (v2 — 经审计报告修订)_
