-- Migration: 028_trading_sessions
-- Description: Trading session tracking for active shop interactions (ADR 0008)

SET lock_timeout = '1s';
SET statement_timeout = '5s';

CREATE TABLE user_trading_sessions (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    shop_id TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    thread_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
