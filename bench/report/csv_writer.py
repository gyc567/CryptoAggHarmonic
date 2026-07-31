"""CSV writer for bench records.

v3 changelog item 15 + docs/HarmonicSignal-Bench.md report schema.

Writes a 45-column CSV with the schema fields below. The order is
fixed so downstream consumers can rely on positional parsing.
"""

from __future__ import annotations

import csv
from typing import Iterable, List

from bench.dataset.signal_record import SignalRecord


# Schema columns in fixed order. Per v3 changelog item 15.
# Field names map to SignalRecord attribute names. The spec wording
# (e.g. "pattern") maps to the actual attribute (pattern_type) — this
# keeps the CSV readable while reusing the dataclass schema.
CSV_COLUMNS: List[str] = [
    # Identity (3)
    "signal_id",
    "run_id",
    "params_sha",
    # Time (3)
    "timestamp",
    "split",
    "horizon_bars",
    # Geometry (5)
    "pattern",
    "direction",
    "entry_price",
    "stop_price",
    "tp1",
    # Stage scores (4)
    "stage1_score",
    "stage3_score",
    "stage4a_score",
    "stage4b_score",
    # Aggregates (3)
    "signal_score",
    "config_score",
    "bench_total",
    # Outcome (4)
    "outcome",
    "r_multiple",
    "bars_held",
    "weak_validity",
    # Trade metrics (8)
    "mae",
    "mfe",
    "mae_atr_ratio",
    "mfe_atr_ratio",
    "callback_depth",
    "callback_bars",
    "callback_volume_ratio",
    "hit_stop_before_tp",
    # Zone / efficiency (2)
    "stop_zone_touches",
    "price_efficiency",
    # Optional extras (13) — pad to 45 total
    "extra_a",
    "extra_b",
    "extra_c",
    "extra_d",
    "extra_e",
    "extra_f",
    "extra_g",
    "extra_h",
    "extra_i",
    "extra_j",
    "extra_k",
    "extra_l",
    "extra_m",
]


# Map CSV column → SignalRecord attribute. Where they differ, we
# translate here so the CSV header stays readable.
_COL_TO_ATTR: dict[str, str] = {
    "pattern": "pattern_type",
    "r_multiple": "net_rr",
    "horizon_bars": None,  # not stored on record; dataset_builder holds it
}


def record_to_row(rec: SignalRecord) -> dict:
    """Map a SignalRecord to a CSV row dict keyed by CSV_COLUMNS.

    Columns with no matching attribute (placeholder ``extra_*`` slots
    or ``horizon_bars`` which lives outside the record) are set to
    ``None``. The caller can post-process to fill them in.
    """
    row: dict = {}
    for col in CSV_COLUMNS:
        attr = _COL_TO_ATTR.get(col, col)
        if attr is None or not hasattr(rec, attr):
            row[col] = None
            continue
        row[col] = getattr(rec, attr)
    return row


def write_csv(records: Iterable[SignalRecord], path: str) -> int:
    """Write ``records`` to ``path`` as a CSV with ``CSV_COLUMNS`` order.

    Returns the number of rows written (excluding header).
    """
    n = 0
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rec in records:
            writer.writerow(record_to_row(rec))
            n += 1
    return n


def write_csv_string(records: Iterable[SignalRecord]) -> str:
    """In-memory variant for tests / small reports."""
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for rec in records:
        writer.writerow(record_to_row(rec))
    return buf.getvalue()
