-- ================================================================
-- Migration: 20260910_001_auth_complete.sql
-- Description: Complete auth system overhaul
--   - Invite codes with quota tiers
--   - Concurrent-safe reserve_quota
--   - User registration with invite consumption
-- ================================================================

BEGIN;

-- ================================================================
-- 1. Extend invites table with invite code support
-- ================================================================
ALTER TABLE invites
  ADD COLUMN IF NOT EXISTS code TEXT,
  ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS used_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS daily_quota_override INTEGER,
  ADD COLUMN IF NOT EXISTS rsi_daily_quota_override INTEGER,
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES profiles(id);

-- Unique index on code (allows multiple NULLs for email-only invites)
CREATE UNIQUE INDEX IF NOT EXISTS uq_invites_code
  ON invites (code) WHERE code IS NOT NULL;

-- Unique index on email for pending invites only (allows re-invite after revoke)
DROP INDEX IF EXISTS uq_invites_email_pending;
CREATE UNIQUE INDEX IF NOT EXISTS uq_invites_email_pending
  ON invites (LOWER(email)) WHERE status = 'pending';

-- Index for listing by status
CREATE INDEX IF NOT EXISTS idx_invites_status ON invites(status);
CREATE INDEX IF NOT EXISTS idx_invites_code ON invites(code) WHERE code IS NOT NULL;

-- ================================================================
-- 2. Extend profiles table
-- ================================================================
ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS invited_by UUID REFERENCES profiles(id),
  ADD COLUMN IF NOT EXISTS invite_code_used TEXT,
  ADD COLUMN IF NOT EXISTS rsi_daily_quota INTEGER NOT NULL DEFAULT 50;

