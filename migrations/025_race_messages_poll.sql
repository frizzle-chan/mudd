set lock_timeout = '1s';
set statement_timeout = '5s';
ALTER TABLE race_messages ADD COLUMN poll JSONB;
