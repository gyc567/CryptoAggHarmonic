# Loop State — pyharmonics-gpt

> 由 `daily-triage.yml` 等 workflow 自动更新。
> 人类每周审查一次。

## High Priority

<!-- 由循环自动填充 -->

- [x] 2026-08-08: GitHub Issues **enabled** on `gyc567/pyharmonics-gpt` (smoke #1 closed)
- [x] 2026-08-08: Triage + loop labels created (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `maker-checker`, `release-prep`, `code-health`, `dependencies`, `automated`, `loop`)
- [x] 2026-08-08: #3 apply_tuning Path A (get_tuning live reads)
- [x] 2026-08-09: **Loop engineering v3 follow-ups** — wired 14-metric /metrics
  (private CollectorRegistry), closed `MIN_CANDLES` setattr bug via
  `TuningScope` in `scripts/backtest_harmonic_lib`, fixed
  `loop.loop_context.load_episodic` UnboundLocal, added
  `get_min_candles` / `get_atr_window` / `get_rsi_window` accessors
  consumed by `signal_engine.build_signal`. 24 new tests pass; full
  loop / maker-checker / signal-engine suites green (407/407).
- [x] 2026-08-09: Frontend **deployed to Vercel** (`https://www.cryptoagg.xyz`)

## Watch List

<!-- 由循环自动填充 -->

- Phase 0 **live** baseline (real harness + market data) — fill table in `docs/loop-state/phase0-baseline.md`

- Expand contributor failure stories (dependency sweeper, multi-loop)
- Collect a production story for Post-Merge Cleanup
- Validate `loop-init` scaffolds on fresh projects across all patterns

## Recent Noise (ignored this run)

<!-- 由循环自动填充 -->

---

_Maintained by: `.github/workflows/daily-triage.yml`_
_See also: `docs/loop-state/LOOP.md`_
