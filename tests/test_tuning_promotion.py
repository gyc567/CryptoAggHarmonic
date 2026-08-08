"""Tests for TUNING live-promotion gate helpers."""

from __future__ import annotations

from app.loop.tuning_promotion import (
    LIVE_TUNING_PATH,
    is_live_tuning_path,
    promotion_allowed_for_files,
    promotion_checklist,
)
from loop.loop_gate import check_files, check_path


class TestIsLiveTuningPath:
    def test_exact(self):
        assert is_live_tuning_path(LIVE_TUNING_PATH)
        assert is_live_tuning_path("app/config/tuning.py")

    def test_other_paths(self):
        assert not is_live_tuning_path("app/config/settings.py")
        assert not is_live_tuning_path("docs/loop-state/gate.yaml")


class TestPromotionAllowed:
    def test_blocks_tuning(self):
        ok, reason = promotion_allowed_for_files(["app/config/tuning.py"])
        assert not ok
        assert "TUNING" in reason or "tuning" in reason

    def test_allows_other(self):
        ok, reason = promotion_allowed_for_files(["app/loop/search.py"])
        assert ok
        assert reason == "ok"

    def test_checklist_nonempty(self):
        steps = promotion_checklist()
        assert len(steps) >= 3
        assert any("SIGHUP" in s for s in steps)


class TestGateIntegration:
    def test_gate_blocks_tuning_path(self):
        allowed, reason = check_path("app/config/tuning.py")
        assert not allowed
        assert reason  # denylist or promotion hard rule

    def test_gate_allows_loop_cli(self):
        result = check_files(["loop/loop.py", "docs/loop-state/STATE.md"])
        assert result["passed"]
