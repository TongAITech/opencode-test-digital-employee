from copy import deepcopy
import pytest
from rc6_runtime.truth import TruthRuntime
from test_rc72_n7_execution_preparation import _setup, _service
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService, ToolDispatchError
from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationError


def _prepared(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    row = service.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    return truth, service, row


def test_dispatch_persists_intent_before_io_and_replays_without_call(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    calls = []
    def invoke(*, contract, context):
        assert truth.query('rc72_n7_tool_dispatch')[0]['state'] == 'IN_FLIGHT'
        assert truth.query('rc7_task', task_id=row['workitem_id'])[0]['state'] == 'RUNNING'
        assert context['attempt_id'] == row['attempt_id']
        calls.append(deepcopy(contract))
        contract['request']['injected'] = True
        return {'status_code': 200, 'body': {'ok': True}}
    service = SignedToolDispatchService(prep, adapters={'api_http': invoke})
    result = service.dispatch(row['preparation_id'])
    assert result['state'] == 'RETURNED'
    assert result['raw_result']['status_code'] == 200
    assert 'passed' not in result
    assert 'injected' not in truth.query('rc72_n6_executable_contract', contract_id=row['contract_id'])[0]['request']
    replay = TruthRuntime(truth.store.path)
    again = SignedToolDispatchService(_service(replay), adapters={'api_http': invoke})
    assert again.dispatch(row['preparation_id']) == result
    assert len(calls) == 1
    assert {lease['state'] for lease in replay.query('rc72_data_lease')} == {'ACTIVE'}
    with pytest.raises(ExecutionPreparationError):
        prep.release_unstarted(row['preparation_id'], reason='cannot claim cleanup')


def test_missing_adapter_does_not_start_or_write(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    with pytest.raises(ToolDispatchError, match='ADAPTER_REQUIRED'):
        SignedToolDispatchService(prep, adapters={}).dispatch(row['preparation_id'])
    assert list(truth.store.iter_raw()) == before


@pytest.mark.parametrize('bad', [None, {}, {'bad': float('nan')}, {'bad': object()}])
def test_invalid_receipt_blocks_completion_and_is_not_retried(tmp_path, monkeypatch, bad):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    calls = []
    def invoke(**kwargs):
        calls.append(1)
        return bad
    service = SignedToolDispatchService(prep, adapters={'api_http': invoke})
    result = service.dispatch(row['preparation_id'])
    assert result['state'] == 'UNKNOWN'
    assert result['possible_external_effect'] is True
    assert result['replay_prohibited'] is True
    with pytest.raises(ToolDispatchError, match='SIDE_EFFECTS_UNKNOWN'):
        service.dispatch(row['preparation_id'])
    assert len(calls) == 1


def test_adapter_exception_records_type_without_secret_and_retains_leases(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    def invoke(**kwargs):
        raise RuntimeError('secret-do-not-persist')
    result = SignedToolDispatchService(prep, adapters={'api_http': invoke}).dispatch(row['preparation_id'])
    assert result['error_type'] == 'RuntimeError'
    assert 'secret-do-not-persist' not in truth.store.path.read_text()
    assert {lease['state'] for lease in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_crash_after_possible_side_effect_requires_diagnosis_not_reexecution(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    calls = []
    def crash(**kwargs):
        calls.append(1)
        raise KeyboardInterrupt()
    service = SignedToolDispatchService(prep, adapters={'api_http': crash})
    with pytest.raises(KeyboardInterrupt):
        service.dispatch(row['preparation_id'])
    replay = TruthRuntime(truth.store.path)
    with pytest.raises(ToolDispatchError, match='SIDE_EFFECTS_UNKNOWN'):
        SignedToolDispatchService(_service(replay), adapters={'api_http': crash}).dispatch(row['preparation_id'])
    assert len(calls) == 1


def test_claim_survives_crash_before_truth_write_and_blocks_duplicate_io(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    service = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: pytest.fail('unexpected IO')})
    original = truth.append_atomic
    def crash(event, payload):
        if event == 'RC72_N7_TOOL_DISPATCH_UPSERTED':
            raise KeyboardInterrupt()
        return original(event, payload)
    monkeypatch.setattr(truth, 'append_atomic', crash)
    with pytest.raises(KeyboardInterrupt):
        service.dispatch(row['preparation_id'])
    monkeypatch.setattr(truth, 'append_atomic', original)
    with pytest.raises(ToolDispatchError, match='ALREADY_CLAIMED'):
        service.dispatch(row['preparation_id'])
    assert truth.query('rc72_n7_tool_dispatch') == []


def test_oracle_uses_stored_receipt_and_frozen_predicates_without_completing_task(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    service = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: {'unrelated': True}})
    receipt = service.dispatch(row['preparation_id'])
    result = service.evaluate(row['preparation_id'])
    assert result['raw_result'] == receipt['raw_result']
    assert result['oracle_result']['passed'] is False
    before = list(truth.store.iter_raw())
    assert service.evaluate(row['preparation_id']) == result
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc7_task', task_id=row['workitem_id'])[0]['state'] == 'RUNNING'
    assert {lease['state'] for lease in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_oracle_refuses_missing_or_failed_receipt(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    service = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: None})
    with pytest.raises(ToolDispatchError, match='RETURNED_RECEIPT_REQUIRED'):
        service.evaluate(row['preparation_id'])
    service.dispatch(row['preparation_id'])
    with pytest.raises(ToolDispatchError, match='RETURNED_RECEIPT_REQUIRED'):
        service.evaluate(row['preparation_id'])


def test_matching_oracle_is_assertion_evidence_not_case_completion(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    actual = {'http': {'status': 200}, 'business': {'outcome': 'APPROVED_FIXTURE_RESULT'}}
    service = SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: actual})
    service.dispatch(row['preparation_id'])
    result = service.evaluate(row['preparation_id'])
    assert result['oracle_result']['passed'] is True
    binding = truth.query('rc72_workitem_attempt_binding', binding_id=row['binding_id'])[0]
    assert binding['state'] == 'RUNNING'
    assert truth.query('rc7_task', task_id=row['workitem_id'])[0]['state'] == 'RUNNING'
    assert 'cleanup_complete' not in result


def test_stale_upstream_blocks_tool_invocation_without_dispatch_write(tmp_path, monkeypatch):
    from rc7_runtime.rc72_state_machine import RC72StateMachine
    from rc7_runtime.rc72_domain import AutonomousMissionNode
    from rc72_n2_test_support import MISSION, RELEASE
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    runtime.mark_stale(node['mission_node_id'], reason='new executable required')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='UPSTREAM_NOT_PASS'):
        SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: pytest.fail('stale IO')}).dispatch(row['preparation_id'])
    assert list(truth.store.iter_raw()) == before


