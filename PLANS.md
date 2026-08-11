# Plans Index

Work-in-progress plans. See [AGENTS.md](AGENTS.md) → Project plans for lifecycle rules.

- [OKX Agent Trade Kit 整合](docs/plans/okx-agent-trade-kit-integration.md) — 把 dex-original/okx-agent-trade-kit (101★ MIT, TypeScript, 145 tools) 作为 cryptoagg 第二下游层（实盘执行 + 行情补全），v2 经 466 行审计报告修订（6 F + 12 M + 3 P + 5 D = 23 项修复）；12 ADR 决策；Phase 1 0.5 周拆 1A/1B；包管理 npm 全局 + 单文件 VERSION；三重门（启动参数 + env + 运行时）+ 第四门 human checklist；audit log 走 outbox 模式；90 天滚动；首笔实盘 ≤ $10 USDT

## Active Plans

- [Binance CLI 整合](docs/plans/binance-cli-integration.md) — 将 `@binance/binance-cli`（read-only 行情补全层）接入 cryptoagg loop-engineering；Loop #12（L2）；funding rate / OI / mark price 补全；不替代 Binance REST 主路径；Phase 0 基线测量待启动
- [Local Backend Deployment](docs/plans/local-backend-deployment.md) — 旧后端（`/var/www/pyharmonics/` + systemd）下架，用本项目最新代码替换；复用旧 venv（Python 3.11，依赖已解决）+ `PYTHONPATH` 覆盖；**已部署**
- [Loop Engineering Integration v3.0](docs/loop-engineering-plan.md) — 引入 loop-engineering 框架，建立开发循环自进化体系（阶段 1-5）；含二次审计新增：`.claude/` gitignore 冲突修复、`apply_tuning()` 竞态条件修复、TUNING promotion gate、drawdown guardrails 等 26 项优化
- [Freqtrade Dev MCP 整合](docs/plans/freqtrade-mcp-integration.md) — 将 freqtrade_dev_mcp (github.com/gyc567/freqtrade_dev_mcp) 接入 cryptoagg loop-engineering，新增 signal → freqtrade strategy 翻译层 + freqtrade_promotion.py gate（L2 辅助模式）
- [Backend Auth 500 Fix (and Deploy)](docs/plans/backend-auth-500-fix.md) — `app/api/auth.py` 漏 import 三个名字（`ErrorCode` / `verify_user_token` / `reserve_user_quota`），带 token 请求 → `NameError` → 500。源码已修 (commit `c6c2d0e`)，测试 1772/0；**后端 redeploy 待人工**（`scripts/deploy-backend-auth-fix.sh` 一键拉取+重启+探测）

## Completed Plans (archived in git)

- [Vercel Frontend Deployment (CLI)](docs/plans/vercel-frontend-deploy.md) — ...

---

_Last updated: 2026-08-11_
