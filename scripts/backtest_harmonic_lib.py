"""Walk-forward backtest library for the harmonic pattern analyzer.

Pure logic. The CLI lives in ``scripts/backtest_harmonic.py``; tests live in
``tests/test_backtest_harmonic_lib.py``.

Pipeline at each step:
  1. Window df -> ``detect_patterns`` (deterministic, no LLM).
  2. ``extract_candidates`` -> live (high-quality) candidates.
  3. ``build_signal`` -> Signal with entry zone / stop / TP ladder.
  4. Forward df -> ``simulate_trades`` over the next ``horizon`` bars.
  5. ``aggregate_trades`` -> win/loss/scratch counts and R-multiples.

This module deliberately avoids the LLM interpretation layer so the backtest
is reproducible and cheap to re-run across markets.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Iterable, Optional

import pandas as pd

from app.domain.signals import Signal, SignalTarget
from app.infra.marketdata import DirectBinanceCandleData
from app.services.signal_engine import build_signal, extract_candidates
from app.services.vibe.backtest_engine import (
    BacktestSummary,
    Trade,
    compute_metrics,
    simulate_trades,
)
from pyharmonics.plotter import HarmonicPlotter
from pyharmonics.search import DivergenceSearch, HarmonicSearch
from pyharmonics.technicals import OHLCTechnicals


# --- DTOs --------------------------------------------------------------------


@dataclass
class BacktestSignalRecord:
    """One detected harmonic signal + the resulting forward trade (if any)."""

    step_index: int
    signal_time: str  # ISO timestamp on the window's close
    direction: str
    grade: str
    pattern_name: str
    family: str
    formed: bool
    entry_price: float
    stop_loss: float
    tp1: float
    rr1: Optional[float]
    entry_reference: float
    entry_zone: list[float]
    horizon: int
    result: str  # "win" | "loss" | "scratch" | "skipped"
    r_multiple: float
    exit_time: Optional[str]
    bars_held: Optional[int]


# --- Step 1+2+3: detect + extract + build -----------------------------------


def _to_candle_data(window_df: pd.DataFrame, symbol: str, interval: str) -> DirectBinanceCandleData:
    cd = DirectBinanceCandleData()
    cd.df = window_df.copy()
    cd.symbol = symbol
    cd.interval = interval
    return cd


def detect_window(window_df: pd.DataFrame, symbol: str, interval: str) -> dict:
    """Run harmonic + divergence detection on a window, return detection dict.

    Mirrors ``app.pyharmonics_handler.whats_new`` but skips the heavyweight
    HarmonicPlotter base64 encoding (irrelevant for backtests) and always
    emits a ``raw_assessment`` dict so ``extract_candidates`` can run.

    Detection is deterministic and LLM-free.
    """
    t = OHLCTechnicals(window_df, symbol, interval)
    hs = HarmonicSearch(t)
    d = DivergenceSearch(t)

    if interval in ("1d", "1w", "4h"):
        # Forming-pattern scan is meaningful on coarser timeframes; on
        # sub-hour windows it would dominate compute and add mostly false
        # positives for a 90d walk-forward. Caller can override by patching
        # this seam in tests.
        hs.forming(limit_to=5, percent_c_to_d=0.8)
    hs.search(limit_to=5)
    d.search(limit_to=5)

    raw_assessment = {
        "forming": hs.get_patterns(formed=False),
        "patterns": hs.get_patterns(),
    }

    divergences = {
        family: [pa.to_dict() for pa in found[-1:]]
        for family, found in d.get_patterns().items()
    }

    # Pick the strongest pattern (XABCD > ABCD > ABC; formed > forming) so
    # downstream `extract_candidates` has something to work with even before
    # we materialise a Signal.
    best_pattern = None
    best_family = None
    best_formed = False
    for formed in (True, False):
        bucket = raw_assessment["patterns" if formed else "forming"]
        for family in (hs.XABCD, hs.ABCD, hs.ABC):
            patterns = bucket.get(family) or []
            if patterns:
                best_pattern = patterns[0]
                best_family = family
                best_formed = formed
                break
        if best_pattern is not None:
            break

    return {
        "raw_assessment": raw_assessment,
        "divergences": divergences,
        "patterns": (
            {"family": best_family} if best_pattern is not None else {}
        ),
        "best_pattern": best_pattern,
    }


def _maybe_relax_filters(relax: bool) -> Optional[list]:
    """Temporarily relax live-trading staleness filters for backtests.

    Backtests evaluate 'if I had taken this signal at this time, would I have
    won?'. The live filter rejects candidates whose PRZ is far from current
    price — that makes sense for real-time, but it hides exactly the trades
    we want to evaluate historically. We widen the distance / age gates so
    every well-formed candidate becomes a tradeable Signal.

    Returns a list of (attr_name, original) pairs that the caller should
    pass to ``_restore_filters`` when finished.
    """
    if not relax:
        return None
    from app.domain import validation as _val

    saved: list[tuple] = []
    # Module-level constants used by rejection_reason().
    # We widen those three distances/ages but leave ``completed`` and
    # ``degenerate_prz`` (data-validity filters) intact.
    for name in ("MAX_PRZ_DISTANCE_ATR", "MAX_D_AGE_BARS"):
        if hasattr(_val, name):
            original = getattr(_val, name)
            setattr(_val, name, 1e9)
            saved.append((_val, name, original))

    # ``completed`` and ``violated`` are computed inside rejection_reason().
    # For the backtest we want to evaluate any well-formed pattern, even if
    # the live trader would never have entered it. Patch the function itself
    # with a no-op so every candidate is accepted; restore on cleanup.
    if hasattr(_val, "rejection_reason"):
        saved.append((_val, "rejection_reason", _val.rejection_reason))

        def _noop_rejection_reason(*_a, **_k):
            return None

        _val.rejection_reason = _noop_rejection_reason

    # build_signal's pipeline also uses the symbol-level ``MIN_CANDLES``
    # gate (signal_engine.py:700). Lower it to 30 so a 60-bar window still
    # passes the guard.
    import app.services.signal_engine as _se
    if hasattr(_se, "MIN_CANDLES"):
        original = _se.MIN_CANDLES
        _se.MIN_CANDLES = 30
        saved.append((_se, "MIN_CANDLES", original))
    return saved


def _restore_filters(saved) -> None:
    if not saved:
        return
    for target, name, original in saved:
        setattr(target, name, original)


def extract_signal(
    window_df: pd.DataFrame,
    symbol: str,
    interval: str,
    detection: Optional[dict] = None,
    relax_filters: bool = True,
) -> Optional[Signal]:
    """Take a window df and return the strongest ``Signal`` (or None).

    ``detection`` is an injection seam: tests pass a pre-built dict instead
    of paying the cost of running ``detect_patterns``.

    ``relax_filters``: when True (default) the live-trading staleness gates
    are widened to infinity so any well-formed candidate becomes a Signal.
    This is the right semantic for a walk-forward backtest — the question
    being answered is "given this pattern, would the trade have won?",
    not "would the live trader have accepted this signal?".
    """
    if detection is None:
        detection = detect_window(window_df, symbol, interval)
    if not detection.get("patterns") and not detection.get("raw_assessment"):
        return None
    if not window_df["close_time"].is_monotonic_increasing:
        # signal_engine relies on close_time mapping; sort to be safe.
        window_df = window_df.sort_index()
    close_times = window_df["close_time"].tolist()
    candidates = extract_candidates(detection, close_times=close_times)
    if not candidates:
        return None
    saved = _maybe_relax_filters(relax_filters)
    try:
        return build_signal(
            window_df,
            interval,
            candidates,
            divergences=detection.get("divergences"),
        )
    finally:
        _restore_filters(saved)


# --- Step 4: forward simulation ---------------------------------------------


@dataclass
class ForwardResult:
    """Result of forward-simulating a single signal."""

    result: str  # "win" | "loss" | "scratch" | "skipped"
    r_multiple: float
    exit_time: Optional[pd.Timestamp]
    bars_held: Optional[int]


def simulate_one(
    forward_df: pd.DataFrame,
    signal: Signal,
    current_price: Optional[float] = None,
    entry_price: Optional[float] = None,
    target_price: Optional[float] = None,
) -> ForwardResult:
    """Forward-simulate one signal.

    Entry-price semantics for the backtest
    --------------------------------------
    ``entry_price`` (highest priority) defaults to ``signal.entry_reference``
    which is the PRZ mid from the harmonic engine. That is the entry a live
    trader was waiting for (price must pull back to PRZ before entry). But
    in a walk-forward backtest the PRZ is often far behind us by the time
    the detector fires, so passing ``current_price`` (= the last close of
    the window at signal time) is a more honest expression of "I would have
    bought at market right now, with these stops and targets".

    ``target_price`` defaults to TP1.

    ``simulate_trades`` returns the matched trade (or empty list if entry
    was never touched). Empty list is mapped to ``"skipped"`` so the caller
    can distinguish it from a 0 R scratch close.
    """
    if signal is None:
        return ForwardResult("skipped", 0.0, None, None)
    direction = "long" if signal.direction == "bullish" else "short"
    if entry_price is not None:
        entry = float(entry_price)
    elif current_price is not None:
        entry = float(current_price)
    else:
        entry = float(signal.entry_reference)
    if target_price is None:
        if signal.targets:
            target_price = signal.targets[0].price
        else:
            # Fallback: assume 1% TP when the engine did not provide one.
            target_price = entry * (1.01 if direction == "long" else 0.99)

    # Sanity-validate direction-invariants up front so a malformed Signal
    # does not crash the whole walk-forward loop. ``simulate_trades`` itself
    # also raises ValueError on bad levels; we map either to a "skipped"
    # result so the report still shows the candidate was evaluated.
    if direction == "long":
        ok = signal.stop_loss < entry < target_price
    else:
        ok = signal.stop_loss > entry > target_price
    if not ok:
        return ForwardResult("skipped", 0.0, None, None)

    try:
        trades = simulate_trades(
            forward_df,
            direction=direction,
            entry_price=entry,
            stop_loss=signal.stop_loss,
            target_price=target_price,
        )
    except ValueError:
        return ForwardResult("skipped", 0.0, None, None)
    if not trades:
        return ForwardResult("skipped", 0.0, None, None)
    t = trades[0]
    bars = (
        int((t.exit_time - t.entry_time) / pd.Timedelta(seconds=86400))
        if t.exit_time is not None and t.entry_time is not None
        else None
    )
    return ForwardResult(
        result=t.result,
        r_multiple=t.r_multiple,
        exit_time=t.exit_time,
        bars_held=bars,
    )


# --- Step 5: walk-forward + summary ------------------------------------------


def walk_forward(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    *,
    window: int,
    step: int,
    horizon: int,
    detect: Optional[callable] = None,  # type: ignore[valid-type]
    extract: Optional[callable] = None,  # type: ignore[valid-type]
    forward_sim: Optional[callable] = None,  # type: ignore[valid-type]
    signal_time_offset: str = "close",
    entry_mode: str = "market",
) -> list[BacktestSignalRecord]:
    """Roll a window forward. Return one record per step (drop None slots).

    Args:
        df: Full OHLC dataframe (must have open/high/low/close/close_time/dts).
        symbol, interval: For detection context.
        window: Bars in the rolling window.
        step: Bar advance between iterations.
        horizon: Forward bars used to evaluate each signal.
        detect/extract/forward_sim: Optional injection seams for tests.
        signal_time_offset: ``"close"`` to label signals by window-close ts.
        entry_mode: ``"market"`` enters at the window's last close (current
            behaviour: many signals skip because price has already run past
            the PRZ). ``"prz"`` enters at ``signal.entry_reference`` (the PRZ
            mid the harmonic engine was waiting for); matches the live trader
            semantic of waiting for a pullback into the zone.

    Records are not produced when ``extract`` returns None or when the forward
    window is unavailable (i.e., last ``horizon`` bars of the dataset).
    """
    detect = detect or detect_window
    extract = extract or (
        lambda w, s, i: extract_signal(w, s, i, detection=detect(w, s, i))
    )
    forward_sim = forward_sim or simulate_one

    records: list[BacktestSignalRecord] = []
    n = len(df)
    if n < window + horizon + 1:
        return records

    last_start = n - horizon  # earliest index where forward has horizon bars
    for end_idx in range(window - 1, last_start, step):
        window_df = df.iloc[end_idx - window + 1 : end_idx + 1]
        forward_df = df.iloc[end_idx + 1 : end_idx + 1 + horizon + 1]

        signal = extract(window_df, symbol, interval)
        if signal is None:
            continue
        # Entry semantics (see ``entry_mode`` doc):
        #   - "market": enter at the window's last close — the price the
        #     trader had available at signal time. Most signals in trending
        #     markets skip because price has already run past the PRZ.
        #   - "prz": enter at ``signal.entry_reference`` (the PRZ mid), which
        #     matches the live trader semantic of waiting for a pullback into
        #     the zone. Trades execute whenever the PRZ is touched within the
        #     forward window (or after, depending on the engine's simulate_trades
        #     logic).
        current_price = float(window_df["close"].iloc[-1])
        prz_entry = float(signal.entry_reference) if entry_mode == "prz" else None
        result = forward_sim(
            forward_df,
            signal,
            current_price=current_price,
            entry_price=prz_entry,
        )
        if result is None:
            continue

        if signal_time_offset == "close":
            signal_time = df.index[end_idx]
        elif signal_time_offset == "next_open":
            # Use the next candle's timestamp for cleanness.
            signal_time = df.index[end_idx + 1] if end_idx + 1 < n else df.index[end_idx]
        else:
            signal_time = df.index[end_idx]

        tp1 = signal.targets[0].price if signal.targets else float("nan")
        records.append(
            BacktestSignalRecord(
                step_index=end_idx,
                signal_time=pd.Timestamp(signal_time).isoformat(),
                direction=signal.direction,
                grade=signal.grade,
                pattern_name=signal.pattern_name,
                family=signal.family,
                formed=signal.formed,
                # Entry actually used in the simulation = current_price
                # (last close of the window). Surface both so a reader of
                # the JSON can see what the engine asked for vs what was
                # used.
                entry_price=current_price,
                stop_loss=signal.stop_loss,
                tp1=tp1,
                rr1=signal.net_rr_tp1,
                entry_reference=signal.entry_reference,
                entry_zone=list(signal.entry_zone),
                horizon=horizon,
                result=result.result,
                r_multiple=result.r_multiple,
                exit_time=pd.Timestamp(result.exit_time).isoformat()
                if result.exit_time is not None
                else None,
                bars_held=result.bars_held,
            )
        )

    return records


# --- Aggregation -------------------------------------------------------------


def aggregate_records(
    records: Iterable[BacktestSignalRecord],
) -> dict:
    """Fold per-signal records into a summary dict with win/loss/scratch stats."""
    records = list(records)
    by_result: dict[str, list[BacktestSignalRecord]] = {
        "win": [],
        "loss": [],
        "scratch": [],
        "skipped": [],
    }
    total_r = 0.0
    win_r = 0.0
    loss_r = 0.0
    wins = 0
    losses = 0
    scratches = 0
    skipped = 0
    for r in records:
        total_r += r.r_multiple
        if r.result == "win":
            wins += 1
            win_r += r.r_multiple
            by_result["win"].append(r)
        elif r.result == "loss":
            losses += 1
            loss_r += r.r_multiple
            by_result["loss"].append(r)
        elif r.result == "scratch":
            scratches += 1
            by_result["scratch"].append(r)
        elif r.result == "skipped":
            skipped += 1
            by_result["skipped"].append(r)

    decided = wins + losses
    win_rate = (wins / decided) if decided else 0.0
    # Profit factor: sum of winning R / abs(sum of losing R). Guard zero.
    # Two distinct zero-loss branches:
    #   - At least one win, no losses            -> undefined, report None/inf
    #   - No wins at all                          -> 0.0 (no edge)
    if losses == 0:
        profit_factor = float("inf") if wins > 0 else 0.0
    elif loss_r == 0:
        profit_factor = float("inf") if wins > 0 else 0.0
    else:
        profit_factor = win_r / abs(loss_r)
    avg_r = (total_r / len(records)) if records else 0.0

    # By grade:
    by_grade: dict[str, dict] = {}
    for r in records:
        b = by_grade.setdefault(r.grade, {"count": 0, "wins": 0, "losses": 0, "r": 0.0})
        b["count"] += 1
        if r.result == "win":
            b["wins"] += 1
        elif r.result == "loss":
            b["losses"] += 1
        b["r"] += r.r_multiple

    # By family:
    by_family: dict[str, dict] = {}
    for r in records:
        b = by_family.setdefault(r.family, {"count": 0, "wins": 0, "losses": 0, "r": 0.0})
        b["count"] += 1
        if r.result == "win":
            b["wins"] += 1
        elif r.result == "loss":
            b["losses"] += 1
        b["r"] += r.r_multiple

    return {
        "total_signals": len(records),
        "skipped_signals": skipped,
        "decisions": decided,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "total_r": total_r,
        "profit_factor": profit_factor,
        "by_grade": by_grade,
        "by_family": by_family,
    }


def report(
    *,
    config: dict,
    summary: dict,
    records: list[BacktestSignalRecord],
) -> dict:
    """Package everything into a JSON-serialisable report dict."""
    return {
        "config": config,
        "summary": summary,
        "signals": [asdict(r) for r in records],
    }


def _scrub_nonfinite(obj):
    """Recursively replace +/-inf / nan floats with None for JSON."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _scrub_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_nonfinite(v) for v in obj]
    if isinstance(obj, tuple):
        return [_scrub_nonfinite(v) for v in obj]
    return obj


