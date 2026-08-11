"""Tests that tuning_promotion.py blocks freqtrade hyperopt direct-TUNING paths."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.loop.tuning_promotion import (
    is_live_tuning_path,
    promotion_allowed_for_files,
    promotion_checklist,
)


class TestTuningPromotionGate:
    """Verify promotion gate blocks direct TUNING modification from freqtrade path."""

    def test_live_tuning_path_rejected(self) -> None:
        """Direct edit to app/config/tuning.py must be blocked."""
        assert is_live_tuning_path("app/config/tuning.py") is True
        # .py extension required
        assert is_live_tuning_path("app/config/tuning") is False

    def test_freqtrade_dir_allowed(self) -> None:
        """freqtrade hyperopt results must NOT directly write to TUNING."""
        ok, reason = promotion_allowed_for_files([
            ".scratch/loop_state/freqtrade/hyperopt_results/result.yaml",
            "app/services/freqtrade/translator.py",
        ])
        assert ok is True, reason

    def test_live_tuning_blocked(self) -> None:
        """Any path touching app/config/tuning.py must be rejected."""
        ok, reason = promotion_allowed_for_files([
            ".scratch/loop_state/freqtrade/hyperopt_results/result.yaml",
            "app/config/tuning.py",
        ])
        assert ok is False
        assert "live TUNING promotion blocked" in reason

    def test_promotion_checklist_includes_drawdown_gate(self) -> None:
        """promotion_checklist() must include drawdown/Calmar/Shadow gates."""
        steps = promotion_checklist()
        assert isinstance(steps, list)
        assert len(steps) >= 4
        full_text = "\n".join(steps)
        assert "drawdown" in full_text.lower()

    def test_promotion_checklist_includes_salt_version(self) -> None:
        """promotion_checklist() must include salt_version traceability."""
        steps = promotion_checklist()
        full_text = "\n".join(steps)
        assert "salt_version" in full_text
