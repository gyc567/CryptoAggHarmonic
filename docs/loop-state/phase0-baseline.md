# Phase 0 Baseline

> Measure before you improve. Without a frozen baseline, Pareto moves are noise.

## Status

| Item | Status |
|------|--------|
| Candidates generator | ✅ `python -m app.loop.baseline` |
| Driver metrics (`tuning_proposals_total`) | ✅ recorded in driver |
| Pipeline smoke (synthetic) | ✅ `LOOP_WORKER_DRY_RUN=1` |
| Market-data full gen (20+ real backtests) | ⏳ needs data + wall time |
| `/metrics` endpoint | ✅ `app/api/metrics_routes.py` (mounted in factory) |

## Pipeline smoke (CI / local, seconds)

Does **not** produce a real fitness baseline — only validates
driver → HISTORY / PARETO / STATE / metrics wiring.

```bash
LOOP_WORKER_DRY_RUN=1 python -m app.loop.baseline --n 20 --run --dry-run \
  --state-root .scratch/loop_state/phase0
```

Acceptance for smoke:

- [x] ≥ N HISTORY.jsonl records
- [x] PARETO.json non-empty when accepts exist
- [x] STATE.md written
- [x] `summary.json` dry_run flag under runs/

## Real baseline (hours, when data is ready)

Prerequisites:

1. Kline cache under `data/backtest/` (see `docs/` download scripts)
2. Harness `.scratch/backtest/run_backtest_v3.py` runnable
3. Unset `LOOP_WORKER_DRY_RUN`

```bash
# 1) Emit candidates (parent + mutations)
python -m app.loop.baseline --n 20 --out candidates-baseline.json

# 2) Run without dry-run (MC off — default)
python -m app.loop.driver \
  --candidates candidates-baseline.json \
  --state-root .scratch/loop_state/phase0_live \
  --workers 4 \
  --timeout 900

# 3) Inspect
python -c "from app.loop.baseline import summarize_state_root; \
  import json; print(json.dumps(summarize_state_root('.scratch/loop_state/phase0_live'), indent=2))"
```

Record results here when a live run completes:

| Metric | Baseline value | Date | Notes |
|--------|----------------|------|-------|
| history_records | 20 | 2026-08-08 | phase0_live run, C1 Geometry, BTC/ETH/SOL |
| accepted | 20 | 2026-08-08 | trade-count floor ≥ 30 |
| avg fitness | +4.267 | 2026-08-08 | mean across accepted |
| Pareto size | 2 | 2026-08-08 | both points are duplicates (same metrics) |
| max fitness | +6.377 | 2026-08-08 | params_sha `16c414e73197`, sharpe +0.24, calmar +10.23, PF 2.56, 161 trades |
| LLM $ / gen | $0.00 | 2026-08-08 | MAKER_CHECKER_ENABLED=true (default) but mock backend |

## v3 follow-ups (closed in this run)

- `scripts/backtest_harmonic_lib._maybe_relax_filters` no longer mutates
  `signal_engine.MIN_CANDLES` via setattr. Uses
  `app.config.tuning.TuningScope` (ADR-0003 D9). Live alias untouched.
- `signal_engine.build_signal` reads `min_candles` via the new
  `app.config.tuning.get_min_candles()` accessor; `TuningScope` /
  `apply_tuning()` overrides now propagate into the hot path.
- `loop/loop_context.load_episodic()` no longer raises
  `UnboundLocalError` — JSONL lines are parsed and only the last
  ``limit`` are returned.
- `/metrics` endpoint now publishes every metric promised in plan §7.2:
  `tuning_proposals_total`, `loop_generation_duration_seconds`,
  `llm_maker_calls_total`, `llm_checker_calls_total`, `llm_tokens_total`,
  `llm_latency_seconds`, `llm_cost_usd_total`, `llm_cache_hit_total`,
  `pareto_front_size`, `mc_agreement_rate`, `suspicious_to_human_rate`,
  `worker_timeout_total`, `runs_disk_bytes`, `loop_readiness_score`.
  Producers are wired into `app/loop/driver.py`,
  `app/loop/worker.py`, and `app/loop/maker_checker/runner.py`.
  Metrics live in a private `CollectorRegistry` to avoid
  `DuplicateTimeseries` on Flask reload.

## Metrics

With the API running:

```bash
curl -s localhost:5000/metrics | grep tuning_proposals
```

Driver increments `tuning_proposals_total{decision=...}` per candidate and