def write_json(report: dict, path) -> None:
    """Write the report dict as JSON, with non-finite floats normalised to None."""
    safe = _scrub_nonfinite(report)
    path.write_text(json.dumps(safe, indent=2, ensure_ascii=False, default=str))


def markdown_summary(report: dict) -> str:
    """Render a short Markdown summary for human reading."""
    cfg = report["config"]
    s = report["summary"]
    sigs = report["signals"]

    def _fmt_pf(pf):
        return "inf" if pf == float("inf") else f"{pf:.2f}"

    lines = [
        f"# Walk-forward backtest — {cfg.get('symbol', '?')} {cfg.get('interval', '?')} ({cfg.get('days', '?')}d)",
        "",
        "## Config",
        "",
        f"- symbol: `{cfg.get('symbol', '?')}`",
        f"- interval: `{cfg.get('interval', '?')}`",
        f"- window: `{cfg.get('window', '?')}` bars",
        f"- step: `{cfg.get('step', '?')}` bar(s)",
        f"- horizon: `{cfg.get('horizon', '?')}` bars",
        f"- market: `{cfg.get('market', 'binance')}`",
        "",
        "## Summary",
        "",
        f"- total signals: **{s['total_signals']}**",
        f"- decisions (entry filled): {s['decisions']}",
        f"- skipped (entry never touched): {s['skipped_signals']}",
        f"- wins / losses / scratches: {s['wins']} / {s['losses']} / {s['scratches']}",
        f"- win rate (of decided): **{s['win_rate']:.1%}**",
        f"- avg R multiple: **{s['avg_r']:.2f}**",
        f"- total R: **{s['total_r']:+.2f}**",
        f"- profit factor: **{_fmt_pf(s['profit_factor'])}**",
        "",
    ]
    if s.get("by_grade"):
        lines += ["## By grade", ""]
        for grade, b in sorted(s["by_grade"].items()):
            wr = b["wins"] / (b["wins"] + b["losses"]) if (b["wins"] + b["losses"]) else 0
            lines.append(
                f"- {grade}: count={b['count']} wins={b['wins']} losses={b['losses']} "
                f"win_rate={wr:.1%} R={b['r']:+.2f}"
            )
        lines.append("")
    if s.get("by_family"):
        lines += ["## By family", ""]
        for fam, b in sorted(s["by_family"].items()):
            wr = b["wins"] / (b["wins"] + b["losses"]) if (b["wins"] + b["losses"]) else 0
            lines.append(
                f"- {fam}: count={b['count']} wins={b['wins']} losses={b['losses']} "
                f"win_rate={wr:.1%} R={b['r']:+.2f}"
            )
        lines.append("")
    if sigs:
        lines += ["## Signals (first 20)", ""]
        lines.append("| time | dir | grade | pattern | entry | stop | tp1 | rr1 | result | r |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in sigs[:20]:
            lines.append(
                f"| {r['signal_time']} | {r['direction']} | {r['grade']} | "
                f"{r['pattern_name']} | {r['entry_price']:.4g} | {r['stop_loss']:.4g} | "
                f"{r['tp1']:.4g} | {r['rr1'] if r['rr1'] is not None else ''} | "
                f"{r['result']} | {r['r_multiple']:+.2f} |"
            )
        if len(sigs) > 20:
            lines.append("")
            lines.append(f"_…{len(sigs) - 20} more in JSON artifact._")
        lines.append("")
    return "\n".join(lines)


# --- Re-export for convenience ----------------------------------------------


__all__ = [
    "BacktestSignalRecord",
    "ForwardResult",
    "detect_window",
    "extract_signal",
    "simulate_one",
    "walk_forward",
    "aggregate_records",
    "report",
    "write_json",
    "markdown_summary",
    "BacktestSummary",
    "Trade",
    "Signal",
    "SignalTarget",
    "compute_metrics",
    "simulate_trades",
]
