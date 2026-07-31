"""Stage 4a: Callback quality scoring (0-20).

v3 changelog item 4 + docs/HarmonicSignal-Bench.md Stage 4a.

Sub-scores:
* mae_mfe_ratio  (0-6):  ratio = mae/mfe (or 1.0 if mfe=0)
                          <0.2:6, <0.4:4, <0.6:2, else 0
* callback_depth (0-5):  depth in ATR
                          <0.3:5, <0.6:3, <1.0:1, >=1.0:0
* callback_time  (0-3):  callback_bars / bars_held
                          <20%:3, <40%:2, <60%:1, >=60%:0
* volume         (0-3):  callback_volume_ratio
                          <0.8:3 (缩量), 0.8-1.2:2, >1.2:0 (放量)
* stop_buffer    (0-3):  buffer_consumption = closest / risk
                          <30%:3, <60%:2, <90%:1, >=90%:0

Mutates ``rec.stage4a_score`` and returns it.
"""

from __future__ import annotations

from bench.dataset.signal_record import SignalRecord


def _mae_mfe_subscore(mae: float | None, mfe: float | None) -> float:
    if mae is None or mfe is None:
        return 0.0
    if mfe <= 0:
        ratio = 1.0
    else:
        ratio = mae / mfe
    if ratio < 0.2:
        return 6.0
    if ratio < 0.4:
        return 4.0
    if ratio < 0.6:
        return 2.0
    return 0.0


def _depth_subscore(depth: float | None) -> float:
    if depth is None:
        return 0.0
    if depth < 0.3:
        return 5.0
    if depth < 0.6:
        return 3.0
    if depth < 1.0:
        return 1.0
    return 0.0


def _time_subscore(callback_bars: int | None, bars_held: int | None) -> float:
    if callback_bars is None or bars_held is None or bars_held <= 0:
        return 0.0
    ratio = callback_bars / bars_held
    if ratio < 0.2:
        return 3.0
    if ratio < 0.4:
        return 2.0
    if ratio < 0.6:
        return 1.0
    return 0.0


def _volume_subscore(volume_ratio: float | None) -> float:
    if volume_ratio is None:
        return 0.0
    if volume_ratio < 0.8:
        return 3.0  # 缩量 = benign
    if volume_ratio <= 1.2:
        return 2.0  # normal
    return 0.0  # 放量 = malicious


def _stop_buffer_subscore(buffer: float | None) -> float:
    """buffer = closest_to_stop / risk_distance. 0 = safe; 1 = at stop."""
    if buffer is None:
        return 0.0
    if buffer < 0.3:
        return 3.0
    if buffer < 0.6:
        return 2.0
    if buffer < 0.9:
        return 1.0
    return 0.0


def _buffer_consumption(rec: SignalRecord) -> float | None:
    """Compute stop-buffer consumption: closest_to_stop / risk_distance.

    None if no MAE was observed (no risk taken).
    """
    if rec.mae is None or rec.atr_at_entry is None or rec.atr_at_entry <= 0:
        return None
    risk = abs(rec.entry_price - rec.stop_price)
    if risk <= 0:
        return None
    return rec.mae / risk


def stage4a_score(rec: SignalRecord) -> float:
    """Compute Stage 4a score; mutate the record; return the score."""
    buffer = _buffer_consumption(rec)
    total = (
        _mae_mfe_subscore(rec.mae, rec.mfe)
        + _depth_subscore(rec.callback_depth)
        + _time_subscore(rec.callback_bars, rec.bars_held)
        + _volume_subscore(rec.callback_volume_ratio)
        + _stop_buffer_subscore(buffer)
    )
    rec.stage4a_score = round(total, 4)
    return rec.stage4a_score
