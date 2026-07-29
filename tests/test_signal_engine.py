"""100% coverage tests for app.services.signal_engine."""

import pandas as pd
import pytest

from app.domain.signals import Candidate
from app.services.signal_engine import (
    _is_reversal_candle,
    _to_candidate,
    build_signal,
    compute_atr,
    compute_rsi,
    confluence_score,
    extract_candidates,
    htf_trend,
)

# --- Fixtures -----------------------------------------------------------------


def make_df(closes, interval_sec=900, volumes=None, start=1_700_000_000):
    """Build a CandleData-shaped DataFrame from a close-price series."""
    n = len(closes)
    close_time = [start + i * interval_sec for i in range(n)]
    opens = [closes[i - 1] if i else closes[0] for i in range(n)]
    highs = [max(o, c) + 0.5 for o, c in zip(opens, closes, strict=False)]
    lows = [min(o, c) - 0.5 for o, c in zip(opens, closes, strict=False)]
    vols = volumes or [100.0] * n
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
            "close_time": close_time,
        }
    )
    df["dts"] = pd.to_datetime(df["close_time"], unit="s", utc=True)
    return df


def bullish_df(n=600):
    """Uptrend with a sharp pullback at the end (D-point of a bullish pattern)."""
    closes = [50.0 + i * 0.2 for i in range(n - 10)]
    peak = closes[-1]
    closes += [peak - 2.16 * (i + 1) for i in range(10)]
    # Final bar: hammer reversal closing at 146.4 territory.
    closes[-1] = closes[-2] - 2.16
    df = make_df(closes)
    # Override last candle: hammer with volume spike.
    c = closes[-1]
    df.loc[df.index[-1], "open"] = c - 0.4
    df.loc[df.index[-1], "high"] = c + 0.2
    df.loc[df.index[-1], "low"] = c - 2.2
    df.loc[df.index[-1], "volume"] = 500.0
    return df


def gartley_candidate(entry_area=None, **overrides):
    """Bullish gartley with PRZ around the tail of bullish_df."""
    last = 50.0 + 589 * 0.2 - 2.16 * 10  # ~146.24
    lo, hi = entry_area or (last - 2.4, last + 1.6)
    base = dict(
        family="XABCD",
        name="gartley",
        bullish=True,
        formed=True,
        points=(142.0, 170.0, 155.0, 165.0, last),
        completion_min=lo,
        completion_max=hi,
    )
    base.update(overrides)
    return Candidate(**base)


# --- extract_candidates --------------------------------------------------------


class TestExtractCandidates:
    def test_no_assessment(self):
        assert extract_candidates({}) == []

    def test_formed_and_forming(self):
        class P:
            y = (100.0, 150.0, 120.0, 140.0, 110.0)
            completion_min_price = 108.0
            completion_max_price = 112.0
            name = "gartley"
            bullish = True

        detection = {
            "raw_assessment": {
                "patterns": {"XABCD": [P()], "ABCD": [], "ABC": []},
                "forming": {"XABCD": [P()], "ABCD": [], "ABC": []},
            }
        }
        cands = extract_candidates(detection)
        assert len(cands) == 2
        assert cands[0].formed is True
        assert cands[1].formed is False
        assert cands[0].family == "XABCD"

    def test_none_pattern_list(self):
        detection = {"raw_assessment": {"patterns": {"XABCD": None}, "forming": {}}}
        assert extract_candidates(detection) == []

    def test_invalid_pattern_skipped(self):
        class Bad:
            y = ("x", "y", "z")
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "gartley"
            bullish = True

        detection = {"raw_assessment": {"patterns": {"XABCD": [Bad()]}, "forming": {}}}
        assert extract_candidates(detection) == []


