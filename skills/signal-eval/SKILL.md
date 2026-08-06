# SKILL.md — signal-eval

## Trigger Condition

Invoked when:
- A new harmonic pattern is detected that wasn't in the historical training set
- A Pareto improvement was driven by a new pattern type
- The human requests evaluation of a specific pattern

## Input

Reads:
- The detected `Candidate` object (from `app/domain/signals.py`)
- Historical win rates per pattern family (from PARETO.json metadata)
- `app/domain/signals.py` pattern definitions

## Output

Returns a signal evaluation report:
- `pattern_family: str`
- `novelty: bool` — is this a new pattern type for this system?
- `estimated_win_rate: float`
- `historical_precedent: dict`
- `recommendation: str` — use / monitor / avoid

## Pattern Reliability (from Backtest Data)

| Pattern | Base Win Rate | Notes |
|---------|--------------|-------|
| Gartley | ~60% | Most reliable |
| Butterfly | ~55% | Good risk/reward |
| Bat | ~52% | Conservative entry |
| Crab | ~48% | High reward, lower win rate |
| DeepCrab | ~45% | Reserved for high conviction |

## Rules

1. **Novelty check**: If `novelty=True`, recommend "monitor" until 30+ trades
2. **Regime awareness**: Pattern performance varies by market regime (high_quant vs normal)
3. **Composite signals**: A confluence of 2+ patterns increases win probability by ~10%
