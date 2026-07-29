"""100% coverage tests for app.services.chart_store and chart distribution."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chart_store import (
    chart_file_path,
    is_valid_chart_name,
    save_chart_locally,
)

VALID_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class TestIsValidChartName:
    @pytest.mark.parametrize(
        "name",
        [
            VALID_ID,
            "a1b2c3d4",
            "a" * 64,
        ],
    )
    def test_valid(self, name):
        assert is_valid_chart_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "short",
            "a" * 65,
            "../etc/passwd",
            "a/b",
            "..",
            "a1b2c3d4.png",
            "A1B2C3D4",  # uppercase not allowed
            "a1b2c3d4.exe",
            "a1b2c3$4",
        ],
    )
    def test_invalid(self, name):
        assert is_valid_chart_name(name) is False


class TestSaveChartLocally:
    def test_save_and_path(self, tmp_path):
        result = save_chart_locally(VALID_ID, PNG, chart_dir=tmp_path)
        assert result == str(tmp_path / f"{VALID_ID}.png")
        assert (tmp_path / f"{VALID_ID}.png").read_bytes() == PNG

    def test_invalid_name_returns_none(self, tmp_path):
        assert save_chart_locally("../evil", PNG, chart_dir=tmp_path) is None
        assert list(tmp_path.iterdir()) == []

    def test_oserror_returns_none(self, tmp_path):
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            assert save_chart_locally(VALID_ID, PNG, chart_dir=tmp_path) is None

    def test_cleanup_removes_old_files(self, tmp_path):
        old = tmp_path / "deadbeef-dead-0000-0000-000000000000.png"
        old.write_bytes(PNG)
        old_time = time.time() - 25 * 3600
        os.utime(old, (old_time, old_time))

        recent = tmp_path / "beefbeef-beef-1111-1111-111111111111.png"
        recent.write_bytes(PNG)

        save_chart_locally(VALID_ID, PNG, chart_dir=tmp_path)

        assert not old.exists()
        assert recent.exists()
        assert (tmp_path / f"{VALID_ID}.png").exists()

    def test_default_chart_dir_used_when_omitted(self, tmp_path):
        with patch("app.services.chart_store.CHART_DIR", tmp_path):
            result = save_chart_locally(VALID_ID, PNG)
        assert result == str(tmp_path / f"{VALID_ID}.png")

    def test_cleanup_tolerates_stat_error(self, tmp_path):
        old = tmp_path / "deadbeef-dead-0000-0000-000000000000.png"
        old.write_bytes(PNG)
        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self == old:
                raise OSError("gone")
            return real_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            result = save_chart_locally(VALID_ID, PNG, chart_dir=tmp_path)
        assert result is not None  # cleanup failure must not block saving
        assert old.exists()  # and the un-stat-able file is left alone


class TestChartFilePath:
    def test_existing_file_returns_absolute_path(self, tmp_path):
        (tmp_path / f"{VALID_ID}.png").write_bytes(PNG)
        result = chart_file_path(VALID_ID, chart_dir=tmp_path)
        assert result == (tmp_path / f"{VALID_ID}.png").resolve()
        assert result.is_absolute()

    def test_missing_file(self, tmp_path):
        assert chart_file_path(VALID_ID, chart_dir=tmp_path) is None

    def test_invalid_name(self, tmp_path):
        assert chart_file_path("../evil", chart_dir=tmp_path) is None


class TestDistributeChart:
    """Orchestrator chart distribution: Supabase first, local fallback."""

    def _chart(self):
        from app.domain.schemas import ChartMeta

        return ChartMeta(format="png")

    def test_supabase_success(self, tmp_path):
        from app.services.analysis import AnalysisOrchestrator

        chart = self._chart()
        with (
            patch("app.services.analysis.upload_chart", return_value="u/x.png"),
            patch("app.services.analysis.get_chart_url", return_value="https://signed"),
        ):
            result = AnalysisOrchestrator._distribute_chart(chart, VALID_ID, PNG, "user-1")
        assert result.url == "https://signed"
        assert result.path == "u/x.png"

    def test_supabase_none_falls_back_to_local(self, tmp_path):
        from app.services.analysis import AnalysisOrchestrator

        chart = self._chart()
        with (
            patch("app.services.analysis.upload_chart", return_value=None),
            patch("app.services.analysis.save_chart_locally", return_value=str(tmp_path / f"{VALID_ID}.png")),
        ):
            result = AnalysisOrchestrator._distribute_chart(chart, VALID_ID, PNG, "user-1")
        assert result.url == f"/api/charts/{VALID_ID}.png"

    def test_supabase_exception_falls_back_to_local(self, tmp_path):
        from app.services.analysis import AnalysisOrchestrator

        chart = self._chart()
        with (
            patch("app.services.analysis.upload_chart", side_effect=RuntimeError("boom")),
            patch("app.services.analysis.save_chart_locally", return_value=str(tmp_path / f"{VALID_ID}.png")),
        ):
            result = AnalysisOrchestrator._distribute_chart(chart, VALID_ID, PNG, "user-1")
        assert result.url == f"/api/charts/{VALID_ID}.png"

    def test_no_user_goes_straight_to_local(self, tmp_path):
        from app.services.analysis import AnalysisOrchestrator

        chart = self._chart()
        with (
            patch("app.services.analysis.upload_chart") as mock_up,
            patch("app.services.analysis.save_chart_locally", return_value=str(tmp_path / f"{VALID_ID}.png")),
        ):
            result = AnalysisOrchestrator._distribute_chart(chart, VALID_ID, PNG, None)
        mock_up.assert_not_called()
        assert result.url == f"/api/charts/{VALID_ID}.png"

    def test_local_save_failure_leaves_url_none(self):
        from app.services.analysis import AnalysisOrchestrator

        chart = self._chart()
        with patch("app.services.analysis.save_chart_locally", return_value=None):
            result = AnalysisOrchestrator._distribute_chart(chart, VALID_ID, PNG, None)
        assert result.url is None
