-- Add no_duplicates column to spawning_pools
-- When TRUE, the pool will not spawn an entity type that is already spawned by the pool

SET lock_timeout = '1s';
SET statement_timeout = '5s';

ALTER TABLE spawning_pools
ADD COLUMN no_duplicates BOOLEAN NOT NULL DEFAULT FALSE;
