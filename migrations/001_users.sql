-- Migration: 001_users
-- Description: Initial schema for user location tracking

SET lock_timeout = '1s';
SET statement_timeout = '5s';

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,  -- Discord user snowflake ID
    current_location TEXT,  -- Logical room name (e.g., "office", "tavern")
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_current_location ON users(current_location);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
