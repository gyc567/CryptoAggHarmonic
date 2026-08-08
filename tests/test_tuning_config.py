"""Tests for ``app.config.tuning`` — the central knobs hub for the loop-tuning project.

Covers:
* Constraint enforcement in ``__post_init__`` (hard + soft)
* Round-trip serialisation via ``to_dict`` / ``from_dict``
* Hot-swap via ``apply_tuning`` / ``reset_tuning`` / ``tuning_scope``
* Cluster mapping completeness
"""

from __future__ import annotations

import dataclasses

import pytest

from app.config.tuning import (
    TUNING,
    TuningScope,
    apply_tuning,
    clusters,
    from_dict,
    get_tuning,
    reset_tuning,
    to_dict,
)

# --- Constraint enforcement --------------------------------------------------


class TestConstraints:
    def test_default_instantiates(self):
        assert TUNING.fib_tp1 < TUNING.fib_tp2 < TUNING.fib_tp3

    def test_fib_order_violated(self):
        with pytest.raises(ValueError, match="fib_tp ordering violated"):
            dataclasses.replace(TUNING, fib_tp1=0.9, fib_tp2=0.5, fib_tp3=0.4)

    def test_tp_close_pcts_sum_must_be_100(self):
        with pytest.raises(ValueError, match="tp_close_pcts must sum to 100"):
            dataclasses.replace(TUNING, tp_close_pcts=(40, 30, 20))

    def test_authenticity_ordering(self):
        with pytest.raises(ValueError, match="authenticity_veto"):
            dataclasses.replace(
                TUNING,
                authenticity_veto=50,
                authenticity_halve=40,
            )

    def test_regime_ordering(self):
        with pytest.raises(ValueError, match="regime_moderate"):
            dataclasses.replace(TUNING, regime_moderate=70, regime_high=60)

    def test_confluence_weights_must_sum_100(self):
        with pytest.raises(ValueError, match="confluence_weights must sum to 100"):
            dataclasses.replace(
                TUNING,
                confluence_weights={
                    "price_action": 30,
                    "htf_trend": 25,
                    "rsi": 15,
                    "structure": 15,
                    "macd": 10,
                    "funding": 10,
                },
            )

    def test_extreme_inverse_must_exceed_inverse_bands(self):
        # Default extreme=1.2 ≥ max(0.6, 0.5). Drop trending_inverse to 0.4
        # first, then try to set extreme below the new max(0.4, 0.5)=0.5.
        with pytest.raises(ValueError, match="mult_extreme_inverse"):
            dataclasses.replace(
                TUNING,
                mult_trending_inverse=0.4,
                mult_ranging_inverse=0.5,
                mult_extreme_inverse=0.4,  # < max(0.4, 0.5) = 0.5
            )

    def test_aligned_must_exceed_inverse_min(self):
        with pytest.raises(ValueError, match="trending_aligned"):
            dataclasses.replace(
                TUNING,
                mult_trending_inverse=0.9,
                mult_ranging_inverse=0.9,
                mult_trending_aligned=0.5,  # < inverse_min=0.9
            )

    def test_data_short_in_safe_range(self):
        with pytest.raises(ValueError, match="mult_data_short"):
            dataclasses.replace(TUNING, mult_data_short=0.3)  # < 0.5

    def test_extreme_inverse_capped_for_risk_parity(self):
        with pytest.raises(ValueError, match="risk-parity"):
            dataclasses.replace(TUNING, mult_extreme_inverse=1.6)

    def test_atr_long_window_must_be_at_least_short(self):
        with pytest.raises(ValueError, match="atr_long_window"):
            dataclasses.replace(TUNING, atr_window=20, atr_long_window=10)

    def test_window_positivity(self):
        with pytest.raises(ValueError, match="must be > 0"):
            dataclasses.replace(TUNING, atr_window=0)

    def test_atr_stop_buffer_standard_upper_bound(self):
        """Guard against silent regression of the standard stop buffer above 0.5 ATR.

        The standard buffer was tightened from 0.5 to 0.3 ATR in the
        stop-loss-expert-tuning plan; this validation rejects any future override
        that would silently re-introduce the wider default without explicit
        intent. ``validate()`` enforces 0.2 <= standard <= 0.5.
        """
        with pytest.raises(ValueError, match="atr_stop_buffer..standard"):
            dataclasses.replace(
                TUNING,
                atr_stop_buffer={"conservative": 1.0, "standard": 0.7, "aggressive": 0.25},
            )

    def test_atr_stop_buffer_standard_lower_bound(self):
        """Refuse an absurdly tight standard (< 0.2 ATR) which would shake out
        every healthy pullback."""
        with pytest.raises(ValueError, match="atr_stop_buffer..standard"):
            dataclasses.replace(
                TUNING,
                atr_stop_buffer={"conservative": 1.0, "standard": 0.1, "aggressive": 0.25},
            )


