-- Add poll message type and poll tracking for races

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Poll message type for Discord polls posted to race threads
-- squawk-ignore require-enum-value-ordering
ALTER TYPE race_message_type ADD VALUE IF NOT EXISTS 'poll';

-- Track the Discord message ID of the poll so it can be ended when the race finishes
-- squawk-ignore adding-not-nullable-field
ALTER TABLE races ADD COLUMN poll_message_id BIGINT;
