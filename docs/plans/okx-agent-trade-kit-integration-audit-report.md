# Audit Report — OKX Agent Trade Kit 整合

> Loop Engineering 视角对 `docs/plans/okx-agent-trade-kit-integration.md` v1 的二阶审计。
> 参考：`docs/loop-engineering-plan.md` §16 审计范式、`docs/adr/0010-freqtrade-mcp-integration.md`（11 条决策）、
> `app/loop/tuning_promotion.py`（现状）、`docs/loop-state/gate.yaml`、`AGENTS.md` North Star + Ponytail 约束。
>
> 审计日期：2026-08-11
> 审计者：loop-audit (auto)
> 标的版本：plan v1

---

## 0. 审计摘要

| 维度 | 评分 | 备注 |
|------|------|------|
| 与 freqtrade 整合 (ADR-0010) 的一致性 | **C** | 多处与 ADR-0010 已落地决策冲突（F1-F3）|
| 路径 / 命名 / Denylist 合规 | **B** | 1 处 denylist 边缘，1 处可复用现有 path |
| L 等级目标合理性 | **C** | OKX 写操作风险高于 freqtrade，目标 L3+ 但描述缺细节 |
| 安全门（三重门） | **B** | D1 三重门是新增概念，必须 v2 落地细节 |
| 与现有基础设施的复用度 | **D** | v1 多处重复造轮（F4-F6）|
| 模块选择（D8）的可行性 | **A** | Phase 1 收窄到 market+account+spot paper 合理 |
| 验证完整性 | **C** | 端到端 / 5 场景回滚可落地，但缺 Phase 0 基线 |

**总体结论**：**条件性通过**。v1 框架方向正确，但 6 个 F 类问题（与已有 ADR-0010 冲突）+ 4 个 M 类缺失需要在 v2 解决后才能进 Phase 0。最低修复集见 §6。

---

## 1. 与现有基础设施的冲突（事实层）

### F1. 「不新建 okx_promotion」是空话 — v1 实际加了 `is_live_execution_path()` 新函数

**事实**：
- `app/loop/tuning_promotion.py` 已落地（66 行），含 `is_live_tuning_path()` + `promotion_allowed_for_files()` + `promotion_checklist()` 三个公共 API，是 ADR-0003 D9 + ADR-0010 D5 共同代码。
- v1 §3.1 D1 / §6 Modify 列表写"在 `app/loop/tuning_promotion.py` 加 `is_live_execution_path()` + checklist 新增 audit log 强制项" — 实际就是**扩展** `tuning_promotion.py`。

**问题**：
- v1 同时说"复用 `tuning_promotion.py`"（D1 标题）+ "扩展 `tuning_promotion.py`"（Modify 表），文字有歧义。
- 但 v1 没明确 `is_live_execution_path()` 的语义 — 是"路径 gate"（拦截直接调 OKX 写 tool 的代码路径）？还是"运行时 gate"（拦截写 tool 调用）？
- 当前 `is_live_tuning_path` 是**文件路径 gate**（审 PR 时检查改的文件路径），OKX 写操作是**运行时 tool call gate**（审每次 MCP 调用）。两者性质不同，混在一起会让 `tuning_promotion.py` 既管"PR-level 文件 gate"又管"runtime tool gate"，职责过载。

**修复 (v2)**：
- `is_live_tuning_path` / `promotion_allowed_for_files` 保持原语义（PR-level 路径 gate）
- 新增 `is_live_execution_tool(name: str) -> bool`（runtime-level tool gate，名字而非路径）
- 新增 `execution_allowed_for_tools(names: list[str], paper: bool) -> tuple[bool, str]`
- checklist 加 `audit log` 强制项，但**不**改 `is_live_tuning_path` / `promotion_allowed_for_files` 签名
- 文档明确两个 gate 的边界：路径 gate = PR review；tool gate = runtime check

### F2. `tuning_promotion.py` 在 §6 Modify 列表 — 实际应该是"扩展"而非"修改"

**事实**：v1 §6 Modify 表写"`app/loop/tuning_promotion.py` 加 `is_live_execution_path()`"。

**问题**：
- `app/loop/` 在 Ponytail 排除区（AGENTS.md "Ponytail Constraint Scope"），**但 `tuning_promotion.py` 是已落地的 gate 工具**，不在科学实验代码区。
- 不过 v1 没区分清楚"扩展既有 gate 函数"（OK）vs"修改 `tuning_promotion.py` 的现有行为"（违反"不修改既有 API"原则）。

