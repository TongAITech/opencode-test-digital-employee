"""Real repeated data failures preserve earlier repair and execution history."""
import pytest
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
from test_rc72_n8_member_reuse import _repaired
from test_rc72_n5_existing_data_repair import _launcher
from test_rc72_n7_member_drain import _close


def _second_repair(tmp_path, monkeypatch, *, repair_completed=False):
    truth, prep, server, completed, failed, first_diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=repair_completed)
    try:
        child = DataRepairContinuationService(first_diagnosis).prepare_replacement(failed['preparation_id'])
        first_reconciliation = truth.query('rc72_n8_retry_reconciliation')[0]
        failed_refs = {ref['data_ref'] for ref in prep._one('rc72_n6_executable_contract', contract_id=child['contract_id'])['data_refs']}
        server.allowed_data_refs.difference_update(failed_refs)
        root = tmp_path / 'second-failure'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(child['preparation_id'])['state'] == 'FAILED'
        second_diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'second-diagnosis')
        assert second_diagnosis.run(child['preparation_id'])['failure_class'] == 'TEST_DATA_GAP'
        boundary = RepairBoundaryService(second_diagnosis, cleanup_adapters={'api_http': env.cleanup})
        assert boundary.open(child['preparation_id'])['state'] == 'REPAIR_OPEN'
        calls = []
        data = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, prep, server, calls),
                                        allowed_tools=['query-exact-data-ref'])
        for binding in truth.query('rc72_n5_data_binding', release_batch_id=child['release_batch_id']):
            if binding['data_ref'] not in failed_refs:
                continue
            requested = data.request(child['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                     binding_revision=binding['artifact_version'])
            data.prepare(requested['repair_id'], launcher=_launcher(tmp_path, prep, server, calls),
                         allowed_tools=['repair-exact-data-ref'])
            assert data.run(requested['repair_id'])['state'] == 'VERIFIED'
        gate = N5DeliveryGateService(truth, release_id=child['release_id'], source_commit=child['source_commit']).complete(
            release_batch_id=child['release_batch_id'])
        second_diagnosis.record_accepted_repair(child['preparation_id'], repair_delivery_id=gate['delivery']['delivery_id'],
            changed_refs=sorted(failed_refs), reason='independent second exact-data repair after fresh failure')
        return truth, prep, server, completed, failed, child, first_reconciliation, second_diagnosis
    except BaseException:
        _close(server)
        raise


@pytest.mark.parametrize('repair_completed', [False, True])
def test_two_actual_data_repair_rounds_keep_required_disposition_and_both_failed_histories(tmp_path, monkeypatch, repair_completed):
    truth, prep, server, completed, failed, child, first_row, diagnosis = _second_repair(tmp_path, monkeypatch, repair_completed=repair_completed)
    try:
        histories = {p['attempt_id']: prep._one('execution_attempt', attempt_id=p['attempt_id']) for p in (completed, failed, child)}
        second = DataRepairContinuationService(diagnosis).prepare_replacement(child['preparation_id'])
        plan = prep.planning.assert_current(second['plan_id'])
        assert second['attempt_generation'] == child['attempt_generation'] + 1
        assert prep._one('rc72_workitem_attempt_binding', binding_id=second['binding_id'])['parent_attempt_id'] == child['attempt_id']
        assert len(truth.query('rc72_n8_retry_reconciliation')) == 2
        rows = truth.query('rc72_n8_retry_reconciliation', preparation_id=child['preparation_id'])
        assert rows[0]['members'][0]['preparation_id'] == completed['preparation_id']
        assert rows[0]['member_decisions'][0]['disposition'] == ('REEXECUTE_AFTER_VERIFIED_DRAIN' if repair_completed else 'REUSE_FOR_CURRENT_REVIEW')
        assert len(server.calls) == 1
        root = tmp_path / 'third-execution'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        for item in plan['items']:
            if not repair_completed and item['workitem_id'] == completed['workitem_id']:
                continue
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-third')
        bundle = review.build(plan['plan_id'])
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS'
        from rc6_runtime.truth import TruthRuntime
        from test_rc72_n7_execution_preparation import _service
        cold = _service(TruthRuntime(truth.store.path))
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=review.capture_root)
        before = cold.truth.store.path.read_bytes()
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == final
        assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
        assert len(server.calls) == len(plan['items']) + int(repair_completed)
        assert len(truth.query('execution_attempt')) == len(plan['items']) + 2 + int(repair_completed)
        for p in (failed, child):
            assert prep._one('execution_attempt', attempt_id=p['attempt_id']) == histories[p['attempt_id']]
        assert prep._one('rc72_n8_retry_reconciliation', reconciliation_id=first_row['reconciliation_id']) == first_row
        assert len(truth.query('rc72_diagnosis_recovery')) == 2
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)


