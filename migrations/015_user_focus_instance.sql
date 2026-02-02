-- Migration: 015_user_focus_instance
-- Description: Replace room+entity_id with entity_instance_id in user_focus
-- Focus is short-lived (5 min timeout), so clean swap is safe.

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Drop old table and create new schema
-- squawk-ignore ban-drop-table
DROP TABLE IF EXISTS user_focus;

CREATE TABLE user_focus (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    entity_instance_id UUID NOT NULL REFERENCES entity_instances(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Recreate index for timeout queries
CREATE INDEX idx_user_focus_updated ON user_focus(updated_at);
