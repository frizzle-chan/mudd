-- Migration: 030_dialog_sessions
-- Description: Dialog session tracking for NPC dialog trees (ADR 0009)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

CREATE TABLE user_dialog_sessions (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    dialog_id TEXT NOT NULL,
    thread_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
