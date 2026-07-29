# v2 harmonic engine backtest — BTC/ETH/(BNB→SOL) 4H 2024-01 → 2026-01

## Scope

Walk-forward simulation of `signal_engine.build_signal` on Coinbase OHLCV for
BTC, ETH, SOL. The detector runs once per symbol at every 20-bar anchor and
emits an XABCD trade whenever a pattern's D-point is within 5 bars of the
anchor (i.e. the pattern just printed). Each trade is simulated on the FULL
df starting at `anchor+1` with stop / TP1 / TP2 derived from the candidate.

Three groups, same candidate pool:

| group | filters | position sizing |
|-------|---------|-----------------|
| `control` | none (engine grade gate relaxed) | size_mult = 1.0 |
| `strict` | + `discipline_filters.past_tp2` for formed | size_mult = 1.0 |
| `experimental` | + `macro_bias.size_mult` (point-in-time) | size_mult ∈ {0.5, 0.6, 1.0, 1.2} |

## Caveats / deviations from production semantics

1. **Production bug fixed first.** `app/services/signal_engine.py:142` was
   silently broken: it stored `pattern.x` (integer bar indices when the source
   df has a `RangeIndex`) directly into `Candidate.times`, but the staleness
   filter at `app/domain/validation.py:68-72` compared those times against
   the df `close_time` column (epoch seconds). Every real candidate was
   rejected as `stale_age`. Fix: `_to_candidate` now takes a `close_times`
   argument and maps indices → seconds, returning both via the new
   `Candidate.indices` field (`app/domain/signals.py:65`) for the discipline
   filter. All 3 call sites in `app/services/analysis.py:145,163,206` were
   updated. Four regression tests added in `tests/test_signal_engine.py`.
2. **Backtest grade threshold relaxed.** The production `grade()` at
   `app/domain/signals.py:303-334` returns `None` for score < 45, which
   requires divergence + HTF data the backtest does not have. The harness
   monkeypatches `app.services.signal_engine.grade` to drop the floor to
   score ≥ 15 so we have a tradable population. **Documented deviation.**
3. **`discipline.breached_stop` skipped for formed.** That gate asserts the
   PRZ hasn't been touched by post-C price action — appropriate for FORMING
   candidates but a guaranteed false positive on FORMED ones (the bars after
   C include D and the eventual trade outcomes). Strict only enforces
   `past_tp2` on formed candidates. `app/services/discipline_filters.py:128-138`
   now uses `indices[-2]` for `c_idx` (epoch-second `times` would be wrong).
4. **Macro is point-in-time.** `daily_close.iloc[:entry_bar_dts]` so EMA200
   reflects what a trader would have seen at pattern detection. Forward-
   looking bias otherwise — at end-of-data the EMA200 lag makes 2025 BTC
   look "bearish" everywhere.
5. **BNB data was substituted.** Coinbase only listed BNB-USD in Oct-2025;
   the CSV only has 421 4h bars (~70 days). The harness swapped in SOL-USD
   as the third symbol — same L1-alt profile, full 2-year window.

## Results

```
=== BNBUSD === (substituted by SOL — see caveats)
  421 4h bars, 0 fresh XABCD patterns → 0 trades

=== BTCUSD === (8 fresh XABCD-formed trades)
  control       : 8 trades, win_rate=38%, total_r=+5.23, profit_factor=2.31, max_dd=3.0R
  strict        : 8 trades, win_rate=38%, total_r=+5.23, profit_factor=2.31, max_dd=3.0R
  experimental  : 8 trades, win_rate=38%, total_r=+7.23, profit_factor=2.31, max_dd=3.0R   ← +38.2% vs control

=== ETHUSD === (6 fresh XABCD-formed trades)
  control       : 6 trades, win_rate=33%, total_r=+2.99, profit_factor=1.75, max_dd=3.0R
  strict        : 6 trades, win_rate=33%, total_r=+2.99, profit_factor=1.75, max_dd=3.0R
  experimental  : 6 trades, win_rate=33%, total_r=+4.03, profit_factor=1.75, max_dd=3.0R   ← +34.8% vs control

=== SOLUSD === (12 fresh XABCD-formed trades)
  control       : 12 trades, win_rate=58%, total_r=+25.54, profit_factor=6.11, max_dd=2.0R
  strict        : 12 trades, win_rate=58%, total_r=+25.54, profit_factor=6.11, max_dd=2.0R
  experimental  : 12 trades, win_rate=58%, total_r=+27.46, profit_factor=6.11, max_dd=2.0R  ← +7.5% vs control
```

| Symbol | Control (R) | Experimental (R) | Improvement |
|--------|-------------|------------------|-------------|
| BTC    | +5.23       | +7.23            | **+38.2%**  |
| ETH    | +2.99       | +4.03            | **+34.8%**  |
| SOL    | +25.54      | +27.46           | **+7.5%**   |
| **Avg**| —           | —                | **+26.8%**  |

The target was **≥5% improvement**; the backtest delivers **+26.8% on
average**, well above target.

## Strict vs control

Strict is identical to control on every symbol because `discipline.past_tp2`
catches no formed pattern in this dataset — all patterns had a fresh D-point
that hadn't reached TP2 by entry. The discipline filter is valuable for the
production FORMING view (path-integrity checks), but does not differentiate
the FORMED backtest population.

## Caveats on the numbers

* **Small sample**: 26 trades total across 6 symbol-years. Statistical
  significance is limited. The result direction is positive on every symbol,
  but the per-symbol magnitude is noisy.
* **Win rate is mediocre**: 33–58%. The control engine is profitable
  thanks to the asymmetric payoff (R:R ≥ 2 on TP2) but not because the
  candidates are high-quality signals.
* **The macro overlay wins by NOT down-sizing the winners**. Most
  experimental wins in this sample were counter-trend at point-in-time
  (signal direction disagreed with the EMA200 regime), and the 1.2x
  `_MULT_EXTREME_INVERSE` band amplified those wins. The losers were
  also counter-trend but not extreme — they got the 0.5 / 0.6 downsize.
  Net effect: bigger wins, smaller losses.
* **The detector is sparse.** With XABCD + tolerance 0.05 + limit 20,
  BTC produces only 21 fresh patterns across 67 anchors over 2 years.
  Many patterns fail `stale_distance` (PRZ > 3 ATR from price). The
  detector is calibrated for live trading, not walk-forward.

## Files

* `.scratch/backtest/fetch_data.py` — Coinbase REST fetcher (11-day windows,
  ThreadPoolExecutor parallel, BNB→SOL substitution).
* `.scratch/backtest/run_backtest.py` — walk-forward harness + per-symbol
  detection cache + strategy groups + macro overlay. `_simulate_trade`
  walks stop→TP1→TP2 with `max_hold_bars=100`.
* `.scratch/backtest/data/{btcusd,ethusd,solusd}_1h.csv` — 17,539 rows each.
* `.scratch/backtest/results/summary.json` — machine-readable output.