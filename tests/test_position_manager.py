"""100 % coverage tests for app.services.position_manager.

The position manager is a pure state machine — every scenario must be
exercised here, including degenerate cases (empty bar, hit-before-TP1,
time-stop before any TP, Chandelier ratchet only after TP1, etc.).
"""

from __future__ import annotations

import pytest

from app.services.position_manager import (
    Action,
    PositionState,
    _chandelier_stop,
    _stop_hit,
    _tp_hit,
    process_bar,
)


# --- Fixtures --------------------------------------------------------------


def make_long_state(**overrides) -> PositionState:
    base = dict(
        bullish=True,
        entry_price=100.0,
        initial_stop=95.0,
        current_stop=95.0,
        tp1=110.0,
        tp2=120.0,
        tp3=130.0,
        atr=2.0,
        cd_leg_bars=10,
    )
    base.update(overrides)
    return PositionState(**base)


def make_short_state(**overrides) -> PositionState:
    base = dict(
        bullish=False,
        entry_price=100.0,
        initial_stop=105.0,
        current_stop=105.0,
        tp1=90.0,
        tp2=80.0,
        tp3=70.0,
        atr=2.0,
        cd_leg_bars=10,
    )
    base.update(overrides)
    return PositionState(**base)


# --- Pure helpers ----------------------------------------------------------


class TestTpHit:
    def test_long_hit_via_high(self):
        assert _tp_hit(bar_high=110.0, bar_low=105.0, tp=110.0, bullish=True)

    def test_long_no_hit_when_high_below_tp(self):
        assert not _tp_hit(bar_high=109.0, bar_low=105.0, tp=110.0, bullish=True)

    def test_short_hit_via_low(self):
        assert _tp_hit(bar_high=95.0, bar_low=90.0, tp=90.0, bullish=False)

    def test_short_no_hit_when_low_above_tp(self):
        assert not _tp_hit(bar_high=95.0, bar_low=91.0, tp=90.0, bullish=False)


class TestStopHit:
    def test_long_hit_via_low(self):
        assert _stop_hit(bar_high=100.0, bar_low=94.0, stop=95.0, bullish=True)

    def test_long_no_hit_when_low_above_stop(self):
        assert not _stop_hit(bar_high=100.0, bar_low=96.0, stop=95.0, bullish=True)

    def test_short_hit_via_high(self):
        assert _stop_hit(bar_high=106.0, bar_low=100.0, stop=105.0, bullish=False)

    def test_short_no_hit_when_high_below_stop(self):
        assert not _stop_hit(bar_high=104.0, bar_low=100.0, stop=105.0, bullish=False)


class TestChandelierStop:
    def test_long(self):
        s = make_long_state(
            tp1_hit=True, chandelier_high=112.0, atr=2.0, chandelier_atr_mult=2.0
        )
        assert _chandelier_stop(s) == 112.0 - 2.0 * 2.0

    def test_short(self):
        s = make_short_state(
            tp1_hit=True, chandelier_low=88.0, atr=2.0, chandelier_atr_mult=2.0
        )
        assert _chandelier_stop(s) == 88.0 + 2.0 * 2.0


# --- Constructor contracts -------------------------------------------------


class TestContracts:
    def test_zero_entry_rejected(self):
        with pytest.raises(ValueError, match="entry_price"):
            PositionState(
                bullish=True, entry_price=0.0, initial_stop=95.0, current_stop=95.0,
                tp1=110.0, tp2=120.0, tp3=130.0, atr=2.0, cd_leg_bars=10,
            )

    def test_negative_size_rejected(self):
        with pytest.raises(ValueError, match="size_remaining"):
            PositionState(
                bullish=True, entry_price=100.0, initial_stop=95.0, current_stop=95.0,
                tp1=110.0, tp2=120.0, tp3=130.0, atr=2.0, cd_leg_bars=10,
                size_remaining=-0.1,
            )

    def test_zero_atr_rejected(self):
        with pytest.raises(ValueError, match="atr"):
            PositionState(
                bullish=True, entry_price=100.0, initial_stop=95.0, current_stop=95.0,
                tp1=110.0, tp2=120.0, tp3=130.0, atr=0.0, cd_leg_bars=10,
            )

    def test_zero_tp_rejected(self):
        with pytest.raises(ValueError, match="tp1/tp2/tp3"):
            PositionState(
                bullish=True, entry_price=100.0, initial_stop=95.0, current_stop=95.0,
                tp1=0.0, tp2=120.0, tp3=130.0, atr=2.0, cd_leg_bars=10,
            )

    def test_negative_cd_leg_rejected(self):
        with pytest.raises(ValueError, match="cd_leg_bars"):
            PositionState(
                bullish=True, entry_price=100.0, initial_stop=95.0, current_stop=95.0,
                tp1=110.0, tp2=120.0, tp3=130.0, atr=2.0, cd_leg_bars=-1,
            )

    def test_zero_initial_stop_rejected(self):
        with pytest.raises(ValueError, match="initial_stop"):
            PositionState(
                bullish=True, entry_price=100.0, initial_stop=0.0, current_stop=95.0,
                tp1=110.0, tp2=120.0, tp3=130.0, atr=2.0, cd_leg_bars=10,
            )


