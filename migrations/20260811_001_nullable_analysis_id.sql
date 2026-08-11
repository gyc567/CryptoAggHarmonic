-- Migration: nullable analysis_id in usage_ledger and reserve_quota
-- Problem: RSI-trend and vibe routes call reserve_quota with a random UUID
-- as analysis_id, but no corresponding record exists in the analyses table.
-- This causes a FK constraint violation (HTTP 409 / PostgreSQL 23503) and
-- users get 429 "quota exceeded" even when they have quota remaining.
--
-- Root cause from gunicorn log:
--   APIError: {'code': '23503', 'message': 'insert or update on table "usage_ledger"
--   violates foreign key constraint "usage_ledger_analysis_id_fkey"
--   Key (analysis_id)=(XXX) is not present in table "analyses".'}
--
-- Solution:
-- 1. Drop the FK constraint on usage_ledger.analysis_id — the column is
--    informational only (links a ledger entry to an analyses record when
--    one exists). The quota logic itself only needs user_id + date.
-- 2. reserve_quota already accepts NULL for p_analysis_id (UUID is nullable).
--    No function signature change needed.
--
-- Run in Supabase Dashboard → SQL Editor

-- 1. Drop the FK constraint (constraint name from initial schema)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'usage_ledger_analysis_id_fkey'
          AND table_name = 'usage_ledger'
    ) THEN
        ALTER TABLE usage_ledger DROP CONSTRAINT usage_ledger_analysis_id_fkey;
    END IF;
END $$;
