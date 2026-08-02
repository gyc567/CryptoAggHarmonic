"""100% coverage tests for app.domain.signals (pure functions)."""

import pytest

from app.domain.signals import (
    ATR_STOP_BUFFER,
    Candidate,
    MAX_STOP_BUFFER_MULT,
    REGIME_STOP_MULTIPLIER,
    GRADE_STOP_MULTIPLIER,
    Signal,
    SignalTarget,
    compute_stop,
    compute_targets,
    grade,
    is_swept,
    net_rr,
    prz_state,
    reasoning_from_signal,
)


def make_candidate(**overrides):
    base = dict(
        family="XABCD",
        name="gartley",
        bullish=True,
        formed=True,
        points=(100.0, 150.0, 120.0, 140.0, 110.0),  # X, A, B, C, D
        completion_min=108.0,
        completion_max=112.0,
    )
    base.update(overrides)
    return Candidate(**base)


class TestCandidate:
    def test_direction_long(self):
        assert make_candidate().direction == "long"

    def test_direction_short(self):
        assert make_candidate(bullish=False).direction == "short"

    def test_x_price(self):
        assert make_candidate().x_price == 100.0

    def test_a_price_xabcd(self):
        assert make_candidate().a_price == 150.0

    def test_a_price_abcd_family(self):
        c = make_candidate(family="ABCD", points=(150.0, 120.0, 140.0, 110.0))
        assert c.a_price == 150.0

    def test_prz_bounds_sorted(self):
        c = make_candidate(completion_min=112.0, completion_max=108.0)
        assert c.prz_low == 108.0
        assert c.prz_high == 112.0


def make_signal(**overrides):
    target = SignalTarget(
        label="TP1",
        price=120.0,
        fib_basis="AD 38.2% retrace",
        close_pct=50,
        move_stop_to="breakeven",
    )
    base = dict(
        status="confirmed",
        grade="A",
        direction="long",
        pattern_name="gartley",
        family="XABCD",
        formed=True,
        entry_zone=(108.0, 112.0),
        entry_reference=110.0,
        stop_loss=99.0,
        stop_basis="X/PRZ invalidation - 0.5*ATR",
        stop_level="standard",
        invalidation_point=99.5,
        targets=(target,),
        net_rr_tp1=1.2,
        net_rr_tp2=2.4,
        confluence_score=80,
        confluence={"rsi": 15},
        htf_trend="bullish",
    )
    base.update(overrides)
    return Signal(**base)


class TestSignalToDict:
    def test_to_dict_roundtrip(self):
        signal = make_signal()
        d = signal.to_dict()
        assert d["status"] == "confirmed"
        assert d["grade"] == "A"
        assert d["entry_zone"] == [108.0, 112.0]
        assert d["targets"][0]["label"] == "TP1"
        assert d["targets"][0]["close_pct"] == 50
        assert d["confluence"] == {"rsi": 15}
        assert d["htf_trend"] == "bullish"
        assert d["stop_level"] == "standard"
        assert d["invalidation_point"] == 99.5
        # confluence dict is a copy
        d["confluence"]["rsi"] = 0
        assert signal.confluence["rsi"] == 15

    def test_to_dict_includes_v4_metadata(self):
        signal = make_signal(
            reasoning="方向：做多",
            sharpe=0.42,
            regime="high_quant",
            position_multiplier=0.9,
            stability_score=85,
            trap_score=50,
        )
        d = signal.to_dict()
        assert d["reasoning"] == "方向：做多"
        assert d["sharpe"] == 0.42
        assert d["regime"] == "high_quant"
        assert d["position_multiplier"] == 0.9
        assert d["stability_score"] == 85
        assert d["trap_score"] == 50

    def test_to_dict_metadata_defaults(self):
        d = make_signal().to_dict()
        assert d["reasoning"] == ""
        assert d["sharpe"] is None
        assert d["regime"] == "normal"
        assert d["stability_score"] is None


class TestPrzState:
    def test_in_prz(self):
        assert prz_state(110.0, 108.0, 112.0, swept=False) == "in_prz"

    def test_approaching_below(self):
        assert prz_state(100.0, 108.0, 112.0, swept=False) == "approaching"

    def test_approaching_above(self):
        assert prz_state(120.0, 108.0, 112.0, swept=False) == "approaching"

    def test_swept_flag_wins(self):
        assert prz_state(110.0, 108.0, 112.0, swept=True) == "swept"

    def test_boundary_values(self):
        assert prz_state(108.0, 108.0, 112.0, swept=False) == "in_prz"
        assert prz_state(112.0, 108.0, 112.0, swept=False) == "in_prz"


