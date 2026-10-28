from pathlib import Path

import pytest

from rc6_runtime.authority import AuthorityError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.rc72_capability_broker import (
    CapabilityBroker,
    CapabilityDecision,
    CapabilityPolicyRule,
)


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    authority = RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    identity = authority.issue_identity(
        "RC7_EXECUTION_WORKER",
        "EXECUTION",
        None,
        0,
        "DSH-SESSION-1",
    )
    base_lease = authority.issue_lease(
        identity.worker_id,
        "task:WI-1",
        ["rc7_execution_candidate"],
        ["mcp__pfc_aitest_rc7__truth_query"],
        ttl_seconds=1800,
    )
    broker = CapabilityBroker(
        truth,
        release_id="RC7.2",
        authority=authority,
        policies={
            "mcp__pfc_aitest_rc7__attempt_cat_query": CapabilityPolicyRule(
                decision=CapabilityDecision.AUTO_GRANT_TEMP_LEASE,
                max_ttl_seconds=120,
            ),
            "mcp__pfc_aitest_rc7__database_write": CapabilityPolicyRule(
                decision=CapabilityDecision.DELEGATE_TO_SPECIALIST,
                delegate_role="RC7_PREPARATION_WORKER",
            ),
            "mcp__pfc_aitest_rc7__production_mutation": CapabilityPolicyRule(
                decision=CapabilityDecision.HUMAN_GATE,
            ),
            "mcp__pfc_aitest_rc7__forbidden_tool": CapabilityPolicyRule(
                decision=CapabilityDecision.DENY,
            ),
        },
    )
    return truth, authority, identity, base_lease, broker


def _request(broker, identity, base_lease, capability, request_id="CAPREQ-1"):
    return broker.request(
        request_id=request_id,
        mission_id="M-1",
        workitem_id="WI-1",
        attempt_id="ATT-1",
        worker_id=identity.worker_id,
        parent_task_lease_id=base_lease.lease_id,
        requested_capability=capability,
        reason="required by executable contract evidence path",
    )


def test_strict_worker_cannot_use_missing_capability_before_broker_grant(tmp_path: Path):
    _, authority, identity, base_lease, _ = _setup(tmp_path)
    with pytest.raises(AuthorityError, match="LEASE_TOOL_FORBIDDEN"):
        authority.authorize_tool(
            identity.worker_id,
            base_lease.lease_id,
            "mcp__pfc_aitest_rc7__attempt_cat_query",
        )


def test_safe_capability_creates_exact_temporary_signed_child_lease_and_audit_truth(tmp_path: Path):
    truth, authority, identity, base_lease, broker = _setup(tmp_path)
    result = _request(
        broker,
        identity,
        base_lease,
        "mcp__pfc_aitest_rc7__attempt_cat_query",
    )

    assert result.decision == CapabilityDecision.AUTO_GRANT_TEMP_LEASE
    assert result.capability_lease_id
    audit = truth.query("rc72_capability_request", request_id="CAPREQ-1")[0]
    assert audit["mission_id"] == "M-1"
    assert audit["workitem_id"] == "WI-1"
    assert audit["attempt_id"] == "ATT-1"
    assert audit["worker_id"] == identity.worker_id
    assert audit["requested_capability"] == "mcp__pfc_aitest_rc7__attempt_cat_query"
    assert audit["parent_task_lease_id"] == base_lease.lease_id
    assert audit["reason"]

    cap = truth.query("rc72_capability_lease", capability_lease_id=result.capability_lease_id)[0]
    assert cap["parent_task_lease_id"] == base_lease.lease_id
    assert cap["workitem_id"] == "WI-1"
    assert cap["attempt_id"] == "ATT-1"
    assert cap["worker_id"] == identity.worker_id
    assert cap["requested_capability"] == "mcp__pfc_aitest_rc7__attempt_cat_query"
    assert cap["expires_at"] > cap["issued_at"]
    assert cap["expires_at"] - cap["issued_at"] <= 120
    assert cap["state"] == "ACTIVE"
    assert "signature" not in cap
    assert "signing_key" not in cap
    assert "captain_token" not in cap
    assert "full_access" not in cap

    child_lease = authority.get_lease(cap["signed_task_lease_id"])
    assert child_lease.worker_id == identity.worker_id
    assert child_lease.scope_ref == "task:WI-1"
    assert set(child_lease.allowed_tools) == {
        "mcp__pfc_aitest_rc7__truth_query",
        "mcp__pfc_aitest_rc7__attempt_cat_query",
    }
    authority.authorize_tool(
        identity.worker_id,
        child_lease.lease_id,
        "mcp__pfc_aitest_rc7__attempt_cat_query",
    )


