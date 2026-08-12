# Loop #12 — Binance Market Data Loop

> Binance CLI (npm package `@binance/binance-cli`, v1.3.0) integration
> for read-only public market data: mark price, funding rate, open
> interest. Loop-engineering complement to the existing REST path
> (`app/infra/marketdata.py`).

## Cadence

| Trigger | Frequency |
|---|---|
| On-demand (route handler / scheduler / outerloop) | event-driven |
| Loop-economics log poll | every 6 h (advisory) |

## Trigger

API request, scheduler tick, or outerloop correlation. The Binance
data source is stateless (each fetch is independent) and is invoked
whenever a downstream consumer needs a fresh value.

## Skill

`binance` — npm package `@binance/binance-cli` (skill manifest at
`~/.agents/skills/binance/SKILL.md`). **Read-only** public market data
endpoints only.

## State

- `app/services/binance/data_source.py` — DTOs + CLI wrapper
- `app/services/binance/handshake.py` — appends `source: binance_market`
  records to `HISTORY.jsonl`
- `app/services/binance/metrics.py` — counters / histograms (no
  external dep; hand-rolled prom-style)
- `app/loop/tuning_promotion.py` — `BINANCE_MARKET_TOOLS` allowlist,
  `is_market_data_tool()` + `market_data_allowed_for_tools()` gate

## Inputs

| Input | Source |
|---|---|
| Symbol set | Caller (route handler / scheduler / outerloop) |
| Endpoint | One of `mark_price`, `open_interest`, `funding_history` |
| Latency budget | Default 5 s; override via `timeout_s` |

## Outputs

| Output | Destination |
|---|---|
| MarkPrice / OpenInterest / list[FundingRate] dataclasses | Returned to caller |
| `HISTORY.jsonl` records (`source: binance_market`) | `app/loop/state.py` |
| Metrics: `binance_market_fetch_total{endpoint,status}` | `app/api/metrics_routes.py` `/metrics` endpoint |
| Latency: `binance_market_latency_seconds{endpoint}` | Same |

## Gate

- L2 — **suggest-only**, never auto-executes a write tool.
- ADR-0013 D2: write tools (algo, spot order, etc.) are NOT in
  scope here. They would require a separate ADR + 3-gate
  (startup-param + env + runtime) — same shape as OKX ADR-0011.
- ADR-0013 D5: source `binance_market` is **exempt** from the
  freqtrade ↔ OKX source mutex (read-only).
- `gate.yaml` denylist: `app/services/binance/__pycache__/`,
  `node_modules/@binance/`, etc. (defense in depth)

## MCP

- None for read-only market data — `binance-cli` runs as a subprocess
  invoked by `data_source._run_cli()`. The CLI binary is at
  `/Users/jie/.hermes/node/bin/binance-cli` (or `BINANCE_CLI_BIN` env).

## Promotion

Not applicable. The binance data source is a read-only context
provider — it has no TUNING output, no candidate_ids, no backtest
gate. Outerloop correlation (e.g. "is this candidate's Sharpe
attributable to a favorable funding-rate regime?") happens later,
not in this loop.

## Non-Goals

- ❌ Spot / futures / algo order placement (Phase 2+ requires
  separate ADR + write gate, mirroring OKX ADR-0011)
- ❌ Replacing `app/infra/marketdata.py` (REST stays as primary
  fallback)
- ❌ Live trading credentials in `app/services/binance/`
  (the public market data endpoints don't need any key; private
  endpoints are out of scope)

## ADR

`docs/adr/0013-binance-cli-integration.md` (D1–D6)

## Verification

| Item | Command |
|---|---|
| Loop registered | `python -m loop.loop_sync check .` |
| CLI smoke | `binance-cli futures-usds mark-price --symbol BTCUSDT` |
| Data source smoke | `python -c "from app.services.binance.data_source import fetch_mark_price; print(fetch_mark_price('BTCUSDT'))"` |
| Tests | `pytest tests/services/binance/ -v` (35 passed) |
| Loop readiness | `python -m loop.loop audit .` (expect 100.0/100 [L3]) |