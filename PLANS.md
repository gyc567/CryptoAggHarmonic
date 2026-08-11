# Plans Index

Work-in-progress plans. See [AGENTS.md](AGENTS.md) → Project plans for lifecycle rules.

## Active Plans

- [Local Backend Deployment](docs/plans/local-backend-deployment.md) — 旧后端（`/var/www/pyharmonics/` + systemd）下架，用本项目最新代码替换；复用旧 venv（Python 3.11，依赖已解决）+ `PYTHONPATH` 覆盖；**已部署**
- [Loop Engineering Integration v3.0](docs/loop-engineering-plan.md) — 引入 loop-engineering 框架，建立开发循环自进化体系（阶段 1-5）；含二次审计新增：`.claude/` gitignore 冲突修复、`apply_tuning()` 竞态条件修复、TUNING promotion gate、drawdown guardrails 等 26 项优化
- [Freqtrade Dev MCP 整合](docs/plans/freqtrade-mcp-integration.md) — 将 freqtrade_dev_mcp (github.com/gyc567/freqtrade_dev_mcp) 接入 cryptoagg loop-engineering，新增 signal → freqtrade strategy 翻译层 + freqtrade_promotion.py gate（L2 辅助模式）
- [Backend Auth 500 Fix (and Deploy)](docs/plans/backend-auth-500-fix.md) — `app/api/auth.py` 漏 import 三个名字（`ErrorCode` / `verify_user_token` / `reserve_user_quota`），带 token 请求 → `NameError` → 500。源码已修 (commit `c6c2d0e`)，测试 1772/0；**后端 redeploy 待人工**（`scripts/deploy-backend-auth-fix.sh` 一键拉取+重启+探测）

## Completed Plans (archived in git)

- [Vercel Frontend Deployment (CLI)](docs/plans/vercel-frontend-deploy.md) — ...

---

_Last updated: 2026-08-11_
