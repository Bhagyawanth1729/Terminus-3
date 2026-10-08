PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_origin_active_generation;
CREATE UNIQUE INDEX IF NOT EXISTS idx_origin_one_live_status
ON origin_generations(region,status)
WHERE status IN ('CONFIRMED','PENDING_APPROVAL');

CREATE TABLE IF NOT EXISTS effect_dispatches (
    dispatch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumer_name TEXT NOT NULL REFERENCES consumer_registry(consumer_name),
    event_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    fence_epoch INTEGER NOT NULL CHECK (fence_epoch >= 0),
    state TEXT NOT NULL CHECK (state IN ('SENT','CONFIRMED','FAILED')),
    detail_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_effect_dispatch_event
ON effect_dispatches(consumer_name,event_id,dispatch_id);

CREATE TABLE IF NOT EXISTS origin_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    stream_fingerprint TEXT NOT NULL,
    first_sequence INTEGER NOT NULL,
    last_sequence INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('MATCH','PENDING_GENERATION','APPROVED_GENERATION','REJECTED')),
    detail_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_origin_observation_region_time
ON origin_observations(region,observed_at);
