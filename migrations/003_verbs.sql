-- Migration: 003_verbs
-- Description: Verb lookup table with pg_trgm fuzzy matching for typo tolerance

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- pg_trgm extension already enabled in migration 002

-- Action type determines which entity handler to invoke
CREATE TYPE verb_action AS ENUM ('on_look', 'on_touch', 'on_attack', 'on_use', 'on_take');

CREATE TABLE verbs (
    verb TEXT PRIMARY KEY,
    action verb_action NOT NULL
);

-- GIN index for trigram similarity search
CREATE INDEX verbs_verb_trgm_idx ON verbs USING GIN (verb gin_trgm_ops);
