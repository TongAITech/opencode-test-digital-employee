import pytest
from rc6_runtime.truth import TruthRuntime
from test_rc72_n7_tool_dispatch import _prepared
from test_rc72_n7_execution_preparation import _service
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService, ExecutionEvidenceError

ACTUAL = {'http': {'status': 200}, 'business': {'outcome': 'APPROVED_FIXTURE_RESULT'}}


def test_receipt_enters_inherited_attempt_assertion_and_both_evidence_surfaces(tmp_path, monkeypatch):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    service = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL})
    service.dispatch(p['preparation_id'])
    result = ExecutionEvidenceService(prep).record(p['preparation_id'])
    assert result['attempt_id'] == p['attempt_id']
    assert result['worker_id'] == p['worker_id']
    assert result['status'] == 'BLOCKED'
    assert result['assertion_passed'] is True
    assert result['actual_result'] == ACTUAL
    assert result['case_version_source'] == 'N4_DELIVERY_VERSION'
    assert truth.query('assertion', id=result['assertion_ref'])[0]['passed'] is True
    for ref in result['evidence_refs']:
        assert truth.query('evidence', id=ref)[0]['attempt_id'] == p['attempt_id']
        assert p['attempt_id'] in truth.query('rc7_evidence', evidence_id=ref)[0]['subject_refs']
    assert truth.query('rc72_workitem_attempt_binding', binding_id=p['binding_id'])[0]['state'] == 'EVIDENCE_READY'
    assert {v['state'] for v in truth.query('rc72_data_lease')} == {'ACTIVE'}
    replay = TruthRuntime(truth.store.path)
    before = list(replay.store.iter_raw())
    assert ExecutionEvidenceService(_service(replay)).record(p['preparation_id']) == result
    assert list(replay.store.iter_raw()) == before


@pytest.mark.parametrize('state', ['UNKNOWN', 'IN_FLIGHT', 'ORACLE_FAILED'])
def test_real_failure_or_unknown_side_effect_gets_blocked_attempt_and_evidence(tmp_path, monkeypatch, state):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    def invoke(**kw):
        if state == 'UNKNOWN':
            raise RuntimeError('never-persist-this-secret')
        if state == 'IN_FLIGHT':
            raise KeyboardInterrupt()
        return {'http': {'status': 500}}
    dispatcher = SignedToolDispatchService(prep, adapters={'api_http': invoke})
    if state == 'IN_FLIGHT':
        with pytest.raises(KeyboardInterrupt):
            dispatcher.dispatch(p['preparation_id'])
    else:
        dispatcher.dispatch(p['preparation_id'])
    attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
    assert attempt['status'] == 'BLOCKED'
    assert attempt['reason'] != 'CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED'
    if state in {'UNKNOWN', 'IN_FLIGHT'}:
        assert attempt['reason'] == 'TOOL_SIDE_EFFECTS_UNKNOWN'
        assert attempt['assertion_passed'] is None
        assert attempt['actual_result'] is None
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
    assert attempt['evidence_refs']
    assert 'never-persist-this-secret' not in truth.store.path.read_text()


def test_historical_observation_is_recordable_when_upstream_becomes_stale(tmp_path, monkeypatch):
    from rc7_runtime.rc72_state_machine import RC72StateMachine
    from rc7_runtime.rc72_domain import AutonomousMissionNode
    from rc72_n2_test_support import RELEASE, MISSION
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    runtime.mark_stale(node['mission_node_id'], reason='upstream changed after invocation')
    attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
    assert attempt['status'] == 'BLOCKED'
    assert attempt['actual_result'] == ACTUAL


def test_wrong_signing_key_cannot_admit_evidence(tmp_path, monkeypatch):
    from rc6_runtime.authority import AuthorityError
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    before = list(truth.store.iter_raw())
    with pytest.raises(AuthorityError):
        ExecutionEvidenceService(_service(truth, key=b'wrong-key-with-valid-length')).record(p['preparation_id'])
    assert list(truth.store.iter_raw()) == before


def test_changed_contract_cannot_be_used_to_reinterpret_old_receipt(tmp_path, monkeypatch):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    contract = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
    contract['steps'] = ['different unapproved actions']
    contract['artifact_version'] += 1
    truth.append_atomic('rc72.n6.executable_contract_compiled', contract)
    before = list(truth.store.iter_raw())
    with pytest.raises(ExecutionEvidenceError, match='BINDING_MISMATCH'):
        ExecutionEvidenceService(prep).record(p['preparation_id'])
    assert list(truth.store.iter_raw()) == before


