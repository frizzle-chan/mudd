-- Rooms table for storing room definitions
-- Source of truth is data/worlds/<world>/*.rec files
-- Loaded via the entity loader script

CREATE TABLE rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);
