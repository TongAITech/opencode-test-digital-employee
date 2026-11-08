"""GAP-01 N6-native script-ready signed producer and Field HOLD regressions."""
from dataclasses import replace
import time

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_script_ready_gate import NativeScriptReadyGateProducer
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc7_release.rc72_captain_host_reentry import (
    ObservedDshCaptain, reenter_host_captain,
)
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n6_executable_readiness import NOW
from test_rc72_n7_execution_admission import _ready


def _producer(truth, signer=None):
    return NativeScriptReadyGateProducer(
        truth, release_id=RELEASE, source_commit=COMMIT,
        authority=signer, now=NOW)


def _captain(truth):
    host_key = RC72AuthorityRuntime(b'isolated-test-dsh-host-observer')
    lease = CaptainDispatchFencer(truth, release_id=RELEASE).acquire_initial(
        mission_id=MISSION, team_id='FIELD-AGENTTEAMS-A',
        captain_session_id='FIELD-ACTUAL-OBSERVED-DSH-A', ttl_seconds=300)
    ticket = ObservedDshCaptain(
        release_id=RELEASE, source_commit=COMMIT, release_batch_id=BATCH,
        mission_id=MISSION, team_id=lease['team_id'],
        captain_session_id=lease['captain_session_id'],
        captain_lease_id=lease['lease_id'], captain_generation=lease['generation'],
        dsh_session_ref='dsh://agent-teams/actual-host-observation',
        observed_at=int(time.time()), state='ACTIVE', signature='PENDING')
    ticket = replace(ticket, signature=host_key._sign(ticket.signed_fields()))
    return reenter_host_captain(
        truth, release_id=RELEASE, source_commit=COMMIT, release_batch_id=BATCH,
        observed=ticket, host_authority=host_key,
        role_profiles={'L3_EXECUTE': ('api_http',)},
        approved_capabilities=('api_http',))


