"""Tests for app.services.freqtrade.handshake."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.freqtrade.handshake import (
    HyperoptResult,
    parse_hyperopt_yaml,
    _float_or_none,
)


class TestFloatOrNone:
    def test_valid_float(self) -> None:
        assert _float_or_none(0.5) == 0.5

    def test_valid_int(self) -> None:
        assert _float_or_none(3) == 3.0

    def test_none(self) -> None:
        assert _float_or_none(None) is None

    def test_string_float(self) -> None:
        assert _float_or_none("0.123") == 0.123

    def test_invalid_string(self) -> None:
        assert _float_or_none("abc") is None


class TestHyperoptResult:
    def test_hyperopt_result_dataclass(self) -> None:
        result = HyperoptResult(
            uuid=uuid.uuid4().hex,
            strategy_name="TestStrategy",
            hyperopt_path=Path("test.yaml"),
            win_rate=0.62,
            sharpe_ratio=1.34,
            calmar_ratio=2.1,
            max_drawdown=0.08,
            trade_count=847,
            timestamp=datetime.now(timezone.utc).isoformat(),
            hyperopt_epochs=500,
            best_params={"buy_rsi": 30},
            salt_version=1,
            source="freqtrade_hyperopt",
        )
        assert result.win_rate == 0.62
        assert result.source == "freqtrade_hyperopt"
        assert result.strategy_name == "TestStrategy"


class TestParseHyperoptYaml:
    def test_missing_file_raises(self) -> None:
        try:
            parse_hyperopt_yaml(Path("/nonexistent/hyperopt.yaml"))
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_parse_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = """
best_params:
  strategy_name: HarmonicGartley1h
  buy_rsi: 30
results_metric:
  win_rate: 0.62
  sharpe_ratio: 1.34
  calmar_ratio: 2.1
  max_drawdown: -0.08
  trade_count: 847
epochs: 500
"""
        yaml_file = tmp_path / "test.fthypt"
        yaml_file.write_text(yaml_content)

        result = parse_hyperopt_yaml(yaml_file)
        assert result.win_rate == 0.62
        assert result.sharpe_ratio == 1.34
        assert result.trade_count == 847
        assert result.hyperopt_epochs == 500

    def test_parse_yaml_handles_missing_fields(self, tmp_path: Path) -> None:
        yaml_content = """
best_params:
  strategy_name: MinimalStrategy
epochs: 100
"""
        yaml_file = tmp_path / "minimal.fthypt"
        yaml_file.write_text(yaml_content)

        result = parse_hyperopt_yaml(yaml_file)
        assert result.win_rate == 0.0
        assert result.sharpe_ratio == 0.0
        assert result.trade_count == 0
