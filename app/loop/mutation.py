from __future__ import annotations

import random
from dataclasses import replace
from typing import Optional

from app.config.tuning import TUNING, TuningConstants

# --- Cluster definitions -----------------------------------------------------


# Cluster map: cluster_name -> list of (field_name, kind, kwargs)
# kind ∈ {"abs_small", "rel_large", "int_window", "int_threshold",
#         "dict_per_key", "enum"}.
#
# Built from inspection of TuningConstants. To add a new tunable field:
# 1) add it to TuningConstants
# 2) put it here in the right cluster
# 3) (optionally) add a post_init / __post_perturb__ validator
#
# Frozen / structural fields (fib_tp1/2/3, extended_patterns, htf_rule,
# funding_confluence_default, tp_close_pcts) are intentionally excluded
# from the map — the loop tunes only the soft, continuous knobs whose
# hard + soft constraints can be auto-repaired in __post_init__.
"""Per-cluster mutation operators for the loop-tuning project.

Implements the loop-tuning plan §3 (5 parameter clusters) + §3.2
(per-field σ, not flat 5%). Each cluster gets its own mutator that
respects the field type:

* ``abs_small``   — continuous small (e.g. fib level weights);  N(0, 0.05)
* ``rel_large``   — continuous large (e.g. confluence multipliers);  N(0, 0.05) relative
* ``int_window``  — integer window sizes; N(0, 5), clamped to [min, max]
* ``int_threshold`` — integer thresholds;  N(0, 3)
* ``dict_per_key`` — dict field (e.g. family_bias); perturb each key by N(0, 2)
* ``enum``        — declared enum field; uniform random pick from allowed

A mutator takes a :class:`TuningConstants` and returns a NEW instance
with the cluster fields perturbed (or unchanged if the random draw
happens to land exactly at zero — that's allowed; mutation is allowed
to be a no-op so we get "control" candidates naturally).

The cluster map is built once via :func:`default_cluster_map` and is the
single source of truth — adding a new tunable field means adding it to
the relevant cluster entry here.
"""

DEFAULT_CLUSTER_MAP: dict[str, list[tuple[str, str, dict]]] = {
    # C1 Geometry — fee/slippage knobs and the PRZ distance tolerance
    "C1 Geometry": [
        ("atr_prz_sweep", "abs_small", {"min": 0.05, "max": 1.0}),
        ("fee_rate", "abs_small", {"min": 0.0002, "max": 0.005}),
        ("slippage_rate", "abs_small", {"min": 0.0001, "max": 0.005}),
        ("atr_stop_buffer", "dict_per_key", {"per_key": 0.20}),
    ],
    # C2 Discipline — risk gates, regime thresholds, ATR sizing, TTLs
    "C2 Discipline": [
        ("max_d_age_bars", "int_threshold", {"min": 5, "max": 60}),
        ("max_prz_distance_atr", "abs_small", {"min": 1.0, "max": 6.0}),
        ("max_forming_prz_width_atr", "abs_small", {"min": 0.3, "max": 3.0}),
        ("authenticity_halve", "int_threshold", {"min": 30, "max": 70}),
        ("authenticity_veto", "int_threshold", {"min": 10, "max": 40}),
        ("adverse_sharpe_threshold", "abs_small", {"min": 0.5, "max": 2.5}),
        ("regime_moderate", "int_threshold", {"min": 20, "max": 50}),
        ("regime_high", "int_threshold", {"min": 40, "max": 80}),
        ("target_atr_pct", "abs_small", {"min": 1.0, "max": 5.0}),
        ("default_ttl_bars", "int_threshold", {"min": 20, "max": 80}),
    ],
    # C3 Confluence — weights that combine multiple harmonic signals
    "C3 Confluence": [
        ("a_grade_min", "int_threshold", {"min": 50, "max": 90}),
        ("a_grade_min_high_quant", "int_threshold", {"min": 60, "max": 95}),
        ("high_quant_position_mult", "abs_small", {"min": 0.3, "max": 1.0}),
        ("confluence_weights", "dict_per_key", {"per_key": 5.0, "target_sum": 100}),
        ("pattern_base_score", "dict_per_key", {"per_key": 2.0}),
        ("stability_window", "int_threshold", {"min": 3, "max": 15}),
    ],
    # C4 Macro — macro bias overrides, regime weights
    "C4 Macro": [
        ("slope_trend_up", "abs_small", {"min": 0.2, "max": 1.0}),
        ("slope_trend_down", "abs_small", {"min": -1.0, "max": -0.2}),
        ("mult_trending_aligned", "abs_small", {"min": 0.8, "max": 1.5}),
        ("mult_ranging_aligned", "abs_small", {"min": 0.8, "max": 1.5}),
        ("mult_trending_inverse", "abs_small", {"min": 0.3, "max": 0.9}),
        ("mult_ranging_inverse", "abs_small", {"min": 0.2, "max": 0.9}),
        ("mult_extreme_inverse", "abs_small", {"min": 0.9, "max": 1.5}),
        ("mult_data_short", "abs_small", {"min": 0.5, "max": 1.0}),
        ("extreme_deviation_pct", "abs_small", {"min": 10.0, "max": 40.0}),
        ("min_daily_bars", "int_window", {"min": 100, "max": 400}),
    ],
    # C5 Windows — rolling-window lookbacks for technical indicators
    "C5 Windows": [
        ("min_candles", "int_threshold", {"min": 30, "max": 200}),
        ("atr_window", "int_window", {"min": 5, "max": 50}),
        ("atr_long_window", "int_window", {"min": 50, "max": 200}),
        ("rsi_window", "int_window", {"min": 5, "max": 30}),
        ("volume_ma_window", "int_window", {"min": 5, "max": 50}),
        ("swing_lookback", "int_window", {"min": 20, "max": 120}),
        ("quant_trap_lookback", "int_window", {"min": 20, "max": 120}),
        ("volume_authenticity_window", "int_window", {"min": 20, "max": 120}),
        ("quant_regime_window", "int_window", {"min": 50, "max": 200}),
        ("per_bar_sharpe_window", "int_window", {"min": 5, "max": 50}),
    ],
}


