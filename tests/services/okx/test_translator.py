"""Tests HarmonicSignal → OKXOrderParams round-trip.

Covers the 3 translation modes (pattern / indicator / regime) plus
defensive checks on missing fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.translator import (
    HarmonicSignal,
    OKXOrderParams,
    translate,
)


class TestPatternMode:
    """Pattern-driven translation: direct entry/exit/sl from signal fields."""

    def test_round_trip_valid_signal(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley",
            entry_price=65000.0,
            exit_price=66500.0,
            stop_loss=64200.0,
            zrpc_price=64800.0,
            confidence=0.82,
            regime="bullish",
            instrument="BTC-USDT",
        )
        order = translate(sig, mode="pattern")
        assert isinstance(order, OKXOrderParams)
        assert order.instId == "BTC-USDT"
        assert order.side == "buy"
        assert order.ordType == "limit"
        assert order.tpTriggerPx is not None
        assert order.slTriggerPx is not None
        assert order.clOrdId.startswith("OKX-LOOP-")
        assert len(order.clOrdId) == len("OKX-LOOP-") + 12

    def test_missing_required_fields_raises(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Bat",
            entry_price=None,  # missing
            exit_price=66500.0,
            stop_loss=64200.0,
            zrpc_price=64800.0,
            confidence=0.5,
            regime="bullish",
        )
        with pytest.raises(ValueError, match="pattern mode requires"):
            translate(sig, mode="pattern")

    def test_unique_cl_ord_id_per_call(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.8, regime="bullish",
        )
        ids = {translate(sig, mode="pattern").clOrdId for _ in range(50)}
        # 50 calls should produce 50 unique clOrdId values
        assert len(ids) == 50


class TestIndicatorMode:
    """Indicator-driven: needs confidence >= 0.5."""

    def test_high_confidence_passes(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.7, regime="bullish",
        )
        order = translate(sig, mode="indicator")
        assert order.instId  # produced via _translate_pattern fallback

    def test_low_confidence_rejected(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.3, regime="bullish",
        )
        with pytest.raises(ValueError, match="confidence >= 0.5"):
            translate(sig, mode="indicator")


class TestRegimeMode:
    """Regime-driven: regime determines side (bearish → sell)."""

    def test_bearish_regime_flips_side(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Bat", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.8, regime="bearish",
        )
        order = translate(sig, mode="regime")
        assert order.side == "sell"

    def test_bullish_regime_keeps_buy(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.8, regime="bullish",
        )
        order = translate(sig, mode="regime")
        assert order.side == "buy"

    def test_unknown_regime_rejected(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.8, regime="sideways",
        )
        with pytest.raises(ValueError, match="regime in bullish/bearish/ranging"):
            translate(sig, mode="regime")


class TestUnknownMode:
    """Invalid mode triggers assert_never (defense in depth)."""

    def test_unknown_mode_raises(self) -> None:
        sig = HarmonicSignal(
            pattern_type="Gartley", entry_price=100.0, exit_price=110.0,
            stop_loss=95.0, zrpc_price=99.0, confidence=0.8, regime="bullish",
        )
        # Bypass type narrowing to test the runtime guard.
        with pytest.raises((AssertionError, ValueError)):
            translate(sig, mode="bogus")  # type: ignore[arg-type]
