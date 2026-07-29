"""Maker agent — emits mutation ops (never raw parameter values).

The Maker is the creative half of the Maker-Checker architecture. Its
job is to propose **how** the next generation of ``TuningConstants``
should be mutated, not **what** the new values should be. This is a
deliberate design choice (audit §2.3):

* The LLM is bad at respecting ``TuningConstants``' geometric
  invariants (``fib_tp1 < fib_tp2 < fib_tp3``, frozen fields). Letting
  it propose raw values leads to constant validation failures.
* The LLM is good at *picking a direction* (which cluster, which
  field, what sign, what magnitude). It is bad at arithmetic, but
  mutation code (``app.loop.mutation.mutate_field``) is good at
  arithmetic.
* Output schema is restricted to *cluster + signed magnitude*, so the
  Pydantic-style dataclass validation in :mod:`schemas` rejects malformed
  outputs.

Public API:

* :class:`MakerAgent` — orchestrates a batch of proposals.
* :func:`propose_batch` — convenience wrapper.
* :func:`traditional_proposals` — the math-only baseline (no LLM).
* The :class:`MakerConfig` dataclass carries the configuration so tests
  can construct it without parsing YAML.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.config.tuning import TuningConstants, from_dict, to_dict
from app.loop.maker_checker.llm_backend import LLMBackend, MockLLMBackend
from app.loop.maker_checker.schemas import (
    MakerSelfScore,
    Proposal,
    make_proposal,
)
from app.loop.mutation import DEFAULT_CLUSTER_MAP, mutate_field


logger = logging.getLogger("app.loop.maker_checker.maker_agent")


# ---- Configuration --------------------------------------------------------


VALID_RUN_MODES = ("mix", "llm_only", "trad_only")


@dataclass(frozen=True)
class MakerConfig:
    """Static configuration for a :class:`MakerAgent`.

    Fields:

    * ``run_mode`` — ``"mix"`` (default) blends LLM and traditional
      variants in the ratio ``llm_ratio``; ``"llm_only"`` ignores the
      traditional path; ``"trad_only"`` ignores the LLM path.
    * ``llm_ratio`` — fraction of proposals to draw from the LLM path
      (clamped to ``[0, 1]``). Only meaningful when ``run_mode == "mix"``.
    * ``max_diff_pct`` — passed to :class:`Proposal` to bound magnitudes.
    * ``seed`` — deterministic seed for the LLM mock backend.
    * ``n_mutations`` — used by the traditional path; the magnitude's
      sigma is ``mutate_field``'s default × this scale.
    """

    run_mode: str = "mix"
    llm_ratio: float = 0.6
    max_diff_pct: float = 50.0
    seed: int = 0
    n_mutations: int = 1

    def __post_init__(self) -> None:
        if self.run_mode not in VALID_RUN_MODES:
            raise ValueError(
                f"run_mode must be one of {VALID_RUN_MODES}; got "
                f"{self.run_mode!r}"
            )
        if not 0.0 <= self.llm_ratio <= 1.0:
            raise ValueError(
                f"llm_ratio must be in [0, 1]; got {self.llm_ratio}"
            )
        if self.max_diff_pct <= 0 or self.max_diff_pct > 50.0:
            raise ValueError(
                f"max_diff_pct must be in (0, 50]; got {self.max_diff_pct}"
            )


# ---- Traditional (math-only) mutation ------------------------------------


def _split_count(n: int, llm_ratio: float) -> tuple[int, int]:
    """Split ``n`` proposals into (llm_count, trad_count).

    Rounds so the sum is exactly ``n``; ties go to the LLM side.
    """
    llm = round(n * llm_ratio)
    llm = max(0, min(n, llm))
    return llm, n - llm


def traditional_proposals(
    parent: TuningConstants | dict,
    *,
    n: int,
    cluster: str,
    seed: int,
) -> list[Proposal]:
    """Generate ``n`` math-only mutation proposals.

    Each proposal targets one cluster (``cluster``). The mutated field
    is selected round-robin from :data:`DEFAULT_CLUSTER_MAP`'s entries
    for that cluster. The magnitude is computed from the diff between
    parent and mutated ``TuningConstants``.
    """
    cluster_specs = DEFAULT_CLUSTER_MAP.get(cluster)
    if not cluster_specs:
        raise ValueError(
            f"unknown cluster {cluster!r}; known: "
            f"{list(DEFAULT_CLUSTER_MAP)}"
        )
    parent_tuning = (
        parent if isinstance(parent, TuningConstants)
        else from_dict(parent)
    )
    out: list[Proposal] = []
    for i in range(n):
        # Round-robin across the cluster's fields for diversity.
        spec = cluster_specs[i % len(cluster_specs)]
        field_name, kind, kwargs = spec
        sub_seed = seed * 1000 + i
        rng = random.Random(sub_seed)
        try:
            mutated = mutate_field(
                field_name, kind, kwargs, parent_tuning, rng,
            )
        except Exception as exc:  # noqa: BLE001 — constraint violation etc.
            logger.debug(
                "traditional mutation failed for %s: %s", field_name, exc
            )
            continue
        old_val = getattr(parent_tuning, field_name, None)
        new_val = getattr(mutated, field_name, None)
        if old_val is None or new_val is None:  # pragma: no cover  # defensive: dataclass fields are never None
            continue
        if old_val == new_val:
            # No effective change; skip.
            continue
        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            if old_val == 0:
                magnitude = 0.0
            else:
                magnitude = round(
                    (new_val - old_val) / abs(old_val) * 100.0, 2
                )
            # Clamp to ±50 to satisfy Proposal.MAX_DIFF_PCT.
            magnitude = max(min(magnitude, 50.0), -50.0)
        else:
            # Non-numeric fields (e.g. dicts): skip from diff tracking.
            continue  # pragma: no cover  # defensive: cluster specs are all numeric
        proposal = make_proposal(
            clusters_touched=(cluster,),
            diff={field_name: magnitude},
            maker_intent=f"trad_{cluster.replace(' ', '_').lower()}_{i}",
            reasoning=f"traditional {kind} perturbation on {field_name}",
            self_score=0.5,  # neutral — no LLM confidence
            proposal_id=f"trad-{cluster.replace(' ', '_').lower()}-{i}",
        )
        out.append(proposal)
    return out


# ---- Maker agent ----------------------------------------------------------


@dataclass
class MakerAgent:
    """Proposes a batch of ``Proposal``s per generation.

    Construction is cheap; :meth:`propose_batch` is the only stateful
    operation. The LLM backend is injected so tests can substitute a
    deterministic mock; production wiring uses
    :func:`app.loop.maker_checker.llm_backend.default_backend`.
    """

    backend: LLMBackend = field(default_factory=MockLLMBackend)
    config: MakerConfig = field(default_factory=MakerConfig)

    def propose_batch(
        self,
        parent: TuningConstants | dict,
        *,
        n: int,
        cluster: str,
        history: Sequence[Any] = (),
        pareto_front: Sequence[Any] = (),
    ) -> list[Proposal]:
        """Return ``n`` :class:`Proposal`s derived from ``parent``.

        The split between LLM and traditional variants follows
        ``self.config.run_mode`` and ``llm_ratio``. When the LLM path
        produces an invalid proposal, we silently fall back to the
        traditional path for that slot — the agent never blocks a
        generation because of a single malformed LLM output.
        """
        if n <= 0:
            raise ValueError(f"n must be positive; got {n}")
        if cluster not in DEFAULT_CLUSTER_MAP:
            raise ValueError(
                f"unknown cluster {cluster!r}; known: "
                f"{list(DEFAULT_CLUSTER_MAP)}"
            )

        if self.config.run_mode == "trad_only":
            return traditional_proposals(
                parent, n=n, cluster=cluster, seed=self.config.seed
            )

        llm_n, trad_n = _split_count(n, self.config.llm_ratio)
        out: list[Proposal] = []

        # In llm_only mode, all proposals come from the LLM. In mix mode,
        # we allocate llm_n to the LLM and trad_n to the traditional path;
        # the shortfall from a flaky LLM is top-up'd with traditional.
        llm_target = n if self.config.run_mode == "llm_only" else llm_n
        if llm_target > 0:
            llm_out = self._propose_via_llm(
                parent,
                n=llm_target,
                cluster=cluster,
                history=history,
                pareto_front=pareto_front,
            )
            out.extend(llm_out)
            # Top up with traditional if LLM fell short.
            shortfall = llm_target - len(llm_out)
            if shortfall > 0:
                out.extend(
                    traditional_proposals(
                        parent, n=shortfall, cluster=cluster,
                        seed=self.config.seed,
                    )
                )

        if self.config.run_mode == "mix" and trad_n > 0:
            out.extend(
                traditional_proposals(
                    parent, n=trad_n, cluster=cluster,
                    seed=self.config.seed,
                )
            )

        return out[:n]

    # ---- internal ---------------------------------------------------------

    def _propose_via_llm(
        self,
        parent: TuningConstants | dict,
        *,
        n: int,
        cluster: str,
        history: Sequence[Any],
        pareto_front: Sequence[Any],
    ) -> list[Proposal]:
        prompt = _build_prompt(
            parent, n=n, cluster=cluster,
            history=history, pareto_front=pareto_front,
        )
        try:
            raw = self.backend.complete_proposals(
                prompt, n_proposals=n, seed=self.config.seed,
                cluster=cluster,
            )
        except Exception as exc:  # noqa: BLE001 — any backend error
            logger.warning("LLM backend failed; falling back: %s", exc)
            return []
        proposals_raw = raw.get("proposals") or []
        out: list[Proposal] = []
        for p in proposals_raw:
            proposal = _parse_proposal(p, cluster=cluster)
            if proposal is not None:
                out.append(proposal)
        return out


def _build_prompt(
    parent: TuningConstants | dict,
    *,
    n: int,
    cluster: str,
    history: Sequence[Any],
    pareto_front: Sequence[Any],
) -> str:
    """Compose the prompt for the Maker LLM.

    Stable, deterministic string format. The :class:`MockLLMBackend`
    hashes this prompt, so any whitespace change will break tests —
    keep the format fixed.
    """
    parent_dict = to_dict(parent) if isinstance(parent, TuningConstants) else dict(parent)
    cluster_specs = DEFAULT_CLUSTER_MAP.get(cluster, ())
    # cluster_specs is a list of (name, kind, kwargs) tuples.
    field_names = ",".join(spec[0] for spec in cluster_specs)
    return (
        f"maker|cluster={cluster}|n={n}|"
        f"fields={field_names}|"
        f"parent={sorted(parent_dict.keys())[:5]}|"
        f"history_len={len(history)}|"
        f"pareto_len={len(pareto_front)}"
    )


def _parse_proposal(raw: dict, *, cluster: str) -> Proposal | None:
    """Build a :class:`Proposal` from an LLM JSON output, or return None.

    Returns ``None`` if the JSON doesn't match the contract (cluster
    wrong, magnitude out of range, missing fields). The caller falls
    back to the traditional path on a ``None`` result.
    """
    if not isinstance(raw, dict):
        return None
    touched = raw.get("clusters_touched")
    diff = raw.get("diff")
    intent = raw.get("maker_intent")
    reasoning = raw.get("reasoning")
    self_score = raw.get("self_score")
    proposal_id = raw.get("proposal_id", "")
    if not isinstance(touched, (list, tuple)) or not touched:
        return None
    if not isinstance(diff, dict) or not diff:
        return None
    if not isinstance(intent, str):
        return None
    if not isinstance(reasoning, str):
        return None
    if not isinstance(self_score, (int, float)):
        return None
    # Enforce: the Maker may only touch the cluster it was asked about.
    # If it returned other clusters, fall back to None.
    if any(c != cluster for c in touched):
        return None
    try:
        return make_proposal(
            clusters_touched=tuple(touched),
            diff={k: float(v) for k, v in diff.items()},
            maker_intent=intent,
            reasoning=reasoning,
            self_score=float(self_score),
            proposal_id=str(proposal_id),
        )
    except (ValueError, TypeError):
        return None


# ---- Convenience ----------------------------------------------------------


def propose_batch(
    parent: TuningConstants | dict,
    *,
    n: int,
    cluster: str,
    config: MakerConfig | None = None,
    backend: LLMBackend | None = None,
    history: Sequence[Any] = (),
    pareto_front: Sequence[Any] = (),
) -> list[Proposal]:
    """Convenience wrapper that constructs a default :class:`MakerAgent`."""
    agent = MakerAgent(
        backend=backend or MockLLMBackend(),
        config=config or MakerConfig(),
    )
    return agent.propose_batch(
        parent, n=n, cluster=cluster,
        history=history, pareto_front=pareto_front,
    )


__all__ = [
    "MakerConfig",
    "MakerAgent",
    "propose_batch",
    "traditional_proposals",
]