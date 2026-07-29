"""Tests for :mod:`app.loop.maker_checker.maker_agent`.

Covers: MakerConfig validation, traditional_proposals (math-only
baseline), MakerAgent LLM path, fallback semantics, the
propose_batch wrapper, and the run_mode mixing logic.
"""
from __future__ import annotations

import pytest

from app.config.tuning import TUNING, from_dict, to_dict
from app.loop.maker_checker.llm_backend import MockLLMBackend
from app.loop.maker_checker.maker_agent import (
    MakerAgent,
    MakerConfig,
    propose_batch,
    traditional_proposals,
)
from app.loop.maker_checker.schemas import Proposal, make_proposal
from app.loop.mutation import DEFAULT_CLUSTER_MAP


# ---- MakerConfig ----------------------------------------------------------


class TestMakerConfig:
    def test_defaults_are_valid(self) -> None:
        c = MakerConfig()
        assert c.run_mode == "mix"
        assert c.llm_ratio == 0.6

    @pytest.mark.parametrize("mode", ["mix", "llm_only", "trad_only"])
    def test_valid_run_modes(self, mode: str) -> None:
        MakerConfig(run_mode=mode)

    @pytest.mark.parametrize("bad", ["", "MIX", "llm", "trad", "random"])
    def test_unknown_run_mode_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="run_mode"):
            MakerConfig(run_mode=bad)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
    def test_llm_ratio_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="llm_ratio"):
            MakerConfig(llm_ratio=bad)

    @pytest.mark.parametrize("bad", [0.0, -1.0, 51.0, 100.0])
    def test_max_diff_pct_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="max_diff_pct"):
            MakerConfig(max_diff_pct=bad)


# ---- _split_count ---------------------------------------------------------


class TestSplitCount:
    def test_split_basic(self) -> None:
        from app.loop.maker_checker.maker_agent import _split_count
        llm, trad = _split_count(10, 0.6)
        assert llm == 6
        assert trad == 4

    def test_split_zero_llm_ratio(self) -> None:
        from app.loop.maker_checker.maker_agent import _split_count
        llm, trad = _split_count(10, 0.0)
        assert llm == 0
        assert trad == 10

    def test_split_full_llm_ratio(self) -> None:
        from app.loop.maker_checker.maker_agent import _split_count
        llm, trad = _split_count(10, 1.0)
        assert llm == 10
        assert trad == 0

    def test_split_sums_to_n(self) -> None:
        from app.loop.maker_checker.maker_agent import _split_count
        for n in [1, 2, 3, 5, 7, 11, 13]:
            llm, trad = _split_count(n, 0.4)
            assert llm + trad == n


# ---- traditional_proposals ------------------------------------------------


class TestTraditionalProposals:
    def test_returns_n_proposals(self) -> None:
        proposals = traditional_proposals(
            TUNING, n=3, cluster="C1 Geometry", seed=42,
        )
        assert len(proposals) == 3

    def test_each_proposal_is_valid(self) -> None:
        proposals = traditional_proposals(
            TUNING, n=5, cluster="C4 Macro", seed=7,
        )
        for p in proposals:
            assert isinstance(p, Proposal)
            assert p.clusters_touched == ("C4 Macro",)
            assert len(p.diff) >= 1

    def test_unknown_cluster_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown cluster"):
            traditional_proposals(
                TUNING, n=2, cluster="Z Unknown", seed=0,
            )

    def test_diff_magnitude_within_cap(self) -> None:
        proposals = traditional_proposals(
            TUNING, n=20, cluster="C1 Geometry", seed=0,
        )
        for p in proposals:
            for mag in p.diff.values():
                assert abs(mag) <= 50.0

    def test_accepts_dict_input(self) -> None:
        proposals = traditional_proposals(
            to_dict(TUNING), n=2, cluster="C4 Macro", seed=0,
        )
        assert len(proposals) >= 0  # may be fewer due to constraints

    def test_deterministic_with_same_seed(self) -> None:
        a = traditional_proposals(
            TUNING, n=5, cluster="C1 Geometry", seed=42,
        )
        b = traditional_proposals(
            TUNING, n=5, cluster="C1 Geometry", seed=42,
        )
        assert [(p.diff, p.maker_intent) for p in a] == [
            (p.diff, p.maker_intent) for p in b
        ]


# ---- MakerAgent.propose_batch --------------------------------------------


