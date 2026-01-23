-- Migration: 010_world_instance_marker
-- Description: Add is_world_instance column to distinguish rec-file instances
-- from player-created ones (drops, spawning pools, grants).
--
-- World instances use a partial unique index for UPSERT during sync.
-- Player instances (is_world_instance = FALSE) can have duplicates.

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Add marker column (FALSE for all existing instances initially)
ALTER TABLE entity_instances
ADD COLUMN IF NOT EXISTS is_world_instance BOOLEAN NOT NULL DEFAULT FALSE;

-- Drop the old constraint that blocked duplicates
-- Safety: IF EXISTS makes this idempotent; small table has brief lock duration
-- squawk-ignore prefer-robust-stmts,require-concurrent-index-deletion
DROP INDEX IF EXISTS idx_entity_instances_entity_room;

-- Create new partial unique index only for world instances
-- Safety: IF NOT EXISTS makes this idempotent; small table has brief lock duration
-- squawk-ignore prefer-robust-stmts,require-concurrent-index-creation
CREATE UNIQUE INDEX IF NOT EXISTS idx_world_instances_entity_room
ON entity_instances(entity_id, room)
WHERE is_world_instance = TRUE;

-- Mark existing room instances as world instances (they came from rec file sync)
-- Excludes: inventory (owner_id), spawning pool items, player drops
UPDATE entity_instances
SET is_world_instance = TRUE
WHERE room IS NOT NULL
  AND owner_id IS NULL
  AND spawning_pool_id IS NULL
  AND player_dropped = FALSE;
