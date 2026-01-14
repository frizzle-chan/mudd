-- Migration: 005_entity_instances_constraints
-- Description: Add constraints for entity instance sync:
--   1. UNIQUE constraint on (entity_id, room) for idempotent sync
--   2. ON DELETE CASCADE on entity_id FK for automatic cleanup

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Add UNIQUE constraint on (entity_id, room) for entities in rooms
-- This enables idempotent sync: INSERT ON CONFLICT DO NOTHING
-- Partial index: only applies where room IS NOT NULL (excludes inventory items)
-- Inventory items (owner_id set, room NULL) can have multiple instances of same entity
-- NOTE: Cannot use CONCURRENTLY inside a transaction (our migration runner wraps each
-- migration in a transaction). This is acceptable because entity_instances is typically
-- empty at migration time - instances are created during bot startup by entity_loader.
-- squawk-ignore prefer-robust-stmts,require-concurrent-index-creation
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_instances_entity_room
ON entity_instances(entity_id, room)
WHERE room IS NOT NULL;

-- Drop existing FK constraint on entity_id (IF EXISTS for safety)
-- squawk-ignore prefer-robust-stmts
ALTER TABLE entity_instances DROP CONSTRAINT IF EXISTS entity_instances_entity_id_fkey;

-- Re-add FK with ON DELETE CASCADE
-- When an entity definition is deleted, all its instances are also deleted
-- This includes both room instances and inventory items
-- Using NOT VALID to avoid blocking reads/writes during constraint creation
-- NOTE: We intentionally skip VALIDATE CONSTRAINT here.
-- The entity_instances table may be empty at migration time; instances are
-- populated during bot startup by the entity_loader service. NOT VALID
-- ensures new rows are validated without blocking.
ALTER TABLE entity_instances
ADD CONSTRAINT entity_instances_entity_id_fkey
FOREIGN KEY (entity_id) REFERENCES entities(id)
ON DELETE CASCADE
NOT VALID;
