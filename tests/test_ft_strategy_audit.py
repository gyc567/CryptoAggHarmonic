"""Tests for D-FT-12 audit log: ``app.infra.ft_strategy_audit``.

Contract per ``docs/plans/ft-strategy-ui-integration.md`` §3.3 + ADR-0012 D12:
  - append-only ``.scratch/loop_state/ft_strategy/audit.jsonl``
  - fixed ``source = ft_strategy_ui`` (never HISTORY.jsonl's source set)
  - honors ``LOOP_STATE_ROOT`` env var so tests isolate to tmp
  - per-line JSON record with timestamp, event_type, strategy_id, source,
    plus free-form payload fields
  - directory is created if missing
  - re-appending preserves prior lines (no truncation, no rewrite)
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from app.infra import ft_strategy_audit


@pytest.fixture
def isolated_loop_state(tmp_path, monkeypatch):
    """Redirect LOOP_STATE_ROOT to a tmp dir so tests never touch the repo."""
    root = tmp_path / "loop_state"
    root.mkdir()
    monkeypatch.setenv("LOOP_STATE_ROOT", str(root))
    return root


def test_audit_path_is_under_ft_strategy_subdir(isolated_loop_state):
    """Default audit file is ``<root>/ft_strategy/audit.jsonl``."""
    assert ft_strategy_audit.AUDIT_PATH == isolated_loop_state / "ft_strategy" / "audit.jsonl"


def test_append_creates_parent_directory(tmp_path, monkeypatch):
    """If the ft_strategy dir does not exist, ``append_audit`` creates it."""
    root = tmp_path / "loop_state"
    root.mkdir()
    monkeypatch.setenv("LOOP_STATE_ROOT", str(root))
    assert not (root / "ft_strategy").exists()

    record = ft_strategy_audit.append_audit(
        event_type="refine",
        strategy_id="abc-123",
        version=2,
        note="manual edit",
    )

    assert (root / "ft_strategy").is_dir()
    assert ft_strategy_audit.AUDIT_PATH.exists()
    assert record["source"] == "ft_strategy_ui"


def test_append_writes_one_jsonl_line_per_call(isolated_loop_state):
    """Each call appends exactly one JSON object terminated by newline."""
    ft_strategy_audit.append_audit("refine", "s1", version=2)
    ft_strategy_audit.append_audit("deploy_pr", "s1", version=2, pr_url="x")

    raw = ft_strategy_audit.AUDIT_PATH.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line]
    assert len(lines) == 2

    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["event_type"] == "refine"
    assert second["event_type"] == "deploy_pr"


def test_append_preserves_prior_lines(isolated_loop_state):
    """Append-only: prior records remain readable after subsequent appends."""
    ft_strategy_audit.append_audit("refine", "s1", version=1)
    first_line = ft_strategy_audit.AUDIT_PATH.read_text(encoding="utf-8").splitlines()[0]

    ft_strategy_audit.append_audit("refine", "s1", version=2)
    lines = ft_strategy_audit.AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == first_line


def test_record_carries_timestamp_event_strategy_source(isolated_loop_state):
    """Every record has timestamp (ISO-8601 UTC), event_type, strategy_id, source."""
    record = ft_strategy_audit.append_audit("refine", "s-xyz", version=3)

    assert record["strategy_id"] == "s-xyz"
    assert record["event_type"] == "refine"
    assert record["version"] == 3
    assert record["source"] == "ft_strategy_ui"
    assert record["timestamp"].endswith("Z")
    assert "T" in record["timestamp"]


def test_extra_kwargs_merged_into_record(isolated_loop_state):
    """Free-form payload fields flow through into the JSON record."""
    record = ft_strategy_audit.append_audit(
        "deploy_pr",
        "s1",
        version=4,
        pr_url="https://github.com/x/y/pull/42",
        checklist_passed=True,
    )
    assert record["pr_url"] == "https://github.com/x/y/pull/42"
    assert record["checklist_passed"] is True


def test_source_is_always_ft_strategy_ui(isolated_loop_state):
    """D-FT-12 invariant: ``source`` is hard-coded to ``ft_strategy_ui``.

    A caller that tries to set ``source`` via kwargs must NOT be able to
    poison the audit log with a HISTORY.jsonl-compatible source key.
    """
    record = ft_strategy_audit.append_audit(
        "refine",
        "s1",
        version=1,
        source="freqtrade_hyperopt",
    )
    assert record["source"] == "ft_strategy_ui"


def test_concurrent_appends_do_not_lose_lines(isolated_loop_state):
    """Two threads appending concurrently both produce readable lines."""
    def writer(prefix: str) -> None:
        for i in range(50):
            ft_strategy_audit.append_audit("refine", f"{prefix}-{i}", version=1)

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    lines = [json.loads(line) for line in ft_strategy_audit.AUDIT_PATH.read_text().splitlines() if line]
    assert len(lines) == 100
    assert {line["source"] for line in lines} == {"ft_strategy_ui"}


def test_read_audit_returns_records_in_order(isolated_loop_state):
    """``read_audit`` yields the JSON records in append order."""
    ft_strategy_audit.append_audit("refine", "s1", version=1)
    ft_strategy_audit.append_audit("refine", "s1", version=2)
    ft_strategy_audit.append_audit("deploy_pr", "s1", version=2)

    records = list(ft_strategy_audit.read_audit())
    assert [r["version"] for r in records] == [1, 2, 2]
    assert [r["event_type"] for r in records] == ["refine", "refine", "deploy_pr"]


def test_read_audit_empty_when_missing(isolated_loop_state):
    """Reading before any append returns an empty iterator, not an error."""
    assert list(ft_strategy_audit.read_audit()) == []


def test_append_to_missing_root_uses_default(tmp_path, monkeypatch):
    """When LOOP_STATE_ROOT points at a non-existent dir, ``append_audit``
    creates the full path chain (root + ft_strategy/) before writing."""
    new_root = tmp_path / "another_root"
    assert not new_root.exists()
    monkeypatch.setenv("LOOP_STATE_ROOT", str(new_root))

    ft_strategy_audit.append_audit("refine", "s1", version=1)

    assert (new_root / "ft_strategy" / "audit.jsonl").exists()
