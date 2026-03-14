-- Migration: 030_unique_thread_id
-- Description: Add UNIQUE constraint on discord_thread_id to prevent duplicate
-- thread assignments from concurrent inventory reconcilers.

SET lock_timeout = '2s';
SET statement_timeout = '30s';

-- Step 1: Clean up existing duplicate discord_thread_id values.
-- Keep the row with the latest created_at for each duplicate thread ID.
DELETE FROM entity_instances
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY discord_thread_id
                   ORDER BY created_at DESC
               ) AS rn
        FROM entity_instances
        WHERE discord_thread_id IS NOT NULL
    ) ranked
    WHERE rn > 1
);

-- Step 2: Drop old non-unique index.
-- CONCURRENTLY cannot be used inside a transaction block (migration runner uses transactions)
-- squawk-ignore require-concurrent-index-deletion
DROP INDEX IF EXISTS idx_entity_instances_thread;

-- Step 3: Create unique partial index (replaces old non-unique index).
-- CONCURRENTLY cannot be used inside a transaction block (migration runner uses transactions)
-- squawk-ignore require-concurrent-index-creation
CREATE UNIQUE INDEX idx_entity_instances_thread
    ON entity_instances(discord_thread_id)
    WHERE discord_thread_id IS NOT NULL;
