-- Migration: RSI backtest/scan/plan independent quota pool
--
-- Problem: RSI backtest/scan/plan are pure data-read operations (Binance/TradingView),
-- consuming zero AI tokens, but they share the same daily_quota pool with LLM-powered
-- /api/analyze. A user who runs 5 RSI backtests exhausts their quota and can't
-- use the AI analyzer.
--
-- Solution: Add a separate rsi_daily_quota pool (default 50/day) for RSI operations.
-- Both pools are independent — exhausting one doesn't affect the other.
--
-- Run in Supabase Dashboard → SQL Editor

-- ============================================================
-- Step 1: Add rsi_daily_quota column to profiles
-- ============================================================
ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS rsi_daily_quota INTEGER NOT NULL DEFAULT 50;

COMMENT ON COLUMN profiles.rsi_daily_quota IS 'Daily quota for RSI backtest/scan/plan operations (pure data-read, no AI tokens). Default 50.';

-- ============================================================
-- Step 2: Modify reserve_quota to support pool-aware checking
-- ============================================================
CREATE OR REPLACE FUNCTION reserve_quota(
    p_user_id UUID,
    p_analysis_id UUID,
    p_units INTEGER DEFAULT 1,
    p_pool TEXT DEFAULT 'default'
) RETURNS TABLE(reserved BOOLEAN, remaining INTEGER) AS $$
DECLARE
    v_quota INTEGER;
    v_used_today INTEGER;
BEGIN
    IF p_units <= 0 THEN
        RAISE EXCEPTION 'p_units must be positive, got %', p_units;
    END IF;

    IF p_pool NOT IN ('default', 'rsi_backtest') THEN
        RAISE EXCEPTION 'Unknown quota pool: %', p_pool;
    END IF;

    -- Acquire advisory lock keyed by user_id + pool to isolate pools
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || p_pool, 0));

    -- Select the appropriate quota column
    IF p_pool = 'rsi_backtest' THEN
        SELECT rsi_daily_quota INTO v_quota
        FROM profiles WHERE id = p_user_id AND status = 'active';
    ELSE
        SELECT daily_quota INTO v_quota
        FROM profiles WHERE id = p_user_id AND status = 'active';
    END IF;

    IF v_quota IS NULL THEN
        RETURN QUERY SELECT false, 0;
        RETURN;
    END IF;

    SELECT COALESCE(SUM(units_consumed), 0) INTO v_used_today
    FROM usage_ledger
    WHERE user_id = p_user_id
      AND usage_date = CURRENT_DATE
      AND status = 'consumed'
      AND pool = p_pool;

    IF v_used_today + p_units > v_quota THEN
        RETURN QUERY SELECT false, v_quota - v_used_today;
        RETURN;
    END IF;

    INSERT INTO usage_ledger (user_id, analysis_id, units_reserved, status, pool)
    VALUES (p_user_id, p_analysis_id, p_units, 'reserved', p_pool);

    RETURN QUERY SELECT true, v_quota - v_used_today - p_units;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- Step 3: Add pool column to usage_ledger (migrate existing rows to 'default')
-- ============================================================
ALTER TABLE usage_ledger
ADD COLUMN IF NOT EXISTS pool TEXT NOT NULL DEFAULT 'default';

COMMENT ON COLUMN usage_ledger.pool IS 'Quota pool: default (LLM analyze) or rsi_backtest (RSI scan/backtest/plan).';

-- Backfill existing rows
UPDATE usage_ledger SET pool = 'default' WHERE pool = 'default' AND pool IS NOT NULL;

-- ============================================================
-- Step 4: Add check constraint for pool values
-- ============================================================
ALTER TABLE usage_ledger
DROP CONSTRAINT IF EXISTS usage_ledger_pool_check;
ALTER TABLE usage_ledger
ADD CONSTRAINT usage_ledger_pool_check
CHECK (pool IN ('default', 'rsi_backtest'));
