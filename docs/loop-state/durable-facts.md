# Durable Facts — pyharmonics-gpt

> Append-only log of durable project facts.
> NEVER delete entries — mark superseded with `superseded_by`.
> Format: JSON-ish per entry.

## Entries

<!-- Entries are append-only. Format:

### [uuid] — {fact summary}
- **Created**: {date}
- **Content**: {description}
- **Source**: {git commit or decision reference}
- **superseded_by**: {uuid if applicable}

-->

### [v3fup01] — Loop engineering v3 follow-ups shipped
- **Created**: 2026-08-09
- **Source**: docs/loop-engineering-plan.md §7.2 + §10.7 + §16
- **Content**: Closed 4 outstanding v3 follow-ups.
  1. ``/metrics`` publishes all 14 plan §7.2 metrics
     (private ``CollectorRegistry``; producers in driver / worker / runner).
  2. ``scripts/backtest_harmonic_lib._maybe_relax_filters`` no longer
     mutates ``signal_engine.MIN_CANDLES`` via setattr — uses
     ``TuningScope`` (ADR-0003 D9).
  3. ``loop.loop_context.load_episodic`` no longer raises
     ``UnboundLocalError``.
  4. ``app.config.tuning`` exposes ``get_min_candles`` / ``get_atr_window``
     / ``get_rsi_window`` consumed by ``signal_engine.build_signal`` hot
     path.
  24 new tests pass; 407/407 in loop / maker-checker / signal scope.
- **superseded_by**: _none_
