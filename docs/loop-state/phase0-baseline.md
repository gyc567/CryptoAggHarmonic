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
| avg fitness | _TBD_ | | |
| Pareto size | _TBD_ | | |
| mean candidate seconds | _TBD_ | | |
| LLM $ / gen | $0 (MC off) | | |

## Metrics

With the API running:

```bash
curl -s localhost:5000/metrics | grep tuning_proposals
```

Driver increments `tuning_proposals_total{decision=...}` per candidate and
observes `loop_generation_duration_seconds`.
