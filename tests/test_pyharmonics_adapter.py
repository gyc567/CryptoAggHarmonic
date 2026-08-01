"""Unit tests for the v2 forming view in app.services.analysis.

These tests stub out the heavy pieces (fetch_market_data, detect_patterns,
openai_handler, supabase uploads) and feed hand-crafted detection results
through ``AnalysisOrchestrator._build_forming_view`` and the full
``analyze()`` path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app.domain.enums import AnalysisType, Interval, Market
from app.domain.schemas import AnalyzeRequest
from app.services.analysis import AnalysisOrchestrator


def _make_df(n: int = 600) -> pd.DataFrame:
    closes = [100.0 + i * 0.2 for i in range(n)]
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "open": c,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 100.0,
                "close_time": 1_700_000_000 + i * 900,
            }
        )
    df = pd.DataFrame(rows)
    df["dts"] = pd.to_datetime(df["close_time"], unit="s", utc=True)
    return df


def _make_request(analysis_type: AnalysisType = AnalysisType.FORMING) -> AnalyzeRequest:
    return AnalyzeRequest(
        market=Market.BINANCE,
        symbol="BTCUSDT",
        interval=Interval.H4,
        analysis_type=analysis_type,
        limit_to=5,
        percent_complete=0.8,
        candles=600,
    )


def _candle_data() -> SimpleNamespace:
    return SimpleNamespace(
        df=_make_df(),
        symbol="BTCUSDT",
        interval=Interval.H4,
    )


class _Pattern:
    """Lightweight stand-in for a pyharmonics pattern object.

    ``extract_candidates`` reads ``.y``, ``.x``, ``.name``,
    ``.completion_min_price``, ``.completion_max_price``, ``.bullish``.
    """

    def __init__(self, name, y, completion_min, completion_max, bullish=True, x=None):
        self.name = name
        self.y = y
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else [0, 10, 20, 580, 599]


def _detection_result(forming_patterns=None, formed_patterns=None, position=None) -> dict:
    """Build a detection_result dict shaped as ``extract_candidates`` expects."""
    return {
        "divergences": {},
        "patterns": {},
        "position": position,
        "plot": None,
        "raw_assessment": {
            "forming": {"XABCD": forming_patterns or []},
            "patterns": {"XABCD": formed_patterns or []},
        },
    }


# A PRZ safely above the last close (220) so no bar wicks into it.
_FAR_PRZ = (225.0, 230.0)


# ---------------------------------------------------------------------------
# Regression tests for dashboard-trade-levels bug: stop_loss / target_price /
# risk_reward_ratio were None because _PatternPosition read nonexistent attrs.
# ---------------------------------------------------------------------------


class _FakePattern:
    """Hand-built pyharmonics pattern object.

    Avoids real ``XABCDPattern.__init__`` (which requires `retraces` dict and
    `name` keys present in pyharmonics constants) — we only need the public
    attributes the adapter reads (``completion_min_price``,
    ``completion_max_price``, ``x``, ``y``, ``bullish``).
    """

    def __init__(
        self,
        *,
        completion_min: float,
        completion_max: float,
        bullish: bool = True,
        x=None,
        y=None,
    ):
        self.symbol = "BTCUSDT"  # Position.__init__ reads pattern.symbol
        self.interval = "4h"
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else (0, 10, 20, 580, 599)
        # Five pivots so real Position._set_targets (which reads y[-2]) gets
        # a non-degenerate C-vs-strike distance.
        self.y = y if y is not None else (
            completion_min + 0.5,
            completion_max,
            (completion_min + completion_max) / 2,
            completion_max - 0.2,
            (completion_min + completion_max) / 2,
        )
        self.reversal = None
        self.htf_trend = None


class TestFirstTargetPrice:
    """`_first_target_price` must normalize both dict and float target shapes."""

    def test_none_returns_none(self):
        from app.infra.pyharmonics_adapter import _first_target_price

        assert _first_target_price(None) is None

    def test_empty_returns_none(self):
        from app.infra.pyharmonics_adapter import _first_target_price

        assert _first_target_price([]) is None

    def test_dict_shape_returns_price(self):
        from app.infra.pyharmonics_adapter import _first_target_price

        assert _first_target_price([{"price": 1.5, "label": "TP1"}]) == 1.5

    def test_float_shape_returns_first(self):
        from app.infra.pyharmonics_adapter import _first_target_price

        assert _first_target_price([2.5, 3.0, 4.0]) == 2.5

    def test_unknown_shape_returns_none(self):
        from app.infra.pyharmonics_adapter import _first_target_price

        # Defensive: unknown element type must not crash.
        assert _first_target_price(["not-a-target"]) is None


def _make_fake_pattern(
    *,
    completion_min: float,
    completion_max: float,
    bullish: bool = True,
    y=None,
):
    """Build a _FakePattern with C pivot far enough from strike to make net_rr positive.

    pyharmonics Position._set_stop / _set_targets compute:
        TP1_amount = |C - strike| / 2
        TP3_amount = |C - strike| * 1.618
        stop_offset = TP1_amount / 3 (so stop is 1/6 of C-vs-strike below strike)
    Fees/slippage are 0.2% round-trip, so reward must exceed 0.4% of strike.

    Caller passes a PRZ wide enough that the resulting reward vs stop is
    meaningfully positive. The default helper below uses a C ~10% above
    strike for tests that just need "the math works".
    """
    if y is None:
        strike = (completion_min + completion_max) / 2
        # Place C ~10% above strike so net_rr is comfortably positive even
        # after the 0.4% round-trip cost. pyharmonics.Position reads `y[-2]`,
        # so C must be the second-to-last pivot.
        c = strike * 1.10
        y = (completion_min, completion_max, strike, c, completion_max)
    return _FakePattern(
        completion_min=completion_min,
        completion_max=completion_max,
        bullish=bullish,
        y=y,
    )


class TestPatternPositionDerivesRealStopAndTargets:
    """`_PatternPosition` must produce real stop + 3-TP ladder, not None/[].

    This is the regression test for the dashboard bug where stop_loss /
    target_price were None in `technical_result`.
    """

    def test_xabcd_uses_prz_midpoint_as_strike(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0)
        pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")

        assert pos.strike == 596.5
        assert pos.family == "XABCD"

    def test_abc_family_uses_completion_max(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=100.0, completion_max=101.0)
        pos = _PatternPosition(pattern, "BTCUSDT", "1h", forming=True, family="ABC")

        # ABC: completion_min == completion_max for ABCPattern, strike = completion_max.
        assert pos.strike == 101.0

    def test_stop_and_targets_are_nonempty_floats(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0, bullish=True)
        pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")

        assert pos.stop is not None and pos.stop > 0
        assert len(pos.targets) >= 3
        assert all(isinstance(t, float) for t in pos.targets)

    def test_bullish_geometry_stop_below_strike_tp1_above(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0, bullish=True)
        pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")

        assert pos.stop < pos.strike, f"bullish stop ({pos.stop}) must be below strike ({pos.strike})"
        assert pos.targets[0] > pos.strike, "bullish TP1 must be above strike"

    def test_bearish_geometry_stop_above_strike_tp1_below(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0, bullish=False)
        pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")

        assert pos.stop > pos.strike, f"bearish stop ({pos.stop}) must be above strike ({pos.strike})"
        assert pos.targets[0] < pos.strike, "bearish TP1 must be below strike"

    def test_to_dict_exposes_computed_fields(self):
        from app.infra.pyharmonics_adapter import _PatternPosition

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0)
        pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")
        d = pos.to_dict()

        assert d["symbol"] == "BTCUSDT"
        assert d["family"] == "XABCD"
        assert d["strike"] == 596.5
        assert d["stop"] is not None
        assert isinstance(d["targets"], list)
        assert len(d["targets"]) >= 3

    def test_position_failure_degrades_to_minimal_dict(self):
        """If pyharmonics.Position construction raises (e.g. exotic shape),
        we still produce a usable position with strike + direction but no stop/targets.
        """
        # Patch Position's __init__ to explode so the try/except branch runs.
        from app.infra import pyharmonics_adapter as adapter
        from app.infra.pyharmonics_adapter import _PatternPosition

        original_position = adapter.Position

        class _BrokenPosition:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("simulated upgrade break")

        adapter.Position = _BrokenPosition  # type: ignore[assignment]
        try:
            pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0)
            pos = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")
        finally:
            adapter.Position = original_position  # type: ignore[assignment]

        assert pos.strike == 596.5
        assert pos.stop is None
        assert pos.targets == []
        assert pos.direction  # direction still resolvable from .bullish


class TestTechnicalResultSchemaExposesAllLevels:
    """`technical_result_to_schema` must produce entry/stop/target/RR for both
    the validated-signal path and the raw-position fallback path.
    """

    def _detection_result(self, position) -> dict:
        return {
            "position": position,
            "patterns": {
                "symbol": "BTCUSDT",
                "family": "XABCD",
                "direction": "bullish",
                "entry": 596.5,
                "stop": 596.42,
                "targets": [596.75, 597.0, 597.31],
                "reversal": None,
                "forming": False,
            },
            "divergences": {"count": 0, "items": []},
        }

    def test_raw_position_path_populates_all_three_levels(self):
        from app.infra.pyharmonics_adapter import _PatternPosition, technical_result_to_schema

        pattern = _make_fake_pattern(completion_min=595.0, completion_max=598.0)
        position = _PatternPosition(pattern, "BTCUSDT", "4h", forming=False, family="XABCD")
        result = technical_result_to_schema(self._detection_result(position))

        assert result.entry_price is not None and result.entry_price > 0
        assert result.stop_loss is not None and result.stop_loss > 0
        assert result.target_price is not None and result.target_price > 0
        # Wider geometry ensures net_rr > 0 after fees/slippage.
        assert result.risk_reward_ratio is not None and result.risk_reward_ratio > 0
        assert result.confidence == "raw-position"

    def test_validated_signal_path_uses_signal_targets(self):
        from app.infra.pyharmonics_adapter import technical_result_to_schema

        signal = {
            "status": "formed",
            "grade": "B",
            "direction": "long",
            "pattern_name": "gartley",
            "family": "XABCD",
            "formed": True,
            "entry_zone": [595.0, 598.0],
            "entry_reference": 596.5,
            "stop_loss": 590.0,
            "targets": [
                {"label": "TP1", "price": 610.0, "fib_basis": "x", "close_pct": 33, "move_stop_to": "breakeven"},
                {"label": "TP2", "price": 620.0, "fib_basis": "x", "close_pct": 33, "move_stop_to": "tp1"},
            ],
        }
        result = technical_result_to_schema(
            {"position": None, "patterns": {"family": "XABCD", "direction": "bullish"}, "divergences": {}},
            signal=signal,
        )

        assert result.entry_price == 596.5
        assert result.stop_loss == 590.0
        assert result.target_price == 610.0
        assert result.risk_reward_ratio is not None and result.risk_reward_ratio > 0
        assert result.confidence == "validated-signal"

    def test_no_pattern_no_position_returns_empty_levels(self):
        from app.infra.pyharmonics_adapter import technical_result_to_schema

        result = technical_result_to_schema(
            {"position": None, "patterns": {}, "divergences": {}}
        )

        assert result.entry_price is None
        assert result.stop_loss is None
        assert result.target_price is None
        assert result.risk_reward_ratio is None


class TestRestoreCachedRejectsDirtyPayload:
    """`_restore_cached` returns None for v1 payloads missing stop_loss so the
    orchestrator drops the stale key and re-runs detection.
    """

    def test_returns_none_when_stop_loss_missing(self):
        from app.domain.schemas import AnalysisData, TimingInfo

        cache = {
            "analysis_json": AnalysisData(
                analysis_id="legacy",
                status="completed",
                market="binance",
                symbol="BTCUSDT",
                interval="4h",
                analysis_type="auto",
                parameters={},
                technical_result={
                    # entry_price set but stop_loss missing → dirty v1 payload
                    "entry_price": 596.5,
                    "stop_loss": None,
                    "target_price": None,
                    "risk_reward_ratio": None,
                },
                interpretation={"summary": "legacy"},
                timing=TimingInfo(duration_ms=1000),
                forming_candidates=[],
            ).model_dump_json()
        }
        # Use a transient orchestrator (no real cache dependency for this method).
        orchestrator = AnalysisOrchestrator()
        result = orchestrator._restore_cached(cache, "new-id", None, 0.0)
        assert result is None

    def test_returns_data_when_complete(self):
        from app.domain.schemas import AnalysisData, TimingInfo

        cache = {
            "analysis_json": AnalysisData(
                analysis_id="v2",
                status="completed",
                market="binance",
                symbol="BTCUSDT",
                interval="4h",
                analysis_type="auto",
                parameters={},
                technical_result={
                    "entry_price": 596.5,
                    "stop_loss": 590.0,
                    "target_price": 610.0,
                    "risk_reward_ratio": 2.5,
                },
                interpretation={"summary": "ok"},
                timing=TimingInfo(duration_ms=1000),
                forming_candidates=[],
            ).model_dump_json()
        }
        orchestrator = AnalysisOrchestrator()
        result = orchestrator._restore_cached(cache, "new-id", None, 0.0)
        assert result is not None
        assert result.analysis_id == "new-id"
        assert result.technical_result.entry_price == 596.5


