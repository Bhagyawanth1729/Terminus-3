BEGIN IMMEDIATE;

INSERT INTO regions(region, jetstream_domain, physical_stream, subject_prefix, required, enabled, created_at) VALUES
('east', 'edge-east', 'EDGE_EAST_TELEMETRY', 'telemetry.east', 1, 1, '2026-08-01T00:00:00Z'),
('west', 'edge-west', 'EDGE_WEST_TELEMETRY', 'telemetry.west', 1, 1, '2026-08-01T00:00:00Z');

INSERT INTO origin_generations(region, generation, stream_fingerprint, first_sequence, last_observed_sequence, status, approved_by, approved_at, detected_at) VALUES
('east', 1, 'east-gen1-2f85b37a', 1, 6000, 'CONFIRMED', 'platform-ops', '2026-08-01T00:01:00Z', '2026-08-01T00:00:30Z'),
('west', 1, 'west-gen1-5e993c41', 1, 6000, 'CONFIRMED', 'platform-ops', '2026-08-01T00:01:00Z', '2026-08-01T00:00:30Z');

WITH digits(d) AS (
    VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9)
), nums(n) AS (
    SELECT a.d + 10*b.d + 100*c.d + 1
    FROM digits a CROSS JOIN digits b CROSS JOIN digits c
    WHERE a.d + 10*b.d + 100*c.d < 120
), regions(region) AS (
    VALUES('east'),('west')
)
INSERT INTO device_registry(device_id, region, site_id, device_type, status, installed_at, criticality, last_seen_at)
SELECT
    printf('dev-%s-%03d', region, n),
    region,
    printf('site-%02d', 1 + (n % 12)),
    CASE n % 6
        WHEN 0 THEN 'pressure-sensor'
        WHEN 1 THEN 'flow-meter'
        WHEN 2 THEN 'temperature-probe'
        WHEN 3 THEN 'vibration-monitor'
        WHEN 4 THEN 'valve-controller'
        ELSE 'power-quality-meter'
    END,
    CASE n % 17
        WHEN 0 THEN 'MAINTENANCE'
        WHEN 1 THEN 'QUARANTINED'
        ELSE 'ACTIVE'
    END,
    printf('2025-%02d-%02dT08:00:00Z', 1 + (n % 12), 1 + (n % 27)),
    CASE n % 8 WHEN 0 THEN 'SAFETY' WHEN 1 THEN 'HIGH' WHEN 2 THEN 'HIGH' WHEN 3 THEN 'MEDIUM' ELSE 'LOW' END,
    '2026-08-08T18:00:00Z'
FROM nums CROSS JOIN regions;

WITH digits(d) AS (
    VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9)
), nums(x) AS (
    SELECT a.d + 10*b.d + 100*c.d + 1000*d.d + 10000*e.d + 1
    FROM digits a
    CROSS JOIN digits b
    CROSS JOIN digits c
    CROSS JOIN digits d
    CROSS JOIN (SELECT 0 AS d UNION ALL SELECT 1 AS d) e
    WHERE a.d + 10*b.d + 100*c.d + 1000*d.d + 10000*e.d < 12000
), prepared AS (
    SELECT
        x,
        CASE WHEN x % 2 = 0 THEN 'east' ELSE 'west' END AS region,
        CAST((x + 1) / 2 AS INTEGER) AS origin_sequence,
        1 AS generation,
        1 + ((x * 37) % 120) AS device_no,
        1 + ((x * 19) % 12) AS site_no,
        CASE x % 8
            WHEN 0 THEN 'pressure.sample'
            WHEN 1 THEN 'flow.sample'
            WHEN 2 THEN 'temperature.sample'
            WHEN 3 THEN 'vibration.sample'
            WHEN 4 THEN 'valve.state'
            WHEN 5 THEN 'power.sample'
            WHEN 6 THEN 'device.heartbeat'
            ELSE 'quality.alert'
        END AS event_type,
        100 + ((x * 7919) % 4900) AS payload_bytes,
        x % 10 AS priority
    FROM nums
)
INSERT INTO event_journal(
    journal_id, event_id, region, generation, origin_sequence, device_id, site_id,
    event_type, event_time, accepted_at, payload_json, payload_sha256, payload_bytes,
    priority, publish_state, publish_attempts, last_publish_at, publish_ack_stream,
    publish_ack_sequence, archive_confirmed_at, retention_hold
)
SELECT
    x,
    printf('evt-%s-g%02d-%06d', region, generation, origin_sequence),
    region,
    generation,
    origin_sequence,
    printf('dev-%s-%03d', region, device_no),
    printf('site-%02d', site_no),
    event_type,
    datetime('2026-08-08T12:00:00Z', printf('+%d seconds', x * 2)),
    datetime('2026-08-08T12:00:01Z', printf('+%d seconds', x * 2)),
    json_object(
        'reading', 1000 + ((x * 97) % 80000),
        'quality', CASE x % 9 WHEN 0 THEN 'WARN' WHEN 1 THEN 'DEGRADED' ELSE 'GOOD' END,
        'unit', CASE event_type
                    WHEN 'pressure.sample' THEN 'kPa'
                    WHEN 'flow.sample' THEN 'Lpm'
                    WHEN 'temperature.sample' THEN 'C'
                    WHEN 'vibration.sample' THEN 'mm_s'
                    WHEN 'power.sample' THEN 'kW'
                    ELSE 'state'
                END,
        'sample_no', x,
        'site', printf('site-%02d', site_no)
    ),
    printf('%064x', (x * 2654435761) % 2147483647),
    payload_bytes,
    priority,
    CASE
        WHEN origin_sequence <= 5700 THEN 'ARCHIVED'
        WHEN origin_sequence <= 5900 THEN 'PUBLISHED'
        WHEN origin_sequence <= 5960 THEN 'RETRY'
        ELSE 'ACCEPTED'
    END,
    CASE WHEN origin_sequence <= 5700 THEN 1 WHEN origin_sequence <= 5900 THEN 2 ELSE 0 END,
    CASE WHEN origin_sequence <= 5900 THEN datetime('2026-08-08T12:00:03Z', printf('+%d seconds', x * 2)) END,
    CASE WHEN origin_sequence <= 5900 THEN CASE region WHEN 'east' THEN 'EDGE_EAST_TELEMETRY' ELSE 'EDGE_WEST_TELEMETRY' END END,
    CASE WHEN origin_sequence <= 5900 THEN origin_sequence END,
    CASE WHEN origin_sequence <= 5700 THEN datetime('2026-08-08T12:00:05Z', printf('+%d seconds', x * 2)) END,
    1
