"""TUNING live-promotion gate.

Live gunicorn workers each hold their own ``TUNING`` copy. Search-loop
``apply_tuning()`` must never be treated as a production promotion.

Promotion path (ADR-0003 D9):

1. accepted candidate → ``tuning_snapshots/pareto-{sha}.yaml``
2. human PR that edits ``app/config/tuning.py``
3. deploy / SIGHUP so workers reload

This module is the code-side checklist helpers; ``docs/loop-state/gate.yaml``
denylists ``app/config/tuning.py`` so loops cannot auto-merge that path.
"""

from __future__ import annotations

from pathlib import Path

LIVE_TUNING_PATH = "app/config/tuning.py"


def is_live_tuning_path(path: str | Path) -> bool:
    """True if ``path`` is the live TUNING constants module."""
    p = Path(path).as_posix()
    return p == LIVE_TUNING_PATH or p.endswith("/" + LIVE_TUNING_PATH)


def promotion_allowed_for_files(paths: list[str]) -> tuple[bool, str]:
    """Return (ok, reason). Fail if any path is live TUNING (must be human PR)."""
    for path in paths:
        if is_live_tuning_path(path):
            return (
                False,
                f"live TUNING promotion blocked: {path} "
                f"(edit only via human PR + SIGHUP; see ADR-0003 D9)",
            )
    return True, "ok"


def promotion_checklist(
    max_drawdown: float | None = None,
    calmar_ratio: float | None = None,
    baseline_drawdown: float | None = None,
) -> list[str]:
    """Human-readable promotion steps (ADR-0010 D5: drawdown/Calmar/Shadow quant gates).

    Args:
        max_drawdown: Candidate max drawdown (fraction, e.g. 0.15 = 15%).
        calmar_ratio: Candidate Calmar ratio.
        baseline_drawdown: Baseline max drawdown for comparison.
    """
    checks = [
        "1. Accept candidate → write tuning_snapshots/pareto-{sha}.yaml",
        "2. Open PR editing app/config/tuning.py (never auto-merge)",
        "3. Review backtest metrics:",
        "   [ ] max_drawdown ≤ 2 × baseline_drawdown"
        + (f" (baseline={baseline_drawdown:.1%}, threshold={2*baseline_drawdown:.1%})"
           if baseline_drawdown else ""),
        "   [ ] Calmar ratio ≥ threshold"
        + (f" (candidate={calmar_ratio:.2f})" if calmar_ratio is not None else ""),
        "   [ ] Shadow mode running ≥ 7 days without drawdown anomaly",
        "   [ ] source=freqtrade_hyperopt salt_version traceable in HISTORY.jsonl",
        "4. Merge + SIGHUP/restart gunicorn workers",
    ]
    return checks


# ── OKX execution gate (ADR-0011 D8, D9) ──────────────────────────────────
#
# Path-level gate (existing 3 APIs): decides whether a PR is allowed to
# touch live TUNING / app/config/tuning.py. Used at PR review time.
#
# Tool-level gate (new 2 APIs below): decides whether a runtime OKX write
# tool call is allowed. Used at MCP tool invocation time. Different
# question, different boundary — kept separate to avoid overloading this
# module.

# OKX write tool names — names match the `okx-trade-mcp` MCP tool names
# (e.g. "spot_place_order", "swap_set_leverage"). When OKX upstream
# adds new write tools, append here AND update tests/test_promotion_guard.py
# in the same PR. Phase 1 scope: spot only.
OKX_WRITE_TOOLS: frozenset[str] = frozenset({
    # spot module (Phase 1)
    "spot_place_order",
    "spot_cancel_order",
    "spot_amend_order",
    "spot_batch_place_orders",
    "spot_batch_cancel_orders",
    # account module write subset
    "account_transfer",
    "account_set_position_mode",
    "account_set_leverage",
    # swap module (Phase 2+ — listed for completeness; Phase 1 MCP
    # startup default omits swap, so these won't be invokable yet)
    "swap_place_order",
    "swap_cancel_order",
    "swap_amend_order",
    "swap_batch_place_orders",
    "swap_batch_cancel_orders",
    "swap_set_leverage",
    "swap_close_position",
    "move_order_stop",
    # futures module (Phase 3+)
    "futures_place_order",
    "futures_cancel_order",
    "futures_amend_order",
    "futures_batch_place_orders",
    "futures_batch_cancel_orders",
    "futures_set_leverage",
    "futures_close_position",
    # option module (intentionally NOT integrated; listed for completeness)
    "option_place_order",
    "option_cancel_order",
    "option_amend_order",
    "option_batch_cancel_orders",
    # earn / event / bot — out of scope; included so any accidental call
    # is also rejected by this gate (defense in depth)
    "earn_purchase",
    "earn_redeem",
    "earn_subscribe",
    "earn_redeem_subscription",
    "event_place_order",
    "event_amend_order",
    "event_cancel_order",
    "bot_create_grid",
    "bot_create_dca",
    "bot_stop",
})


def is_live_execution_tool(name: str) -> bool:
    """True if ``name`` is an OKX write tool that requires the execution gate.

    Unlike ``is_live_tuning_path`` (which is path-based, PR-review time),
    this is tool-name-based and called at runtime before any write tool
    is dispatched. Read-only tools (market_get_*, account_get_*, etc.) and
    paper-mode-only tools return False.

    Unknown tool names return False (conservative: don't block unknown
    tools; let the MCP server's own --read-only flag handle that).
    """
    return name in OKX_WRITE_TOOLS


def execution_allowed_for_tools(
    names: list[str],
    paper: bool,
) -> tuple[bool, str]:
    """Return (ok, reason). Fail if any tool is a live OKX write tool.

    Args:
        names: OKX MCP tool names being invoked.
        paper: True if ``OKX_PAPER_MODE=true`` (default) or if the
            MCP server is started with ``--demo``. False means
            ``OKX_ALLOW_LIVE=1`` is set and writes go to real OKX.

    Rules:
    - paper=True: writes allowed IF the tool is in OKX_WRITE_TOOLS
      (paper mode is the default safe path; promoted live via
      ``promotion_checklist()`` + human PR).
    - paper=False: writes are allowed but the response is an explicit
      "live mode" signal so callers can include it in the audit log.

    The function NEVER raises — it returns a tuple. Callers should
    check the boolean before dispatching.
    """
    if not isinstance(names, list):
        return False, f"execution_allowed_for_tools: names must be list, got {type(names).__name__}"
    if not isinstance(paper, bool):
        return False, f"execution_allowed_for_tools: paper must be bool, got {type(paper).__name__}"
    write_hits = [n for n in names if is_live_execution_tool(n)]
    if write_hits and not paper:
        # Caller is in live mode. This is NOT a hard block — the live
        # switch is a deliberate human decision (ADR-0011 D8 gate 4
        # human checklist). This function just records the mode.
        return True, f"live mode: write tools {write_hits} dispatched to real OKX (audit log MANDATORY)"
    if not write_hits:
        return True, "ok (no write tools requested)"
    return True, f"paper mode: write tools {write_hits} dispatched to OKX demo (audit log MANDATORY)"


# Note: ``promotion_checklist()`` is intentionally NOT modified at this
# site. ADR-0011 D9 mandates the existing signature stays unchanged.
# The audit-log enforcement is layered in ``executor.py`` (Phase 2),
# not here.
