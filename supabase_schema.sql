-- Supabase Schema Setup for Pyharmonics SaaS
-- Run this in Supabase Dashboard → SQL Editor

-- ============================================
-- 1. Enable UUID extension
-- ============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 2. profiles table (用户档案)
-- ============================================
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    daily_quota INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS Policies
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own profile" ON profiles;
CREATE POLICY "Users can read own profile" ON profiles
    FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update own profile" ON profiles;
CREATE POLICY "Users can update own profile" ON profiles
    FOR UPDATE USING (auth.uid() = id);

-- ============================================
-- 3. invites table (邀请管理)
-- ============================================
CREATE TABLE IF NOT EXISTS invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    invited_by UUID REFERENCES profiles(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE invites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "No direct access" ON invites;
CREATE POLICY "No direct access" ON invites
    FOR ALL USING (false);

-- ============================================
-- 4. analyses table (分析记录)
-- ============================================
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    input_mode TEXT NOT NULL DEFAULT 'form' CHECK (input_mode IN ('form', 'natural_language')),
    market TEXT NOT NULL CHECK (market IN ('binance', 'yahoo')),
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL CHECK (interval IN ('15m', '1h', '4h', '1d', '1w')),
    analysis_type TEXT NOT NULL DEFAULT 'forming' CHECK (analysis_type IN ('forming', 'formed', 'divergence')),
    parameters JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN (
        'created', 'validating', 'fetching_market_data', 'detecting_patterns',
        'interpreting', 'rendering_chart', 'completed', 'no_result',
        'failed_upstream', 'failed_model', 'failed_chart', 'rejected', 'stale'
    )),
    technical_result JSONB,
    interpretation JSONB,
    chart_path TEXT,
    model_provider TEXT,
    model_name TEXT,
    prompt_version TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_micros INTEGER,
    error_code TEXT,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    idempotency_key TEXT,
    UNIQUE(user_id, idempotency_key)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_analyses_user_created ON analyses(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
CREATE INDEX IF NOT EXISTS idx_analyses_idempotency ON analyses(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own analyses" ON analyses;
CREATE POLICY "Users can read own analyses" ON analyses
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own analyses" ON analyses;
CREATE POLICY "Users can insert own analyses" ON analyses
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own analyses" ON analyses;
CREATE POLICY "Users can update own analyses" ON analyses
    FOR UPDATE USING (auth.uid() = user_id);

-- ============================================
-- 5. usage_ledger table (额度账本)
-- ============================================
CREATE TABLE IF NOT EXISTS usage_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    analysis_id UUID REFERENCES analyses(id) ON DELETE SET NULL,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    units_reserved INTEGER NOT NULL DEFAULT 0,
    units_consumed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'consumed', 'released')),
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_micros INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_ledger_user_date ON usage_ledger(user_id, usage_date);

ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own ledger" ON usage_ledger;
CREATE POLICY "Users can read own ledger" ON usage_ledger
    FOR SELECT USING (auth.uid() = user_id);