def test_native_n6_gate_requires_explicit_host_signature_even_after_n6_pass(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    before = truth.store.path.read_bytes()
    result = _producer(truth).inspect(release_batch_id=BATCH)
    assert result['status'] == 'HOLD'
    assert result['reason'] == 'SCRIPT_READY_CURRENT_CAPTAIN_REQUIRED'
    assert not truth.query('rc72_script_ready_admission')
    assert truth.store.path.read_bytes() == before
    assert truth.query('execution_attempt') == []


def test_signed_script_ready_producer_is_idempotent_and_survives_cold_replay(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    captain = _captain(truth)
    signer = RC72AuthorityRuntime(b'isolated-approved-test-script-gate-signer')
    producer = _producer(truth, signer)
    start = len(list(truth.store.iter_raw()))
    first = producer.issue(release_batch_id=BATCH, captain_binding=captain)
    assert first['status'] == 'ADMITTED' and first['case_count'] > 0
    assert len(list(truth.store.iter_raw())) == start + 1
    assert producer.issue(release_batch_id=BATCH, captain_binding=captain) == first
    cold = TruthRuntime(truth.store.path)
    assert _producer(cold, signer).inspect(release_batch_id=BATCH) == first
    assert len(list(truth.store.iter_raw())) == start + 1
    assert not cold.query('execution_attempt')


def test_script_ready_invalid_signature_or_stale_case_fails_closed(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    signer = RC72AuthorityRuntime(b'isolated-gate-signer-case-check')
    assert _producer(truth, signer).issue(
        release_batch_id=BATCH, captain_binding=_captain(truth))['status'] == 'ADMITTED'
    receipt = truth.query('rc72_script_ready_admission')[0]
    forged = dict(receipt, signature='0' * 64,
                  artifact_version=receipt['artifact_version'] + 1)
    truth.append_atomic('RC72_SCRIPT_READY_ADMISSION_UPSERTED', forged)
    before = truth.store.path.read_bytes()
    status = _producer(TruthRuntime(truth.store.path), signer).inspect(release_batch_id=BATCH)
    assert status['status'] == 'HOLD'
    assert status['reason'] == 'SCRIPT_READY_TRUSTED_SIGNATURE_OR_LINEAGE_INVALID'
    assert truth.store.path.read_bytes() == before
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N4_TEST_DESIGN)
    runtime.mark_stale(node['mission_node_id'], reason='approved Case changed')
    before = truth.store.path.read_bytes()
    assert _producer(truth, signer).inspect(release_batch_id=BATCH)['status'] == 'HOLD'
    assert truth.store.path.read_bytes() == before


def test_script_ready_does_not_accept_unbound_worker_or_unknown_batch(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    signer = RC72AuthorityRuntime(b'approved-failclosed-gate-key')
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='REAL_CAPTAIN_BINDING_REQUIRED'):
        _producer(truth, signer).issue(release_batch_id=BATCH, captain_binding=None)
    assert _producer(truth, signer).inspect(release_batch_id='OTHER')['status'] == 'HOLD'
    assert truth.store.path.read_bytes() == before


def test_trusted_script_gate_captain_takeover_requires_new_signed_generation(tmp_path, monkeypatch):
    """GAP-01/02: old Captain's accepted N6 proof persists, cannot authorize new work."""
    from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
    truth, _ = _ready(tmp_path, monkeypatch)
    old = _captain(truth)
    signer = RC72AuthorityRuntime(b'cross-generation-script-gate-authority')
    producer = _producer(truth, signer)
    first = producer.issue(release_batch_id=BATCH, captain_binding=old)
    original = truth.query('rc72_script_ready_admission', admission_id=first['admission_id'])[0]
    fencer = CaptainDispatchFencer(truth, release_id=RELEASE)
    lifecycle = WorkerLifecycleService(truth, release_id=RELEASE)
    n6 = truth.query('rc72_mission_node', mission_id=MISSION,
                     node_type='N6_EXECUTABLE_READINESS')[0]
    checkpoint = fencer.prepare_handoff(
        mission_id=MISSION, lease_id=old.captain_lease_id,
        captain_session_id=old.captain_session_id,
        lifecycle=lifecycle, team_id=old.team_id,
        current_node_refs=['N6_EXECUTABLE_READINESS'],
        latest_delivery_refs=list(n6['delivery_refs']),
        latest_gate_refs=list(n6['gate_refs']),
        next_workitem_ids=[])
    successor = fencer.takeover(
        mission_id=MISSION, team_id=old.team_id,
        checkpoint_id=checkpoint.checkpoint_id,
        new_captain_session_id='DSH-AGENTTEAMS-CAPTAIN-B',
        lifecycle=lifecycle)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='CAPTAIN_DISPATCH_FENCED'):
        producer.issue(release_batch_id=BATCH, captain_binding=old)
    assert truth.store.path.read_bytes() == before
    assert producer.inspect(release_batch_id=BATCH)['reason'] == 'SCRIPT_READY_CURRENT_CAPTAIN_RESIGN_REQUIRED'
    host_key = RC72AuthorityRuntime(b'isolated-takeover-host-observer')
    ticket = ObservedDshCaptain(
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, mission_id=MISSION, team_id=successor['team_id'],
        captain_session_id=successor['captain_session_id'],
        captain_lease_id=successor['lease_id'],
        captain_generation=successor['generation'],
        dsh_session_ref='dsh://agent-teams/new-observed-captain',
        observed_at=int(time.time()), state='ACTIVE', signature='PENDING')
    ticket = replace(ticket, signature=host_key._sign(ticket.signed_fields()))
    second = reenter_host_captain(
        truth, release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, observed=ticket, host_authority=host_key,
        role_profiles={'L3_EXECUTE': ('api_http',)},
        approved_capabilities=('api_http',))
    accepted = producer.issue(release_batch_id=BATCH, captain_binding=second)
    assert accepted['status'] == 'ADMITTED'
    assert accepted['admission_id'] != first['admission_id']
    assert truth.query('rc72_script_ready_admission', admission_id=first['admission_id'])[0] == original
    assert len(truth.query('rc72_script_ready_admission', release_batch_id=BATCH)) == 2
    assert producer.issue(release_batch_id=BATCH, captain_binding=second) == accepted
    assert not truth.query('execution_attempt')


def test_old_signed_case_generation_does_not_disqualify_current_n6_evidence(tmp_path, monkeypatch):
    """P1-6: signer rotation and R1 version history are additive, not bypasses."""
    truth, _ = _ready(tmp_path, monkeypatch)
    signer = RC72AuthorityRuntime(b'approved-multi-delivery-script-gate-key')
    producer = _producer(truth, signer)
    accepted = producer.issue(release_batch_id=BATCH, captain_binding=_captain(truth))
    original = truth.query('rc72_script_ready_admission', admission_id=accepted['admission_id'])[0]
    stale = dict(original)
    stale.pop('artifact_type', None)
    stale.update(admission_id='SCRIPTREADY-OLD-HISTORICAL',
                 contract_digest='0' * 64, artifact_version=1)
    signed = {k: v for k, v in stale.items() if k != 'signature' and k != 'artifact_version'}
    stale['signature'] = signer._sign(signed)
    truth.append_atomic('RC72_SCRIPT_READY_ADMISSION_UPSERTED', stale)
    assert producer.inspect(release_batch_id=BATCH) == accepted
    assert truth.query('rc72_script_ready_admission', admission_id=accepted['admission_id'])[0] == original
    assert not truth.query('execution_attempt')