FROM prepared;

INSERT INTO publish_attempts(event_id, attempt_no, message_id, requested_stream, started_at, finished_at, outcome, ack_stream, ack_sequence)
SELECT
    event_id,
    1,
    event_id,
    CASE region WHEN 'east' THEN 'EDGE_EAST_TELEMETRY' ELSE 'EDGE_WEST_TELEMETRY' END,
    accepted_at,
    last_publish_at,
    'ACKED',
    publish_ack_stream,
    publish_ack_sequence
FROM event_journal
WHERE origin_sequence <= 5900;

INSERT INTO archive_index(
    event_id, region, generation, origin_sequence, hub_stream_sequence, payload_sha256,
    archived_at, source_stream, source_domain, duplicate_observation_count
)
SELECT
    event_id,
    region,
    generation,
    origin_sequence,
    ROW_NUMBER() OVER (ORDER BY accepted_at, event_id),
    payload_sha256,
    datetime(accepted_at, '+4 seconds'),
    CASE region WHEN 'east' THEN 'EDGE_EAST_TELEMETRY' ELSE 'EDGE_WEST_TELEMETRY' END,
    CASE region WHEN 'east' THEN 'edge-east' ELSE 'edge-west' END,
    CASE WHEN origin_sequence % 911 = 0 THEN 1 ELSE 0 END
FROM event_journal
WHERE origin_sequence <= 5700
  AND NOT (region = 'west' AND origin_sequence IN (5311, 5489, 5603))
  AND NOT (region = 'east' AND origin_sequence IN (5397, 5521));

UPDATE event_journal
SET publish_state = CASE WHEN EXISTS (SELECT 1 FROM archive_index a WHERE a.event_id = event_journal.event_id) THEN 'ARCHIVED' ELSE 'PUBLISHED' END,
    archive_confirmed_at = CASE WHEN EXISTS (SELECT 1 FROM archive_index a WHERE a.event_id = event_journal.event_id)
                                THEN datetime(accepted_at, '+4 seconds') ELSE NULL END
WHERE origin_sequence <= 5700;

INSERT INTO consumer_registry(consumer_name, required, stream_name, filter_subject, effect_type, max_ack_pending, ack_wait_seconds, enabled, created_at) VALUES
('telemetry-indexer', 1, 'REGIONAL_RAW_ARCHIVE', 'telemetry.raw.>', 'SEARCH_INDEX', 512, 45, 1, '2026-08-01T00:02:00Z'),
('safety-state-projector', 1, 'REGIONAL_RAW_ARCHIVE', 'telemetry.raw.>', 'SAFETY_STATE', 256, 60, 1, '2026-08-01T00:02:00Z'),
('analytics-sampler', 0, 'REGIONAL_RAW_ARCHIVE', 'telemetry.raw.>', 'ANALYTICS_SAMPLE', 1024, 30, 1, '2026-08-01T00:02:00Z');

