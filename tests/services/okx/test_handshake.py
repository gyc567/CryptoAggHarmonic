"""Tests OKX fill → HISTORY.jsonl round-trip with source mutex enforcement."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.loop.state import SourceMutexError, append_history
from app.services.okx import handshake
from app.services.okx.handshake import OKXFill, write_fill_to_history


@pytest.fixture
def history_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the OKX handshake module's _LOOP_STATE_ROOT to a tmp dir.

    The module reads LOOP_STATE_ROOT at import time, so we patch the
    module attribute directly rather than the env var. This isolates
    the test from the repo's .scratch/loop_state (which may contain
    real freqtrade records).
    """
    root = tmp_path / "loop_state"
    (root / "HISTORY.jsonl.outbox").mkdir(parents=True)
    monkeypatch.setattr(handshake, "_LOOP_STATE_ROOT", root, raising=False)
    monkeypatch.setattr(handshake, "HISTORY_PATH", root / "HISTORY.jsonl", raising=False)
    monkeypatch.setattr(handshake, "OUTBOX_DIR", root / "HISTORY.jsonl.outbox", raising=False)
    return root


def _make_fill(paper: bool = True, uuid: str = "abcdef1234567890abcdef12") -> OKXFill:
    return OKXFill(
        uuid=uuid, instId="BTC-USDT", side="buy",
        fillPx=65000.0, fillSz=0.001, fee=0.05,
        ts="2026-08-11T13:47:26.123456Z",
        ordId="999", clOrdId="OKX-LOOP-test1234",
        paper=paper, salt_version=3,
    )


class TestWriteFillToHistory:
    def test_paper_fill_recorded(self, history_root: Path) -> None:
        # Use a uuid where uuid[:12] is unambiguous (>= 12 chars).
        fill = _make_fill(paper=True, uuid="paperuuid-aaaa")
        write_fill_to_history(fill, params={"stoploss": -0.08})
        history = history_root / "HISTORY.jsonl"
        assert history.exists()
        lines = [json.loads(l) for l in history.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        rec = lines[0]
        assert rec["source"] == "okx_paper"
        assert rec["paper"] is True
        assert rec["instrument"] == "BTC-USDT"
        assert rec["fill_px"] == 65000.0
        assert rec["params"] == {"stoploss": -0.08}
        assert rec["salt_version"] == 3
        assert rec["clOrdId"] == "OKX-LOOP-test1234"
        # candidate_id = f"okx-{uuid[:12]}" — verify the 12-char slice
        assert rec["candidate_id"] == f"okx-{fill.uuid[:12]}"

    def test_live_fill_recorded(self, history_root: Path) -> None:
        fill = _make_fill(paper=False, uuid="liveuuid12345")
        write_fill_to_history(fill)
        rec = json.loads((history_root / "HISTORY.jsonl").read_text().strip())
        assert rec["source"] == "okx_live"
        assert rec["paper"] is False

    def test_outbox_cleaned_after_write(self, history_root: Path) -> None:
        fill = _make_fill(uuid="cleanup001")
        write_fill_to_history(fill)
        outbox = history_root / "HISTORY.jsonl.outbox"
        leftovers = [f for f in outbox.iterdir() if f.name == "cleanup001.json"]
        assert leftovers == []


class TestSourceMutex:
    def test_paper_then_live_promotion_allowed(self, history_root: Path) -> None:
        write_fill_to_history(_make_fill(paper=True, uuid="promote01"))
        write_fill_to_history(_make_fill(paper=False, uuid="promote02"))
        recs = (history_root / "HISTORY.jsonl").read_text().splitlines()
        assert len(recs) == 2

    def test_freqtrade_vs_okx_mutex(self, history_root: Path) -> None:
        from app.loop.state import ensure_root
        ensure_root(history_root)
        # OKX producer's candidate_id is f"okx-{uuid[:12]}". Pick a uuid
        # whose 12-char slice plus the "okx-" prefix matches a known
        # freqtrade candidate_id. Use uuid = "sharedcand1x" (12 chars).
        # Resulting OKX candidate_id = "okx-sharedcand1x".
        okx_uuid = "sharedcand1x"
        freqtrade_candidate = f"okx-{okx_uuid[:12]}"
        assert freqtrade_candidate == "okx-sharedcand1x"
        append_history(
            {"candidate_id": freqtrade_candidate, "gen": 5, "source": "freqtrade_hyperopt",
             "cluster": "cma_es", "decision": "accepted", "fitness": {}, "params": {},
             "salt_version": 1, "timestamp": "2026-08-11T00:00:00Z",
             "strategy_name": "HarmonicGartley1h"},
            root=history_root,
        )
        fill = OKXFill(
            uuid=okx_uuid, instId="BTC-USDT", side="buy",
            fillPx=65000.0, fillSz=0.001, fee=0.05,
            ts="2026-08-11T13:47:26Z", ordId="999", clOrdId="OKX-LOOP-test",
            paper=True, salt_version=3,
        )
        with pytest.raises(SourceMutexError, match="source mutex"):
            write_fill_to_history(fill)