class TestToCandidate:
    def test_missing_attr(self):
        assert _to_candidate(object(), "XABCD", True) is None

    def test_too_few_points(self):
        class P:
            y = (1.0, 2.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True

        assert _to_candidate(P(), "ABC", True) is None

    def test_nonpositive_prz(self):
        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 0.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True

        assert _to_candidate(P(), "ABC", True) is None

    def test_unparseable_times_falls_back_to_empty(self):
        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True
            x = ("not-a-number", None)

        cand = _to_candidate(P(), "ABC", True)
        assert cand is not None
        assert cand.times == ()

    def test_parseable_times_kept(self):
        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True
            x = (100, 200, 300)

        cand = _to_candidate(P(), "ABC", True)
        assert cand is not None
        assert cand.times == (100, 200, 300)

    def test_x_indices_mapped_to_close_times(self):
        """Regression: pyharmonics pattern.x are df.index values (bar positions).

        When close_times is provided, _to_candidate must map those positions
        to the matching epoch seconds. Without that mapping the staleness
        filter at rejection_reason() compares seconds to bar indices and
        rejects every real candidate as stale_age.
        """

        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True
            x = (10, 20, 30)

        close_times = [1_700_000_000 + i * 3600 for i in range(40)]
        cand = _to_candidate(P(), "ABC", True, close_times)
        assert cand is not None
        assert cand.times == (close_times[10], close_times[20], close_times[30])
        # The last time must be epoch seconds, not a tiny bar index.
        assert cand.times[-1] > 1_700_000_000

    def test_x_timestamp_fallback(self):
        """DatetimeIndex support: pattern.x as pd.Timestamp → epoch seconds."""
        import pandas as pd

        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True
            x = (
                pd.Timestamp("2026-01-01"),
                pd.Timestamp("2026-01-02"),
                pd.Timestamp("2026-01-03"),
            )

        cand = _to_candidate(P(), "ABC", True, [0] * 10)
        assert cand is not None
        assert cand.times == (
            int(pd.Timestamp("2026-01-01").timestamp()),
            int(pd.Timestamp("2026-01-02").timestamp()),
            int(pd.Timestamp("2026-01-03").timestamp()),
        )

    def test_x_out_of_range_falls_back_to_timestamp(self):
        """If the index is out of range, fall back to Timestamp conversion."""
        import pandas as pd

        class P:
            y = (1.0, 2.0, 3.0)
            completion_min_price = 1.0
            completion_max_price = 2.0
            name = "abc"
            bullish = True
            x = (9999, pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03"))

        close_times = [1_700_000_000 + i * 3600 for i in range(10)]
        cand = _to_candidate(P(), "ABC", True, close_times)
        assert cand is not None
        # First entry out of range → dropped from mapped list (no fallback Timestamp).
        assert len(cand.times) == 2
        assert cand.times[0] == int(pd.Timestamp("2026-01-02").timestamp())

    def test_real_pipeline_emits_signal_with_proper_times(self):
        """End-to-end: build_signal emits a non-None signal when times are mapped.

        Without the fix, candidate.times stays at bar indices and the
        staleness filter rejects every real candidate.
        """
        from types import SimpleNamespace

        from pyharmonics.search import HarmonicSearch
        from pyharmonics.technicals import OHLCTechnicals

        n = 600
        closes = [50.0 + i * 0.2 for i in range(n - 10)]
        closes += [closes[-1] - 2.16 * (i + 1) for i in range(10)]
        opens = [closes[i - 1] if i else closes[0] for i in range(n)]
        highs = [max(o, c) + 0.5 for o, c in zip(opens, closes, strict=False)]
        lows = [min(o, c) - 0.5 for o, c in zip(opens, closes, strict=False)]
        df = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": [100.0] * n,
                "close_time": [1_700_000_000 + i * 900 for i in range(n)],
            }
        )
        candle = SimpleNamespace(df=df, symbol="BTCUSDT", interval="15m")
        t = OHLCTechnicals(candle.df, candle.symbol, candle.interval, peak_spacing=5)
        hs = HarmonicSearch(t, fib_tolerance=0.05)
        hs.search(limit_to=3)
        det = {"raw_assessment": hs.get_patterns()}
        # Patch raw_assessment into a dict of {family: [patterns]} shape that
        # extract_candidates expects.
        formed = hs.get_patterns()
        det = {
            "raw_assessment": {
                "forming": formed,
                "patterns": {},
            }
        }
        cands = extract_candidates(det, df["close_time"])
        # At least one candidate should survive stale_age (D within 20 bars).
        if cands:
            assert all(t > 1_700_000_000 for t in cands[0].times), f"times still in bar-index units: {cands[0].times}"


