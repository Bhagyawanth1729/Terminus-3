from __future__ import annotations

import copy
import hashlib
from datetime import timedelta
import json

from verifier_lib import (
    NOW,
    ROOT,
    audit_records,
    base_policy,
    base_scans,
    case_dir,
    changed_scan,
    exception_for,
    find_digest,
    iso,
    issue_clean_permit,
    make_request,
    other_surface,
    run_evaluate,
    run_two_verifications,
    run_verify,
    trusted_source,
)


def test_f2p_dpkg_untrusted_source_rejected():
    """Direct dpkg acquisition must not bypass the package trusted-source policy."""
    with case_dir() as root:
        req = make_request("req-dpkg", "package", "dpkg", find_digest(vulnerable=False), "attacker.invalid/repo")
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 42 and out["code"] == "DENY_UNTRUSTED_SOURCE"


def test_f2p_rpm_untrusted_source_rejected():
    """Direct rpm acquisition must obey the same trusted-source policy as other packages."""
    with case_dir() as root:
        req = make_request("req-rpm", "package", "rpm", find_digest(vulnerable=False), "attacker.invalid/repo")
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 42 and out["code"] == "DENY_UNTRUSTED_SOURCE"


def test_f2p_maven_untrusted_source_rejected():
    """Maven dependency acquisition must reject a repository outside the dependency allow-list."""
    with case_dir() as root:
        req = make_request("req-maven", "dependency", "maven", find_digest(vulnerable=False), "attacker.invalid/maven")
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 42 and out["code"] == "DENY_UNTRUSTED_SOURCE"


def test_f2p_missing_digest_cannot_be_excepted():
    """An exception cannot waive the immutable-digest prerequisite for a digest-required surface."""
    with case_dir() as root:
        policy = base_policy()
        surface = next(s for s, required in policy["require_digest"].items() if required)
        manager = {"package": "apt", "container": "docker", "dependency": "maven"}[surface]
        req = make_request("req-no-digest", surface, manager, "", trusted_source(surface, policy), name="digest-required")
        exceptions = {"exceptions": [exception_for(req, digest="")]}
        cp, out, _ = run_evaluate(root, req, exceptions=exceptions)
        assert cp.returncode == 42 and out["code"] == "DENY_MISSING_DIGEST"


def test_f2p_scanner_unavailable_fails_closed():
    """Unavailable current scanner evidence must deny rather than synthesize a clean result."""
    with case_dir() as root:
        digest = find_digest(status="unavailable")
        req = make_request("req-scan-down", "package", "apt", digest, trusted_source("package"))
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 42 and out["code"] == "DENY_SCANNER_UNAVAILABLE"


