-- Migration: 011_inventory_description_message
-- Description: Track description message ID for inventory thread sync

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Track the description message ID in inventory threads
-- This allows the sync system to edit the description when entity definitions change
ALTER TABLE entity_instances ADD COLUMN discord_description_msg_id BIGINT;
