"""Tests for :mod:`app.loop.maker_checker.isolation`.

Covers: stripping rules per mode, salt hashing, leakage measurement.
"""
from __future__ import annotations

import pytest

from app.loop.maker_checker.isolation import (
    MINIMAL,
    MODERATE,
    STRICT,
    STRIPPED_FIELDS_V1,
    leakage_metrics,
    list_stripped_fields,
    make_salt,
    strip_maker_artifacts,
)


def _payload() -> dict:
    return {
        "candidate_id": "gen1-C4-003",
        "generation_id": "gen1",
        "parent_id": "gen0-baseline",
        "gen": 1,
        "cluster": "C4 Macro",
        "clusters_touched": ["C4 Macro"],
        "diff": {"extreme_deviation_pct": 15.0},
        "maker_intent": "boost_bear_sharpe",
        "reasoning": "lower deviation threshold",
        "expected_impact": {"sharpe": "+0.3"},
        "self_score": 0.7,
        "prompt_version": "v1.1",
        # Non-Maker fields the Checker legitimately needs:
        "metrics": {"sharpe": 1.2, "calmar": 1.5},
        "trades": [{"r": 1.5}, {"r": -1.0}],
        "by_regime": {"bull": {"n": 20}, "bear": {"n": 10}},
    }


# ---- strip_maker_artifacts ----------------------------------------------


class TestStrict:
    def test_removes_all_maker_fields(self) -> None:
        out = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        for f in STRIPPED_FIELDS_V1[STRICT]:
            assert f not in out, f"{f} should be stripped in strict mode"

    def test_preserves_trade_metrics(self) -> None:
        out = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        assert out["metrics"] == {"sharpe": 1.2, "calmar": 1.5}
        assert out["trades"] == [{"r": 1.5}, {"r": -1.0}]
        assert "by_regime" in out

    def test_candidate_id_is_hashed(self) -> None:
        out = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        assert out["candidate_id"] != "gen1-C4-003"
        assert len(out["candidate_id"]) == 16

    def test_hash_is_deterministic_with_same_salt(self) -> None:
        a = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        b = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        assert a["candidate_id"] == b["candidate_id"]

    def test_hash_differs_with_different_salt(self) -> None:
        a = strip_maker_artifacts(_payload(), level=STRICT, salt="abc")
        b = strip_maker_artifacts(_payload(), level=STRICT, salt="xyz")
        assert a["candidate_id"] != b["candidate_id"]

    def test_requires_candidate_id(self) -> None:
        p = _payload()
        del p["candidate_id"]
        with pytest.raises(ValueError, match="candidate_id"):
            strip_maker_artifacts(p, level=STRICT, salt="abc")

    def test_does_not_mutate_input(self) -> None:
        p = _payload()
        before = dict(p)
        strip_maker_artifacts(p, level=STRICT, salt="abc")
        assert p == before


class TestModerate:
    def test_strips_intent_but_keeps_id(self) -> None:
        out = strip_maker_artifacts(_payload(), level=MODERATE)
        assert out["candidate_id"] == "gen1-C4-003"
        assert "maker_intent" not in out
        assert "reasoning" not in out
        assert "self_score" not in out
        assert "prompt_version" not in out

    def test_keeps_clusters_touched(self) -> None:
        out = strip_maker_artifacts(_payload(), level=MODERATE)
        assert "clusters_touched" in out


class TestMinimal:
    def test_strips_only_creative_intent(self) -> None:
        # Minimal mode: only strips maker_intent + reasoning; everything else stays.
        out = strip_maker_artifacts(_payload(), level=MINIMAL)
        assert "maker_intent" not in out
        assert "reasoning" not in out
        # The rest must remain.
        assert out["candidate_id"] == "gen1-C4-003"
        assert "clusters_touched" in out
        assert "diff" in out
        assert "self_score" in out
        assert "prompt_version" in out

    def test_strips_only_base_fields(self) -> None:
        # All _BASE_STRIPPED must go; the rest must stay.
        out = strip_maker_artifacts(_payload(), level=MINIMAL)
        assert "maker_intent" not in out
        assert "reasoning" not in out
        assert "self_score" in out  # kept in minimal
        assert "prompt_version" in out  # kept in minimal
        assert "clusters_touched" in out
        assert "diff" in out


class TestErrors:
    @pytest.mark.parametrize("bad", ["", "STRICT", "Strict", "all"])
    def test_unknown_level(self, bad: str) -> None:
        with pytest.raises(ValueError, match="unknown isolation level"):
            strip_maker_artifacts(_payload(), level=bad)


# ---- list_stripped_fields -------------------------------------------------


class TestListStrippedFields:
    def test_returns_tuple(self) -> None:
        assert isinstance(list_stripped_fields(STRICT), tuple)

    def test_strict_is_superset_of_moderate(self) -> None:
        s = set(list_stripped_fields(STRICT))
        m = set(list_stripped_fields(MODERATE))
        assert m.issubset(s)

    def test_minimal_overlaps_moderate(self) -> None:
        # Minimal only strips creative intent (maker_intent + reasoning),
        # which is a subset of what moderate strips.
        n = set(list_stripped_fields(MINIMAL))
        m = set(list_stripped_fields(MODERATE))
        assert n.issubset(m)


# ---- leakage_metrics ------------------------------------------------------


class TestLeakageMetrics:
    def test_empty_input(self) -> None:
        out = leakage_metrics([], [])
        assert out["kl_divergence"] == 0.0
        assert out["disagreement_rate"] == 0.0
        assert out["n"] == 0

    def test_identical_verdicts_have_zero_divergence(self) -> None:
        verdicts = [True, False, True, False]
        out = leakage_metrics(verdicts, list(verdicts))
        assert out["kl_divergence"] == 0.0
        assert out["disagreement_rate"] == 0.0

    def test_completely_flipped_verdicts_have_max_divergence(self) -> None:
        a = [True, True, True, True]
        b = [False, False, False, False]
        out = leakage_metrics(a, b)
        assert out["disagreement_rate"] == 1.0

    def test_partial_disagreement(self) -> None:
        a = [True, True, True, True]
        b = [True, False, True, False]
        out = leakage_metrics(a, b)
        assert out["disagreement_rate"] == 0.5

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            leakage_metrics([True], [True, False])

    def test_threshold_for_strict_isolation(self) -> None:
        # Strict isolation must produce < 10% disagreement.
        # Synthetic: 20 cases, 1 flipped → 5%.
        a = [True] * 20
        b = [True] * 19 + [False]
        out = leakage_metrics(a, b)
        assert out["disagreement_rate"] < 0.10


# ---- make_salt ------------------------------------------------------------


class TestMakeSalt:
    def test_returns_hex_string(self) -> None:
        s = make_salt()
        assert isinstance(s, str)
        assert len(s) == 16  # 8 bytes hex
        int(s, 16)  # parses as hex

    def test_two_salts_differ(self) -> None:
        assert make_salt() != make_salt()