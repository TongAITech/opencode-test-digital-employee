from pathlib import Path
import pytest
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter, verified_formal_receipt, FormalRunnerError
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment


def test_actual_http_target_and_real_runner_feed_the_same_signed_attempt_and_review(tmp_path, monkeypatch):
    monkeypatch.setenv('RC72_PARENT_SECRET', 'must-not-reach-business-runner')
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        output = tmp_path / 'actual-output'
        environment = LocalHTTPEnvironment(url, output)
        runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                      execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
        for item in plan['items']:
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            dispatch = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
            assert dispatch['state'] == 'RETURNED', dispatch
            c = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
            proof = verified_formal_receipt(prep, p, c, dispatch['raw_result'])
            assert proof['worker_id'] == p['worker_id'] and proof['attempt_id'] == p['attempt_id']
            assert proof['runner_result']['exit_code'] == 0
            assert proof['required_tool_observed'] is True
            attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
            assert attempt['target_identity_scope'] == 'FULL_TARGET_IDENTITY'
            assert attempt['target_id'].startswith('TARGET-')
            assert attempt['status'] == 'BLOCKED'
            ExecutionCleanupService(prep, adapters={'api_http': environment.cleanup}).run(p['preparation_id'])
        assert len(server.calls) == len(plan['items'])
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=output, capture_root=tmp_path / 'captured')
        bundle = review.build(plan['plan_id'])
        assert bundle['known_gaps'] == []
        admitted = review.request_review(bundle['bundle_id'])
        assert admitted['state'] == 'REVIEW_PENDING'
        from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
        from rc6_runtime.truth import TruthRuntime
        from test_rc72_n7_execution_preparation import _service
        result = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert result['state'] == 'N7_PASS'
        assert result['field_verified'] is False and result['bank_final'] is False
        assert {row['status'] for row in truth.query('execution_attempt')} == {'PASS'}
        assert {row['state'] for row in truth.query('rc7_task', task_type='RC72_CASE_EXECUTION')} == {'PASS'}
        assert truth.query('rc72_mission_node', mission_id=plan['mission_id'], node_type='N9_DEFECT')[0]['state'] == 'READY'
        process_review = truth.query('rc72_n7_execution_review')[0]
        assert process_review['pid'] > 0 and process_review['exit_code'] == 0
        assert process_review['verdict'] == 'PASS'
        from rc7_runtime.closed_loop_control import ClosedLoopControlPlane, ClosedLoopControlError
        from rc7_runtime.models import Evaluation, EvaluationResult
        control = ClosedLoopControlPlane(truth, prep.release_id, plan['mission_id'])
        fake_completion = Evaluation(evaluation_id='NO-PREMATURE-MISSION-COMPLETION', mission_id=plan['mission_id'],
            node='MISSION_EVALUATION', artifact_refs=[bundle['bundle_id']], result=EvaluationResult.PASS,
            evaluator_ref='legacy-mission-evaluator', dimensions={'sufficiency_state': 'SUFFICIENT'})
        before = list(truth.store.iter_raw())
        with pytest.raises(ClosedLoopControlError, match='RC72_N10_ACCEPTED_GATE_REQUIRED'):
            control.converge_mission(fake_completion)
        assert list(truth.store.iter_raw()) == before
        before = list(truth.store.iter_raw())
        assert ExecutionFinalizationService(review).finalize(bundle['bundle_id']) == result
        assert list(truth.store.iter_raw()) == before
        replay = TruthRuntime(truth.store.path)
        restored = ExecutionEvidenceReviewService(_service(replay), adapter_output_root=output, capture_root=tmp_path / 'captured')
        before = list(replay.store.iter_raw())
        assert ExecutionFinalizationService(restored).finalize(bundle['bundle_id']) == result
        assert list(replay.store.iter_raw()) == before
    finally:
        server.shutdown()
        server.server_close()


def test_partial_success_cannot_hide_runner_process_failure(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch, fail=True)
    try:
        output = tmp_path / 'actual-output'
        environment = LocalHTTPEnvironment(url, output)
        runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                      execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        receipt = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert receipt['state'] == 'RETURNED'
        attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
        assert attempt['assertion_passed'] is True
        assert attempt['reason'] == 'RUNNER_PROCESS_FAILED'
        diagnosis = ExecutionEvidenceService(prep).begin_diagnosis(p['preparation_id'])
        assert diagnosis.worker_id != p['worker_id']
    finally:
        server.shutdown()
        server.server_close()


def test_actual_parent_call_does_not_require_a_child_reported_tool_name(tmp_path,monkeypatch):
    from rc7_runtime.rc72_n7_pipeline import N7PipelineService
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,emit_tool=False)
    try:
        output=tmp_path/'actual-output'
        runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
            execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
        result=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured').complete(release_batch_id=plan['release_batch_id'])
        assert result['state']=='N7_PASS' and len(server.calls)==len(plan['items'])
        rows=truth.query('rc72_n7_formal_runner_receipt')
        assert all(r['native_http_protocol']=='RC72_NATIVE_API_HTTP_V1' and r['required_tool_observed'] for r in rows)
        assert all(not any(c['tool_id']=='api_http' for c in r['runner_result']['tool_calls']) for r in rows)
    finally:
        server.shutdown();server.server_close()
