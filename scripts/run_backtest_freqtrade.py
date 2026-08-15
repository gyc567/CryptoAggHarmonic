#!/usr/bin/env python3
"""
run_backtest_freqtrade.py

Unified RSI strategy backtest — two modes:

Mode A — Local (no API key needed):
    Loads feather data directly, runs the pure-Python event-driven backtest
    from app.domain.rsi_trend_backtest.py (same logic as the API endpoint).

Mode B — Freqtrade (requires Binance API key):
    Converts feather → CSV, writes config.json, then shells out to
    `freqtrade backtesting`.  Useful when you have real API keys.

Usage
~~~~~
    # Local backtest (default, no API key needed):
    python scripts/run_backtest_freqtrade.py

    # Local, custom params:
    python scripts/run_backtest_freqtrade.py \
        --symbol BTC_USDT --interval 1h \
        --strategy-params rsi_zone=pullback,atr_mult=1.5,use_ema50=true

    # Freqtrade mode (requires Binance API key in BINANCE_API_KEY env var):
    BINANCE_API_KEY=xxx BINANCE_SECRET=yyy python scripts/run_backtest_freqtrade.py --freqtrade

    # Dry run (show what would happen):
    python scripts/run_backtest_freqtrade.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd

# Project root
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

# Feather data directory — set FEATHER_DIR env var or use freqtrade_dev_mcp/user_data/data
FEATHER_DIR = Path(os.environ.get(
    "FEATHER_DIR",
    str(ROOT / "freqtrade_dev_mcp" / "user_data" / "data" / "binance"),
))

FREQTRADE_ROOT = ROOT / "freqtrade_dev_mcp"
FREQTRADE_UD = FREQTRADE_ROOT / "user_data"
STRAT_FILE = FREQTRADE_UD / "strategies" / "trend_rsi_strategy.py"
STRAT_NAME = "TrendRSI"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_backtest_freqtrade")


# ==========================================================================
# Strategy param overrides (passed to detect_signals / run_backtest)
# ==========================================================================

def build_param_overrides(raw: str) -> dict:
    out = {}
    for item in raw.split(","):
        item = item.strip()
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        if val.lower() == "true":
            val = True
        elif val.lower() == "false":
            val = False
        elif "." in val:
            try:
                val = float(val)
            except ValueError:
                pass
        else:
            try:
                val = int(val)
            except ValueError:
                pass
        out[key.strip()] = val
    return out


# ==========================================================================
# Mode A: Local pure-Python backtest (no API key needed)
# ==========================================================================

def load_feather_data(symbol: str, interval: str) -> pd.DataFrame | None:
    """Load and sort feather data for symbol/interval."""
    pair_map = {
        "BTC_USDT": "BTC_USDT",
        "ETH_USDT": "ETH_USDT",
        "SOL_USDT": "SOL_USDT",
        "BNB_USDT": "BNB_USDT",
    }
    pair = pair_map.get(symbol, symbol)
    feather_path = FEATHER_DIR / f"{pair}-{interval}.feather"
    if not feather_path.exists():
        log.error("Feather file not found: %s", feather_path)
        return None
    df = pd.read_feather(str(feather_path))
    df = df.sort_values("timestamp").reset_index(drop=True)
    # Convert ms timestamp → UTC datetime column
    df["dts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def run_local_backtest(
    symbol: str,
    interval: str,
    lookback_days: int,
    strategy_params: dict,
) -> dict:
    """
    Run the pure-Python event-driven backtest using RSI strategy logic.
    """
    sys.path.insert(0, str(ROOT))
    from app.domain.rsi_trend import detect_signals
    from app.domain.rsi_trend_backtest import run_backtest

    log.info("Loading feather data: %s %s", symbol, interval)
    df = load_feather_data(symbol, interval)
    if df is None:
        return {"success": False, "error": "Failed to load data"}

    # Trim to lookback window
    if lookback_days:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=lookback_days)
        df = df[df["dts"] >= cutoff].reset_index(drop=True)
        log.info("  After lookback filter: %d rows", len(df))

    if len(df) < 250:
        return {"success": False, "error": f"Not enough data: {len(df)} rows"}

    log.info("Running RSI strategy backtest ...")
    log.info("  Params: %s", strategy_params)

    # Map strategy params → detect_signals kwargs
    signal_kwargs = {
        "use_ema50": strategy_params.get("use_ema50", False),
        "require_candle_color": strategy_params.get("require_candle_color", False),
        "atr_mult": strategy_params.get("atr_mult", 1.0),
        "rsi_zone": strategy_params.get("rsi_zone", "extreme"),
        "reward_risk": strategy_params.get("reward_risk", 2.0),
        "min_quality_score": strategy_params.get("min_quality_score", 0.0),
        "short_rsi_min": strategy_params.get("short_rsi_min", 65.0),
    }
    # Backtest kwargs
    bt_kwargs = {
        "partial_mode": strategy_params.get("partial_mode", False),
        "trailing_stop": strategy_params.get("trailing_stop", False),
        "exit_ema": strategy_params.get("exit_ema", "ema200"),
        "ttl_bars": strategy_params.get("ttl_bars", 0),
    }

    signals = detect_signals(df, **signal_kwargs)
    log.info("  %d signals detected", len(signals))

    if not signals:
        return {
            "success": True,
            "total_signals": 0,
            "trades_count": 0,
            "message": "No signals generated with current parameters",
        }

    result = run_backtest(df, signals, **bt_kwargs)
    return {"success": True, **result.to_dict()}


def print_local_results(metrics: dict) -> None:
    print("\n" + "=" * 60)
    print("  TrendRSI  —  Local Backtest Results")
    print("=" * 60)
    if not metrics.get("success"):
        print(f"  ⚠  {metrics.get('error', 'Unknown error')}")
        return

    trades = metrics.get("trades_count", 0)
    print(f"\n  Total Signals  : {metrics.get('total_signals', 0)}")
    print(f"  Trades        : {trades}")
    if trades == 0:
        print("\n  ⚠  No trades generated.")
        return

    wins = metrics.get("win_count", 0)
    losses = metrics.get("loss_count", 0)
    scratches = metrics.get("scratch_count", 0)
    wr = metrics.get("win_rate", 0) * 100
    avg_r = metrics.get("avg_r", 0)
    total_r = metrics.get("total_r", 0)
    pf = metrics.get("profit_factor")
    max_dd = metrics.get("max_drawdown_r", 0)
    avg_bars = metrics.get("avg_bars_held", 0)

    print(f"  Wins          : {wins}")
    print(f"  Losses        : {losses}")
    print(f"  Scratches     : {scratches}")
    print(f"  Win Rate      : {wr:.1f} %")
    print(f"  Avg R         : {avg_r:+.2f} R")
    print(f"  Total R       : {total_r:+.2f} R")
    print(f"  Profit Factor : {pf if pf is not None else 'N/A'}")
    print(f"  Max Drawdown  : {max_dd:.2f} R")
    print(f"  Avg Bars Held : {avg_bars:.1f}")

    # Exit breakdown
    if trades > 0:
        exit_reasons: dict[str, int] = {}
        for t in metrics.get("trades", []):
            exit_reasons[t["exit_reason"]] = exit_reasons.get(t["exit_reason"], 0) + 1
        print(f"\n  Exit Reasons")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:<20} {count:>4}")

    print("\n" + "=" * 60)


# ==========================================================================
# Mode B: Freqtrade backtest (requires API key)
# ==========================================================================

def convert_feather_data() -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "feather_to_freqtrade.py")],
        check=True,
    )


def write_freqtrade_config(api_key: str = "", api_secret: str = "") -> Path:
    config = {
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": 1.0,
        "fiat_display_currency": "USD",
        "timeframe": "1h",
        "dry_run_wallet": 10_000,
        "dry_run": True,
        "unfilledtimeout": {
            "entry": 10,
            "exit": 10,
            "exit_timeout_count": 0,
            "unit": "minutes",
        },
        "entry_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
            "price_last_balance": 0.0,
            "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
        },
        "exit_pricing": {
            "price_side": "same",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exchange": {
            "name": "binance",
            "key": api_key,
            "secret": api_secret,
            "ccxt_config": {},
            "ccxt_async_config": {},
            "pair_whitelist": ["BTC/USDT", "ETH/USDT"],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "edge": {"enabled": False},
        "bot_name": "TrendRSI_backtest",
    }
    config_path = FREQTRADE_ROOT / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    return config_path


def run_freqtrade_backtest(
    symbol: str,
    interval: str,
    timerange: str,
    strategy_params: dict,
) -> subprocess.CompletedProcess:
    config_path = write_freqtrade_config(
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_SECRET", ""),
    )
    pair = symbol.replace("_", "/")
    cmd = [
        "freqtrade", "backtesting",
        "--config", str(config_path),
        "--strategy", STRAT_NAME,
        "--strategy-path", str(STRAT_FILE.parent),
        "--data-dir", str(FREQTRADE_UD),
        "--timerange", timerange,
        "--timeframe", interval,
        "--pairs", pair,
        "--export", "trades",
        "--export-directory", str(FREQTRADE_UD / "backtest_results"),
        "--fee", "0.001",
    ]
    for key, val in strategy_params.items():
        cmd += ["--strategy-params", f"{key}={val}"]
    log.info("CMD: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(FREQTRADE_ROOT),
    )


def parse_freqtrade_output(stdout: str) -> dict:
    result: dict = {}
    lines = stdout.splitlines()

    # Per-pair summary line
    pair_pat = re.compile(
        r"^\s*([\w_/]+)\s*,\s*(\w+)\s*\|\s*"
        r"(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|\s*"
        r"([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*"
        r"([\d.]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|"
    )
    for line in lines:
        m = pair_pat.search(line)
        if m:
            result.update({
                "pair": m.group(1), "timeframe": m.group(2),
                "total_trades": int(m.group(3)),
                "win_rate": float(m.group(4)),
                "max_drawdown": float(m.group(5)),
                "profit_factor": float(m.group(6)),
                "avg_duration": float(m.group(7)),
                "drawdown": float(m.group(8)),
                "profit_total": float(m.group(9)),
                "holding_avg": float(m.group(10)),
            })
    return result


# ==========================================================================
# Main
# ==========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run TrendRSI backtest (local or freqtrade)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
            # Local backtest — no API key needed:
            python scripts/run_backtest_freqtrade.py

            # Local with custom RSI zone:
            python scripts/run_backtest_freqtrade.py \\
                --strategy-params rsi_zone=pullback,atr_mult=1.5

            # Freqtrade backtest — requires BINANCE_API_KEY + BINANCE_SECRET env vars:
            BINANCE_API_KEY=xxx BINANCE_SECRET=yyy python scripts/run_backtest_freqtrade.py --freqtrade

            # Dry run:
            python scripts/run_backtest_freqtrade.py --dry-run
            """),
    )
    parser.add_argument("--symbol",    default="BTC_USDT")
    parser.add_argument("--interval", default="1h", choices=["15m","1h","4h","1d"])
    parser.add_argument("--timerange", default="",
                        help="freqtrade timerange, e.g. 20230101-20231231")
    parser.add_argument("--lookback-days", type=int, default=0,
                        help="Limit data to last N days (local backtest only)")
    parser.add_argument("--strategy-params", default="",
                        help="Comma-separated key=val overrides")
    parser.add_argument("--freqtrade", action="store_true",
                        help="Run via freqtrade CLI instead of local engine")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Show what would run, don't execute")

    args = parser.parse_args()
    params = build_param_overrides(args.strategy_params)

    log.info("=" * 60)
    mode = "freqtrade" if args.freqtrade else "local"
    log.info("Mode: %s  |  Symbol: %s  |  Interval: %s", mode, args.symbol, args.interval)
    log.info("Strategy params: %s", params or "(defaults)")
    log.info("=" * 60)

    if args.dry_run:
        log.info("[DRY RUN] Nothing executed.")
        return

    # ── FREQTRADE MODE ────────────────────────────────────────────────────
    if args.freqtrade:
        log.info("[Mode B] Freqtrade backtest (requires API key) ...")
        convert_feather_data()
        proc = run_freqtrade_backtest(
            symbol=args.symbol,
            interval=args.interval,
            timerange=args.timerange,
            strategy_params=params,
        )
        print("\n" + "=" * 60)
        print("  Freqtrade stdout (last 60 lines)")
        print("=" * 60)
        for line in proc.stdout.splitlines()[-60:]:
            print("  ", line)
        if proc.stderr:
            print("\n  Stderr (last 20):")
            for line in proc.stderr.splitlines()[-20:]:
                print("  ", line)
        metrics = parse_freqtrade_output(proc.stdout)
        print("\n  Parsed metrics:", metrics if metrics else "(none)")
        return

    # ── LOCAL MODE ─────────────────────────────────────────────────────────
    log.info("[Mode A] Local backtest (no API key) ...")
    metrics = run_local_backtest(
        symbol=args.symbol,
        interval=args.interval,
        lookback_days=args.lookback_days,
        strategy_params=params,
    )
    print_local_results(metrics)


if __name__ == "__main__":
    main()
