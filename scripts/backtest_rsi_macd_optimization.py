#!/usr/bin/env python3
"""Compare baseline vs optimized RSI/MACD confluence scoring on BTC 4H walk-forward.

Usage:
    PYTHONPATH=. python scripts/backtest_rsi_macd_optimization.py \\
        --symbol BTCUSDT --interval 4h --days 120 \\
        --out-dir docs/_backtest_artifacts

Outputs:
    - baseline.json / baseline.md
    - optimized.json / optimized.md
    - comparison.json / comparison.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts._binance_stdlib import fetch_binance_klines


def fetch_data(symbol: str, interval: str, days: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    print(f"Fetching {symbol} {interval} {days}d from Binance ({start.date()} → {end.date()})…")
    df = fetch_binance_klines(symbol, interval, start, end).sort_index()
    print(f"  → {len(df)} candles, {df.index[0]} → {df.index[-1]}")
    return df


# ─── Baseline confluence_score (v4) ─────────────────────────────────────────

from app.services.signal_engine import SWING_LOOKBACK, VOLUME_MA_WINDOW, ATR_PRZ_SWEEP


def _is_reversal_candle(row, bullish: bool) -> bool:
    rng = row["high"] - row["low"]
    if rng <= 0:
        return False
    if bullish:
        lower_wick = min(row["open"], row["close"]) - row["low"]
        return bool(row["close"] > row["open"] and lower_wick >= 0.5 * rng)
    upper_wick = row["high"] - max(row["open"], row["close"])
    return bool(row["close"] < row["open"] and upper_wick >= 0.5 * rng)


def confluence_score_baseline(
    df, candidate, atr, rsi, trend, divergences, pa_scale=1.0,
    rsi_series=None, macd_line=0.0, macd_histogram=0.0, macd_histogram_prev=0.0,
):
    """v4 original: simple binary divergence check."""
    factors = {}
    last = df.iloc[-1]
    pa = 0.0
    if _is_reversal_candle(last, candidate.bullish):
        pa += 15.0
        vol_ma = df["volume"].tail(VOLUME_MA_WINDOW).mean()
        if vol_ma > 0 and last["volume"] >= 1.5 * vol_ma:
            pa += 10.0
    factors["price_action"] = pa * pa_scale
    if trend == ("bullish" if candidate.bullish else "bearish"):
        factors["htf_trend"] = 25
    elif trend == "unknown":
        factors["htf_trend"] = 10
    else:
        factors["htf_trend"] = 0
    div_families = divergences or {}
    rsi_divs = div_families.get("rsi", [])
    rsi_score = 0
    if any(bool(d.get("bullish")) == candidate.bullish for d in rsi_divs):
        rsi_score += 8
    elif any(d.get("bullish") is not None for d in rsi_divs):
        rsi_score -= 5
    if (candidate.bullish and rsi <= 35) or (not candidate.bullish and rsi >= 65):
        rsi_score += 7
    elif (candidate.bullish and rsi <= 45) or (not candidate.bullish and rsi >= 55):
        rsi_score += 4
    factors["rsi"] = rsi_score
    tail = df["low"].tail(SWING_LOOKBACK) if candidate.bullish else df["high"].tail(SWING_LOOKBACK)
    swing = tail.min() if candidate.bullish else tail.max()
    mid = (candidate.prz_low + candidate.prz_high) / 2
    factors["structure"] = 15 if abs(mid - swing) <= ATR_PRZ_SWEEP * atr else 0
    macd_divs = div_families.get("macd", [])
    factors["macd"] = 10 if any(bool(d.get("bullish")) == candidate.bullish for d in macd_divs) else 0
    factors["funding"] = 5
    return sum(factors.values()), factors


# ─── Optimized confluence_score (v5) ─────────────────────────────────────────


def _rsi_zone_score(rsi: float, bullish: bool, rsi_series) -> float:
    score = 0
    rsi_recent = rsi_series.tail(5).values if rsi_series is not None and len(rsi_series) >= 2 else []
    rsi_rising = len(rsi_recent) >= 2 and rsi_recent[-1] > rsi_recent[0]
    if bullish:
        if rsi <= 30: score += 7
        elif rsi <= 40: score += 5
        elif rsi <= 50: score += 2
        if score > 0 and rsi_rising: score += 3
        if rsi >= 60: score -= 3
    else:
        if rsi >= 70: score += 7
        elif rsi >= 60: score += 5
        elif rsi >= 50: score += 2
        if score > 0 and not rsi_rising: score += 3
        if rsi <= 40: score -= 3
    return score


def confluence_score_optimized(
    df, candidate, atr, rsi, trend, divergences, pa_scale=1.0,
    rsi_series=None, macd_line=0.0, macd_histogram=0.0, macd_histogram_prev=0.0,
):
    """v5: Regular/Hidden filtering, MACD zero-line, RSI zone+trend, dual-confirm."""
    factors = {}
    last = df.iloc[-1]
    pa = 0.0
    if _is_reversal_candle(last, candidate.bullish):
        pa += 15.0
        vol_ma = df["volume"].tail(VOLUME_MA_WINDOW).mean()
        if vol_ma > 0 and last["volume"] >= 1.5 * vol_ma:
            pa += 10.0
    factors["price_action"] = pa * pa_scale
    if trend == ("bullish" if candidate.bullish else "bearish"):
        factors["htf_trend"] = 25
    elif trend == "unknown":
        factors["htf_trend"] = 10
    else:
        factors["htf_trend"] = 0

    div_families = divergences or {}
    rsi_divs = div_families.get("rsi", [])
    rsi_regular_bull = [d for d in rsi_divs if d.get("name") == "Regular" and d.get("bullish") is True]
    rsi_regular_bear = [d for d in rsi_divs if d.get("name") == "Regular" and d.get("bullish") is False]
    rsi_hidden_bull = [d for d in rsi_divs if d.get("name") == "Hidden" and d.get("bullish") is True]
    rsi_hidden_bear = [d for d in rsi_divs if d.get("name") == "Hidden" and d.get("bullish") is False]
    rsi_score = 0
    if candidate.bullish:
        if rsi_regular_bull: rsi_score += 8
        elif rsi_hidden_bull: rsi_score -= 5
    else:
        if rsi_regular_bear: rsi_score += 8
        elif rsi_hidden_bear: rsi_score -= 5
    rsi_score += _rsi_zone_score(rsi, candidate.bullish, rsi_series if rsi_series is not None else pd.Series([]))
    factors["rsi"] = rsi_score

    tail = df["low"].tail(SWING_LOOKBACK) if candidate.bullish else df["high"].tail(SWING_LOOKBACK)
    swing = tail.min() if candidate.bullish else tail.max()
    mid = (candidate.prz_low + candidate.prz_high) / 2
    factors["structure"] = 15 if abs(mid - swing) <= ATR_PRZ_SWEEP * atr else 0

    macd_divs = div_families.get("macd", [])
    macd_regular_bull = [d for d in macd_divs if d.get("name") == "Regular" and d.get("bullish") is True]
    macd_regular_bear = [d for d in macd_divs if d.get("name") == "Regular" and d.get("bullish") is False]
    macd_hidden_bull = [d for d in macd_divs if d.get("name") == "Hidden" and d.get("bullish") is True]
    macd_hidden_bear = [d for d in macd_divs if d.get("name") == "Hidden" and d.get("bullish") is False]
    macd_score = 0
    if candidate.bullish:
        if macd_regular_bull: macd_score += 10
        elif macd_hidden_bull: macd_score -= 5
    else:
        if macd_regular_bear: macd_score += 10
        elif macd_hidden_bear: macd_score -= 5
    factors["macd"] = macd_score

    if candidate.bullish:
        factors["macd_zero"] = 8 if macd_line < 0 else -4
    else:
        factors["macd_zero"] = 8 if macd_line > 0 else -4

    has_rsi_regular = (candidate.bullish and rsi_regular_bull) or (not candidate.bullish and rsi_regular_bear)
    has_macd_regular = (candidate.bullish and macd_regular_bull) or (not candidate.bullish and macd_regular_bear)
    if has_rsi_regular and has_macd_regular:
        factors["dual_confirm"] = 8
    elif has_rsi_regular or has_macd_regular:
        factors["dual_confirm"] = 3
    else:
        factors["dual_confirm"] = 0

    if candidate.bullish:
        factors["histogram"] = 5 if (macd_histogram > 0 and macd_histogram > macd_histogram_prev) else 0
    else:
        factors["histogram"] = 5 if (macd_histogram < 0 and macd_histogram < macd_histogram_prev) else 0

    factors["funding"] = 5
    return sum(factors.values()), factors


import pandas as pd


# ─── Patch + run helper ───────────────────────────────────────────────────────


def _run_backtest(df, symbol, interval, *, window, step, horizon, confluence_fn):
    """Run walk_forward with a patched confluence_score."""
    import app.services.signal_engine as se
    import app.services.signal_engine as signal_engine_module

    orig = signal_engine_module.confluence_score
    signal_engine_module.confluence_score = confluence_fn

    try:
        from scripts.backtest_harmonic_lib import walk_forward, aggregate_records
        records = walk_forward(
            df, symbol, interval,
            window=window, step=step, horizon=horizon,
        )
    finally:
        signal_engine_module.confluence_score = orig

    summary = aggregate_records(records)
    return records, summary


# ─── Report writing ───────────────────────────────────────────────────────────


def _scrub(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _write_report(out_dir: Path, name: str, config: dict, summary: dict, records: list):
    report = {"config": config, "summary": summary, "signals": _scrub([asdict(r) for r in records])}
    (out_dir / f"{name}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    lines = [
        f"# {name.upper()} — {config['symbol']} {config['interval']} ({config['days']}d)",
        "",
        "## Config",
        f"- window: {config['window']} bars  step: {config['step']}  horizon: {config['horizon']}",
        "",
        "## Summary",
        f"- signals: **{summary['total_signals']}**  decisions: {summary['decisions']}  skipped: {summary['skipped_signals']}",
        f"- wins / losses / scratches: {summary['wins']} / {summary['losses']} / {summary['scratches']}",
        f"- **win rate: {summary['win_rate']:.1%}**",
        f"- **avg R: {summary['avg_r']:+.2f}**  total R: {summary['total_r']:+.2f}",
        f"- profit factor: {summary['profit_factor']}",
        "",
    ]
    if summary.get("by_grade"):
        lines += ["## By grade", ""]
        for g, b in sorted(summary["by_grade"].items()):
            wr = b["wins"] / (b["wins"] + b["losses"]) if (b["wins"] + b["losses"]) else 0
            lines.append(f"- {g}: n={b['count']} wr={wr:.1%} R={b['r']:+.2f}")
        lines.append("")
    if summary.get("by_family"):
        lines += ["## By family", ""]
        for f, b in sorted(summary["by_family"].items()):
            wr = b["wins"] / (b["wins"] + b["losses"]) if (b["wins"] + b["losses"]) else 0
            lines.append(f"- {f}: n={b['count']} wr={wr:.1%} R={b['r']:+.2f}")
        lines.append("")
    (out_dir / f"{name}.md").write_text("\n".join(lines))


def _comparison_md(baseline: dict, optimized: dict) -> str:
    b = baseline["summary"]
    o = optimized["summary"]

    def _wr(s):
        return f"{s['win_rate']:.1%}" if s["decisions"] > 0 else "N/A"
    def _ar(s):
        return f"{s['avg_r']:+.2f}"
    def _pf(s):
        return "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
    def _delta(new, old):
        d = new - old
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.1%}" if abs(d) < 2 else f"{sign}{d:+.2f}"

    b_wr = b["win_rate"]
    o_wr = o["win_rate"]
    b_ar = b["avg_r"]
    o_ar = o["avg_r"]
    wr_delta = o_wr - b_wr
    ar_delta = o_ar - b_ar

    lines = [
        f"# BTC 4H Backtest Comparison: Baseline vs Optimized",
        "",
        "## Headline",
        "",
        f"| metric | baseline | optimized | delta |",
        f"|--------|----------|-----------|-------|",
        f"| win rate | {_wr(b)} | {_wr(o)} | {_delta(o_wr, b_wr)} |",
        f"| avg R | {_ar(b)} | {_ar(o)} | {ar_delta:+.2f} |",
        f"| profit factor | {_pf(b)} | {_pf(o)} | |",
        f"| total signals | {b['total_signals']} | {o['total_signals']} | |",
        f"| decisions | {b['decisions']} | {o['decisions']} | |",
        "",
        "## Win Rate Delta by Grade",
        "",
        f"| grade | baseline WR | optimized WR | delta |",
        f"|-------|-------------|--------------|-------|",
    ]
    all_grades = set(b.get("by_grade", {})) | set(o.get("by_grade", {}))
    for g in sorted(all_grades):
        bb = b.get("by_grade", {}).get(g, {"wins": 0, "losses": 0})
        bo = o.get("by_grade", {}).get(g, {"wins": 0, "losses": 0})
        b_wr_g = bb["wins"] / (bb["wins"] + bb["losses"]) if (bb["wins"] + bb["losses"]) else 0
        o_wr_g = bo["wins"] / (bo["wins"] + bo["losses"]) if (bo["wins"] + bo["losses"]) else 0
        lines.append(f"| {g} | {b_wr_g:.1%} | {o_wr_g:.1%} | {_delta(o_wr_g, b_wr_g)} |")

    lines += ["", "## Win Rate Delta by Family", "", f"| family | baseline WR | optimized WR | delta |", f"|--------|-------------|--------------|-------|"]
    all_families = set(b.get("by_family", {})) | set(o.get("by_family", {}))
    for f in sorted(all_families):
        bb = b.get("by_family", {}).get(f, {"wins": 0, "losses": 0})
        bo = o.get("by_family", {}).get(f, {"wins": 0, "losses": 0})
        b_wr_f = bb["wins"] / (bb["wins"] + bb["losses"]) if (bb["wins"] + bb["losses"]) else 0
        o_wr_f = bo["wins"] / (bo["wins"] + bo["losses"]) if (bo["wins"] + bo["losses"]) else 0
        lines.append(f"| {f} | {b_wr_f:.1%} | {o_wr_f:.1%} | {_delta(o_wr_f, b_wr_f)} |")

    lines += ["", "## Interpretation", ""]
    if wr_delta > 0.02:
        lines.append(f"✅ **Optimized outperforms baseline by {wr_delta:.1%} win rate.**")
    elif wr_delta < -0.02:
        lines.append(f"⚠️ **Optimized underperforms by {abs(wr_delta):.1%}.**")
    else:
        lines.append(f"ℹ️ **Marginal difference ({wr_delta:+.1%}).**")
    if ar_delta > 0.1:
        lines.append(f"✅ **Avg R improved by {ar_delta:+.2f}.**")
    elif ar_delta < -0.1:
        lines.append(f"⚠️ **Avg R decreased by {abs(ar_delta):.2f}.**")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="BTC 4H RSI+MACD optimization backtest")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--window", type=int, default=200)
    parser.add_argument("--step", type=int, default=12)
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--out-dir", default="docs/_backtest_artifacts")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "symbol": args.symbol,
        "interval": args.interval,
        "days": args.days,
        "window": args.window,
        "step": args.step,
        "horizon": args.horizon,
    }

    df = fetch_data(args.symbol, args.interval, args.days)

    # ── Baseline ──
    print("\n[1/2] Running BASELINE (v4) backtest…")
    t0 = time.time()
    baseline_records, baseline_summary = _run_backtest(
        df, args.symbol, args.interval,
        window=args.window, step=args.step, horizon=args.horizon,
        confluence_fn=confluence_score_baseline,
    )
    _write_report(out_dir, "baseline", config, baseline_summary, baseline_records)
    print(f"  → {len(baseline_records)} signals, {baseline_summary['decisions']} decisions, "
          f"win rate {baseline_summary['win_rate']:.1%}, {time.time()-t0:.1f}s")

    # ── Optimized ──
    print("\n[2/2] Running OPTIMIZED (v5) backtest…")
    t0 = time.time()
    optimized_records, optimized_summary = _run_backtest(
        df, args.symbol, args.interval,
        window=args.window, step=args.step, horizon=args.horizon,
        confluence_fn=confluence_score_optimized,
    )
    _write_report(out_dir, "optimized", config, optimized_summary, optimized_records)
    print(f"  → {len(optimized_records)} signals, {optimized_summary['decisions']} decisions, "
          f"win rate {optimized_summary['win_rate']:.1%}, {time.time()-t0:.1f}s")

    # ── Comparison ──
    baseline_report = {"config": config, "summary": baseline_summary, "signals": _scrub([asdict(r) for r in baseline_records])}
    optimized_report = {"config": config, "summary": optimized_summary, "signals": _scrub([asdict(r) for r in optimized_records])}
    comparison = {"baseline": baseline_report, "optimized": optimized_report}
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False, default=str))
    (out_dir / "comparison.md").write_text(_comparison_md(baseline_report, optimized_report))

    print(f"\n✅ Reports written to {out_dir}/")
    print(f"   - baseline.json / baseline.md")
    print(f"   - optimized.json / optimized.md")
    print(f"   - comparison.json / comparison.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
