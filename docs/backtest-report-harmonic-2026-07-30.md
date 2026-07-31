# Harmonic Pattern Analyzer — Walk-Forward Backtest Report

Date: 2026-07-30 (last 90 calendar days of Binance USDⓈ-M futures data)
Branch: `main`
Scope: `app/services/signal_engine.py` + `app/infra/pyharmonics_adapter.py`
       + `app/services/vibe/backtest_engine.simulate_trades`
Runner: `scripts/backtest_harmonic.py` (pure logic in `scripts/backtest_harmonic_lib.py`)
Tests:  `tests/test_backtest_harmonic_lib.py` (26/26 pass, 89.85% lib coverage)

## Headline

| Symbol       | Interval | Window | Step | Horizon | Signals | Decided | W / L | Win rate (decided) | avg R | Total R | Profit factor |
|--------------|----------|--------|------|---------|--------:|--------:|-------|-------------------:|------:|--------:|--------------:|
| **BTCUSDT**  | 4h       | 200    | 12   | 30      | 16      | 5       | 4 / 1 | **80.0%**          | -0.03 | -0.47   | 0.53          |
| **ETHUSDT**  | 4h       | 200    | 12   | 30      | 11      | 3       | 2 / 1 | **66.7%**          | +0.14 | +1.57   | 2.57          |

Sample size is small (5 decided BTC trades, 3 decided ETH trades) so the
percentages are illustrative only — none of the figures below is
statistically significant. The intent of this backtest is to confirm that
the **detection → signal extraction → forward simulation → aggregation**
pipeline runs end-to-end on real Binance data, exposes its assumptions, and
emits well-formed per-signal records that can be audited.

## Configuration

```bash
PYTHONPATH=. .venv/bin/python scripts/backtest_harmonic.py \
  --symbol BTCUSDT --interval 4h --days 90 \
  --window 200 --step 12 --horizon 30 \
  --out-dir docs/_backtest_artifacts
```

| Parameter        | Value     | Why                                                            |
|------------------|-----------|----------------------------------------------------------------|
| `--symbol`       | BTCUSDT / ETHUSDT | Liquidity; closest analog to "average crypto market".   |
| `--interval`     | 4h        | 1d windows are too short for the harmonic detector (`MIN_CANDLES=60`, plus extra context for XABCD peaks). 4h gives ~540 bars over 90 days — enough to find patterns AND keep the walk-forward tractable. |
| `--days`         | 90        | The user's request: "近 3 个月". |
| `--window`       | 200       | 200 × 4h ≈ 33 days of context per step. Empirically the smallest window in which the harmonic detector consistently surfaces XABCD/ABCD/ABC families. |
| `--step`         | 12        | ~2 days between iterations. Decoupled from "1 bar" so the run finishes in seconds instead of hours. |
| `--horizon`      | 30        | 30 × 4h = 5 days forward evaluation per signal. Long enough to clear the engine's median stop distance, short enough that >50 valid steps fit in a 90-day window. |
| `--out-dir`      | `docs/_backtest_artifacts` | JSON + Markdown artifacts land next to this report. |
| `--llm-disabled` | true (hard-coded in the lib) | The expensive LLM interpretation step is intentionally skipped. Detection (`pyharmonics`) + signal extraction (`signal_engine`) are already deterministic and ~0.2 s per call, so the full 90d walk-forward finishes in ~1 s per symbol. |

## Pipeline

```
        Binance daily candles
              ↓
   fetch_historical_data(...)         # 90d window (~540 4h bars)
              ↓
   for end_idx in [window-1, last_start]:
        window = df[end_idx-window+1 : end_idx+1]
              ↓
   scripts/backtest_harmonic_lib.detect_window(window)
       - OHLCTechnicals(window, symbol, interval)
       - HarmonicSearch.search(limit_to=5)
       - HarmonicSearch.forming(limit_to=5, percent_c_to_d=0.8)   # on 4h, daily, weekly
       - DivergenceSearch.search(limit_to=5)
       - emit raw_assessment { patterns:{XABCD,ABCD,ABC}, forming:{...} }
              ↓
   scripts.backtest_harmonic_lib.extract_signal(window)
       - extract_candidates(detection, close_times=...)
       - _maybe_relax_filters(True)  ← widens live-trading guards
       - build_signal(window, "4h", candidates)
       - restore filters
              ↓
   forward_df = df[end_idx+1 : end_idx+1+horizon+1]
   current_price = window_df["close"].iloc[-1]
   scripts.backtest_harmonic_lib.simulate_one(forward, signal, current_price=current_price)
       - simulate_trades(forward_df, long|short, current_price, signal.stop_loss, tp1)
       - return { result, r_multiple, exit_time, bars_held }
              ↓
   append BacktestSignalRecord(...)
              ↓
   aggregate_records(records)
       - win / loss / scratch counts
       - total R, avg R, profit factor (win_r / |loss_r|)
       - by_grade, by_family sub-buckets
              ↓
   write_json(report, out.json) + write(markdown_summary(report), out.md)
```

### Filter relaxation