# --- Core scenarios --------------------------------------------------------


class TestLongFlow:
    """Long position from entry through all three TPs."""

    def test_initial_state(self):
        s = make_long_state()
        assert s.size_remaining == 1.0
        assert s.current_stop == 95.0
        assert s.tp1_hit is False

    def test_bar_no_event(self):
        s = make_long_state()
        s2, actions = process_bar(s, bar_high=102.0, bar_low=98.0, bar_close=100.0)
        assert s2.bars_held == 1
        assert s2.size_remaining == 1.0
        assert s2.current_stop == 95.0
        assert [a.type for a in actions] == ["hold"]
        assert s2.tp1_hit is False

    def test_tp1_hit_moves_stop_to_breakeven(self):
        s = make_long_state()
        s2, actions = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        # 50 % closed, stop → entry (or tighter via Chandelier).
        assert s2.size_remaining == 0.5
        assert s2.tp1_hit is True
        # The bar's high was 111; Chandelier says 111 - 4 = 107, beats breakeven 100.
        assert s2.current_stop == 107.0
        action_types = [a.type for a in actions]
        assert "close_partial" in action_types
        assert "move_stop" in action_types

    def test_tp1_then_tp2_in_same_bar(self):
        """Single bar that gaps through TP1 and TP2."""
        s = make_long_state()
        s2, _ = process_bar(s, bar_high=121.0, bar_low=100.0, bar_close=120.0)
        assert s2.tp1_hit and s2.tp2_hit
        assert s2.size_remaining == 0.2  # 100 - 50 - 30
        # Chandelier wins over TP1 placement: 121 - 2*2 = 117 > 120 is false,
        # 117 < 120 so 117 is tighter (long).  Stop ratchets down to 117.
        assert s2.current_stop == 117.0

    def test_tp3_closes_position(self):
        s = make_long_state()
        s2, _ = process_bar(s, bar_high=131.0, bar_low=100.0, bar_close=130.0)
        assert s2.tp3_hit
        assert s2.closed
        assert s2.size_remaining == 0.0
        assert s2.close_reason == "tp3"

    def test_stop_hit_closes_position(self):
        s = make_long_state()
        s2, actions = process_bar(s, bar_high=99.0, bar_low=94.0, bar_close=95.0)
        assert s2.closed
        assert s2.close_reason == "stop"
        assert s2.size_remaining == 0.0
        assert actions[-1].type == "close_all"

    def test_stop_hit_via_wick(self):
        """Bar wick below stop but close above — still hit."""
        s = make_long_state()
        s2, _ = process_bar(s, bar_high=98.0, bar_low=94.5, bar_close=96.0)
        assert s2.closed and s2.close_reason == "stop"

    def test_chandelier_ratchet_after_tp1(self):
        """After TP1, Chandelier ratchets stop up as new highs print."""
        s = make_long_state()
        # Bar 1: TP1 hit at high=111.
        s, _ = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        # Bar 2: New high at 115 — Chandelier should ratchet.
        s, actions = process_bar(s, bar_high=115.0, bar_low=112.0, bar_close=114.0)
        # Chandelier = 115 - 4 = 111
        assert s.current_stop == 111.0
        assert any(a.type == "move_stop" and a.reason == "chandelier_ratchet" for a in actions)

    def test_chandelier_does_not_move_backwards(self):
        """A new low without new high leaves Chandelier unchanged."""
        s = make_long_state()
        s, _ = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        # chandelier_high = 111; stop = 107.
        s, actions = process_bar(s, bar_high=110.0, bar_low=108.0, bar_close=109.0)
        # New high is 110 < 111, so Chandelier unchanged → stop stays.
        assert s.current_stop == 107.0
        assert not any(a.type == "move_stop" and a.reason == "chandelier_ratchet" for a in actions)

    def test_tp1_then_pullback_hits_breakeven_stop(self):
        """After TP1 + breakeven stop, a pullback to entry closes @ ~0 P&L."""
        s = make_long_state()
        s, _ = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        # Now suppose Chandelier wins and stop = 107; pull back to 106.
        s, actions = process_bar(s, bar_high=108.0, bar_low=106.0, bar_close=107.0)
        # Bar low 106 < stop 107 → stopped out.  size_remaining collapses to 0
        # at closure so consumers can't double-sell the position.
        assert s.closed and s.close_reason == "stop"
        assert s.size_remaining == 0.0

    def test_time_stop_forces_close(self):
        s = make_long_state(cd_leg_bars=4)
        # Need bars_held > 1.5 * 4 = 6 → 7 bars.
        cur = s
        for _ in range(7):
            cur, _ = process_bar(cur, bar_high=102.0, bar_low=99.0, bar_close=100.5)
        assert cur.closed and cur.close_reason == "time_stop"

    def test_time_stop_exact_boundary_keeps_open(self):
        """bars_held == 1.5 * CD_leg (the boundary) keeps position open."""
        s = make_long_state(cd_leg_bars=4)
        cur = s
        for _ in range(6):  # 1.5 * 4 = 6
            cur, _ = process_bar(cur, bar_high=102.0, bar_low=99.0, bar_close=100.5)
        assert not cur.closed


