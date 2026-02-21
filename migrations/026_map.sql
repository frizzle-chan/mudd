set lock_timeout = '1s';
set statement_timeout = '5s';

CREATE TABLE room_visits (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    visited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, room_id)
);

CREATE INDEX idx_room_visits_user_id ON room_visits (user_id);

ALTER TABLE users ADD COLUMN map_instance_id UUID;
ALTER TABLE users ADD COLUMN map_image_msg_id BIGINT;

-- Add FK separately with NOT VALID to avoid blocking reads/writes
ALTER TABLE users
ADD CONSTRAINT fk_users_map_instance
FOREIGN KEY (map_instance_id) REFERENCES entity_instances(id)
ON DELETE SET NULL
NOT VALID;
