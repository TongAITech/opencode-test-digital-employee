"""Actual two-member execution, native N5 repair and independent current review."""
from pathlib import Path
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc7_runtime.rc72_n5_existing_data_repair import ExistingDataRepairService
from rc7_runtime.rc72_n5_completion import N5DeliveryGateService
from rc72_formal_runner_support import LocalHTTPEnvironment
from test_rc72_n7_member_drain import _completed, _close
from test_rc72_n5_existing_data_repair import _launcher
from test_rc72_n7_execution_preparation import _service


def _repaired(tmp_path, monkeypatch, *, repair_completed=False):
    truth, plan, prep, server, completed, drain = _completed(tmp_path, monkeypatch)
    try:
        failed = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][1]['workitem_id'])
        contract = prep._one('rc72_n6_executable_contract', contract_id=failed['contract_id'])
        failed_refs = {ref['data_ref'] for ref in contract['data_refs']}
        old_refs = {ref['data_ref'] for ref in prep._one('rc72_n6_executable_contract', contract_id=completed['contract_id'])['data_refs']}
        assert not old_refs & failed_refs
        server.allowed_data_refs.difference_update(failed_refs)
        root = tmp_path / 'failed-member'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(failed['preparation_id'])['state'] == 'FAILED'
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        assert diagnosis.run(failed['preparation_id'])['failure_class'] == 'TEST_DATA_GAP'
        drain.drain(completed['preparation_id'])
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': env.cleanup})
        assert boundary.open(failed['preparation_id'])['state'] == 'REPAIR_OPEN'
        calls = []
        data = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, prep, server, calls),
                                        allowed_tools=['query-exact-data-ref'])
        for binding in truth.query('rc72_n5_data_binding', release_batch_id=failed['release_batch_id']):
            if not repair_completed and binding['data_ref'] not in failed_refs:
                continue
            requested = data.request(failed['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                     binding_revision=binding['artifact_version'])
            data.prepare(requested['repair_id'], launcher=_launcher(tmp_path, prep, server, calls),
                         allowed_tools=['repair-exact-data-ref'])
            assert data.run(requested['repair_id'])['state'] == 'VERIFIED'
        n5 = N5DeliveryGateService(truth, release_id=failed['release_id'], source_commit=failed['source_commit']).complete(
            release_batch_id=failed['release_batch_id'])
        diagnosis.record_accepted_repair(failed['preparation_id'], repair_delivery_id=n5['delivery']['delivery_id'],
            changed_refs=sorted(failed_refs | old_refs if repair_completed else failed_refs), reason='independent exact failed-member DataRef restoration')
        return truth, prep, server, completed, failed, diagnosis, drain
    except BaseException:
        _close(server)
        raise


@pytest.mark.parametrize('renew_before_execution', [False, True])
def test_unaffected_member_reuses_same_attempt_and_entire_repaired_batch_gets_independent_review(tmp_path, monkeypatch, renew_before_execution):
    if renew_before_execution:
        from rc7_runtime.rc72_lease_renewal import ExecutionLeaseRenewalService
        dispatch, renewed = SignedToolDispatchService.dispatch, []
        def renew_then_dispatch(controller, preparation_id):
            if not renewed:
                renewed.append(ExecutionLeaseRenewalService(controller.preparation, max_extension_seconds=600).renew(
                    preparation_id, renewal_id='COMPLETED-MEMBER-RENEWAL', ttl_seconds=600))
            return dispatch(controller, preparation_id)
        monkeypatch.setattr(SignedToolDispatchService, 'dispatch', renew_then_dispatch)
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch)
    try:
        original = prep._one('execution_attempt', attempt_id=completed['attempt_id'])
        old_failed = prep._one('execution_attempt', attempt_id=failed['attempt_id'])
        service = DataRepairContinuationService(diagnosis)
        plan = service.reconcile(failed['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        assert len(row['member_decisions']) == 1
        decision = row['member_decisions'][0]
        assert decision['attempt_id'] == completed['attempt_id']
        assert decision['disposition'] == 'REUSE_FOR_CURRENT_REVIEW'
        assert truth.query('execution_attempt', attempt_id=completed['attempt_id'])[0] == original
        with pytest.raises(ContractError, match='ALREADY_EXECUTED_REVIEW_REQUIRED'):
            prep.prepare(plan_id=plan['plan_id'], workitem_id=completed['workitem_id'])
        root = tmp_path / 'repaired-execution'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        for item in plan['items']:
            if item['workitem_id'] == completed['workitem_id']:
                continue
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-current')
        bundle = review.build(plan['plan_id'])
        assert len(bundle['case_results']) == len(plan['items'])
        assert next(case for case in bundle['case_results'] if case['case_id'] == completed['case_id'])['attempt_id'] == completed['attempt_id']
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS'
        assert drain.drain(completed['preparation_id'])['state'] == 'DRAINED'
        assert len(server.calls) == len(plan['items'])
        assert len(truth.query('execution_attempt')) == len(plan['items']) + 1
        assert truth.query('execution_attempt', attempt_id=failed['attempt_id'])[0] == old_failed
        assert truth.query('rc72_n7_execution_preparation', preparation_id=completed['preparation_id'])[0]['status'] == 'DRAINED'
        cold = _service(TruthRuntime(truth.store.path))
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=review.capture_root)
        before = truth.store.path.read_bytes()
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == final
        assert cold.truth.store.path.read_bytes() == before
        assert cold.authority.is_lease_revoked(completed['task_lease']['lease_id']) or not cold.authority._leases
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['captured_bytes', 'impact', 'decision_signature'])
def test_reuse_proof_tampering_blocks_current_plan_before_any_replacement_business(tmp_path, monkeypatch, change):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch)
    try:
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        if change == 'captured_bytes':
            member = truth.query('rc72_n7_member_drain')[0]
            Path(member['captured_evidence'][0]['content_ref'][len('file://'):]).write_bytes(b'changed')
            expected = 'REUSE_CAPTURE_BYTES_CHANGED'
        elif change == 'impact':
            impact = truth.query('rc72_impact_set')[0]
            impact['reason'] += ' changed after signed decision'
            impact['artifact_version'] += 1
            truth.append_atomic('RC72_IMPACT_SET_UPSERTED', impact)
            expected = 'REUSE_RECORDED_IMPACT_CHANGED'
        else:
            row = truth.query('rc72_n8_retry_reconciliation')[0]
            row['member_decisions'][0]['attempt_id'] = 'FORGED'
            row['artifact_version'] += 1
            truth.append_atomic('RC72_N8_RETRY_RECONCILIATION_UPSERTED', row)
            expected = 'RECONCILIATION_SIGNATURE_INVALID'
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match=expected):
            prep.prepare(plan_id=plan['plan_id'], workitem_id=failed['workitem_id'])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 1 and len(truth.query('execution_attempt')) == 2
    finally:
        _close(server)


