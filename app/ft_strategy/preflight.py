"""D-FT-24 — preflight gate, 6 items.

Per plan §6.6: enqueue worker 之前 sync run, any failure => 422, no enqueue.

Six checks:
  1. strategy_text — AST parse + has populate_indicators / populate_entry_trend /
     populate_exit_trend
  2. import_check — ta.RSI / ta.EMA imports present
  3. informative_tf — `@informative('TF')` decorator uses whitelisted timeframe
  4. data_file_exists — pair × timeframe CSV present in user_data/data/
  5. param_in_set — params are in hyperopt spaces
  6. research_md_length — already ≥ 200 chars (delegated to research_md_validator)

Pure function on a structured ``PreflightRequest``; returns a structured
``PreflightResult`` (mirroring tuning_promotion_v3 D-FT-23).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


ALLOWED_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})
REQUIRED_METHODS: tuple[str, ...] = (
    "populate_indicators",
    "populate_entry_trend",
    "populate_exit_trend",
)
REQUIRED_IMPORTS: tuple[str, ...] = ("ta.RSI", "ta.EMA", "IStrategy")


# Cache: preflight result is purely derivable from input; cache by (content_hash, ...).
# We skip caching in v0 to keep the function easy to test.


@dataclass(frozen=True)
class PreflightCheck:
    label: str
    passed: bool
    note: str = ""
    observed: Optional[str] = None
    expected: Optional[str] = None


@dataclass(frozen=True)
class PreflightRequest:
    """Inputs needed to evaluate preflight.

    Fields are all optional except ``strategy_text`` and ``research_md``;
    items 5 (param_in_set) is skipped if ``hyperopt_spaces`` is None.
    """

    strategy_text: str
    research_md: str
    pair: str = "BTC/USDT"
    interval: str = "5m"
    user_data_dir: Optional[str] = None
    hyperopt_spaces: Optional[tuple[str, ...]] = None  # e.g. ("buy_rsi", "sell_rsi")


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    items: tuple[PreflightCheck, ...]
    failing_labels: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "items": [
                {
                    "label": i.label,
                    "passed": i.passed,
                    "note": i.note,
                    "observed": i.observed,
                    "expected": i.expected,
                }
                for i in self.items
            ],
            "failing_labels": list(self.failing_labels),
        }


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _check_ast_and_methods(text: str) -> PreflightCheck:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return PreflightCheck(
            label="ast_parse",
            passed=False,
            note=f"syntax error: {e.msg} at line {e.lineno}",
        )

    # Find class definitions; the freqtrade IStrategy typically declares
    # exactly one class inheriting IStrategy.
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef):
                    defined.add(stmt.name)

    missing = [m for m in REQUIRED_METHODS if m not in defined]
    if missing:
        return PreflightCheck(
            label="ast_methods",
            passed=False,
            note=f"missing required methods: {missing}",
            observed=str(sorted(defined)),
            expected=str(sorted(REQUIRED_METHODS)),
        )
    return PreflightCheck(label="ast_methods", passed=True, note="all required methods present")


def _check_imports(text: str) -> PreflightCheck:
    # Cheap textual grep; AST-level would miss "from X import Y" aliased forms.
    found: set[str] = set()
    for token in REQUIRED_IMPORTS:
        if token in text:
            found.add(token)
    missing = [t for t in REQUIRED_IMPORTS if t not in found]
    if missing:
        return PreflightCheck(
            label="imports",
            passed=False,
            note=f"missing imports: {missing}",
            observed=str(sorted(found)),
            expected=str(sorted(REQUIRED_IMPORTS)),
        )
    return PreflightCheck(label="imports", passed=True, note="all required imports present")


def _check_informative_timeframes(text: str) -> PreflightCheck:
    # Find @informative(...) decorators. First positional arg = TF.
    # Optional second arg is a cross-pair reference (e.g. "BTC/USDT")
    # and must be filtered out so we don't flag it as an invalid TF.
    multi = re.compile(
        r"@informative\(\s*[\'\"]([^\'\"]+)[\'\"](?:\s*,)"
    )
    single = re.compile(
        r"@informative\(\s*[\'\"]([^\'\"]+)[\'\"]\s*\)"
    )
    all_hits = set(multi.findall(text)) | set(single.findall(text))
    found: set[str] = {t for t in all_hits if "/" not in t}

    if not found:
        # No informative decorators is fine — strategy can still be single-TF.
        return PreflightCheck(
            label="informative_tf",
            passed=True,
            note="no informative decorators (single-TF strategy is allowed)",
        )
    bad = sorted(found - ALLOWED_TIMEFRAMES)
    if bad:
        return PreflightCheck(
            label="informative_tf",
            passed=False,
            note=f"timeframes out of whitelist: {bad}",
            observed=str(sorted(found)),
            expected=str(sorted(ALLOWED_TIMEFRAMES)),
        )
    return PreflightCheck(label="informative_tf", passed=True, note=f"timeframes ok: {sorted(found)}")


def _check_data_file(
    pair: str, interval: str, user_data_dir: Optional[str]
) -> PreflightCheck:
    if not user_data_dir:
        return PreflightCheck(
            label="data_file_exists",
            passed=True,
            note="no user_data_dir configured; skipping file existence check",
        )
    base = Path(user_data_dir)
    # Freqtrade convention: BTC/USDT → BTC_USDT-1h.feather / .csv
    flat_pair = pair.replace("/", "_")
    candidates = [
        base / "data" / f"{flat_pair}-{interval}.feather",
        base / "data" / f"{flat_pair}-{interval}.csv",
        base / "data" / f"{flat_pair}-{interval}.parquet",
    ]
    for path in candidates:
        if path.exists():
            return PreflightCheck(
                label="data_file_exists",
                passed=True,
                note=f"found: {path.name}",
            )
    return PreflightCheck(
        label="data_file_exists",
        passed=False,
        note=(
            f"no data file for {pair} ({interval}) in {base / 'data'}; "
            "run prepare.py / download_candles first"
        ),
    )


def _check_param_keys(text: str, spaces: Optional[tuple[str, ...]]) -> PreflightCheck:
    if spaces is None or len(spaces) == 0:
        return PreflightCheck(
            label="param_in_set",
            passed=True,
            note="no hyperopt_spaces configured; skipping param-in-set check",
        )
    # Look for `space.value` syntax (e.g. IntParameter / CategoricalParameter)
    # plus bare references like `buy_rsi`.
    pattern = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")
    referenced: set[str] = set(pattern.findall(text))
    missing = sorted(s for s in spaces if s not in referenced)
    if missing:
        return PreflightCheck(
            label="param_in_set",
            passed=False,
            note=f"hyperopt spaces not referenced: {missing}",
            observed=str(sorted(referenced))[:120],
            expected=str(sorted(spaces)),
        )
    return PreflightCheck(
        label="param_in_set",
        passed=True,
        note=f"all {len(spaces)} space(s) referenced",
    )


def _check_research_md_length(text: str) -> PreflightCheck:
    if len(text) < 200:
        return PreflightCheck(
            label="research_md_length",
            passed=False,
            note=f"len={len(text)} < 200",
            observed=str(len(text)),
            expected=">=200",
        )
    return PreflightCheck(label="research_md_length", passed=True, note=f"len={len(text)}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_preflight(req: PreflightRequest) -> PreflightResult:
    """Run all 6 checks. Returns structured result; never raises for false returns.

    Defense: non-PreflightRequest input yields a structured failure.
    """
    if not isinstance(req, PreflightRequest):
        return PreflightResult(
            ok=False,
            items=(PreflightCheck(
                label="type_check",
                passed=False,
                note=f"req must be PreflightRequest, got {type(req).__name__}",
            ),),
            failing_labels=("type_check",),
        )

    items: list[PreflightCheck] = []
    items.append(_check_ast_and_methods(req.strategy_text))
    items.append(_check_imports(req.strategy_text))
    items.append(_check_informative_timeframes(req.strategy_text))
    items.append(_check_data_file(req.pair, req.interval, req.user_data_dir))
    items.append(_check_param_keys(req.strategy_text, req.hyperopt_spaces))
    items.append(_check_research_md_length(req.research_md))

    failing = tuple(i for i in items if not i.passed)
    return PreflightResult(
        ok=not failing,
        items=tuple(items),
        failing_labels=tuple(i.label for i in failing),
    )


# ---------------------------------------------------------------------------
# Module constants (D-FT-16: capabilities endpoint echoes these)
# ---------------------------------------------------------------------------


def module_constants() -> dict[str, object]:
    return {
        "ALLOWED_TIMEFRAMES": sorted(ALLOWED_TIMEFRAMES),
        "REQUIRED_METHODS": list(REQUIRED_METHODS),
        "REQUIRED_IMPORTS": list(REQUIRED_IMPORTS),
        "RESEARCH_MD_MIN_LENGTH": 200,
    }