# --- Mutators ----------------------------------------------------------------


def _gauss(rng: random.Random, sigma: float) -> float:
    return rng.gauss(0.0, sigma)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


_VALID_KINDS = frozenset(
    {
        "abs_small",
        "rel_large",
        "int_window",
        "int_threshold",
        "dict_per_key",
        "enum",
    }
)


def mutate_field(
    name: str,
    kind: str,
    kwargs: dict,
    t: TuningConstants,
    rng: random.Random,
    *,
    sigma_scale: float = 1.0,
) -> TuningConstants:
    """Apply one perturbation to ``t`` and return the new instance.

    On constraint violations the field is left unchanged — the candidate
    stays valid and downstream operators see a partial mutation rather
    than an exception. We retry up to ``max_retries`` times to absorb
    the occasional repairable violation (e.g. confluence_weights sum
    drift after a per-key perturbation).

    An unknown ``kind`` is a programmer error and raises immediately
    (it is NOT retried — silent dropping would hide configuration bugs).
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"unknown kind {kind!r} for field {name!r}")
    max_retries = kwargs.get("max_retries", 5)
    for _ in range(max_retries + 1):
        try:
            new_t = _apply_one_mutation(name, kind, kwargs, t, rng, sigma_scale)
        except (ValueError, TypeError):
            continue
        if new_t is t:
            return t
        return new_t
    return t


def _apply_one_mutation(name, kind, kwargs, t, rng, sigma_scale):
    cur = getattr(t, name)

    if kind == "abs_small":
        sigma = sigma_scale * 0.05
        new = cur + _gauss(rng, sigma)
        new = _clip(new, kwargs["min"], kwargs["max"])
        return replace(t, **{name: new})

    if kind == "rel_large":
        sigma = sigma_scale * 0.05
        factor = 1.0 + _gauss(rng, sigma)
        new = cur * factor
        new = _clip(new, kwargs["min"], kwargs["max"])
        return replace(t, **{name: new})

    if kind == "int_window":
        sigma = sigma_scale * 5.0
        new = int(round(cur + _gauss(rng, sigma)))
        new = _clip(new, kwargs["min"], kwargs["max"])
        return replace(t, **{name: int(new)})

    if kind == "int_threshold":
        sigma = sigma_scale * 3.0
        new = int(round(cur + _gauss(rng, sigma)))
        new = _clip(new, kwargs["min"], kwargs["max"])
        return replace(t, **{name: int(new)})

    if kind == "dict_per_key":
        per_key = sigma_scale * kwargs.get("per_key", 0.10)
        lo = kwargs.get("min", -50.0)
        hi = kwargs.get("max", 200.0)
        new = {}
        for k, v in cur.items():
            nv = v + _gauss(rng, per_key)
            new[k] = _clip(nv, lo, hi)
        # Optional renormalisation for fields that must sum to a constant.
        target_sum = kwargs.get("target_sum")
        if target_sum is not None:
            s = sum(new.values())
            if s != 0:
                scale = target_sum / s
                # Round each value to int (these dicts are typically int-keyed
                # weights). The final value gets the leftover to land exactly.
                scaled = {k: int(round(v * scale)) for k, v in new.items()}
                drift = target_sum - sum(scaled.values())
                if scaled:
                    last_key = next(reversed(scaled))
                    scaled[last_key] += drift
                new = scaled
        return replace(t, **{name: new})

    if kind == "enum":
        allowed = kwargs["allowed"]
        if cur in allowed and rng.random() < sigma_scale:
            new = rng.choice([x for x in allowed if x != cur])
            return replace(t, **{name: new})
        return t

    raise ValueError(f"unknown kind {kind!r} for field {name!r}")


def mutate_cluster(
    t: TuningConstants,
    cluster: str,
    rng: random.Random | None = None,
    *,
    sigma_scale: float = 1.0,
    n_mutations: Optional[int] = None,
    cluster_map: Optional[dict[str, list[tuple[str, str, dict]]]] = None,
) -> TuningConstants:
    """Mutate one field (or ``n_mutations`` fields) in ``cluster``.

    ``n_mutations=None`` ⇒ mutate exactly one randomly-chosen field in the
    cluster (the conservative default — corresponds to plan §3 "mutate one
    cluster per generation").

    Mutations respect the cluster map's kind + bounds. The new instance
    still goes through ``TuningConstants.__post_init__`` for cross-field
    constraints — invalid candidates are auto-repaired in-place, which is
    intentional: a tiny constraint repair is cheaper than rejecting a
    candidate on a minor ordering violation.
    """
    rng = rng or random.Random()
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    members = cm.get(cluster, [])
    if not members:
        return t
    if n_mutations is None:
        n_mutations = 1
    n_mutations = min(n_mutations, len(members))

    chosen = rng.sample(members, n_mutations)
    for name, kind, kwargs in chosen:
        t = mutate_field(name, kind, kwargs, t, rng, sigma_scale=sigma_scale)
    return t


def mutate_all_clusters(
    t: TuningConstants,
    rng: random.Random | None = None,
    *,
    sigma_scale: float = 1.0,
    cluster_map: Optional[dict[str, list[tuple[str, str, dict]]]] = None,
) -> TuningConstants:
    """One mutation in EACH cluster. Useful for global sensitivity scans."""
    rng = rng or random.Random()
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    for cluster in cm:
        t = mutate_cluster(t, cluster, rng=rng, sigma_scale=sigma_scale, cluster_map=cm)
    return t


def random_child(
    parent: Optional[TuningConstants] = None,
    *,
    seed: Optional[int] = None,
    cluster_map: Optional[dict[str, list[tuple[str, str, dict]]]] = None,
) -> TuningConstants:
    """Return a fresh :class:`TuningConstants` mutated from ``parent`` (or
    :data:`TUNING`) at exactly one randomly-chosen cluster, with exactly
    one field perturbed. Useful as the seed for CMA-ES-style restart."""
    rng = random.Random(seed)
    base = parent if parent is not None else TUNING
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    cluster = rng.choice(list(cm))
    return mutate_cluster(base, cluster, rng=rng, cluster_map=cm)


def cluster_fields(
    cluster: str,
    cluster_map: Optional[dict[str, list[tuple[str, str, dict]]]] = None,
) -> list[str]:
    """Return the field names in ``cluster`` (handy for sensitivity scans)."""
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    return [n for n, _, _ in cm.get(cluster, [])]


def all_clusters(
    cluster_map: Optional[dict[str, list[tuple[str, str, dict]]]] = None,
) -> list[str]:
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    return list(cm)