def test_signed_ready_decision_recovers_missing_plan_publication_without_new_execution(tmp_path, monkeypatch):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch)
    try:
        append, hits = truth.append_atomic, []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == 'RC72_N8_RETRY_RECONCILIATION_UPSERTED' and payload['state'] == 'READY' and not hits:
                hits.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        cold = _service(TruthRuntime(truth.store.path))
        cold_diagnosis = ExecutionDiagnosisService(cold, evidence_root=tmp_path / 'diagnosis')
        plan = DataRepairContinuationService(cold_diagnosis).reconcile(failed['preparation_id'])
        row = cold.truth.query('rc72_n8_retry_reconciliation')[0]
        assert row['member_decisions'][0]['preparation_id'] == completed['preparation_id']
        assert len(cold.truth.query('execution_attempt')) == 2 and len(server.calls) == 1
        before = cold.truth.store.path.read_bytes()
        assert DataRepairContinuationService(cold_diagnosis).reconcile(failed['preparation_id']) == plan
        assert cold.truth.store.path.read_bytes() == before
        assert not cold.authority._leases
    finally:
        _close(server)


def test_physical_repair_of_completed_members_data_creates_fresh_child_and_full_independent_review(tmp_path, monkeypatch):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=True)
    try:
        from rc7_runtime.rc72_n8_member_disposition import assert_disposed_member
        original = prep._one('execution_attempt', attempt_id=completed['attempt_id'])
        failed_history = prep._one('execution_attempt', attempt_id=failed['attempt_id'])
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        assert row['member_decisions'][0]['disposition'] == 'REEXECUTE_AFTER_VERIFIED_DRAIN'
        assert prep._one('rc7_task', task_id=completed['workitem_id'])['state'] == 'READY'
        assert prep._one('rc72_n7_execution_preparation', preparation_id=completed['preparation_id'])['status'] == 'INTERRUPTED'
        assert prep._one('rc72_workitem_attempt_binding', binding_id=completed['binding_id'])['state'] == 'SUPERSEDED'
        assert prep.authority.is_lease_revoked(completed['task_lease']['lease_id'])
        assert len(server.calls) == 1
        root = tmp_path / 'all-repaired-members'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        children = []
        for item in plan['items']:
            child = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            children.append(child)
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(child['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(child['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        replacement = next(child for child in children if child['workitem_id'] == completed['workitem_id'])
        assert replacement['attempt_id'] != completed['attempt_id'] and replacement['worker_id'] != completed['worker_id']
        assert replacement['attempt_generation'] == completed['attempt_generation'] + 1
        assert prep._one('rc72_workitem_attempt_binding', binding_id=replacement['binding_id'])['parent_attempt_id'] == completed['attempt_id']
        assert [(item['case_id'], item['etu_id'], item['workitem_id']) for item in plan['items']] == [
            (item['case_id'], item['etu_id'], item['workitem_id']) for item in row['original_plan']['items']]
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-all-repaired')
        bundle = review.build(plan['plan_id'])
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS'
        assert len(server.calls) == len(plan['items']) + 1
        assert len(truth.query('execution_attempt')) == len(plan['items']) + 2
        assert prep._one('execution_attempt', attempt_id=completed['attempt_id']) == original
        assert prep._one('execution_attempt', attempt_id=failed['attempt_id']) == failed_history
        assert_disposed_member(prep, row, row['members'][0])
        cold = _service(TruthRuntime(truth.store.path))
        before = cold.truth.store.path.read_bytes()
        assert_disposed_member(cold, row, row['members'][0])
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=review.capture_root)
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == final
        assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)


def test_forged_task_completion_cannot_enter_historical_finalized_review_branch(tmp_path, monkeypatch):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch)
    try:
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        task = truth.query('rc7_task', task_id=completed['workitem_id'])[0]
        task.update(state='PASS', evaluation_id='FORGED-UNREVIEWED-EVALUATION', artifact_version=task['artifact_version'] + 1)
        truth.append_atomic('RC7_TASK_UPSERTED', task)
        from rc7_runtime.rc72_n7_member_drain import assert_drained_member
        with pytest.raises(ContractError, match='SIGNED_FINAL_REVIEW_REQUIRED'):
            assert_drained_member(prep, completed['preparation_id'], allow_finalized=True)
        assert len(server.calls) == 1
    finally:
        _close(server)