def test_f2p_scanner_db_revision_mismatch_is_stale():
    """Scanner evidence from a DB revision other than the policy revision must be rejected as stale."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=False)
        scans = changed_scan(base_scans(), digest, db_revision=policy["scanner_db_revision"] + "-old")
        req = make_request("req-stale-db", "package", "apt", digest, trusted_source("package", policy))
        cp, out, _ = run_evaluate(root, req, policy=policy, scans=scans)
        assert cp.returncode == 42 and out["code"] == "DENY_SCANNER_EVIDENCE_STALE"


def test_f2p_mutable_name_digest_change_invalidates_cache():
    """Reusing the same mutable name/version with a different digest must not reuse old clean evidence."""
    with case_dir() as root:
        policy = base_policy()
        clean = find_digest(vulnerable=False)
        vulnerable = find_digest(vulnerable=True)
        state = root / "state"
        req1 = make_request("req-tag-a", "container", "docker", clean, trusted_source("container", policy), name="service", version="stable")
        cp1, out1, _ = run_evaluate(root / "a", req1, state=state)
        assert cp1.returncode == 0 and out1["cache_hit"] is False
        req2 = make_request("req-tag-b", "container", "docker", vulnerable, trusted_source("container", policy), name="service", version="stable")
        cp2, out2, _ = run_evaluate(root / "b", req2, state=state)
        assert cp2.returncode == 42 and out2["code"] == "DENY_VULNERABLE" and out2["cache_hit"] is False


def test_f2p_policy_version_change_invalidates_cache():
    """A policy-version change must force current evidence instead of reusing an older policy cache entry."""
    with case_dir() as root:
        policy1 = base_policy()
        digest = find_digest(vulnerable=False)
        state = root / "state"
        req = make_request("req-policy-a", "package", "apt", digest, trusted_source("package", policy1), name="policy-cache")
        cp1, out1, _ = run_evaluate(root / "a", req, state=state, policy=policy1)
        assert cp1.returncode == 0 and out1["cache_hit"] is False
        policy2 = copy.deepcopy(policy1)
        policy2["version"] = policy1["version"] + "-next"
        scans2 = changed_scan(base_scans(), digest, vulnerable=True)
        req["request_id"] = "req-policy-b"
        cp2, out2, _ = run_evaluate(root / "b", req, state=state, policy=policy2, scans=scans2)
        assert cp2.returncode == 42 and out2["code"] == "DENY_VULNERABLE" and out2["cache_hit"] is False


def test_f2p_scanner_revision_change_invalidates_cache():
    """Changing the policy scanner DB revision must invalidate evidence cached under the prior revision."""
    with case_dir() as root:
        policy1 = base_policy()
        digest = find_digest(vulnerable=False)
        state = root / "state"
        req = make_request("req-db-a", "package", "apt", digest, trusted_source("package", policy1), name="db-cache")
        cp1, out1, _ = run_evaluate(root / "a", req, state=state, policy=policy1)
        assert cp1.returncode == 0 and out1["cache_hit"] is False
        policy2 = copy.deepcopy(policy1)
        policy2["scanner_db_revision"] = policy1["scanner_db_revision"] + "-next"
        scans2 = changed_scan(base_scans(), digest, db_revision=policy2["scanner_db_revision"], vulnerable=True)
        req["request_id"] = "req-db-b"
        cp2, out2, _ = run_evaluate(root / "b", req, state=state, policy=policy2, scans=scans2)
        assert cp2.returncode == 42 and out2["code"] == "DENY_VULNERABLE" and out2["cache_hit"] is False


def test_f2p_cache_ttl_expiry_forces_scanner_recheck():
    """Expired cached evidence must not hide a scanner outage after its TTL boundary."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=False)
        state = root / "state"
        req = make_request("req-ttl-a", "package", "apt", digest, trusted_source("package", policy), name="ttl-cache")
        cp1, out1, _ = run_evaluate(root / "a", req, state=state, policy=policy)
        assert cp1.returncode == 0 and out1["cache_hit"] is False
        scans2 = changed_scan(base_scans(), digest, status="unavailable")
        req["request_id"] = "req-ttl-b"
        later = NOW + timedelta(seconds=int(policy["cache_ttl_seconds"]) + 1)
        cp2, out2, _ = run_evaluate(root / "b", req, state=state, policy=policy, scans=scans2, now=later)
        assert cp2.returncode == 42 and out2["code"] == "DENY_SCANNER_UNAVAILABLE"


def test_f2p_expired_exception_is_ignored():
    """An otherwise exact vulnerability exception must stop authorizing at its expiry boundary."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=True)
        req = make_request("req-ex-expired", "package", "apt", digest, trusted_source("package", policy))
        ex = exception_for(req, expires=iso(NOW - timedelta(seconds=1)))
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_VULNERABLE"


def test_f2p_exception_same_name_wrong_digest_is_rejected():
    """Artifact name equality cannot let an exception authorize a different immutable digest."""
    with case_dir() as root:
        policy = base_policy()
        vulnerable = find_digest(vulnerable=True)
        clean = find_digest(vulnerable=False)
        req = make_request("req-ex-digest", "package", "apt", vulnerable, trusted_source("package", policy), name="shared-name")
        ex = exception_for(req, digest=clean, name="shared-name")
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_VULNERABLE"


def test_f2p_exception_wrong_surface_is_rejected():
    """A vulnerability exception issued for another acquisition surface must not apply cross-surface."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=True)
        req = make_request("req-ex-surface", "container", "docker", digest, trusted_source("container", policy))
        ex = exception_for(req, surfaces=[other_surface(req["surface"])])
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_VULNERABLE"


