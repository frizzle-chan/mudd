-- Migration: 019_skills
-- Description: Add user skills tables for the skills progression system (ADR 0006)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Skills tracking: one row per user per skill
CREATE TABLE IF NOT EXISTS user_skills (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    xp BIGINT NOT NULL DEFAULT 0,
    -- squawk-ignore prefer-bigint-over-int
    level INT NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, skill),
    CONSTRAINT user_skills_xp_range CHECK (xp >= 0 AND xp <= 200000000),
    CONSTRAINT user_skills_level_range CHECK (level >= 1 AND level <= 99)
);

-- Fast lookup of all skills for a user
CREATE INDEX IF NOT EXISTS idx_user_skills_user_id ON user_skills(user_id);

-- Per-user Discord skills channel tracking
CREATE TABLE IF NOT EXISTS user_skills_channels (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
