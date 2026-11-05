"""Crash/replay tests exercise native journal and stale mutations, no SUT claim."""
from dataclasses import fields
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_domain import AutonomousMissionNode, NodeDelivery, ETUState, ExecutionTaskUnit
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_diagnosis_orchestration import DiagnosisOrchestrator
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from test_rc72_phase6_repair_reexecution_contract import (_setup, _persist_diagnosis_case,
    _accept_repair_delivery)


def _repair(tmp_path, *, fallback=False):
    truth, runtime, repo, orchestrator = _setup(tmp_path)
    diagnosis_id = _persist_diagnosis_case(truth, orchestrator)
    n3 = runtime.node_by_type('M-1', AutonomousMissionNode.N3_CODE_ANALYSIS)
    repair_delivery = NodeDelivery(delivery_id='REPAIR', mission_id='M-1',
        mission_node_id=n3['mission_node_id'], node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        version=2, producer_ref='fresh-repair', artifact_refs=['analysis-v2'],
        evidence_refs=['EVD-FAIL-1'], created_by_workitems=['REPAIR-WI'])
    repo.persist(repair_delivery)
    # Phase 6+ requires accepted upstream repair truth, not a merely saved
    # Delivery.  Preserve that production gate in all cold/crash/replay tests.
    _accept_repair_delivery(repo, runtime, repair_delivery)
    params = dict(source_delivery_id='REPAIR', changed_refs=['unknown' if fallback else 'Service#create'],
                  reason='accepted repair changed execution inputs')
    return truth, runtime, repo, orchestrator, diagnosis_id, params


def _cold(truth):
    replay = TruthRuntime(truth.store.path)
    return replay, RC72StateMachine(replay, release_id='RC7.2')


@pytest.mark.parametrize('fallback', [False, True])
@pytest.mark.parametrize('event', ['RC72_IMPACT_SET_UPSERTED', 'RC72_MISSION_NODE_UPSERTED',
    'RC72_TEST_OBLIGATION_UPSERTED', 'RC72_ETU_UPSERTED', 'RC72_IMPACT_APPLICATION_UPSERTED'])
def test_partial_stale_application_resumes_same_decision_after_cold_restart(tmp_path, monkeypatch, fallback, event):
    truth, runtime, _, _, _, params = _repair(tmp_path, fallback=fallback)
    append = truth.append_atomic
    writes = []

    def crash(kind, payload, *args, **kwargs):
        writes.append(kind)
        # Application intent must be durable before any target can change.
        should_crash = kind == event and (event != 'RC72_IMPACT_APPLICATION_UPSERTED' or payload['state'] == 'APPLIED')
        if should_crash:
            raise RuntimeError('injected journal interruption')
        return append(kind, payload, *args, **kwargs)

    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError, match='injected journal interruption'):
        runtime.propagate_stale(**params)
    assert writes[0] == 'RC72_IMPACT_APPLICATION_UPSERTED'
    planned = truth.query('rc72_impact_application')[0]
    replay, resumed = _cold(truth)
    impact = resumed.propagate_stale(**params)
    assert impact.impact_set_id == planned['impact']['impact_set_id']
    assert len(replay.query('rc72_impact_application')) == len(replay.query('rc72_impact_set')) == 1
    assert replay.query('rc72_impact_application')[0]['state'] == 'APPLIED'
    for target in planned['targets']:
        original = target['original']
        row = replay.query(target['kind'], **{target['identity_key']: original[target['identity_key']]})[0]
        key = 'status' if target['kind'] == 'rc72_test_obligation' else 'state'
        assert row[key] == 'STALE'
        assert row['artifact_version'] == original['artifact_version'] + (original[key] != 'STALE')
    before = replay.store.path.read_bytes()
    assert resumed.propagate_stale(**params) == impact
    assert replay.store.path.read_bytes() == before


def test_completed_impact_replay_does_not_stale_a_rebuilt_etu(tmp_path):
    truth, runtime, repo, _, _, params = _repair(tmp_path)
    impact = runtime.propagate_stale(**params)
    row = truth.query('rc72_etu')[0]
    etu = ExecutionTaskUnit(**{field.name: row[field.name] for field in fields(ExecutionTaskUnit) if field.name in row})
    etu.state = ETUState.READY
    repo.persist(etu, artifact_version=row['artifact_version'] + 1)
    before = truth.store.path.read_bytes()
    assert runtime.propagate_stale(**params) == impact
    assert truth.store.path.read_bytes() == before
    assert truth.query('rc72_etu')[0]['state'] == 'READY'


