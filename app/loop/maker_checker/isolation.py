"""Isolation — strip Maker artifacts before the Checker sees the data.

Three strictness levels (audit §2.7):

* ``strict`` — remove all Maker fingerprints including candidate_id hash,
  generation_id, parent_id, clusters_touched, maker_intent, reasoning,
  diff, expected_impact, self_score, prompt_version.
* ``moderate`` — keep candidate_id verbatim; remove Maker intent fields.
* ``minimal`` — keep candidate_id, clusters_touched, diff; remove only
  maker_intent and reasoning (debug mode only).

The function is pure: it returns a new dict and never mutates the
input. The set of fields to strip is versioned (``STRIPPED_FIELDS_V1``)
so that a future schema change can add a new constant rather than
mutating the old one.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any


STRICT = "strict"
MODERATE = "moderate"
MINIMAL = "minimal"
VALID_LEVELS = (STRICT, MODERATE, MINIMAL)


# Fields removed at every isolation level (Maker creative-layer fields).
_BASE_STRIPPED = (
    "maker_intent",
    "reasoning",
    "self_score",
    "prompt_version",
)

# Fields removed in moderate+strict (lineage/structure that leaks
# experiment metadata).
_STRICT_EXTRA = (
    "clusters_touched",
    "diff",
    "expected_impact",
    "generation_id",
    "parent_id",
    "parent_metrics",
    "gen",
    "cluster",
    "fingerprint",
)

# Minimal mode only strips the creative intent; lineage/structure
# stays for debugging the Checker's view of the data.
_MINIMAL_EXTRA = ("maker_intent", "reasoning")

STRIPPED_FIELDS_V1 = {
    STRICT: _BASE_STRIPPED + _STRICT_EXTRA,
    MODERATE: _BASE_STRIPPED,
    MINIMAL: _MINIMAL_EXTRA,
}


def _salted_id(raw_id: str, salt: str) -> str:
    """Deterministic salted hash for candidate_id in strict mode."""
    return hashlib.sha256(f"{salt}|{raw_id}".encode()).hexdigest()[:16]


def strip_maker_artifacts(
    payload: dict[str, Any],
    *,
    level: str = STRICT,
    salt: str = "",
) -> dict[str, Any]:
    """Return a copy of ``payload`` with Maker fields removed.

    Parameters
    ----------
    payload
        The dict that the Checker would otherwise see. Must contain
        either ``candidate_id`` (moderate/minimal) or the salted
        equivalent (strict).
    level
        One of ``"strict"``, ``"moderate"``, ``"minimal"``.
    salt
        Salt for ``candidate_id`` re-hashing. Required for strict mode
        unless ``payload["candidate_id"]`` already looks salted (16 hex
        chars). A random per-generation salt prevents the Checker from
        correlating runs across generations.

    Returns
    -------
    A new dict with the stripped fields removed. Original is untouched.

    Raises
    ------
    ValueError
        If ``level`` is unknown, or if strict mode is requested but
        neither ``candidate_id`` nor ``salt`` is provided.
    """
    if level not in VALID_LEVELS:
        raise ValueError(
            f"unknown isolation level {level!r}; must be one of "
            f"{VALID_LEVELS}"
        )

    out = dict(payload)
    for field_name in STRIPPED_FIELDS_V1[level]:
        out.pop(field_name, None)

    if level == STRICT:
        raw_id = payload.get("candidate_id", "")
        if not raw_id:
            raise ValueError(
                "strict isolation requires payload['candidate_id']"
            )
        # Re-hash so the Checker cannot correlate across generations.
        out["candidate_id"] = _salted_id(raw_id, salt)

    return out


def list_stripped_fields(level: str) -> tuple[str, ...]:
    """Return the tuple of fields that would be stripped at ``level``.

    Useful for diagnostics and tests.
    """
    if level not in VALID_LEVELS:
        raise ValueError(f"unknown isolation level {level!r}")
    return STRIPPED_FIELDS_V1[level]


# ---- Leakage measurement -------------------------------------------------


def leakage_metrics(
    verdicts_a: list[bool],
    verdicts_b: list[bool],
) -> dict[str, float]:
    """Quantify how much the Checker's verdict depends on Maker fields.

    The test (audit §2.7) constructs two parallel sets of inputs that
    differ *only* in Maker-artifact fields (``A`` = real Maker output;
    ``B`` = same trade ledger with ``clusters_touched`` replaced by a
    fake label). If the Checker's verdicts diverge between ``A`` and
    ``B``, the isolation is leaking.

    Metrics returned:

    * ``kl_divergence`` — KL(A || B) over accept/reject Bernoulli. 0.0
      means no divergence.
    * ``disagreement_rate`` — fraction of candidates where the verdict
      flipped between ``A`` and ``B``. Should be < 0.10 for strict
      isolation.

    Both inputs must be the same length. Empty input returns zeros.
    """
    if len(verdicts_a) != len(verdicts_b):
        raise ValueError("verdicts_a and verdicts_b must be same length")
    n = len(verdicts_a)
    if n == 0:
        return {"kl_divergence": 0.0, "disagreement_rate": 0.0,
                "n": 0}

    p_a = sum(verdicts_a) / n
    p_b = sum(verdicts_b) / n

    # Bernoulli KL. Add tiny epsilon to avoid log(0).
    eps = 1e-9
    p_a_c = max(min(p_a, 1.0 - eps), eps)
    p_b_c = max(min(p_b, 1.0 - eps), eps)
    kl = (
        p_a_c * (0 if p_a_c <= 0 else (0 if p_b_c <= 0 else
              __import__("math").log(p_a_c / p_b_c)))
        + (1 - p_a_c) * (0 if (1 - p_a_c) <= 0 else
              (0 if (1 - p_b_c) <= 0 else
               __import__("math").log((1 - p_a_c) / (1 - p_b_c))))
    )

    disagree = sum(1 for a, b in zip(verdicts_a, verdicts_b) if a != b) / n

    return {
        "kl_divergence": max(0.0, kl),
        "disagreement_rate": disagree,
        "n": float(n),
    }


def make_salt() -> str:
    """Return a random per-generation salt (hex).

    Wraps :func:`os.urandom` for testability — callers can monkeypatch
    ``os.urandom`` if they need determinism.
    """
    return os.urandom(8).hex()


__all__ = [
    "STRICT",
    "MODERATE",
    "MINIMAL",
    "VALID_LEVELS",
    "STRIPPED_FIELDS_V1",
    "strip_maker_artifacts",
    "list_stripped_fields",
    "leakage_metrics",
    "make_salt",
]