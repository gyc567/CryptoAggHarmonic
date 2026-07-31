"""SignalRecord — the row type for the bench dataset.

Mirrors docs/HarmonicSignal-Bench.md SignalRecord (v3). Field types
intentionally permissive (``str | None``, ``float | None``) so the
record can be built incrementally as pipeline stages fill in the
extended trade metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Literal, Optional

Direction = Literal["long", "short"]
Grade = Literal["A", "B", "C"]
Split = Literal["is", "oos"]
Outcome = Literal[
    "tp3", "tp2", "tp1", "breakeven", "stoploss", "expired", "incomplete"
]


@dataclass
class SignalRecord:
    # === identity ===
    signal_id: str
    run_id: str
    params_sha: str

    # === signal attributes ===
    timestamp: str  # ISO 8601
    symbol: str
    timeframe: str
    pattern_type: str
    pattern_family: str
    direction: Direction
    grade: Grade

    # === prices ===
    entry_price: float
    stop_price: float
    tp1: float
    tp2: float
    tp3: float
    atr_at_entry: float
    prz_width_atr: float
    entry_offset_atr: float = 0.0

    # === existing engine output ===
    confluence_score: float = 0.0
    pattern_base_score: float = 0.0
    stability_verdict: str = ""
    regime: str = ""
    volume_authenticity_score: float = 0.0

    # === trade outcome (filled by stage2) ===
    outcome: Optional[Outcome] = None
    net_rr: Optional[float] = None
    bars_held: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    # === extended trade metrics (filled by trade_metrics) ===
    mae: Optional[float] = None
    mfe: Optional[float] = None
    mae_atr_ratio: Optional[float] = None
    mfe_atr_ratio: Optional[float] = None
    callback_depth: Optional[float] = None
    callback_bars: Optional[int] = None
    callback_volume_ratio: Optional[float] = None
    hit_stop_before_tp: Optional[bool] = None
    stop_zone_touches: Optional[int] = None
    price_efficiency: Optional[float] = None

    # === walk-forward labels ===
    split: Optional[Split] = None
    crosses_boundary: bool = False
    boundary_distance_bars: Optional[int] = None
    weak_validity: bool = False

    # === ai judge output ===
    ai_score: Optional[float] = None
    ai_reasoning: Optional[str] = None
    ai_agreement: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_degraded: bool = False

    # === bench scores (filled by pipeline stages) ===
    stage1_score: Optional[float] = None
    stage3_score: Optional[float] = None
    stage4a_score: Optional[float] = None
    stage4b_score: Optional[float] = None
    stage4c_score: Optional[float] = None
    signal_score: Optional[float] = None
    config_score: Optional[float] = None
    bench_total: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly dict (no nested objects)."""
        return asdict(self)


def empty_record(**overrides: Any) -> SignalRecord:
    """Build a SignalRecord with safe defaults for tests / fixtures.

    Required identity + price fields are filled with placeholder strings
    or NaN-safe values; everything else defaults to 0 / None.
    """
    base: Dict[str, Any] = dict(
        signal_id="sid_test",
        run_id="rid_test",
        params_sha="paramsha_test",
        timestamp="2026-07-30T00:00:00Z",
        symbol="BTCUSDT",
        timeframe="4h",
        pattern_type="gartley",
        pattern_family="XABCD",
        direction="long",
        grade="C",
        entry_price=100.0,
        stop_price=95.0,
        tp1=110.0,
        tp2=115.0,
        tp3=120.0,
        atr_at_entry=2.0,
        prz_width_atr=0.3,
        entry_offset_atr=0.0,
    )
    base.update(overrides)
    return SignalRecord(**base)