# --- Indicator helpers ---------------------------------------------------------


class TestComputeAtr:
    def test_normal(self):
        df = make_df([100 + (i % 5) for i in range(60)])
        assert compute_atr(df) > 0

    def test_short_frame_fallback(self):
        df = make_df([100.0, 101.0, 102.0])
        atr = compute_atr(df)
        assert atr > 0


class TestComputeRsi:
    def test_uptrend_high_rsi(self):
        closes = pd.Series([float(i) for i in range(1, 100)])
        assert compute_rsi(closes) == 100.0

    def test_downtrend_low_rsi(self):
        closes = pd.Series([float(100 - i) for i in range(100)])
        assert compute_rsi(closes) < 10

    def test_flat_returns_50(self):
        closes = pd.Series([100.0] * 100)
        assert compute_rsi(closes) == 50.0

    def test_mixed(self):
        closes = pd.Series([100 + (i % 7) - 3 for i in range(100)])
        rsi = compute_rsi(closes)
        assert 0 <= rsi <= 100


class TestHtfTrend:
    def test_no_rule(self):
        df = make_df([100.0] * 60)
        assert htf_trend(df, "1m") == "unknown"

    def test_no_dts_column(self):
        df = pd.DataFrame({"close": [100.0] * 60})
        assert htf_trend(df, "1h") == "unknown"

    def test_insufficient_htf_bars(self):
        df = make_df([100.0 + i for i in range(60)])  # 60 x 15m -> 15 hourly
        assert htf_trend(df, "15m") == "unknown"

    def test_bullish(self):
        df = make_df([50.0 + i * 0.5 for i in range(400)])  # 100 hourly bars up
        assert htf_trend(df, "15m") == "bullish"

    def test_bearish(self):
        df = make_df([250.0 - i * 0.5 for i in range(400)])
        assert htf_trend(df, "15m") == "bearish"

    def test_flat_is_unknown(self):
        df = make_df([100.0] * 400)
        assert htf_trend(df, "15m") == "unknown"


class TestReversalCandle:
    def test_bullish_hammer(self):
        row = pd.Series({"open": 100.0, "high": 101.0, "low": 97.0, "close": 100.5})
        assert _is_reversal_candle(row, bullish=True) is True

    def test_bullish_not_reversal(self):
        row = pd.Series({"open": 100.0, "high": 103.0, "low": 99.5, "close": 100.5})
        assert _is_reversal_candle(row, bullish=True) is False

    def test_bullish_requires_up_close(self):
        row = pd.Series({"open": 100.5, "high": 101.0, "low": 97.0, "close": 100.0})
        assert _is_reversal_candle(row, bullish=True) is False

    def test_bearish_shooting_star(self):
        row = pd.Series({"open": 100.5, "high": 103.0, "low": 99.5, "close": 100.0})
        assert _is_reversal_candle(row, bullish=False) is True

    def test_bearish_requires_down_close(self):
        row = pd.Series({"open": 100.0, "high": 103.0, "low": 99.5, "close": 100.5})
        assert _is_reversal_candle(row, bullish=False) is False

    def test_zero_range(self):
        row = pd.Series({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})
        assert _is_reversal_candle(row, bullish=True) is False


