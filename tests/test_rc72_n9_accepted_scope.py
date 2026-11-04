"""Actual formal execution/review -> deterministic N9 clearance; not Field."""
from rc72_pip_field_test_support import provider as prior_field_provider
from pathlib import Path
import pytest

from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc72_formal_runner_support import formal_setup,LocalHTTPEnvironment
from rc72_n2_test_support import BATCH,MISSION


def _accepted(tmp_path,monkeypatch):
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    out=tmp_path/'output'
    runner=FormalN7RunnerAdapter(prep,evidence_root=out,environment_adapter=LocalHTTPEnvironment(url,out),
        execution_env={'RC72_OUTPUT_ROOT':str(out)},timeout_seconds=30)
    pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
    return truth,plan,pipeline,server


def test_real_accepted_scope_enters_n10_without_new_business_io_and_reaudits_evidence(tmp_path,monkeypatch):
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        n9=AcceptedScopeN9Service(pipeline)
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='ACCEPTED_N7_REQUIRED'):n9.complete(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before
        pipeline.complete(release_batch_id=BATCH)
        result=n9.complete(release_batch_id=BATCH)
        assert result['state']=='N9_PASS'
        assert truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]['state']=='READY'
        assert truth.query('rc7_mission',mission_id=MISSION)[0]['state']!='CONVERGED'
        assert len(server.calls)==len(plan['items'])
        before=truth.store.path.read_bytes()
        assert n9.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(plan['items'])
        receipt=truth.query('rc72_n7_execution_review')[0]
        path=Path(receipt['stdout_ref'][7:]);path.write_bytes(path.read_bytes()+b'tampered')
        with pytest.raises(Exception,match='PROCESS_EVIDENCE_CHANGED'):n9.complete(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before
    finally:server.shutdown();server.server_close()


def test_open_gap_prevents_clearance_and_new_gap_prevents_completed_replay(tmp_path,monkeypatch):
    from rc7_runtime.models import Gap,GapSeverity
    from rc7_runtime.truth_overlay import append_entity
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        n9=AcceptedScopeN9Service(pipeline)
        gap=Gap(gap_id='N9-ACTUAL-INTAKE',mission_id=MISSION,source_node='N8_DIAGNOSIS_RECOVERY',
            target_node='DEFECT',category='VALID_TEST_FAILURE',severity=GapSeverity.HIGH,description='requires professional qualification')
        append_entity(truth,gap,release_id=pipeline.release_id)
        before=truth.store.path.read_bytes()
        blocked=n9.complete(release_batch_id=BATCH)
        assert blocked['reason']=='N9_PROFESSIONAL_DISPOSITION_REQUIRED'
        assert blocked['blockers']==['gap:N9-ACTUAL-INTAKE']
        assert truth.store.path.read_bytes()==before and not truth.query('rc72_n9_accepted_scope')
        row=truth.query('rc7_gap',gap_id=gap.gap_id)[0]
        row.update(state='RESOLVED',resolution_evaluation_id='unverified-caller-evaluation',artifact_version=row['artifact_version']+1)
        truth.append_atomic('RC7_GAP_UPSERTED',row)
        before=truth.store.path.read_bytes()
        blocked=n9.complete(release_batch_id=BATCH)
        assert blocked['status']=='HOLD'
        assert blocked['blockers']==['professional-gap-history:N9-ACTUAL-INTAKE']
        assert truth.store.path.read_bytes()==before and not truth.query('rc72_n9_accepted_scope')
        assert len(server.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close()


@pytest.mark.parametrize('point',['delivery','gate','passed','forward'])
def test_interrupted_n9_metadata_resumes_original_clearance_without_execution(tmp_path,monkeypatch,point):
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        n9=AcceptedScopeN9Service(pipeline)
        original=truth.append_atomic
        hit=[]
        def append(event,row,**kwargs):
            result=original(event,row,**kwargs)
            match=(point=='delivery' and event=='RC72_NODE_DELIVERY_UPSERTED' and row.get('node_type')=='N9_DEFECT'
                or point=='gate' and event=='RC72_NODE_GATE_UPSERTED' and row.get('node_type')=='N9_DEFECT'
                or point=='passed' and event=='RC72_MISSION_NODE_UPSERTED' and row.get('node_type')=='N9_DEFECT' and row['state']=='PASS'
                or point=='forward' and event=='RC72_MISSION_NODE_UPSERTED' and row.get('node_type')=='N10_RELEASE_CONVERGENCE' and row['state']=='READY')
            if match and not hit:hit.append(1);raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth,'append_atomic',append)
        with pytest.raises(KeyboardInterrupt):n9.complete(release_batch_id=BATCH)
        monkeypatch.setattr(truth,'append_atomic',original)
        assert AcceptedScopeN9Service(pipeline).complete(release_batch_id=BATCH)['state']=='N9_PASS'
        assert len(truth.query('rc72_n9_accepted_scope'))==1
        assert len(truth.query('rc72_node_gate',node_type='N9_DEFECT'))==1
        assert len(server.calls)==len(plan['items'])
        before=truth.store.path.read_bytes()
        assert n9.complete(release_batch_id=BATCH)['state']=='N9_PASS'
        assert truth.store.path.read_bytes()==before
    finally:server.shutdown();server.server_close()


def test_actual_n9_service_is_composable_with_controller_and_cannot_accept_scope_swaps(tmp_path,monkeypatch):
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    import sys
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        patch=tmp_path/'patch.json';patch.write_text('{}')
        def launcher(role):
            def never(*a,**k):pytest.fail('accepted-prefix replay launched upstream worker')
            return DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),
                truth=truth,authority=RC72AuthorityRuntime(('test-controller-'+role).encode()),
                coordinator_instance_id='controller',release_id=pipeline.release_id,state_root=str(tmp_path/role),command_runner=never)
        n1,n2,review=launcher('n1'),launcher('n2'),launcher('review')
        n9=AcceptedScopeN9Service(pipeline)
        driver=ReleaseBatchDriver(truth,source_commit=pipeline.source_commit,bank_pip_mirror=prior_field_provider(truth,source_commit=pipeline.source_commit),n1_launcher=n1,n1_tools=['field-probe'],
            n2_launcher=n2,n2_tools=['requirement-probe'],n2_evaluator=DshRequirementEvaluator(review,allowed_tools=['review-probe']),
            n7_pipeline=pipeline,n9_pipeline=n9)
        # This small formal fixture intentionally lacks the full N4 parent
        # denominator, so it cannot qualify the entire controller prefix.
        # The full original 28-Case product test covers that route separately.
        batch=truth.query('rc72_release_batch',release_batch_id=BATCH)[0]
        assert driver._complete_gate('N9_DEFECT',batch)['state']=='N9_PASS'
        assert driver._diagnosis_bypassed(driver.status(release_batch_id=BATCH)['nodes'],MISSION)
        assert driver._has_gate('N9_DEFECT')
        clearance=truth.query('rc72_n9_accepted_scope')[0]
        original_signature=clearance['signature']
        clearance.update(signature='0'*64,artifact_version=clearance['artifact_version']+1)
        truth.append_atomic('RC72_N9_ACCEPTED_SCOPE_UPSERTED',clearance)
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='N9_ACCEPTED_SCOPE_SIGNATURE_INVALID'):
            driver._complete_gate('N9_DEFECT',batch)
        assert truth.store.path.read_bytes()==before
        clearance.update(signature=original_signature,artifact_version=clearance['artifact_version']+1)
        truth.append_atomic('RC72_N9_ACCEPTED_SCOPE_UPSERTED',clearance)
        before=truth.store.path.read_bytes()
        n9.source_commit='0'*40
        with pytest.raises(Exception,match='N9_PIPELINE_SCOPE_MISMATCH'):driver._assert_n9_scope()
        assert truth.store.path.read_bytes()==before
    finally:server.shutdown();server.server_close()