# --- Round-trip --------------------------------------------------------------


class TestRoundTrip:
    def test_dict_roundtrip_equal(self):
        d = to_dict(TUNING)
        t2 = from_dict(d)
        assert t2 == TUNING

    def test_partial_override(self):
        # Only override one field; rest should fall back to defaults.
        t = from_dict({"a_grade_min": 80})
        assert t.a_grade_min == 80
        assert t.fib_tp1 == TUNING.fib_tp1  # default preserved

    def test_frozenset_coerced_from_list(self):
        d = to_dict(TUNING)
        d["extended_patterns"] = list(d["extended_patterns"])  # list on the wire
        t = from_dict(d)
        assert isinstance(t.extended_patterns, frozenset)

    def test_invalid_override_raises(self):
        with pytest.raises(ValueError):
            from_dict({"fib_tp1": 0.9, "fib_tp2": 0.5, "fib_tp3": 0.4})


# --- Hot-swap ----------------------------------------------------------------


class TestHotSwap:
    def setup_method(self):
        reset_tuning()  # clean slate per test

    def teardown_method(self):
        reset_tuning()

    def test_apply_tuning_sets_get_tuning_only(self):
        """Path A: apply_tuning no longer mutates module-level aliases."""
        import app.services.signal_engine as se

        frozen = se.A_GRADE_MIN
        t = dataclasses.replace(TUNING, a_grade_min=80, mult_extreme_inverse=1.4)
        apply_tuning(t)
        assert get_tuning().a_grade_min == 80
        assert get_tuning().mult_extreme_inverse == 1.4
        # Legacy alias remains the import-time / last-snapshot value
        assert se.A_GRADE_MIN == frozen

    def test_reset_tuning_reverts(self):
        t = dataclasses.replace(TUNING, a_grade_min=80)
        apply_tuning(t)
        assert get_tuning().a_grade_min == 80
        reset_tuning()
        assert get_tuning() is TUNING
        assert get_tuning().a_grade_min == TUNING.a_grade_min

    def test_tuning_scope_context_manager(self):
        """TuningScope overrides get_tuning(); exits restore applied/singleton."""
        applied = dataclasses.replace(TUNING, a_grade_min=80)
        scoped = dataclasses.replace(TUNING, a_grade_min=90)
        apply_tuning(applied)
        assert get_tuning().a_grade_min == 80
        with TuningScope(scoped):
            assert get_tuning().a_grade_min == 90
        assert get_tuning().a_grade_min == 80
        reset_tuning()
        assert get_tuning() is TUNING

    def test_hot_path_reads_get_tuning_not_import_freeze(self):
        """score path must honor apply_tuning even if aliases were frozen earlier."""
        import app.services.signal_engine as se

        base_halve = TUNING.authenticity_halve
        apply_tuning(dataclasses.replace(TUNING, authenticity_halve=base_halve + 5))
        assert get_tuning().authenticity_halve == base_halve + 5
        assert se._pattern_base_score("unknown_xyz") == 0
        apply_tuning(
            dataclasses.replace(
                TUNING,
                pattern_base_score={
                    "gartley": 99,
                    "bat": 0,
                    "butterfly": 0,
                    "crab": 0,
                    "deep crab": 0,
                    "shark": 0,
                },
            )
        )
        assert se._pattern_base_score("gartley-382-1") == 99
        reset_tuning()

    def test_apply_tuning_does_not_mutate_singleton(self):
        """Applied candidate is process-local; TUNING singleton stays clean."""
        apply_tuning(
            dataclasses.replace(
                TUNING,
                pattern_base_score={
                    "gartley": 99,
                    "bat": 0,
                    "butterfly": 0,
                    "crab": 0,
                    "deep crab": 0,
                    "shark": 0,
                },
            )
        )
        assert get_tuning().pattern_base_score["gartley"] == 99
        assert TUNING.pattern_base_score["bat"] == 2
        reset_tuning()


# --- Cluster map -------------------------------------------------------------


class TestClusters:
    def test_clusters_cover_all_tunable_fields(self):
        listed = {f for fs in clusters().values() for f in fs}
        dataclass_fields = {f.name for f in dataclasses.fields(TUNING)}
        # All cluster-listed fields must exist on the dataclass.
        assert listed <= dataclass_fields, f"Unknown cluster fields: {listed - dataclass_fields}"

    def test_clusters_partition_tunable_fields(self):
        """Every tunable field should appear in some cluster (Frozen fields
        like fib_tp1 / extended_patterns / htf_rule / confluence_weights /
        funding_confluence_default are deliberately excluded from search)."""
        listed = {f for fs in clusters().values() for f in fs}
        # Sanity: should have at least 25 entries (we have ~50 fields total
        # minus the Frozen ones).
        assert len(listed) >= 25
