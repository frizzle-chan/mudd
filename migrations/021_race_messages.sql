-- Race message queue for Discord delivery
-- Pre-computed messages with future timestamps, deleted after posting

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Discord state columns on races
-- squawk-ignore adding-not-nullable-field
ALTER TABLE races ADD COLUMN channel_id BIGINT;
-- squawk-ignore adding-not-nullable-field
ALTER TABLE races ADD COLUMN thread_id BIGINT;

-- Message type: channel announcement vs thread message
CREATE TYPE race_message_type AS ENUM ('announcement', 'thread');

-- Pre-computed messages with future timestamps
-- Rows are deleted after posting to avoid BYTEA accumulation
CREATE TABLE IF NOT EXISTS race_messages (
    -- squawk-ignore prefer-bigint-over-int
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- squawk-ignore prefer-bigint-over-int
    race_id INT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    -- squawk-ignore prefer-bigint-over-int
    sequence INT NOT NULL,
    message_type race_message_type NOT NULL,
    content TEXT,
    image_data BYTEA,
    image_name TEXT,
    post_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_race_messages_post_at ON race_messages(post_at);
CREATE INDEX idx_race_messages_race ON race_messages(race_id);