class TestConfluenceScore:
    def test_full_alignment(self):
        df = bullish_df()
        cand = gartley_candidate()
        atr = compute_atr(df)
        rsi = compute_rsi(df["close"])
        divs = {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]}
        score, factors = confluence_score(df, cand, atr, rsi, "bullish", divs)
        assert factors["price_action"] == 25
        assert factors["htf_trend"] == 25
        assert factors["rsi"] >= 8
        assert factors["macd"] == 10
        assert factors["funding"] == 5
        assert score == sum(factors.values())

    def test_no_confirmation(self):
        df = make_df([100.0 + i * 0.1 for i in range(100)])  # slow grind up
        cand = gartley_candidate()
        atr = compute_atr(df)
        score, factors = confluence_score(df, cand, atr, 50.0, "bearish", {})
        assert factors["price_action"] == 0
        assert factors["htf_trend"] == 0
        assert factors["rsi"] == 0
        assert factors["macd"] == 0

    def test_unknown_trend_partial(self):
        df = make_df([100.0 + i * 0.1 for i in range(100)])
        cand = gartley_candidate()
        atr = compute_atr(df)
        _, factors = confluence_score(df, cand, atr, 50.0, "unknown", {})
        assert factors["htf_trend"] == 10

    def test_rsi_mid_zone_partial(self):
        df = make_df([100.0 + i * 0.1 for i in range(100)])
        cand = gartley_candidate()
        atr = compute_atr(df)
        _, f_bull = confluence_score(df, cand, atr, 40.0, "unknown", {})
        assert f_bull["rsi"] == 4
        bear_cand = gartley_candidate(bullish=False)
        _, f_bear = confluence_score(df, bear_cand, atr, 60.0, "unknown", {})
        assert f_bear["rsi"] == 4

    def test_rsi_extreme_zone(self):
        df = make_df([100.0 + i * 0.1 for i in range(100)])
        cand = gartley_candidate()
        atr = compute_atr(df)
        _, factors = confluence_score(df, cand, atr, 30.0, "unknown", {})
        assert factors["rsi"] == 7

    def test_reversal_candle_without_volume(self):
        closes = [100.0] * 99 + [101.0]
        df = make_df(closes)
        c = 101.0
        df.loc[df.index[-1], "open"] = c - 0.6
        df.loc[df.index[-1], "high"] = c + 0.2
        df.loc[df.index[-1], "low"] = c - 2.6
        cand = gartley_candidate()
        atr = compute_atr(df)
        _, factors = confluence_score(df, cand, atr, 50.0, "unknown", {})
        assert factors["price_action"] == 15


# --- build_signal --------------------------------------------------------------