The signal engine's live-trading `rejection_reason()` filter is tightened
for live flows. We deliberately **disable** three of its branches for the
backtest and document the reason:

| Branch              | Live behaviour                | Backtest behaviour                                |
|---------------------|-------------------------------|---------------------------------------------------|
| `stale_distance`    | Reject if PRZ is `> 3 ATR` from current price. | **Relaxed** (1e9 ATR): the pattern is treated as a valid signal; the price "might come to it" — we want to evaluate that historical possibility. |
| `stale_age`         | Reject if pattern D-bar is older than `MAX_D_AGE_BARS`. | **Relaxed**: same reason. The pattern is older than live would allow, but backtests answer "if I had noticed and acted, would I have won?". |
| `violated`          | Reject if current price has already crossed the stop. | **Relaxed**: same. |
| `completed`         | Reject if price has already passed TP2 (the trade ran without us). | Kept. The trade's entry zone is behind us, so forward simulation has nowhere to start. |
| `degenerate_prz`    | Reject if PRZ is wider than `MAX_FORMING_PRZ_WIDTH_ATR`. | Kept. A zero-width PRZ is structurally untradeable. |

The relaxation is implemented in `_maybe_relax_filters` / `_restore_filters`
and is bounded inside `extract_signal`; live code paths are untouched.

### Entry-price semantics

`signal.entry_reference` is the PRZ mid — the price the harmonic engine
asked us to **wait for**. But a walk-forward backtest answers a different
question: "given this pattern was detected at time *t*, what would have
happened if I entered the market at the current price?".

So in the CLI/lib:
- `current_price = window_df["close"].iloc[-1]` is the **actual** entry used
  for the forward simulation.
- `signal.entry_reference` and `signal.entry_zone` are still recorded on each
  record so the reader can see what the engine asked for vs. what was used.

## Per-symbol results

### BTCUSDT 4h, 90 days
*raw artifact:* [`docs/_backtest_artifacts/BTCUSDT_4h_90d.json`](_backtest_artifacts/BTCUSDT_4h_90d.json)
*markdown:* [`docs/_backtest_artifacts/BTCUSDT_4h_90d.md`](_backtest_artifacts/BTCUSDT_4h_90d.md)

```
total signals: 16  (decided 5, skipped 11)
wins / losses / scratches: 4 / 1 / 0
win rate (of decided): 80.0%
avg R multiple: -0.03
total R: -0.47
profit factor: 0.53

by grade (all C(参考)):
  - C(参考): count=16 wins=4 losses=1 R=-0.47

by family:
  - ABC:  14 signals, 3 W / 1 L, R=-0.72   (75% WR, slightly losing)
  - ABCD:  2 signals, 1 W / 0 L, R=+0.25   (100% WR, small sample)
```

The 11 skipped BTC signals are predominantly the May–early-June batch
(long `1.272` PRZ-side patterns whose entry zone was already swept by the
mid-July crash and target below current price — a direction-invariant
mismatch). `simulate_one` flags these as `result="skipped"`,
`r_multiple=0`, rather than raising.

The four wins carry tiny R multiples (0.01, 0.13, 0.13, 0.25). The single
loss is -1.00 R (full stop). Total R is **-0.47** over the period: the
strategy is **breakeven-to-slightly-negative** at this sample size, with
no statistical confidence in either direction.

### ETHUSDT 4h, 90 days
*raw artifact:* [`docs/_backtest_artifacts/ETHUSDT_4h_90d.json`](_backtest_artifacts/ETHUSDT_4h_90d.json)
*markdown:* [`docs/_backtest_artifacts/ETHUSDT_4h_90d.md`](_backtest_artifacts/ETHUSDT_4h_90d.md)

```
total signals: 11 (decided 3, skipped 8)
wins / losses / scratches: 2 / 1 / 0
win rate (of decided): 66.7%
avg R multiple: +0.14
total R: +1.57
profit factor: 2.57

by grade:
  - B:       3 signals, 1 W / 1 L, R=-0.49
  - C(参考): 8 signals, 1 W / 0 L, R=+2.06

by family (all ABC):
  - ABC: 11 signals, 2 W / 1 L, R=+1.57
```

The standout is the **21 July 2026 short on `1.618` PRZ**, which entered
near the post-rally top and rode the BTC-driven drawdown into TP1 for a
**+2.06 R** payout. Without that single trade the strategy has effectively
zero edge over the period. It is included in the report to make the
fragility obvious: 3 trades is not a backtest, it is anecdotal.

## Known limitations

1. **No transaction costs.** The engine is honest about this: each
   `Trade` has zero slippage, zero fees, and assumes the simulator resolves
   the closer of (stop, target) first when both fire on the same bar.
2. **No partial fills.** The signal engine returns TP1/TP2/TP3 ladders,
   but this report only evaluates the **first target** (TP1). Adding
   ladder logic is straightforward (extend `simulate_one` with a TP list)
   but is intentionally out of scope for this checkpoint.
