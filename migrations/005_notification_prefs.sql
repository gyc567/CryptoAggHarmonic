-- Migration 005: Daily Watchlist Scan + DingTalk Notification System
-- Adds tables for user notification preferences, scan logging, and signal outcome tracking.
-- Run this migration in Supabase SQL Editor or via supabase CLI:
--   supabase db push or   psql $DATABASE_URL -f migrations/005_notification_prefs.sql

BEGIN;

-- ============================================================================
-- 1. User notification preferences
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_notification_prefs (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               TEXT NOT NULL UNIQUE,
    -- DingTalk configuration
    dingtalk_webhook_url  TEXT,
    dingtalk_secret       TEXT,
    -- Scan preferences
    scan_interval_hours   INT  NOT NULL DEFAULT 4,
    scan_enabled          BOOLEAN NOT NULL DEFAULT true,
    min_signal_score      INT  NOT NULL DEFAULT 60,
    -- Notification preferences
    notify_on_pattern     BOOLEAN NOT NULL DEFAULT true,
    notify_bearish_only   BOOLEAN NOT NULL DEFAULT false,
    send_daily_summary    BOOLEAN NOT NULL DEFAULT true,
    -- Risk preferences
    max_risk_per_trade    NUMERIC(5,4) NOT NULL DEFAULT 0.02,  -- 2% default
    -- Meta
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_notification_prefs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users manage own prefs"
    ON user_notification_prefs
    FOR ALL
    USING (auth.uid()::text = user_id);

-- auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_notification_prefs_updated_at
    BEFORE UPDATE ON user_notification_prefs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- 2. Scan execution log
-- ============================================================================
CREATE TABLE IF NOT EXISTS scan_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    scan_time      TIMESTAMPTZ NOT NULL,
    timeframe      TEXT NOT NULL DEFAULT '4H',
    signals_found  INT  NOT NULL DEFAULT 0,
    top_score      INT  NOT NULL DEFAULT 0,
    top_pattern    TEXT,
    top_direction  TEXT,
    top_entry      NUMERIC,
    top_stop       NUMERIC,
    top_target     NUMERIC,
    is_sent        BOOLEAN NOT NULL DEFAULT false,
    sent_at        TIMESTAMPTZ,
    error_msg      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scan_log_user_time  ON scan_log(user_id, scan_time DESC);
CREATE INDEX idx_scan_log_symbol_time ON scan_log(symbol, scan_time DESC);

-- ============================================================================
-- 3. Individual signal records (for outcome tracking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS signal_outcome (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_log_id    UUID REFERENCES scan_log(id) ON DELETE SET NULL,
    user_id        TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    pattern        TEXT NOT NULL,
    direction      TEXT NOT NULL,
    score          INT  NOT NULL,
    timeframe      TEXT NOT NULL DEFAULT '4H',
    entry_price    NUMERIC NOT NULL,
    stop_price     NUMERIC NOT NULL,
    target_price   NUMERIC NOT NULL,
    rr_ratio       NUMERIC,
    actual_exit    NUMERIC,
    outcome        TEXT CHECK (outcome IN ('win', 'loss', 'breakeven', 'pending', 'cancelled')),
    closed_at      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signal_outcome_user     ON signal_outcome(user_id, created_at DESC);
CREATE INDEX idx_signal_outcome_symbol    ON signal_outcome(symbol, created_at DESC);
CREATE INDEX idx_signal_outcome_pending  ON signal_outcome(outcome) WHERE outcome = 'pending';

-- ============================================================================
-- 4. Pattern historical statistics (used for scoring)
-- ============================================================================
CREATE TABLE IF NOT EXISTS harmonic_pattern_stats (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol        TEXT NOT NULL,
    pattern       TEXT NOT NULL,
    direction     TEXT NOT NULL,
    timeframe     TEXT NOT NULL DEFAULT '4H',
    total_count   INT  NOT NULL DEFAULT 0,
    win_count     INT  NOT NULL DEFAULT 0,
    avg_rr        NUMERIC NOT NULL DEFAULT 0,
    avg_score     NUMERIC NOT NULL DEFAULT 0,
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, pattern, direction, timeframe)
);

CREATE INDEX idx_pattern_stats_lookup
    ON harmonic_pattern_stats(symbol, pattern, direction, timeframe);

-- ============================================================================
-- 5. Daily scan summary
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_scan_summary (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           TEXT NOT NULL,
    scan_date         DATE NOT NULL,
    symbols_scanned   INT  NOT NULL DEFAULT 0,
    strong_signals    INT  NOT NULL DEFAULT 0,
    medium_signals    INT  NOT NULL DEFAULT 0,
    total_signals     INT  NOT NULL DEFAULT 0,
    outcomes_tracked  INT  NOT NULL DEFAULT 0,
    win_rate_7d       NUMERIC,
    avg_rr_7d        NUMERIC,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, scan_date)
);

CREATE INDEX idx_daily_summary_user ON daily_scan_summary(user_id, scan_date DESC);

-- ============================================================================
-- 6. Economic calendar (for event filtering)
-- ============================================================================
CREATE TABLE IF NOT EXISTS economic_calendar (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_date  DATE NOT NULL,
    event_time  TIME,
    currency    TEXT NOT NULL,
    event_name  TEXT NOT NULL,
    impact      TEXT CHECK (impact IN ('high', 'medium', 'low')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_econ_calendar_date ON economic_calendar(event_date);

COMMIT;
