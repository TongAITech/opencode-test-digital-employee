"""Expiry cannot turn unknown external effects into free resource custody."""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_data_resources import DataAccessMode, DataResourceConflict
from test_rc72_n8_repair_boundary import _setup


def _expire_by_contending(prep, p, monkeypatch):
    lease = prep.data.lease(p['data_lease_ids'][0])
    with pytest.raises(DataResourceConflict, match='RESOURCE_CONFLICT'):
        prep.data.acquire(data_ref=lease['data_ref'], mission_id=p['mission_id'], workitem_id=p['workitem_id'],
            attempt_id=p['attempt_id'], worker_id=p['worker_id'], mode=DataAccessMode.EXCLUSIVE_WRITE,
            ttl_seconds=300, cleanup_policy=lease['cleanup_policy'], now=lease['expires_at'] + 1)
    return lease


def test_actual_n8_signed_compensation_can_relinquish_expired_custody_without_reviving_business_lease(tmp_path, monkeypatch):
    truth, prep, server, p, _, boundary, calls = _setup(tmp_path, monkeypatch)
    try:
        old = truth.query('execution_attempt', attempt_id=p['attempt_id'])[0]
        lease = _expire_by_contending(prep, p, monkeypatch)
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'EXPIRED'
        with pytest.raises(ContractError, match='VERIFIED_RECOVERY_REQUIRED'):
            prep.data.release(lease['data_lease_id'], cleanup_evidence_ref='arbitrary-proof', reason='claim clean')
        prep.authority.revoke_worker_lease(p['task_lease']['lease_id'])
        result = boundary.open(p['preparation_id'])
        assert result['state'] == 'REPAIR_OPEN'
        assert calls == ['CLEANUP', 'VERIFY'] and server.calls == []
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'RELEASED'
        assert truth.query('execution_attempt', attempt_id=p['attempt_id'])[0] == old
        assert prep.authority.is_lease_revoked(p['task_lease']['lease_id'])
        assert all(row.get('runtime_signature') for row in truth.query('rc72_n7_cleanup_call'))
        before = truth.store.path.read_bytes()
        assert boundary.open(p['preparation_id']) == result
        assert truth.store.path.read_bytes() == before and calls == ['CLEANUP', 'VERIFY']
    finally:
        server.shutdown()
        server.server_close()


def test_failed_compensation_keeps_expired_custody_and_never_reuses_the_resource(tmp_path, monkeypatch):
    truth, prep, server, p, _, boundary, calls = _setup(tmp_path, monkeypatch, bad_verification=True)
    try:
        lease = _expire_by_contending(prep, p, monkeypatch)
        assert boundary.open(p['preparation_id'])['state'] == 'VERIFICATION_FAILED'
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'EXPIRED'
        _expire_by_contending(prep, p, monkeypatch)
        assert calls == ['CLEANUP', 'VERIFY']
        assert truth.query('rc72_n7_execution_preparation')[0]['status'] == 'PREPARED'
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('proof_tamper', ['invalid', 'missing'])
def test_tampered_runtime_cleanup_proof_cannot_release_expired_custody(tmp_path, monkeypatch, proof_tamper):
    truth, prep, server, p, _, boundary, calls = _setup(tmp_path, monkeypatch)
    try:
        lease = _expire_by_contending(prep, p, monkeypatch)
        adapter = boundary.cleanup.adapters['api_http']
        def tamper(**kwargs):
            result = adapter(**kwargs)
            if kwargs['context']['phase'] == 'VERIFY':
                action = truth.query('rc72_n7_cleanup_call', phase='CLEANUP')[0]
                action = dict(action, artifact_version=action['artifact_version'] + 1)
                if proof_tamper == 'missing':
                    action.pop('runtime_signature')
                else:
                    action['runtime_signature'] = '0' * 64
                truth.append_atomic('RC72_N7_CLEANUP_CALL_UPSERTED', action)
            return result
        boundary.cleanup.adapters['api_http'] = tamper
        with pytest.raises(ContractError, match='RUNTIME_(SIGNATURE_INVALID|PROOF_REQUIRED)'):
            boundary.open(p['preparation_id'])
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'EXPIRED'
        assert calls == ['CLEANUP', 'VERIFY']
        with pytest.raises(ContractError, match='RUNTIME_(SIGNATURE_INVALID|PROOF_REQUIRED)'):
            boundary.open(p['preparation_id'])
        assert calls == ['CLEANUP', 'VERIFY']
    finally:
        server.shutdown()
        server.server_close()


def test_expired_inflight_business_effect_cannot_be_cleaned_or_reassigned(tmp_path, monkeypatch):
    import json
    from urllib.request import Request, urlopen
    from rc72_formal_runner_support import formal_setup
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
    from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
    from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        def lost_result(**kwargs):
            request = Request(url + '/business', data=json.dumps({'attempt_id': p['attempt_id']}).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=5) as response:
                assert response.status == 200
            raise KeyboardInterrupt('controller lost after real business effect')
        with pytest.raises(KeyboardInterrupt):
            SignedToolDispatchService(prep, adapters={'api_http': lost_result}).dispatch(p['preparation_id'])
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        lease = _expire_by_contending(prep, p, monkeypatch)
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'unknown-effects')
        assert diagnosis.run(p['preparation_id'])['failure_class'] == 'UNKNOWN'
        calls = []
        def forbidden_cleanup(**kwargs):
            calls.append(kwargs)
            raise AssertionError('unknown business process cannot be presumed drained')
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': forbidden_cleanup})
        with pytest.raises(ContractError):
            boundary.open(p['preparation_id'])
        assert not calls and len(server.calls) == 1
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'EXPIRED'
        assert truth.query('rc72_n7_tool_dispatch')[0]['state'] == 'IN_FLIGHT'
        assert truth.query('rc72_n8_repair_boundary') == []
    finally:
        server.shutdown()
        server.server_close()


