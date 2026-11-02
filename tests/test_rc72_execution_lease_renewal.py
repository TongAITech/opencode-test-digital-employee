"""Temporal amendments preserve original attempt truth and exact tool scope."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from rc6_runtime.authority import AuthorityError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_lease_renewal import ExecutionLeaseRenewalService
from test_rc72_n7_execution_preparation import _setup, _service


def _prepared(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    prep = _service(truth)
    p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    return truth, plan, prep, p


def _renewal(prep):
    return ExecutionLeaseRenewalService(prep, max_extension_seconds=1200, max_total_seconds=3600)


def test_native_renewal_preserves_all_identities_original_signature_and_exact_permissions(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    original = truth.query('rc72_n7_execution_preparation')[0]
    first = _renewal(prep).renew(p['preparation_id'], renewal_id='RENEW-1', ttl_seconds=600)
    second = _renewal(prep).renew(p['preparation_id'], renewal_id='RENEW-2', ttl_seconds=900)
    assert first['state'] == second['state'] == 'APPLIED'
    assert second['previous_renewal_id'] == 'RENEW-1'
    assert truth.query('rc72_n7_execution_preparation')[0] == original
    effective = prep.authority.get_lease(p['task_lease']['lease_id'])
    for key in ('lease_id', 'worker_id', 'scope_ref', 'allowed_tools', 'allowed_artifact_types', 'issued_at'):
        expected = p['task_lease'][key]
        if isinstance(expected, (tuple, list)):
            assert tuple(asdict(effective)[key]) == tuple(expected)
        else:
            assert asdict(effective)[key] == expected
    assert effective.expires_at > first['renewed_lease']['expires_at'] > p['task_lease']['expires_at']
    assert prep.assert_current(p['preparation_id']) == original
    before = truth.store.path.read_bytes()
    assert _renewal(prep).renew(p['preparation_id'], renewal_id='RENEW-1', ttl_seconds=600) == first
    assert truth.store.path.read_bytes() == before
    cold = _service(TruthRuntime(truth.store.path))
    assert cold.assert_current(p['preparation_id']) == original
    assert cold.authority.get_lease(effective.lease_id) == effective
    assert truth.query('execution_attempt') == []
    assert len(truth.query('rc72_decomposition_snapshot')) == 1


def test_partial_projection_blocks_business_then_resumes_same_signed_decision(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    original = truth.append_atomic
    interrupted = []
    def lose_response(event, payload):
        result = original(event, payload)
        if event == 'RC72_DATA_LEASE_UPSERTED' and payload['expires_at'] > p['task_lease']['expires_at'] and not interrupted:
            interrupted.append(True)
            raise RuntimeError('lost resource renewal response')
        return result
    monkeypatch.setattr(truth, 'append_atomic', lose_response)
    with pytest.raises(RuntimeError, match='lost resource'):
        _renewal(prep).renew(p['preparation_id'], renewal_id='RENEW-PARTIAL', ttl_seconds=600)
    assert truth.query('rc72_execution_lease_renewal')[0]['state'] == 'PLANNED'
    cold = _service(TruthRuntime(truth.store.path))
    with pytest.raises(ContractError, match='INCOMPLETE_EXECUTION_SUSPENDED'):
        cold.assert_current(p['preparation_id'])
    assert p['task_lease']['lease_id'] not in cold.authority._leases
    monkeypatch.setattr(truth, 'append_atomic', original)
    before = truth.query('rc72_data_lease')[0]
    assert _renewal(prep).renew(p['preparation_id'], renewal_id='RENEW-PARTIAL', ttl_seconds=600)['state'] == 'APPLIED'
    assert truth.query('rc72_data_lease')[0] == before
    assert len(truth.query('rc72_execution_lease_renewal')) == 1


def test_expired_resource_cannot_renew(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    from test_rc72_expired_resource_recovery import _expire_by_contending
    _expire_by_contending(prep, p, monkeypatch)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='DATA_LEASE_NOT_ACTIVE'):
        _renewal(prep).renew(p['preparation_id'], renewal_id='NO-REVIVE', ttl_seconds=600)
    assert truth.store.path.read_bytes() == before
    assert truth.query('rc72_execution_lease_renewal') == []


def test_forged_renewal_proof_cannot_restore_cold_authority(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    row = _renewal(prep).renew(p['preparation_id'], renewal_id='SIGNED-ONLY', ttl_seconds=600)
    truth.append_atomic('RC72_EXECUTION_LEASE_RENEWAL_UPSERTED', dict(row,
        signature='0' * 64, artifact_version=row['artifact_version'] + 1))
    cold = _service(TruthRuntime(truth.store.path))
    with pytest.raises(ContractError, match='SIGNATURE_INVALID'):
        cold.assert_current(p['preparation_id'])
    assert p['task_lease']['lease_id'] not in cold.authority._leases


def test_inflight_renewal_requires_same_live_dispatch_controller_not_a_new_object(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    service = _renewal(prep)
    observed = []
    def adapter(**kwargs):
        stranger = SignedToolDispatchService(prep, adapters={'api_http': adapter})
        with pytest.raises(ContractError, match='LIVE_DISPATCH_CONTROLLER_REQUIRED'):
            service.renew(p['preparation_id'], renewal_id='NO-STRANGER', ttl_seconds=600, dispatcher=stranger)
        observed.append(service.renew(p['preparation_id'], renewal_id='LIVE-CONTROLLER', ttl_seconds=600, dispatcher=dispatcher))
        raise KeyboardInterrupt('lost controller after renewal')
    dispatcher = SignedToolDispatchService(prep, adapters={'api_http': adapter})
    with pytest.raises(KeyboardInterrupt):
        dispatcher.dispatch(p['preparation_id'])
    assert observed[0]['state'] == 'APPLIED' and not dispatcher._live_invocations
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='LIVE_DISPATCH_CONTROLLER_REQUIRED'):
        service.renew(p['preparation_id'], renewal_id='NO-ORPHAN', ttl_seconds=900, dispatcher=dispatcher)
    assert truth.store.path.read_bytes() == before


def test_actual_formal_business_execution_after_original_deadline_uses_renewed_scope(tmp_path, monkeypatch):
    import rc6_runtime.authority as authority_module
    import rc7_runtime.rc72_lease_renewal as renewal_module
    import rc7_runtime.rc72_data_resources as data_module
    import rc7_runtime.rc72_browser_resources as browser_module
    from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment
    from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
    from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
    from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'actual-renewed'
        environment = LocalHTTPEnvironment(url, root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=environment,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        original = None
        for index, item in enumerate(plan['items']):
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            if index == 0:
                original = truth.query('rc72_n7_execution_preparation', preparation_id=p['preparation_id'])[0]
                _renewal(prep).renew(p['preparation_id'], renewal_id='ACTUAL-RENEWAL', ttl_seconds=600)
                after_old_deadline = p['task_lease']['expires_at'] + 1
                monkeypatch.setattr(authority_module, 'time', SimpleNamespace(time=lambda: after_old_deadline))
                monkeypatch.setattr(data_module, '_now', lambda: after_old_deadline)
                monkeypatch.setattr(renewal_module, '_now', lambda: after_old_deadline)
                monkeypatch.setattr(browser_module, '_now', lambda: after_old_deadline)
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': environment.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured')
        bundle = review.build(plan['plan_id'])
        assert ExecutionFinalizationService(review).finalize(bundle['bundle_id'])['state'] == 'N7_PASS'
        assert truth.query('rc72_n7_execution_preparation', preparation_id=original['preparation_id'])[0] == original
        assert len(server.calls) == len(plan['items'])
        assert len(truth.query('execution_attempt')) == len(plan['items'])
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
        receipt = truth.query('rc72_n7_formal_runner_receipt', preparation_id=original['preparation_id'])[0]
        assert receipt['execution_authorization']['renewal_id'] == 'ACTUAL-RENEWAL'
        assert receipt['execution_authorization']['authorized_at'] > original['task_lease']['expires_at']
    finally:
        server.shutdown()
        server.server_close()


def test_ttl_policy_expired_parent_and_changed_replay_are_fail_closed(tmp_path, monkeypatch):
    import rc7_runtime.rc72_lease_renewal as module
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    service = _renewal(prep)
    before = truth.store.path.read_bytes()
    for ttl in (True, 0, 1201):
        with pytest.raises(ContractError, match='TTL_OUTSIDE_POLICY'):
            service.renew(p['preparation_id'], renewal_id='NO-POLICY', ttl_seconds=ttl)
    tight = ExecutionLeaseRenewalService(prep, max_extension_seconds=1200,
        max_total_seconds=p['task_lease']['expires_at'] - p['task_lease']['issued_at'] + 1)
    with pytest.raises(ContractError, match='WINDOW_OUTSIDE_POLICY'):
        tight.renew(p['preparation_id'], renewal_id='NO-TOTAL', ttl_seconds=600)
    assert truth.store.path.read_bytes() == before
    old_clock = module._now
    monkeypatch.setattr(module, '_now', lambda: p['task_lease']['expires_at'] + 1)
    with pytest.raises(AuthorityError, match='LEASE_EXPIRED'):
        service.renew(p['preparation_id'], renewal_id='NO-EXPIRED-PARENT', ttl_seconds=600)
    assert truth.store.path.read_bytes() == before
    monkeypatch.setattr(module, '_now', old_clock)
    service.renew(p['preparation_id'], renewal_id='IMMUTABLE-REQUEST', ttl_seconds=600)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='REQUEST_REPLAY_CONFLICT'):
        service.renew(p['preparation_id'], renewal_id='IMMUTABLE-REQUEST', ttl_seconds=900)
    assert truth.store.path.read_bytes() == before


def test_valid_signed_lease_for_wrong_task_scope_cannot_be_renewed_or_restored(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    wrong = prep.authority.issue_lease(p['worker_id'], 'task:UNRELATED/attempt:UNRELATED', (), ('api_http',), ttl_seconds=300)
    truth.append_atomic('RC72_N7_EXECUTION_PREPARATION_UPSERTED', dict(p,
        task_lease=asdict(wrong), artifact_version=p['artifact_version'] + 1))
    binding = truth.query('rc72_workitem_attempt_binding', binding_id=p['binding_id'])[0]
    truth.append_atomic('RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED', dict(binding,
        task_lease_ref=wrong.lease_id, artifact_version=binding['artifact_version'] + 1))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='PREPARATION_BINDING_INVALID'):
        _renewal(prep).renew(p['preparation_id'], renewal_id='NO-WRONG-SCOPE', ttl_seconds=600)
    cold = _service(TruthRuntime(truth.store.path))
    with pytest.raises(ContractError, match='PREPARATION_BINDING_INVALID'):
        cold.assert_current(p['preparation_id'])
    assert wrong.lease_id not in cold.authority._leases
    assert truth.store.path.read_bytes() == before


def test_partial_renewal_cannot_roll_forward_after_its_original_deadline(tmp_path, monkeypatch):
    import rc7_runtime.rc72_lease_renewal as module
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    append = truth.append_atomic
    def interrupt(event, payload):
        result = append(event, payload)
        if event == 'RC72_DATA_LEASE_UPSERTED' and payload['expires_at'] > p['task_lease']['expires_at']:
            raise RuntimeError('interrupted renewal')
        return result
    monkeypatch.setattr(truth, 'append_atomic', interrupt)
    with pytest.raises(RuntimeError):
        _renewal(prep).renew(p['preparation_id'], renewal_id='DEADLINE', ttl_seconds=600)
    monkeypatch.setattr(truth, 'append_atomic', append)
    monkeypatch.setattr(module, '_now', lambda: p['task_lease']['expires_at'] + 1)
    before = truth.store.path.read_bytes()
    with pytest.raises(AuthorityError, match='LEASE_EXPIRED'):
        _renewal(prep).renew(p['preparation_id'], renewal_id='DEADLINE', ttl_seconds=600)
    assert truth.store.path.read_bytes() == before
    assert truth.query('rc72_execution_lease_renewal')[0]['state'] == 'PLANNED'
    assert prep.authority.get_lease(p['task_lease']['lease_id']).expires_at == p['task_lease']['expires_at']


def test_generic_fresh_process_reads_renewal_without_service_imports(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    _renewal(prep).renew(p['preparation_id'], renewal_id='COLD-SCHEMA', ttl_seconds=600)
    code = '''import json,sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
rows=TruthRuntime(sys.argv[1]).query('rc72_execution_lease_renewal')
print(json.dumps([(row['renewal_id'],row['state']) for row in rows]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(truth.store.path)],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [['COLD-SCHEMA', 'APPLIED']]


@pytest.mark.parametrize('tamper', ['time', 'tool_scope', 'contract'])
def test_runtime_authorization_rejects_even_validly_signed_wrong_time_or_expanded_scope(tmp_path, monkeypatch, tamper):
    from rc7_runtime.rc72_lease_renewal import execution_authorization_snapshot, verify_execution_authorization
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    _renewal(prep).renew(p['preparation_id'], renewal_id='AUTHORIZATION', ttl_seconds=600)
    snapshot = execution_authorization_snapshot(prep, p)
    assert verify_execution_authorization(prep, p, snapshot) == snapshot
    if tamper == 'time':
        snapshot['authorized_at'] = snapshot['task_lease']['expires_at'] + 1
    elif tamper == 'contract':
        snapshot['contract_sha256'] = '0' * 64
    else:
        lease = snapshot['task_lease']
        lease['allowed_tools'].append('unapproved-write-tool')
        lease['signature'] = prep.authority._sign({key: value for key, value in lease.items() if key != 'signature'})
    snapshot['signature'] = prep.authority._sign({key: value for key, value in snapshot.items() if key != 'signature'})
    before = truth.store.path.read_bytes()
    expected = 'AUTHORIZATION_SCOPE_CHANGED' if tamper == 'contract' else 'AUTHORIZATION_SCOPE_OR_TIME_INVALID'
    with pytest.raises(ContractError, match=expected):
        verify_execution_authorization(prep, p, snapshot)
    assert truth.store.path.read_bytes() == before


def test_changed_data_reservation_scope_blocks_renewal_before_authority_mutation(tmp_path, monkeypatch):
    truth, _, prep, p = _prepared(tmp_path, monkeypatch)
    data = truth.query('rc72_data_lease')[0]
    changed_mode = 'SHARED_READ' if data['mode'] == 'EXCLUSIVE_WRITE' else 'EXCLUSIVE_WRITE'
    truth.append_atomic('RC72_DATA_LEASE_UPSERTED', dict(data, mode=changed_mode,
        artifact_version=data['artifact_version'] + 1))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='DATA_LEASE_CONTRACT_SCOPE_MISMATCH'):
        _renewal(prep).renew(p['preparation_id'], renewal_id='NO-RESOURCE-SCOPE', ttl_seconds=600)
    cold = _service(TruthRuntime(truth.store.path))
    with pytest.raises(ContractError, match='DATA_LEASE_CONTRACT_SCOPE_MISMATCH'):
        cold.assert_current(p['preparation_id'])
    assert p['task_lease']['lease_id'] not in cold.authority._leases
    assert truth.store.path.read_bytes() == before