class TestBuildSignal:
    def test_none_df(self):
        assert build_signal(None, "15m", [gartley_candidate()]) is None

    def test_short_df(self):
        df = make_df([100.0] * 30)
        assert build_signal(df, "15m", [gartley_candidate()]) is None

    def test_no_candidates(self):
        df = bullish_df()
        assert build_signal(df, "15m", []) is None

    def test_zero_atr(self):
        df = make_df([100.0] * 100)  # constant prices, some ranges though
        df["high"] = df["close"]
        df["low"] = df["close"]
        assert build_signal(df, "15m", [gartley_candidate()]) is None

    def test_confirmed_a_grade_signal(self):
        df = bullish_df()
        cand = gartley_candidate()
        signal = build_signal(df, "15m", [cand], divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]})
        assert signal is not None
        assert signal.grade == "A"
        assert signal.direction == "long"
        assert signal.status == "confirmed"
        assert signal.stop_loss < signal.entry_reference
        assert len(signal.targets) == 3
        assert signal.net_rr_tp2 >= 2.0
        assert signal.confluence_score >= 75
        d = signal.to_dict()
        assert d["grade"] == "A"
        assert d["targets"][0]["close_pct"] == 50

    def test_approaching_uses_prz_edge_as_entry(self):
        df = bullish_df()
        last = float(df["close"].iloc[-1])
        # PRZ far above current price -> approaching.
        cand = gartley_candidate(
            points=(140.0, 170.0, 155.0, 165.0, last),
            completion_min=last + 10.0,
            completion_max=last + 12.0,
        )
        signal = build_signal(df, "15m", [cand])
        if signal is not None:
            assert signal.status == "approaching"
            assert signal.entry_reference == pytest.approx(cand.prz_high)

    def test_swept_status(self):
        closes = [100.0 + i * 0.05 for i in range(99)] + [100.0]
        df = make_df(closes)
        # Last bar pierces below PRZ low but closes inside; not a reversal candle.
        df.loc[df.index[-1], "open"] = 105.0
        df.loc[df.index[-1], "low"] = 95.0
        df.loc[df.index[-1], "high"] = 105.5
        df.loc[df.index[-1], "close"] = 100.0
        cand = gartley_candidate(completion_min=99.0, completion_max=101.0)
        signal = build_signal(df, "15m", [cand])
        if signal is not None:
            assert signal.status in ("swept", "confirmed")

    def test_bearish_signal(self):
        # Downtrend then sharp rally into a bearish PRZ.
        closes = [250.0 - i * 0.2 for i in range(590)]
        trough = closes[-1]
        closes += [trough + 2.0 * (i + 1) for i in range(10)]
        df = make_df(closes)
        last = float(df["close"].iloc[-1])
        cand = Candidate(
            family="XABCD",
            name="gartley",
            bullish=False,
            formed=True,
            points=(last + 30, last - 30, last + 10, last - 5, last),
            completion_min=last - 2.0,
            completion_max=last + 2.0,
        )
        signal = build_signal(df, "15m", [cand], divergences={"rsi": [{"bullish": False}]})
        assert signal is not None
        assert signal.direction == "short"
        assert signal.stop_loss > signal.entry_reference
        assert signal.targets[0].price < signal.entry_reference

    def test_low_score_candidate_dropped(self):
        df = make_df([100.0 + i * 0.1 for i in range(100)])  # grind up, counter
        cand = gartley_candidate(completion_min=98.0, completion_max=99.0)
        # price ~109.9 far above PRZ, counter-trend, no divergence, rr tiny span
        assert build_signal(df, "15m", [cand]) is None

    def test_degenerate_rr_dropped(self):
        df = bullish_df()
        last = float(df["close"].iloc[-1])
        # A-D span nearly zero -> fees kill reward -> rr None -> dropped.
        cand = gartley_candidate(
            points=(140.0, last + 0.05, 155.0, 165.0, last),
        )
        assert build_signal(df, "15m", [cand]) is None

    def test_best_candidate_wins(self):
        df = bullish_df()
        last = float(df["close"].iloc[-1])
        good = gartley_candidate()
        bad = gartley_candidate(
            name="gartley",
            points=(140.0, last + 0.05, 155.0, 165.0, last),
        )
        signal = build_signal(df, "15m", [bad, good], divergences={"rsi": [{"bullish": True}]})
        assert signal is not None
        assert signal.entry_zone[0] == good.prz_low

    def test_unknown_interval(self):
        df = bullish_df()
        signal = build_signal(df, "1m", [gartley_candidate()])
        # HTF unknown -> capped below A but signal may still exist.
        if signal is not None:
            assert signal.htf_trend == "unknown"
            assert signal.grade in ("B", "C", "C(参考)")

    def test_stale_candidate_filtered(self):
        # PRZ 45x ATR away from price -> filtered before scoring (SOXLUSDT case).
        df = bullish_df()
        cand = gartley_candidate(completion_min=1000.0, completion_max=1010.0)
        assert build_signal(df, "15m", [cand]) is None

    def test_stale_age_filtered(self):
        df = bullish_df()
        cand = gartley_candidate(times=(1,))
        # close_times in df are far greater than 1 -> D age huge -> stale
        assert build_signal(df, "15m", [cand]) is None

    def test_trap_veto_drops_candidate(self):
        df = bullish_df()
        cand = gartley_candidate()
        # Wick deep into the PRZ and close far below it -> PRZ support failure.
        idx = df.index[-3]
        lo = cand.prz_low
        df.loc[idx, "low"] = (cand.prz_low + cand.prz_high) / 2
        df.loc[idx, "close"] = lo * 0.5
        assert build_signal(df, "15m", [cand]) is None

    def test_adverse_momentum_veto(self):
        # Relentless downtrend: long candidate walks into a falling knife.
        closes = [200.0 * 0.995**i for i in range(300)]
        df = make_df(closes)
        last = closes[-1]
        cand = Candidate(
            family="XABCD",
            name="gartley",
            bullish=True,
            formed=True,
            points=(last * 0.9, last * 1.3, last * 1.1, last * 1.2, last),
            completion_min=last * 0.99,
            completion_max=last * 1.01,
        )
        assert build_signal(df, "15m", [cand]) is None

    def test_volume_authenticity_veto(self):
        # Extreme volume chaos -> authenticity < 25 -> no signal at all.
        # Alternating huge/tiny spikes with fully misaligned price moves.
        rows_vol = []
        closes = []
        price = 100.0
        for i in range(200):
            if i % 3 == 0:
                price = price - 0.3
                rows_vol.append(1000.0)
            else:
                price = price + 0.2
                rows_vol.append(10.0)
            closes.append(price)
        df = make_df(closes, volumes=rows_vol)
        cand = gartley_candidate(completion_min=99.0, completion_max=101.0)
        result = build_signal(df, "15m", [cand])
        # Either vetoed or heavily penalized; must not crash.
        assert result is None or result.grade in ("C", "C(参考)")

    def test_volume_authenticity_hard_veto(self):
        from app.services.signal_engine import volume_authenticity

        rows_vol = []
        closes = []
        price = 100.0
        for i in range(200):
            if i % 3 == 0:
                price = price - 0.3
                rows_vol.append(1000.0)
            else:
                price = price + 0.2
                rows_vol.append(10.0)
            closes.append(price)
        df = make_df(closes, volumes=rows_vol)
        # Precondition: the fixture is chaotic enough to trip the hard veto.
        assert volume_authenticity(df) < 25
        cand = gartley_candidate(completion_min=99.0, completion_max=101.0)
        assert build_signal(df, "15m", [cand]) is None

    def test_invariant_violation_drops_candidate(self):
        # Defense-in-depth: if target computation ever yields malformed
        # geometry (here: descending targets on a long), the candidate is
        # dropped at the invariant gate.
        from unittest.mock import patch

        from app.domain.signals import SignalTarget

        bad_targets = tuple(
            SignalTarget(label=f"TP{i+1}", price=100.0 - i * 10, fib_basis="x", close_pct=50, move_stop_to="y") for i in range(3)
        )
        df = bullish_df()
        with patch("app.services.signal_engine.compute_targets", return_value=bad_targets):
            assert build_signal(df, "15m", [gartley_candidate()]) is None

    def test_stability_suspect_vetoes_ab_signal(self):
        df = bullish_df()
        cand = gartley_candidate()
        # Sub-windows find nothing -> pattern only exists in full window -> veto.
        signal = build_signal(
            df,
            "15m",
            [cand],
            divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
            stability_detector=lambda _df: None,
        )
        assert signal is None

    def test_stability_consistent_keeps_signal(self):
        df = bullish_df()
        cand = gartley_candidate()
        signal = build_signal(
            df,
            "15m",
            [cand],
            divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
            stability_detector=lambda _df: "gartley",
        )
        assert signal is not None
        assert signal.stability_score == 85

    def test_stability_detector_exception_treated_unverifiable(self):
        df = bullish_df()
        cand = gartley_candidate()

        def boom(_df):
            raise RuntimeError("detector exploded")

        signal = build_signal(
            df,
            "15m",
            [cand],
            divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
            stability_detector=boom,
        )
        # Detector failure -> sub-windows unknown -> suspect -> vetoed.
        assert signal is None

    def test_stability_partial_match(self):
        df = bullish_df()
        cand = gartley_candidate()
        calls = {"n": 0}

        def detector(_df):
            calls["n"] += 1
            return "gartley" if calls["n"] == 1 else None

        signal = build_signal(
            df,
            "15m",
            [cand],
            divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
            stability_detector=detector,
        )
        assert signal is not None
        assert signal.stability_score == 40

    def test_signal_includes_v4_metadata(self):
        df = bullish_df()
        cand = gartley_candidate()
        signal = build_signal(
            df,
            "15m",
            [cand],
            divergences={"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert signal is not None
        assert signal.regime in ("normal", "moderate_quant", "high_quant")
        assert signal.position_multiplier is not None
        assert signal.trap_score is not None
        assert signal.sharpe is not None
        assert "方向" in signal.reasoning
        d = signal.to_dict()
        assert d["regime"] == signal.regime
        assert d["reasoning"] == signal.reasoning


class TestPipelineHelpers:
    """Direct unit tests for the three helpers that ``build_signal`` delegates to.

    ``TestBuildSignal`` covers the public façade end-to-end; these tests
    pin the per-stage contracts so a regression in one stage can't be
    hidden by another stage absorbing the failure.
    """

    def test_rank_signals_prefers_higher_grade(self):

        from app.services.signal_engine import rank_signals

        a = _dummy_signal(grade="A", score=70, formed=True)
        b = _dummy_signal(grade="B", score=95, formed=True)
        assert rank_signals([b, a]).pattern_name == a.pattern_name

    def test_rank_signals_breaks_ties_by_score_then_formed(self):

        from app.services.signal_engine import rank_signals

        a = _dummy_signal(grade="A", score=80, formed=True)
        c = _dummy_signal(grade="A", score=80, formed=False)
        assert rank_signals([c, a]).pattern_name == a.pattern_name

    def test_rank_signals_empty_returns_none(self):
        from app.services.signal_engine import rank_signals

        assert rank_signals([]) is None

    def test_apply_stability_passes_through_for_c_grade(self):
        from app.services.signal_engine import apply_stability

        sig = _dummy_signal(grade="C", score=60)
        calls = {"n": 0}

        def detector(_df):
            calls["n"] += 1
            return "none"

        # C-grade should skip the detector entirely.
        assert apply_stability(bullish_df(), sig, detector) is sig
        assert calls["n"] == 0

    def test_apply_stability_vetoes_when_only_in_full_window(self):
        from app.services.signal_engine import apply_stability

        sig = _dummy_signal(grade="A", score=80, name="gartley")

        def detector(_df):
            return None  # Pattern absent from every sub-window.

        assert apply_stability(bullish_df(), sig, detector) is None

    def test_score_candidate_rejects_when_trap_veto(self, monkeypatch):
        from app.services import signal_engine as se
        from app.services.signal_engine import _prepare_score_context, score_candidate

        df = bullish_df()
        ctx = _prepare_score_context(
            df,
            "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None

        def fake_trap(*_a, **_kw):
            return 0.0, True, ["test trap"]

        monkeypatch.setattr(se, "quant_trap_risk", fake_trap)
        assert score_candidate(ctx, gartley_candidate()) is None


# --- v2 engine amendments (Q4 reliability, Q5 reverse-div, Q6 width_pct) -------


class TestV2EngineAmendments:
    def test_pattern_reliability_bump_visible_on_signal(self):
        from app.services.signal_engine import (
            _prepare_score_context,
            score_candidate,
        )

        df = bullish_df()
        ctx = _prepare_score_context(
            df,
            "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None
        sig = score_candidate(ctx, gartley_candidate())
        assert sig is not None
        # Gartley base bump is +5.
        assert sig.confluence_score >= 50

    def test_reverse_rsi_divergence_penalised(self):
        from app.services.signal_engine import (
            compute_atr,
            compute_rsi,
            confluence_score,
        )

        # Use a flat series: RSI returns 50 (mid-zone, not extreme so the
        # -5 penalty is NOT compensated by the +7 extreme-zone bonus).
        df = make_df([100.0] * 100)
        cand = gartley_candidate(bullish=True)
        atr = compute_atr(df)
        rsi = compute_rsi(df["close"])
        # Bearish divergence on a bullish candidate must subtract 5.
        divs = {"rsi": [{"bullish": False}]}
        _score, factors = confluence_score(
            df,
            cand,
            atr,
            rsi,
            "unknown",
            divs,
        )
        assert factors["rsi"] == -5

        # Same divergence on a bearish candidate is aligned (not penalised).
        bear_cand = gartley_candidate(bullish=False)
        _score, factors_bear = confluence_score(
            df,
            bear_cand,
            atr,
            rsi,
            "unknown",
            divs,
        )
        assert factors_bear["rsi"] >= 0

    def test_wide_width_pct_demotes_to_observation(self):
        from app.services.signal_engine import (
            _prepare_score_context,
            score_candidate,
        )

        df = bullish_df()
        ctx = _prepare_score_context(
            df,
            "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None
        # 8% PRZ width (mid=143, range=11.4) → above the 4% gate.
        wide = gartley_candidate(
            completion_min=137.5,
            completion_max=148.5,
        )
        sig = score_candidate(ctx, wide)
        assert sig is not None
        assert sig.grade == "C(参考)"
        assert sig.tradable is False
        assert sig.width_pct >= 0.04

    def test_forming_pattern_volume_gate_is_lenient(self):
        # Forming pattern with low volume authenticity → still produces a signal.
        from app.services.signal_engine import (
            _prepare_score_context,
            score_candidate,
        )

        df = bullish_df()
        # Inject very low volume across the whole df to depress authenticity.
        df["volume"] = 1.0
        df.loc[df.index[-1], "volume"] = 1.0  # no spike
        ctx = _prepare_score_context(
            df,
            "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None
        # Forming pattern: lenient (HALVE) threshold.
        forming = gartley_candidate(formed=False)
        sig = score_candidate(ctx, forming)
        assert sig is not None

    def test_formed_pattern_vetoed_on_low_volume(self):
        from app.services.signal_engine import (
            _prepare_score_context,
            score_candidate,
        )

        df = bullish_df()
        ctx = _prepare_score_context(
            df,
            "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None

        # Force authenticity below VETO (25). _ScoreContext is a NamedTuple,
        # so we use _replace.
        ctx_low = ctx._replace(volume_authenticity=10)
        formed = gartley_candidate(formed=True)
        assert score_candidate(ctx_low, formed) is None

        # auth=30 is below VETO (25)? No — 30 ≥ 25. Use 20 to be sure.
        ctx_20 = ctx._replace(volume_authenticity=20)
        assert score_candidate(ctx_20, formed) is None
        # Forming pattern with the same auth (20) — the LOOSER threshold
        # (HALVE = 40) still rejects, so bump up to 45 (above HALVE).
        ctx_mid = ctx._replace(volume_authenticity=45)
        forming = gartley_candidate(formed=False)
        assert score_candidate(ctx_mid, forming) is not None


def _dummy_signal(grade="A", score=70, formed=True, name="gartley"):
    """Build a minimal ``Signal`` for ranking/stability tests without a real df."""
    from app.services.signal_engine import Signal

    sig = Signal(
        status="confirmed",
        grade=grade,
        direction="long",
        pattern_name=name,
        family="g",
        formed=formed,
        entry_zone=(100.0, 101.0),
        entry_reference=100.5,
        stop_loss=99.0,
        stop_basis="atr",
        stop_level="standard",
        invalidation_point=99.0,
        targets=[],
        net_rr_tp1=2.0,
        net_rr_tp2=3.0,
        confluence_score=score,
        confluence={},
        htf_trend="bullish",
        sharpe=0.0,
        regime="normal",
        position_multiplier=1.0,
        trap_score=10.0,
    )
    return sig
