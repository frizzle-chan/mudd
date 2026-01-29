-- Simplify user_focus table to instance_id only
-- room and entity_id are redundant - they can be derived from entity_instances
--
-- Before: user_focus(user_id, room, entity_id, instance_id, updated_at)
-- After: user_focus(user_id, instance_id, updated_at)

-- Set timeouts for safety
set lock_timeout = '2s';
set statement_timeout = '5s';

-- Drop CHECK constraint (we'll use actual NOT NULL)
ALTER TABLE user_focus DROP CONSTRAINT user_focus_instance_id_not_null;

-- Add real NOT NULL constraint
ALTER TABLE user_focus ALTER COLUMN instance_id SET NOT NULL;

-- Drop foreign key constraints first
ALTER TABLE user_focus DROP CONSTRAINT user_focus_room_fkey;
ALTER TABLE user_focus DROP CONSTRAINT user_focus_entity_id_fkey;

-- Drop columns
ALTER TABLE user_focus DROP COLUMN room;
ALTER TABLE user_focus DROP COLUMN entity_id;
