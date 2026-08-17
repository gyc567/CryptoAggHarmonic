"""Shared harmonic signal dataclasses.

Re-exports the canonical :class:`HarmonicSignal` from :mod:`app.domain.signals`
for use by exchange-specific translators (freqtrade, OKX) so they don't need
their own duplicate definitions.

Usage::

    from app.domain.signal_schemas import HarmonicSignal

ponytail: this file is a pure re-export shim — no logic, no state.
No upgrade path needed; the domain module is the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["pattern", "indicator", "regime"]


@dataclass
class HarmonicSignal:
    """Minimal signal representation consumed by exchange translators.

    Fields:
        pattern_type:  e.g. "Gartley", "Bat", "Butterfly"
        entry_price:   suggested entry level (None if TBD)
        exit_price:    first take-profit level (None if TBD)
        stop_loss:     stop-loss level (None if TBD)
        zrpc_price:    Potential Reversal Zone price
        confidence:    0.0–1.0
        regime:        "bullish" | "bearish" | "ranging" | None
        instrument:    exchange-specific instrument ID (e.g. "BTC-USDT" for OKX)

    Canonical source: ``app.domain.signals.Candidate`` is the internal
    domain representation; this dataclass is the translator-facing DTO.
    """

    pattern_type: str
    entry_price: float | None = None
    exit_price: float | None = None
    stop_loss: float | None = None
    zrpc_price: float | None = None
    confidence: float = 0.0
    regime: str | None = None
    instrument: str = "BTC-USDT"  # exchange-specific default
