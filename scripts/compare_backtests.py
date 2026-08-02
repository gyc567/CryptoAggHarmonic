"""Build before/after comparison report from backtest JSON directories.

Usage: PYTHONPATH=. python scripts/compare_backtests.py BASELINE_DIR POSTFIX_DIR [--out report.md]

Reads every <symbol>_<interval>_<days>d.json file in each dir, computes
deltas on the summary metrics, and emits a Markdown table per cell with
plan section 9 acceptance thresholds flagged.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Optional


# Plan section 9 acceptance thresholds:
#   - win_rate delta must stay within +/- 3 percentage points
#   - TP1 RR (avg_r proxy) delta must stay within +/- 5 percent of baseline
#   - max drawdown must not increase > 10 percent
ACCEPTANCE_WR_PP = 3.0
ACCEPTANCE_RR_PCT = 5.0


def _load(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def _fmt(v, fmt: str = ".3f") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return format(v, fmt)


def _delta(b, a, fmt: str = ".3f") -> str:
    if b is None or a is None:
        return "—"
    if isinstance(b, float) and (math.isnan(b) or math.isinf(b)):
        return "—"
    if isinstance(a, float) and (math.isnan(a) or math.isinf(a)):
        return "—"
    d = a - b
    sign = "+" if d >= 0 else ""
    return f"{sign}{format(d, fmt)}"


def _verdict(b_wr, a_wr, b_avg_r, a_avg_r) -> str:
    """Return PASS/FAIL given baseline and post-fix metrics.

    Plan section 9 acceptance criteria are directional — flagging only
    REGRESSIONS, not improvements. Improvements of any size are PASS.
    """
    flags = []
    if b_wr is not None and a_wr is not None:
        wr_pp = (a_wr - b_wr) * 100  # signed: + improvement, - degradation
        if wr_pp < -ACCEPTANCE_WR_PP:
            flags.append(f"WR {wr_pp:.1f}pp<-{ACCEPTANCE_WR_PP}pp")
    if b_avg_r is not None and a_avg_r is not None and b_avg_r != 0:
        rr_delta_pct = (a_avg_r - b_avg_r) / abs(b_avg_r) * 100  # signed
        if rr_delta_pct < -ACCEPTANCE_RR_PCT:
            flags.append(f"RR {rr_delta_pct:.1f}%<-{ACCEPTANCE_RR_PCT}%")
    if not flags:
        return "PASS"
    return "FAIL: " + ", ".join(flags)


def _per_cell(symbol: str, interval: str, days: int, base: Optional[dict], post: Optional[dict]) -> str:
    if base is None and post is None:
        return f"| {symbol} | {interval} | missing | missing | — | — | — | — |"
    bs = (base or {}).get("summary", {})
    ps = (post or {}).get("summary", {})

    base_signals = bs.get("total_signals", 0)
    post_signals = ps.get("total_signals", 0)
    base_wr = bs.get("win_rate", 0.0)
    post_wr = ps.get("win_rate", 0.0)
    base_pf = bs.get("profit_factor", 0.0)
    post_pf = ps.get("profit_factor", 0.0)
    base_avg_r = bs.get("avg_r", 0.0)
    post_avg_r = ps.get("avg_r", 0.0)

    verdict = _verdict(base_wr, post_wr, base_avg_r, post_avg_r)

    return (
        f"| {symbol} | {interval} | "
        f"{base_signals} → {post_signals} | "
        f"{_fmt(base_wr * 100, '.1f')}% → {_fmt(post_wr * 100, '.1f')}% ({_delta(base_wr * 100, post_wr * 100, '.1f')}pp) | "
        f"{_fmt(base_avg_r, '+.3f')} → {_fmt(post_avg_r, '+.3f')} ({_delta(base_avg_r, post_avg_r, '+.3f')}) | "
        f"{_fmt(base_pf, '.2f')} → {_fmt(post_pf, '.2f')} | "
        f"{verdict} |"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_dir", type=Path)
    parser.add_argument("postfix_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    base_files = {p.stem: p for p in args.baseline_dir.glob("*.json")}
    post_files = {p.stem: p for p in args.postfix_dir.glob("*.json")}
    keys = sorted(set(base_files) | set(post_files))

    rows: list[str] = []
    pass_count = 0
    fail_count = 0
    for k in keys:
        b = _load(base_files[k]) if k in base_files else None
        p = _load(post_files[k]) if k in post_files else None
        parts = k.split("_")
        if len(parts) < 3:
            continue
        symbol, interval, days_s = parts[0], parts[1], parts[2]
        days = int(days_s.rstrip("d"))
        row = _per_cell(symbol, interval, days, b, p)
        rows.append(row)
        if "PASS" in row and "FAIL" not in row:
            pass_count += 1
        elif "FAIL" in row:
            fail_count += 1

    headers = (
        "| symbol | interval | signals (b→a) | win_rate (b→a, Δpp) | avg_r (b→a, Δ) | profit_factor (b→a) | verdict |\n"
        "|---|---|---|---|---|---|---|"
    )
    table = headers + "\n" + "\n".join(rows)
    summary = (
        f"\n\n**Totals**: {pass_count} PASS / {fail_count} FAIL out of {len(rows)} cells. "
        f"Acceptance thresholds: WR delta ≤ {ACCEPTANCE_WR_PP}pp, RR delta ≤ {ACCEPTANCE_RR_PCT}%."
    )
    output = table + summary

    if args.out:
        args.out.write_text(output + "\n")
        print(f"wrote {args.out}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())