def test_historical_identity_check_is_read_only_and_cannot_admit_the_stale_previous_plan(tmp_path, monkeypatch):
    import pytest
    from rc7_runtime.models import ContractError
    from rc7_runtime.rc72_n8_retry_truth import verify_reconciled_history
    truth, prep, server, completed, failed, child, first_row, diagnosis = _second_repair(tmp_path, monkeypatch)
    try:
        old = prep._one('rc72_n7_execution_plan', plan_id=child['plan_id'])
        before, permissions = truth.store.path.read_bytes(), dict(prep.authority._leases)
        assert verify_reconciled_history(prep.planning, old) == first_row
        with pytest.raises(ContractError):
            prep.planning.assert_current(old['plan_id'])
        assert truth.store.path.read_bytes() == before and prep.authority._leases == permissions
        assert len(server.calls) == 1
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['historical_admission', 'ancestor_signature', 'origin_capture'])
def test_altered_ancestor_or_original_member_cannot_enter_a_new_round(tmp_path, monkeypatch, change):
    from pathlib import Path
    from rc7_runtime.models import ContractError
    truth, prep, server, completed, failed, child, first_row, diagnosis = _second_repair(tmp_path, monkeypatch)
    try:
        if change == 'historical_admission':
            old_plan = prep._one('rc72_n7_execution_plan', plan_id=child['plan_id'])
            admission = prep._one('rc72_n7_execution_admission', admission_id=old_plan['items'][0]['admission_id'])
            admission.update(input_digest='0' * 64, artifact_version=admission['artifact_version'] + 1)
            truth.append_atomic('RC72_N7_EXECUTION_ADMISSION_UPSERTED', admission)
            expected = 'HISTORICAL_ADMISSION_OR_CONTRACT_CHANGED'
        elif change == 'ancestor_signature':
            old = dict(first_row, artifact_version=first_row['artifact_version'] + 1)
            old['member_decisions'][0]['attempt_id'] = 'UNRELATED-ATTEMPT'
            truth.append_atomic('RC72_N8_RETRY_RECONCILIATION_UPSERTED', old)
            expected = 'RECONCILIATION_SIGNATURE_INVALID'
        else:
            Path(first_row['members'][0]['captured_evidence'][0]['content_ref'][len('file://'):]).write_bytes(b'changed')
            expected = 'CAPTURE_BYTES_CHANGED'
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match=expected):
            DataRepairContinuationService(diagnosis).reconcile(child['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert len(truth.query('rc72_n8_retry_reconciliation')) == 1
        assert len(server.calls) == 1 and len(truth.query('execution_attempt')) == 3
    finally:
        _close(server)


@pytest.mark.parametrize('stage', ['planned', 'ready', 'published'])
def test_second_round_cold_roll_forward_keeps_original_member_and_no_duplicate_actions(tmp_path, monkeypatch, stage):
    _resume_second_round(tmp_path, monkeypatch, stage=stage)


def _resume_second_round(tmp_path, monkeypatch, *, stage, repair_completed=False):
    from rc6_runtime.truth import TruthRuntime
    from test_rc72_n7_execution_preparation import _service
    truth, prep, server, completed, failed, child, first_row, diagnosis = _second_repair(tmp_path, monkeypatch, repair_completed=repair_completed)
    try:
        pending_before = {kind: prep._one(kind, **{key: completed[value]}) for kind, key, value in (
            ('rc7_task', 'task_id', 'workitem_id'), ('rc72_n7_execution_preparation', 'preparation_id', 'preparation_id'),
            ('rc72_workitem_attempt_binding', 'binding_id', 'binding_id'))} if repair_completed else {}
        before_histories = truth.query('execution_attempt')
        physical_repairs = list(server.repair_calls)
        append, hits = truth.append_atomic, []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            selected = (stage in {'planned', 'ready'} and kind == 'RC72_N8_RETRY_RECONCILIATION_UPSERTED'
                        and payload['state'] == stage.upper() and payload['preparation_id'] == child['preparation_id']
                        or stage == 'published' and kind == 'RC72_N7_EXECUTION_PLAN_UPSERTED')
            if selected and not hits:
                hits.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            DataRepairContinuationService(diagnosis).reconcile(child['preparation_id'])
        cold = _service(TruthRuntime(truth.store.path))
        resumed = DataRepairContinuationService(ExecutionDiagnosisService(cold, evidence_root=tmp_path / 'second-diagnosis'))
        plan = resumed.reconcile(child['preparation_id'])
        record = cold.truth.query('rc72_n8_retry_reconciliation', preparation_id=child['preparation_id'])[0]
        assert record['member_decisions'][0]['preparation_id'] == completed['preparation_id']
        assert record['members'][0] == first_row['members'][0]
        assert record['member_decisions'][0]['disposition'] == ('REEXECUTE_AFTER_VERIFIED_DRAIN' if repair_completed else 'REUSE_FOR_CURRENT_REVIEW')
        for kind, before_projection in pending_before.items():
            key = {'rc7_task': 'task_id', 'rc72_n7_execution_preparation': 'preparation_id',
                   'rc72_workitem_attempt_binding': 'binding_id'}[kind]
            assert cold._one(kind, **{key: before_projection[key]}) == before_projection
        assert cold.truth.query('execution_attempt') == before_histories
        assert len(server.calls) == 1 and server.repair_calls == physical_repairs
        before = cold.truth.store.path.read_bytes()
        assert resumed.reconcile(child['preparation_id']) == plan
        assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
    finally:
        _close(server)
