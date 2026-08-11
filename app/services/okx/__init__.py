"""OKX Agent Trade Kit integration.

Layer 2 downstream of the cryptoagg signal loop. Complements the
freqtrade integration (Layer 1) by providing:

  - market data (funding rate / OI / mark price / 70+ technical
    indicators) — secondary source alongside Binance
  - spot paper-mode order execution via the ``okx-trade-mcp`` MCP
    server (Phase 1 scope; swap/futures/option are Phase 2+)
  - handshake layer that writes OKX fill data into the loop's
    ``HISTORY.jsonl`` with ``source: okx_paper`` (or ``okx_live``)

Files:

  - ``translator.py``  HarmonicSignal → OKX spot order params
  - ``mcp_client.py``  stdio JSON-RPC wrapper around okx-trade-mcp
  - ``executor.py``    write-path with three-gate enforcement
  - ``audit.py``       append-only audit log (outbox mode, 10 fields)
  - ``handshake.py``   OKX result → HISTORY.jsonl round-trip
  - ``data_source.py`` read-only market data wrapper

ADR-0011 governs the design. See ``docs/plans/okx-agent-trade-kit-
integration.md`` (v2) for full architecture.
"""
