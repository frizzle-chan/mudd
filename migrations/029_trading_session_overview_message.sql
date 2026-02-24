-- Migration: 029_trading_session_overview_message
-- Description: Add overview_message_id to track the shop overview message in trading threads

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Delete existing sessions since they lack the overview message ID.
-- Active traders will simply re-interact with the merchant.
DELETE FROM user_trading_sessions;

ALTER TABLE user_trading_sessions
    ADD COLUMN overview_message_id BIGINT NOT NULL DEFAULT 0;

ALTER TABLE user_trading_sessions
    ALTER COLUMN overview_message_id DROP DEFAULT;
