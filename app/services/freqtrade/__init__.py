# Freqtrade integration — Signal → FreqtradeStrategy translation layer.
#
# Architecture (ADR-0010 D2):
#   app/services/freqtrade/  ← new code here (NOT in app/loop/ — Ponytail exclusion zone)
#   translator.py: HarmonicSignal → IStrategy file
#   mcp_client.py: MCP tool discovery + invocation (timeout=1800s, cap=5/gen)
#   handshake.py: hyperopt yaml → HISTORY.jsonl (outbox, source=freqtrade_hyperopt)
#
# TUNING promotion is handled by app/loop/tuning_promotion.py (ADR-0010 D1: reuse, don't duplicate).
