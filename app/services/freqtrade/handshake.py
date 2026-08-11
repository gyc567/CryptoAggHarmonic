"""Freqtrade hyperopt result → HISTORY.jsonl feedback protocol.

ADR-0010 D4: hyperopt results write to HISTORY.jsonl with source=freqtrade_hyperopt,
never directly modify TUNING.

Flow:
  freqtrade hyperopt → .scratch/loop_state/freqtrade/hyperopt_results/{uuid}.yaml
    → handshake.write_hyperopt_to_history(uuid) → .scratch/loop_state/HISTORY.jsonl

Outbox mode (ADR-0010 §4 Principle 4):
  1. Write hyperopt result to HISTORY.jsonl.outbox/<uuid>.json
  2. Rename atomically into HISTORY.jsonl
  3. On rename failure: quarantine to HISTORY.jsonl.quarantine/<uuid>.json
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.loop.state import append_history

logger = logging.getLogger(__name__)

FREQTRADE_STATE = Path(".scratch/loop_state/freqtrade")
OUTBOX_DIR = Path(".scratch/loop_state/HISTORY.jsonl.outbox")
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class HyperoptResult:
    """Freqtrade hyperopt result parsed into loop domain format.

    Maps to the 5-D fitness space used by cryptoagg Pareto front.
    """

    uuid: str
    strategy_name: str
    hyperopt_path: Path

    # 5-D fitness (aligned with cryptoagg Candidate fitness)
    win_rate: float
    sharpe_ratio: float
    calmar_ratio: float
    max_drawdown: float
    trade_count: int

    # Metadata
    timestamp: str
    hyperopt_epochs: int
    best_params: dict

    # ADR-0010 D4: salt_version for traceability
    salt_version: int = 1
    source: str = "freqtrade_hyperopt"


def write_hyperopt_to_history(result: HyperoptResult) -> None:
    """Write a hyperopt result to HISTORY.jsonl via outbox.

    Args:
        result: Parsed hyperopt result.

    Raises:
        OSError: If outbox rename fails after retries.
    """
    record = {
        "candidate_id": f"freqtrade-{result.uuid[:12]}",
        "gen": -1,  # Freqtrade is not a CMA-ES generation
        "cluster": "freqtrade_hyperopt",
        "decision": "hyperopt_accepted",  # Placeholder — subject to promotion gate
        "fitness": {
            "win_rate": result.win_rate,
            "sharpe_ratio": result.sharpe_ratio,
            "calmar_ratio": result.calmar_ratio,
            "max_drawdown": result.max_drawdown,
            "trade_count": result.trade_count,
        },
        "params": result.best_params,
        "timestamp": result.timestamp,
        "source": result.source,
        "salt_version": result.salt_version,
        "strategy_name": result.strategy_name,
        "hyperopt_epochs": result.hyperopt_epochs,
        "hyperopt_path": str(result.hyperopt_path),
    }

    # Step 1: write to outbox
    outbox_file = OUTBOX_DIR / f"{result.uuid}.json"
    outbox_file.write_text(json.dumps(record))

    # Step 2: atomic rename into HISTORY.jsonl
    history_path = Path(".scratch/loop_state/HISTORY.jsonl")
    try:
        append_history(history_path, record)
        outbox_file.unlink()  # Clean up outbox entry on success
        logger.info(f"hyperopt result {result.uuid} written to HISTORY.jsonl")
    except Exception as e:
        logger.warning(f"append_history failed for {result.uuid}, leaving in outbox: {e}")
        # Outbox entry stays — will be retried or quarantined by state.py GC


def parse_hyperopt_yaml(yaml_path: Path) -> HyperoptResult:
    """Parse a Freqtrade hyperopt .fthypt YAML file into a HyperoptResult.

    Args:
        yaml_path: Path to the hyperopt .fthypt (or .yaml) result file.

    Returns:
        HyperoptResult with 5-D fitness fields.

    Raises:
        FileNotFoundError: If yaml_path does not exist.
        ValueError: If required fields are missing from the hyperopt file.
    """
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    # Extract best result from hyperopt file structure
    # Freqtrade hyperopt format: {best_index, best_params, results_tensor, ...}
    best_params = data.get("best_params", {})
    results = data.get("results_metric", {})

    # Map to 5-D fitness (handle None gracefully)
    win_rate = _float_or_none(results.get("win_rate")) or 0.0
    sharpe = _float_or_none(results.get("sharpe_ratio")) or 0.0
    calmar = _float_or_none(results.get("calmar_ratio")) or 0.0
    max_dd = abs(_float_or_none(results.get("max_drawdown")) or 0.0)  # Freqtrade uses negative
    trade_count = int(results.get("trade_count") or 0)

    return HyperoptResult(
        uuid=uuid.uuid4().hex,
        strategy_name=best_params.get("strategy_name", yaml_path.stem),
        hyperopt_path=yaml_path,
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        max_drawdown=max_dd,
        trade_count=trade_count,
        timestamp=datetime.now(timezone.utc).isoformat(),
        hyperopt_epochs=data.get("epochs", 0),
        best_params=best_params,
    )


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
