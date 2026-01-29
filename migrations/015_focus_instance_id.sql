-- Add instance_id to user_focus table (part 1: add column and constraints as NOT VALID)
-- This allows tracking the specific entity instance that is focused,
-- which is needed to create EntityContext for the focused container.

-- Set timeouts for safety
set lock_timeout = '2s';
set statement_timeout = '5s';

-- Add nullable column first (no lock issues)
ALTER TABLE user_focus
ADD COLUMN instance_id UUID;

-- Add foreign key constraint as NOT VALID (doesn't scan table)
ALTER TABLE user_focus
ADD CONSTRAINT user_focus_instance_id_fkey
FOREIGN KEY (instance_id) REFERENCES entity_instances(id) ON DELETE CASCADE
NOT VALID;

-- Backfill existing rows by looking up the instance_id from entity_instances
-- For room entities, there should be exactly one instance per entity_id + room
UPDATE user_focus uf
SET instance_id = (
    SELECT ei.id
    FROM entity_instances ei
    WHERE ei.entity_id = uf.entity_id
      AND ei.room = uf.room
    LIMIT 1
)
WHERE uf.instance_id IS NULL;

-- Use CHECK constraint instead of NOT NULL (doesn't block reads)
ALTER TABLE user_focus
ADD CONSTRAINT user_focus_instance_id_not_null
CHECK (instance_id IS NOT NULL) NOT VALID;
