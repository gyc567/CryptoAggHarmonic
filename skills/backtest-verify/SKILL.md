# SKILL.md — backtest-verify

## Trigger Condition

Invoked when:
- A tuning candidate is accepted by the Maker-Checker and promoted to the Pareto front
- A new tuning configuration is being evaluated for promotion
- The human requests a backtest quality review

## Input

Reads:
- `PLANS.md` — Backtest Evaluation Guide
- The candidate's `tuning.yaml` (from `.scratch/loop_state/runs/{uuid}/`)
- The candidate's `metrics.json` / `summary.json`
- Historical Pareto front (PARETO.json)

## Output

Returns a verification report:
- `passed: bool`
- `metrics: dict` — key backtest numbers
- `concerns: list[str]` — issues that don't fail but warrant attention
- `recommendation: str` — promote / hold / reject

## Verification Rules

1. **Sharpe ratio**: Must be > baseline or > 0.5 (whichever is higher)
2. **Calmar ratio**: Must be positive
3. **Trade count**: Must be >= 30 (minimum sample size)
4. **Max drawdown**: Must be < 2x the baseline drawdown
5. **Consistency**: Performance should be similar across symbol sets

## Backtest Evaluation Guide (from PLANS.md)

> When evaluating backtest results, use these metrics in priority order:
> 1. Sharpe ratio (risk-adjusted return)
> 2. Maximum drawdown (tail risk)
> 3. Calmar ratio (return / max drawdown)
> 4. Win rate (should be > 55% for harmonic patterns)
> 5. Profit factor (should be > 1.2)
