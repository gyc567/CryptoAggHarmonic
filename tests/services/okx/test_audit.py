"""Tests AuditLog: 11-field schema, redaction, outbox mode, crash-safe."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.audit import AuditLog


def test_build_record_has_11_fields() -> None:
    log = AuditLog(root=Path(".scratch/audit_test"))
    rec = log.build_record(
        tool="spot_place_order", args={"instId": "BTC-USDT", "side": "buy"},
        salt_version=3, paper=True, gate="dispatched",
        result_code="0", latency_ms=120, trace_id="abc123",
        cl_ord_id="OKX-LOOP-deadbeef",
    )
    expected_fields = {
        "ts", "tool", "args", "result_code", "result_body_hash",
        "user", "salt_version", "paper", "cl_ord_id", "latency_ms",
        "trace_id", "gate",
    }


def test_redact_args_strips_secrets() -> None:
    log = AuditLog(root=Path(".scratch/audit_test"))
    rec = log.build_record(
        tool="spot_place_order",
        args={"api_key": "REAL-KEY-AAA", "instId": "BTC-USDT",
              "nested": {"secret_key": "REAL-SECRET-BBB"}},
        salt_version=1, paper=True, gate="dispatched",
        result_code="0", latency_ms=10, trace_id=None,
    )
    assert rec["args"]["api_key"] == "***"
    assert rec["args"]["instId"] == "BTC-USDT"
    assert rec["args"]["nested"]["secret_key"] == "***"


def test_redact_args_handles_list() -> None:
    log = AuditLog(root=Path(".scratch/audit_test"))
    rec = log.build_record(
        tool="spot_batch_place_orders",
        args=[{"apiKey": "K1"}, {"apiKey": "K2", "instId": "ETH-USDT"}],
        salt_version=1, paper=True, gate="dispatched",
        result_code="0", latency_ms=10, trace_id=None,
    )
    assert rec["args"][0]["apiKey"] == "***"
    assert rec["args"][1]["apiKey"] == "***"
    assert rec["args"][1]["instId"] == "ETH-USDT"


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    log = AuditLog(root=tmp_path / "audit")
    for i in range(3):
        rec = log.build_record(
            tool="spot_place_order", args={"idx": i},
            salt_version=1, paper=True, gate="dispatched",
            result_code="0", latency_ms=i * 10, trace_id=None,
        )
        log.write(rec)
    records = log.read_today()
    assert len(records) == 3
    assert [r["args"]["idx"] for r in records] == [0, 1, 2]


def test_outbox_cleaned_after_write(tmp_path: Path) -> None:
    log = AuditLog(root=tmp_path / "audit")
    rec = log.build_record(
        tool="spot_place_order", args={"foo": "bar"},
        salt_version=1, paper=True, gate="dispatched",
        result_code="0", latency_ms=10, trace_id=None,
    )
    log.write(rec)
    outbox = log.root / f"{log._date_str()}.jsonl.outbox"
    leftovers = list(outbox.iterdir())
    assert leftovers == []


def test_result_body_hash_is_stable() -> None:
    log = AuditLog(root=Path(".scratch/audit_test"))
    rec = log.build_record(
        tool="spot_place_order", args={}, salt_version=1, paper=True,
        gate="dispatched", result_code="0", latency_ms=10, trace_id=None,
        result_body={"ordId": "12345", "fillPx": "65000"},
    )
    rec2 = log.build_record(
        tool="spot_place_order", args={}, salt_version=1, paper=True,
        gate="dispatched", result_code="0", latency_ms=10, trace_id=None,
        result_body={"ordId": "12345", "fillPx": "65000"},
    )
    assert rec["result_body_hash"] == rec2["result_body_hash"]
    assert rec["result_body_hash"].startswith("sha256:")
