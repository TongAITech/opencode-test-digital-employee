from pathlib import Path

import pytest

from rc6_runtime.authority import AuthorityError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_capability_broker import (
    CapabilityBroker,
    CapabilityDecision,
    CapabilityPolicyRule,
)
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


def _setup(tmp_path: Path, *, native=False):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-center",
            business_scenario="guarantor creation",
            business_rule="required fields persist",
            risk_level="HIGH",
            test_level="L3",
            code_slice_refs=["Service#create"],
            oracle_refs=["HTTP", "DB"],
        )
    )
    repo.persist(
        ExecutionTaskUnit(
            etu_id="ETU-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-1"],
            primary_goal="execute TC-1",
            primary_code_slice="Service#create",
            test_level="L3",
            primary_oracle="HTTP+DB",
            data_domain="guarantor",
            primary_tool_family="api",
            planning_snapshot_ref="PLAN-1",
            cohesion_score=1.0,
            cohesion_explanation="single high-risk case",
            required_capabilities=["tool:api"],
            estimated_duration_minutes=5,
            estimated_cost=1.0,
        )
    )
    append_entity(
        truth,
        Task(
            task_id="WI-1",
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="ETU_EXECUTION",
            objective="execute ETU-1",
            required_capabilities=["api"],
            input_artifact_refs=["ETU-1"],
            acceptance_criteria=["evidence persisted"],
        ),
        release_id="RC7.2",
    )

    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    authority = (RC72AuthorityRuntime if native else RC7AuthorityRuntime)(b"0123456789abcdef0123456789abcdef")
    identity = authority.issue_identity(
        "L3_EXECUTE" if native else "RC7_EXECUTION_WORKER",
        "EXECUTION",
        None,
        0,
        "DSH-SESSION-1",
    )
    base_lease = authority.issue_lease(
        identity.worker_id,
        "task:WI-1",
        [] if native else ["rc7_execution_candidate"],
        ["mcp__pfc_aitest_rc7__truth_query"],
        ttl_seconds=1800,
    )
    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-1",
            mission_id="M-1",
            etu_id="ETU-1",
            workitem_id="WI-1",
            case_id="TC-1",
            attempt_id="ATT-1",
            worker_id=identity.worker_id,
            session_id="DSH-SESSION-1",
            task_lease_ref=base_lease.lease_id,
            state=WorkItemAttemptState.PREPARED,
        )
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

    with pytest.raises(Exception, match="CAPABILITY_REQUEST_ATTEMPT_BINDING_MISMATCH"):
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


def test_same_request_replay_does_not_issue_or_write_again_and_conflicts_are_rejected(tmp_path, monkeypatch):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    capability = 'mcp__pfc_aitest_rc7__attempt_cat_query'
    result = _request(broker, identity, parent, capability)
    before = truth.store.path.read_bytes()
    count = len(authority._leases)
    assert _request(broker, identity, parent, capability) == result
    assert len(authority._leases) == count and truth.store.path.read_bytes() == before
    with pytest.raises(Exception, match='REPLAY_CONFLICT'):
        _request(broker, identity, parent, 'different-tool')
    assert truth.store.path.read_bytes() == before


def test_observed_grant_survives_lost_metadata_response_without_duplicate_issuance(tmp_path, monkeypatch):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    original = broker._append
    def interrupt(event, payload):
        if event == 'RC72_CAPABILITY_DECISION_UPSERTED':
            raise RuntimeError('interrupted metadata projection')
        return original(event, payload)
    monkeypatch.setattr(broker, '_append', interrupt)
    capability = 'mcp__pfc_aitest_rc7__attempt_cat_query'
    with pytest.raises(RuntimeError, match='interrupted metadata'):
        _request(broker, identity, parent, capability)
    child_count = len(authority._leases)
    assert truth.query('rc72_capability_resolution')[0]['state'] == 'OBSERVED'
    monkeypatch.setattr(broker, '_append', original)
    result = _request(broker, identity, parent, capability)
    assert result.signed_task_lease_id and len(authority._leases) == child_count
    assert len(truth.query('rc72_capability_lease')) == 1


def test_unknown_issuance_never_reissues_even_after_lock_file_loss(tmp_path, monkeypatch):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    issue = authority.issue_lease
    calls = []
    def lost_response(*args, **kwargs):
        calls.append(issue(*args, **kwargs))
        raise RuntimeError('lost authority issuance response')
    monkeypatch.setattr(authority, 'issue_lease', lost_response)
    capability = 'mcp__pfc_aitest_rc7__attempt_cat_query'
    with pytest.raises(RuntimeError, match='lost authority'):
        _request(broker, identity, parent, capability)
    assert truth.query('rc72_capability_resolution')[0]['state'] == 'ISSUING'
    for lock in truth.store.path.with_suffix('.capability-locks').iterdir():
        lock.unlink()
    monkeypatch.setattr(authority, 'issue_lease', issue)
    with pytest.raises(Exception, match='ISSUANCE_EFFECT_UNKNOWN'):
        _request(broker, identity, parent, capability)
    assert len(calls) == 1 and truth.query('rc72_capability_decision') == []


