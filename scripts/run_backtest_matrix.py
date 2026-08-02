#!/usr/bin/env python3
"""Backtest matrix runner: BTCUSDT/ETHUSDT/SOLUSDT x 1h/4h/1d.

Runs 9 cells across ~30 months of Binance history, writes JSON+MD per
cell under OUT_DIR.

Usage:
    PYTHONPATH=. python scripts/run_backtest_matrix.py OUT_DIR [--entry-mode {market,prz}]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


# Per-interval walk-forward parameters.  Window = max(pattern length, ~30).
# Step is chosen to give ~30-60 forward samples per cell while keeping
# runtime under ~60s per cell.
INTERVALS: dict[str, dict[str, int]] = {
    "1h": {"days": 900, "window": 72, "step": 24, "horizon": 72},
    "4h": {"days": 900, "window": 60, "step": 20, "horizon": 60},
    "1d": {"days": 900, "window": 45, "step": 15, "horizon": 45},
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument(
        "--entry-mode", choices=["market", "prz"], default="prz"
    )
    parser.add_argument(
        "--python", default=".venv/bin/python",
        help="path to python interpreter (default: .venv/bin/python)",
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="run only first N cells (debug)")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    py = args.python
    total = 0
    cells = [(s, i) for s in SYMBOLS for i in INTERVALS]
    if args.limit:
        cells = cells[: args.limit]
    total_cells = len(cells)

    t_overall = time.time()
    for n, (symbol, interval) in enumerate(cells, 1):
        params = INTERVALS[interval]
        slug = f"{symbol}_{interval}_{params['days']}d"
        print(f"[{n}/{total_cells}] {slug} ... ", end="", flush=True)
        t0 = time.time()
        cmd = [
            py, "scripts/backtest_harmonic.py",
            "--symbol", symbol,
            "--interval", interval,
            "--days", str(params["days"]),
            "--window", str(params["window"]),
            "--step", str(params["step"]),
            "--horizon", str(params["horizon"]),
            "--silent",
            "--entry-mode", args.entry_mode,
            "--out-dir", str(args.out_dir),
        ]
        # Inject PYTHONPATH=. so the subprocess finds app.* even when the
        # python interpreter is an absolute path outside the repo's bin.
        env = {"PYTHONPATH": ".", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        # Pass through parent env so venv shebangs work, then override.
        import os
        full_env = {**os.environ, **env}
        result = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
        elapsed = time.time() - t0
        if result.returncode != 0:
            print(f"FAIL ({elapsed:.1f}s)")
            print(result.stderr[-500:])
            return result.returncode
        print(f"OK ({elapsed:.1f}s)")
        total += 1

    print(f"\nDONE {total}/{total_cells} cells in {time.time() - t_overall:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())