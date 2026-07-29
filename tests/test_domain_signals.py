"""100% coverage tests for app.domain.signals (pure functions)."""
import pytest

from app.domain.signals import (
    ATR_STOP_BUFFER,
    Candidate,
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
        label="TP1", price=120.0, fib_basis="AD 38.2% retrace",
        close_pct=50, move_stop_to="breakeven",
    )
    base = dict(
        status="confirmed", grade="A", direction="long",
        pattern_name="gartley", family="XABCD", formed=True,
        entry_zone=(108.0, 112.0), entry_reference=110.0,
        stop_loss=99.0, stop_basis="X/PRZ invalidation - 0.5*ATR",
        stop_level="standard",
        invalidation_point=99.5,
        targets=(target,), net_rr_tp1=1.2, net_rr_tp2=2.4,
        confluence_score=80, confluence={"rsi": 15},
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
            reasoning="方向：做多", sharpe=0.42, regime="high_quant",
            position_multiplier=0.9, stability_score=85, trap_score=50,
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
            completion_min=138.0, completion_max=142.0,
        )
        stop, basis, inv = compute_stop(c, atr=2.0)
        assert stop == 150.0 + ATR_STOP_BUFFER["standard"] * 2.0
        assert "ATR" in basis
        assert inv == 150.0

    def test_bearish_gartley_prz_above_x(self):
        c = make_candidate(
            bullish=False,
            points=(145.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=148.0, completion_max=152.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 152.0 + ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_bullish_uses_prz_not_x(self):
        # butterfly completes beyond X -> anchor is PRZ low even though X lower
        c = make_candidate(
            name="butterfly",
            points=(100.0, 150.0, 120.0, 140.0, 95.0),
            completion_min=94.0, completion_max=96.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 94.0 - ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_bearish_uses_prz(self):
        c = make_candidate(
            name="crab", bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 155.0),
            completion_min=154.0, completion_max=156.0,
        )
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 156.0 + ATR_STOP_BUFFER["standard"] * 2.0

    def test_extended_pattern_case_insensitive(self):
        c = make_candidate(name="Deep Crab")
        stop, _, _ = compute_stop(c, atr=2.0)
        assert stop == 108.0 - ATR_STOP_BUFFER["standard"] * 2.0


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