def test_f2p_exception_wrong_environment_is_rejected():
    """An exception scoped to another environment must not authorize the current environment."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=True)
        req = make_request("req-ex-env", "package", "apt", digest, trusted_source("package", policy), environment="staging")
        ex = exception_for(req, environments=["production"])
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_VULNERABLE"


def test_f2p_exception_cannot_override_scanner_unavailable():
    """Even an exact current exception cannot waive the requirement for current scanner evidence."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(status="unavailable")
        req = make_request("req-ex-scan", "package", "apt", digest, trusted_source("package", policy))
        ex = exception_for(req)
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_SCANNER_UNAVAILABLE"


def test_f2p_permit_rejected_with_different_secret():
    """A permit authenticated under one host secret must fail verification under a different secret."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue", secret=b"secret-one")
        cp, out = run_verify(permit, req, policy, b"secret-two", work=root / "verify")
        assert cp.returncode == 43 and out["valid"] is False


def test_f2p_permit_signature_depends_on_secret():
    """Identical permit fields signed with different host secrets must not produce the same authenticator."""
    with case_dir() as root:
        permit1, _, _ = issue_clean_permit(root / "one", secret=b"secret-one", request_id="req-same", instance="i-same")
        permit2, _, _ = issue_clean_permit(root / "two", secret=b"secret-two", request_id="req-same", instance="i-same")
        assert permit1["signature"] != permit2["signature"]


def test_f2p_permit_instance_binding_is_enforced():
    """A valid permit must not authorize the same request and digest on another EC2 instance."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        changed = copy.deepcopy(req)
        changed["instance_id"] = "i-different"
        cp, out = run_verify(permit, changed, policy, b"verifier-secret-a", work=root / "verify")
        assert cp.returncode == 43 and out["valid"] is False


def test_f2p_stateful_permit_first_use_is_valid():
    """The stable verifier CLI must accept the first exact-scope permit use while recording durable consumption state."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        cp, out = run_verify(permit, req, policy, b"verifier-secret-a", work=root / "verify", state=root / "replay")
        assert cp.returncode == 0 and out["valid"] is True


def test_f2p_permit_replay_is_rejected_after_restart():
    """A permit consumed by one verifier process must be rejected by a later process using the same durable state."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        state = root / "replay"
        first, first_out = run_verify(permit, req, policy, b"verifier-secret-a", work=root / "first", state=state)
        assert first.returncode == 0 and first_out["valid"] is True
        second, second_out = run_verify(permit, req, policy, b"verifier-secret-a", work=root / "second", state=state)
        assert second.returncode == 43 and second_out["valid"] is False and second_out["code"] == "PERMIT_REPLAYED"


