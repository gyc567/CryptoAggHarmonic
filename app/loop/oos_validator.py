"""OOS (out-of-sample) validator.

For a candidate to be admitted to the Pareto front we require that its
OOS quarter (the last quarter in the walk-forward window) be
"consistent" with the in-sample quarters. This module encapsulates the
consistency check.

The contract:

* :func:`oos_validate` takes the in-sample metrics (a list of dicts)
  and the OOS metrics (one dict).
* Returns an :class:`OOSVerdict` with a ``passed`` flag, a list of
  ``reasons``, and a numeric ``robustness`` score (0..1, higher = better).

This is intentionally a separate module from :mod:`app.loop.checker`
(which reviews an *individual* candidate). The OOS check operates on
the *distribution* of metrics across quarters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OOSVerdict:
    """Outcome of an OOS validation check."""

    passed: bool
    robustness: float  # 0..1
    reasons: list[str] = field(default_factory=list)
    in_sample_mean_sharpe: float = 0.0
    oos_sharpe: Optional[float] = None
    oos_trade_count: int = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "robustness": self.robustness,
            "reasons": self.reasons,
            "in_sample_mean_sharpe": self.in_sample_mean_sharpe,
            "oos_sharpe": self.oos_sharpe,
            "oos_trade_count": self.oos_trade_count,
        }


def oos_validate(
    in_sample_metrics: list[dict],
    oos_metrics: dict,
    *,
    min_oos_trade_count: int = 15,
    sharpe_floor: float = 0.0,
    sharpe_drop_tolerance: float = 0.5,
) -> OOSVerdict:
    """Validate that the OOS quarter is consistent with the in-sample ones.

    The check fires on three independent red flags; any one is enough
    to fail the validation:

    1. ``oos_trade_count < min_oos_trade_count``  ⇒ too few trades.
    2. ``oos_sharpe < sharpe_floor``  ⇒ the OOS Sharpe is negative.
    3. ``oos_sharpe < in_sample_mean_sharpe * (1 - sharpe_drop_tolerance)``
       ⇒ the OOS Sharpe is much lower than in-sample.

    ``robustness`` is a 0..1 score computed as:

        robustness = max(0, oos_sharpe / max(in_sample_mean_sharpe, 0.01))

    so a candidate whose OOS matches in-sample gets a high score and one
    whose OOS collapses to zero or below gets 0.
    """
    reasons: list[str] = []
    in_sample_sharpes = [
        m.get("sharpe") or 0.0 for m in in_sample_metrics
    ]
    in_sample_mean = (
        sum(in_sample_sharpes) / len(in_sample_sharpes)
        if in_sample_sharpes else 0.0
    )
    oos_sharpe = oos_metrics.get("sharpe")
    oos_tc = oos_metrics.get("trades_count", 0)

    passed = True

    if oos_tc < min_oos_trade_count:
        passed = False
        reasons.append(
            f"oos trade count {oos_tc} < floor {min_oos_trade_count}"
        )

    if oos_sharpe is None:
        passed = False
        reasons.append("oos sharpe is None")
    elif oos_sharpe < sharpe_floor:
        passed = False
        reasons.append(
            f"oos sharpe {oos_sharpe:+.3f} < floor {sharpe_floor:+.3f}"
        )
    elif oos_sharpe < in_sample_mean * (1 - sharpe_drop_tolerance):
        passed = False
        reasons.append(
            f"oos sharpe {oos_sharpe:+.3f} dropped >"
            f" {sharpe_drop_pct(sharpe_drop_tolerance):.0%} from "
            f"in-sample mean {in_sample_mean:+.3f}"
        )

    # Robustness — ratio of oos to in-sample (clipped 0..1).
    denom = max(in_sample_mean, 0.01)
    if oos_sharpe is None:
        robustness = 0.0
    else:
        robustness = max(0.0, min(1.0, oos_sharpe / denom))

    return OOSVerdict(
        passed=passed,
        robustness=robustness,
        reasons=reasons or ["oos consistent with in-sample"],
        in_sample_mean_sharpe=in_sample_mean,
        oos_sharpe=oos_sharpe,
        oos_trade_count=oos_tc,
    )


def sharpe_drop_pct(t: float) -> float:
    """Convenience: ``sharpe_drop_tolerance=0.5`` → "50% drop"."""
    return t