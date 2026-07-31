"""Leaderboard JSON writer.

v3 changelog item 12 + docs/HarmonicSignal-Bench.md leaderboard schema.

Emits a JSON object with the v3 schema fields. ``comparisons`` and
``low_confidence`` carry the BH-FDR / Wilson-CI outputs from
bench.scoring.confidence.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from bench.scoring.pareto import (
    BENCH_VERSION,
    WEIGHTS_VERSION,
    BenchAugmentedParetoPoint,
)


def leaderboard_dict(
    points: List[BenchAugmentedParetoPoint],
    *,
    low_confidence: bool,
    comparisons: Optional[List[float]] = None,
    warnings: Optional[List[str]] = None,
    exit_code: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the leaderboard JSON document (in-memory)."""
    return {
        "bench_version": BENCH_VERSION,
        "weights_version": WEIGHTS_VERSION,
        "exit_code": exit_code,
        "low_confidence": low_confidence,
        "comparisons": list(comparisons) if comparisons is not None else [],
        "warnings": list(warnings) if warnings is not None else [],
        "n_points": len(points),
        "points": [p.to_dict() for p in points],
        "extra": dict(extra) if extra is not None else {},
    }


def write_leaderboard(
    path: str,
    points: List[BenchAugmentedParetoPoint],
    *,
    low_confidence: bool,
    comparisons: Optional[List[float]] = None,
    warnings: Optional[List[str]] = None,
    exit_code: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialise leaderboard to ``path`` and also return the dict."""
    doc = leaderboard_dict(
        points,
        low_confidence=low_confidence,
        comparisons=comparisons,
        warnings=warnings,
        exit_code=exit_code,
        extra=extra,
    )
    with open(path, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True, default=str)
    return doc


def leaderboard_string(
    points: List[BenchAugmentedParetoPoint],
    **kwargs,
) -> str:
    """Serialise to a string (for tests)."""
    doc = leaderboard_dict(points, **kwargs)
    return json.dumps(doc, indent=2, sort_keys=True, default=str)
