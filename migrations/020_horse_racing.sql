-- Horse racing minigame tables
-- See ADR 0007 for design decisions

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Race lifecycle status
CREATE TYPE race_status AS ENUM ('open', 'locked', 'running', 'finished', 'cancelled');

-- Horse definitions synced from data/horses/*.rec
CREATE TABLE IF NOT EXISTS horses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    -- squawk-ignore prefer-bigint-over-int
    speed INT NOT NULL CHECK (speed BETWEEN 1 AND 100),
    -- squawk-ignore prefer-bigint-over-int
    stamina INT NOT NULL CHECK (stamina BETWEEN 1 AND 100),
    -- squawk-ignore prefer-bigint-over-int
    consistency INT NOT NULL CHECK (consistency BETWEEN 1 AND 100),
    -- squawk-ignore prefer-bigint-over-int
    luck INT NOT NULL CHECK (luck BETWEEN 1 AND 100),
    -- Rolling-window performance counters (updated after each race)
    -- squawk-ignore prefer-bigint-over-int
    recent_races INT NOT NULL DEFAULT 0,
    -- squawk-ignore prefer-bigint-over-int
    recent_wins INT NOT NULL DEFAULT 0,
    -- squawk-ignore prefer-bigint-over-int
    recent_places INT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    -- Image assets (synced from data/horses/)
    profile_image BYTEA,
    race_image BYTEA,
    victory_image BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Races (one row per race event)
CREATE TABLE IF NOT EXISTS races (
    -- squawk-ignore prefer-bigint-over-int
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status race_status NOT NULL DEFAULT 'open',
    horses JSONB,
    snapshots JSONB,
    events JSONB,
    finishing_order JSONB,
    odds_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

-- Individual horse results per race
CREATE TABLE IF NOT EXISTS race_results (
    -- squawk-ignore prefer-bigint-over-int
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- squawk-ignore prefer-bigint-over-int
    race_id INT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    horse_id TEXT NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    -- squawk-ignore prefer-bigint-over-int
    position INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_race_results_race ON race_results(race_id);
CREATE INDEX idx_race_results_horse ON race_results(horse_id);

-- Player bets (one bet per user per race)
CREATE TABLE IF NOT EXISTS bets (
    -- squawk-ignore prefer-bigint-over-int
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- squawk-ignore prefer-bigint-over-int
    race_id INT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    horse_id TEXT NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    -- squawk-ignore prefer-bigint-over-int
    amount INT NOT NULL CHECK (amount > 0),
    -- squawk-ignore prefer-bigint-over-int
    payout INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (race_id, user_id)
);

CREATE INDEX idx_bets_race ON bets(race_id);
CREATE INDEX idx_bets_user ON bets(user_id);