def test_f2p_concurrent_permit_replay_has_single_winner():
    """Concurrent verification of one single-use permit must yield one success and one replay rejection."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        results = run_two_verifications(permit, req, policy, b"verifier-secret-a", root / "replay", root / "verify")
        codes = sorted(cp.returncode for cp, _ in results)
        outcomes = sorted(out["code"] for _, out in results)
        assert codes == [0, 43]
        assert outcomes == ["PERMIT_REPLAYED", "PERMIT_VALID"]


def test_f2p_deny_decision_is_durably_journaled():
    """A policy denial must appear in the durable audit journal before evaluate returns its denial."""
    with case_dir() as root:
        policy = base_policy()
        req = make_request("req-deny-audit", "package", "apt", find_digest(vulnerable=False), "attacker.invalid/repo")
        state = root / "state"
        cp, out, _ = run_evaluate(root / "run", req, state=state, policy=policy)
        assert cp.returncode == 42
        records = audit_records(state)
        assert records and records[-1]["request_id"] == req["request_id"] and records[-1]["decision"] == "DENY"


def test_f2p_deny_projection_matches_durable_journal():
    """After a denied evaluation, last-decision must agree with the newest durable audit record."""
    with case_dir() as root:
        req = make_request("req-deny-projection", "package", "apt", find_digest(vulnerable=False), "attacker.invalid/repo")
        state = root / "state"
        cp, _, _ = run_evaluate(root / "run", req, state=state)
        assert cp.returncode == 42
        last = json.loads((state / "last-decision.json").read_text())
        records = audit_records(state)
        assert records and last["decision_id"] == records[-1]["decision_id"]


def test_f2p_valid_unterminated_audit_record_survives_recovery():
    """Recovery must preserve a complete final audit record even when its trailing newline was not durable."""
    with case_dir() as root:
        digest = find_digest(vulnerable=False)
        source = trusted_source("package")
        state = root / "state"
        req1 = make_request("req-tail-valid-a", "package", "apt", digest, source)
        cp1, _, _ = run_evaluate(root / "a", req1, state=state)
        assert cp1.returncode == 0
        path = state / "audit.jsonl"
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        req2 = make_request("req-tail-valid-b", "package", "apt", digest, source)
        cp2, _, _ = run_evaluate(root / "b", req2, state=state)
        assert cp2.returncode == 0
        assert [record["request_id"] for record in audit_records(state)] == [req1["request_id"], req2["request_id"]]


def test_f2p_interior_audit_corruption_fails_closed():
    """Durable interior audit corruption must stop a new decision instead of silently extending corrupted history."""
    with case_dir() as root:
        digest = find_digest(vulnerable=False)
        source = trusted_source("package")
        state = root / "state"
        req1 = make_request("req-corrupt-a", "package", "apt", digest, source)
        cp1, _, _ = run_evaluate(root / "a", req1, state=state)
        assert cp1.returncode == 0
        with (state / "audit.jsonl").open("ab") as fh:
            fh.write(b'{"broken":\n')
        req2 = make_request("req-corrupt-b", "package", "apt", digest, source)
        cp2, _, _ = run_evaluate(root / "b", req2, state=state)
        assert cp2.returncode == 2


def test_f2p_identical_retry_does_not_duplicate_audit_decision():
    """Repeating the same deterministic evaluation must not create a duplicate durable decision record."""
    with case_dir() as root:
        digest = find_digest(vulnerable=False)
        req = make_request("req-idempotent", "package", "apt", digest, trusted_source("package"))
        state = root / "state"
        cp1, out1, _ = run_evaluate(root / "a", req, state=state)
        cp2, out2, _ = run_evaluate(root / "b", req, state=state)
        assert cp1.returncode == 0 and cp2.returncode == 0
        assert out1["decision_id"] == out2["decision_id"]
        assert len(audit_records(state)) == 1


def test_f2p_corrupt_cache_does_not_become_clean_evidence():
    """A malformed cache entry must be treated as unusable evidence and cannot mask a scanner outage."""
    with case_dir() as root:
        digest = find_digest(vulnerable=False)
        req = make_request("req-cache-corrupt-a", "package", "apt", digest, trusted_source("package"), name="cache-corrupt")
        state = root / "state"
        cp1, _, _ = run_evaluate(root / "a", req, state=state)
        assert cp1.returncode == 0
        entries = list((state / "cache").glob("*.json"))
        assert len(entries) == 1
        entries[0].write_text('{"partial":')
        scans = changed_scan(base_scans(), digest, status="unavailable")
        req["request_id"] = "req-cache-corrupt-b"
        cp2, out2, _ = run_evaluate(root / "b", req, state=state, scans=scans)
        assert cp2.returncode == 42 and out2["code"] == "DENY_SCANNER_UNAVAILABLE"


def test_p2p_trusted_clean_package_remains_allowed():
    """A trusted digest-pinned clean package remains an ordinary allowed acquisition."""
    with case_dir() as root:
        req = make_request("req-p2p-package", "package", "apt", find_digest(vulnerable=False), trusted_source("package"))
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 0 and out["decision"] == "ALLOW"


def test_p2p_trusted_clean_container_remains_allowed():
    """A trusted digest-pinned clean container remains allowed through the shared policy path."""
    with case_dir() as root:
        req = make_request("req-p2p-container", "container", "docker", find_digest(vulnerable=False), trusted_source("container"))
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 0 and out["decision"] == "ALLOW"


def test_p2p_exact_current_exception_remains_allowed():
    """A current exact-scope vulnerability exception still authorizes its intended vulnerable artifact."""
    with case_dir() as root:
        digest = find_digest(vulnerable=True)
        req = make_request("req-p2p-exception", "package", "apt", digest, trusted_source("package"))
        ex = exception_for(req)
        cp, out, _ = run_evaluate(root, req, exceptions={"exceptions": [ex]})
        assert cp.returncode == 0 and out["code"] == "ALLOW_EXCEPTION"


def test_p2p_ordinary_untrusted_apt_remains_denied():
    """The already-enforced normal apt source rejection remains a policy denial with exit 42."""
    with case_dir() as root:
        req = make_request("req-p2p-untrusted", "package", "apt", find_digest(vulnerable=False), "attacker.invalid/repo")
        cp, out, _ = run_evaluate(root, req)
        assert cp.returncode == 42 and out["code"] == "DENY_UNTRUSTED_SOURCE"


def test_p2p_expired_permit_remains_invalid():
    """An otherwise authentic permit remains invalid once its expiry time has passed."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        expiry = NOW + timedelta(seconds=int(policy["permit_ttl_seconds"]) + 1)
        cp, out = run_verify(permit, req, policy, b"verifier-secret-a", work=root / "verify", now=expiry)
        assert cp.returncode == 43 and out["valid"] is False