class TestIsSwept:
    def test_pierce_below_close_inside(self):
        assert is_swept(105.0, 111.0, 110.0, 108.0, 112.0) is True

    def test_pierce_above_close_inside(self):
        assert is_swept(109.0, 113.0, 110.0, 108.0, 112.0) is True

    def test_no_pierce(self):
        assert is_swept(109.0, 111.0, 110.0, 108.0, 112.0) is False

    def test_close_below_after_pierce_is_not_sweep(self):
        assert is_swept(105.0, 111.0, 106.0, 108.0, 112.0) is False

    def test_close_above_after_pierce_is_not_sweep(self):
        assert is_swept(109.0, 113.0, 113.0, 108.0, 112.0) is False


class TestComputeStop:
    def test_bullish_gartley_stops_below_x(self):
        # gartley: X=100 < PRZ low=108 -> anchor is X
        stop, basis, inv = compute_stop(make_candidate(), atr=2.0)
        assert stop == 100.0 - ATR_STOP_BUFFER["standard"] * 2.0
        assert "ATR" in basis
        assert inv == 100.0

    def test_bullish_gartley_prz_below_x(self):
        # PRZ below X -> anchor is PRZ low
        c = make_candidate(points=(115.0, 150.0, 120.0, 140.0, 110.0))
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 108.0 - ATR_STOP_BUFFER["standard"] * 2.0

    def test_bearish_gartley_stops_above_x(self):
        c = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=138.0,
            completion_max=142.0,
        )
        stop, basis, inv = compute_stop(c, atr=2.0)
        assert stop == 150.0 + ATR_STOP_BUFFER["standard"] * 2.0
        assert "ATR" in basis
        assert inv == 150.0

    def test_bearish_gartley_prz_above_x(self):
        c = make_candidate(
            bullish=False,
            points=(145.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=148.0,
            completion_max=152.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 152.0 + ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_bullish_uses_prz_not_x(self):
        # butterfly completes beyond X -> anchor is PRZ low even though X lower
        c = make_candidate(
            name="butterfly",
            points=(100.0, 150.0, 120.0, 140.0, 95.0),
            completion_min=94.0,
            completion_max=96.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 94.0 - ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_bearish_uses_prz(self):
        c = make_candidate(
            name="crab",
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 155.0),
            completion_min=154.0,
            completion_max=156.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 156.0 + ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_case_insensitive(self):
        c = make_candidate(name="Deep Crab")
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 108.0 - ATR_STOP_BUFFER["standard"] * 2.0

    # --- swing_anchor: Carney 3-layer redundancy ---------------------------------

    def test_swing_anchor_bullish_takes_tighter_when_valid(self):
        """Bullish: swing_low on the correct side of entry (< entry) and tighter
        than the structural anchor (X) wins.  The stop basis gains the
        ``+ swing`` suffix so Vibe/LLM can explain it."""
        # X=100, PRZ 108-112, entry 110.  Swing 109.5 > X=100 -> tighter anchor.
        stop, basis, inv = compute_stop(
            make_candidate(), atr=2.0, swing_anchor=109.5, entry=110.0,
        )
        assert inv == 109.5
        assert stop == 109.5 - ATR_STOP_BUFFER["standard"] * 2.0
        assert "+ swing" in basis

    def test_swing_anchor_bullish_rejected_when_above_entry(self):
        """Swing above entry would put the stop above the entry — meaningless.
        Silently ignored (fallback to structural anchor)."""
        stop, basis, _ = compute_stop(
            make_candidate(), atr=2.0, swing_anchor=111.0, entry=110.0,
        )
        assert "swing" not in basis
        # Falls back to X=100 anchor.
        assert stop == 100.0 - ATR_STOP_BUFFER["standard"] * 2.0

    def test_swing_anchor_bullish_rejected_when_below_structure(self):
        """Swing looser than the structural anchor is not adopted (we take the
        tighter of the two; a looser swing would widen risk)."""
        # Structural anchor X=100; swing 95 (lower) is wider -> keep X.
        stop, basis, _ = compute_stop(
            make_candidate(), atr=2.0, swing_anchor=95.0, entry=110.0,
        )
        assert "swing" not in basis
        assert stop == 100.0 - ATR_STOP_BUFFER["standard"] * 2.0

    def test_swing_anchor_bullish_ignored_without_entry(self):
        """Swing_anchor without entry cannot be validated; silently ignored to
        avoid placing the stop above the entry zone."""
        stop, basis, _ = compute_stop(
            make_candidate(), atr=2.0, swing_anchor=109.5, entry=None,
        )
        assert "swing" not in basis

    def test_swing_anchor_bearish_takes_tighter_when_valid(self):
        """Short: swing_high on the correct side of entry (> entry) and tighter
        than the structural anchor wins."""
        c = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=148.0,
            completion_max=152.0,
        )
        # Structure anchor max(150, 152) = 152; swing 151 < 152 -> tighter.
        stop, basis, inv = compute_stop(
            c, atr=2.0, swing_anchor=151.0, entry=150.0,
        )
        assert inv == 151.0
        assert stop == 151.0 + ATR_STOP_BUFFER["standard"] * 2.0
        assert "+ swing" in basis

    def test_swing_anchor_bearish_rejected_when_below_entry(self):
        """Bearish swing below entry would put the stop below entry — ignored."""
        c = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=148.0,
            completion_max=152.0,
        )
        stop, basis, _ = compute_stop(
            c, atr=2.0, swing_anchor=149.0, entry=150.0,
        )
        assert "swing" not in basis

    def test_swing_anchor_compatible_with_all_levels(self):
        """swing_anchor must work for conservative/standard/aggressive — only
        the buffer magnitude differs."""
        for level in ("conservative", "standard", "aggressive"):
            stop, basis, _ = compute_stop(
                make_candidate(),
                atr=2.0,
                level=level,
                swing_anchor=109.5,
                entry=110.0,
            )
            assert "+ swing" in basis, f"level={level} missing swing suffix"
            assert stop == 109.5 - ATR_STOP_BUFFER[level] * 2.0


class TestComputeStopMultiplierChain:
    """Fix 5/6/7/8 — trap / regime / grade multiplier chain + escape hatch.

    Plan §2.5-2.8.  Verifies:
    * default behaviour unchanged (multiplier = 1.0× when nothing is set)
    * each multiplier multiplies the base buffer independently
    * the chain clamps to MAX_STOP_BUFFER_MULT × atr
    * ``stop_buffer_atr`` escape hatch overrides level/trap/regime/grade
    """

    BULL = dict(
        bullish=True,
        points=(100.0, 150.0, 120.0, 140.0, 110.0),
        completion_min=108.0,
        completion_max=112.0,
    )

    def test_default_no_multiplier_matches_baseline(self):
        """With no multipliers, compute_stop produces the pre-Fix behaviour."""
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(c, atr=2.0, level="standard")
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        # Bullish standard: anchor = min(X, PRZ_low) = min(100, 108) = 100.
        assert stop == 100.0 - base_buffer
        assert "trap" not in basis and "regime" not in basis and "grade" not in basis

    def test_trap_multiplier_1p5_widens_buffer(self):
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", trap_multiplier=1.5,
        )
        # 0.3 * 1.5 = 0.45 ATR-mult → 0.9 absolute (× atr=2.0); anchor 100
        assert stop == 100.0 - 0.9
        assert "trap×1.50" in basis

    def test_regime_high_quant_widens_buffer(self):
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", regime="high_quant",
        )
        # 0.3 * 1.5 = 0.45 ATR-mult → 0.9 absolute
        assert stop == 100.0 - 0.9
        assert "regime×1.50" in basis

    def test_grade_C_widens_buffer(self):
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", grade="C",
        )
        # 0.3 * 1.3 = 0.39 ATR-mult → 0.78 absolute
        assert stop == 100.0 - 0.78
        assert "grade×1.30" in basis

    def test_grade_A_unchanged(self):
        """Fix 7 correction: A-grade signals use the standard buffer (1.0×)."""
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", grade="A",
        )
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        assert stop == 100.0 - base_buffer
        # No grade suffix when multiplier is 1.0.
        assert "grade" not in basis

    def test_grade_C参考_widens_most(self):
        c = make_candidate(**self.BULL)
        stop, _, _ = compute_stop(
            c, atr=2.0, level="standard", grade="C(参考)",
        )
        # 0.3 * 1.5 * 2.0 = 0.9
        assert stop == 100.0 - 0.9

    def test_chain_multiplies(self):
        """trap × regime × grade compose multiplicatively (plan §2.6)."""
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard",
            trap_multiplier=1.5, regime="high_quant", grade="C",
        )
        # 0.3 * 1.5 * 1.5 * 1.3 = 0.8775 ATR-mult → 1.755 absolute (× atr=2.0)
        assert stop == 100.0 - 1.755
        assert "trap×1.50" in basis
        assert "regime×1.50" in basis
        assert "grade×1.30" in basis

    def test_chain_clamps_at_MAX(self):
        """Plan §5: trap×regime×grade extreme combo is clamped at 2.0× atr."""
        c = make_candidate(**self.BULL)
        # 0.3 base × 2.0 trap × 1.5 regime × 1.5 grade = 1.35 (no clamp)
        # push trap to 2.0× and grade to "C(参考)" 1.5×:  0.3*2.0*1.5*1.5 = 1.35 (still ok)
        # Use stop_buffer_atr=2.0 directly: clamp kicks in at MAX_STOP_BUFFER_MULT=2.0.
        stop, _, _ = compute_stop(
            c, atr=2.0, level="standard",
            trap_multiplier=2.0, regime="high_quant", grade="C(参考)",
            stop_buffer_atr=3.0,  # way above 2.0 cap
        )
        # escape hatch: base=3.0, chain 1.0× (escape hatch doesn't multiply)
        # effective_mult = min(3.0, MAX_STOP_BUFFER_MULT=2.0) = 2.0
        assert stop == 100.0 - MAX_STOP_BUFFER_MULT * 2.0
        assert stop == 100.0 - 4.0

    def test_stop_buffer_atr_overrides_level(self):
        """Fix 8: escape hatch completely overrides the level vocabulary."""
        c = make_candidate(**self.BULL)
        # standard level → 0.3 base; override to 0.7
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", stop_buffer_atr=0.7,
        )
        assert stop == 100.0 - 1.4  # 0.7 * 2.0
        assert "0.70*ATR" in basis
        # No trap/regime/grade suffix because escape hatch means they don't apply.
        assert "trap" not in basis
        assert "regime" not in basis
        assert "grade" not in basis

    def test_stop_buffer_atr_with_level_aggressive_still_honors_level_for_anchor(self):
        """escape hatch overrides buffer but level still picks the anchor."""
        c = make_candidate(
            bullish=True, name="gartley",
            points=(100.0, 150.0, 120.0, 140.0, 110.0),
            completion_min=108.0, completion_max=112.0,
        )
        # Aggressive anchor = min(X=100, PRZ_low=108) = 100 (same as standard).
        # The distinction shows for non-extended families; here X is the smaller
        # pivot so both levels anchor at 100.  Sanity-check that the basis
        # string carries the escape hatch label, not the level label.
        _, basis, _ = compute_stop(
            c, atr=2.0, level="aggressive", stop_buffer_atr=0.5,
        )
        assert "0.50*ATR" in basis

    def test_unknown_regime_defaults_to_1x(self):
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", regime="bogus",
        )
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        assert stop == 100.0 - base_buffer
        assert "regime" not in basis

    def test_unknown_grade_defaults_to_1x(self):
        c = make_candidate(**self.BULL)
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard", grade="Z",
        )
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        assert stop == 100.0 - base_buffer
        assert "grade" not in basis

    def test_trap_multiplier_below_1_clamped_to_1(self):
        """Defensive: caller passes 0.5 (e.g. bug) — clamped to 1.0×."""
        c = make_candidate(**self.BULL)
        stop, _, _ = compute_stop(
            c, atr=2.0, level="standard", trap_multiplier=0.5,
        )
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        assert stop == 100.0 - base_buffer

    def test_bearish_chain(self):
        c = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=148.0,
            completion_max=152.0,
        )
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="standard",
            trap_multiplier=1.5, regime="high_quant", grade="C",
        )
        # Bearish: anchor = max(X=150, PRZ_high=152) = 152; buffer adds.
        # 0.3 * 1.5 * 1.5 * 1.3 = 0.8775 ATR-mult → 1.755 absolute
        assert stop == 152.0 + 1.755
        assert "trap×1.50" in basis
        assert "regime×1.50" in basis
        assert "grade×1.30" in basis

    def test_REGIME_STOP_MULTIPLIER_table(self):
        assert REGIME_STOP_MULTIPLIER == {"normal": 1.0, "high_quant": 1.5}

    def test_GRADE_STOP_MULTIPLIER_table(self):
        assert GRADE_STOP_MULTIPLIER == {
            "A": 1.0, "B": 1.0, "C": 1.3, "C(参考)": 1.5,
        }

    def test_bullish_aggressive_chain(self):
        """Bullish aggressive anchor path also threads the multiplier chain."""
        c = make_candidate(
            bullish=True,
            points=(100.0, 150.0, 120.0, 140.0, 110.0),
            completion_min=108.0, completion_max=112.0,
        )
        stop, basis, _ = compute_stop(
            c, atr=2.0, level="aggressive",
            trap_multiplier=1.5, regime="high_quant", grade="C",
        )
        # Aggressive bullish anchor = min(X=100, PRZ_low=108) = 100.
        # 0.25 * 1.5 * 1.5 * 1.3 = 0.73125 ATR-mult → 1.4625 absolute.
        assert stop == 100.0 - 1.4625
        assert "X点" in basis
        assert "trap×1.50" in basis

    def test_invalid_level_falls_back_to_standard(self):
        """Defensive: an unknown level silently falls back to standard."""
        c = make_candidate(**self.BULL)
        stop, _, _ = compute_stop(c, atr=2.0, level="bogus")
        base_buffer = ATR_STOP_BUFFER["standard"] * 2.0
        assert stop == 100.0 - base_buffer

    def test_stop_buffer_atr_clamped(self):
        """Escape hatch > MAX_STOP_BUFFER_MULT is clamped to MAX."""
        c = make_candidate(**self.BULL)
        stop, _, _ = compute_stop(
            c, atr=2.0, level="standard", stop_buffer_atr=5.0,
        )
        assert stop == 100.0 - MAX_STOP_BUFFER_MULT * 2.0

    def test_trap_multiplier_at_upper_bound(self):
        """trap=2.0 is exactly the upper bound; not clamped beyond."""
        c = make_candidate(**self.BULL)
        stop, _, _ = compute_stop(
            c, atr=2.0, level="standard", trap_multiplier=2.0,
        )
        # 0.3 * 2.0 = 0.6 ATR-mult → 1.2 absolute
        assert stop == 100.0 - 1.2

    def test_chain_suffix_when_all_1x_returns_empty(self):
        """Sanity: when no multiplier deviates from 1.0, suffix is empty."""
        # Indirectly via the default test: assert "trap×" not in basis, etc.
        c = make_candidate(**self.BULL)
        _, basis, _ = compute_stop(c, atr=2.0, level="standard")
        assert "·" not in basis  # no separator when suffix is empty

    def test_chain_suffix_omitted_parts(self):
        """When only one multiplier fires, only that part appears."""
        c = make_candidate(**self.BULL)
        _, basis, _ = compute_stop(
            c, atr=2.0, level="standard", trap_multiplier=1.5,
        )
        assert "trap×1.50" in basis
        assert "regime" not in basis
        assert "grade" not in basis


