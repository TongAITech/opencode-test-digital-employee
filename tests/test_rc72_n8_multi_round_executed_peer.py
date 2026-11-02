"""Fresh regression evidence replaces invalidated root evidence across repairs."""
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc72_formal_runner_support import LocalHTTPEnvironment
from test_rc72_n8_multi_round import _second_repair
from test_rc72_n7_member_drain import _close
from test_rc72_n7_execution_preparation import _service


def test_second_round_reuses_actual_regression_peer_not_invalidated_original_result(tmp_path, monkeypatch):
    truth, prep, server, peer, failed, child, first_row, diagnosis = _second_repair(
        tmp_path, monkeypatch, repair_completed=True, execute_peer=True)
    try:
        root_p = first_row['members'][0]['original_preparation']
        original_histories = {p['attempt_id']: prep._one('execution_attempt', attempt_id=p['attempt_id'])
                              for p in (root_p, failed, child)}
        assert peer['attempt_id'] != root_p['attempt_id']
        assert len(server.calls) == 2
        successor = DataRepairContinuationService(diagnosis).prepare_replacement(child['preparation_id'])
        plan = prep.planning.assert_current(successor['plan_id'])
        second_row = prep._one('rc72_n8_retry_reconciliation', preparation_id=child['preparation_id'])
        assert second_row['member_decisions'][0]['disposition'] == 'REUSE_FOR_CURRENT_REVIEW'
        assert second_row['member_decisions'][0]['attempt_id'] == peer['attempt_id']
        assert second_row['members'][0]['preparation_id'] == peer['preparation_id']
        assert prep._one('rc72_n7_execution_preparation', preparation_id=root_p['preparation_id'])['status'] == 'INTERRUPTED'
        root = tmp_path / 'latest-regression'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(successor['preparation_id'])['state'] == 'RETURNED'
        assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(successor['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-latest-regression')
        bundle = review.build(plan['plan_id'])
        assert next(c for c in bundle['case_results'] if c['case_id'] == peer['case_id'])['attempt_id'] == peer['attempt_id']
        final = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert final['state'] == 'N7_PASS' and len(bundle['case_results']) == len(plan['items'])
        assert len(server.calls) == len(plan['items']) + 1
        assert len(truth.query('execution_attempt')) == len(plan['items']) + 3
        for attempt_id, history in original_histories.items():
            assert prep._one('execution_attempt', attempt_id=attempt_id) == history
        cold = _service(TruthRuntime(truth.store.path))
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=review.capture_root)
        before = cold.truth.store.path.read_bytes()
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == final
        assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)
