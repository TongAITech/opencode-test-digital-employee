"""Actual native repair, compilation, signed retry and formal local SUT execution."""
from pathlib import Path
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc7_runtime.rc72_n7_execution_planning import ExecutionPlanningService
from test_rc72_n5_existing_data_repair import _accepted_data_repair, _close


def test_native_recompile_reuses_original_snapshot_etu_workitems_and_creates_child_attempt(tmp_path, monkeypatch):
    values, repair = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, old, _, data, _, _, _ = values
    try:
        failed = truth.query('execution_attempt', attempt_id=old['attempt_id'])[0]
        previous = truth.query('rc72_n7_execution_plan', plan_id=old['plan_id'])[0]
        snapshot = truth.query('rc72_decomposition_snapshot', snapshot_id=previous['snapshot_id'])[0]
        service = DataRepairContinuationService(data.boundary.diagnosis)
        plan = service.reconcile(old['preparation_id'])
        assert plan['plan_id'] != previous['plan_id']
        assert plan['snapshot_id'] == previous['snapshot_id']
        assert [(item['case_id'], item['etu_id'], item['workitem_id']) for item in plan['items']] == [
            (item['case_id'], item['etu_id'], item['workitem_id']) for item in previous['items']]
        assert truth.query('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id'])[0] == snapshot
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'PASS'
        before = truth.store.path.read_bytes()
        assert service.reconcile(old['preparation_id']) == plan
        assert prep.planning.plan(release_batch_id=old['release_batch_id']) == plan
        assert truth.store.path.read_bytes() == before
        new = service.prepare_replacement(old['preparation_id'])
        assert (new['workitem_id'], new['etu_id'], new['case_id']) == (old['workitem_id'], old['etu_id'], old['case_id'])
        assert new['attempt_id'] != old['attempt_id'] and new['worker_id'] != old['worker_id']
        assert new['session_id'] != old['session_id'] and new['attempt_generation'] == old['attempt_generation'] + 1
        binding = truth.query('rc72_workitem_attempt_binding', binding_id=new['binding_id'])[0]
        assert binding['parent_attempt_id'] == old['attempt_id']
        assert truth.query('execution_attempt', attempt_id=old['attempt_id'])[0] == failed
        assert truth.query('rc72_diagnosis_recovery')[0]['replacement_attempt_id'] == new['attempt_id']
        assert server.calls == []
    finally:
        _close(server)


