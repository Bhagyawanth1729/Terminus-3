PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

CREATE TABLE regions (
    region TEXT PRIMARY KEY,
    jetstream_domain TEXT NOT NULL UNIQUE,
    physical_stream TEXT NOT NULL UNIQUE,
    subject_prefix TEXT NOT NULL UNIQUE,
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE origin_generations (
    region TEXT NOT NULL REFERENCES regions(region),
    generation INTEGER NOT NULL CHECK (generation > 0),
    stream_fingerprint TEXT NOT NULL,
    first_sequence INTEGER NOT NULL CHECK (first_sequence >= 0),
    last_observed_sequence INTEGER NOT NULL CHECK (last_observed_sequence >= 0),
    status TEXT NOT NULL CHECK (status IN ('CONFIRMED','PENDING_APPROVAL','RETIRED','REJECTED')),
    approved_by TEXT,
    approved_at TEXT,
    detected_at TEXT NOT NULL,
    PRIMARY KEY (region, generation)
);

CREATE UNIQUE INDEX idx_origin_active_generation
ON origin_generations(region)
WHERE status IN ('CONFIRMED','PENDING_APPROVAL');

CREATE TABLE device_registry (
    device_id TEXT PRIMARY KEY,
    region TEXT NOT NULL REFERENCES regions(region),
    site_id TEXT NOT NULL,
    device_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','MAINTENANCE','RETIRED','QUARANTINED')),
    installed_at TEXT NOT NULL,
    criticality TEXT NOT NULL CHECK (criticality IN ('LOW','MEDIUM','HIGH','SAFETY')),
    last_seen_at TEXT
);

CREATE INDEX idx_device_region_status ON device_registry(region, status);

CREATE TABLE event_journal (
    journal_id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL REFERENCES regions(region),
    generation INTEGER NOT NULL,
    origin_sequence INTEGER NOT NULL CHECK (origin_sequence > 0),
    device_id TEXT NOT NULL REFERENCES device_registry(device_id),
    site_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_bytes INTEGER NOT NULL CHECK (payload_bytes > 0),
    priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 9),
    publish_state TEXT NOT NULL CHECK (publish_state IN ('ACCEPTED','PUBLISHING','PUBLISHED','RETRY','HELD','ARCHIVED')),
    publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    last_publish_at TEXT,
    publish_ack_stream TEXT,
    publish_ack_sequence INTEGER,
    archive_confirmed_at TEXT,
    retention_hold INTEGER NOT NULL DEFAULT 1 CHECK (retention_hold IN (0,1)),
    FOREIGN KEY (region, generation) REFERENCES origin_generations(region, generation),
    UNIQUE (region, generation, origin_sequence)
);

CREATE INDEX idx_event_journal_region_sequence
ON event_journal(region, generation, origin_sequence);
CREATE INDEX idx_event_journal_publish_state
ON event_journal(publish_state, region, generation, origin_sequence);
CREATE INDEX idx_event_journal_retention
ON event_journal(region, generation, retention_hold, origin_sequence);
CREATE INDEX idx_event_journal_device_time
ON event_journal(device_id, event_time);

CREATE TABLE publish_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES event_journal(event_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    message_id TEXT NOT NULL,
    requested_stream TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('STARTED','ACKED','TIMEOUT','ERROR','DUPLICATE_ACK')),
    ack_stream TEXT,
    ack_sequence INTEGER,
    error_code TEXT,
    error_text TEXT,
    UNIQUE(event_id, attempt_no)
);

CREATE INDEX idx_publish_attempts_event ON publish_attempts(event_id, attempt_no);

CREATE TABLE archive_index (
    event_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    origin_sequence INTEGER NOT NULL,
    hub_stream_sequence INTEGER NOT NULL UNIQUE,
    payload_sha256 TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    source_stream TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    duplicate_observation_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_observation_count >= 0),
    UNIQUE(region, generation, origin_sequence)
);

CREATE INDEX idx_archive_origin
ON archive_index(region, generation, origin_sequence);

