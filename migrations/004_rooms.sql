-- Migration: 004_rooms
-- Description: Add zones table for multi-category support, update rooms with zone FK,
--              and rename users.current_location to current_room

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Zones table for grouping rooms by Discord category
-- Zone id matches Discord category name for auto-discovery
CREATE TABLE zones (
    id TEXT PRIMARY KEY,           -- Matches Discord category name (lowercase, hyphenated)
    name TEXT NOT NULL,            -- Display name for the zone
    description TEXT               -- MUD flavor text (e.g., "You enter the second floor...")
);

-- Rooms table for storing room definitions
-- Source of truth is data/worlds/<world>/*.rec files
CREATE TABLE rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    zone_id TEXT NOT NULL REFERENCES zones(id),
    has_voice BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_rooms_zone ON rooms(zone_id);

-- Rename current_location to current_room for consistency with rooms table
-- squawk-ignore renaming-column
ALTER TABLE users RENAME COLUMN current_location TO current_room;

-- Update index name to match the new column name
ALTER INDEX idx_users_current_location RENAME TO idx_users_current_room;

-- Add FK from users.current_room to rooms.id
-- ON DELETE RESTRICT prevents deleting rooms that have users in them
-- Use NOT VALID to avoid blocking reads/writes during constraint creation
ALTER TABLE users
ADD CONSTRAINT fk_users_current_room
FOREIGN KEY (current_room) REFERENCES rooms(id)
ON DELETE RESTRICT
NOT VALID;

-- Validate the constraint in a separate transaction (non-blocking)
-- squawk-ignore constraint-missing-not-valid
ALTER TABLE users VALIDATE CONSTRAINT fk_users_current_room;