INSERT INTO processing_effects(
    consumer_name, event_id, effect_key, region, generation, origin_sequence,
    effect_type, effect_payload, effect_sha256, status, prepared_at, committed_at,
    worker_id, fence_epoch
)
SELECT
    'telemetry-indexer',
    a.event_id,
    'idx:' || a.event_id,
    a.region,
    a.generation,
    a.origin_sequence,
    'SEARCH_INDEX',
    json_object('event_id', a.event_id, 'indexed', 1),
    a.payload_sha256,
    'COMMITTED',
    a.archived_at,
    datetime(a.archived_at, '+1 second'),
    'indexer-seed',
    1
FROM archive_index a
WHERE a.origin_sequence <= CASE a.region WHEN 'east' THEN 5650 ELSE 5580 END;

INSERT INTO processing_effects(
    consumer_name, event_id, effect_key, region, generation, origin_sequence,
    effect_type, effect_payload, effect_sha256, status, prepared_at, committed_at,
    worker_id, fence_epoch
)
SELECT
    'safety-state-projector',
    a.event_id,
    'safety:' || a.event_id,
    a.region,
    a.generation,
    a.origin_sequence,
    'SAFETY_STATE',
    json_object('event_id', a.event_id, 'projected', 1),
    a.payload_sha256,
    'COMMITTED',
    a.archived_at,
    datetime(a.archived_at, '+2 seconds'),
    'safety-seed',
    1
FROM archive_index a
WHERE a.origin_sequence <= CASE a.region WHEN 'east' THEN 5610 ELSE 5540 END;

INSERT INTO consumer_checkpoints(
    consumer_name, region, generation, last_effect_sequence, last_ack_sequence,
    last_event_id, jetstream_ack_floor, updated_at
) VALUES
('telemetry-indexer','east',1,5650,5650,'evt-east-g01-005650',5650,'2026-08-08T18:30:00Z'),
('telemetry-indexer','west',1,5580,5580,'evt-west-g01-005580',5580,'2026-08-08T18:30:00Z'),
('safety-state-projector','east',1,5610,5610,'evt-east-g01-005610',5610,'2026-08-08T18:30:00Z'),
('safety-state-projector','west',1,5540,5540,'evt-west-g01-005540',5540,'2026-08-08T18:30:00Z'),
('analytics-sampler','east',1,5400,5400,'evt-east-g01-005400',5400,'2026-08-08T18:30:00Z'),
('analytics-sampler','west',1,5400,5400,'evt-west-g01-005400',5400,'2026-08-08T18:30:00Z');

INSERT INTO retention_policies(
    region, journal_min_age_seconds, stream_max_age_seconds, maximum_disconnect_seconds,
    maximum_replay_seconds, safety_margin_seconds, updated_at
) VALUES
('east', 21600, 259200, 172800, 43200, 21600, '2026-08-01T00:03:00Z'),
('west', 21600, 259200, 172800, 43200, 21600, '2026-08-01T00:03:00Z');

INSERT INTO retention_watermarks(
    region, generation, archive_sequence, slowest_required_consumer_sequence,
    replay_pin_sequence, cleanup_safe_sequence, calculated_at
) VALUES
('east',1,5699,5610,NULL,5610,'2026-08-08T18:31:00Z'),
('west',1,5697,5540,NULL,5540,'2026-08-08T18:31:00Z');

INSERT INTO replay_plans(
    plan_id, region, generation, start_sequence, end_sequence, status, reason,
    created_by, created_at, approved_by, approved_at
) VALUES
('rp-west-incident-001','west',1,5311,5603,'APPROVED','Hub reconciliation found three west archive gaps after carrier reconnect.','night-ops','2026-08-08T18:35:00Z','shift-lead','2026-08-08T18:36:00Z');

INSERT INTO replay_plan_items(plan_id,event_id,origin_sequence,state,attempts,updated_at)
SELECT 'rp-west-incident-001', event_id, origin_sequence, 'PENDING', 0, '2026-08-08T18:36:00Z'
FROM event_journal
WHERE region='west' AND generation=1 AND origin_sequence IN (5311,5489,5603);

INSERT INTO runtime_kv(key,value,updated_at) VALUES
('incident_id','INC-JS-2026-0808-17','2026-08-08T18:40:00Z'),
('last_operator','night-ops','2026-08-08T18:40:00Z'),
('recovery_mode','HOLD','2026-08-08T18:40:00Z'),
('expected_hub_archive','REGIONAL_RAW_ARCHIVE','2026-08-08T18:40:00Z');

COMMIT;
