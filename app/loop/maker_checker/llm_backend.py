"""LLM backend — pluggable interface + deterministic default mock.

The Maker and Checker agents both depend on this single interface. The
default implementation is :class:`MockLLMBackend`, which returns
deterministic outputs derived from a hash of the prompt — this lets
every test run offline and reproducibly. A real provider (OpenAI,
Anthropic, etc.) can be plugged in by passing it to the agent
constructors or by setting ``MAKER_CHECKER_LLM_BACKEND=openai`` in the
environment (only relevant when ``runner.py`` is wired up).

The interface is intentionally tiny — just two methods:
:func:`complete_json` returns parsed JSON. Callers are responsible for
validating the output against :mod:`app.loop.maker_checker.schemas`.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Optional, Protocol, runtime_checkable

# ---- Interface ------------------------------------------------------------


@runtime_checkable
class LLMBackend(Protocol):
    """Pluggable LLM interface.

    Implementations must:

    * Return parsed JSON (a dict or list) on success.
    * Raise :class:`LLMBackendError` on any failure (network, parse,
      schema mismatch).
    * Be **deterministic** for the same ``prompt + seed`` pair unless
      the implementation documents otherwise.
    """

    def complete_json(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        seed: Optional[int] = None,
    ) -> Any:  # pragma: no cover  # Protocol body — never executed at runtime
        ...


class LLMBackendError(RuntimeError):
    """Raised by any :class:`LLMBackend` on parse / network failure."""


# ---- Mock backend ---------------------------------------------------------


class MockLLMBackend:
    """Deterministic mock that derives JSON output from the prompt.

    The mock is *not* a real LLM. It is sufficient for unit tests, CI,
    and offline development. The two methods that the agents actually
    use are :meth:`complete_proposals` (Maker) and
    :meth:`complete_verdict` (Checker), but the generic
    :meth:`complete_json` is also implemented for flexibility.

    For the Maker: we hash the prompt and pick a cluster / field /
    magnitude pseudo-randomly from a deterministic pool.

    For the Checker: we hash the prompt and pick a verdict that is
    biased by a configurable ``accept_rate`` so tests can simulate
    over- or under- confident LLMs.
    """

    def __init__(
        self,
        *,
        accept_rate: float = 0.7,
        seed: int = 0,
    ) -> None:
        if not 0.0 <= accept_rate <= 1.0:
            raise ValueError(f"accept_rate must be in [0, 1]; got {accept_rate}")
        self.accept_rate = accept_rate
        self.seed = seed
        self.call_count = 0

    # Generic interface (used by tests and the agents' fallback path).
    def complete_json(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        seed: Optional[int] = None,
    ) -> Any:
        self.call_count += 1
        # Use a stable hash to pick a "verdict"-shaped blob.
        h = hashlib.sha256(f"{self.seed}|{seed}|{prompt}".encode()).digest()
        accept = (h[0] / 255.0) < self.accept_rate
        return {
            "_mock": True,
            "accept": accept,
            "score": h[1] / 255.0,
            "confidence": h[2] / 255.0,
        }

    # Maker-specific helper used by maker_agent.
    def complete_proposals(
        self,
        prompt: str,
        *,
        n_proposals: int,
        seed: Optional[int] = None,
        cluster: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return a JSON shape mimicking the Maker LLM output.

        The mock picks ``n_proposals`` distinct cluster+field combos
        using a hash of the prompt + seed. The shape matches the
        contract documented in :mod:`schemas`.

        If ``cluster`` is provided, every proposal is constrained to
        that cluster (simulating a real LLM that respects its system
        prompt's "only propose for cluster X" instruction). When
        ``cluster`` is None, the mock picks from a fixed pool of
        clusters.
        """
        self.call_count += 1
        clusters = (
            [cluster]
            if cluster is not None
            else [
                "C1 Geometry",
                "C2 Discipline",
                "C3 Confluence",
                "C4 Macro",
                "C5 Windows",
            ]
        )
        fields = [
            ("atr_stop_buffer", 5.0, 25.0),
            ("fib_tolerance_pct", 0.05, 0.20),
            ("min_confluence_score", 1.0, 5.0),
            ("extreme_deviation_pct", 5.0, 25.0),
            ("trend_alignment_min", 1.0, 5.0),
        ]
        seed_eff = seed if seed is not None else self.seed
        h = hashlib.sha256(f"{seed_eff}|{prompt}|{n_proposals}|{cluster}".encode()).digest()
        proposals = []
        for i in range(n_proposals):
            c_idx = h[(2 * i) % len(h)] % len(clusters)
            f_idx = h[(2 * i + 1) % len(h)] % len(fields)
            field_name, lo, hi = fields[f_idx]
            mag_raw = h[(3 * i) % len(h)] / 255.0
            magnitude = round((mag_raw * 2 - 1) * 30.0, 2)  # in [-30, +30]
            score = h[(4 * i) % len(h)] / 255.0
            proposals.append(
                {
                    "clusters_touched": [clusters[c_idx]],
                    "diff": {field_name: magnitude},
                    "maker_intent": f"mock_intent_{i}",
                    "reasoning": f"mock reasoning for proposal {i}",
                    "expected_impact": {
                        "sharpe": f"+{magnitude / 100:.2f}",
                        "calmar": "neutral",
                        "worst_regime": "neutral",
                    },
                    "self_score": round(score, 3),
                }
            )
        return {"proposals": proposals}

    # Checker-specific helper used by checker_agent.
    def complete_verdict(
        self,
        prompt: str,
        *,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        """Return a JSON shape mimicking the Checker LLM output."""
        self.call_count += 1
        seed_eff = seed if seed is not None else self.seed
        h = hashlib.sha256(f"verdict|{seed_eff}|{prompt}".encode()).digest()
        accept = (h[0] / 255.0) < self.accept_rate
        score = h[1] / 255.0
        confidence = max(0.5, h[2] / 255.0)
        flags = []
        if h[3] % 5 == 0:
            flags.append(
                {
                    "severity": "low",
                    "issue": "mock flag for testing",
                }
            )
        return {
            "checker_score": round(score, 3),
            "confidence": round(confidence, 3),
            "raw_score": round(score, 3),
            "components": {
                "cross_symbol_consistency": round(h[4] / 255.0, 3),
                "regime_robustness": round(h[5] / 255.0, 3),
                "trade_quality": round(h[6] / 255.0, 3),
                "statistical_sufficiency": round(h[7] / 255.0, 3),
            },
            "flags": flags,
            "accept": bool(accept),
            "feedback": "mock verdict for testing",
        }


# ---- Factory --------------------------------------------------------------


def default_backend() -> LLMBackend:
    """Return the backend selected by environment, or the mock.

    Environment variable ``MAKER_CHECKER_LLM_BACKEND`` may be set to
    ``"openai"`` or ``"anthropic"`` to opt into a real provider. Those
    providers are not bundled (audit §2.3 feature-flag design) — the
    mock is the default for offline / CI use.
    """
    name = os.environ.get("MAKER_CHECKER_LLM_BACKEND", "mock").lower()
    if name in ("mock", ""):
        return MockLLMBackend()
    # Real providers intentionally raise loudly if requested but not
    # wired — the user must explicitly extend this module.
    raise LLMBackendError(
        f"LLM backend {name!r} is not configured; only 'mock' is " f"available out of the box. See audit §2.9 for rollback."
    )


__all__ = [
    "LLMBackend",
    "LLMBackendError",
    "MockLLMBackend",
    "default_backend",
]
