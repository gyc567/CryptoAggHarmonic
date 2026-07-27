# Database Migrations

This directory contains incremental Supabase/PostgreSQL migrations. Apply them
in numeric order via the Supabase Dashboard SQL Editor or `psql`.

## Execution order

| Order | File | Purpose |
|-------|------|---------|
| 1 | `20260715_001_initial_schema.sql` | Core tables, RLS policies, RPC functions (`reserve_quota`, `consume_quota`, etc.) |
| 2 | `20260721_002_rpc_storage_trigger_fixes.sql` | RPC fixes, storage bucket policies, invite trigger |
| 3 | `20260722_003_storage_policy_fixes.sql` | Additional storage policy adjustments |
| 4 | `20260723_004_vibe_tables.sql` | Vibe sessions, messages, runs, journal, worker queue tables |

## Notes

- The root-level `supabase_schema*.sql` files are kept for backward
  compatibility with existing documentation; new changes should be added here
  as incremental migrations.
- `reserve_quota` uses `pg_advisory_xact_lock` to prevent concurrent
  over-reservation of daily quota.
