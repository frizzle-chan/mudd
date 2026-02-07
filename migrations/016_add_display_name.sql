-- Add display_name column to users table for DB-driven autocomplete
SET lock_timeout = '1s';
SET statement_timeout = '5s';
ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT '';
