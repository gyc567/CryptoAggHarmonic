# Loop Budget — pyharmonics-gpt

> Token and compute budget for development loops.

## Default Budget

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `weekly_budget_usd` | 25.0 | USD | Max LLM + compute per week |
| `dollars_per_cpu_second` | 0.0001 | USD | CPU compute cost rate |
| `per_generation_max_usd` | 2.00 | USD | Max cost per single generation |

## Enforcement

- Budget check runs before each generation starts
- When `weekly_budget_usd` is exceeded: `LoopPausedException` is raised
- To opt out: set `DISABLE_LOOP_BUDGET=1` (for local development only)

## Cost Estimation

### LLM Costs

| Call Type | Estimated Cost | Notes |
|-----------|--------------|-------|
| Maker call | $0.01-0.05 | Per candidate |
| Checker call | $0.01-0.05 | Per candidate |
| Triage/other | $0.005 | Minor loops |

### CPU Costs

Estimated at `dollars_per_cpu_second` × wall-clock seconds × workers.

## Budget Alerts

| Threshold | Action |
|-----------|--------|
| 80% of weekly budget used | Log WARNING |
| 100% of weekly budget used | Pause loop, raise alert |
| Budget exceeded by 50% | Page human (if configured) |
