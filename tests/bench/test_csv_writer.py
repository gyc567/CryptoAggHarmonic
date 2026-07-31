"""Tests for bench.report.csv_writer."""

from __future__ import annotations

import csv
import io
import os

import pytest

from bench.dataset.signal_record import empty_record
from bench.report.csv_writer import (
    CSV_COLUMNS,
    record_to_row,
    write_csv,
    write_csv_string,
)


def test_csv_columns_count_is_45() -> None:
    assert len(CSV_COLUMNS) == 45


def test_csv_columns_unique() -> None:
    assert len(set(CSV_COLUMNS)) == len(CSV_COLUMNS)


def test_csv_columns_have_expected_order() -> None:
    # Identity first
    assert CSV_COLUMNS[0] == "signal_id"
    assert CSV_COLUMNS[1] == "run_id"
    assert CSV_COLUMNS[2] == "params_sha"
    # Time next
    assert CSV_COLUMNS[3] == "timestamp"
    # Extras are last
    extras = [c for c in CSV_COLUMNS if c.startswith("extra_")]
    assert extras == [f"extra_{c}" for c in "abcdefghijklm"]
    assert extras[-1] == "extra_m"


def test_record_to_row_maps_known_fields() -> None:
    rec = empty_record(
        signal_id="sid",
        run_id="rid",
        params_sha="sha",
        timestamp="2026-07-30T00:00:00Z",
        split="is",
        pattern_type="gartley",
        direction="long",
        entry_price=100.0,
        stop_price=95.0,
        tp1=110.0,
        stage1_score=10.0,
        stage3_score=40.0,
        stage4a_score=15.0,
        stage4b_score=8.0,
        signal_score=80.0,
        config_score=70.0,
        bench_total=76.0,
        outcome="tp1",
        net_rr=2.0,
        bars_held=10,
        weak_validity=False,
        mae=1.0,
        mfe=10.0,
        mae_atr_ratio=0.5,
        mfe_atr_ratio=5.0,
        callback_depth=0.5,
        callback_bars=2,
        callback_volume_ratio=0.7,
        hit_stop_before_tp=False,
        stop_zone_touches=1,
        price_efficiency=0.8,
    )
    row = record_to_row(rec)
    for col in CSV_COLUMNS:
        assert col in row
    assert row["signal_id"] == "sid"
    assert row["entry_price"] == 100.0
    assert row["outcome"] == "tp1"
    # CSV column mapping:
    assert row["pattern"] == "gartley"  # from pattern_type
    assert row["r_multiple"] == 2.0     # from net_rr
    assert row["horizon_bars"] is None  # not stored on record


def test_record_to_row_extras_default_to_none() -> None:
    row = record_to_row(empty_record())
    extras = [c for c in CSV_COLUMNS if c.startswith("extra_")]
    assert all(row[k] is None for k in extras)


def test_write_csv_writes_header_and_rows(tmp_path) -> None:
    out = tmp_path / "report.csv"
    records = [
        empty_record(signal_id=f"sig{i}", entry_price=100 + i)
        for i in range(3)
    ]
    n = write_csv(records, str(out))
    assert n == 3
    with open(out) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == CSV_COLUMNS
    assert len(rows) == 3
    assert rows[0][0] == "sig0"
    assert rows[2][0] == "sig2"


def test_write_csv_empty(tmp_path) -> None:
    out = tmp_path / "report.csv"
    n = write_csv([], str(out))
    assert n == 0
    with open(out) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == CSV_COLUMNS
    assert rows == []


def test_write_csv_string_round_trip() -> None:
    records = [empty_record(signal_id="sig1", entry_price=100)]
    s = write_csv_string(records)
    assert "sig1" in s
    assert "signal_id" in s
    # Header is the first line
    first_line = s.splitlines()[0]
    cols = first_line.split(",")
    assert cols == CSV_COLUMNS


def test_write_csv_round_trip_via_csv_module(tmp_path) -> None:
    """Verify the CSV is parseable by stdlib csv.DictReader."""
    out = tmp_path / "report.csv"
    records = [
        empty_record(signal_id=f"sig{i}", entry_price=100 + i)
        for i in range(5)
    ]
    write_csv(records, str(out))
    with open(out) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 5
    assert rows[0]["signal_id"] == "sig0"
    assert rows[4]["entry_price"] == "104"