def _whole_inventory_repaired(tmp_path, monkeypatch):
    from test_rc72_n5_existing_data_repair import _service_setup, _launcher
    from rc7_runtime.rc72_n5_completion import N5DeliveryGateService
    values = _service_setup(tmp_path, monkeypatch, restored=False)
    truth, prep, server, p, _, data, request, calls, _ = values
    try:
        changed = []
        for binding in truth.query('rc72_n5_data_binding', release_batch_id=p['release_batch_id']):
            current = truth.query('rc72_n5_existing_data_repair', data_requirement_id=binding['data_requirement_id'])
            if current:
                requested = current[0]
            else:
                requested = data.request(p['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                         binding_revision=binding['artifact_version'])
            data.prepare(requested['repair_id'], launcher=_launcher(tmp_path, prep, server, calls),
                         allowed_tools=['repair-exact-data-ref'])
            assert data.run(requested['repair_id'])['state'] == 'VERIFIED'
            changed.append(binding['data_ref'])
        n5 = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        data.boundary.diagnosis.record_accepted_repair(p['preparation_id'],
            repair_delivery_id=n5['delivery']['delivery_id'], changed_refs=changed, reason='whole inventory physical restoration and independent verification')
        return values
    except BaseException:
        _close(server)
        raise


@pytest.mark.parametrize('renew_before_failure', [False, True])
@pytest.mark.parametrize('expired_custody', [False, True])
def test_actual_full_denominator_retry_runs_strict_runner_and_finalizes_without_changing_old_failure(tmp_path, monkeypatch, expired_custody, renew_before_failure):
    from rc72_formal_runner_support import LocalHTTPEnvironment
    from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
    from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
    from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
    renewed = []
    if renew_before_failure:
        from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
        from rc7_runtime.rc72_lease_renewal import ExecutionLeaseRenewalService
        original_dispatch = SignedToolDispatchService.dispatch
        def dispatch_after_renewal(dispatcher, preparation_id):
            if not renewed:
                renewed.append(ExecutionLeaseRenewalService(dispatcher.preparation,
                    max_extension_seconds=600, max_total_seconds=3600).renew(preparation_id,
                    renewal_id='RETRY-ORIGINAL-RENEWAL', ttl_seconds=600))
            return original_dispatch(dispatcher, preparation_id)
        monkeypatch.setattr(SignedToolDispatchService, 'dispatch', dispatch_after_renewal)
    expired = []
    if expired_custody:
        from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
        from test_rc72_expired_resource_recovery import _expire_by_contending
        original_open = RepairBoundaryService.open
        def open_after_expiry(boundary, preparation_id):
            original = boundary.preparation._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
            if not expired:
                expired.append(_expire_by_contending(boundary.preparation, original, monkeypatch))
            return original_open(boundary, preparation_id)
        monkeypatch.setattr(RepairBoundaryService, 'open', open_after_expiry)
    truth, prep, server, p, _, data, _, _, _ = _whole_inventory_repaired(tmp_path, monkeypatch)
    try:
        old = truth.query('execution_attempt', attempt_id=p['attempt_id'])[0]
        service = DataRepairContinuationService(data.boundary.diagnosis)
        replacement = service.prepare_replacement(p['preparation_id'])
        plan = prep.planning.assert_current(replacement['plan_id'])
        root = tmp_path / 'actual-retry'
        environment = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=environment,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        for item in plan['items']:
            prepared = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(prepared['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': environment.cleanup}).run(prepared['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-retry')
        bundle = review.build(plan['plan_id'])
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS'
        if expired_custody:
            assert truth.query('rc72_data_lease', data_lease_id=expired[0]['data_lease_id'])[0]['state'] == 'RELEASED'
        assert len(server.calls) == len(plan['items'])
        assert truth.query('execution_attempt', attempt_id=p['attempt_id'])[0] == old
        if renew_before_failure:
            assert renewed[0]['state'] == 'APPLIED'
        assert len(truth.query('execution_attempt')) == len(plan['items']) + 1
        assert len(truth.query('rc72_decomposition_snapshot')) == 1
        assert truth.query('rc7_mission', mission_id=p['mission_id'])[0]['state'] != 'CONVERGED'
    finally:
        _close(server)


def test_reconciliation_resumes_after_target_restoration_interruption(tmp_path, monkeypatch):
    values, _ = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, p, _, data, _, _, _ = values
    try:
        service = DataRepairContinuationService(data.boundary.diagnosis)
        original_compile = service._compile
        def interrupt(row):
            raise RuntimeError('simulated process interruption after durable restoration')
        monkeypatch.setattr(service, '_compile', interrupt)
        with pytest.raises(RuntimeError, match='simulated process interruption'):
            service.reconcile(p['preparation_id'])
        record = truth.query('rc72_n8_retry_reconciliation')[0]
        assert record['state'] == 'PLANNED'
        assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'READY'
        monkeypatch.setattr(service, '_compile', original_compile)
        plan = service.reconcile(p['preparation_id'])
        assert plan['snapshot_id'] == record['original_snapshot']['snapshot_id']
        assert len(truth.query('rc72_n8_retry_reconciliation')) == 1
        assert len(truth.query('rc72_n7_execution_plan')) == 2
        assert server.calls == []
    finally:
        _close(server)



def test_n8_retry_rejects_changed_nonfailed_case_verifier_before_any_r1_mutation(
        tmp_path, monkeypatch):
    """C01/C02 whole inventory: unrelated verified DataRef is not disposable."""
    truth, prep, server, original, _, data, _, _, _ = _whole_inventory_repaired(
        tmp_path, monkeypatch)
    try:
        contract = prep._one('rc72_n6_executable_contract',
                             contract_id=original['contract_id'])
        affected = {item['data_ref'] for item in contract['data_refs']}
        other = [row for row in truth.query(
            'rc72_n5_existing_data_repair',
            release_batch_id=original['release_batch_id'])
            if row['state'] == 'VERIFIED'
            and row['original_binding']['data_ref'] not in affected]
        assert other, 'whole-inventory setup must include another verified Case'
        evidence = prep._one('rc7_evidence', evidence_id=other[0]['evidence_ref'])
        raw = Path(evidence['content_ref'][len('file://'):])
        raw.write_bytes(raw.read_bytes() + b'QA-UNRELATED-DATA-RECHECK-TAMPER')
        before = truth.store.path.read_bytes()
        attempts = list(truth.query('execution_attempt'))
        calls = list(server.calls)
        with pytest.raises(ContractError, match='N8_RETRY_N5_BATCH_REVERIFICATION_BYTES_CHANGED'):
            DataRepairContinuationService(data.boundary.diagnosis).reconcile(
                original['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert truth.query('execution_attempt') == attempts
        assert server.calls == calls
        assert not truth.query('rc72_n8_retry_reconciliation')
    finally:
        _close(server)


def test_unsigned_recovery_plan_cannot_reuse_old_identities(tmp_path, monkeypatch):
    values, _ = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, p, _, data, _, _, _ = values
    try:
        service = DataRepairContinuationService(data.boundary.diagnosis)
        plan = service.reconcile(p['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        row['signature'] = '0' * 64
        row['artifact_version'] += 1
        truth.append_atomic('RC72_N8_RETRY_RECONCILIATION_UPSERTED', row)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='SIGNATURE_INVALID'):
            prep.planning.assert_current(plan['plan_id'])
        assert truth.store.path.read_bytes() == before
    finally:
        _close(server)


def test_changed_original_snapshot_blocks_reconciliation_before_restoration(tmp_path, monkeypatch):
    values, _ = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, p, _, data, _, _, _ = values
    try:
        plan = truth.query('rc72_n7_execution_plan', plan_id=p['plan_id'])[0]
        snapshot = truth.query('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id'])[0]
        snapshot['planning_cases'][0]['auth_role'] = 'unapproved-role'
        snapshot['artifact_version'] += 1
        truth.append_atomic('RC72_DECOMPOSITION_SNAPSHOT_UPSERTED', snapshot)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='ORIGINAL_PLAN_IDENTITY_CHANGED'):
            DataRepairContinuationService(data.boundary.diagnosis).reconcile(p['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'STALE'
    finally:
        _close(server)


def test_repaired_verifier_bytes_are_rechecked_before_new_compilation(tmp_path, monkeypatch):
    values, _ = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, p, _, data, _, _, _ = values
    try:
        evidence = truth.query('rc7_evidence', kind='N5_EXISTING_DATA_REVERIFICATION')
        assert evidence
        proof = Path(evidence[0]['content_ref'][len('file://'):])
        proof.write_bytes(proof.read_bytes() + b'changed')
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            DataRepairContinuationService(data.boundary.diagnosis).reconcile(p['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'STALE'
    finally:
        _close(server)


@pytest.mark.parametrize('mutation', ['case_etu', 'admission'])
def test_changed_historical_mapping_or_admission_cannot_authorize_retry(tmp_path, monkeypatch, mutation):
    values, _ = _accepted_data_repair(tmp_path, monkeypatch)
    truth, prep, server, p, _, data, _, _, _ = values
    try:
        plan = truth.query('rc72_n7_execution_plan', plan_id=p['plan_id'])[0]
        if mutation == 'case_etu':
            assert plan['items'][0]['etu_id'] != plan['items'][1]['etu_id']
            plan['items'][0]['etu_id'] = plan['items'][1]['etu_id']
            plan['artifact_version'] += 1
            truth.append_atomic('RC72_N7_EXECUTION_PLAN_UPSERTED', plan)
        else:
            receipt = truth.query('rc72_n7_execution_admission', admission_id=plan['items'][0]['admission_id'])[0]
            receipt['upstream_refs'][0]['digest'] = '0' * 64
            receipt['artifact_version'] += 1
            truth.append_atomic('RC72_N7_EXECUTION_ADMISSION_UPSERTED', receipt)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='N8_RETRY_ORIGINAL_'):
            DataRepairContinuationService(data.boundary.diagnosis).reconcile(p['preparation_id'])
        assert truth.store.path.read_bytes() == before
    finally:
        _close(server)
