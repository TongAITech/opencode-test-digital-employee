import pytest
from rc6_runtime.truth import TruthRuntime
from test_rc72_n7_execution_preparation import _setup, _service
from test_rc72_n7_execution_evidence import ACTUAL
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService, CleanupError


def _setup_cleanup(tmp_path, monkeypatch, *, tool='api_http'):
    # Refine the upstream N4 source before it is written, reviewed, hashed and
    # compiled. Never rewrite a frozen N6 contract to make cleanup tests pass.
    import rc72_integrated_test_support as support
    import test_rc72_n4_test_design_handoff as n4
    original = support.install_execution_sources
    def install(*args):
        original(*args)
        candidate = n4._candidate
        def refined(*args, **kwargs):
            result = candidate(*args, **kwargs)
            for case in result['cases']:
                case['execution']['cleanup'].update(tool=tool, verification=dict(tool=tool, source_ref=case['execution']['cleanup']['source_ref'],
                    checks=[dict(id='data-restored', type='DATA_STATE', actual_path='restored', operator='EQ', expected=True)]))
            return result
        monkeypatch.setattr(n4, '_candidate', refined)
    monkeypatch.setattr(support, 'install_execution_sources', install)
    truth, plan = _setup(tmp_path, monkeypatch)
    prep = _service(truth)
    p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    if tool == 'api_http':
        SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: ACTUAL}).dispatch(p['preparation_id'])
    return truth, prep, p


def _adapter(calls, *, restored=True, incomplete=False):
    def invoke(*, contract, context):
        calls.append(context['phase'])
        if context['phase'] == 'CLEANUP':
            return {'action_receipt': 'fixture cleanup actually invoked'}
        refs = [row['data_ref'] for row in contract['data_refs']]
        return {'data_results': {} if incomplete else {ref: {'restored': restored} for ref in refs}}
    return invoke


def test_cleanup_invokes_action_then_verifies_all_refs_before_release_and_replays(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    calls = []
    adapter = _adapter(calls)
    service = ExecutionCleanupService(prep, adapters={'api_http': adapter})
    result = service.run(p['preparation_id'])
    assert result['state'] == 'CLEANUP_VERIFIED'
    assert calls == ['CLEANUP', 'VERIFY']
    leases = truth.query('rc72_data_lease')
    assert {row['state'] for row in leases} == {'RELEASED'}
    assert all(row['cleanup_evidence_ref'] == result['evidence_ref'] for row in leases)
    assert truth.query('execution_attempt', attempt_id=p['attempt_id'])[0]['status'] == 'BLOCKED'
    assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'RUNNING'
    replay = TruthRuntime(truth.store.path)
    before = list(replay.store.iter_raw())
    assert ExecutionCleanupService(_service(replay), adapters={'api_http': adapter}).run(p['preparation_id']) == result
    assert list(replay.store.iter_raw()) == before
    assert calls == ['CLEANUP', 'VERIFY']


@pytest.mark.parametrize('incomplete', [True, False])
def test_missing_or_failed_data_verification_keeps_all_leases(tmp_path, monkeypatch, incomplete):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    service = ExecutionCleanupService(prep, adapters={'api_http': _adapter([], restored=False, incomplete=incomplete)})
    if incomplete:
        with pytest.raises(CleanupError, match='DENOMINATOR_MISMATCH'):
            service.run(p['preparation_id'])
    else:
        assert service.run(p['preparation_id'])['state'] == 'VERIFICATION_FAILED'
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_cleanup_crash_never_repeats_possible_side_effects(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    calls = []
    def crash(**kw):
        calls.append(1)
        raise KeyboardInterrupt()
    service = ExecutionCleanupService(prep, adapters={'api_http': crash})
    with pytest.raises(KeyboardInterrupt):
        service.run(p['preparation_id'])
    with pytest.raises(CleanupError, match='SIDE_EFFECTS_UNKNOWN'):
        service.run(p['preparation_id'])
    assert len(calls) == 1
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_unscoped_cleanup_tool_cannot_be_called(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch, tool='unapproved-delete-tool')
    before = list(truth.store.iter_raw())
    from rc7_runtime.rc72_n7_tool_dispatch import ToolDispatchError
    with pytest.raises(ToolDispatchError, match='OUTSIDE_SCOPE'):
        SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: pytest.fail('unauthorized'),
            'unapproved-delete-tool': lambda **kw: pytest.fail('unauthorized')}).dispatch(p['preparation_id'])
    assert list(truth.store.iter_raw()) == before