def test_p2p_permit_digest_mismatch_remains_invalid():
    """A permit must continue rejecting a request whose immutable artifact digest differs from its signed scope."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        changed = copy.deepcopy(req)
        changed["digest"] = find_digest(vulnerable=True)
        cp, out = run_verify(permit, changed, policy, b"verifier-secret-a", work=root / "verify")
        assert cp.returncode == 43 and out["valid"] is False

def test_p2p_current_cache_entry_remains_operational():
    """A current exact cache entry remains usable instead of disabling the cache as a workaround."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=False)
        state = root / "state"
        req = make_request("req-p2p-cache-a", "package", "apt", digest, trusted_source("package", policy), name="cache-preserve")
        cp1, out1, _ = run_evaluate(root / "a", req, state=state, policy=policy)
        assert cp1.returncode == 0 and out1["cache_hit"] is False
        req["request_id"] = "req-p2p-cache-b"
        scans2 = changed_scan(base_scans(), digest, status="unavailable")
        cp2, out2, _ = run_evaluate(root / "b", req, state=state, policy=policy, scans=scans2)
        assert cp2.returncode == 0 and out2["decision"] == "ALLOW" and out2["cache_hit"] is True


def test_p2p_valid_stateless_permit_remains_valid():
    """The existing stateless verify-permit path still accepts an exact unexpired permit."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        cp, out = run_verify(permit, req, policy, b"verifier-secret-a", work=root / "verify")
        assert cp.returncode == 0 and out["valid"] is True and out["code"] == "PERMIT_VALID"


def test_p2p_supplied_policy_scanner_exception_fixtures_remain_unchanged():
    """The shipped policy, scanner, and exception fixtures remain byte-for-byte unchanged."""
    expected = {
        "config/policy.json": "d5c9673e074c72bf2dfd0b1a5d7a868145ccee4d405927819e41f22e83aa6ea8",
        "fixtures/scans.json": "f8f969cc35cd6f4e7e80eff6628311ba5d63e8fd06f010b9ebd1d786d53d3e5c",
        "fixtures/exceptions.json": "f188638bac295f3601107ef74cbaeeef69d0bcea84c1c234aa8da35fb2d1043b",
    }
    for rel, digest in expected.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest
