-- Migration: 007_rooms_is_default
-- Description: Add is_default column to rooms table

SET lock_timeout = '1s';
SET statement_timeout = '5s';

ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;

-- Partial unique index enforces only one default room
-- Note: Using blocking index creation (not CONCURRENTLY) because:
-- 1. CONCURRENTLY can't run inside a transaction (migrations use transactions)
-- 2. The rooms table is small (<100 rows), so brief write-blocking is acceptable
-- squawk-ignore require-concurrent-index-creation
CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_single_default
    ON rooms (is_default) WHERE is_default = TRUE;