def test_legacy_text_cleanup_is_rejected_before_tool_execution(tmp_path, monkeypatch):
    import rc72_integrated_test_support as support
    import test_rc72_n4_test_design_handoff as n4
    original = support.install_execution_sources
    def install(*args):
        original(*args)
        candidate = n4._candidate
        def legacy(*args, **kwargs):
            result = candidate(*args, **kwargs)
            for case in result['cases']:
                case['execution']['cleanup'].pop('verification', None)
            return result
        monkeypatch.setattr(n4, '_candidate', legacy)
    monkeypatch.setattr(support, 'install_execution_sources', install)
    from test_rc72_n7_tool_dispatch import _prepared
    truth, prep, p = _prepared(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    with pytest.raises(CleanupError, match='VERIFICATION_REQUIRED'):
        SignedToolDispatchService(prep, adapters={'api_http': lambda **kw: pytest.fail('unresolved cleanup')}).dispatch(p['preparation_id'])
    assert list(truth.store.iter_raw()) == before



@pytest.mark.parametrize('mode', ['exception', 'unknown', 'bad_data', 'missing_data'])
def test_cleanup_failure_routes_evidence_to_independent_n8_without_release(tmp_path, monkeypatch, mode):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    def adapter(*, contract, context):
        if context['phase'] == 'CLEANUP':
            if mode == 'exception':
                raise RuntimeError('private exception detail')
            if mode == 'unknown':
                raise KeyboardInterrupt()
            return {'action_receipt': 'fixture cleanup'}
        return {'data_results': {} if mode == 'missing_data' else
                {ref['data_ref']: {'restored': False} for ref in contract['data_refs']}}
    service = ExecutionCleanupService(prep, adapters={'api_http': adapter})
    if mode == 'unknown':
        with pytest.raises(KeyboardInterrupt):
            service.run(p['preparation_id'])
    elif mode == 'missing_data':
        with pytest.raises(CleanupError):
            service.run(p['preparation_id'])
    else:
        assert service.run(p['preparation_id'])['resources_released'] is False
    diagnosis = service.begin_failure_diagnosis(p['preparation_id'])
    assert diagnosis.worker_id != p['worker_id']
    assert diagnosis.source_attempt_id == p['attempt_id']
    before = list(truth.store.iter_raw())
    assert service.begin_failure_diagnosis(p['preparation_id']) == diagnosis
    assert list(truth.store.iter_raw()) == before
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_verified_cleanup_cannot_be_mislabeled_as_failure(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    service = ExecutionCleanupService(prep, adapters={'api_http': _adapter([])})
    service.run(p['preparation_id'])
    with pytest.raises(CleanupError, match='FAILURE_REQUIRED'):
        service.begin_failure_diagnosis(p['preparation_id'])


def test_restart_after_release_crash_finishes_without_repeating_cleanup_or_verify(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    calls = []
    adapter = _adapter(calls)
    release = prep.data.release
    def interrupted(*args, **kwargs):
        release(*args, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(prep.data, 'release', interrupted)
    with pytest.raises(KeyboardInterrupt):
        ExecutionCleanupService(prep, adapters={'api_http': adapter}).run(p['preparation_id'])
    replay = TruthRuntime(truth.store.path)
    result = ExecutionCleanupService(_service(replay), adapters={'api_http': adapter}).run(p['preparation_id'])
    assert result['resources_released'] is True
    assert calls == ['CLEANUP', 'VERIFY']


def test_resource_owner_change_blocks_success_evidence_and_release(tmp_path, monkeypatch):
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    original = _adapter([])
    def adapter(**kwargs):
        result = original(**kwargs)
        if kwargs['context']['phase'] == 'VERIFY':
            resource = truth.query('rc72_data_lease', data_lease_id=p['data_lease_ids'][0])[0]
            resource['worker_id'] = 'another-worker'
            resource['artifact_version'] += 1
            truth.append_atomic('RC72_DATA_LEASE_UPSERTED', resource)
        return result
    with pytest.raises(CleanupError, match='OWNER_OR_STATE_MISMATCH'):
        ExecutionCleanupService(prep, adapters={'api_http': adapter}).run(p['preparation_id'])
    assert truth.query('rc7_evidence', kind='N7_CLEANUP_DATA_REVERIFIED') == []
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_cleanup_calls_replay_in_a_cold_process(tmp_path, monkeypatch):
    import subprocess
    import sys
    truth, prep, p = _setup_cleanup(tmp_path, monkeypatch)
    ExecutionCleanupService(prep, adapters={'api_http': _adapter([])}).run(p['preparation_id'])
    script = '''import sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
assert len(truth.query('rc72_n7_cleanup_call')) == 2
assert len(truth.query('execution_attempt')) == 1
assert truth.query('rc72_data_lease')[0]['state'] == 'RELEASED'
'''
    subprocess.run([sys.executable, '-c', script, str(truth.store.path)], check=True, capture_output=True, text=True)
