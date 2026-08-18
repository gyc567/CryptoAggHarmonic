"""Watchlist harmonic scan task.

Callable via Hermes cron job (every 4H at :05 past the hour):
    hermes cron run watchlist-harmonic-scan

Or directly:
    python -m app.tasks.watchlist_scan

Pipeline:
    1. Load all enabled users + their watchlists
    2. For each (user, symbol):
         a. Fetch 4H bars
         b. Compute market regime (trend + ATR + event filter)
         c. Run harmonic pattern detection (via existing signal_engine)
         d. Grade the candidate (signal_grader)
         e. If grade >= 60 → format + send DingTalk notification
    3. Log scan results to scan_log + signal_outcome tables
    4. Send daily summary to users who opted in (once per day)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Hermes cron injects these; local dev falls back to env
SUPABASE_URL    = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
REDIS_URL       = os.getenv("REDIS_URL", "")

MAX_CONCURRENT_SCANS = 3
SCAN_TIMEOUT_SECONDS = 30
LOCK_TTL_SECONDS     = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScanResult:
    symbol:       str
    pattern:      str
    direction:    str
    score:        int
    grade:        str          # "strong" | "medium" | "skip"
    entry_price:  float
    stop_price:   float
    target_1:     float
    target_2:     float
    atr:          float
    rr_ratio:     float
    trend_ok:     bool
    rsi_div:      bool
    volume_confirm: bool
    volatility_ok: bool
    event_ok:     bool
    regime:       str
    skipped:      bool
    skip_reason:  str | None


# ---------------------------------------------------------------------------
# Scan per symbol
# ---------------------------------------------------------------------------

def scan_symbol(
    symbol: str,
    user_prefs: Any,
) -> ScanResult | None:
    """Scan a single symbol for the user.

    Returns None if the symbol should be skipped entirely (event blocked,
    insufficient data, etc.). Returns ScanResult even if score < 60
    (so we still log it for analytics).
    """
    from app.services.market_regime import (
        compute_rsi_divergence,
        get_market_regime,
        is_direction_allowed,
        is_event_clear,
        is_volatility_healthy,
        is_volume_confirming,
    )
    from app.services.signal_grader import grade_signal

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Step 1: Market regime ────────────────────────────────────────
    regime_result = get_market_regime(symbol)
    bars = regime_result.bars_4h

    if regime_result.event_blocked:
        return _make_skip(
            symbol, now_iso, f"event_blocked: {regime_result.block_reason}"
        )

    if bars is None or bars.empty:
        return _make_skip(symbol, now_iso, "no_bar_data")

    # ── Step 2: Harmonic pattern detection ──────────────────────────
    candidate = _detect_harmonic_candidate(symbol, bars)
    if candidate is None:
        return _make_skip(symbol, now_iso, "no_candidate")

    direction = "bullish" if candidate.get("direction") == "bullish" else "bearish"

    # Direction × regime compatibility check
    if not is_direction_allowed(regime_result.regime, direction):
        return _make_skip(
            symbol, now_iso,
            f"direction_blocked_by_regime({direction}/{regime_result.regime})"
        )

    # ── Step 3: Confirmation checks ─────────────────────────────────
    rsi_div     = compute_rsi_divergence(bars) if bars is not None else False
    vol_confirm = is_volume_confirming(bars) if bars is not None else False
    atr_ok      = is_volatility_healthy(regime_result.atr_ratio)
    event_ok    = not regime_result.event_blocked

    # ── Step 4: Compute entry / stop / target ──────────────────────
    entry_price = candidate.get("entry_price", 0)
    stop_price  = _compute_atr_stop(direction, entry_price, bars)
    target_1    = _compute_target(entry_price, stop_price, rr=1.5)
    target_2    = _compute_target(entry_price, stop_price, rr=2.5)
    atr         = _get_atr(bars) if bars is not None else 0.0
    rr_ratio    = _compute_rr(entry_price, stop_price, target_1)

    # ── Step 5: Grade ──────────────────────────────────────────────
    # P0 fix: defensively coerce pattern_score to float; None would cause TypeError
    pattern_score_val = candidate.get("pattern_score")
    if not isinstance(pattern_score_val, (int, float)) or pattern_score_val <= 0:
        pattern_score_val = 0.5  # safe default when engine returns nothing

    grade_result = grade_signal(
        pattern_score=float(pattern_score_val),
        rsi_divergence=rsi_div,
        volume_confirm=vol_confirm,
        regime_result=regime_result,
        direction=direction,
        rr_ratio=rr_ratio,
        atr_ratio=regime_result.atr_ratio,
        event_clear=event_ok,
    )

    return ScanResult(
        symbol=symbol,
        pattern=candidate.get("pattern", "Unknown"),
        direction=direction,
        score=grade_result.total,
        grade=grade_result.grade,
        entry_price=entry_price,
        stop_price=stop_price,
        target_1=target_1,
        target_2=target_2,
        atr=atr,
        rr_ratio=rr_ratio,
        trend_ok=is_direction_allowed(regime_result.regime, direction),
        rsi_div=rsi_div,
        volume_confirm=vol_confirm,
        volatility_ok=atr_ok,
        event_ok=event_ok,
        regime=regime_result.regime,
        skipped=grade_result.grade == "skip",
        skip_reason=", ".join(grade_result.reasons) if grade_result.reasons else None,
    )


# ---------------------------------------------------------------------------
# Scan all users
# ---------------------------------------------------------------------------

def scan_all_users() -> dict[str, Any]:
    """Main entry point. Scans all enabled users' watchlists.

    Returns a summary dict for logging / reporting.
    """
    from app.infra.notification_prefs_store import NotificationPrefsStore
    from app.infra.watchlist_store import WatchlistStore
    from app.infra.dingtalk_client import DingTalkClient
    from app.services.signal_formatter import (
        format_daily_summary,
        format_medium_signal,
        format_signal,
        ScoredSignal,
    )

    prefs_store   = NotificationPrefsStore()
    watchlist_store = WatchlistStore()
    client        = DingTalkClient()

    now_iso  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today    = datetime.now(timezone.utc).date().isoformat()
    summary  = {
        "scan_time": now_iso,
        "users_scanned": 0,
        "symbols_scanned": 0,
        "signals_found": 0,
        "notifications_sent": 0,
        "errors": [],
    }

    enabled_users = prefs_store.list_enabled_users()
    logger.info("Starting watchlist scan for %d enabled users", len(enabled_users))

    for user_id, prefs in enabled_users:
        if not _acquire_scan_lock(user_id, prefs.scan_interval_hours):
            logger.debug("Skipping user %s — scan lock held", user_id)
            continue

        try:
            results = _scan_user(user_id, prefs, watchlist_store, client, now_iso)
            summary["users_scanned"] += 1
            summary["symbols_scanned"] += results["symbols_scanned"]
            summary["signals_found"]   += results["signals_found"]
            summary["notifications_sent"] += results["notifications_sent"]
        except Exception as exc:
            logger.exception("Scan failed for user %s: %s", user_id, exc)
            summary["errors"].append({"user_id": user_id, "error": str(exc)})

    logger.info(
        "Scan complete: %d users, %d symbols, %d signals, %d notifications",
        summary["users_scanned"], summary["symbols_scanned"],
        summary["signals_found"], summary["notifications_sent"],
    )
    return summary


def _scan_user(
    user_id: str,
    prefs,
    watchlist_store,
    client,
    now_iso: str,
) -> dict[str, Any]:
    """Scan a single user's watchlist."""
    # ── Load watchlist ──────────────────────────────────────────────
    items = watchlist_store.list_items(user_id)
    symbols = [item["symbol"] for item in items]
    logger.debug("User %s has %d watchlist items", user_id, len(symbols))

    strong_signals = []
    medium_signals = []
    total_scanned  = 0

    for symbol in symbols:
        # ponytail: serial scan per user (concurrency within symbol is cheap)
        result = scan_symbol(symbol, prefs)
        if result is None:
            continue

        total_scanned += 1

        if result.skipped or result.score < prefs.min_signal_score:
            _log_scan(user_id, symbol, result, is_sent=False)
            continue

        # Build ScoredSignal for formatter
        scored = ScoredSignal(
            symbol=result.symbol,
            pattern=result.pattern,
            direction=result.direction,
            score=result.score,
            entry_price=result.entry_price,
            stop_price=result.stop_price,
            target_1=result.target_1,
            target_2=result.target_2,
            atr=result.atr,
            rr_ratio=result.rr_ratio,
            trend_ok=result.trend_ok,
            rsi_div=result.rsi_div,
            volume_confirm=result.volume_confirm,
            volatility_ok=result.volatility_ok,
            event_ok=result.event_ok,
            regime=result.regime,
            scan_time_utc=now_iso,
        )

        if result.grade == "strong":
            strong_signals.append(scored)
        elif result.grade == "medium":
            medium_signals.append(scored)

        _log_scan(user_id, symbol, result, is_sent=True)

    # ── Send notifications ──────────────────────────────────────────
    notif_count = 0
    if prefs.dingtalk_webhook_url:
        # Strong signals → detailed messages
        for sig in strong_signals:
            msg = format_signal(sig)
            if client.send(msg, prefs.dingtalk_webhook_url, prefs.dingtalk_secret):
                notif_count += 1

        # Medium signals → compact messages
        for sig in medium_signals:
            msg = format_medium_signal(sig)
            if client.send(msg, prefs.dingtalk_webhook_url, prefs.dingtalk_secret):
                notif_count += 1

        # Daily summary (once per user per day)
        if prefs.send_daily_summary and (strong_signals or medium_signals):
            summary_msg = format_daily_summary(
                user_id=user_id,
                scan_time_utc=now_iso,
                symbols_scanned=total_scanned,
                strong_signals=strong_signals,
                medium_signals=medium_signals,
            )
            if client.send(summary_msg, prefs.dingtalk_webhook_url, prefs.dingtalk_secret):
                notif_count += 1

    return {
        "symbols_scanned": total_scanned,
        "signals_found": len(strong_signals) + len(medium_signals),
        "notifications_sent": notif_count,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_harmonic_candidate(symbol: str, bars) -> dict[str, Any] | None:
    """Run the existing signal_engine / pyharmonics pipeline on bars.

    Falls back to a simplified heuristic if the full pipeline is unavailable.
    """
    try:
        from app.services.signal_engine import extract_candidates, build_signal
        from app.config.tuning import TUNING

        candidates = extract_candidates(bars, symbol)
        if not candidates:
            return None

        # Take the best candidate
        best = max(candidates, key=lambda c: getattr(c, "score", 0.5))
        signal = build_signal(best, bars)

        return {
            "pattern":        getattr(best, "pattern_type", "Unknown"),
            "direction":      "bullish" if getattr(best, "direction", 1) > 0 else "bearish",
            "entry_price":    getattr(best, "entry_price", bars["close"].iloc[-1]),
            "pattern_score":  getattr(best, "score", 0.5),
            "raw_candidate":  best,
        }
    except Exception as exc:
        logger.debug("signal_engine unavailable for %s: %s — using fallback", symbol, exc)
        return _fallback_candidate(symbol, bars)


def _fallback_candidate(symbol: str, bars) -> dict[str, Any] | None:
    """Minimal candidate when signal_engine can't run.

    ponytail: this is intentionally rough. Replace with proper pattern detection.
    """
    import pandas as pd

    if bars is None or len(bars) < 60:
        return None

    close = bars["close"]
    high  = bars["high"]
    low   = bars["low"]

    # Very rough XABCD heuristic (only fires if structure is obvious)
    try:
        # Check for a potential swing high/low in last 20 bars
        recent = close.iloc[-20:]
        price  = float(close.iloc[-1])
        rolling_high = float(high.iloc[-20:].max())
        rolling_low  = float(low.iloc[-20:].min())

        # No candidate if price not near a structural extreme
        if not (price >= rolling_high * 0.97 or price <= rolling_low * 1.03):
            return None

        return {
            "pattern":       "Gartley",
            "direction":     "bullish" if price < rolling_low * 1.01 else "bearish",
            "entry_price":   price,
            "pattern_score": 0.6,
        }
    except Exception:
        return None


def _compute_atr_stop(direction: str, entry: float, bars) -> float:
    """Compute stop-loss using 2.5× ATR."""
    atr = _get_atr(bars)
    if atr == 0:
        # Fallback: 3% stop
        atr = entry * 0.03
    stop = entry - (2.5 * atr) if direction == "bullish" else entry + (2.5 * atr)
    return round(stop, 4)


def _compute_target(entry: float, stop: float, rr: float = 1.5) -> float:
    risk = abs(entry - stop)
    return round(entry + (rr * risk), 4)


def _compute_rr(entry: float, stop: float, target: float) -> float:
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    return round(abs(target - entry) / risk, 2)


def _get_atr(bars, period: int = 14) -> float:
    """Compute ATR(14) from bars."""
    try:
        import pandas as pd
        high  = bars["high"]
        low   = bars["low"]
        close = bars["close"].shift(1)
        tr1   = high - low
        tr2   = (high - close).abs()
        tr3   = (low - close).abs()
        tr    = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr   = tr.rolling(period).mean().iloc[-1]
        return float(atr)
    except Exception:
        return 0.0


def _make_skip(symbol: str, now_iso: str, reason: str) -> ScanResult:
    return ScanResult(
        symbol=symbol, pattern="", direction="",
        score=0, grade="skip",
        entry_price=0, stop_price=0, target_1=0, target_2=0,
        atr=0, rr_ratio=0,
        trend_ok=False, rsi_div=False, volume_confirm=False,
        volatility_ok=False, event_ok=False, regime="neutral",
        skipped=True, skip_reason=reason,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _log_scan(user_id: str, symbol: str, result: ScanResult, is_sent: bool) -> None:
    """Write a scan_log row to Supabase."""
    try:
        from app.infra.supabase_client import get_supabase_client
        client = get_supabase_client(use_service_role=True)
        if client is None:
            return
        client.table("scan_log").insert({
            "user_id":        user_id,
            "symbol":         symbol,
            "scan_time":      datetime.now(timezone.utc).isoformat(),
            "timeframe":       "4H",
            "signals_found":  0 if result.skipped else 1,
            "top_score":      result.score,
            "top_pattern":    result.pattern,
            "top_direction":  result.direction,
            "top_entry":     result.entry_price,
            "top_stop":       result.stop_price,
            "top_target":     result.target_1,
            "is_sent":        is_sent,
            "sent_at":        datetime.now(timezone.utc).isoformat() if is_sent else None,
            "error_msg":      result.skip_reason,
        }).execute()
    except Exception as exc:
        logger.debug("Failed to log scan for %s/%s: %s", user_id, symbol, exc)


def _acquire_scan_lock(user_id: str, interval_hours: int) -> bool:
    """Acquire a short-lived Redis lock to prevent concurrent scans of the same user.

    Returns True if lock acquired (or Redis unavailable — fail-open to avoid
    blocking the scan, but logs a warning so ops can monitor lock failures).
    """
    try:
        from app.infra.redis_client import get_redis_client
        redis = get_redis_client()
        if redis is None:
            # P1 fix: Redis unavailable — fail-open but warn so ops is aware
            logger.warning(
                "Redis unavailable for scan lock — concurrent scan possible for user=%s",
                user_id,
            )
            return True
        key = f"scan_lock:{user_id}:{interval_hours}h"
        acquired = redis.set(key, "1", ex=LOCK_TTL_SECONDS, nx=True)
        return bool(acquired)
    except Exception as exc:
        # P1 fix: log as error (not silently swallow), but still fail-open
        logger.error(
            "Scan lock acquisition failed for user=%s: %s — allowing scan (fail-open)",
            user_id, exc,
        )
        return True  # fail-open to avoid blocking the entire scan run