class TestShortFlow:
    """Mirror tests for short positions."""

    def test_tp1_hit_moves_stop_to_breakeven(self):
        s = make_short_state()
        s2, actions = process_bar(s, bar_high=95.0, bar_low=89.0, bar_close=90.0)
        assert s2.size_remaining == 0.5
        assert s2.tp1_hit
        # Short Chandelier = low + 2*ATR = 89 + 4 = 93, beats breakeven 100.
        assert s2.current_stop == 93.0

    def test_stop_hit_via_high(self):
        s = make_short_state()
        s2, _ = process_bar(s, bar_high=106.0, bar_low=101.0, bar_close=105.0)
        assert s2.closed and s2.close_reason == "stop"

    def test_chandelier_ratchet_down_after_tp1(self):
        s = make_short_state()
        s, _ = process_bar(s, bar_high=95.0, bar_low=89.0, bar_close=90.0)
        # New low at 85 → Chandelier = 85 + 4 = 89.
        s, actions = process_bar(s, bar_high=88.0, bar_low=85.0, bar_close=86.0)
        assert s.current_stop == 89.0
        assert any(a.type == "move_stop" and a.reason == "chandelier_ratchet" for a in actions)

    def test_tp3_closes_short(self):
        s = make_short_state()
        s2, _ = process_bar(s, bar_high=95.0, bar_low=69.0, bar_close=70.0)
        assert s2.tp3_hit and s2.closed and s2.close_reason == "tp3"


# --- Idempotency -----------------------------------------------------------


class TestAlreadyClosed:
    def test_already_closed_returns_hold(self):
        from dataclasses import replace

        s = make_long_state()
        s2, _ = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        s3 = replace(s2, closed=True, size_remaining=0.0, close_reason="tp3")
        s4, actions = process_bar(s3, bar_high=200.0, bar_low=50.0, bar_close=150.0)
        assert s4 is s3
        assert actions == [Action(type="hold", reason="already closed")]


# --- Action ordering ------------------------------------------------------


class TestActionOrdering:
    def test_close_partial_emitted_before_move_stop(self):
        """On TP1 hit, close_partial must precede move_stop so the partial
        close executes before the broker adjusts the stop."""
        s = make_long_state()
        _, actions = process_bar(s, bar_high=111.0, bar_low=100.0, bar_close=110.0)
        types = [a.type for a in actions]
        if "close_partial" in types and "move_stop" in types:
            assert types.index("close_partial") < types.index("move_stop")