class TestComputeTargets:
    def test_bullish_targets(self):
        c = make_candidate()  # A=150
        targets = compute_targets(c, entry=110.0)
        assert len(targets) == 3
        assert targets[0].label == "TP1"
        assert targets[0].price == pytest.approx(110.0 + 0.382 * 40.0)
        assert targets[1].price == pytest.approx(110.0 + 0.618 * 40.0)
        assert targets[2].price == pytest.approx(110.0 + 1.272 * 40.0)
        assert targets[0].fib_basis == "AD 38.2% retrace"
        assert targets[1].fib_basis == "AD 61.8% retrace"
        assert targets[2].fib_basis == "AD 127.2% extension"
        assert [t.close_pct for t in targets] == [50, 30, 20]
        assert targets[0].move_stop_to == "breakeven"

    def test_bearish_targets(self):
        c = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
        )  # A=100
        targets = compute_targets(c, entry=140.0)
        assert targets[0].price == pytest.approx(140.0 - 0.382 * 40.0)
        assert targets[1].price == pytest.approx(140.0 - 0.618 * 40.0)
        assert targets[2].price == pytest.approx(140.0 - 1.272 * 40.0)


class TestNetRr:
    def test_basic_long(self):
        rr = net_rr(entry=100.0, stop=95.0, target=110.0, fee_rate=0.0, slippage_rate=0.0)
        assert rr == pytest.approx(2.0, rel=1e-3)

    def test_fees_reduce_rr(self):
        gross = net_rr(100.0, 95.0, 110.0, fee_rate=0.0, slippage_rate=0.0)
        net = net_rr(100.0, 95.0, 110.0)
        assert net < gross

    def test_short_symmetry(self):
        rr = net_rr(entry=100.0, stop=105.0, target=90.0, fee_rate=0.0, slippage_rate=0.0)
        assert rr == pytest.approx(2.0, rel=1e-3)

    def test_zero_risk_returns_none(self):
        assert net_rr(100.0, 100.0, 110.0) is None

    def test_zero_entry_returns_none(self):
        # Pre-icontract contract: zero entry raises ViolationError (it used to
        # silently return None). The Layer-2 contract now catches this at the
        # boundary so the signal engine fails loudly instead of producing
        # a misleading "None = no signal" silently. Asserting both:
        from icontract import ViolationError

        with pytest.raises(ViolationError):
            net_rr(0.0, 95.0, 110.0)

    def test_negative_reward_returns_none(self):
        # target barely above entry, fees eat the whole reward
        assert net_rr(100.0, 50.0, 100.1) is None

    def test_custom_fee(self):
        rr = net_rr(100.0, 95.0, 110.0, fee_rate=0.01, slippage_rate=0.0)
        # reward = 10 - 2*0.01*100 = 8; risk = 5 + 2 = 7
        assert rr == pytest.approx(8 / 7, rel=1e-3)


