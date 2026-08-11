# Outerloop Protocol — pyharmonics-gpt

> Defines the handshake between the **trading signal loop** (`app/loop/`)
> and the **development loop** (this directory).

## Two Loops, One System

```
┌─────────────────────────────────────────────────────────────┐
│                   TRADING SIGNAL LOOP                        │
│  (app/loop/ — CMA-ES, Pareto, Maker-Checker, Backtests)   │
│                                                              │
│  OUTPUTS:                                                   │
│  - Pareto front moves (non-dominated candidates)            │
│  - suspicious_to_human verdicts                             │
│  - New cluster discovered                                    │
│  - Fitness record broken                                     │
└─────────────────────────────────────────────────────────────┘
          │                                    │
          │  trigger conditions                │  status reports
          ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                    OUTERLOOP PROTOCOL                        │
│                                                              │
│  pending_issues/  ← suspicious_to_human verdicts            │
│  outerloop.log    ← milestone events (fitness records)      │
└─────────────────────────────────────────────────────────────┘
          │                                    ▲
          │  issue creation                   │  triage
          ▼                                    │
┌─────────────────────────────────────────────────────────────┐
│                   DEVELOPMENT LOOP                           │
│  (GitHub Actions — triage, CI, changelog, cleanup)        │
└─────────────────────────────────────────────────────────────┘
```

## Trigger Conditions

### Pareto Stagnation

When Pareto front has not moved for N generations:
1. Write to `docs/loop-state/STATE.md` Watch List
2. Optional: `gh issue create --label "ready-for-human"`

### New Cluster Discovered

When a new market regime cluster is found:
1. Trigger `changelog-drafter`
2. Create issue with `enhancement` label

### Fitness Record Broken

When fitness exceeds historical best:
1. Log milestone to `docs/loop-state/loop-run-log.md`
2. Trigger `changelog-drafter`

### suspicious_to_human Verdict

When Maker-Checker verdict is `suspicious_to_human`:
1. Write JSON to `.scratch/loop_state/pending_issues/<uuid>.json`
2. `issue-sync.yml` (GitHub Actions) syncs to GitHub Issues

## Freqtrade Handshake（ADR-0010 D4）

```
cryptoagg Signal Loop                    Freqtrade Strategy Loop
(app/loop/)                             (app/services/freqtrade/)
┌──────────────────┐   tuning snapshot   ┌──────────────────────────┐
│ Pareto frontier  │ ──────────────────► │ translator.py             │
│ fitness 突破     │                    │   → IStrategy file       │
└──────────────────┘                    └────────────┬─────────────┘
                                                     │ backtest
                                                     ▼
                                          ┌──────────────────────────┐
                                          │ MCP tools (backtest,     │
                                          │ hyperopt, extract)       │
                                          └────────────┬─────────────┘
                                                     │ results
                                                     ▼
                                          ┌──────────────────────────┐
                                          │ handshake.py             │
                                          │ write_hyperopt_to_      │
                                          │ history() → HISTORY.jsonl│
                                          │ source: freqtrade_       │
                                          │ hyperopt                │
                                          └────────────┬─────────────┘
                                                     │ suspicious?
                                                     ▼
                                          ┌──────────────────────────┐
                                          │ pending_issues/<uuid>.json│
                                          │ → issue-sync.yml → gh    │
                                          └──────────────────────────┘
```

### File Formats

**tuning snapshot** (`tuning_snapshots/pareto-{sha}.yaml`):
```yaml
pattern_type: Gartley
entry_price: 50000
exit_price: 51000
stop_loss: 49500
zrpc_price: 50200
confidence: 0.82
regime: bullish
timeframe: 1h
```

**hyperopt result → HISTORY.jsonl** (ADR-0010 D4):
```json
{
  "candidate_id": "freqtrade-{uuid12}",
  "gen": -1,
  "cluster": "freqtrade_hyperopt",
  "decision": "hyperopt_accepted",
  "fitness": {
    "win_rate": 0.62,
    "sharpe_ratio": 1.34,
    "calmar_ratio": 2.1,
    "max_drawdown": 0.08,
    "trade_count": 847
  },
  "params": { ... },
  "timestamp": "2026-08-11T...",
  "source": "freqtrade_hyperopt",
  "salt_version": 1,
  "strategy_name": "HarmonicGartley1h",
  "hyperopt_epochs": 500
}
```

### Promotion Path（ADR-0010 D1 + D4）

```
hyperopt result in HISTORY.jsonl
  → suspicious_to_human verdict (if drawdown/Calmar gates fail)
  → pending_issues/<uuid>.json → gh issue
  → human review
  → PR editing app/config/tuning.py
  → gunicorn SIGHUP
```

**Forbidden**: hyperopt → apply_tuning() → gunicorn workers（violates ADR-0003 D9）

## Implementation

The outerloop does NOT directly call `gh` or access GitHub API.
It writes state files that GitHub Actions read and act upon.
This decouples the loop machine from network/auth dependencies.
