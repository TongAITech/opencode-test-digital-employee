import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
from test_rc72_n8_execution_diagnosis import _failure
from rc72_formal_runner_support import LocalHTTPEnvironment


def _setup(tmp_path, monkeypatch, *, bad_verification=False):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        diagnosis.run(p['preparation_id'])
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], tmp_path / 'cleanup')
        calls = []
        def adapter(**kwargs):
            calls.append(kwargs['context']['phase'])
            result = env.cleanup(**kwargs)
            if bad_verification and kwargs['context']['phase'] == 'VERIFY':
                for actual in result['data_results'].values():
                    actual['restored'] = False
            return result
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': adapter})
        return truth, prep, server, p, diagnosis, boundary, calls
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


def test_actual_compensation_uses_fresh_cleanup_scope_then_opens_locked_repair(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        original = truth.query('execution_attempt')[0]
        prep.authority.revoke_worker_lease(p['task_lease']['lease_id'])
        result = service.open(p['preparation_id'])
        assert result['state'] == 'REPAIR_OPEN'
        assert calls == ['CLEANUP', 'VERIFY'] and server.calls == []
        assert truth.query('execution_attempt')[0] == original
        grant = truth.query('rc72_n8_repair_boundary')[0]
        assert grant['cleanup_identity']['worker_id'] != p['worker_id']
        assert grant['cleanup_identity']['phase'] == 'N8_RECOVERY_CLEANUP'
        assert not grant['cleanup_lease']['allowed_artifact_types']
        assert grant['cleanup_lease']['scope_ref'].startswith('cleanup:')
        assert {row['state'] for row in truth.query('rc72_data_lease')} == {'RELEASED'}
        assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'STALE'
        assert truth.query('rc72_workitem_attempt_binding', binding_id=p['binding_id'])[0]['state'] == 'SUPERSEDED'
        for kind in ('N6_EXECUTABLE_READINESS', 'N7_EXECUTION'):
            node = truth.query('rc72_mission_node', node_type=kind)[0]
            assert node['state'] == 'NOT_STARTED' and node['active_delivery_version'] is None
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'RUNNING'
        before = list(truth.store.iter_raw())
        assert service.open(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
        from rc6_runtime.truth import TruthRuntime
        from test_rc72_n7_execution_preparation import _service
        replay = TruthRuntime(truth.store.path)
        resumed = RepairBoundaryService(ExecutionDiagnosisService(_service(replay), evidence_root=tmp_path / 'diagnosis'),
                                       cleanup_adapters={})
        before = list(replay.store.iter_raw())
        assert resumed.open(p['preparation_id']) == result
        assert list(replay.store.iter_raw()) == before
        assert calls == ['CLEANUP', 'VERIFY']
    finally:
        server.shutdown()
        server.server_close()


def test_failed_compensation_verification_cannot_release_or_open_repair(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch, bad_verification=True)
    try:
        result = service.open(p['preparation_id'])
        assert result['state'] == 'VERIFICATION_FAILED' and result['resources_released'] is False
        assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NEEDS_REVISION'
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'PASS'
        assert truth.query('rc72_n7_execution_preparation')[0]['status'] == 'PREPARED'
        assert service.open(p['preparation_id']) == result
        assert calls == ['CLEANUP', 'VERIFY']
    finally:
        server.shutdown()
        server.server_close()


def test_changed_source_blocks_cleanup_before_any_external_action(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        node = truth.query('rc72_mission_node', node_type='N1_REALITY')[0]
        from rc7_runtime.rc72_domain import MissionNodeState
        diagnosis.runtime._persist_node_state(node, MissionNodeState.STALE, reason='source changed', bypass_direct_transition=True)
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='UPSTREAM_SOURCE_CHANGED'):
            service.open(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before and calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('event', ['RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED', 'RC72_MISSION_NODE_UPSERTED'])
def test_interrupted_boundary_resumes_without_repeating_compensation(tmp_path, monkeypatch, event):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        append = truth.append_atomic
        interrupted = []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == event and not interrupted:
                interrupted.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            service.open(p['preparation_id'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        result = service.open(p['preparation_id'])
        assert result['state'] == 'REPAIR_OPEN'
        assert calls == ['CLEANUP', 'VERIFY']
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'RUNNING'
    finally:
        server.shutdown()
        server.server_close()


def test_unaccepted_diagnosis_never_receives_compensation_authority(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        calls = []
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': lambda **kwargs: calls.append(kwargs)})
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError):
            boundary.open(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert calls == [] and truth.query('rc72_n8_repair_boundary') == []
    finally:
        server.shutdown()
        server.server_close()


def test_other_execution_must_drain_before_the_batch_can_enter_repair(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        plan = truth.query('rc72_n7_execution_plan')[0]
        other = next(item for item in plan['items'] if item['workitem_id'] != p['workitem_id'])
        prep.prepare(plan_id=plan['plan_id'], workitem_id=other['workitem_id'])
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        diagnosis.run(p['preparation_id'])
        calls = []
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': lambda **kwargs: calls.append(kwargs)})
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='OTHER_EXECUTION_MUST_DRAIN'):
            boundary.open(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before and calls == []
        assert len(truth.query('rc72_worker_session', purpose='EXECUTION', state='ACTIVE')) == 2
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('target', ['grant', 'cleanup_evidence'])
def test_completed_boundary_proof_tampering_is_rejected_without_side_effects(tmp_path, monkeypatch, target):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        service.open(p['preparation_id'])
        grant = truth.query('rc72_n8_repair_boundary')[0]
        if target == 'grant':
            grant['contract_sha256'] = 'changed'
            grant['artifact_version'] += 1
            truth.append_atomic('RC72_N8_REPAIR_BOUNDARY_UPSERTED', grant)
        else:
            evidence = truth.query('rc7_evidence', evidence_id=grant['cleanup_evidence_ref'])[0]
            evidence['content_hash'] = 'changed'
            evidence['artifact_version'] += 1
            truth.append_atomic('RC7_EVIDENCE_UPSERTED', evidence)
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError):
            service.open(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert calls == ['CLEANUP', 'VERIFY']
    finally:
        server.shutdown()
        server.server_close()


def test_generic_callback_cannot_replace_cleanup_authority(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService, CleanupError
    with pytest.raises(CleanupError, match='TRUSTED_REPAIR_BOUNDARY_REQUIRED'):
        from types import SimpleNamespace
        ExecutionCleanupService(SimpleNamespace(truth=None), adapters={}, recovery_authorizer=object())


def test_fresh_cleanup_worker_cannot_use_expired_resource_custody(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        import rc7_runtime.rc72_data_resources as resources
        lease = truth.query('rc72_data_lease')[0]
        monkeypatch.setattr(resources, '_now', lambda: lease['expires_at'] + 1)
        with pytest.raises(ContractError, match='DATA_LEASE_EXPIRED'):
            service.open(p['preparation_id'])
        assert calls == []
        assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NEEDS_REVISION'
    finally:
        server.shutdown()
        server.server_close()


def test_changed_original_n6_cannot_be_reset_as_if_it_were_the_failed_scope(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, service, calls = _setup(tmp_path, monkeypatch)
    try:
        from rc7_runtime.rc72_domain import MissionNodeState
        node = truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]
        diagnosis.runtime._persist_node_state(node, MissionNodeState.STALE, reason='different downstream change', bypass_direct_transition=True)
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='ORIGINAL_N6_SCOPE_CHANGED'):
            service.open(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before and calls == []
    finally:
        server.shutdown()
        server.server_close()



def test_recalled_n8_compensation_grant_fails_closed_before_external_cleanup_io(
        tmp_path, monkeypatch):
    """A changed signed N8 boundary cannot authorize a call via stale precheck."""
    truth, prep, server, p, diagnosis, service, calls = _setup(
        tmp_path, monkeypatch)
    try:
        original_authorize = service.authorize_cleanup
        switches = []
        def revoke_after_initial_check(prepared, contract, phase, tool):
            accepted = original_authorize(prepared, contract, phase, tool)
            boundary = service._one(
                'rc72_n8_repair_boundary',
                preparation_id=prepared['preparation_id'])
            service._persist(dict(
                boundary, state='REPAIR_OPEN',
                artifact_version=boundary['artifact_version'] + 1))
            switches.append(True)
            return accepted
        monkeypatch.setattr(service, 'authorize_cleanup',
                            revoke_after_initial_check)
        with pytest.raises(ContractError,
                           match='N8_CLEANUP_GRANT_CHANGED_BEFORE_EXTERNAL_IO'):
            service.open(p['preparation_id'])
        assert switches == [True]
        assert calls == [] and server.calls == []
        assert truth.query('rc72_n7_cleanup_call') == []
        assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}
    finally:
        server.shutdown()
        server.server_close()