def test_interrupted_expired_cleanup_finalization_resumes_cold_without_more_tool_calls(tmp_path, monkeypatch):
    from rc6_runtime.truth import TruthRuntime
    from test_rc72_n7_execution_preparation import _service
    from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
    from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
    truth, prep, server, p, _, boundary, calls = _setup(tmp_path, monkeypatch)
    try:
        lease = _expire_by_contending(prep, p, monkeypatch)
        def interrupt(*args):
            raise RuntimeError('interrupted after verified expired resource release')
        monkeypatch.setattr(boundary, '_open_after_cleanup', interrupt)
        with pytest.raises(RuntimeError, match='interrupted after verified'):
            boundary.open(p['preparation_id'])
        assert prep.data.lease(lease['data_lease_id'])['state'] == 'RELEASED'
        assert truth.query('rc72_n8_repair_boundary')[0]['state'] == 'CLEANUP_AUTHORIZED'
        cold = TruthRuntime(truth.store.path)
        def no_more_tools(**kwargs):
            raise AssertionError('saved verified cleanup cannot be replayed as external I/O')
        resumed = RepairBoundaryService(ExecutionDiagnosisService(_service(cold), evidence_root=tmp_path / 'diagnosis'),
            cleanup_adapters={'api_http': no_more_tools})
        result = resumed.open(p['preparation_id'])
        assert result['state'] == 'REPAIR_OPEN' and calls == ['CLEANUP', 'VERIFY']
        assert cold.query('execution_attempt', attempt_id=p['attempt_id'])[0]['status'] == 'BLOCKED'
        before = cold.store.path.read_bytes()
        assert resumed.open(p['preparation_id']) == result
        assert cold.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('kind', ['data', 'browser'])
def test_expired_wall_time_cannot_bypass_recovery_by_retaining_active_metadata(tmp_path, monkeypatch, kind):
    if kind == 'data':
        import rc7_runtime.rc72_data_resources as module
        from test_rc72_phase7_data_lease_contract import _setup as setup, _acquire as acquire
        truth, manager, a, _ = setup(tmp_path)
        grant = acquire(manager, a, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
        row = manager.lease(grant.data_lease_id)
        release = lambda: manager.release(grant.data_lease_id, cleanup_evidence_ref='claimed-proof', reason='claimed clean')
    else:
        import rc7_runtime.rc72_browser_resources as module
        from test_rc72_phase7_browser_lease_contract import _setup as setup, _acquire as acquire
        truth, manager, actors = setup(tmp_path, instance_count=1)
        grant = acquire(manager, actors['L4'], purpose='EXECUTION')
        row = manager.lease(grant.browser_lease_id)
        release = lambda: manager.release(grant.browser_lease_id, reason='claimed clean')
    assert row['state'] == 'ACTIVE'
    monkeypatch.setattr(module, '_now', lambda: row['expires_at'] + 1)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='VERIFIED_RECOVERY_REQUIRED'):
        release()
    assert truth.store.path.read_bytes() == before


def test_cold_preparation_resource_failure_never_restores_business_authority(tmp_path, monkeypatch):
    from rc6_runtime.truth import TruthRuntime
    from rc72_formal_runner_support import formal_setup
    from test_rc72_n7_execution_preparation import _service
    truth, plan, prep, server, _ = formal_setup(tmp_path, monkeypatch)
    try:
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        _expire_by_contending(prep, p, monkeypatch)
        cold = _service(TruthRuntime(truth.store.path))
        assert p['task_lease']['lease_id'] not in cold.authority._leases
        with pytest.raises(ContractError, match='DATA_LEASE_NOT_ACTIVE'):
            cold.assert_current(p['preparation_id'])
        assert p['task_lease']['lease_id'] not in cold.authority._leases
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_failed_recovery_durably_suspends_business_restoration_on_cold_restart(tmp_path, monkeypatch):
    from rc6_runtime.truth import TruthRuntime
    from test_rc72_n7_execution_preparation import _service
    truth, prep, server, p, _, boundary, _ = _setup(tmp_path, monkeypatch, bad_verification=True)
    try:
        _expire_by_contending(prep, p, monkeypatch)
        assert boundary.open(p['preparation_id'])['state'] == 'VERIFICATION_FAILED'
        assert prep.authority.is_lease_revoked(p['task_lease']['lease_id'])
        cold = _service(TruthRuntime(truth.store.path))
        with pytest.raises(ContractError, match='SUSPENDED_BY_REPAIR_BOUNDARY'):
            cold.assert_current(p['preparation_id'])
        assert p['task_lease']['lease_id'] not in cold.authority._leases
        assert cold.authority.is_lease_revoked(p['task_lease']['lease_id'])
    finally:
        server.shutdown()
        server.server_close()
