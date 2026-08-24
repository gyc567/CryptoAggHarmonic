"""Tests for app.services.freqtrade.translator."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.freqtrade.translator import (
    HarmonicSignal,
    Mode,
    TranslatorConfig,
    translate,
)


class TestHarmonicSignal:
    def test_minimal_signal(self) -> None:
        s = HarmonicSignal(
            pattern_type="Gartley",
            entry_price=None,
            exit_price=None,
            stop_loss=None,
            zrpc_price=None,
            confidence=0.75,
            regime=None,
        )
        assert s.pattern_type == "Gartley"
        assert s.confidence == 0.75


class TestTranslate:
    def test_pattern_mode_requires_signal_fields(self) -> None:
        s = HarmonicSignal(
            pattern_type="Bat",
            entry_price=50000.0,
            exit_price=51000.0,
            stop_loss=49500.0,
            zrpc_price=50200.0,
            confidence=0.8,
            regime="bullish",
        )
        cfg = TranslatorConfig(timeframe="1h")
        path = translate(s, cfg, mode="pattern")
        try:
            assert path.exists()
            assert path.suffix == ".py"
            # Verify generated file is valid Python
            source = path.read_text()
            ast.parse(source)
            assert "HarmonicSignal" in source
            assert "IStrategy" in source
        finally:
            if path.exists():
                path.unlink()

    def test_pattern_mode_missing_entry_raises(self) -> None:
        s = HarmonicSignal(
            pattern_type="Gartley",
            entry_price=None,  # missing
            exit_price=51000.0,
            stop_loss=49500.0,
            zrpc_price=None,
            confidence=0.7,
            regime=None,
        )
        cfg = TranslatorConfig()
        try:
            translate(s, cfg, mode="pattern")
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "pattern mode requires" in str(e)

    def test_indicator_mode(self) -> None:
        s = HarmonicSignal(
            pattern_type="Butterfly",
            entry_price=None,
            exit_price=None,
            stop_loss=None,
            zrpc_price=None,
            confidence=0.65,
            regime=None,
        )
        cfg = TranslatorConfig()
        path = translate(s, cfg, mode="indicator")
        try:
            assert path.exists()
            ast.parse(path.read_text())
            assert "IndDriver" in path.stem
        finally:
            if path.exists():
                path.unlink()

    def test_regime_mode(self) -> None:
        s = HarmonicSignal(
            pattern_type="Crab",
            entry_price=None,
            exit_price=None,
            stop_loss=None,
            zrpc_price=None,
            confidence=0.7,
            regime="bearish",
        )
        cfg = TranslatorConfig()
        path = translate(s, cfg, mode="regime")
        try:
            assert path.exists()
            ast.parse(path.read_text())
            assert "RegimeDriver" in path.stem
        finally:
            if path.exists():
                path.unlink()

    def test_unknown_mode_raises(self) -> None:
        s = HarmonicSignal(
            pattern_type="Gartley",
            entry_price=50000.0,
            exit_price=51000.0,
            stop_loss=49500.0,
            zrpc_price=None,
            confidence=0.7,
            regime=None,
        )
        cfg = TranslatorConfig()
        try:
            translate(s, cfg, mode="unknown")  # type: ignore
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "Unknown translation mode" in str(e)
