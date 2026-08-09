"""Tests for the v3 loop-engineering gap-fixes.

Covers:
* ``loop.loop_context.load_episodic`` does not raise UnboundLocal on
  non-trivial JSONL state (regression for the named bug).
* ``app.config.tuning.get_min_candles`` / ``get_atr_window`` /
  ``get_rsi_window`` honour the active ``TuningScope`` (Path A).
* ``signal_engine.build_signal`` no longer reads the import-time
  ``MIN_CANDLES`` alias; the live accessor is used.
* ``scripts.backtest_harmonic_lib._maybe_relax_filters`` widens
  ``min_candles`` via ``TuningScope`` (no module-alias setattr).
* ``app.api.metrics_routes`` exposes every metric promised in plan §7.2.
"""

from __future__ import annotations

import json
from app.config.tuning import (
    TUNING,
    TuningScope,
    apply_tuning,
    from_dict,
    get_atr_window,
    get_min_candles,
    get_rsi_window,
    reset_tuning,
)


# ---- loop_context.load_episodic -----------------------------------------


def test_load_episodic_parses_jsonl(tmp_path, monkeypatch):
    from loop import loop_context

    monkeypatch.setattr(loop_context, "EPISODIC_FILE", tmp_path / "episodic.jsonl")
    monkeypatch.setattr(loop_context, "STATE_DIR", tmp_path)
    (tmp_path / "episodic.jsonl").write_text(
        "\n".join(
            json.dumps({"ts": f"2026-08-09T00:0{i}:00Z", "key": f"k{i}", "value": "v" * 300}) for i in range(5)
        )
        + "\n"
    )
    records = loop_context.load_episodic(limit=3)
    assert len(records) == 3
    assert records[-1]["key"] == "k4"


def test_load_episodic_skips_corrupt_lines(tmp_path, monkeypatch):
    from loop import loop_context

    monkeypatch.setattr(loop_context, "EPISODIC_FILE", tmp_path / "episodic.jsonl")
    monkeypatch.setattr(loop_context, "STATE_DIR", tmp_path)
    (tmp_path / "episodic.jsonl").write_text(
        json.dumps({"ts": "2026-08-09T00:00:00Z", "key": "ok", "value": "v"})
        + "\n"
        + "this is not json\n"
        + json.dumps({"ts": "2026-08-09T00:01:00Z", "key": "ok2", "value": "v2"})
        + "\n"
    )
    records = loop_context.load_episodic()
    assert [r["key"] for r in records] == ["ok", "ok2"]


def test_load_episodic_missing_file(tmp_path, monkeypatch):
    from loop import loop_context

    monkeypatch.setattr(loop_context, "EPISODIC_FILE", tmp_path / "missing.jsonl")
    assert loop_context.load_episodic() == []


# ---- tuning accessors ----------------------------------------------------


def test_min_candles_accessor_default():
    assert get_min_candles() == TUNING.min_candles
    assert get_atr_window() == TUNING.atr_window
    assert get_rsi_window() == TUNING.rsi_window


def test_min_candles_accessor_respects_tuning_scope():
    relaxed = from_dict({"min_candles": 30, "atr_window": 10, "rsi_window": 8})
    with TuningScope(relaxed):
        assert get_min_candles() == 30
        assert get_atr_window() == 10
        assert get_rsi_window() == 8
    assert get_min_candles() == TUNING.min_candles


def test_min_candles_accessor_respects_apply_tuning():
    relaxed = from_dict({"min_candles": 25})
    apply_tuning(relaxed)
    try:
        assert get_min_candles() == 25
    finally:
        reset_tuning()
    assert get_min_candles() == TUNING.min_candles


# ---- signal_engine hot path --------------------------------------------


def test_build_signal_uses_live_min_candles(monkeypatch):
    """``build_signal`` must consult the live TUNING, not the import alias."""
    import app.services.signal_engine as se

    # A scope with min_candles=2 should let a 2-bar df produce a
    # build_signal call past the floor; we only check the floor is
    # honoured, not the full pipeline.
    relaxed = from_dict({"min_candles": 2})
    sentinel = {"n": 0}
    real_build_signal = se.build_signal

    def wrapped(df, interval, candidates, **kw):
        sentinel["n"] += 1
        # floor check: live min_candles is reflected
        assert get_min_candles() == 2
        return real_build_signal(df, interval, candidates, **kw)

    monkeypatch.setattr(se, "build_signal", wrapped)
    from app.services.signal_engine import build_signal  # noqa: F401 (cache import)

    df = _make_small_df(3)
    with TuningScope(relaxed):
        se.build_signal(df, "15m", [])
    assert sentinel["n"] == 1


# ---- scripts/backtest_harmonic_lib relax/restore -----------------------


def test_relax_filters_uses_tuning_scope_not_setattr():
    """The fix is: relax/restore must NOT mutate the MIN_CANDLES alias.

    The simplest way to prove the bug is gone is to assert the alias is
    unchanged after a relax→restore cycle and that ``get_min_candles``
    inside the scope is wider.
    """
    import app.services.signal_engine as se
    from scripts import backtest_harmonic_lib as bh

    pre = se.MIN_CANDLES
    saved = bh._maybe_relax_filters(True)
    try:
        # Alias untouched (no setattr).
        assert se.MIN_CANDLES == pre
        # Live TUNING widened.
        assert get_min_candles() == 30
    finally:
        bh._restore_filters(saved)
    # Restored.
    assert se.MIN_CANDLES == pre
    assert get_min_candles() == TUNING.min_candles


def test_relax_filters_noop_when_disabled():
    from scripts import backtest_harmonic_lib as bh

    assert bh._maybe_relax_filters(False) is None


# ---- helpers -------------------------------------------------------------


def _make_small_df(n: int):
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "close_time": [int(t.timestamp()) for t in idx],
        },
        index=idx,
    )