-- ============================================
-- 6. audit_events table (审计日志)
-- ============================================
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id UUID REFERENCES profiles(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "No direct access" ON audit_events;
CREATE POLICY "No direct access" ON audit_events
    FOR ALL USING (false);

-- ============================================
-- 7. RPC Functions
-- ============================================

-- 7.1 原子额度预占
-- Uses a per-user advisory transaction lock to prevent concurrent requests from
-- double-counting consumed units and exceeding the daily quota.
CREATE OR REPLACE FUNCTION reserve_quota(
    p_user_id UUID,
    p_analysis_id UUID,
    p_units INTEGER DEFAULT 1
) RETURNS TABLE(reserved BOOLEAN, remaining INTEGER) AS $$
DECLARE
    v_daily_quota INTEGER;
    v_used_today INTEGER;
BEGIN
    IF p_units <= 0 THEN
        RAISE EXCEPTION 'p_units must be positive, got %', p_units;
    END IF;

    -- Acquire advisory lock keyed by user_id for the duration of the transaction.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

    SELECT daily_quota INTO v_daily_quota
    FROM profiles WHERE id = p_user_id AND status = 'active';

    IF v_daily_quota IS NULL THEN
        RETURN QUERY SELECT false, 0;
        RETURN;
    END IF;

    SELECT COALESCE(SUM(units_consumed), 0) INTO v_used_today
    FROM usage_ledger
    WHERE user_id = p_user_id
      AND usage_date = CURRENT_DATE
      AND status = 'consumed';

    IF v_used_today + p_units > v_daily_quota THEN
        RETURN QUERY SELECT false, v_daily_quota - v_used_today;
        RETURN;
    END IF;

    INSERT INTO usage_ledger (user_id, analysis_id, units_reserved, status)
    VALUES (p_user_id, p_analysis_id, p_units, 'reserved');

    RETURN QUERY SELECT true, v_daily_quota - v_used_today - p_units;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7.2 额度结算
CREATE OR REPLACE FUNCTION consume_quota(
    p_ledger_id UUID,
    p_input_tokens INTEGER DEFAULT NULL,
    p_output_tokens INTEGER DEFAULT NULL,
    p_cost_micros INTEGER DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE usage_ledger
    SET status = 'consumed',
        units_consumed = units_reserved,
        input_tokens = COALESCE(p_input_tokens, input_tokens),
        output_tokens = COALESCE(p_output_tokens, output_tokens),
        estimated_cost_micros = COALESCE(p_cost_micros, estimated_cost_micros),
        updated_at = NOW()
    WHERE id = p_ledger_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7.3 额度释放
CREATE OR REPLACE FUNCTION release_quota(
    p_ledger_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE usage_ledger
    SET status = 'released',
        units_consumed = 0,
        updated_at = NOW()
    WHERE id = p_ledger_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7.4 用户注册时自动创建 profile
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, role, status, daily_quota)
    VALUES (
        NEW.id,
        NEW.email,
        'user',
        'active',
        5
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 绑定触发器（如果未绑定）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'on_auth_user_created'
    ) THEN
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_new_user();
    END IF;
END $$;

-- 7.5 检查邀请邮箱
CREATE OR REPLACE FUNCTION is_invited_email(p_email TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM invites
        WHERE email = LOWER(p_email)
          AND status = 'pending'
          AND expires_at > NOW()
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 8. Storage Bucket (cryptoagg-bucket)
-- ============================================
-- 在 Supabase Dashboard → Storage 中手动创建 bucket: cryptoagg-bucket
-- 设置为 Private
-- 然后执行以下 SQL 设置策略：

-- 允许认证用户上传自己的图表
DROP POLICY IF EXISTS "Users can upload own charts" ON storage.objects;
CREATE POLICY "Users can upload own charts" ON storage.objects
    FOR INSERT TO authenticated WITH CHECK (
        bucket_id = 'cryptoagg-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户读取自己的图表
DROP POLICY IF EXISTS "Users can read own charts" ON storage.objects;
CREATE POLICY "Users can read own charts" ON storage.objects
    FOR SELECT TO authenticated USING (
        bucket_id = 'cryptoagg-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户删除自己的图表
DROP POLICY IF EXISTS "Users can delete own charts" ON storage.objects;
CREATE POLICY "Users can delete own charts" ON storage.objects
    FOR DELETE TO authenticated USING (
        bucket_id = 'cryptoagg-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- ============================================
-- 9. 验证
-- ============================================
-- 执行以下查询验证表是否创建成功
SELECT 
    table_name,
    EXISTS (
        SELECT 1 FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename = table_name
    ) as exists
FROM (
    VALUES 
        ('profiles'),
        ('invites'),
        ('analyses'),
        ('usage_ledger'),
        ('audit_events')
) AS tables(table_name);
