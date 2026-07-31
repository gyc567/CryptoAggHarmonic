"""Walk-forward split + boundary handling for the bench dataset.

Pure functions only; no I/O. The runner passes already-built
SignalRecord lists + the entry-bar index of each signal; we mutate
each record's ``split`` field in place and mark signals whose forward
window crosses the boundary.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from bench.dataset.signal_record import SignalRecord


def split_boundary(total_bars: int, is_ratio: float = 0.7) -> int:
    """Return the bar index of the IS/OOS boundary.

    ``is_ratio`` is clamped to (0, 1). Boundary index is inclusive
    for IS (so bars [0, boundary] are IS, bars [boundary+1, ...] are
    OOS). Given the validated inputs, ``int(total_bars * is_ratio)``
    is always strictly less than ``total_bars`` — no clamp needed.
    """
    if total_bars <= 0:
        raise ValueError("total_bars must be positive")
    if not 0.0 < is_ratio < 1.0:
        raise ValueError("is_ratio must be in (0, 1)")
    return int(total_bars * is_ratio)


def assign_split(
    records: Iterable[SignalRecord],
    bar_index_of: dict,
    boundary: int,
) -> int:
    """Mutate each record's ``split`` to 'is' or 'oos' by entry bar.

    ``bar_index_of`` maps ``record.signal_id`` -> entry-bar index
    (i.e. the bar index of the record's ``timestamp`` within the
    full historical series). Records whose ``signal_id`` is missing
    from the map are left untouched (split stays None). The caller
    is expected to surface such gaps in the report metadata.

    Returns the count of records assigned.
    """
    assigned = 0
    for rec in records:
        idx = bar_index_of.get(rec.signal_id)
        if idx is None:
            continue
        rec.split = "is" if idx <= boundary else "oos"
        assigned += 1
    return assigned


def find_boundary_crossings(
    records: Iterable[SignalRecord],
    bar_index_of: dict,
    boundary: int,
    horizon: Optional[int] = None,
    horizon_of: Optional[dict] = None,
) -> int:
    """Mark records whose forward window crosses the IS/OOS boundary.

    A signal at entry-bar ``e`` with horizon ``h`` consumes bars
    ``[e, e+h-1]``. If ``e <= boundary < e + h - 1``, the trade's
    exit bar is in OOS while entry is in IS.

    ``horizon`` is the uniform horizon used when ``horizon_of`` is
    not supplied. ``horizon_of`` maps ``signal_id`` -> per-record
    horizon and takes precedence over ``horizon``.

    Marked records get:
    * ``crosses_boundary = True``
    * ``boundary_distance_bars = (e + h - 1) - boundary`` (how many
      OOS bars the trade consumes)

    Returns the count of crossings found.
    """
    if horizon_of is None and horizon is None:
        raise ValueError("either horizon or horizon_of must be provided")
    if horizon_of is None and horizon is not None and horizon <= 0:
        raise ValueError("horizon must be positive")
    count = 0
    for rec in records:
        idx = bar_index_of.get(rec.signal_id)
        if idx is None:
            rec.crosses_boundary = False
            rec.boundary_distance_bars = None
            continue
        h = (
            horizon_of.get(rec.signal_id)
            if horizon_of is not None
            else horizon
        )
        if h is None or h <= 0:
            rec.crosses_boundary = False
            rec.boundary_distance_bars = None
            continue
        exit_bar = idx + h - 1
        if idx <= boundary < exit_bar:
            rec.crosses_boundary = True
            rec.boundary_distance_bars = exit_bar - boundary
            count += 1
        else:
            rec.crosses_boundary = False
            rec.boundary_distance_bars = None
    return count


def boundary_discount(rec: SignalRecord, horizon: int) -> float:
    """Return the OOS score discount factor in [0, 1] for one record.

    Per v3 changelog item 5:
    ``discount = 1 - boundary_distance / horizon``

    Records with no boundary crossing receive 1.0 (no discount).
    The discount is clamped to [0, 1] so that future changes to the
    crossing logic can't accidentally produce values outside this range.
    """
    if not rec.crosses_boundary:
        return 1.0
    if rec.boundary_distance_bars is None:
        return 1.0
    if horizon <= 0:
        return 1.0
    discount = 1.0 - rec.boundary_distance_bars / horizon
    if discount < 0.0:
        return 0.0
    return discount


def partition_by_split(
    records: Iterable[SignalRecord],
) -> Tuple[List[SignalRecord], List[SignalRecord]]:
    """Return ``(is_records, oos_records)`` lists in input order.

    Records whose ``split`` is ``None`` are silently dropped; the
    caller is expected to surface such gaps in the report metadata.
    """
    is_recs: List[SignalRecord] = []
    oos_recs: List[SignalRecord] = []
    for rec in records:
        if rec.split == "is":
            is_recs.append(rec)
        elif rec.split == "oos":
            oos_recs.append(rec)
    return is_recs, oos_recs
