"""Maker-Checker separation architecture (v1.1).

Implements the design from
``docs/maker-checker-architecture-audit-and-optimization.md``.

Submodules:

* :mod:`app.loop.maker_checker.schemas`      — Pydantic-free dataclasses for
  Proposal, Verdict, MakerSelfScore, MergeResult, CalibrationParams. The
  types are the contract between Maker, Checker, and Arbiter.
* :mod:`app.loop.maker_checker.isolation`    — strips Maker artifacts from
  backtest results before they reach the Checker (three strictness modes).
* :mod:`app.loop.maker_checker.calibration`  — Platt-scaling calibration of
  raw checker scores, with reliability-diagram evaluation.
* :mod:`app.loop.maker_checker.llm_backend`  — pluggable LLM backend
  (deterministic mock by default; real provider pluggable via env).
* :mod:`app.loop.maker_checker.maker_agent`  — Maker: batch proposer that
  emits mutation ops (not raw parameter values) plus self-scores.
* :mod:`app.loop.maker_checker.checker_agent`— Checker: information-isolated
  LLM verifier; sits alongside the M4 heuristic checker.
* :mod:`app.loop.maker_checker.arbiter`      — decision tree that fuses M4
  heuristics + LLM Checker + Maker self-score, with 5-D Pareto back-compat.
* :mod:`app.loop.maker_checker.runner`       — orchestrator that glues
  Maker → worker subprocess → Checker → Arbiter, with feature-flag bypass.
* :mod:`app.loop.maker_checker.review`       — CLI for human review of
  ``suspicious_to_human`` candidates.

Design constraints (audit §2.3):

* Maker outputs *mutation operations* (cluster + signed magnitude), never
  raw parameter values; the geometric invariants of ``TuningConstants``
  (``fib_tp1 < fib_tp2 < fib_tp3``, frozen fields) are enforced by code
  via :func:`app.loop.mutation.mutate_field`, never trusted to the LLM.
* Checker inputs are stripped of Maker artifacts by :mod:`isolation`
  before reaching the LLM.
* ``MAKER_CHECKER_ENABLED=false`` returns the runner to the original
  driver path with zero LLM calls.

All public functions in this package should be importable without any
LLM credentials; the default backend is deterministic.
"""
from __future__ import annotations

from app.loop.maker_checker.schemas import (
    Proposal,
    Verdict,
    MakerSelfScore,
    MergeResult,
    CalibrationParams,
)

__all__ = [
    "Proposal",
    "Verdict",
    "MakerSelfScore",
    "MergeResult",
    "CalibrationParams",
]