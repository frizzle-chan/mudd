set lock_timeout = '1s';
set statement_timeout = '5s';
ALTER TYPE race_message_type ADD VALUE IF NOT EXISTS 'event_start';