CREATE TABLE consumer_registry (
    consumer_name TEXT PRIMARY KEY,
    required INTEGER NOT NULL CHECK (required IN (0,1)),
    stream_name TEXT NOT NULL,
    filter_subject TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    max_ack_pending INTEGER NOT NULL CHECK (max_ack_pending > 0),
    ack_wait_seconds INTEGER NOT NULL CHECK (ack_wait_seconds > 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE processing_effects (
    consumer_name TEXT NOT NULL REFERENCES consumer_registry(consumer_name),
    event_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    origin_sequence INTEGER NOT NULL,
    effect_type TEXT NOT NULL,
    effect_payload TEXT NOT NULL,
    effect_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PREPARED','COMMITTED','QUARANTINED','REVERSED')),
    prepared_at TEXT NOT NULL,
    committed_at TEXT,
    worker_id TEXT NOT NULL,
    fence_epoch INTEGER NOT NULL CHECK (fence_epoch >= 0),
    PRIMARY KEY (consumer_name, event_id),
    UNIQUE (consumer_name, effect_key)
);

CREATE INDEX idx_effect_origin
ON processing_effects(consumer_name, region, generation, origin_sequence, status);

CREATE TABLE consumer_checkpoints (
    consumer_name TEXT NOT NULL REFERENCES consumer_registry(consumer_name),
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    last_effect_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_effect_sequence >= 0),
    last_ack_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_ack_sequence >= 0),
    last_event_id TEXT,
    jetstream_ack_floor INTEGER NOT NULL DEFAULT 0 CHECK (jetstream_ack_floor >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (consumer_name, region, generation)
);

CREATE TABLE poison_events (
    consumer_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    origin_sequence INTEGER NOT NULL,
    reason_code TEXT NOT NULL,
    reason_text TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    delivery_count INTEGER NOT NULL CHECK (delivery_count > 0),
    disposition TEXT NOT NULL CHECK (disposition IN ('QUARANTINED','RETRY_APPROVED','DROPPED_WITH_APPROVAL','RESOLVED')),
    PRIMARY KEY (consumer_name, event_id)
);

CREATE TABLE reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','RECOVERY','VERIFY')),
    status TEXT NOT NULL CHECK (status IN ('RUNNING','CONVERGED','DIVERGED','BLOCKED','FAILED')),
    archive_event_count INTEGER NOT NULL DEFAULT 0,
    journal_event_count INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    metadata_mismatch_count INTEGER NOT NULL DEFAULT 0,
    consumer_lag_count INTEGER NOT NULL DEFAULT 0,
    checksum TEXT,
    summary_json TEXT
);

CREATE TABLE reconciliation_findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR','BLOCKER')),
    region TEXT,
    generation INTEGER,
    origin_sequence INTEGER,
    event_id TEXT,
    finding_type TEXT NOT NULL,
    expected_value TEXT,
    observed_value TEXT,
    remediation_hint TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_findings_run_type ON reconciliation_findings(run_id, finding_type);

CREATE TABLE replay_plans (
    plan_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    start_sequence INTEGER NOT NULL CHECK (start_sequence > 0),
    end_sequence INTEGER NOT NULL CHECK (end_sequence >= start_sequence),
    status TEXT NOT NULL CHECK (status IN ('DRAFT','APPROVED','RUNNING','COMPLETED','FAILED','CANCELLED','BLOCKED')),
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    fence_epoch INTEGER,
    CHECK ((status NOT IN ('APPROVED','RUNNING','COMPLETED')) OR approved_at IS NOT NULL)
);

CREATE INDEX idx_replay_active_range
ON replay_plans(region, generation, start_sequence, end_sequence, status);

CREATE TABLE replay_plan_items (
    plan_id TEXT NOT NULL REFERENCES replay_plans(plan_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES event_journal(event_id),
    origin_sequence INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PENDING','PUBLISHED','ALREADY_ARCHIVED','FAILED','HELD')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(plan_id, event_id)
);

CREATE TABLE recovery_leases (
    region TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    fence_epoch INTEGER NOT NULL CHECK (fence_epoch > 0),
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT
);

CREATE TABLE retention_policies (
    region TEXT PRIMARY KEY REFERENCES regions(region),
    journal_min_age_seconds INTEGER NOT NULL CHECK (journal_min_age_seconds > 0),
    stream_max_age_seconds INTEGER NOT NULL CHECK (stream_max_age_seconds > 0),
    maximum_disconnect_seconds INTEGER NOT NULL CHECK (maximum_disconnect_seconds > 0),
    maximum_replay_seconds INTEGER NOT NULL CHECK (maximum_replay_seconds > 0),
    safety_margin_seconds INTEGER NOT NULL CHECK (safety_margin_seconds >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE retention_watermarks (
    region TEXT NOT NULL,
    generation INTEGER NOT NULL,
    archive_sequence INTEGER NOT NULL DEFAULT 0,
    slowest_required_consumer_sequence INTEGER NOT NULL DEFAULT 0,
    replay_pin_sequence INTEGER,
    cleanup_safe_sequence INTEGER NOT NULL DEFAULT 0,
    calculated_at TEXT NOT NULL,
    PRIMARY KEY(region, generation)
);

CREATE TABLE operator_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    region TEXT,
    generation INTEGER,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    state TEXT NOT NULL CHECK (state IN ('REQUESTED','APPROVED','APPLIED','REJECTED','EXPIRED')),
    detail_json TEXT NOT NULL
);

CREATE TABLE runtime_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
