SET lock_timeout = '1s';
SET statement_timeout = '5s';

ALTER TABLE bets DROP CONSTRAINT bets_race_id_user_id_key;

-- squawk-ignore constraint-missing-not-valid,disallowed-unique-constraint
ALTER TABLE bets ADD CONSTRAINT bets_race_user_horse_unique
    UNIQUE (race_id, user_id, horse_id);