def test_interrupted_application_refuses_newer_target_before_resuming_any_mutation(tmp_path, monkeypatch):
    truth, runtime, repo, _, _, params = _repair(tmp_path)
    append = truth.append_atomic
    def crash(event, payload, *args, **kwargs):
        if event == 'RC72_IMPACT_SET_UPSERTED':
            raise RuntimeError('pause before effects')
        return append(event, payload, *args, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        runtime.propagate_stale(**params)
    monkeypatch.setattr(truth, 'append_atomic', append)
    row = truth.query('rc72_etu')[0]
    etu = ExecutionTaskUnit(**{field.name: row[field.name] for field in fields(ExecutionTaskUnit) if field.name in row})
    etu.primary_goal = 'replanned while interrupted'
    repo.persist(etu, artifact_version=row['artifact_version'] + 1)
    replay, resumed = _cold(truth)
    # Materialize immutable ImpactSet separately, so failed preflight is no-write.
    from rc7_runtime.rc72_impact import ImpactSet
    from rc7_runtime.rc72_impact_truth import append_impact_set
    append_impact_set(replay, ImpactSet(**replay.query('rc72_impact_application')[0]['impact']), release_id='RC7.2')
    before = replay.store.path.read_bytes()
    with pytest.raises(ContractError, match='IMPACT_APPLICATION_TARGET_CHANGED'):
        resumed.propagate_stale(**params)
    assert replay.store.path.read_bytes() == before


@pytest.mark.parametrize('event', ['RC72_DIAGNOSIS_REPAIR_UPSERTED', 'RC72_DIAGNOSIS_CASE_UPSERTED'])
def test_repair_registration_resumes_missing_write_without_reapplying_impact(tmp_path, monkeypatch, event):
    truth, runtime, _, orchestrator, diagnosis_id, params = _repair(tmp_path)
    args = dict(diagnosis_id=diagnosis_id, repair_delivery_id='REPAIR',
                changed_refs=params['changed_refs'], reason=params['reason'])
    append = truth.append_atomic
    def crash(kind, payload, *extra, **kwargs):
        if kind == event:
            raise RuntimeError('interrupted repair registration')
        return append(kind, payload, *extra, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        orchestrator.record_upstream_repair(**args)
    replay, resumed = _cold(truth)
    service = DiagnosisOrchestrator(replay, release_id='RC7.2', state_machine=resumed,
        worker_lifecycle=WorkerLifecycleService(replay, release_id='RC7.2'))
    result = service.record_upstream_repair(**args)
    assert result.impact_set_id == replay.query('rc72_impact_set')[0]['impact_set_id']
    assert replay.query('rc72_diagnosis_case')[0]['state'] == 'REPAIR_RECORDED'
    before = replay.store.path.read_bytes()
    assert service.record_upstream_repair(**args) == result
    assert replay.store.path.read_bytes() == before
    with pytest.raises(ContractError, match='DIAGNOSIS_REPAIR_REPLAY_CONFLICT'):
        service.record_upstream_repair(**dict(args, reason='different repair'))
    assert replay.store.path.read_bytes() == before


def test_cold_process_recovers_overlay_and_pending_application(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import subprocess
    import sys
    truth, runtime, _, _, _, params = _repair(tmp_path)
    append = truth.append_atomic
    def crash(kind, payload, *args, **kwargs):
        if kind == 'RC72_ETU_UPSERTED':
            raise RuntimeError('stop after other native stale writes')
        return append(kind, payload, *args, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        runtime.propagate_stale(**params)
    script = '''
import json, sys
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
runtime = RC72StateMachine(truth, release_id='RC7.2')
impact = runtime.propagate_stale(**json.loads(sys.argv[2]))
before = truth.store.path.read_bytes()
runtime.propagate_stale(**json.loads(sys.argv[2]))
assert truth.store.path.read_bytes() == before
print(json.dumps(dict(id=impact.impact_set_id, state=truth.query('rc72_impact_application')[0]['state'],
                     etu=truth.query('rc72_etu')[0]['state'])))
'''
    process = subprocess.run([sys.executable, '-c', script, str(truth.store.path), json.dumps(params)],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result == dict(id=truth.query('rc72_impact_application')[0]['impact']['impact_set_id'],
                          state='APPLIED', etu='STALE')


@pytest.mark.parametrize('change', ['source', 'denominator', 'impact'])
def test_interrupted_decision_rejects_changed_source_or_manifest_without_asset_writes(tmp_path, monkeypatch, change):
    truth, runtime, _, _, _, params = _repair(tmp_path)
    append = truth.append_atomic
    def crash(kind, payload, *args, **kwargs):
        if kind == 'RC72_IMPACT_SET_UPSERTED':
            raise RuntimeError('stop before impact append')
        return append(kind, payload, *args, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        runtime.propagate_stale(**params)
    monkeypatch.setattr(truth, 'append_atomic', append)
    if change == 'source':
        source = truth.query('rc72_node_delivery', delivery_id='REPAIR')[0]
        truth.append_atomic('RC72_NODE_DELIVERY_UPSERTED',
            dict(source, artifact_refs=['different-repair'], artifact_version=source['artifact_version'] + 1))
    else:
        row = truth.query('rc72_impact_application')[0]
        if change == 'denominator':
            row['targets'] = row['targets'][:-1]
        else:
            row['impact']['reason'] = 'different-repair'
        truth.append_atomic('RC72_IMPACT_APPLICATION_UPSERTED', dict(row, artifact_version=2))
    replay, resumed = _cold(truth)
    before = replay.store.path.read_bytes()
    with pytest.raises(ContractError, match='IMPACT_APPLICATION_(SOURCE_CHANGED|TARGET_SCOPE_CHANGED|REPLAY_CONFLICT)'):
        resumed.propagate_stale(**params)
    assert replay.store.path.read_bytes() == before


@pytest.mark.parametrize('changes', [dict(mission_id='OTHER'), dict(source_attempt_id='OTHER'),
                                     dict(release_id='OTHER')])
def test_repair_cannot_apply_impact_from_unrelated_diagnosis(tmp_path, changes):
    truth, _, _, orchestrator, diagnosis_id, params = _repair(tmp_path)
    row = truth.query('rc72_diagnosis_outcome')[0]
    truth.append_atomic('RC72_DIAGNOSIS_OUTCOME_UPSERTED', dict(row, **changes, artifact_version=2))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='REPAIR_DIAGNOSIS_LINEAGE_MISMATCH'):
        orchestrator.record_upstream_repair(diagnosis_id=diagnosis_id,
            repair_delivery_id='REPAIR', changed_refs=params['changed_refs'], reason=params['reason'])
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_impact_application')


def test_repair_replay_preserves_later_recovery_linked_state(tmp_path):
    from test_rc72_phase6_diagnosis_orchestration_contract import _replacement
    truth, _, repo, orchestrator, diagnosis_id, params = _repair(tmp_path)
    args = dict(diagnosis_id=diagnosis_id, repair_delivery_id='REPAIR',
                changed_refs=params['changed_refs'], reason=params['reason'])
    first = orchestrator.record_upstream_repair(**args)
    _replacement(repo)
    orchestrator.record_replacement_attempt(diagnosis_id=diagnosis_id, replacement_binding_id='BIND-2')
    before = truth.store.path.read_bytes()
    assert orchestrator.record_upstream_repair(**args) == first
    assert truth.store.path.read_bytes() == before
    assert truth.query('rc72_diagnosis_case')[0]['state'] == 'RECOVERY_LINKED'


@pytest.mark.parametrize('state', ['PLANNED', 'APPLIED'])
def test_interrupt_after_durable_application_write_is_recoverable(tmp_path, monkeypatch, state):
    truth, runtime, _, _, _, params = _repair(tmp_path)
    append = truth.append_atomic
    def crash(event, payload, *args, **kwargs):
        result = append(event, payload, *args, **kwargs)
        if event == 'RC72_IMPACT_APPLICATION_UPSERTED' and payload['state'] == state:
            raise RuntimeError('lost response after durable write')
        return result
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        runtime.propagate_stale(**params)
    replay, resumed = _cold(truth)
    if state == 'APPLIED':
        before = replay.store.path.read_bytes()
    result = resumed.propagate_stale(**params)
    if state == 'APPLIED':
        assert replay.store.path.read_bytes() == before
    assert replay.query('rc72_impact_application')[0]['state'] == 'APPLIED'
    assert len(replay.query('rc72_impact_set')) == 1
    assert replay.query('rc72_impact_set')[0]['impact_set_id'] == result.impact_set_id


@pytest.mark.parametrize('change', ['changed_refs', 'reason', 'repair_delivery_id'])
def test_interrupted_repair_refuses_changed_request_before_new_impact(tmp_path, monkeypatch, change):
    truth, _, repo, orchestrator, diagnosis_id, params = _repair(tmp_path)
    args = dict(diagnosis_id=diagnosis_id, repair_delivery_id='REPAIR',
                changed_refs=params['changed_refs'], reason=params['reason'])
    append = truth.append_atomic
    def crash(kind, payload, *extra, **kwargs):
        if kind == 'RC72_DIAGNOSIS_REPAIR_UPSERTED':
            raise RuntimeError('interrupt after native impact')
        return append(kind, payload, *extra, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(RuntimeError):
        orchestrator.record_upstream_repair(**args)
    monkeypatch.setattr(truth, 'append_atomic', append)
    changed_args = dict(args)
    if change == 'repair_delivery_id':
        source = truth.query('rc72_node_delivery', delivery_id='REPAIR')[0]
        repo.persist(NodeDelivery(delivery_id='DIFFERENT-REPAIR', mission_id='M-1',
            mission_node_id=source['mission_node_id'], node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
            version=3, producer_ref='repair', artifact_refs=['another-analysis'],
            evidence_refs=['EVD-FAIL-1']))
        changed_args[change] = 'DIFFERENT-REPAIR'
    else:
        changed_args[change] = ['another-ref'] if change == 'changed_refs' else 'different reason'
    replay, resumed = _cold(truth)
    service = DiagnosisOrchestrator(replay, release_id='RC7.2', state_machine=resumed,
        worker_lifecycle=WorkerLifecycleService(replay, release_id='RC7.2'))
    before = replay.store.path.read_bytes()
    with pytest.raises(ContractError, match='DIAGNOSIS_REPAIR_INTENT_CONFLICT'):
        service.record_upstream_repair(**changed_args)
    assert replay.store.path.read_bytes() == before
    assert len(replay.query('rc72_impact_set')) == 1
    assert service.record_upstream_repair(**args).impact_set_id == replay.query('rc72_impact_set')[0]['impact_set_id']