@pytest.mark.parametrize('failed_tool', [True, False])
def test_failure_dispatches_fresh_independent_n8_worker_once(tmp_path, monkeypatch, failed_tool):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    def invoke(**kw):
        if failed_tool:
            raise RuntimeError('external failure')
        return {'http': {'status': 500}}
    SignedToolDispatchService(prep, adapters={'api_http': invoke}).dispatch(p['preparation_id'])
    evidence = ExecutionEvidenceService(prep)
    diagnosis = evidence.begin_diagnosis(p['preparation_id'])
    assert diagnosis.worker_id != p['worker_id']
    assert diagnosis.session_id != p['session_id']
    assert diagnosis.source_attempt_id == p['attempt_id']
    assert diagnosis.context_bundle['failure_evidence_refs']
    assert truth.query('rc72_mission_node', mission_id=p['mission_id'], node_type='N7_EXECUTION')[0]['state'] == 'NEEDS_REVISION'
    assert truth.query('rc72_mission_node', mission_id=p['mission_id'], node_type='N8_DIAGNOSIS_RECOVERY')[0]['state'] == 'READY'
    before = list(truth.store.iter_raw())
    assert evidence.begin_diagnosis(p['preparation_id']) == diagnosis
    assert list(truth.store.iter_raw()) == before


def test_successful_assertion_cannot_start_failure_diagnosis(tmp_path, monkeypatch):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    with pytest.raises(ExecutionEvidenceError, match='FAILURE_REQUIRED'):
        ExecutionEvidenceService(prep).begin_diagnosis(p['preparation_id'])
    assert truth.query('rc72_diagnosis_case') == []


def test_record_then_evaluate_then_record_preserves_the_same_evidence(tmp_path, monkeypatch):
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    dispatcher = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL})
    dispatcher.dispatch(p['preparation_id'])
    service = ExecutionEvidenceService(prep)
    first = service.record(p['preparation_id'])
    dispatcher.evaluate(p['preparation_id'])
    assert service.record(p['preparation_id']) == first


def test_expired_worker_can_record_past_receipt_without_regaining_tool_authority(tmp_path, monkeypatch):
    import rc6_runtime.authority as authority_module
    from rc6_runtime.authority import AuthorityError
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    monkeypatch.setattr(authority_module.time, 'time', lambda: p['task_lease']['expires_at'] + 5)
    assert ExecutionEvidenceService(prep).record(p['preparation_id'])['status'] == 'BLOCKED'
    with pytest.raises(AuthorityError, match='LEASE_EXPIRED'):
        prep.authority.authorize_tool(p['worker_id'], p['task_lease']['lease_id'], 'api_http')


def test_failure_routing_is_scoped_when_store_has_another_release_batch(tmp_path, monkeypatch):
    from rc7_runtime.rc72_state_machine import RC72StateMachine
    from rc7_runtime.rc72_domain import ReleaseBatch
    from rc72_n2_test_support import RELEASE
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    runtime.bootstrap_release_batch(ReleaseBatch(release_batch_id='OTHER-BATCH', mission_id='OTHER-MISSION', name='other'))
    other_before = truth.query('rc72_mission_node', mission_id='OTHER-MISSION')
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: {'http': {'status': 500}}}).dispatch(p['preparation_id'])
    diagnosis = ExecutionEvidenceService(prep).begin_diagnosis(p['preparation_id'])
    assert diagnosis.context_bundle['mission_id'] == p['mission_id']
    assert truth.query('rc72_mission_node', mission_id='OTHER-MISSION') == other_before



def test_unknown_business_effect_is_durable_in_attempt_and_stays_blocked_after_cold_replay(
        tmp_path, monkeypatch):
    from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
    from test_rc72_n7_execution_preparation import _service

    truth, prep, p = _prepared(tmp_path, monkeypatch)
    invocations = []

    def ambiguous_call(**kwargs):
        invocations.append(kwargs['context']['attempt_id'])
        raise TimeoutError('bank request may have committed: never-persist-private-token')

    result = SignedToolDispatchService(
        prep, adapters={'api_http': ambiguous_call}).dispatch(p['preparation_id'])
    assert result['state'] == 'UNKNOWN' and result['replay_prohibited'] is True
    first = ExecutionEvidenceService(prep).record(p['preparation_id'])
    assert first['status'] == 'BLOCKED'
    assert first['reason'] == 'TOOL_SIDE_EFFECTS_UNKNOWN'
    assert first['assertion_ref'] is None and first['assertion_passed'] is None
    assert first['evidence_refs']
    assert 'never-persist-private-token' not in truth.store.path.read_text()

    cold = TruthRuntime(truth.store.path)
    before = cold.store.path.read_bytes()
    restored = ExecutionEvidenceService(_service(cold)).record(p['preparation_id'])
    assert restored == first
    assert cold.store.path.read_bytes() == before
    assert invocations == [p['attempt_id']]
    assert {row['state'] for row in cold.query('rc72_data_lease')} == {'ACTIVE'}
