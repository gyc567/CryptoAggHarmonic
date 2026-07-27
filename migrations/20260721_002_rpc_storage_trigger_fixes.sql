-- ============================================
-- 增量修复：RPC Functions + Storage + Trigger
-- 在 Supabase Dashboard → SQL Editor 中执行
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
-- Storage Bucket (charts)
-- ============================================
-- 注意：bucket 需要在 Dashboard → Storage 中手动创建，命名为 "charts"，设置为 Private
-- 创建后执行以下 SQL 设置策略：

-- 允许认证用户上传自己的图表
DROP POLICY IF EXISTS "Users can upload own charts" ON storage.objects;
CREATE POLICY "Users can upload own charts" ON storage.objects
    FOR INSERT TO authenticated WITH CHECK (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户读取自己的图表
DROP POLICY IF EXISTS "Users can read own charts" ON storage.objects;
CREATE POLICY "Users can read own charts" ON storage.objects
    FOR SELECT TO authenticated USING (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户删除自己的图表
DROP POLICY IF EXISTS "Users can delete own charts" ON storage.objects;
CREATE POLICY "Users can delete own charts" ON storage.objects
    FOR DELETE TO authenticated USING (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- ============================================
-- 验证
-- ============================================
SELECT 
    'functions' as category,
    proname as name,
    EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = proname
    ) as exists
FROM (
    VALUES 
        ('reserve_quota'),
        ('consume_quota'),
        ('release_quota'),
        ('is_invited_email'),
        ('handle_new_user')
) AS funcs(proname)
UNION ALL
SELECT 
    'triggers' as category,
    tgname as name,
    EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = tgname
    ) as exists
FROM (
    VALUES ('on_auth_user_created')
) AS triggers(tgname);