def test_full_real_n7_to_n9_allows_genuinely_closed_product_defect_without_reexecution(
        tmp_path, monkeypatch):
    import test_rc7_defect_resolution_control as defects
    from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
    truth, plan, pipeline, server = _accepted(tmp_path, monkeypatch)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['state'] == 'N7_PASS'
        original_calls = len(server.calls)
        assert original_calls == len(plan['items'])
        # Reuse this exact real N7/R1 Mission with the inherited formal
        # DefectResolutionControl, not a parallel fake defect workspace.
        monkeypatch.setattr(defects, 'MISSION', MISSION)
        monkeypatch.setattr(defects, 'RELEASE', pipeline.release_id)
        control = ClosedLoopControlPlane(truth, pipeline.release_id, MISSION)
        defects._setup(tmp_path, existing_truth=truth, existing_control=control)
        n9 = AcceptedScopeN9Service(pipeline)
        assert n9.complete(release_batch_id=BATCH)['status'] == 'HOLD'
        resolution, revision = defects._confirm_and_detect_fix(tmp_path, truth, control)
        verification = defects._owned_execution(
            tmp_path, control, artifact_id='ART-VERIFY-1',
            attempt_id='ATT-VERIFY-1', tc_id=defects.ORIGINAL_TC,
            passed=True, task_type=resolution.FIX_VERIFICATION_TASK_TYPE)
        resolution.accept_fix_verification(
            control, defects.DEFECT_ID,
            verification_artifact_id=verification.artifact_id)
        regression = defects._owned_execution(
            tmp_path, control, artifact_id='ART-REGRESSION-1',
            attempt_id='ATT-REGRESSION-1', tc_id='TC-IMPACT-REGRESSION',
            passed=True, task_type=resolution.IMPACT_REGRESSION_TASK_TYPE)
        resolution.close_after_verification(
            control, defects.DEFECT_ID,
            verification_artifact_id=verification.artifact_id,
            regression_artifact_ids=[regression.artifact_id])
        signed_before = truth.store.path.read_bytes()
        accepted = n9.complete(release_batch_id=BATCH)
        assert accepted['state'] == 'N9_PASS'
        assert truth.query('rc72_mission_node', node_type='N9_DEFECT')[0]['state'] == 'PASS'
        assert truth.query('rc72_mission_node', node_type='N10_RELEASE_CONVERGENCE')[0]['state'] == 'READY'
        assert len(server.calls) == original_calls
        repeat = truth.store.path.read_bytes()
        assert n9.complete(release_batch_id=BATCH) == accepted
        assert truth.store.path.read_bytes() == repeat
        assert len(server.calls) == original_calls
    finally:
        server.shutdown()
        server.server_close()
