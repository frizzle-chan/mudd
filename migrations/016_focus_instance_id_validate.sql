-- Add instance_id to user_focus table (part 2: validate constraints)
-- Run in separate transaction to avoid blocking reads during validation

-- Set timeouts for safety
set lock_timeout = '2s';
set statement_timeout = '30s';

-- Validate foreign key constraint (allows concurrent reads)
ALTER TABLE user_focus
VALIDATE CONSTRAINT user_focus_instance_id_fkey;

-- Validate NOT NULL check constraint
ALTER TABLE user_focus
VALIDATE CONSTRAINT user_focus_instance_id_not_null;
