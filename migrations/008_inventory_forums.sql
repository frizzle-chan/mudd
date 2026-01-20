-- Migration: 008_inventory_forums
-- Description: Add tables for per-user inventory forum channels

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Track per-user inventory forum channels
-- Each user gets one forum channel in the Inventory category
CREATE TABLE user_inventory_forums (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    forum_id BIGINT NOT NULL,       -- Discord forum channel snowflake
    category_id BIGINT NOT NULL,    -- Discord category snowflake (for validation)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add Discord thread ID tracking to entity instances
-- When an item is in a user's inventory, this stores the thread ID
-- NULL when item is in a room (not in inventory)
ALTER TABLE entity_instances ADD COLUMN discord_thread_id BIGINT;

-- Index for quick thread -> instance lookups (used when interacting in threads)
-- CONCURRENTLY cannot be used inside a transaction block (migration runner uses transactions)
-- squawk-ignore require-concurrent-index-creation
CREATE INDEX idx_entity_instances_thread ON entity_instances(discord_thread_id)
WHERE discord_thread_id IS NOT NULL;
