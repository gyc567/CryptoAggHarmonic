"""Tests for :mod:`app.loop.maker_checker.llm_backend`.

Covers: mock determinism, accept_rate behaviour, default_backend env
handling, error surfacing.
"""

from __future__ import annotations

import pytest

from app.loop.maker_checker.llm_backend import (
    LLMBackend,
    LLMBackendError,
    MockLLMBackend,
    default_backend,
)


class TestMockLLMBackend:
    def test_default_is_deterministic(self) -> None:
        m = MockLLMBackend()
        a = m.complete_json("hello world")
        b = m.complete_json("hello world")
        assert a == b

    def test_accept_rate_clamped(self) -> None:
        with pytest.raises(ValueError):
            MockLLMBackend(accept_rate=1.5)
        with pytest.raises(ValueError):
            MockLLMBackend(accept_rate=-0.1)

    def test_complete_json_returns_shape(self) -> None:
        m = MockLLMBackend()
        out = m.complete_json("test")
        assert out["_mock"] is True
        assert isinstance(out["accept"], bool)
        assert 0.0 <= out["score"] <= 1.0
        assert 0.0 <= out["confidence"] <= 1.0

    def test_complete_json_increments_counter(self) -> None:
        m = MockLLMBackend()
        m.complete_json("a")
        m.complete_json("b")
        m.complete_json("c")
        assert m.call_count == 3

    def test_complete_proposals_returns_n(self) -> None:
        m = MockLLMBackend()
        out = m.complete_proposals("test", n_proposals=5)
        assert len(out["proposals"]) == 5

    def test_complete_proposals_schema_shape(self) -> None:
        m = MockLLMBackend()
        out = m.complete_proposals("test", n_proposals=2)
        for p in out["proposals"]:
            assert isinstance(p["clusters_touched"], list)
            assert len(p["clusters_touched"]) == 1
            assert "diff" in p
            assert "self_score" in p
            assert 0.0 <= p["self_score"] <= 1.0

    def test_complete_proposals_diff_magnitude_within_range(self) -> None:
        m = MockLLMBackend()
        out = m.complete_proposals("test", n_proposals=20)
        for p in out["proposals"]:
            for _, mag in p["diff"].items():
                # Mock generates magnitudes in [-30, +30], well below ±50 cap.
                assert abs(mag) <= 30.0

    def test_complete_verdict_shape(self) -> None:
        m = MockLLMBackend()
        out = m.complete_verdict("test")
        assert 0.0 <= out["checker_score"] <= 1.0
        assert 0.0 <= out["confidence"] <= 1.0
        assert "components" in out
        for _k, v in out["components"].items():
            assert 0.0 <= v <= 1.0
        assert isinstance(out["accept"], bool)

    def test_high_accept_rate_yields_more_accepts(self) -> None:
        # With accept_rate=1.0, every verdict should accept.
        m = MockLLMBackend(accept_rate=1.0)
        for i in range(20):
            out = m.complete_verdict(f"prompt_{i}")
            assert out["accept"] is True

    def test_zero_accept_rate_yields_all_rejects(self) -> None:
        m = MockLLMBackend(accept_rate=0.0)
        for i in range(20):
            out = m.complete_verdict(f"prompt_{i}")
            assert out["accept"] is False

    def test_seed_changes_output(self) -> None:
        m1 = MockLLMBackend(seed=1)
        m2 = MockLLMBackend(seed=2)
        # Different seeds → different proposal hashes (statistically).
        outs1 = [m1.complete_proposals("x", n_proposals=3) for _ in range(10)]
        outs2 = [m2.complete_proposals("x", n_proposals=3) for _ in range(10)]
        # At least one should differ across the two seeds.
        assert any(o1["proposals"][0]["diff"] != o2["proposals"][0]["diff"] for o1, o2 in zip(outs1, outs2, strict=False))


class TestProtocol:
    def test_mock_satisfies_protocol(self) -> None:
        m = MockLLMBackend()
        assert isinstance(m, LLMBackend)


class TestDefaultBackend:
    def test_default_returns_mock(self, monkeypatch) -> None:
        monkeypatch.delenv("MAKER_CHECKER_LLM_BACKEND", raising=False)
        b = default_backend()
        assert isinstance(b, MockLLMBackend)

    def test_unknown_backend_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_LLM_BACKEND", "openai")
        with pytest.raises(LLMBackendError, match="not configured"):
            default_backend()
