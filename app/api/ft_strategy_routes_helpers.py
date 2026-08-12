"""Internal helpers for ft_strategy_routes.

Kept separate to keep the routes module focused on Flask wiring.
"""

from __future__ import annotations

from typing import Any, Iterable

from flask import jsonify

from app.loop.tuning_promotion_v3 import PerTimerangeResult


def _coerce_per_timerange(items: Iterable[Any]) -> tuple[PerTimerangeResult, ...]:
    """Coerce a list of dicts or PerTimerangeResults into a tuple of PerTimerangeResult.

    JSON-serialized dicts come back via Flask; dataclasses do not.
    """
    out: list[PerTimerangeResult] = []
    for item in items:
        if isinstance(item, PerTimerangeResult):
            out.append(item)
            continue
        if isinstance(item, dict):
            out.append(PerTimerangeResult(
                regime=item["regime"],
                sharpe=float(item["sharpe"]),
                max_dd=float(item["max_dd"]),
                calmar=float(item["calmar"]),
            ))
    return tuple(out)


def _jsonify(payload: Any) -> Any:
    """Wrap an already-shaped payload in a Flask jsonify response (no envelope)."""
    return jsonify(payload)
