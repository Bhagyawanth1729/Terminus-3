"""Behavioral checks for the regional JetStream continuity control plane."""

from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

APP = Path(os.environ.get("CONTINUITY_ARTIFACT", "/app/continuity"))
BIN = APP / "bin" / "continuityctl"
HEALTH = APP / "out" / "health.json"
RECON = APP / "out" / "reconciliation.json"
CONTRACT = APP / "docs" / "continuity-contract.md"


def _run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP)
    env["CONTINUITY_ROOT"] = str(root)
    command, *rest = args
    return subprocess.run(
        [sys.executable, "-m", "continuity.cli", command, "--root", str(root), "--compact", *rest],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _json(cp: subprocess.CompletedProcess[str]) -> Any:
    text = cp.stdout.strip()
    if not text:
        raise AssertionError(f"empty stdout rc={cp.returncode}\n{cp.stderr}")
    return json.loads(text)


def _db(root: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(root / "state" / "continuity.db")
    connection.row_factory = sqlite3.Row
    return connection


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "continuity"
    shutil.copytree(APP / "config", root / "config")
    shutil.copytree(APP / "sql", root / "sql")
    (root / "state").mkdir(parents=True)
    shutil.copy2(APP / "state" / "continuity.db", root / "state" / "continuity.db")
    (root / "out").mkdir()
    (root / "run").mkdir()
    (root / "log" / "runtime").mkdir(parents=True)
    return root


def _timestamp_ok(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)) and math.isfinite(value):
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _config() -> dict[str, Any]:
    return json.loads((APP / "config" / "continuity.json").read_text(encoding="utf-8"))


def _horizon_seconds(config: dict[str, Any]) -> int:
    recovery = config["recovery"]
    return int(
        recovery["maximum_disconnect_seconds"]
        + recovery["maximum_replay_seconds"]
        + recovery["safety_margin_seconds"]
    )


def _sql(root: Path, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    connection = _db(root)
    try:
        return list(connection.execute(sql, params))
    finally:
        connection.close()


def _exec(root: Path, sql: str, params: tuple[Any, ...] = ()) -> None:
    connection = _db(root)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return _workspace(tmp_path)


def test_p2p_operator_entrypoints_and_contract_present() -> None:
    """Operator binary, contract, and seeded durability store remain present."""
    assert BIN.is_file()
    assert CONTRACT.is_file()
    assert (APP / "state" / "continuity.db").is_file()
    assert "event identity" in CONTRACT.read_text(encoding="utf-8").lower()


def test_p2p_inspect_and_reconcile_do_not_mutate_replay(ws: Path) -> None:
    """Diagnostic inspect and reconcile leave replay plans and journal membership unchanged."""
    before_plans = _sql(ws, "SELECT plan_id,status FROM replay_plans ORDER BY plan_id")
    before_journal = _sql(ws, "SELECT event_id FROM event_journal ORDER BY event_id")
    inspect = _run(ws, ["inspect"])
    reconcile = _run(ws, ["reconcile"])
    assert inspect.returncode in {0, 2}
    assert reconcile.returncode in {0, 2}
    after_plans = _sql(ws, "SELECT plan_id,status FROM replay_plans ORDER BY plan_id")
    after_journal = _sql(ws, "SELECT event_id FROM event_journal ORDER BY event_id")
    assert [(row["plan_id"], row["status"]) for row in after_plans] == [
        (row["plan_id"], row["status"]) for row in before_plans
    ]
    assert [row["event_id"] for row in after_journal] == [row["event_id"] for row in before_journal]


def test_p2p_same_payload_events_remain_distinct(ws: Path) -> None:
    """Two journal identities stay distinct even when payload hashes can coincide."""
    rows = _sql(
        ws,
        "SELECT event_id,payload_sha256 FROM event_journal WHERE region='east' LIMIT 2",
    )
    assert len(rows) == 2
    assert rows[0]["event_id"] != rows[1]["event_id"]
    document = _json(_run(ws, ["reconcile", "--region", "east"]))
    assert document["regions"]["east"]["journal_event_count"] >= 2


def test_p2p_current_lease_owner_renews_same_epoch(ws: Path) -> None:
    """The current recovery owner can renew without advancing fence_epoch."""
    acquired = _json(_run(ws, ["lease", "acquire", "east", "--owner", "ops-a", "--ttl", "30"]))
    renewed = _json(
        _run(
            ws,
            [
                "lease",
                "renew",
                "east",
                "--owner",
                "ops-a",
                "--epoch",
                str(acquired["fence_epoch"]),
                "--ttl",
                "45",
            ],
        )
    )
    assert renewed["fence_epoch"] == acquired["fence_epoch"]
    assert renewed["owner_id"] == "ops-a"


def test_p2p_stale_lease_release_is_rejected(ws: Path) -> None:
    """Release with a stale fence epoch is rejected and the current lease remains."""
    acquired = _json(_run(ws, ["lease", "acquire", "east", "--owner", "ops-a", "--ttl", "30"]))
    stale = _run(
        ws,
        ["lease", "release", "east", "--owner", "ops-a", "--epoch", str(acquired["fence_epoch"] - 1)],
    )
    assert stale.returncode != 0
    current = _json(_run(ws, ["lease", "show", "east"]))
    assert current["owner_id"] == "ops-a"
    assert current["fence_epoch"] == acquired["fence_epoch"]


def test_p2p_cleanup_respects_minimum_age_and_holds(ws: Path) -> None:
    """Retention never selects rows that are younger than the journal minimum or explicitly held."""
    young = _sql(
        ws,
        "SELECT event_id FROM event_journal WHERE region='east' AND origin_sequence=1",
    )[0]["event_id"]
    _exec(ws, "UPDATE event_journal SET retention_hold=1 WHERE region='east'")
    _exec(
        ws,
        "UPDATE event_journal SET retention_hold=0, accepted_at=? WHERE event_id=?",
        (datetime.now().astimezone().isoformat(), young),
    )
    document = _json(_run(ws, ["retention", "east", "--limit", "50"]))
    held = {row["event_id"] for row in _sql(ws, "SELECT event_id FROM event_journal WHERE retention_hold=1")}
    assert not set(document["eligible_event_ids"]) & held
    assert young not in set(document["eligible_event_ids"])


def test_p2p_generation_approval_does_not_rewrite_history(ws: Path) -> None:
    """Approving a later generation leaves historical journal rows on their original generation."""
    sample = _sql(
        ws,
        "SELECT generation FROM event_journal WHERE region='west' AND origin_sequence=12",
    )[0]
    assert sample["generation"] == 1
    _exec(
        ws,
        "INSERT INTO origin_generations(region, generation, stream_fingerprint, first_sequence, "
        "last_observed_sequence, status, approved_by, approved_at, detected_at) VALUES "
        "('west', 2, 'west-recreated-stream-9c', 1, 40, 'PENDING_APPROVAL', NULL, NULL, '2026-08-08T18:10:00Z')",
    )
    approved = _json(
        _run(ws, ["approve-generation", "west", "2", "--approved-by", "platform-ops"])
    )
    assert approved["generation"] == 2
    assert approved["status"] == "CONFIRMED"
    after = _sql(
        ws,
        "SELECT generation FROM event_journal WHERE region='west' AND origin_sequence=12",
    )[0]
    assert after["generation"] == 1
    generations = _json(_run(ws, ["generations", "--region", "west"]))
    assert any(item["generation"] == 1 and item["status"] == "RETIRED" for item in generations)
    assert any(item["generation"] == 2 and item["status"] == "CONFIRMED" for item in generations)


def test_p2p_cli_recovery_entrypoints_operate(ws: Path) -> None:
    """Core recovery commands remain callable through continuityctl."""
    assert _run(ws, ["generations"]).returncode == 0
    assert _run(ws, ["list-replay", "--region", "west"]).returncode == 0
    assert _run(ws, ["retention", "west", "--limit", "5"]).returncode in {0, 2}


def test_f2p_health_and_reconciliation_reports_materialized() -> None:
    """Verify writes both operator reports with the contractual fields and timestamps."""
    assert HEALTH.is_file() and RECON.is_file()
    health = json.loads(HEALTH.read_text(encoding="utf-8"))
    recon = json.loads(RECON.read_text(encoding="utf-8"))
    for name in (
        "healthy",
        "topology_ok",
        "generations_ok",
        "publication_ok",
        "archive_ok",
        "consumers_ok",
        "retention_ok",
        "recovery_ok",
        "generated_at",
    ):
        assert name in health
    assert _timestamp_ok(health["generated_at"])
    assert _timestamp_ok(recon["generated_at"])
    assert isinstance(recon["converged"], bool)
    assert set(recon["regions"]) == {"east", "west"}
    for region, body in recon["regions"].items():
        assert body["status"] in {"CONVERGED", "DIVERGED"}
        assert body["converged"] is (body["status"] == "CONVERGED")
        for field in (
            "journal_event_count",
            "archive_event_count",
            "missing_count",
            "unexpected_count",
            "duplicate_count",
            "metadata_mismatch_count",
            "consumer_lag_count",
            "highest_contiguous_archive_origin_sequence",
        ):
            assert isinstance(body[field], int)
        assert "required_consumer_progress" in body
        assert recon["converged"] is False or body["converged"] is True
        assert region in {"east", "west"}
    flags = [
        health["topology_ok"],
        health["generations_ok"],
        health["publication_ok"],
        health["archive_ok"],
        health["consumers_ok"],
        health["retention_ok"],
        health["recovery_ok"],
    ]
    assert health["healthy"] is all(flags)
    assert health["generations_ok"] is True


def test_f2p_reports_do_not_erase_incident_gaps() -> None:
    """Final reports keep the captured west replay plan and archive identity gaps visible."""
    recon = json.loads(RECON.read_text(encoding="utf-8"))
    west = recon["regions"]["west"]
    east = recon["regions"]["east"]
    assert west["missing_count"] >= 3
    assert east["missing_count"] >= 2
    assert recon["converged"] is False
    health = json.loads(HEALTH.read_text(encoding="utf-8"))
    assert health["recovery_ok"] is False
    assert health["archive_ok"] is False
    rows = _sql(
        APP,
        "SELECT status FROM replay_plans WHERE plan_id='rp-west-incident-001'",
    )
    assert rows and rows[0]["status"] in {"APPROVED", "RUNNING"}


def test_f2p_topology_uses_unique_source_only_streams() -> None:
    """Physical origin names are unique and the hub archive does not listen on local raw subjects."""
    health = json.loads(HEALTH.read_text(encoding="utf-8"))
    assert health["topology_ok"] is True
    config = _config()
    names = [
        config["regions"]["east"]["stream_name"],
        config["regions"]["west"]["stream_name"],
        config["hub"]["stream_name"],
    ]
    assert len(names) == len(set(names))
    assert config["topology"]["hub_archive"]["subjects"] == []
    sources = {item["region"]: item for item in config["topology"]["sources"]}
    assert sources["east"]["origin"]["domain"] == config["regions"]["east"]["domain"]
    assert sources["west"]["origin"]["domain"] == config["regions"]["west"]["domain"]
    assert sources["west"]["origin"]["name"] == config["regions"]["west"]["stream_name"]
    prefix = str(config["topology"]["derived_subject_prefix"])
    assert not prefix.startswith("telemetry.raw")


def test_f2p_stream_max_age_covers_recovery_horizon() -> None:
    """Configured raw stream max-age covers disconnect plus replay plus safety margin."""
    config = _config()
    needed = _horizon_seconds(config)
    for policy in (
        config["regions"]["east"]["stream_policy"],
        config["regions"]["west"]["stream_policy"],
        config["hub_stream_policy"],
    ):
        assert int(policy["max_age_seconds"]) >= needed
    health = json.loads(HEALTH.read_text(encoding="utf-8"))
    assert health["retention_ok"] is True


def test_f2p_retry_uses_stable_event_identity(ws: Path) -> None:
    """A publish attempt records Nats-Msg-Id equal to the stable event_id, not an attempt suffix."""
    event_id = "evt-east-g01-005961"
    cp = _run(ws, ["publish", event_id])
    assert cp.returncode != 0
    rows = _sql(
        ws,
        "SELECT message_id,outcome FROM publish_attempts WHERE event_id=? ORDER BY attempt_no DESC LIMIT 1",
        (event_id,),
    )
    assert rows
    assert rows[0]["message_id"] == event_id
    assert ":attempt:" not in rows[0]["message_id"]


def test_f2p_second_publish_attempt_keeps_same_message_id(ws: Path) -> None:
    """A later publish retry still uses the stable event identity as Nats-Msg-Id."""
    event_id = "evt-east-g01-005963"
    _run(ws, ["publish", event_id])
    _run(ws, ["publish", event_id])
    rows = _sql(
        ws,
        "SELECT attempt_no,message_id FROM publish_attempts WHERE event_id=? ORDER BY attempt_no",
        (event_id,),
    )
    ids = [row["message_id"] for row in rows if row["message_id"] == event_id]
    assert len(ids) >= 2
    assert set(ids) == {event_id}


def test_f2p_failed_publish_does_not_mark_journal_published(ws: Path) -> None:
    """A publish that never receives an origin acknowledgement must not stay PUBLISHED."""
    event_id = "evt-west-g01-005962"
    before = _sql(ws, "SELECT publish_state FROM event_journal WHERE event_id=?", (event_id,))[0]
    assert before["publish_state"] in {"ACCEPTED", "RETRY"}
    _run(ws, ["publish", event_id])
    after = _sql(ws, "SELECT publish_state FROM event_journal WHERE event_id=?", (event_id,))[0]
    assert after["publish_state"] != "PUBLISHED"


def test_f2p_generation_regression_is_held(ws: Path) -> None:
    """A lower origin sequence on the confirmed fingerprint is held for operator approval."""
    config = _config()
    cp = _run(
        ws,
        [
            "observe-origin",
            "east",
            "--stream",
            str(config["regions"]["east"]["stream_name"]),
            "--domain",
            str(config["regions"]["east"]["domain"]),
            "--fingerprint",
            "east-gen1-2f85b37a",
            "--first",
            "1",
            "--last",
            "12",
        ],
    )
    document = _json(cp)
    assert document["status"] == "PENDING_APPROVAL"
    confirmed = [
        item
        for item in _json(_run(ws, ["generations", "--region", "east"]))
        if item["status"] == "CONFIRMED"
    ]
    assert len(confirmed) == 1
    assert confirmed[0]["generation"] == 1
    assert confirmed[0]["last_observed_sequence"] == 6000


def test_f2p_generation_fingerprint_change_is_held(ws: Path) -> None:
    """A new origin fingerprint is recorded as pending and is not auto-approved."""
    config = _config()
    document = _json(
        _run(
            ws,
            [
                "observe-origin",
                "west",
                "--stream",
                str(config["regions"]["west"]["stream_name"]),
                "--domain",
                str(config["regions"]["west"]["domain"]),
                "--fingerprint",
                "west-recreated-stream-9c",
                "--first",
                "1",
                "--last",
                "40",
            ],
        )
    )
    assert document["status"] == "PENDING_APPROVAL"
    assert document["generation"] == 2
    generations = _json(_run(ws, ["generations", "--region", "west"]))
    assert any(item["generation"] == 1 and item["status"] == "CONFIRMED" for item in generations)
    assert any(item["generation"] == 2 and item["status"] == "PENDING_APPROVAL" for item in generations)
    health = _json(_run(ws, ["inspect"]))
    assert health["generations_ok"] is False


def test_f2p_observe_origin_rejects_stream_mismatch(ws: Path) -> None:
    """Origin observations that name the wrong physical stream are rejected."""
    config = _config()
    cp = _run(
        ws,
        [
            "observe-origin",
            "east",
            "--stream",
            "WRONG_STREAM",
            "--domain",
            str(config["regions"]["east"]["domain"]),
            "--fingerprint",
            "east-gen1-2f85b37a",
            "--first",
            "1",
            "--last",
            "10",
        ],
    )
    assert cp.returncode != 0


def test_f2p_monotonic_confirmed_generation_continues(ws: Path) -> None:
    """A matching fingerprint with a later contiguous sequence updates the confirmed watermark."""
    config = _config()
    document = _json(
        _run(
            ws,
            [
                "observe-origin",
                "east",
                "--stream",
                str(config["regions"]["east"]["stream_name"]),
                "--domain",
                str(config["regions"]["east"]["domain"]),
                "--fingerprint",
                "east-gen1-2f85b37a",
                "--first",
                "6001",
                "--last",
                "6004",
            ],
        )
    )
    assert document["status"] == "CONFIRMED"
    assert document["last_observed_sequence"] == 6004


def test_f2p_replay_plan_contains_only_missing_identities(ws: Path) -> None:
    """Replay planning selects identities absent from the archive, not the full journal range."""
    _exec(ws, "UPDATE replay_plans SET status='CANCELLED' WHERE region='west'")
    document = _json(
        _run(
            ws,
            [
                "plan-replay",
                "west",
                "--created-by",
                "verifier",
                "--reason",
                "identity-gap",
            ],
        )
    )
    event_ids = document["missing_event_ids"]
    assert document["plan"] is not None
    assert set(event_ids) == set(document["plan"]["event_ids"])
    archived = {
        row["event_id"]
        for row in _sql(ws, "SELECT event_id FROM archive_index WHERE region='west'")
    }
    assert archived.isdisjoint(set(event_ids))
    assert "evt-west-g01-005311" in event_ids
    assert "evt-west-g01-000010" not in event_ids


def test_f2p_replay_refuses_unapproved_generation(ws: Path) -> None:
    """Planning replay across a pending generation transition is blocked."""
    config = _config()
    _run(
        ws,
        [
            "observe-origin",
            "east",
            "--stream",
            str(config["regions"]["east"]["stream_name"]),
            "--domain",
            str(config["regions"]["east"]["domain"]),
            "--fingerprint",
            "east-recreated-aa",
            "--first",
            "1",
            "--last",
            "8",
        ],
    )
    document = _json(
        _run(
            ws,
            [
                "plan-replay",
                "east",
                "--generation",
                "2",
                "--created-by",
                "verifier",
                "--reason",
                "pending-gen",
            ],
        )
    )
    assert document["plan"] is None
    assert document["blocked_reason"]


def test_f2p_overlapping_active_replay_plan_is_rejected(ws: Path) -> None:
    """A second active plan that overlaps an approved origin range is rejected."""
    cp = _run(
        ws,
        [
            "plan-replay",
            "west",
            "--created-by",
            "verifier",
            "--reason",
            "overlap",
        ],
    )
    assert cp.returncode != 0
    assert "overlap" in (cp.stderr + cp.stdout).lower() or cp.returncode == 2


def test_f2p_reconcile_uses_event_identity_not_counts(ws: Path) -> None:
    """Equal journal and archive counts still diverge when identities are offsetting mismatches."""
    missing = "evt-east-g01-000100"
    _exec(ws, "DELETE FROM archive_index WHERE event_id=?", (missing,))
    _exec(
        ws,
        "INSERT INTO archive_index(event_id,region,generation,origin_sequence,hub_stream_sequence,"
        "payload_sha256,archived_at,source_stream,source_domain,duplicate_observation_count) "
        "VALUES('evt-east-g01-009999','east',1,9999,9000999,'abcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcd',"
        "'2026-08-08T18:00:00Z','EDGE_EAST_TELEMETRY','edge-east',0)",
    )
    document = _json(_run(ws, ["reconcile", "--region", "east"]))
    east = document["regions"]["east"]
    assert east["status"] == "DIVERGED"
    assert east["missing_count"] >= 1
    assert east["unexpected_count"] >= 1


def test_f2p_reconcile_ignores_hub_sequence_as_completeness_key(ws: Path) -> None:
    """Hub aggregate sequence is not treated as an edge completeness watermark."""
    document = _json(_run(ws, ["reconcile"]))
    west = document["regions"]["west"]
    assert west["status"] == "DIVERGED"
    assert west["missing_count"] >= 3
    assert west["highest_contiguous_archive_origin_sequence"] != west["journal_event_count"]


def test_f2p_convergence_waits_for_required_consumers(ws: Path) -> None:
    """A region is not CONVERGED while a required consumer checkpoint lags the confirmed watermark."""
    watermark = 40
    _exec(
        ws,
        "UPDATE origin_generations SET last_observed_sequence=? WHERE region='east' AND generation=1",
        (watermark,),
    )
    _exec(ws, "DELETE FROM event_journal WHERE region='east' AND origin_sequence>?", (watermark,))
    _exec(ws, "DELETE FROM archive_index WHERE region='east' AND origin_sequence>?", (watermark,))
    _exec(
        ws,
        "DELETE FROM archive_index WHERE region='east' AND event_id NOT IN "
        "(SELECT event_id FROM event_journal WHERE region='east')",
    )
    _exec(
        ws,
        "INSERT INTO archive_index(event_id,region,generation,origin_sequence,hub_stream_sequence,"
        "payload_sha256,archived_at,source_stream,source_domain,duplicate_observation_count) "
        "SELECT event_id, region, generation, origin_sequence, 9100000 + origin_sequence, "
        "payload_sha256, '2026-08-08T18:00:00Z', 'EDGE_EAST_TELEMETRY', 'edge-east', 0 "
        "FROM event_journal WHERE region='east' AND generation=1 AND origin_sequence<=? "
        "AND event_id NOT IN (SELECT event_id FROM archive_index)",
        (watermark,),
    )
    _exec(
        ws,
        "UPDATE consumer_checkpoints SET last_effect_sequence=8, last_ack_sequence=8, "
        "jetstream_ack_floor=8 WHERE region='east'",
    )
    document = _json(_run(ws, ["reconcile", "--region", "east"]))
    east = document["regions"]["east"]
    progress = east["required_consumer_progress"]
    assert "telemetry-indexer" in progress
    assert "safety-state-projector" in progress
    assert east["missing_count"] == 0
    assert east["unexpected_count"] == 0
    assert east["highest_contiguous_archive_origin_sequence"] >= watermark
    assert east["consumer_lag_count"] >= 1
    assert east["status"] == "DIVERGED"
    assert all(int(value) < watermark for value in progress.values())


def test_f2p_cleanup_stops_at_archive_and_consumer_and_replay_pin(ws: Path) -> None:
    """Cleanup-safe sequence is the minimum of archive floor, slowest required consumer, and replay pin minus one."""
    _exec(ws, "UPDATE event_journal SET retention_hold=0 WHERE region='west' AND origin_sequence<=4000")
    document = _json(_run(ws, ["retention", "west", "--limit", "20"]))
    pin = 5311
    consumer = int(document["required_consumer_sequence"])
    archive = int(document["archive_sequence"])
    expected = min(archive, consumer, pin - 1)
    assert document["safe_sequence"] == expected
    assert document["replay_pin_sequence"] == pin
    for event_id in document["eligible_event_ids"]:
        seq = int(event_id.rsplit("-", 1)[-1])
        assert seq <= expected


def test_f2p_expired_lease_reacquire_advances_epoch(ws: Path) -> None:
    """Reacquiring an expired recovery lease increments fence_epoch even for the same owner."""
    first = _json(_run(ws, ["lease", "acquire", "east", "--owner", "ops-a", "--ttl", "1"]))
    _exec(
        ws,
        "UPDATE recovery_leases SET acquired_at='2019-12-31T00:00:00Z', "
        "renewed_at='2019-12-31T00:00:00Z', expires_at='2020-01-01T00:00:00Z' WHERE region='east'",
    )
    second = _json(_run(ws, ["lease", "acquire", "east", "--owner", "ops-a", "--ttl", "30"]))
    assert second["fence_epoch"] == first["fence_epoch"] + 1


def test_f2p_stale_recovery_worker_is_fenced(ws: Path) -> None:
    """execute-replay with a stale fence epoch fails before mutating replay-item state."""
    acquired = _json(_run(ws, ["lease", "acquire", "west", "--owner", "ops-a", "--ttl", "30"]))
    before = _sql(
        ws,
        "SELECT state FROM replay_plan_items WHERE plan_id='rp-west-incident-001' ORDER BY origin_sequence",
    )
    cp = _run(
        ws,
        [
            "execute-replay",
            "rp-west-incident-001",
            "--owner",
            "ops-a",
            "--epoch",
            str(acquired["fence_epoch"] - 1 if acquired["fence_epoch"] > 1 else 0),
        ],
    )
    assert cp.returncode != 0
    after = _sql(
        ws,
        "SELECT state FROM replay_plan_items WHERE plan_id='rp-west-incident-001' ORDER BY origin_sequence",
    )
    assert [row["state"] for row in after] == [row["state"] for row in before]
    plan = _sql(ws, "SELECT status FROM replay_plans WHERE plan_id='rp-west-incident-001'")[0]
    assert plan["status"] == "APPROVED"


def test_f2p_consumers_ok_reports_effect_ack_gap(ws: Path) -> None:
    """Health consumers_ok is false when application effects and acknowledgement floors disagree."""
    _exec(
        ws,
        "UPDATE consumer_checkpoints SET jetstream_ack_floor=last_effect_sequence+80 "
        "WHERE consumer_name='telemetry-indexer' AND region='east'",
    )
    health = _json(_run(ws, ["inspect"]))
    assert health["consumers_ok"] is False


def test_f2p_publication_ok_stays_false_while_retry_work_remains() -> None:
    """Incident journal rows still in RETRY or ACCEPTED keep publication_ok false."""
    health = json.loads(HEALTH.read_text(encoding="utf-8"))
    assert health["publication_ok"] is False
    retrying = _sql(
        APP,
        "SELECT COUNT(*) AS n FROM event_journal WHERE publish_state IN ('RETRY','ACCEPTED','PUBLISHING','HELD')",
    )[0]["n"]
    assert retrying > 0


@pytest.fixture(scope="module")
def live_lab() -> Path:
    nats_bin = shutil.which("nats-server")
    if not nats_bin:
        pytest.fail("nats-server is not installed in the verifier image")
    for name in ("hub", "east", "west"):
        conf = APP / "config" / "nats" / f"{name}.conf"
        text = conf.read_text(encoding="utf-8")
        text = text.replace(f"/app/continuity/state/nats/{name}", f"/tmp/continuity-nats/{name}")
        conf.write_text(text, encoding="utf-8")
        Path(f"/tmp/continuity-nats/{name}").mkdir(parents=True, exist_ok=True)
    (APP / "log" / "runtime").mkdir(parents=True, exist_ok=True)
    (APP / "run").mkdir(parents=True, exist_ok=True)
    _run(APP, ["lab-stop"])
    start = _run(APP, ["lab-start", "--timeout", "25"])
    if start.returncode != 0:
        logs = []
        for name in ("hub", "east", "west"):
            path = APP / "log" / "runtime" / f"{name}.log"
            body = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            logs.append(f"--- {name} ---\n{body[-4000:]}")
        pytest.fail(f"lab-start failed rc={start.returncode}\n{start.stdout}\n{start.stderr}\n" + "\n".join(logs))
    yield APP
    _run(APP, ["lab-stop"])


def test_f2p_hub_archive_is_source_only(live_lab: Path) -> None:
    """After lab-start the hub raw archive exposes no local listen subjects."""
    started = _json(_run(live_lab, ["lab-start", "--timeout", "20"]))
    hub = started["streams"]["hub"]
    subjects = hub.get("subjects") or hub.get("config", {}).get("subjects") or []
    assert subjects == []
    east = started["streams"]["east"]
    west = started["streams"]["west"]
    east_name = east.get("name") or east.get("config", {}).get("name")
    west_name = west.get("name") or west.get("config", {}).get("name")
    if east_name and west_name:
        assert east_name != west_name


def _insert_event(root: Path, *, event_id: str, device_id: str, sequence: int) -> None:
    region = "east" if "-east-" in event_id else "west"
    payload = json.dumps({"reading": sequence, "quality": "GOOD", "unit": "kPa", "sample_no": sequence})
    _exec(
        root,
        "INSERT INTO event_journal(event_id,region,generation,origin_sequence,device_id,site_id,event_type,"
        "event_time,accepted_at,payload_json,payload_sha256,payload_bytes,priority,publish_state,publish_attempts,retention_hold) "
        "VALUES(?,?,1,?,?,?,'pressure.sample','2026-08-08T19:00:00Z','2026-08-08T19:00:01Z',?,"
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',120,1,'ACCEPTED',0,1)",
        (event_id, region, sequence, device_id, "site-01", payload),
    )


def _await_effect(root: Path, event_id: str, *, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        _run(
            root,
            [
                "run-consumer",
                "telemetry-indexer",
                "--worker",
                "w-live",
                "--epoch",
                "0",
                "--max-messages",
                "50",
            ],
        )
        count = _sql(
            root,
            "SELECT COUNT(*) AS n FROM processing_effects WHERE consumer_name='telemetry-indexer' AND event_id=?",
            (event_id,),
        )[0]["n"]
        poison = _sql(
            root,
            "SELECT COUNT(*) AS n FROM poison_events WHERE consumer_name='telemetry-indexer' AND event_id=?",
            (event_id,),
        )[0]["n"]
        if count or poison:
            return int(count)
        time.sleep(0.25)
    return int(count)


def test_f2p_redelivery_creates_single_effect(live_lab: Path, tmp_path: Path) -> None:
    """Processing the same origin event twice commits one idempotent consumer effect."""
    root = _workspace(tmp_path)
    event_id = "evt-east-g01-006080"
    _insert_event(root, event_id=event_id, device_id="dev-east-003", sequence=6080)
    published = _run(root, ["publish", event_id])
    assert published.returncode == 0, published.stderr
    assert _await_effect(root, event_id) == 1
    _run(
        root,
        ["run-consumer", "telemetry-indexer", "--worker", "w1", "--epoch", "0", "--max-messages", "50"],
    )
    rows = _sql(
        root,
        "SELECT COUNT(*) AS n FROM processing_effects WHERE consumer_name='telemetry-indexer' AND event_id=?",
        (event_id,),
    )
    assert rows[0]["n"] == 1


def test_f2p_committed_effect_survives_redelivery(live_lab: Path, tmp_path: Path) -> None:
    """A committed effect is reused on redelivery instead of inserting a second business effect."""
    root = _workspace(tmp_path)
    event_id = "evt-east-g01-006081"
    _insert_event(root, event_id=event_id, device_id="dev-east-004", sequence=6081)
    _exec(
        root,
        "INSERT INTO processing_effects(consumer_name,event_id,effect_key,region,generation,origin_sequence,"
        "effect_type,effect_payload,effect_sha256,status,prepared_at,committed_at,worker_id,fence_epoch) "
        "VALUES('telemetry-indexer',?,'idx:'||?, 'east',1,6081,'SEARCH_INDEX','{}',"
        "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','COMMITTED',"
        "'2026-08-08T19:01:00Z','2026-08-08T19:01:00Z','prior',0)",
        (event_id, event_id),
    )
    assert _run(root, ["publish", event_id]).returncode == 0
    for _ in range(12):
        _run(
            root,
            ["run-consumer", "telemetry-indexer", "--worker", "w2", "--epoch", "0", "--max-messages", "50"],
        )
        time.sleep(0.25)
    rows = _sql(
        root,
        "SELECT COUNT(*) AS n FROM processing_effects WHERE consumer_name='telemetry-indexer' AND event_id=?",
        (event_id,),
    )
    assert rows[0]["n"] == 1
    status = _sql(
        root,
        "SELECT status FROM processing_effects WHERE consumer_name='telemetry-indexer' AND event_id=?",
        (event_id,),
    )[0]
    assert status["status"] == "COMMITTED"


def test_f2p_quarantined_device_does_not_complete_effect(live_lab: Path, tmp_path: Path) -> None:
    """Poison input from a quarantined device is recorded without a completed business effect."""
    root = _workspace(tmp_path)
    event_id = "evt-east-g01-006082"
    _insert_event(root, event_id=event_id, device_id="dev-east-001", sequence=6082)
    assert _run(root, ["publish", event_id]).returncode == 0
    _await_effect(root, event_id)
    poison = _sql(
        root,
        "SELECT disposition FROM poison_events WHERE consumer_name='telemetry-indexer' AND event_id=?",
        (event_id,),
    )
    assert poison and poison[0]["disposition"] == "QUARANTINED"
    effects = _sql(
        root,
        "SELECT COUNT(*) AS n FROM processing_effects WHERE consumer_name='telemetry-indexer' AND event_id=? AND status='COMMITTED'",
        (event_id,),
    )
    assert effects[0]["n"] == 0


def test_f2p_checkpoint_does_not_advance_on_quarantine(live_lab: Path, tmp_path: Path) -> None:
    """Quarantine is not counted as completed application progress for that event."""
    root = _workspace(tmp_path)
    event_id = "evt-east-g01-006083"
    _insert_event(root, event_id=event_id, device_id="dev-east-001", sequence=6083)
    before = _sql(
        root,
        "SELECT last_effect_sequence FROM consumer_checkpoints WHERE consumer_name='telemetry-indexer' AND region='east'",
    )
    prior = 0 if not before else int(before[0]["last_effect_sequence"])
    assert _run(root, ["publish", event_id]).returncode == 0
    _await_effect(root, event_id)
    after = _sql(
        root,
        "SELECT last_effect_sequence FROM consumer_checkpoints WHERE consumer_name='telemetry-indexer' AND region='east'",
    )
    observed = 0 if not after else int(after[0]["last_effect_sequence"])
    assert observed == prior or observed < 6083
