"""TuningConstants: single source of truth for harmonic-signal pipeline knobs.

Every constant formerly scattered across ``app/domain/signals.py``,
``app/domain/validation.py``, ``app/services/signal_engine.py``,
``app/services/discipline_filters.py`` and ``app/services/macro_bias.py`` lives
here. Code reads values through the module-level ``TUNING`` singleton; the
previous module-level aliases (``MAX_D_AGE_BARS``, ``ATR_STOP_BUFFER`` …) are
re-exported from the owning modules so existing tests keep working unchanged.

The dataclass is ``frozen=True`` — instances are immutable. Loop-tuning mutates
via :func:`dataclasses.replace`, which produces a new instance whose
``__post_init__`` re-runs the validation. Hard constraints raise on
construction; soft constraints are also enforced in ``__post_init__`` because
they're cheap to check and the loop should fail-fast rather than discover
incoherence at the end of a 15-minute backtest.

**Cluster tags** (used by per-cluster search):

* ``C1 Geometry``   — Fibonacci TPs, ATR buffers, PRZ sweep, fee/slippage
* ``C2 Discipline`` — staleness gates, authenticity vetoes, adverse-momentum
* ``C3 Confluence`` — grade thresholds, A-grade gating, scoring weights,
                       pattern-reliability bumps
* ``C4 Macro``      — EMA slope bands, position-size multiplier policy
* ``C5 Windows``    — feature-calculation lookbacks (ATR / RSI / volume / etc.)

Fields tagged **Frozen** are NOT meant to be touched by the search loop. They
are either structural invariants (``fib_tp*``, ``extended_patterns``),
depend on data we don't yet have (``funding_confluence_default``), or are
out-of-scope for the current search (RSI trend subsystem).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Mapping


# Hard-coded families the stop-placement algorithm needs to special-case.
# Keep in sync with tests/test_signal_engine.py::_pattern_base_score.
_REQUIRED_EXTENDED_FAMILIES: FrozenSet[str] = frozenset(
    {"butterfly", "deep butterfly", "crab", "deep crab", "shark", "deep shark"}
)

# Required keys in PATTERN_BASE_SCORE. Loop never removes entries, only bumps.
_REQUIRED_PATTERN_FAMILIES: FrozenSet[str] = frozenset(
    {"gartley", "bat", "butterfly", "crab", "deep crab", "shark"}
)

# Required keys in CONFLUENCE_WEIGHTS and the sum of their values (must be 100).
_REQUIRED_CONFLUENCE_KEYS: FrozenSet[str] = frozenset(
    {"price_action", "htf_trend", "rsi", "structure", "macd", "funding"}
)

# Allowed stop-loss risk levels — stop-placement logic branches on these.
_REQUIRED_STOP_LOSS_LEVELS: FrozenSet[str] = frozenset(
    {"conservative", "standard", "aggressive"}
)

# Required HTF rule keys (matches Interval enum values used in production).
_REQUIRED_HTF_KEYS: FrozenSet[str] = frozenset({"15m", "1h", "4h", "1d", "1w"})


@dataclass(frozen=True)
class TuningConstants:
    """Immutable bundle of every tunable knob in the harmonic pipeline.

    Construction validates hard + soft constraints. Use
    :func:`dataclasses.replace(tuning, field=value)` to derive a mutated copy;
    the resulting instance re-runs ``__post_init__`` and raises on any
    constraint violation.
    """

    # ===== C1 Geometry (signals.py) ==========================================

    # Frozen — geometric invariants: TP1 < TP2 < TP3 by definition of fib retraces.
    fib_tp1: float = 0.382
    fib_tp2: float = 0.618
    fib_tp3: float = 1.272

    # Frozen — extended patterns require a special stop rule (X is not the
    # invalidation anchor for butterfly/crab/shark). Mutating this would
    # invalidate the stop algorithm in compute_stop().
    extended_patterns: FrozenSet[str] = field(
        default_factory=lambda: frozenset(_REQUIRED_EXTENDED_FAMILIES)
    )

    # Frozen — must cover every Interval enum value so htf_trend() never
    # returns "unknown" silently in production.
    htf_rule: Mapping[str, str] = field(
        default_factory=lambda: {
            "15m": "1h",
            "1h": "4h",
            "4h": "1D",
            "1d": "1W",
            "1w": "1ME",
        }
    )

    # Tunable — ATR buffer for the 3 stop-loss levels. Higher = wider stop.
    atr_stop_buffer: Mapping[str, float] = field(
        default_factory=lambda: {"conservative": 1.0, "standard": 0.5, "aggressive": 0.25}
    )

    # Tunable — within this ATR distance of the PRZ mid counts as "at the zone"
    # for the structure-confluence factor.
    atr_prz_sweep: float = 0.3

    # Tunable — close percentages for the 3 take-profit legs (must sum to 100).
    tp_close_pcts: tuple = (50, 30, 20)

    # Tunable — Binance USDT-M taker fee, both sides.
    fee_rate: float = 0.001

    # Tunable — slippage allowance in fractional price terms.
    slippage_rate: float = 0.0005

    # ===== C2 Discipline (validation.py + discipline_filters.py) =============

    # Tunable — bars between price and PRZ beyond which the candidate is stale.
    max_d_age_bars: int = 20

    # Tunable — |price − PRZ mid| beyond this ATR multiple ⇒ stale_distance.
    max_prz_distance_atr: float = 3.0

    # Tunable — forming PRZ wider than this ATR multiple ⇒ degenerate.
    max_forming_prz_width_atr: float = 1.0

    # Tunable — volume authenticity below halve ⇒ price-action score * 0.5.
    authenticity_halve: int = 40

    # Tunable — volume authenticity below veto ⇒ reject the candidate outright.
    authenticity_veto: int = 25

    # Tunable — per-bar Sharpe |x| above this in adverse direction ⇒ momentum veto.
    adverse_sharpe_threshold: float = 1.0

    # Tunable — quant-regime score thresholds for regime bucketing.
    regime_moderate: int = 35
    regime_high: int = 60

    # Tunable — anchor ATR% used by volatility targeting (each trade carries
    # roughly this much volatility).
    target_atr_pct: float = 2.5

    # Tunable — forming-pattern TTL anchored at the C point. Independently
    # maintained from max_d_age_bars (which is anchored at D).
    default_ttl_bars: int = 40

    # ===== C3 Confluence (signal_engine.py) ==================================

    # Frozen — funding confluence weight when we have no futures feed. Setting
    # this requires funding data we don't yet collect; keep at 5 (neutral half).
    funding_confluence_default: int = 5

    # Tunable — confluence component weights. Must sum to 100.
    confluence_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "price_action": 25,
            "htf_trend": 25,
            "rsi": 15,
            "structure": 15,
            "macd": 10,
            "funding": 10,  # falls back to funding_confluence_default when no data
        }
    )

    # Tunable — minimum confluence to grade an A in normal regime.
    a_grade_min: int = 75

    # Tunable — stricter A-grade floor under high-quant regime.
    a_grade_min_high_quant: int = 85

    # Tunable — position multiplier applied when regime == "high_quant".
    high_quant_position_mult: float = 0.6

    # Tunable — per-family reliability bump. Loop never removes entries.
    pattern_base_score: Mapping[str, int] = field(
        default_factory=lambda: {
            "gartley": +5,
            "bat": +2,
            "butterfly": 0,
            "crab": -3,
            "deep crab": -5,
            "shark": -8,
        }
    )

    # Tunable — sub-window re-detection guard window for stability_verdict.
    stability_window: int = 5

    # ===== C3/C5 Confluence + Windows =========================================

    # Tunable — minimum candles required for the signal pipeline to run.
    min_candles: int = 60

    # Tunable — Wilder / rolling windows.
    atr_window: int = 14
    atr_long_window: int = 100
    rsi_window: int = 14
    volume_ma_window: int = 20
    swing_lookback: int = 60

    # Tunable — secondary-feature lookbacks.
    quant_trap_lookback: int = 60
    volume_authenticity_window: int = 60
    quant_regime_window: int = 100
    per_bar_sharpe_window: int = 20

    # ===== C4 Macro (macro_bias.py) ============================================

    # Tunable — slope thresholds (% over 20 daily bars) for trending vs ranging.
    slope_trend_up: float = 0.5
    slope_trend_down: float = -0.5

    # Tunable — position-size multipliers per regime-alignment combination.
    # Soft constraints enforce: extreme ≥ max(trending_inverse, ranging_inverse)
    # and data_short ≤ all other bands.
    mult_trending_aligned: float = 1.0
    mult_ranging_aligned: float = 1.0
    mult_trending_inverse: float = 0.6
    mult_ranging_inverse: float = 0.5
    mult_extreme_inverse: float = 1.2
    mult_data_short: float = 0.8

    # Tunable — deviation beyond which the inverse signal is flagged "extreme".
    extreme_deviation_pct: float = 20.0

    # Tunable — minimum daily bars required for macro computation; below this
    # the overlay returns the data_short multiplier.
    min_daily_bars: int = 210

    def __post_init__(self) -> None:
        """Fail-fast on constraint violations. Cheap checks only."""
        # ---- Hard constraints ------------------------------------------------

        # C1 — Fibonacci retracement ordering.
        if not (self.fib_tp1 < self.fib_tp2 < self.fib_tp3):
            raise ValueError(
                f"fib_tp ordering violated: "
                f"{self.fib_tp1} < {self.fib_tp2} < {self.fib_tp3}"
            )

        # C1 — TP close percentages must cover all three legs.
        if sum(self.tp_close_pcts) != 100:
            raise ValueError(
                f"tp_close_pcts must sum to 100, got {sum(self.tp_close_pcts)}"
            )

        # C2 — Authenticity ordering (veto must be stricter than halve).
        if not (self.authenticity_veto < self.authenticity_halve):
            raise ValueError(
                f"authenticity_veto ({self.authenticity_veto}) must be < "
                f"authenticity_halve ({self.authenticity_halve})"
            )

        # C2 — Regime ordering.
        if not (self.regime_moderate < self.regime_high):
            raise ValueError(
                f"regime_moderate ({self.regime_moderate}) must be < "
                f"regime_high ({self.regime_high})"
            )

        # C3 — Confluence weights must sum to 100 and contain all required keys.
        weight_sum = sum(self.confluence_weights.values())
        if abs(weight_sum - 100) > 1e-6:
            raise ValueError(
                f"confluence_weights must sum to 100, got {weight_sum}"
            )
        missing = _REQUIRED_CONFLUENCE_KEYS - set(self.confluence_weights.keys())
        if missing:
            raise ValueError(f"confluence_weights missing keys: {sorted(missing)}")

        # C1 — extended_patterns must contain every required family (otherwise
        # the stop-placement algorithm misroutes).
        missing_families = _REQUIRED_EXTENDED_FAMILIES - set(self.extended_patterns)
        if missing_families:
            raise ValueError(
                f"extended_patterns missing required families: "
                f"{sorted(missing_families)}"
            )

        # C1 — atr_stop_buffer must define every risk level.
        missing_levels = _REQUIRED_STOP_LOSS_LEVELS - set(self.atr_stop_buffer.keys())
        if missing_levels:
            raise ValueError(
                f"atr_stop_buffer missing levels: {sorted(missing_levels)}"
            )

        # C1 — htf_rule must cover every supported interval.
        missing_intervals = _REQUIRED_HTF_KEYS - set(self.htf_rule.keys())
        if missing_intervals:
            raise ValueError(
                f"htf_rule missing intervals: {sorted(missing_intervals)}"
            )

        # C3 — pattern_base_score must include the canonical family set.
        missing_pat = _REQUIRED_PATTERN_FAMILIES - set(self.pattern_base_score.keys())
        if missing_pat:
            raise ValueError(
                f"pattern_base_score missing families: {sorted(missing_pat)}"
            )

        # ---- Soft monotonicity (C4 macro policy coherence) --------------------

        # extreme must be >= the inverse bands (extreme-deviation inversions
        # are the highest-conviction mean-reversion entries).
        inverse_max = max(self.mult_trending_inverse, self.mult_ranging_inverse)
        if self.mult_extreme_inverse < inverse_max:
            raise ValueError(
                f"mult_extreme_inverse ({self.mult_extreme_inverse}) must be >= "
                f"max(trending_inverse, ranging_inverse) = {inverse_max}"
            )

        # aligned bands must be >= inverse bands (no reason to size down an
        # aligned signal more than a counter-trend one).
        inverse_min = min(self.mult_trending_inverse, self.mult_ranging_inverse)
        for name, val in (
            ("mult_trending_aligned", self.mult_trending_aligned),
            ("mult_ranging_aligned", self.mult_ranging_aligned),
        ):
            if val < inverse_min:
                raise ValueError(
                    f"{name} ({val}) must be >= min(inverse bands) = {inverse_min}"
                )

        # data_short is a "don't know" fallback (insufficient daily data).
        # It must sit in the cautious-but-not-floor range [0.5, 1.0] — a real
        # signal always gets a tighter or larger mult than "we have no data".
        if not (0.5 <= self.mult_data_short <= 1.0):
            raise ValueError(
                f"mult_data_short ({self.mult_data_short}) must lie in [0.5, 1.0]"
            )

        # Risk-parity ceiling: the extreme-inverse band is the only one that
        # can exceed 1.0; clamp it so vol_mult * regime_mult * macro_mult <= 1.5
        # for any single trade (regime/vol mults are independently <= 1.5).
        if self.mult_extreme_inverse > 1.5:
            raise ValueError(
                f"mult_extreme_inverse ({self.mult_extreme_inverse}) > 1.5 "
                f"violates risk-parity product ceiling"
            )

        # ---- Window positivity ------------------------------------------------
        int_fields = (
            self.max_d_age_bars,
            self.default_ttl_bars,
            self.atr_window,
            self.atr_long_window,
            self.rsi_window,
            self.volume_ma_window,
            self.swing_lookback,
            self.stability_window,
            self.min_candles,
            self.min_daily_bars,
            self.quant_trap_lookback,
            self.volume_authenticity_window,
            self.quant_regime_window,
            self.per_bar_sharpe_window,
            self.authenticity_halve,
            self.authenticity_veto,
            self.regime_moderate,
            self.regime_high,
            self.a_grade_min,
            self.a_grade_min_high_quant,
        )
        for v in int_fields:
            if v <= 0:
                raise ValueError(f"window/grade field must be > 0, got {v}")

        # ATR long window must be >= ATR short window (the robust-ATR formula
        # uses min(short, long), so flipping them is a silent bug).
        if self.atr_long_window < self.atr_window:
            raise ValueError(
                f"atr_long_window ({self.atr_long_window}) must be >= "
                f"atr_window ({self.atr_window})"
            )


# Singleton — read this from anywhere in the codebase.
TUNING: TuningConstants = TuningConstants()


def clusters() -> dict[str, tuple[str, ...]]:
    """Return the cluster → field-name mapping used by per-cluster search.

    Field names here MUST match the dataclass attribute names exactly. The
    loop-tuning project freezes all clusters except one before each
    generation; missing this annotation causes silent "tuning did nothing".
    """
    return {
        "C1 Geometry": (
            "atr_stop_buffer",
            "atr_prz_sweep",
            "tp_close_pcts",
            "fee_rate",
            "slippage_rate",
        ),
        "C2 Discipline": (
            "max_d_age_bars",
            "max_prz_distance_atr",
            "max_forming_prz_width_atr",
            "authenticity_halve",
            "authenticity_veto",
            "adverse_sharpe_threshold",
            "regime_moderate",
            "regime_high",
            "target_atr_pct",
            "default_ttl_bars",
        ),
        "C3 Confluence": (
            "confluence_weights",
            "a_grade_min",
            "a_grade_min_high_quant",
            "high_quant_position_mult",
            "pattern_base_score",
            "stability_window",
            "min_candles",
            "atr_window",
            "atr_long_window",
            "rsi_window",
            "volume_ma_window",
            "swing_lookback",
        ),
        "C4 Macro": (
            "slope_trend_up",
            "slope_trend_down",
            "mult_trending_aligned",
            "mult_ranging_aligned",
            "mult_trending_inverse",
            "mult_ranging_inverse",
            "mult_extreme_inverse",
            "mult_data_short",
            "extreme_deviation_pct",
            "min_daily_bars",
        ),
        "C5 Windows": (
            "quant_trap_lookback",
            "volume_authenticity_window",
            "quant_regime_window",
            "per_bar_sharpe_window",
        ),
    }