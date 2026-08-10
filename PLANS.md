# Plans Index

Work-in-progress plans. See [AGENTS.md](AGENTS.md) → Project plans for lifecycle rules.

## Active Plans

- [Loop Engineering Integration v3.0](docs/loop-engineering-plan.md) — 引入 loop-engineering 框架，建立开发循环自进化体系（阶段 1-5）；含二次审计新增：`.claude/` gitignore 冲突修复、`apply_tuning()` 竞态条件修复、TUNING promotion gate、drawdown guardrails 等 26 项优化
- [自动进化回测与优化方案](docs/plans/2026-08-10-backtest-evolution-plan.md) — 将 cryptoagg 从"形态检测工具"升级为能产出稳定正向收益的交易策略信号系统；含 Confluence Filter + Confidence Score + 标准 SL/TP 规则 + Walk-forward 回测 + Freqtrade 整合（Phase 1-4）
- [Backend Auth 500 Fix (and Deploy)](docs/plans/backend-auth-500-fix.md) — `app/api/auth.py` 漏 import 三个名字（`ErrorCode` / `verify_user_token` / `reserve_user_quota`），带 token 请求 → `NameError` → 500。源码已修 (commit `c6c2d0e`)，测试 1772/0；**后端 redeploy 待人工**（`scripts/deploy-backend-auth-fix.sh` 一键拉取+重启+探测）

## Completed Plans (archived in git)

- [Vercel Frontend Deployment (CLI)](docs/plans/vercel-frontend-deploy.md) — ...

---

_Last updated: 2026-08-09_