3. **Skipped signal ratio is high.** 11/16 BTC and 8/11 ETH signals are
   skipped because the entry-side validation fails (`stop < entry < target`
   invariant violated when the PRZ is far behind current price). Most of
   these are bullish patterns whose entire target ladder sits below the
   current market price — i.e., the trade was already over by the time we
   detected it. The "completed" filter rightly catches this; the result is
   that the *generator* is selective rather than that the *tradeable
   edges* are missing.
4. **Filter relaxation is a research concession.** The live engine would
   have rejected every single one of these signals. We deliberately turn
   off three guards so the backtest can evaluate "what would have
   happened if I had been more aggressive". Numbers will look better
   here than in production. Treat this as a calibration knob, not an
   end-state.
5. **1d interval over 90 days produces too few decisions** to be useful
   (BTC 4h 90d → 16 signals / 5 decided; BTC 1d 90d → 3 signals / 0
   decided). The reason: harmonic XABCD patterns need ~200+ bars to
   resolve, and 1d-90d is only ~90 candles. The artifacts include the
   1d runs as evidence of this; they should not be cited.
6. **Step > 1 day** means some windows never see certain patterns.
   `step=12 @ 4h` (2 days) is a deliberate trade-off: smaller step yields
   a denser sample but a longer runtime. The chosen value keeps
   end-to-end runtime under 10 s per symbol.
7. **Sample size below statistical threshold.** Five decisions on BTC and
   three on ETH are anecdotes. To claim any edge we would need ≥30
   decided trades per symbol — roughly **18-24 months** of 4h data at
   the current density, or shorter intervals (1h, 15m) with a detector
   tuned for those windows.

## Reproduction

```bash
PYTHONPATH=. .venv/bin/python scripts/backtest_harmonic.py \
  --symbol BTCUSDT --interval 4h --days 90 \
  --window 200 --step 12 --horizon 30 \
  --out-dir docs/_backtest_artifacts

PYTHONPATH=. .venv/bin/python scripts/backtest_harmonic.py \
  --symbol ETHUSDT --interval 4h --days 90 \
  --window 200 --step 12 --horizon 30 \
  --out-dir docs/_backtest_artifacts
```

Both runs together finish in under 3 s on the development machine and
emit ~12 KB of JSON + Markdown per symbol. The JSON includes the full
per-signal `BacktestSignalRecord` list (timestamp, direction, grade,
pattern name, family, formed, entry/stop/tp1 used, rr1, result,
r_multiple, exit_time, bars_held, horizon) for ad-hoc analysis.

## Verdict

* The detector + signal engine forward-simulation pipeline runs
  end-to-end on real Binance 4h data and emits a coherent per-signal
  record.
* At this 90-day horizon and at these parameters the **signal density
  is too low** to make any claim of edge. Both symbols are breakeven
  within rounding error.
* Recommend the next iteration extend the dataset to **12+ months** at
  4h or 1h and consider partial-fill + TP-ladder logic in
  `simulate_one` to make the metric less vulnerable to single-trade
  outliers.

## Artifacts

| Path                                                            | Bytes | Notes                                                   |
|-----------------------------------------------------------------|------:|---------------------------------------------------------|
| `docs/_backtest_artifacts/BTCUSDT_4h_90d.json`                  | ~6 KB | Full per-signal records + config + summary.            |
| `docs/_backtest_artifacts/BTCUSDT_4h_90d.md`                    | ~2 KB | Human-readable digest (this report's source of truth for tables). |
| `docs/_backtest_artifacts/ETHUSDT_4h_90d.json`                  | ~5 KB | Same shape.                                            |
| `docs/_backtest_artifacts/ETHUSDT_4h_90d.md`                    | ~2 KB | Same shape.                                            |
| `docs/_backtest_artifacts/BTCUSDT_4h_120d.json`                 | ~7 KB | Sensitivity sweep, 120-day horizon.                    |
| `docs/_backtest_artifacts/BTCUSDT_4h_120d.md`                   |  —    | "                                                       |
| `docs/_backtest_artifacts/ETHUSDT_4h_120d.json`                 | ~6 KB | Same.                                                  |
| `docs/_backtest_artifacts/SOLUSDT_4h_120d.json`                 | ~6 KB | SOL added for cross-asset confirmation.                 |
| `docs/_backtest_artifacts/BTCUSDT_4h_30d.json`                  | ~3 KB | Sensitivity sweep, 30-day horizon (too small).         |
| `docs/_backtest_artifacts/BTCUSDT_1d_90d.json`                  | ~3 KB | 1d sensitivity: detector finds only 3 patterns.         |
| `docs/_backtest_artifacts/BTCUSDT_1d_180d.json`                 | ~4 KB | 1d over 180d: still sparse vs. 4h over 90d.             |
| `docs/_backtest_artifacts/ETHUSDT_1d_180d.json`                 | ~3 KB | Same.                                                  |
| `scripts/backtest_harmonic.py`                                  | ~3 KB | CLI thin wrapper.                                       |
| `scripts/backtest_harmonic_lib.py`                              | ~22 KB | Reusable library: detection + extraction + simulation + aggregation + report rendering. |
| `tests/test_backtest_harmonic_lib.py`                           | ~14 KB | 26 tests, 89.85% coverage on the lib.                   |