-- ================================================================
-- 3. Create invite_usage table for tracking invite consumption
-- ================================================================
CREATE TABLE IF NOT EXISTS invite_usage (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  invite_id UUID NOT NULL REFERENCES invites(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  used_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE invite_usage ENABLE ROW LEVEL SECURITY;

-- Admins can view invite usage
DROP POLICY IF EXISTS "Admins can read invite_usage" ON invite_usage;
CREATE POLICY "Admins can read invite_usage" ON invite_usage
  FOR SELECT TO authenticated USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- Service role can do anything
DROP POLICY IF EXISTS "Service role can manage invite_usage" ON invite_usage;
CREATE POLICY "Service role can manage invite_usage" ON invite_usage
  FOR ALL TO service_role USING (true);

-- ================================================================
-- 4. Replace handle_new_user trigger with invite consumption
-- ================================================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
  v_invite invites%ROWTYPE;
  v_quota INTEGER := 5;
  v_rsi INTEGER := 50;
BEGIN
  -- Look for a matching pending invite (prefer by email match)
  -- Use FOR UPDATE SKIP LOCKED to prevent concurrent registrations
  -- from consuming the same single-use invite
  SELECT * INTO v_invite
  FROM invites
  WHERE LOWER(email) = LOWER(NEW.email)
    AND status = 'pending'
    AND expires_at > NOW()
  ORDER BY created_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1;

  IF FOUND THEN
    -- Check if invite still has uses available
    IF v_invite.used_count < v_invite.max_uses THEN
      -- Atomically consume the invite
      UPDATE invites SET
        used_count = used_count + 1,
        status = CASE
          WHEN used_count + 1 >= max_uses THEN 'accepted'
          ELSE status
        END,
        accepted_at = CASE
          WHEN used_count + 1 >= max_uses THEN NOW()
          ELSE accepted_at
        END
      WHERE id = v_invite.id;

      -- Record usage
      INSERT INTO invite_usage (invite_id, user_id)
      VALUES (v_invite.id, NEW.id);

      -- Apply quota overrides
      v_quota := COALESCE(v_invite.daily_quota_override, 5);
      v_rsi := COALESCE(v_invite.rsi_daily_quota_override, 50);
    END IF;
  END IF;

  -- Create profile with resolved quota
  INSERT INTO public.profiles (id, email, role, status, daily_quota, rsi_daily_quota)
  VALUES (NEW.id, NEW.email, 'user', 'active', v_quota, v_rsi)
  ON CONFLICT (id) DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 5. Fix reserve_quota - concurrent-safe with pool support
-- ================================================================
CREATE OR REPLACE FUNCTION reserve_quota(
    p_user_id UUID,
    p_analysis_id UUID,
    p_units INTEGER DEFAULT 1,
    p_pool TEXT DEFAULT 'default'
) RETURNS TABLE(reserved BOOLEAN, remaining INTEGER) AS $$
DECLARE
  v_daily_quota INTEGER;
  v_used_today INTEGER;
BEGIN
  IF p_units <= 0 THEN
    RAISE EXCEPTION 'p_units must be positive, got %', p_units;
  END IF;

  -- Acquire advisory lock keyed by user_id for the duration of the transaction
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  -- Get user's daily quota
  SELECT daily_quota INTO v_daily_quota
  FROM profiles WHERE id = p_user_id AND status = 'active';

  IF v_daily_quota IS NULL THEN
    RETURN QUERY SELECT false, 0;
    RETURN;
  END IF;

  -- FIX: Count BOTH reserved AND consumed units to prevent overshoot
  -- under bursty concurrency. Reserved rows are in-flight requests that
  -- haven't been consumed yet but still count against the quota.
  SELECT COALESCE(SUM(
    CASE
      WHEN status = 'reserved' THEN units_reserved
      WHEN status = 'consumed' THEN units_consumed
      ELSE 0
    END
  ), 0) INTO v_used_today
  FROM usage_ledger
  WHERE user_id = p_user_id
    AND usage_date = CURRENT_DATE
    AND pool = p_pool;

  -- Check if we have enough quota
  IF v_used_today + p_units > v_daily_quota THEN
    RETURN QUERY SELECT false, v_daily_quota - v_used_today;
    RETURN;
  END IF;

  -- Reserve the quota
  INSERT INTO usage_ledger (user_id, analysis_id, units_reserved, status, pool)
  VALUES (p_user_id, p_analysis_id, p_units, 'reserved', p_pool);

  RETURN QUERY SELECT true, v_daily_quota - v_used_today - p_units;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 6. Create RPC: create_invite_code (Admin only)
-- ================================================================
CREATE OR REPLACE FUNCTION create_invite_code(
  p_email TEXT,
  p_quota INTEGER DEFAULT 5,
  p_rsi_quota INTEGER DEFAULT 50,
  p_max_uses INTEGER DEFAULT 1,
  p_created_by UUID,
  p_days_valid INTEGER DEFAULT 7
) RETURNS TABLE(id UUID, code TEXT, quota INTEGER) AS $$
DECLARE
  v_code TEXT;
  v_id UUID;
BEGIN
  -- Generate unique 8-character code
  LOOP
    v_code := UPPER(SUBSTRING(MD5(RANDOM()::text || clock_timestamp()::text) FROM 1 FOR 8));
    EXIT WHEN NOT EXISTS (SELECT 1 FROM invites WHERE code = v_code);
  END LOOP;

  INSERT INTO invites (
    email, code, daily_quota_override, rsi_daily_quota_override,
    max_uses, used_count, created_by, expires_at, status
  ) VALUES (
    p_email, v_code, p_quota, p_rsi_quota,
    p_max_uses, 0, p_created_by,
    NOW() + (p_days_valid || ' days')::INTERVAL,
    'pending'
  )
  RETURNING id INTO v_id;

  RETURN QUERY SELECT v_id, v_code, p_quota;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 7. Create RPC: check_invite_code (with timing delay to prevent enum)
-- ================================================================
CREATE OR REPLACE FUNCTION check_invite_code(p_code TEXT)
RETURNS TABLE(valid BOOLEAN, quota INTEGER, rsi_quota INTEGER) AS $$
BEGIN
  -- Intentional delay to slow down enumeration attacks
  -- Random delay between 50-150ms
  PERFORM pg_sleep(FLOOR(RANDOM() * 100 + 50) / 1000.0);

  RETURN QUERY
  SELECT
    EXISTS (
      SELECT 1 FROM invites
      WHERE code = p_code
        AND status = 'pending'
        AND expires_at > NOW()
        AND used_count < max_uses
    ) as valid,
    COALESCE(daily_quota_override, 5) as quota,
    COALESCE(rsi_daily_quota_override, 50) as rsi_quota
  FROM invites WHERE code = p_code
  LIMIT 1;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 8. Create RPC: list_invites (for admin panel)
-- ================================================================
CREATE OR REPLACE FUNCTION list_invites()
RETURNS TABLE(
  id UUID,
  email TEXT,
  code TEXT,
  status TEXT,
  daily_quota_override INTEGER,
  used_count INTEGER,
  max_uses INTEGER,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ,
  created_by UUID
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    i.id, i.email, i.code, i.status,
    i.daily_quota_override, i.used_count, i.max_uses,
    i.expires_at, i.created_at, i.created_by
  FROM invites i
  ORDER BY i.created_at DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 9. Create RPC: revoke_invite
-- ================================================================
CREATE OR REPLACE FUNCTION revoke_invite(p_invite_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
  UPDATE invites SET status = 'revoked' WHERE id = p_invite_id;
  RETURN FOUND;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 10. Create RPC: list_users (paginated, for admin panel)
-- ================================================================
CREATE OR REPLACE FUNCTION list_users(
  p_limit INTEGER DEFAULT 20,
  p_offset INTEGER DEFAULT 0
) RETURNS TABLE(
  id UUID,
  email TEXT,
  role TEXT,
  status TEXT,
  daily_quota INTEGER,
  rsi_daily_quota INTEGER,
  invited_by UUID,
  created_at TIMESTAMPTZ,
  total_analyses BIGINT
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    p.id, p.email, p.role, p.status, p.daily_quota, p.rsi_daily_quota,
    p.invited_by, p.created_at,
    COUNT(a.id)::BIGINT as total_analyses
  FROM profiles p
  LEFT JOIN analyses a ON a.user_id = p.id
  GROUP BY p.id
  ORDER BY p.created_at DESC
  LIMIT p_limit
  OFFSET p_offset;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 11. Create RPC: update_user (for admin panel)
-- ================================================================
CREATE OR REPLACE FUNCTION update_user(
  p_user_id UUID,
  p_daily_quota INTEGER DEFAULT NULL,
  p_rsi_daily_quota INTEGER DEFAULT NULL,
  p_status TEXT DEFAULT NULL,
  p_role TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
BEGIN
  UPDATE profiles SET
    daily_quota = COALESCE(p_daily_quota, daily_quota),
    rsi_daily_quota = COALESCE(p_rsi_daily_quota, rsi_daily_quota),
    status = COALESCE(p_status, status),
    role = COALESCE(p_role, role)
  WHERE id = p_user_id;

  RETURN FOUND;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================================================
-- 12. Audit log entries for auth events
-- ================================================================
CREATE OR REPLACE FUNCTION log_auth_event(
  p_actor_id UUID,
  p_action TEXT,
  p_details JSONB DEFAULT '{}'
) RETURNS VOID AS $$
BEGIN
  INSERT INTO audit_events (actor_id, action, target_type, target_id, details)
  VALUES (
    p_actor_id,
    p_action,
    CASE p_action
      WHEN 'login_success' THEN 'user'
      WHEN 'login_failed' THEN 'user'
      WHEN 'user_registered' THEN 'user'
      WHEN 'invite_created' THEN 'invite'
      WHEN 'invite_revoked' THEN 'invite'
      WHEN 'invite_used' THEN 'invite'
      ELSE 'system'
    END,
    p_actor_id,
    p_details
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMIT;

-- ================================================================
-- Verification
-- ================================================================
DO $$
DECLARE
  v_count INTEGER;
BEGIN
  -- Check invites table has new columns
  SELECT COUNT(*) INTO v_count
  FROM information_schema.columns
  WHERE table_name = 'invites'
    AND column_name IN ('code', 'max_uses', 'used_count', 'daily_quota_override', 'rsi_daily_quota_override');

  IF v_count < 5 THEN
    RAISE WARNING 'invites table missing some new columns (found %/5)', v_count;
  ELSE
    RAISE NOTICE 'invites table OK: all 5 new columns present';
  END IF;

  -- Check profiles table has new columns
  SELECT COUNT(*) INTO v_count
  FROM information_schema.columns
  WHERE table_name = 'profiles'
    AND column_name IN ('invited_by', 'invite_code_used', 'rsi_daily_quota');

  IF v_count < 3 THEN
    RAISE WARNING 'profiles table missing some new columns (found %/3)', v_count;
  ELSE
    RAISE NOTICE 'profiles table OK: all 3 new columns present';
  END IF;

  -- Check invite_usage table exists
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'invite_usage'
  ) THEN
    RAISE WARNING 'invite_usage table not found';
  ELSE
    RAISE NOTICE 'invite_usage table OK';
  END IF;
END $$;