def test_wildcard_and_full_access_style_requests_are_fail_closed(tmp_path: Path):
    _, _, identity, base_lease, broker = _setup(tmp_path)
    for requested in ("*", "mcp__pfc_aitest_rc7__*", "FULL_ACCESS", "full_access"):
        with pytest.raises(Exception, match="EXACT_CAPABILITY_REQUIRED"):
            _request(broker, identity, base_lease, requested, request_id="REQ-%s" % requested)


def test_high_risk_capability_delegates_without_granting_requester(tmp_path: Path):
    truth, authority, identity, base_lease, broker = _setup(tmp_path)
    result = _request(
        broker,
        identity,
        base_lease,
        "mcp__pfc_aitest_rc7__database_write",
    )
    assert result.decision == CapabilityDecision.DELEGATE_TO_SPECIALIST
    assert result.capability_lease_id is None
    decision = truth.query("rc72_capability_decision", request_id="CAPREQ-1")[0]
    assert decision["delegate_role"] == "RC7_PREPARATION_WORKER"
    with pytest.raises(AuthorityError, match="LEASE_TOOL_FORBIDDEN"):
        authority.authorize_tool(
            identity.worker_id,
            base_lease.lease_id,
            "mcp__pfc_aitest_rc7__database_write",
        )


def test_human_gate_and_deny_issue_no_privilege(tmp_path: Path):
    truth, authority, identity, base_lease, broker = _setup(tmp_path)
    human = _request(
        broker,
        identity,
        base_lease,
        "mcp__pfc_aitest_rc7__production_mutation",
        request_id="CAPREQ-HUMAN",
    )
    denied = _request(
        broker,
        identity,
        base_lease,
        "mcp__pfc_aitest_rc7__forbidden_tool",
        request_id="CAPREQ-DENY",
    )
    assert human.decision == CapabilityDecision.HUMAN_GATE
    assert denied.decision == CapabilityDecision.DENY
    assert human.capability_lease_id is None
    assert denied.capability_lease_id is None
    assert not truth.query("rc72_capability_lease", request_id="CAPREQ-HUMAN")
    assert not truth.query("rc72_capability_lease", request_id="CAPREQ-DENY")
    with pytest.raises(AuthorityError):
        authority.authorize_tool(identity.worker_id, base_lease.lease_id, "mcp__pfc_aitest_rc7__production_mutation")


def test_child_lease_is_bound_to_worker_workitem_attempt_and_parent_lease(tmp_path: Path):
    truth, authority, identity, base_lease, broker = _setup(tmp_path)
    result = _request(broker, identity, base_lease, "mcp__pfc_aitest_rc7__attempt_cat_query")
    cap = truth.query("rc72_capability_lease", capability_lease_id=result.capability_lease_id)[0]
    child = authority.get_lease(cap["signed_task_lease_id"])

    other = authority.issue_identity("RC7_EXECUTION_WORKER", "EXECUTION", None, 0, "DSH-SESSION-2")
    with pytest.raises(AuthorityError, match="LEASE_WORKER_MISMATCH"):
        authority.authorize_tool(other.worker_id, child.lease_id, "mcp__pfc_aitest_rc7__attempt_cat_query")

    with pytest.raises(Exception, match="CAPABILITY_REQUEST_PARENT_SCOPE_MISMATCH"):
        broker.request(
            request_id="CAPREQ-WRONG-WI",
            mission_id="M-1",
            workitem_id="WI-2",
            attempt_id="ATT-1",
            worker_id=identity.worker_id,
            parent_task_lease_id=base_lease.lease_id,
            requested_capability="mcp__pfc_aitest_rc7__attempt_cat_query",
            reason="wrong workitem",
        )

    with pytest.raises(Exception, match="CAPABILITY_REQUEST_ATTEMPT_MISMATCH"):
        broker.assert_capability_lease_usable(
            capability_lease_id=result.capability_lease_id,
            mission_id="M-1",
            workitem_id="WI-1",
            attempt_id="ATT-2",
            worker_id=identity.worker_id,
        )


def test_revoke_and_expiry_fail_closed_in_authority_and_broker(tmp_path: Path):
    truth, authority, identity, base_lease, broker = _setup(tmp_path)
    result = _request(broker, identity, base_lease, "mcp__pfc_aitest_rc7__attempt_cat_query")
    cap = truth.query("rc72_capability_lease", capability_lease_id=result.capability_lease_id)[0]
    child = authority.get_lease(cap["signed_task_lease_id"])

    broker.revoke(result.capability_lease_id, reason="workitem boundary reached")
    with pytest.raises(AuthorityError, match="LEASE_REVOKED"):
        authority.authorize_tool(identity.worker_id, child.lease_id, "mcp__pfc_aitest_rc7__attempt_cat_query")
    with pytest.raises(Exception, match="CAPABILITY_LEASE_NOT_ACTIVE"):
        broker.assert_capability_lease_usable(
            capability_lease_id=result.capability_lease_id,
            mission_id="M-1",
            workitem_id="WI-1",
            attempt_id="ATT-1",
            worker_id=identity.worker_id,
        )

    result2 = _request(
        broker,
        identity,
        base_lease,
        "mcp__pfc_aitest_rc7__attempt_cat_query",
        request_id="CAPREQ-2",
    )
    cap2 = truth.query("rc72_capability_lease", capability_lease_id=result2.capability_lease_id)[0]
    child2 = authority.get_lease(cap2["signed_task_lease_id"])
    with pytest.raises(AuthorityError, match="LEASE_EXPIRED"):
        authority.authorize_tool(
            identity.worker_id,
            child2.lease_id,
            "mcp__pfc_aitest_rc7__attempt_cat_query",
            now=child2.expires_at + 1,
        )
    with pytest.raises(Exception, match="CAPABILITY_LEASE_EXPIRED"):
        broker.assert_capability_lease_usable(
            capability_lease_id=result2.capability_lease_id,
            mission_id="M-1",
            workitem_id="WI-1",
            attempt_id="ATT-1",
            worker_id=identity.worker_id,
            now=cap2["expires_at"] + 1,
        )


def test_capability_truth_survives_r1_replay_without_secrets(tmp_path: Path):
    truth, _, identity, base_lease, broker = _setup(tmp_path)
    result = _request(broker, identity, base_lease, "mcp__pfc_aitest_rc7__attempt_cat_query")
    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    req = replayed.query("rc72_capability_request", request_id="CAPREQ-1")[0]
    decision = replayed.query("rc72_capability_decision", request_id="CAPREQ-1")[0]
    lease = replayed.query("rc72_capability_lease", capability_lease_id=result.capability_lease_id)[0]
    assert req["requested_capability"] == "mcp__pfc_aitest_rc7__attempt_cat_query"
    assert decision["decision"] == "AUTO_GRANT_TEMP_LEASE"
    assert lease["state"] == "ACTIVE"
    serialized = repr((req, decision, lease)).lower()
    assert "0123456789abcdef" not in serialized
    assert "captain_token" not in serialized
    assert "signature" not in lease
