-- ============================================
-- 增量修复：更新 Storage Policy bucket 名称
-- 从 'charts' 改为 'pyharmonics-gpt-bucket'
-- 在 Supabase Dashboard → SQL Editor 中执行
-- ============================================

-- 删除旧的 policy（如果存在）
DROP POLICY IF EXISTS "Users can upload own charts" ON storage.objects;
DROP POLICY IF EXISTS "Users can read own charts" ON storage.objects;
DROP POLICY IF EXISTS "Users can delete own charts" ON storage.objects;

-- 允许认证用户上传自己的图表
CREATE POLICY "Users can upload own charts" ON storage.objects
    FOR INSERT TO authenticated WITH CHECK (
        bucket_id = 'pyharmonics-gpt-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户读取自己的图表
CREATE POLICY "Users can read own charts" ON storage.objects
    FOR SELECT TO authenticated USING (
        bucket_id = 'pyharmonics-gpt-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户删除自己的图表
CREATE POLICY "Users can delete own charts" ON storage.objects
    FOR DELETE TO authenticated USING (
        bucket_id = 'pyharmonics-gpt-bucket' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );
