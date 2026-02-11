-- Scheduled races: new statuses, message type sentinel, and event tracking

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Race can be in 'announcing' state during pre-race window
ALTER TYPE race_status ADD VALUE IF NOT EXISTS 'announcing';

-- Sentinel message type that triggers announcing -> running transition
ALTER TYPE race_message_type ADD VALUE IF NOT EXISTS 'race_start';

-- Link races to Discord scheduled events for lifecycle management
-- squawk-ignore adding-not-nullable-field
ALTER TABLE races ADD COLUMN scheduled_event_id BIGINT;