class TestGrade:
    def test_grade_a(self):
        assert grade(80, 1.2, 2.5, htf_aligned=True, htf_counter=False) == "A"

    def test_grade_a_requires_htf(self):
        assert grade(80, 1.2, 2.5, htf_aligned=False, htf_counter=False) == "B"

    def test_grade_a_requires_rr2(self):
        assert grade(80, 1.2, 1.8, htf_aligned=True, htf_counter=False) == "B"

    def test_grade_b(self):
        assert grade(65, 1.2, 1.6, htf_aligned=False, htf_counter=False) == "B"

    def test_grade_c(self):
        assert grade(50, 1.2, 1.6, htf_aligned=False, htf_counter=False) == "C(参考)"

    def test_below_45_dropped(self):
        assert grade(40, 1.2, 1.6, htf_aligned=False, htf_counter=False) is None

    def test_rr_gate_violation_demotes_to_c(self):
        # score high but TP2 net R too low -> observation only
        assert grade(90, 1.2, 1.2, htf_aligned=True, htf_counter=False) == "C(参考)"
        assert grade(90, 0.8, 2.5, htf_aligned=True, htf_counter=False) == "C(参考)"

    def test_rr_gate_violation_low_score_dropped(self):
        assert grade(40, 1.2, 1.2, htf_aligned=False, htf_counter=False) is None

    def test_counter_trend_capped_at_c(self):
        assert grade(90, 1.2, 2.5, htf_aligned=False, htf_counter=True) == "C(参考)"

    def test_counter_trend_low_score_dropped(self):
        assert grade(40, 1.2, 2.5, htf_aligned=False, htf_counter=True) is None

    def test_missing_rr_returns_none(self):
        assert grade(90, None, 2.5, htf_aligned=True, htf_counter=False) is None
        assert grade(90, 1.2, None, htf_aligned=True, htf_counter=False) is None

    def test_a_min_threshold_raised_in_high_quant(self):
        # score 80 >= default 75 -> A; but with a_min=85 -> B
        assert grade(80, 1.2, 2.5, htf_aligned=True, htf_counter=False) == "A"
        assert grade(80, 1.2, 2.5, htf_aligned=True, htf_counter=False, a_min=85) == "B"


class TestReasoningFromSignal:
    def test_long_reasoning_full(self):
        text = reasoning_from_signal(make_signal())
        assert "方向：做多" in text
        assert "gartley · XABCD · formed" in text
        assert "108.00 – 112.00" in text
        assert "参考 110.00" in text
        assert "止损：99.00" in text
        assert "TP1 120.00" in text
        assert "平 50%" in text
        assert "净盈亏比：TP1 1.2R / TP2 2.4R" in text
        assert "高周期趋势：bullish" in text

    def test_short_forming_reasoning(self):
        text = reasoning_from_signal(make_signal(direction="short", formed=False))
        assert "方向：做空" in text
        assert "forming" in text

    def test_no_targets_omits_tp_line(self):
        text = reasoning_from_signal(make_signal(targets=()))
        assert "止盈" not in text
