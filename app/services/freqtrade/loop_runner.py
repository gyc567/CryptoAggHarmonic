"""Freqtrade Strategy Loop runner.

This is the entry point for the GitHub Actions workflow
`.github/workflows/freqtrade-strategy-loop.yml`.

Usage:
    python -m app.services.freqtrade.loop_runner --snapshot tuning_snapshots/pareto-{sha}.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from app.services.freqtrade.handshake import write_hyperopt_to_history
from app.services.freqtrade.mcp_client import MCP
from app.services.freqtrade.translator import (
    HarmonicSignal,
    TranslatorConfig,
    translate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run_loop(snapshot_path: str, workers: int = 2) -> None:
    """Run the freqtrade strategy loop.

    Args:
        snapshot_path: Path to a cryptoagg tuning snapshot YAML.
        workers: Number of parallel workers (currently unused — MCP is sequential).
    """
    snapshot = Path(snapshot_path)
    if not snapshot.exists():
        logger.error(f"Snapshot not found: {snapshot_path}")
        sys.exit(1)

    # Load snapshot
    with open(snapshot) as f:
        data = yaml.safe_load(f)

    logger.info(f"Loaded snapshot: {snapshot.name}")

    # Parse into HarmonicSignal (simplified — extend as needed)
    signal = HarmonicSignal(
        pattern_type=data.get("pattern_type", "Gartley"),
        entry_price=data.get("entry_price"),
        exit_price=data.get("exit_price"),
        stop_loss=data.get("stop_loss"),
        zrpc_price=data.get("zrpc_price"),
        confidence=data.get("confidence", 0.7),
        regime=data.get("regime"),
    )

    config = TranslatorConfig(
        timeframe=data.get("timeframe", "1h"),
        stake_amount=data.get("stake_amount", 100.0),
        dry_run=True,
    )

    # Step 1: Translate signal → FreqtradeStrategy
    strategy_path = translate(signal, config, mode="pattern")
    logger.info(f"Generated strategy: {strategy_path}")

    # Step 2: MCP — download candles + backtest
    async with MCP() as client:
        client.reset_gen_counter()

        # Download candles
        logger.info("Downloading candles...")
        download_result = await client.call_tool(
            "download_candles",
            pairs=["BTC/USDT:USDT"],
            timeframes=["1h"],
            date_range="last 3 months",
            exchange="binance",
        )
        logger.info(f"download_candles: {download_result.get('success', False)}")

        # Backtest
        strategy_name = strategy_path.stem
        logger.info(f"Running backtest for {strategy_name}...")
        backtest_result = await client.call_tool(
            "backtest_strategy",
            strategy_name=strategy_name,
            pairs=["BTC/USDT:USDT"],
            timerange="last 3 months",
            export_trades=True,
        )
        logger.info(f"backtest_strategy: {backtest_result.get('success', False)}")

        # Extract backtest data
        if backtest_result.get("success"):
            extract_result = await client.call_tool(
                "extract_backtest_data",
                result_path=backtest_result.get("result_path", ""),
                output_format="summary",
            )
            logger.info(f"extract_backtest_data: {extract_result.get('success', False)}")

    # Step 3: Write result to pending_issues if suspicious
    # (simplified — full implementation uses promotion_checklist)
    logger.info("Freqtrade Strategy Loop completed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freqtrade Strategy Loop runner")
    parser.add_argument("--snapshot", required=True, help="Path to tuning snapshot YAML")
    parser.add_argument("--workers", type=int, default=2, help="Number of parallel workers")
    args = parser.parse_args()

    asyncio.run(run_loop(args.snapshot, args.workers))


if __name__ == "__main__":
    main()
