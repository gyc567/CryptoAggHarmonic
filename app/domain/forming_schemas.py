"""Schemas for multi-candidate forming-pattern views.

Wraps a :class:`Candidate` (the upstream-detected harmonic pattern) with the
discipline-filter metrics and macro-overlay that the signal engine computes on
top of it. This is what the dashboard consumes when it shows multiple
forming candidates ranked by grade + distance, rather than the legacy single
"best pattern" view.

Layering (read top-down):

* ``Candidate``             — upstream pyharmonics raw pattern (frozen dataclass
  in :mod:`app.domain.signals`; a third-party object graph we don't own)
* ``CandidateMetrics``      — pure-filter output (stale / past_tp2 / dist_pct)
* ``MacroOverlay``          — daily EMA200-derived size multiplier + advice
* ``CandidateWithMetrics``  — composite view fed to the frontend

Design choice — Pydantic ``BaseModel(frozen=True)`` over ``@dataclass(frozen=True)``:

These models are *internal* (not API-boundary) but they ARE the dashboard's
contract — the dashboard depends on the ``to_dict()`` shape, on default values
rendering safe "active" rows, and on no constructor ever silently mutating
fields. ``BaseModel(frozen=True)`` gives all that plus runtime type coercion
that dataclasses lack, without the friction of API-boundary models
(see ``app.domain.schemas._StrictModel`` for why we don't enable
``strict=True`` / ``extra="forbid"`` everywhere).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.signals import Candidate


class _DomainModel(BaseModel):
    """Base for internal-domain (not API-boundary) Pydantic models.

    ``frozen=True`` so callers can't mutate a ``CandidateMetrics`` after it's
    been attached to a ``CandidateWithMetrics`` — the signal engine builds
    many of these per request and accidental mutation would corrupt the
    orchestrator's view of what got filtered.

    We deliberately do NOT enable:

    * ``strict=True`` — these are constructed from pandas / numeric contexts
      where widening int → float should be silently accepted (e.g. ``bars_since_c``
      as int from a numpy slice vs as int from a plain dict).
    * ``extra="forbid"`` — orchestrator code attaches metadata fields for
      diagnostics. We want the model to *accept* extra fields without raising,
      so the dashboard contract is forward-compatible with new metrics.
    * ``validate_assignment=True`` — frozen already blocks writes.
    """

    model_config = ConfigDict(frozen=True)


class CandidateMetrics(_DomainModel):
    """Discipline-filter metrics for one candidate.

    All fields default to the safe "active" state so callers that haven't run
    the filter yet can still render a row. None means "not computed".
    """

    bars_since_c: int = 0  # bars from C point to the latest bar
    stale: bool = False  # True => TTL exceeded, downgrade not kill
    breached_stop: bool = False  # True => C 点后路径触达 PRZ(形态已走完)
    past_tp2: bool = False  # True => 现价已穿越 TP2(行情结束)
    in_prz: bool = False  # True => 现价落在 PRZ 区间内
    dist_pct: float = 0.0  # 现价到 PRZ 最近边缘距离(% 正数)


class MacroOverlay(_DomainModel):
    """Macro bias layer suggestion for one signal.

    Mirrors the structure produced by :func:`app.services.macro_bias.compute`
    so the frontend can render the size-mult + advice without re-fetching
    the daily close series.
    """

    size_mult: float = 1.0
    advice: str = ""
    macro_dir: str = "unknown"  # 牛市(价>EMA200) / 熊市 / unknown
    signal_vs_macro: str = "unknown"  # 顺势 / 逆势 / unknown
    deviation_pct: float = 0.0
    ema200_slope_20d: float = 0.0


class CandidateWithMetrics(_DomainModel):
    """Composite view: a :class:`Candidate` plus its discipline + macro tags.

    The ``candidate`` field is a frozen dataclass (not Pydantic), so we use
    ``Field(arbitrary_types_allowed=True)`` to declare it without changing the
    upstream :class:`Candidate` shape.
    """

    # ``Candidate`` is a frozen dataclass from app.domain.signals; Pydantic
    # needs an explicit ``arbitrary_types_allowed`` flag to accept it.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    candidate: Candidate
    metrics: CandidateMetrics = Field(default_factory=CandidateMetrics)
    macro: Optional[MacroOverlay] = None

    @property
    def tradable(self) -> bool:
        """Sentinel: a candidate is non-tradable if it's stale, breached, or past TP2.

        Frontend uses this to grey out the row without losing visibility.
        """
        if self.metrics.stale:
            return False
        if self.metrics.breached_stop:
            return False
        if self.metrics.past_tp2:
            return False
        return True

    @property
    def width_pct(self) -> float:
        """PRZ width as a fraction of the mid-price (used by grade())."""
        c = self.candidate
        if c.prz_low <= 0 or c.prz_high <= 0:
            return 0.0
        mid = (c.prz_low + c.prz_high) / 2
        if mid <= 0:
            return 0.0
        return (c.prz_high - c.prz_low) / mid

    def to_dict(self) -> dict[str, Any]:
        """Serialise for API/JSON. Mirrors the subset of fields the dashboard needs."""
        out: dict[str, Any] = {
            "pattern_name": self.candidate.name,
            "family": self.candidate.family,
            "direction": "long" if self.candidate.bullish else "short",
            "formed": self.candidate.formed,
            "prz_low": self.candidate.prz_low,
            "prz_high": self.candidate.prz_high,
            "bars_since_c": self.metrics.bars_since_c,
            "stale": self.metrics.stale,
            "breached_stop": self.metrics.breached_stop,
            "past_tp2": self.metrics.past_tp2,
            "in_prz": self.metrics.in_prz,
            "dist_pct": self.metrics.dist_pct,
            "width_pct": self.width_pct,
            "tradable": self.tradable,
        }
        if self.macro is not None:
            out["macro"] = {
                "size_mult": self.macro.size_mult,
                "advice": self.macro.advice,
                "macro_dir": self.macro.macro_dir,
                "signal_vs_macro": self.macro.signal_vs_macro,
                "deviation_pct": self.macro.deviation_pct,
                "ema200_slope_20d": self.macro.ema200_slope_20d,
            }
        return out
