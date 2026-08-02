"""Build before/after comparison report from backtest JSON directories.

Usage: PYTHONPATH=. python scripts/compare_backtests.py BASELINE_DIR POSTFIX_DIR [--out report.md]

Reads every <symbol>_<interval>_<days>d.json file in each dir, computes
deltas on the summary metrics, and emits a Markdown table per cell.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Optional


def _load(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def _fmt(v, fmt: str = ".3f") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return format(v, fmt)


def _delta(b: Optional[float], a: Optional[float], fmt: str = ".3f") -> str:
    if b is None or a is None:
        return "—"
    if isinstance(b, float) and (math.isnan(b) or math.isinf(b)):
        return "—"
    if isinstance(a, float) and (math.isnan(a) or math.isinf(a)):
        return "—"
    d = a - b
    sign = "+" if d >= 0 else ""
    return f"{sign}{format(d, fmt)}"


def _per_cell(symbol: str, interval: str, days: int, base: Optional[dict], post: Optional[dict]) -> str:
    if base is None and post is None:
        return f"| {symbol} | {interval} | missing | missing | — | — | — | — |"
    bs = (base or {}).get("summary", {})
    ps = (post or {}).get("summary", {})

    base_signals = bs.get("total_signals", 0)
    post_signals = ps.get("total_signals", 0)
    base_wr = bs.get("win_rate", 0.0) * 100
    post_wr = ps.get("win_rate", 0.0) * 100
    base_pf = bs.get("profit_factor", 0.0)
    post_pf = ps.get("profit_factor", 0.0)

    return (
        f"| {symbol} | {interval} | "
        f"{base_signals} → {post_signals} | "
        f"{_fmt(base_wr, '.1f')}% → {_fmt(post_wr, '.1f')}% ({_delta(base_wr, post_wr, '.1f')}pp) | "
        f"{_fmt(bs.get('avg_r', 0.0), '+.2f')} → {_fmt(ps.get('avg_r', 0.0), '+.2f')} ({_delta(bs.get('avg_r', 0.0), ps.get('avg_r', 0.0), '+.2f')}) | "
        f"{_fmt(base_pf, '.2f')} → {_fmt(post_pf, '.2f')} |"
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
    for k in keys:
        b = _load(base_files[k]) if k in base_files else None
        p = _load(post_files[k]) if k in post_files else None
        # k is e.g. BTCUSDT_1d_900d
        parts = k.split("_")
        symbol, interval, days_s = parts[0], parts[1], parts[2]
        days = int(days_s.rstrip("d"))
        rows.append(_per_cell(symbol, interval, days, b, p))

    headers = (
        "| symbol | interval | signals | win_rate | avg_r | profit_factor |\n"
        "|---|---|---|---|---|---|"
    )
    table = headers + "\n" + "\n".join(rows)

    if args.out:
        args.out.write_text(table + "\n")
        print(f"wrote {args.out}")
    else:
        print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())