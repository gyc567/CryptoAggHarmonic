-- Migration: cryptoagg bucket rename
-- Date: 2026-08-10
-- Description: Rename Supabase storage bucket from pyharmonics-gpt-bucket to cryptoagg-bucket
-- Previous bucket and objects: RETAINED (not migrated per plan decision)
-- New bucket: cryptoagg-bucket (must be created in Supabase Dashboard before this migration runs)
--
-- SQL diff (old → new):
--
-- supabase_schema.sql:
--   bucket_id = 'pyharmonics-gpt-bucket'  →  bucket_id = 'cryptoagg-bucket'
--
-- supabase_storage_policy_fix.sql:
--   bucket_id = 'pyharmonics-gpt-bucket'  →  bucket_id = 'cryptoagg-bucket'
--   comment: '-- 从 \'charts\' 改为 \'pyharmonics-gpt-bucket\''  →  '-- 从 \'charts\' 改为 \'cryptoagg-bucket\''
--
-- app/infra/supabase_client.py:
--   client.storage.from_("pyharmonics-gpt-bucket")  →  client.storage.from_("cryptoagg-bucket")
--
-- Note: No data migration. Old bucket objects remain accessible via old bucket reference
-- until code is fully deployed. New charts write to cryptoagg-bucket.

-- 1. Verify new bucket exists (will error if not)
DO $$
BEGIN
    ASSERT EXISTS (
        SELECT 1 FROM storage.buckets WHERE id = 'cryptoagg-bucket'
    ), 'Bucket cryptoagg-bucket must be created first in Supabase Dashboard';
END $$;

-- 2. Update bucket_id references in storage policies
-- (These are idempotent — safe to re-run)

-- Note: The actual policy updates are already applied via Supabase Dashboard
-- or supabase_storage_policy_fix.sql run manually.
-- This migration documents the change only.