def test_native_cold_child_restore_requires_live_parent_and_signed_resolution(tmp_path):
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    capability = 'mcp__pfc_aitest_rc7__attempt_cat_query'
    result = _request(broker, identity, parent, capability)
    cold = RC72AuthorityRuntime(b'0123456789abcdef0123456789abcdef')
    cold.restore_signed_worker_lease(identity, parent, expected_scope=parent.scope_ref)
    replay = CapabilityBroker(TruthRuntime(truth.store.path), release_id='RC7.2', authority=cold, policies={})
    before = truth.store.path.read_bytes()
    assert _request(replay, identity, parent, capability) == result
    assert result.signed_task_lease_id not in cold._leases
    replay.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
        mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)
    assert result.signed_task_lease_id in cold._leases
    assert truth.store.path.read_bytes() == before
    replay.revoke(result.capability_lease_id, reason='task completed')
    assert _request(replay, identity, parent, capability) == result
    with pytest.raises(Exception, match='NOT_ACTIVE'):
        replay.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
            mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)
    assert replay.truth.query('rc72_capability_lease')[0]['state'] == 'REVOKED'


def test_revoked_parent_blocks_child_even_when_child_itself_is_not_revoked(tmp_path):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    result = _request(broker, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    authority.revoke_worker_lease(parent.lease_id)
    with pytest.raises(AuthorityError):
        broker.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
            mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)


def test_resolution_signature_tamper_cannot_restore_a_child(tmp_path):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    result = _request(broker, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    row = truth.query('rc72_capability_resolution')[0]
    row['signature'] = '0' * 64
    row['artifact_version'] += 1
    truth.append_atomic('RC72_CAPABILITY_RESOLUTION_UPSERTED', row)
    before = truth.store.path.read_bytes()
    with pytest.raises(Exception, match='SIGNATURE_INVALID'):
        broker.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
            mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)
    assert truth.store.path.read_bytes() == before


def test_signed_revocation_blocks_cold_restore_even_if_metadata_write_was_interrupted(tmp_path, monkeypatch):
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    result = _request(broker, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    append = truth.append_atomic
    def interrupt(event, payload):
        if event == 'RC72_CAPABILITY_LEASE_UPSERTED' and payload['state'] == 'REVOKED':
            raise RuntimeError('lost revoke projection')
        return append(event, payload)
    monkeypatch.setattr(truth, 'append_atomic', interrupt)
    with pytest.raises(RuntimeError, match='lost revoke'):
        broker.revoke(result.capability_lease_id, reason='boundary closed')
    monkeypatch.setattr(truth, 'append_atomic', append)
    cold = RC72AuthorityRuntime(b'0123456789abcdef0123456789abcdef')
    cold.restore_signed_worker_lease(identity, parent, expected_scope=parent.scope_ref)
    replay = CapabilityBroker(TruthRuntime(truth.store.path), release_id='RC7.2', authority=cold, policies={})
    with pytest.raises(Exception, match='CHILD_REVOKED'):
        replay.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
            mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)
    assert result.signed_task_lease_id not in cold._leases
    replay.revoke(result.capability_lease_id, reason='resume original revoke')
    assert replay.truth.query('rc72_capability_lease')[0]['state'] == 'REVOKED'


def test_concurrent_native_requests_cannot_duplicate_child_authority(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    entered, release = Event(), Event()
    issue = authority.issue_lease
    calls = []
    def held_issue(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        calls.append(issue(*args, **kwargs))
        return calls[-1]
    monkeypatch.setattr(authority, 'issue_lease', held_issue)
    capability = 'mcp__pfc_aitest_rc7__attempt_cat_query'
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(_request, broker, identity, parent, capability)
        assert entered.wait(5)
        try:
            with pytest.raises(Exception, match='REQUEST_IN_PROGRESS'):
                _request(broker, identity, parent, capability)
        finally:
            release.set()
        result = first.result(timeout=5)
    assert len(calls) == 1
    assert _request(broker, identity, parent, capability) == result
    assert len(truth.query('rc72_capability_lease')) == 1


def test_fresh_process_bootstrap_can_read_signed_capability_resolution(tmp_path):
    import json
    import subprocess
    import sys
    truth, _, identity, parent, broker = _setup(tmp_path, native=True)
    _request(broker, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    code = '''import json,sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
print(json.dumps({kind: len(truth.query(kind)) for kind in ('rc72_capability_resolution','rc72_capability_lease','rc72_capability_decision')}))
'''
    result = subprocess.run([sys.executable, '-c', code, str(truth.store.path)],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == dict(rc72_capability_resolution=1, rc72_capability_lease=1, rc72_capability_decision=1)


def test_broker_cannot_issue_against_a_different_release_binding(tmp_path):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    foreign = CapabilityBroker(truth, release_id='OTHER-RELEASE', authority=authority, policies=broker.policies)
    before = truth.store.path.read_bytes()
    with pytest.raises(Exception, match='ATTEMPT_BINDING_MISMATCH'):
        _request(foreign, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    assert truth.store.path.read_bytes() == before and len(authority._leases) == 1


def test_capability_use_refreshes_a_binding_superseded_by_another_runtime(tmp_path):
    truth, authority, identity, parent, broker = _setup(tmp_path, native=True)
    result = _request(broker, identity, parent, 'mcp__pfc_aitest_rc7__attempt_cat_query')
    other = TruthRuntime(truth.store.path)
    binding = other.query('rc72_workitem_attempt_binding')[0]
    other.append_atomic('RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED',
        dict(binding, state='SUPERSEDED', artifact_version=binding['artifact_version'] + 1))
    with pytest.raises(Exception, match='ATTEMPT_NOT_ACTIVE'):
        broker.assert_capability_lease_usable(capability_lease_id=result.capability_lease_id,
            mission_id='M-1', workitem_id='WI-1', attempt_id='ATT-1', worker_id=identity.worker_id)