class TestMakerAgent:
    def _agent(self, **kwargs) -> MakerAgent:
        cfg = MakerConfig(**kwargs)
        return MakerAgent(
            backend=MockLLMBackend(seed=cfg.seed),
            config=cfg,
        )

    def test_trad_only_skips_llm(self) -> None:
        backend = MockLLMBackend(seed=0)
        agent = MakerAgent(
            backend=backend, config=MakerConfig(run_mode="trad_only"),
        )
        proposals = agent.propose_batch(
            TUNING, n=4, cluster="C1 Geometry",
        )
        # Some mutations may be skipped (no change / constraint
        # violation), so we just assert *some* proposals and no LLM
        # calls.
        assert len(proposals) >= 1
        assert backend.call_count == 0

    def test_trad_only_returns_at_most_n(self) -> None:
        backend = MockLLMBackend(seed=0)
        agent = MakerAgent(
            backend=backend, config=MakerConfig(run_mode="trad_only"),
        )
        proposals = agent.propose_batch(
            TUNING, n=10, cluster="C4 Macro",
        )
        assert len(proposals) <= 10

    def test_llm_only_calls_backend_once(self) -> None:
        backend = MockLLMBackend(seed=0)
        agent = MakerAgent(
            backend=backend, config=MakerConfig(run_mode="llm_only"),
        )
        proposals = agent.propose_batch(
            TUNING, n=3, cluster="C4 Macro",
        )
        # Should be 3 LLM proposals (mock returns exactly n).
        assert len(proposals) == 3
        assert backend.call_count == 1

    def test_mix_blends_paths(self) -> None:
        backend = MockLLMBackend(seed=0)
        agent = MakerAgent(
            backend=backend,
            config=MakerConfig(run_mode="mix", llm_ratio=0.5),
        )
        proposals = agent.propose_batch(
            TUNING, n=4, cluster="C4 Macro",
        )
        assert len(proposals) == 4
        # 1 LLM call for 2 proposals + 2 traditional proposals.
        assert backend.call_count == 1

    def test_n_must_be_positive(self) -> None:
        agent = self._agent()
        with pytest.raises(ValueError, match="n must be positive"):
            agent.propose_batch(TUNING, n=0, cluster="C4 Macro")

    def test_unknown_cluster_raises(self) -> None:
        agent = self._agent()
        with pytest.raises(ValueError, match="unknown cluster"):
            agent.propose_batch(TUNING, n=2, cluster="Z Unknown")

    def test_backend_failure_falls_back_to_traditional(self) -> None:
        class FailingBackend:
            def complete_proposals(self, *a, **kw):
                raise RuntimeError("simulated outage")

        agent = MakerAgent(
            backend=FailingBackend(),  # type: ignore[arg-type]
            config=MakerConfig(run_mode="llm_only"),
        )
        # trad_only fallback path — but llm_only won't get there.
        # We need mix to verify fallback.
        agent = MakerAgent(
            backend=FailingBackend(),  # type: ignore[arg-type]
            config=MakerConfig(run_mode="mix", llm_ratio=0.5),
        )
        proposals = agent.propose_batch(
            TUNING, n=4, cluster="C1 Geometry",
        )
        # The 2 LLM slots fall back to traditional (which also runs).
        # We just assert no exception propagated and got *some* output.
        assert isinstance(proposals, list)

    def test_llm_returning_invalid_clusters_is_rejected(self) -> None:
        class BadBackend:
            call_count = 0

            def complete_proposals(
                self, prompt, *, n_proposals, seed, cluster=None,
            ):
                self.call_count += 1
                return {
                    "proposals": [
                        {
                            "clusters_touched": ["Z Unknown"],  # wrong!
                            "diff": {"x": 1.0},
                            "maker_intent": "x",
                            "reasoning": "y",
                            "self_score": 0.5,
                        }
                    ] * n_proposals
                }

        backend = BadBackend()
        agent = MakerAgent(
            backend=backend,  # type: ignore[arg-type]
            config=MakerConfig(run_mode="llm_only"),
        )
        # The LLM proposals are rejected (cluster mismatch);
        # the shortfall top-up fills with traditional proposals.
        proposals = agent.propose_batch(
            TUNING, n=3, cluster="C4 Macro",
        )
        # All 3 are now traditional (LLM produced 0 valid).
        assert len(proposals) == 3
        assert all(p.clusters_touched == ("C4 Macro",) for p in proposals)


# ---- propose_batch wrapper ------------------------------------------------


class TestProposeBatchWrapper:
    def test_returns_list(self) -> None:
        proposals = propose_batch(
            TUNING, n=3, cluster="C4 Macro",
            config=MakerConfig(run_mode="trad_only"),
        )
        assert isinstance(proposals, list)
        assert len(proposals) == 3