**修复 (v2)**：
- §6 Modify 表改：`**Extend** app/loop/tuning_promotion.py — 追加 is_live_execution_tool + execution_allowed_for_tools + audit log 强制项，**不动现有 3 个 API**`
- 加约束："不修改 is_live_tuning_path / promotion_allowed_for_files / promotion_checklist 的现有签名"

### F3. v1 D1「env gate OKX_PAPER_MODE=true 默认 true」与 OKX MCP `--read-only` flag 重复

**事实**：
- OKX MCP server 自带 `--read-only` flag（ARCHITECTURE.md §6），**启动时**禁用所有 `isWrite=true` tool。
- v1 D1 第 1 重门是 env `OKX_PAPER_MODE=true` 默认拒写。

**问题**：
- 如果 `.claude/settings.json` 的 okx 段启动参数就是 `--read-only`（v1 D2 已说 default 是 `--modules market,account --read-only`），那写 tool 根本不会出现在 tool list 里 — D1 第 1 重门（env）已经被 MCP server 启动参数保证。
- 两层 gate 看似冗余，实则分场景：
  - `--read-only` 启动参数 = 静态配置（启动时决定）
  - `OKX_PAPER_MODE` env = 运行时切换（同一进程可临时允许写）
- 但 v1 没明确两者关系 — 容易让人误以为配置错了就 1 重门被绕过。

**修复 (v2)**：
- D1 第 1 重门重写为：`.claude/settings.json` 启动参数 = `market,account,spot --read-only`（**Phase 1 必填**），env `OKX_PAPER_MODE` 只用于**升级到 swap 等写模块时**的运行时切换
- 加 ADR-0011 D-decision：D-decision-1 「MCP 启动参数 default = `--modules market,account,spot --read-only`，写模块启用必须人审配置」

### F4. v1 §3.7 表格「OKX 改交易所账户」与「TUNING 无关」描述不精确

**事实**：freqtrade hyperopt 反馈 TUNING（修改 `app/config/tuning.py`），是 ADR-0010 D4 设计的。OKX 写操作**不**直接改 TUNING，但**会**通过 audit log + HISTORY.jsonl 间接影响 `okx_live` source 的 fitness 数据 — cryptoagg CMA-ES loop **不**消费 OKX 数据。

**问题**：
- v1 §3.7 「OKX 改交易所账户，不改 TUNING」让读者误以为 OKX 与 TUNING 完全解耦。
- 实际：OKX 写操作产生的 audit log 是**事后分析用**（回放 fill vs signal），**不**进入 tuning snapshot → 不会触发 TUNING promotion。
- 但 OKX 的 market data（funding rate / OI / mark price）**可能**成为未来 cryptoagg CMA-ES 的输入特征 — 这一点 v1 没说。

**修复 (v2)**：
- §3.7 表格 OKX 列改：「**不直接**改 TUNING；audit log 仅事后分析；**未来 Phase 5+** market data 可能进 CMA-ES 特征」
- 加 explicit 决策：「OKX 数据不进 Phase 0-4 的 TUNING promotion 路径」

### F5. v1 §6 Create 列表中 `package.json` 与项目现状冲突

**事实**：
- 项目当前是 **Python-only**（`pyproject.toml` 是 setuptools 后端）。
- 仓库根目录**没有** `package.json`，没有 `node_modules/`，**没有** `.nvmrc`。
- v1 §6 Create 列表说"新建 `package.json`" + "在 `.claude/settings.json` 的 `mcpServers` 加 okx 段"。

**问题**：
- 新建 `package.json` 在 Python 仓库中会**误导** CI/IDE（TypeScript 工具链会找它）。
- 实际只需要 1 个 file 记录 OKX npm 版本（manifest 用），不需真 package.json。
- OKX 既然是全局 npm 安装（用户已确认 D2 = A），version 记录可以放更轻的形式。

**修复 (v2)**：
- Create 表改：`**Create** scripts/okx/VERSION`（只 1 行 `1.0.4` + 注释）
- 不新建 `package.json`
- 加注释：OKX 升级必须人审 `npm view @okx_ai/okx-trade-mcp versions`

### F6. v1 §3.6 audit log 文件路径与 freqtrade handshake 的 outbox 模式不统一

**事实**：
- freqtrade handshake 写 `.scratch/loop_state/HISTORY.jsonl.outbox/{uuid}.json` → atomic rename → outbox 清理（ADR-0010 D4 crash-safe 模式）。
- v1 §3.6 OKX audit log 写 `.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl` — **直接 append**，无 outbox。

**问题**：
- OKX 写操作是**真金白银**的副作用，比 freqtrade handshake 严重得多。
- 直接 append 没有 crash-safe 保护：进程挂 → 写了一半 → audit 不完整 → 不可重放。
- v1 D6 说"append-only（不可删 / 改）"但没说"atomic append"。

**修复 (v2)**：
- audit log 也走 outbox 模式：`.scratch/loop_state/okx/audit/{YYYY-MM-DD}.jsonl.outbox/{uuid}.json` → atomic rename → outbox 清理
- 复用 `app/loop/state.append_history()` 的 outbox 语义
- 加 explicit decision：audit log crash-safe = 复用 HISTORY.jsonl outbox pattern

---

## 2. 缺失的关键设计要素

### M1. 缺 Phase 0 基线（与 freqtrade 同样的 P3 缺失）

**事实**：
- `docs/loop-state/durable-facts.md [freqtrade-baseline-01]` 已记录 cryptoagg signal loop 在 freqtrade 路径**开启前**的基线。
- v1 §5 Phase 0 仅 0.5 周 4 项：.env 占位 / `pip-audit` / ADR-0011 草案 / 审计报告 — **没有**测量 cryptoagg 现状基线。

**问题**：
- OKX 整合完成后，无法用 baseline 衡量"OKX 路径是否带来 improvement"。
- AGENTS.md "North Star metrics" 要求改进要**量化**，不是描述。

**修复 (v2)**：
- Phase 0 加：
  - `[ ] 测量 cryptoagg 当前 `/metrics`：tuning_proposals_total、signal_latency_p95、analyze_api_rps`
  - `[ ] 测量 Binance 主行情路径延迟 (curl_cffi) 作为对比基准`
  - `[ ] 记录 baseline 到 durable-facts.md [okx-baseline-01]`

### M2. 缺 KEY 轮换 (rotation) 流程

**事实**：
- freqtrade E2E 期间用户 chat 明文贴 key，durable-fact `[freqtrade-e2e-01]` 强建议 rotate。
- v1 §6 "凭据管理" 写 4 项但**没**写 rotate 流程。

**问题**：
- Key 轮换是 Keychain-based 凭据的**必填操作**：泄露 / 定期 / 换员工都得 rotate。
- 没有流程 = rotate 靠用户记忆 = 出错率高。

**修复 (v2)**：
- `scripts/okx/start_with_creds.sh` 加 `--rotate` flag（**与 freqtrade 一致**，不新建）
- 文档化：rotate 步骤 1) Binance/OKX console revoke 旧 key 2) 生成新 key 3) `security update-generic-password -s cryptoagg-okx -a api-key -w NEW_KEY` 4) 重启 loop
- 加 decision D-rotation：90 天强制 rotate（与 audit log 留存期一致）

### M3. 缺 npm 全局包损坏检测 + 自动重装策略

**事实**：
- v1 D2 选 A（npm 全局），但 .claude/settings.json 的 okx 段写 `"command": "okx-trade-mcp"` — 假设 PATH 中能找到。
- 如果 `node_modules` 被误清 / 路径 PATH 不对 / 不同 shell 找不到 — MCP server 启动失败。

**问题**：
- v1 §3.5 提到"npm 全局包被误删 → `scripts/okx/install.sh --verify` 检测到 → 报错退出，**不自动重装**"。
- 但 v1 Create 表里**没有** `scripts/okx/install.sh --verify` 设计。

**修复 (v2)**：
- `scripts/okx/install.sh` 设计两个子命令：
  - `install` — `npm i -g @okx_ai/okx-trade-mcp@1.0.4` (幂等)
  - `verify` — `command -v okx-trade-mcp && okx-trade-mcp --version | grep -q 1.0.4` (非破坏性，CI 用)

### M4. 缺写操作的 nonce / 重放保护

**事实**：
- OKX API 用 ISO timestamp + HMAC-SHA256，但**没有** nonce（与 Binance 一样）。
- 如果同一秒两次下单（重放），OKX 视为同一请求可能拒，可能接受 — 取决于 endpoint。

**问题**：
- v1 没说如何避免重放。
- cryptoagg loop 可能在毫秒级并发触发多个写 tool（如果 gate 漏）。

**修复 (v2)**：
- 加决策 D-replay：`executor.py` 内强制每次写 tool 调用的 `clOrdId` (client order id) 必须含 `salt_version + uuid` 唯一后缀
- 复用 `cryptoagg` 已有的 `clOrdId` 规范（如果存在）或新建 `OKX-LOOP-{uuid12}`

### M5. 缺 npm 升级安全门（用户确认锁 1.0.4 长期）

**事实**：
- 用户已确认 "5. 锁 1.0.4 长期"。
- v1 §3.2 决策 D2 写"在 `package.json` 记版本" + "升级必须人审 npm changelog"。

**问题**：
- "升级必须人审" 是口头约束，没有 code-level enforcement。
- 需要 (a) 启动时检查版本 (b) 不匹配则 fail-fast 提示升级。

**修复 (v2)**：
- `scripts/okx/install.sh verify` 检查 `okx-trade-mcp --version == 1.0.4`
- 在 `.claude/settings.json` okx 段加注释说明（人类编辑时警觉）
- 加 decision D-version-lock：`docs/adr/0011` 必须包含"如何从 1.0.4 升级到 1.0.5 的 ADR 模板"

### M6. 缺 OKX 三要素 + passphrase 验证

**事实**：
- OKX 三要素是 `api_key` + `secret_key` + `passphrase` — passphrase 是 OKX 独有。
- v1 Keychain 4 个 account 设计（`api-key` / `secret-key` / `passphrase` / `paper-mode`）— 但 paper-mode 实际是 env 不是 secret。

**问题**：
- `paper-mode` 不是 secret，放 Keychain 浪费且语义混乱。
- passphrase 易错（大小写 / 前后空格），v1 没设计"启动期验证 passphrase 正确"流程。

**修复 (v2)**：
- Keychain 3 accounts：`api-key` / `secret-key` / `passphrase`
- `paper-mode` 移回 env variable（v1 §3.3 表里已经标 env 合适，但 Create 表没改）
- 启动期验证：`executor.py` 启动时调 `account_get_balance`（不需私有钱包操作），成功 = 三要素正确；失败 = 报错退出
- 加 decision D-passphrase-verify

### M7. 缺 Rate Limit 与 OKX server-side rate limit 协调

**事实**：
- OKX MCP server 自带 client-side token bucket rate limiter（ARCHITECTURE.md §4.3）。
- OKX server-side rate limit 是 20 req/2s（公开文档）。
- v1 D8 提到 "per-gen cap=5" 但没说与 OKX server-side 关系。

**问题**：
- `MAX_BACKTEST_PER_GEN=5` 是 freqtrade 决策，OKX 写操作的 per-gen cap 没定义。
- OKX server-side 拒 429 后，client-side limiter 没协调 = retry storm。

**修复 (v2)**：
- OKX per-gen cap：`MAX_OKX_WRITE_PER_GEN=3`（比 freqtrade 严，写操作有副作用）
- 错误处理：`okx_api_error code=50011`（rate limit）→ 等 5s + 单次重试；不重试 on 50012+（鉴权错误）
- 在 `mcp_client.py` 加 metric：`okx_rate_limit_retry_total`

### M8. 缺 swap/spot 选择决策（v1 D8 只说"Phase 1 必做 market+account+spot paper"，没说 spot vs swap 选择逻辑）

**事实**：
- v1 D8 Phase 1：market + account + spot paper。
- v1 §4 Architecture 中 `executor.py` 既处理 spot 又处理 swap。
- 实际：cryptoagg 当前是**现货信号**（harmonic pattern 在 spot 上跑），不是永续合约。

**问题**：
- spot 与 swap 是两种 instrument，order params 完全不同（spot 无 leverage，swap 有）。
- v1 没明说"Phase 1 只做 spot 写，swap 写留给 Phase 2"。

**修复 (v2)**：
- §3.1 D1 改为："**Phase 1 仅 spot paper 写**；swap / futures / option 写操作**明确不**在 Phase 1-3 范围"
- §4 Architecture 调整：`executor.py` 初始只支持 spot，swap 是未来 phase
- Add decision D-instrument-scope

### M9. 缺 audit log 字段定义（v1 §3.6 只有例子 1 行）

**事实**：
- v1 §3.6 audit log 例子：`{"ts": "...", "tool": "spot_place_order", "args": {...}, "result_code": "0", "user": "loop#11", "salt_version": 3, "paper": true}`
- 缺字段：trace_id、order_id、fill_id、latency_ms、retry_count、error_stack（失败时）。

**问题**：
- audit log 字段不全 → 事后分析时缺关键 trace 数据。

**修复 (v2)**：
- audit log 必填字段（schema）：
  - `ts` (ISO 8601 with microseconds)
  - `tool` (MCP tool name)
  - `args` (sanitized — 不含 secret)
  - `result_code` (OKX code or "EXCEPTION")
  - `result_body_hash` (sha256 of response, 不存全文避免 PII)
  - `user` (loop id)
  - `salt_version`
  - `paper` (bool)
  - `cl_ord_id` (client order id for replay protection)
  - `latency_ms`
  - `trace_id` (OKX traceId from response)

### M10. 缺测试用例对应 OKX 5 场景回滚

**事实**：
- v1 §3.5 列 5 场景回滚（删除 `app/services/okx/` / Keychain 缺 / MCP 进程挂 / npm 包误删 / passphrase 错），但 §6 Create 表里只 6 个 test_*.py 文件 — 没有 1-to-1 覆盖 5 场景。

**修复 (v2)**：
- 加 `tests/services/okx/test_rollback_drill.py`：
  - `test_services_removed_graceful_skip`
  - `test_keychain_missing_refuses_startup`
  - `test_mcp_heartbeat_timeout` (mock)
  - `test_npm_package_missing_reports_no_autorepair`
  - `test_wrong_passphrase_does_not_leak_secret`
- 跑在 `tests/services/okx/` 下，被 `pytest` 收集

### M11. 缺 OKX 与 freqtrade 的 TUNING 互斥锁（v1 D7 提到但没实现细节）

**事实**：
- v1 D7 说"互斥锁，gate.yaml 加规则"。
- 当前 `docs/loop-state/gate.yaml` denylist 没有 OKX 相关规则。

**修复 (v2)**：
- `docs/loop-state/gate.yaml` 加：
  - denylist: `"app/services/okx/executor.py"` （loop 不能改）
  - always_exclude: `"**/okx-audit.log"`（凭据相邻隔离）
- 互斥锁实现：`HISTORY.jsonl` source 字段是 `freqtrade_hyperopt` 或 `okx_live` / `okx_paper` — 同一天同一 candidate 不允许两个 source 写（防 race）。由 `app/loop/state.append_history()` 加 check。

### M12. 缺 ADR-0011 草案正文（v1 §2.1 标 todo）

**问题**：v1 §2.1 把 ADR-0011 列为 Phase 0 必做，但没给草案骨架。

**修复 (v2)**：
- v2 直接给 ADR-0011 的 Decision 候选 12 条（继承 ADR-0010 11 条 + OKX 8 条新增，剔除重复）

---

## 3. Phase 排序与依赖问题

### P1. Phase 1 节奏压缩到 0.5 周（用户已确认） — 任务量需重排

**事实**：v1 Phase 1 1 周含 5 大类 13 子任务；用户选 0.5 周。

**问题**：0.5 周 ≈ 2-3 个工作日，13 子任务几乎必崩。

**修复 (v2)**：
- Phase 1 拆为 Phase 1A (0.25 周) + Phase 1B (0.25 周)：
  - **1A**：npm install + Keychain + 凭据脚本 + .env 占位 (4 项)
  - **1B**：tuning_promotion 扩展 + executor.py skeleton + Loop #11 注册 + ADR-0011 (4 项)
- 1A 验收：可以 `okx-trade-mcp --modules market --read-only` 启动 + Keychain --check 全过
- 1B 验收：可以 `pytest tests/services/okx/test_promotion_guard.py`

### P2. 写操作端到端测试用 paper mode 还是 mock？

**事实**：v1 Phase 3 端到端："cryptoagg signal → translator → OKX paper order → fill → handshake → HISTORY.jsonl" — 但 OKX paper 模式**仍然走真实 OKX 模拟盘服务器**，需要网络。

**问题**：
- CI 环境通常**无** OKX 凭据 / 无网络。
- 真跑 paper 模式 = 测试 flaky 依赖 external service。

**修复 (v2)**：
- 端到端测试双层：
  - **单元 + mock**：`tests/services/okx/test_executor.py` mock `mcp_client.invoke_tool()` 返回 fill 数据
  - **集成**（不在 CI 跑）：`scripts/okx/e2e_paper.sh` — 需 OKX paper 凭据，本地手动跑
- 在 v2 §3 标注："CI 跑 mock 集成；真实 paper fill 测试在 docs/test-report-okx-paper.md 记录"

### P3. Phase 4 shadow mode 与 paper mode 概念混用

**事实**：
- v1 §5 Phase 4 "OKX paper mode vs freqtrade 回测并行 7 天"
- OKX paper mode = OKX 模拟盘（有真实 OKX 服务器响应）
- cryptoagg shadow mode = dry-run 模式（无服务器，纯本地回放）

**问题**：两个概念混在一起描述会让"diff < 10%"的指标意义不清。

**修复 (v2)**：
- Phase 4 重命名为 "Paper + Backtest 对比 7 天"
- 明确：OKX paper fill 跟 freqtrade backtest fill 对比（不是两个 source 的对比）
- 验收指标重写：OKX paper fill 数量 vs freqtrade backtest 成交数（不是 ratio，是绝对差）

---

## 4. 文档/格式问题（次要）

### D1. v1 §10 开放问题 8 个，用户已答 — 应移到 ADR-0011 决策表

**问题**：v1 §10 列 8 开放问题（已答），但这些答案是**决策**，应入 ADR-0011 Decision 候选表，不应留在开放问题里。

**修复 (v2)**：
- v2 §10 改为 "已确认的决策" 表，链到 ADR-0011
- 8 个答案翻译成 8 个 ADR Decision（见 §6 v2 修复清单）

### D2. v1 §3.7 「互斥锁，gate.yaml 加规则」 — 没说互斥锁怎么实现

**问题**：v1 提互斥锁但不写实现。

**修复 (v2)**：
- §3.7 决策改："互斥锁由 `app/loop/state.append_history()` 实现：同 candidate_id + 同 gen 不允许同时含 freqtrade_hyperopt 和 okx_live/paper source（race 检测）"
- 写 `tests/loop/test_append_history.py::test_source_mutex`

### D3. v1 §4 ASCII 图与 outerloop-protocol.md §7 重复

**问题**：v1 §4 Architecture 画 ASCII 与 `docs/loop-state/outerloop-protocol.md` §7 Freqtrade Handshake ASCII 重叠 60%。

**修复 (v2)**：
- §4 Architecture ASCII 删 — 改为引用 outerloop-protocol.md §8 OKX Handshake
- 新建 `outerloop-protocol.md §8 OKX Handshake`（与 §7 Freqtrade 同结构）

### D4. v1 §3.1 D1 与 §4 工具名称不一致

**事实**：
- v1 §3.1 D1 提 `is_live_execution_path()` (path-based)
- v1 §3.1 D1 又提 `executor.py` 拦截写 tool 调用 (tool-based)

**问题**：path-based 与 tool-based 混用。

**修复 (v2)**：见 F1，统一为 `is_live_execution_tool()`。

### D5. v1 §6 Create 列表的 `app/services/okx/executor.py` 没说 stub 还是实现

**修复 (v2)**：明确"Phase 1 stub（仅含 gate 拦截 + audit 写入），Phase 2 实现 spot order 完整 flow"。

---

## 5. Phase 划分（v1 原表，已对齐用户选择）

| Phase | v1 周 | v2 修订 | 关键差异 |
|---|---|---|---|
| 0 | 0.5 | 0.5 | + M1 基线测量 |
| 1A | (new) | 0.25 | 拆 1A: 依赖 + 凭据 |
| 1B | (new) | 0.25 | 拆 1B: gate + skeleton + Loop #11 |
| 2 | 1.5 | 1.5 | 无变化（100% 测试） |
| 3 | 1 | 1 | + M10 5 场景回滚测试 |
| 4 | 1 | 1 | + P3 重命名"Paper + Backtest 对比" |
| **总计** | 5 | 5 | 节奏不变，颗粒度变细 |

---

## 6. 最低修复集（v2 必须做）

按"v2 必改"优先级排序：

| # | 来源 | 修复 |
|---|---|---|
| 1 | F1 | `tuning_promotion.py` 加 `is_live_execution_tool()` + `execution_allowed_for_tools()`，不动现有 3 API |
| 2 | F1+ | ADR-0011 明确两个 gate 边界（路径 gate / 运行时 gate）|
| 3 | F2 | §6 Modify 表改 "Extend" 而非 "Modify"，加"不修改现有 API 签名"约束 |
| 4 | F3 | D1 重写为：MCP 启动参数 default = `--read-only`；env `OKX_PAPER_MODE` 只用于模块升级时 |
| 5 | F4 | §3.7 表格 OKX 列改 "不直接改 TUNING" + 加 explicit decision |
| 6 | F5 | §6 Create 表删 `package.json`，新建 `scripts/okx/VERSION` 单文件 |
| 7 | F6 | audit log 走 outbox 模式（复用 `state.append_history` 的 outbox 语义）|
| 8 | M1 | Phase 0 加 baseline 测量（3 个 metric）|
| 9 | M2 | 凭据脚本加 `--rotate` flag + 文档化 rotate 流程 |
| 10 | M3 | `scripts/okx/install.sh verify` 子命令设计 |
| 11 | M4 | executor.py 强制 `clOrdId` 含 `salt_version + uuid` |
| 12 | M5 | 启动期版本检查 + ADR-0011 升级模板 |
| 13 | M6 | Keychain 3 accounts（删 paper-mode）；启动期 passphrase 验证 |
| 14 | M7 | OKX per-gen cap=3 + rate limit retry 策略 + metric |
| 15 | M8 | D1 改 "Phase 1 仅 spot paper"；swap 写明确排除 |
| 16 | M9 | audit log schema 定义（10 字段）|
| 17 | M10 | `test_rollback_drill.py` 5 场景测试 |
| 18 | M11 | gate.yaml denylist + always_exclude 增 OKX 项；source mutex 测试 |
| 19 | M12 | ADR-0011 决策表草案（12 条）|
| 20 | P1 | Phase 1 拆 1A + 1B |
| 21 | P2 | 端到端双层（mock + 真实 paper）|
| 22 | P3 | Phase 4 重命名 + 验收指标改 |
| 23 | D1-D5 | 文档细节清理 |

**总修复 23 项** — 4 F + 12 M + 3 P + 5 D（v1 事实层 + 缺失 + 排序 + 文档）。

---

## 7. 风险提示

1. **npm 全局安装 + 项目 Python 异构**：v2 已选 1 文件 VERSION 而非 package.json（按 F5），但 CI 需要明确不引入 Node.js 工具链依赖。
2. **OKX paper mode ≠ live**：Phase 4 验收指标必须区分 paper fill 与真实 fill 的差异（OKX 模拟盘有独立的撮合规则）。
3. **三重门**（D1）是**新增概念**——v2 必须把"启动参数 + env + 运行时 gate"的关系讲清楚，不能让运维误以为任意门被绕过就 OK。
4. **passphrase 错**（M6）必须 fail-fast，**不能** silent fallback 到 read-only（让人误以为配好了）。
5. **audit log crash-safe**（F6）— 写一半比不写更糟（事后以为有 fill 实际没有），outbox 模式必填。

---

## 8. 审计结论

- v1 方向正确（D1 三重门 / D2 npm 全局 / D3 Keychain / D4 补全不替代 / D6 audit log / D7 复用 promotion gate / D8 模块选择不全做）都是对的。
- 23 项 v2 修复中，6 F 类是**与已有 ADR-0010 / `tuning_promotion.py` 现状的事实冲突**，必须在 v2 解决。
- 12 M 类是**缺失要素**（基线 / 轮换 / verify / nonce / 版本锁 / passphrase 验证 / rate limit / instrument 范围 / audit schema / 回滚测试 / 互斥 / ADR 草案），多数是 v1 草率跳过。
- 3 P 类是**排序与节奏**（Phase 1 0.5 周过紧 / 端到端双层 / Phase 4 概念清）。
- 5 D 类是**文档细节**。

**审计通过 v2 进入实施**。如果用户接受 23 项修复集，v2 plan 应在 1-2 天内完成并进入 Phase 0。

---

_Last updated: 2026-08-11 (audit of plan v1)_
