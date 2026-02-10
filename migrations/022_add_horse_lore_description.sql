-- Add lore and description fields to horses table
-- Supports narrative content for each horse

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Add description column for short horse description
ALTER TABLE horses ADD COLUMN IF NOT EXISTS description TEXT;

-- Add lore column for background/story paragraphs
ALTER TABLE horses ADD COLUMN IF NOT EXISTS lore TEXT;
