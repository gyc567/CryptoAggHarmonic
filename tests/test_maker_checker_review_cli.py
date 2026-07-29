"""Tests for the :mod:`app.loop.maker_checker.review` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.loop.maker_checker.review import (
    HumanReviewDecision,
    main,
)


class TestMainList:
    def test_no_log_returns_message(self, tmp_path: Path, capsys) -> None:
        code = main(["--state-root", str(tmp_path), "list"])
        assert code == 0
        out = capsys.readouterr().out
        assert "no decisions" in out

    def test_list_with_entries(self, tmp_path: Path, capsys) -> None:
        from app.loop.maker_checker.review import append_decision

        for i in range(3):
            append_decision(
                tmp_path,
                HumanReviewDecision(
                    candidate_id=f"c{i}",
                    decision="accept",
                    reviewer="alice",
                    timestamp=f"2026-07-29T00:00:0{i}Z",
                    notes=f"note-{i}" if i == 0 else "",
                ),
            )
        code = main(["--state-root", str(tmp_path), "list"])
        assert code == 0
        out = capsys.readouterr().out
        assert "c0" in out
        assert "c1" in out
        assert "c2" in out
        assert "note-0" in out

    def test_limit(self, tmp_path: Path, capsys) -> None:
        from app.loop.maker_checker.review import append_decision

        for i in range(5):
            append_decision(
                tmp_path,
                HumanReviewDecision(
                    candidate_id=f"c{i}",
                    decision="accept",
                    reviewer="alice",
                    timestamp="t",
                ),
            )
        main(["--state-root", str(tmp_path), "list", "--limit", "2"])
        out = capsys.readouterr().out
        # Only the last two: c3, c4.
        assert "c3" in out
        assert "c4" in out


class TestMainRecord:
    def test_records_decision(self, tmp_path: Path, capsys) -> None:
        code = main(
            [
                "--state-root",
                str(tmp_path),
                "--reviewer",
                "bob",
                "record",
                "--candidate-id",
                "xyz",
                "--decision",
                "reject",
                "--notes",
                "looks bad",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "recorded" in out
        assert "xyz" in out
        log = tmp_path / "HUMAN_REVIEW_LOG.jsonl"
        assert log.exists()


class TestMainErrors:
    def test_no_subcommand_returns_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2

    def test_help_exits_clean(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
