"""Pure state machine for an open harmonic position.

Implements the post-entry stop-management layer the engine declares but never
wired up:

    TP1 hit:  50 % close, stop → entry (breakeven)
    TP2 hit:  30 % close, stop → TP1 (lock in partial)
    TP3 hit:  20 % close, position closed
    Chandelier:  TP1 hit ⇒ trailing stop = highest(N) − k·ATR
    Time stop:  bars_held > 1.5 × CD_leg ⇒ forced market close

Design rules (KISS):

* No I/O, no logging, no external state.  Every function is pure and
  trivially testable.
* Immutable dataclasses for state — each ``process_bar`` returns a new
  :class:`PositionState` and a list of :class:`Action`.
* Consumers (API, Vibe, backtester) translate ``Action`` to their
  side-effect vocabulary; the manager itself never places orders.

Why a separate module (vs. extending :mod:`app.domain.signals`):

* :mod:`signals` is the pure entry-time math; position management is the
  pure holding-time math.  Both are pure, but their inputs differ
  (signal vs. evolving bar stream) — separation keeps each module's
  domain crisply scoped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from icontract import ensure, require

# Defaults — overridable per-construction.  Centralised here so the test
# suite and any future runtime config can tweak them in one place.
DEFAULT_CHANDELIER_PERIOD = 22
DEFAULT_CHANDELIER_ATR_MULT = 2.0
DEFAULT_TIME_STOP_CD_MULT = 1.5


# --- Value objects ---------------------------------------------------------


@dataclass(frozen=True)
class PositionState:
    """Immutable snapshot of an open harmonic position."""

    bullish: bool
    entry_price: float
    initial_stop: float           # Phase 1 (entry-time) stop
    current_stop: float           # current stop (advances as TPs hit)
    tp1: float
    tp2: float
    tp3: float
    atr: float                    # ATR at the time of entry (snapshot)
    cd_leg_bars: int              # C → D bar distance (for time stop)
    chandelier_period: int = DEFAULT_CHANDELIER_PERIOD
    chandelier_atr_mult: float = DEFAULT_CHANDELIER_ATR_MULT
    time_stop_cd_mult: float = DEFAULT_TIME_STOP_CD_MULT
    # Evolving counters
    bars_held: int = 0
    size_remaining: float = 1.0   # 1.0 = full, 0.5 = after TP1, 0.2 = after TP2
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    closed: bool = False
    close_reason: Optional[str] = None
    # Chandelier state — only meaningful after TP1 hit
    chandelier_high: Optional[float] = None   # highest high since TP1 (long)
    chandelier_low: Optional[float] = None    # lowest low since TP1 (short)

    def __post_init__(self) -> None:
        # Hard preconditions — keep state sane regardless of caller.
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be > 0 (got {self.entry_price})")
        if self.initial_stop <= 0:
            raise ValueError(f"initial_stop must be > 0 (got {self.initial_stop})")
        if not (self.tp1 > 0 and self.tp2 > 0 and self.tp3 > 0):
            raise ValueError(
                f"tp1/tp2/tp3 must all be > 0 (got {self.tp1}/{self.tp2}/{self.tp3})"
            )
        if self.atr <= 0:
            raise ValueError(f"atr must be > 0 (got {self.atr})")
        if self.cd_leg_bars < 0:
            raise ValueError(f"cd_leg_bars must be >= 0 (got {self.cd_leg_bars})")
        if not 0.0 <= self.size_remaining <= 1.0:
            raise ValueError(
                f"size_remaining must be in [0, 1] (got {self.size_remaining})"
            )


@dataclass(frozen=True)
class Action:
    """A side-effect request emitted by :func:`process_bar`."""

    type: str  # "hold" | "close_partial" | "move_stop" | "close_all"
    size_pct: float = 0.0        # for close_partial: fraction of original size
    new_stop: float = 0.0        # for move_stop: the new stop price
    reason: str = ""


# --- Helpers ---------------------------------------------------------------


def _chandelier_stop(state: PositionState) -> float:
    """Chandelier trailing stop (long or short).

    Long: highest_high_since_tp1 − k·ATR.
    Short: lowest_low_since_tp1 + k·ATR.

    Never moves the stop backwards — only ratchets in the favourable
    direction.
    """
    k = state.chandelier_atr_mult
    if state.bullish:
        # chandelier_high is always set once TP1 hits (initialised then).
        assert state.chandelier_high is not None
        return state.chandelier_high - k * state.atr
    assert state.chandelier_low is not None
    return state.chandelier_low + k * state.atr


def _tp_hit(bar_high: float, bar_low: float, tp: float, bullish: bool) -> bool:
    """A TP is hit when the bar's range covers the TP level.

    Long: bar_high >= tp (wick up touches target).
    Short: bar_low <= tp (wick down touches target).
    """
    return bar_high >= tp if bullish else bar_low <= tp


def _stop_hit(bar_high: float, bar_low: float, stop: float, bullish: bool) -> bool:
    """A stop is hit when the bar's range crosses the stop price.

    Long: bar_low <= stop (wick down touches stop).
    Short: bar_high >= stop (wick up touches stop).
    """
    return bar_low <= stop if bullish else bar_high >= stop


# --- Core state machine -----------------------------------------------------


@require(lambda state: state.entry_price > 0)
@require(lambda state: state.initial_stop > 0)
@require(lambda state: state.tp1 > 0 and state.tp2 > 0 and state.tp3 > 0)
@require(lambda state: state.atr > 0)
@require(lambda state: state.cd_leg_bars >= 0)
@require(lambda state: 0.0 <= state.size_remaining <= 1.0)
@ensure(lambda result: not result[0].closed or result[0].close_reason is not None)
def process_bar(
    state: PositionState,
    bar_high: float,
    bar_low: float,
    bar_close: float,
) -> tuple[PositionState, list[Action]]:
    """Advance ``state`` by one bar; return (new_state, actions).

    The bar's high/low/close determine whether TPs were hit intra-bar;
    for KISS we collapse all TPs touched in the same bar into a single
    state transition (TP1 → TP2 → TP3 in order, each firing its action).

    If the initial stop is hit before any TP, the position closes with
    reason ``"stop"`` and full size remaining is lost.

    The function is pure: ``state`` is never mutated; ``dataclasses.replace``
    builds the successor.  ``Actions`` are emitted in the order they
    should be applied (close_partial before move_stop is intentional —
    we don't change the stop before partially closing).
    """
    if state.closed:
        return state, [Action(type="hold", reason="already closed")]

    # Always advance the bar counter.
    new_state = dataclasses_replace(state, bars_held=state.bars_held + 1)
    actions: list[Action] = []

    # --- Initial stop check (Phase 1) -------------------------------------
    # If the bar's range crosses the current stop, the position is stopped out.
    if _stop_hit(bar_high, bar_low, new_state.current_stop, new_state.bullish):
        new_state = dataclasses_replace(
            new_state,
            closed=True,
            size_remaining=0.0,
            close_reason="stop",
        )
        return new_state, [Action(type="close_all", reason="initial_or_trail_stop_hit")]

    # --- Time stop ----------------------------------------------------------
    # bars_held > 1.5 × CD leg ⇒ forced market close (regardless of P&L).
    if new_state.bars_held > new_state.time_stop_cd_mult * new_state.cd_leg_bars:
        new_state = dataclasses_replace(
            new_state,
            closed=True,
            size_remaining=0.0,
            close_reason="time_stop",
        )
        return new_state, [Action(type="close_all", reason="time_stop")]

    # --- TP progression + Chandelier ratchet -------------------------------
    # Long positions: TPs advance upward; chandelier tracks the highest high
    # since TP1.  Mirror logic for short.
    tp_targets = (
        (new_state.tp1, "tp1", 0.5, "breakeven"),     # 50 %, stop → entry
        (new_state.tp2, "tp2", 0.3, "tp1"),          # 30 %, stop → TP1
        (new_state.tp3, "tp3", 0.2, None),           # 20 %, close all
    )

    for tp_price, tp_name, close_pct, next_stop_label in tp_targets:
        hit_attr = f"{tp_name}_hit"
        if getattr(new_state, hit_attr):
            continue  # already processed in a prior bar
        if not _tp_hit(bar_high, bar_low, tp_price, new_state.bullish):
            break  # TPs must be hit in order; if tp1 not hit, neither is tp2

        # Mark the TP hit and capture Chandelier anchor at TP1.
        updates: dict = {hit_attr: True}
        if tp_name == "tp1":
            # Chandelier initialises at the bar's extreme; the ratchet is
            # computed per-bar in the loop below so we only need the
            # running extreme as state.
            updates["chandelier_high"] = bar_high if new_state.bullish else None
            updates["chandelier_low"] = bar_low if not new_state.bullish else None
        new_state = dataclasses_replace(new_state, **updates)

        # Emit partial close.
        new_state = dataclasses_replace(
            new_state,
            size_remaining=new_state.size_remaining - close_pct,
        )
        actions.append(
            Action(
                type="close_partial",
                size_pct=close_pct,
                reason=f"{tp_name}_hit",
            )
        )

        # Advance the stop (TP1 → entry, TP2 → tp1, TP3 → close all).
        if next_stop_label == "breakeven":
            new_stop = new_state.entry_price
        elif next_stop_label == "tp1":
            new_stop = new_state.tp1
        else:
            # TP3 ⇒ position fully closed.
            new_state = dataclasses_replace(
                new_state,
                closed=True,
                size_remaining=0.0,
                close_reason="tp3",
            )
            actions.append(Action(type="close_all", reason="tp3_full_close"))
            return new_state, actions

        if new_stop != new_state.current_stop:
            new_state = dataclasses_replace(new_state, current_stop=new_stop)
            actions.append(
                Action(type="move_stop", new_stop=new_stop, reason=f"after_{tp_name}")
            )

    # --- Chandelier ratchet (only after TP1) -------------------------------
    if new_state.tp1_hit and not new_state.closed and new_state.bars_held > 0:
        if new_state.bullish:
            # Update highest high since TP1.
            prev = new_state.chandelier_high
            new_high = max(prev if prev is not None else bar_high, bar_high)
            new_state = dataclasses_replace(new_state, chandelier_high=new_high)
            trail = _chandelier_stop(new_state)
        else:
            prev = new_state.chandelier_low
            new_low = min(prev if prev is not None else bar_low, bar_low)
            new_state = dataclasses_replace(new_state, chandelier_low=new_low)
            trail = _chandelier_stop(new_state)

        # Ratchet only if trail improves (long: trail > current_stop; short: <).
        improved = (
            (new_state.bullish and trail > new_state.current_stop)
            or (not new_state.bullish and trail < new_state.current_stop)
        )
        if improved:
            new_state = dataclasses_replace(new_state, current_stop=trail)
            actions.append(
                Action(type="move_stop", new_stop=trail, reason="chandelier_ratchet")
            )

    if not actions:
        actions.append(Action(type="hold", reason="bar_no_event"))

    return new_state, actions


# --- Local helper (dataclasses.replace import dance) ----------------------

import dataclasses as _dc

# Aliased so the @ensure decorator above can read it without a forward
# reference.  This is the standard ``dataclasses.replace`` indirection
# used to keep the @require/ensure decorators importable in isolation.
def dataclasses_replace(obj, **changes):  # noqa: D401 — short helper
    """Thin alias around ``dataclasses.replace`` so the dataclass module is
    only imported once at module load (avoids the shadow-import dance in
    some test runners)."""
    return _dc.replace(obj, **changes)