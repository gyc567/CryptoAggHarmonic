"""Loop-tuning package — scaffolding for the loop-engineering project.

Submodules:

* :mod:`app.loop.state`    — durable state (HISTORY.jsonl + PARETO.json +
  STATE.md + per-run workspaces). fcntl-locked writes; replay from HISTORY.
* :mod:`app.loop.worker`   — ProcessPoolExecutor-friendly worker that runs
  ``run_backtest_v3`` for a single candidate and emits a metrics.json.
* :mod:`app.loop.pareto`  — Pareto-front maintenance over the 3-D space
  (sharpe, calmar, max_dd_pct) with worst-regime-sharpe as the robustness
  tiebreaker.
* :mod:`app.loop.driver`   — single-generation CLI runner: load candidates,
  fan them out across the worker pool, write results, update Pareto.
"""
