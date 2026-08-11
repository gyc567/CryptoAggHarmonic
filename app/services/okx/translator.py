"""HarmonicSignal → OKX spot order params translator.

Mirrors ``app/services/freqtrade/translator.py`` but for OKX spot
orders. Phase 1 scope: spot only (no swap/futures/option).

Output is a dict consumable by ``mcp_client.invoke_tool()`` — NOT a
file, since OKX MCP tools take JSON args directly. ClOrdId is
mandatory and must be unique per candidate (nonce, ADR-0011 M4).

   — minimal signal representation
  - ``OKXOrderParams``   — translated spot order params
  - ``translate(signal, mode) -> OKXOrderParams``

Phase 2 will add ``translate_swap`` / ``translate_futures`` (gated
by ``OKX_ALLOW_LIVE=1`` + checklist).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, assert_never

# OKX default instrument format. Examples: "BTC-USDT", "ETH-USDT".
# spot module requires this exact format.
INSTRUMENT_SPOT = "BTC-USDT"  # overwritten by translator

Mode = Literal["pattern", "indicator", "regime"]


@dataclass
class HarmonicSignal:
    """Minimal signal representation consumed by the OKX translator."""

    pattern_type: str  # e.g. "Gartley", "Bat", "Butterfly"
    entry_price: float | None
    exit_price: float | None
    stop_loss: float | None
    zrpc_price: float | None  # Potential Reversal Zone price
    confidence: float  # 0.0–1.0
    regime: str | None  # e.g. "bullish", "bearish", "ranging"
    instrument: str = INSTRUMENT_SPOT  # OKX instrument id


@dataclass
class OKXOrderParams:
    """Translated OKX spot order params. Pass to mcp_client.invoke_tool
    as the ``args`` field for ``spot_place_order``."""

    instId: str
    side: Literal["buy", "sell"]
    ordType: Literal["market", "limit", "post_only", "fok", "ioc"]
    sz: str  # OKX expects string for size (precision matters)
    px: str | None = None
    clOrdId: str = field(default_factory=lambda: f"OKX-LOOP-{uuid.uuid4().hex[:12]}")
    # Attached TP/SL (optional; populated when exit_price + stop_loss present)
    tpTriggerPx: str | None = None
    tpOrdPx: str | None = None
    slTriggerPx: str | None = None
    slOrdPx: str | None = None


def translate(signal: HarmonicSignal, mode: Mode = "pattern") -> OKXOrderParams:
    """Translate a HarmonicSignal into OKX spot order params.

    Args:
        signal: The harmonic pattern signal to translate.
        mode: Translation mode (pattern | indicator | regime). Phase 1
            supports all three; behavior mirrors freqtrade translator.

    Returns:
        OKXOrderParams ready for ``spot_place_order`` invocation.

    Raises:
        ValueError: If required signal fields are missing for the mode.
    """
    if mode == "pattern":
        return _translate_pattern(signal)
    if mode == "indicator":
        return _translate_indicator(signal)
    if mode == "regime":
        return _translate_regime(signal)
    assert_never(mode)


def _translate_pattern(signal: HarmonicSignal) -> OKXOrderParams:
    """Pattern-driven translation: direct entry/exit/sl from signal fields."""
    if signal.entry_price is None or signal.exit_price is None or signal.stop_loss is None:
        raise ValueError(
            f"pattern mode requires entry_price, exit_price, stop_loss; "
            f"got entry={signal.entry_price} exit={signal.exit_price} sl={signal.stop_loss}"
        )
    return OKXOrderParams(
        instId=signal.instrument,
        side="buy",  # pattern signals imply long entry; short = Phase 2
        ordType="limit",
        sz="0",  # caller must populate before dispatch (size depends on account)
        px=f"{signal.entry_price:.8f}".rstrip("0").rstrip("."),
        tpTriggerPx=f"{signal.exit_price:.8f}".rstrip("0").rstrip("."),
        tpOrdPx=f"{(signal.exit_price * 0.999):.8f}".rstrip("0").rstrip("."),
        slTriggerPx=f"{signal.stop_loss:.8f}".rstrip("0").rstrip("."),
        slOrdPx=f"{(signal.stop_loss * 1.001):.8f}".rstrip("0").rstrip("."),
    )


def _translate_indicator(signal: HarmonicSignal) -> OKXOrderParams:
    """Indicator-driven: use ATR_RATIO / RSI thresholds (Phase 1 stub)."""
    # Phase 2: pull ATR/RSI from signal metadata when available.
    # For now, defer to pattern with reduced confidence.
    if signal.confidence < 0.5:
        raise ValueError(f"indicator mode requires confidence >= 0.5, got {signal.confidence}")
    return _translate_pattern(signal)


def _translate_regime(signal: HarmonicSignal) -> OKXOrderParams:
    """Regime-driven: regime tag determines side (Phase 1 stub)."""
    if signal.regime not in ("bullish", "bearish", "ranging"):
        raise ValueError(f"regime mode requires regime in bullish/bearish/ranging, got {signal.regime!r}")
    order = _translate_pattern(signal)
    if signal.regime == "bearish":
        order.side = "sell"  # short entry; can_short check is at executor gate
    return order
