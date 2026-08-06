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

## Implementation

The outerloop does NOT directly call `gh` or access GitHub API.
It writes state files that GitHub Actions read and act upon.
This decouples the loop machine from network/auth dependencies.
