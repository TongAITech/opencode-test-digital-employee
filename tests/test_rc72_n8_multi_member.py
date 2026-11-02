"""Actual mixed REUSE/REEXECUTE peers retain the complete three-Case denominator."""
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc72_formal_runner_support import LocalHTTPEnvironment
from rc72_multi_member_support import mixed_member_repair
from test_rc72_n7_member_drain import _close
from test_rc72_n7_execution_preparation import _service


def test_three_original_cases_with_mixed_member_decisions_get_full_independent_review(tmp_path, monkeypatch):
    truth, prep, server, old_plan, peers, failed, diagnosis = mixed_member_repair(tmp_path, monkeypatch)
    try:
        original = {p['attempt_id']: prep._one('execution_attempt', attempt_id=p['attempt_id']) for p in (peers[0], failed)}
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        assert len(row['members']) == 2
        assert [d['disposition'] for d in row['member_decisions']] == ['REEXECUTE_AFTER_VERIFIED_DRAIN', 'REUSE_FOR_CURRENT_REVIEW']
        assert [(i['case_id'], i['etu_id'], i['workitem_id']) for i in plan['items']] == [
            (i['case_id'], i['etu_id'], i['workitem_id']) for i in old_plan['items']]
        root = tmp_path / 'multiple-current-executions'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        children = []
        for item in plan['items']:
            if item['workitem_id'] == peers[1]['workitem_id']:
                continue
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            children.append(p)
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        first_child = next(p for p in children if p['workitem_id'] == peers[0]['workitem_id'])
        assert prep._one('rc72_workitem_attempt_binding', binding_id=first_child['binding_id'])['parent_attempt_id'] == peers[0]['attempt_id']
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-multiple-current')
        bundle = review.build(plan['plan_id'])
        assert len(bundle['case_results']) == 3
        assert next(c for c in bundle['case_results'] if c['case_id'] == peers[1]['case_id'])['attempt_id'] == peers[1]['attempt_id']
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS' and len(server.calls) == 4
        assert len(truth.query('execution_attempt')) == 5 and len(truth.query('rc72_decomposition_snapshot')) == 1
        for attempt_id, history in original.items():
            assert prep._one('execution_attempt', attempt_id=attempt_id) == history
        cold = _service(TruthRuntime(truth.store.path))
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=review.capture_root)
        before = cold.truth.store.path.read_bytes()
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == final
        assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)
