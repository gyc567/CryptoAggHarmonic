"""Tests for bench.dataset.signal_record."""

from __future__ import annotations

import pytest

from bench.dataset.signal_record import SignalRecord, empty_record


def test_empty_record_defaults_are_minimal() -> None:
    rec = empty_record()
    assert rec.signal_id == "sid_test"
    assert rec.symbol == "BTCUSDT"
    assert rec.direction == "long"
    assert rec.grade == "C"
    assert rec.split is None
    assert rec.weak_validity is False
    assert rec.crosses_boundary is False
    assert rec.ai_degraded is False
    assert rec.outcome is None


def test_empty_record_overrides_apply() -> None:
    rec = empty_record(signal_id="abc", direction="short", entry_price=200.0)
    assert rec.signal_id == "abc"
    assert rec.direction == "short"
    assert rec.entry_price == 200.0


def test_to_dict_returns_all_fields() -> None:
    rec = empty_record()
    d = rec.to_dict()
    assert isinstance(d, dict)
    # spot-check that key fields are present
    for key in ("signal_id", "run_id", "entry_price", "split",
                "weak_validity", "crosses_boundary", "ai_degraded",
                "stage1_score", "stage3_score", "stage4a_score",
                "stage4b_score", "stage4c_score", "signal_score"):
        assert key in d


def test_signal_record_required_fields() -> None:
    """Constructing without required fields raises TypeError."""
    with pytest.raises(TypeError):
        SignalRecord()  # type: ignore[call-arg]


def test_outcome_literal_validation() -> None:
    """Dataclass accepts valid Outcome literals; type-checker is responsible."""
    rec = empty_record(outcome="tp1")
    assert rec.outcome == "tp1"
    rec2 = empty_record(outcome="stoploss")
    assert rec2.outcome == "stoploss"


def test_field_defaults_for_optional_metrics() -> None:
    rec = empty_record()
    assert rec.mae is None
    assert rec.mfe is None
    assert rec.mae_atr_ratio is None
    assert rec.callback_depth is None
    assert rec.bars_held is None
    assert rec.ai_score is None
