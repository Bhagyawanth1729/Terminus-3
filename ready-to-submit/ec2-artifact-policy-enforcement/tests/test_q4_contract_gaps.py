from __future__ import annotations

import copy

from verifier_lib import (
    base_policy,
    case_dir,
    exception_for,
    find_digest,
    issue_clean_permit,
    make_request,
    run_evaluate,
    run_verify,
    trusted_source,
)


def test_f2p_exact_exception_cannot_override_untrusted_source():
    """An exact vulnerability exception cannot waive the trusted-source prerequisite."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=True)
        req = make_request("req-ex-source-order", "package", "apt", digest, "attacker.invalid/repo")
        ex = exception_for(req)
        cp, out, _ = run_evaluate(root, req, policy=policy, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_UNTRUSTED_SOURCE"


def test_p2p_permit_request_id_mismatch_remains_invalid():
    """Changing request_id must continue to invalidate an otherwise intact permit."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        changed = copy.deepcopy(req)
        changed["request_id"] = req["request_id"] + "-different"
        cp, out = run_verify(permit, changed, policy, b"verifier-secret-a", work=root / "verify")
        assert cp.returncode == 43 and out["valid"] is False


def test_p2p_permit_policy_version_mismatch_remains_invalid():
    """Changing policy version must continue to invalidate an otherwise intact permit."""
    with case_dir() as root:
        permit, req, policy = issue_clean_permit(root / "issue")
        changed_policy = copy.deepcopy(policy)
        changed_policy["version"] = policy["version"] + "-different"
        cp, out = run_verify(permit, req, changed_policy, b"verifier-secret-a", work=root / "verify")
        assert cp.returncode == 43 and out["valid"] is False


def test_p2p_wrong_exception_policy_code_remains_non_authorizing():
    """An exception for another policy code must not waive vulnerability threshold denial."""
    with case_dir() as root:
        policy = base_policy()
        digest = find_digest(vulnerable=True)
        req = make_request("req-ex-code", "package", "apt", digest, trusted_source("package", policy))
        ex = exception_for(req, codes=["SOURCE_POLICY"])
        cp, out, _ = run_evaluate(root, req, policy=policy, exceptions={"exceptions": [ex]})
        assert cp.returncode == 42 and out["code"] == "DENY_VULNERABLE"
