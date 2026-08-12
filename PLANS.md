# Plans Index

Work-in-progress plans. See [AGENTS.md](AGENTS.md) → Project plans for lifecycle rules.

- [FT 策略中心 UI](docs/plans/ft-strategy-ui-integration.md) — **v4** — Phase 0–2 后端 + Phase 3 前端全部完成（参考 [TraderAlice/Auto-Quant-V2](https://github.com/TraderAlice/Auto-Quant-V2) Agent-native 工作台）：7 表 schema（strategies/runs/insights/events/experiments/reports/jobs）+ `.scratch/loop_state/ft_strategy/{id}.tsv`（gitignored, survives reset）+ `orient` + `capabilities` 自描述端点 + 多目标 9 项 promotion gate（`robust_sharpe_min` / `robust_calmar` / `max_dd` / `profit_floor` / min_position / `pareto_dominated_by` / report ref / crash 闭环 / shadow ≥7d） + KEEP/REVERT/CRASH 不可变实验 + clarify-first `research_md` ≥ 200 chars + 7 sections + preflight 6-item + Honest Boundary；**Phase 3 前端**: 4 pages + 5 components + TypeScript types + API client，`next build` ✅ 0 errors；`npx tsc --noEmit` ✅ 0 ft-strategy errors；**Vercel ✅** `https://www.cryptoagg.xyz/ft-strategy`；`loop audit` 100.0/100 [L3]；D-FT-01..25；**待 infra**: RQ live worker real MCP calls / `[ftstrategy-baseline-01]`/ `[ftstrategy-shadow-01]` 频段值
- [FT 策略中心 UI — 二阶审计](docs/plans/ft-strategy-ui-integration-audit-report.md) — v1 → v2 修订清单（29 项）+ v2 修复策略
- [FT 策略中心 UI — 三阶审计（v2）](docs/plans/ft-strategy-ui-integration-audit-report-v2.md) — **⚠️ 5 P0 + 6 P1 + 4 P2 = 15 项**；P0 阻断：FT-STRATEGY-LOOP.md 缺失 / ADR-0012 缺失 / v1 审计未追踪 / §15 缺失 / LOOP.md §13 是占位符；v1 审计 29 项确认已处理 ≤ 10 项；Gate 项数量不一致（§6.5 实际 9 项 vs §11 称 8 项）
- FT 策略中心 UI v1 初稿（576 行，已被 v2/v3 取代，git 历史保留）— `[plan v1 ref 待 archive 完成后挂]`：将 `freqtrade_dev_mcp` 已有 L3 自动循环包装成人类可观测的策略工作台；七阶段（💡→🔧→⚡→📊→🔍→🔄→🚀）+ AI Learning；Phase A-H

## Active Plans

- [Binance CLI 整合](docs/plans/binance-cli-integration.md) — 将 `@binance/binance-cli`（read-only 行情补全层）接入 cryptoagg loop-engineering；Loop #12（L2）；funding rate / OI / mark price 补全；不替代 Binance REST 主路径；Phase 0 基线测量待启动
- [Local Backend Deployment](docs/plans/local-backend-deployment.md) — 旧后端（`/var/www/pyharmonics/` + systemd）下架，用本项目最新代码替换；复用旧 venv（Python 3.11，依赖已解决）+ `PYTHONPATH` 覆盖；**已部署**
- [Loop Engineering Integration v3.0](docs/loop-engineering-plan.md) — 引入 loop-engineering 框架，建立开发循环自进化体系（阶段 1-5）；含二次审计新增：`.claude/` gitignore 冲突修复、`apply_tuning()` 竞态条件修复、TUNING promotion gate、drawdown guardrails 等 26 项优化
- [Freqtrade Dev MCP 整合](docs/plans/freqtrade-mcp-integration.md) — 将 freqtrade_dev_mcp (github.com/gyc567/freqtrade_dev_mcp) 接入 cryptoagg loop-engineering，新增 signal → freqtrade strategy 翻译层 + freqtrade_promotion.py gate（L2 辅助模式）
- [Backend Auth 500 Fix (and Deploy)](docs/plans/backend-auth-500-fix.md) — `app/api/auth.py` 漏 import 三个名字（`ErrorCode` / `verify_user_token` / `reserve_user_quota`），带 token 请求 → `NameError` → 500。源码已修 (commit `c6c2d0e`)，测试 1772/0；**后端 redeploy 待人工**（`scripts/deploy-backend-auth-fix.sh` 一键拉取+重启+探测）
- [FreqTrade 策略代码双向零修改兼容](docs/plans/freqtrade-strategy-bidirectional-compat.md) — **v1** — 把 FreqTrade `IStrategy` 提升为**唯一**策略形态，本项目其余一切（扫描 API、回测、bench、loop-engineering、AI 训练）变成"运行 freqtrade 策略的运行环境"；**supersede** 旧 `freqtrade-mcp-integration.md`（v2，301 行）。物理路径 `app/strategies/` + symlink 桥接；删除 `app/domain/strategy_core.py` 与 `app/domain/rsi_trend.py` 镜像层；新建 `app/services/strategy_runner.py` 反射 freqtrade 引擎；4 阶段 A/B/C/D（symlink → runner 落地 → API 切换 → hyperopt 闭环）；约 6 工作日；D-FT-26..40；**待启动** Phase A（symlink + parity test，0.5d，零风险）

## Completed Plans (archived in git)

- [Vercel Frontend Deployment (CLI)](docs/plans/vercel-frontend-deploy.md) — ...

---

_Last updated: 2026-08-12_