def test_cold_process_replays_dispatch_without_importing_service(tmp_path, monkeypatch):
    import subprocess
    import sys
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: {'http': {'status': 200}}}).dispatch(row['preparation_id'])
    script = '''import sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
rows = truth.query('rc72_n7_tool_dispatch')
assert len(rows) == 1 and rows[0]['state'] == 'RETURNED'
'''
    subprocess.run([sys.executable, '-c', script, str(truth.store.path)], check=True,
                   capture_output=True, text=True)



def test_adapter_times_out_after_remote_commit_and_cold_resume_never_replays(tmp_path, monkeypatch):
    """A lost response is UNKNOWN, not a failed business operation or retry permission."""
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    remote_operations = []

    def commit_then_lose_response(**kwargs):
        remote_operations.append({'business_reference': 'payment-001'})
        raise TimeoutError('bank business response lost after commit: secret-do-not-persist')

    first = SignedToolDispatchService(prep, adapters={'api_http': commit_then_lose_response})
    unknown = first.dispatch(row['preparation_id'])
    assert unknown['state'] == 'UNKNOWN'
    assert unknown['error_type'] == 'TimeoutError'
    assert unknown['replay_prohibited'] is True
    assert 'secret-do-not-persist' not in truth.store.path.read_text()
    assert len(remote_operations) == 1

    cold = TruthRuntime(truth.store.path)
    resumed = SignedToolDispatchService(_service(cold),
                                        adapters={'api_http': commit_then_lose_response})
    # Before the cold redispatch revokes the old worker lease, UNKNOWN cannot
    # be evaluated as a returned business receipt or a PASS.
    from rc6_runtime.authority import AuthorityError
    with pytest.raises((ToolDispatchError, AuthorityError)):
        resumed.evaluate(row['preparation_id'])
    assert 'oracle_result' not in cold.query('rc72_n7_tool_dispatch', preparation_id=row['preparation_id'])[0]
    with pytest.raises(ToolDispatchError, match='SIDE_EFFECTS_UNKNOWN'):
        resumed.dispatch(row['preparation_id'])
    assert len(remote_operations) == 1
    assert {lease['state'] for lease in cold.query('rc72_data_lease')} == {'ACTIVE'}


def test_unknown_effect_cannot_be_reclassified_to_failed_for_unattended_retry(tmp_path, monkeypatch):
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    calls = []
    def remote(*, contract, context):
        calls.append(context['attempt_id'])
        raise ConnectionResetError('lost acknowledgement')
    dispatch = SignedToolDispatchService(prep, adapters={'api_http': remote})
    unknown = dispatch.dispatch(row['preparation_id'])
    assert unknown['state'] == 'UNKNOWN'
    assert unknown['attempt_id'] == row['attempt_id']
    assert unknown['possible_external_effect'] is True
    with pytest.raises(ToolDispatchError, match='SIDE_EFFECTS_UNKNOWN'):
        dispatch.dispatch(row['preparation_id'])
    assert calls == [row['attempt_id']]



def test_formal_runner_error_without_signed_preexecution_evidence_remains_unknown(tmp_path, monkeypatch):
    from rc7_runtime.rc72_formal_runner import FormalRunnerError
    truth, prep, row = _prepared(tmp_path, monkeypatch)
    calls = []

    def forged_negative(**kwargs):
        calls.append(1)
        # A caller-supplied error string cannot attest a business-safe retry.
        raise FormalRunnerError('FORMAL_PREPARATION_NOT_SATISFIED:PRECONDITION')

    dispatch = SignedToolDispatchService(prep, adapters={'api_http': forged_negative})
    receipt = dispatch.dispatch(row['preparation_id'])
    assert receipt['state'] == 'UNKNOWN'
    assert receipt['replay_prohibited'] is True
    assert receipt['possible_external_effect'] is True
    with pytest.raises(ToolDispatchError, match='SIDE_EFFECTS_UNKNOWN'):
        dispatch.dispatch(row['preparation_id'])
    assert calls == [1]



def test_signed_preflight_cannot_claim_no_effect_when_unloaded_overlay_has_raw_io_event(tmp_path, monkeypatch):
    """R1 raw effect beats a valid signed negative preflight observation."""
    from test_rc72_n8_execution_diagnosis import _failure
    from rc7_runtime.rc72_formal_runner import FormalRunnerError
    from rc7_runtime.rc72_n7_no_effect_attestation import verified_no_external_business_effect

    truth, prep, server, prepared = _failure(tmp_path, monkeypatch, mode="data")
    try:
        error = FormalRunnerError("FORMAL_PREPARATION_NOT_SATISFIED:DATA_RECHECK")
        verified = verified_no_external_business_effect(prep, prepared, error)
        assert verified  # The fixture really wrote a signed negative check.
        original_events = list(truth.store.iter_raw())
        # An optional transport overlay is NOT required to be installed in a
        # cold caller. Model this by adding its recorded event to raw history.
        raw_io = {
            "event_type": "RC72_N7_HTTP_CALL_UPSERTED",
            "payload": {
                "attempt_id": prepared["attempt_id"],
                "preparation_id": prepared["preparation_id"],
                "worker_id": prepared["worker_id"],
            },
        }
        monkeypatch.setattr(truth.store, "iter_raw",
                            lambda: iter(original_events + [raw_io]))
        assert verified_no_external_business_effect(prep, prepared, error) == ()
    finally:
        server.shutdown()
        server.server_close()
