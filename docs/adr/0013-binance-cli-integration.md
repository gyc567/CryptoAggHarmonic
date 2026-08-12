# ADR-0013: Binance CLI Integration (Loop #12)

- **Status**: Accepted
- **Date**: 2026-08-12
- **Decider**: loop-engineering (auto), per the plan at
  `docs/plans/binance-cli-integration.md`

## Decision

Integrate `@binance/binance-cli` (v1.3.0) as a **read-only**
secondary source for Binance public market data (mark price, funding
rate, open interest). The wrapper lives at
`app/services/binance/` and is gated by
`app/loop/tuning_promotion.BINANCE_MARKET_TOOLS`.

## Context

`app/infra/marketdata.py` covers Binance Spot klines via REST and
`app/infra/futures_quote.py` covers mark price + funding rate via
the `/fapi/v1/premiumIndex` endpoint, but **open interest** is not
exposed anywhere. The Binance official CLI provides structured access
to OI, funding history, and a richer set of read-only endpoints. The
goal is to add this without disturbing the existing REST path.

## D1 — read-only complement, never replace

`app/services/binance/` is an **alternative path** for fields the
REST layer doesn't expose. It does NOT replace `marketdata.py` or
`futures_quote.py`. If both paths are available, the REST layer is
preferred (lower latency, no subprocess spawn).

## D2 — Phase 1 scope = market data only

Read-only endpoints in scope (see `BINANCE_MARKET_TOOLS` in
`app/loop/tuning_promotion.py`):

- `futures-usds mark-price`
- `futures-usds open-interest`
- `futures-usds open-interest-statistics`
- `futures-usds get-funding-rate-history`
- `futures-usds get-funding-rate-info`
- `futures-usds mark-price-kline-candlestick-data`
- `futures-usds premium-index` (synonym of mark-price)
- `spot ticker` / `klines` / `depth` / `avg-price` / `trades`

Write tools (`spot place-order`, `algo order`, `convert`,
`margin-trading`, etc.) are **out of scope**. They require a
separate ADR + 3-gate (startup-param + env + runtime) — same shape
as OKX ADR-0011.

## D3 — argv-list subprocess + no shell

`data_source._run_cli()` invokes `subprocess.run([BINANCE_CLI_BIN,
*argv, "--json"], shell=False, ...)`. No string concatenation, no
`shell=True`. All errors raise a typed `BinanceCliError`.

## D4 — credentials via env vars only

`BINANCE_API_KEY` / `BINANCE_SECRET_KEY` are passed via environment
variables, never as CLI args or in profile files checked into git.
Public market endpoints don't require any key — Phase 1 doesn't
touch the auth surface at all.

## D5 — source mutex exemption

`source: binance_market` records appended to `HISTORY.jsonl` are
**exempt** from the freqtrade ↔ OKX source mutex (ADR-0011 D11).
They're complementary read-only context, not a candidate proposal.

## D6 — binance-cli version follows skill

The npm package version is governed by `~/.agents/skills/binance/`
manifest. Upgrade cadence: when the skill bumps, `binance-cli` does
too. No project-level pin.

## Consequences

- **Positive**: OI now reachable without writing new REST code;
  latency comparable to direct REST (≤ 320 ms extra for CLI spawn);
  audit trail via HISTORY.jsonl.
- **Negative**: One extra runtime dependency (npm + binance-cli). The
  Python venv doesn't include it; the deploy script must ensure npm
  is on the path.
- **Mitigation**: `data_source._run_cli()` raises a typed
  `BinanceCliError` (with install instructions) when the binary is
  missing, so a fresh dev machine fails loudly instead of silently.

## Verification

- `pytest tests/services/binance/` → 35 passed
- `loop audit` → 100.0/100 [L3]
- Smoke: `python -c "from app.services.binance.data_source import fetch_mark_price; print(fetch_mark_price('BTCUSDT'))"`