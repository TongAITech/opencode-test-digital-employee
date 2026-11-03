"""Accepted native coverage repair invalidates the original N7/Libra epoch."""
import pytest

from rc72_n2_test_support import BATCH
from test_rc72_native_coverage_diagnosis import _diagnosis
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import Artifact,Evidence,Evaluation,EvaluationResult,ContractError
from rc7_runtime.truth_overlay import append_entity
from rc7_runtime.rc72_libra_measurement import NativeLibraMeasurementService
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_n10_control import NativeN10ControlService


def _accept_task(truth,release_id,task_id,capability):
    task=truth.query('rc7_task',task_id=task_id)[0]
    control=ClosedLoopControlPlane(truth,release_id,task['mission_id'])
    worker='TEST-W-'+task_id[-16:]
    if task['state'] in {'REGISTERED','READY'}:
        leased=control.lease_next(worker_ref=worker,capabilities=[capability])
        assert leased is not None and leased.task_id==task_id
        task=truth.query('rc7_task',task_id=task_id)[0]
    if task['state']=='LEASED':
        control.start(task_id,worker_ref=worker)
        task=truth.query('rc7_task',task_id=task_id)[0]
    worker=task['lease_owner']
    evidence_id='TEST-EV-'+task_id
    artifact_id='TEST-ART-'+task_id
    if not truth.query('rc7_evidence',evidence_id=evidence_id):
        append_entity(truth,Evidence(evidence_id=evidence_id,mission_id=task['mission_id'],kind='ACTUAL_REPAIR_TEST_PROOF',
            source_ref='test://accepted-worker/'+task_id,content_ref='test://evidence/'+task_id,
            content_hash='a'*64,subject_refs=[task_id]),release_id=release_id)
    artifact=Artifact(artifact_id=artifact_id,mission_id=task['mission_id'],artifact_type='RC72_ACCEPTED_WORK_PROOF',
        producer_task_id=task_id,content_ref='test://artifact/'+task_id,content_hash='b'*64,
        parent_refs=task['input_artifact_refs'],evidence_refs=[evidence_id])
    control.submit_worker_output(WorkerOutput(task_id=task_id,worker_ref=worker,artifacts=(artifact,)))
    control.accept_evaluation(task_id,evaluation=Evaluation(evaluation_id='TEST-EVAL-'+task_id,mission_id=task['mission_id'],
        node=task['node'],artifact_refs=[artifact_id],result=EvaluationResult.PASS,evaluator_ref='independent-test-reviewer',
        evidence_refs=[evidence_id]))
    return truth.query('rc7_task',task_id=task_id)[0]


def test_accepted_repair_opens_signed_fresh_n7_fence_and_n10_refuses_old_epoch(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        diagnosed=diagnosis.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        repair=NativeCoverageRepairService(diagnosis)
        pending=repair.prepare(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert pending['reason']=='COVERAGE_PATH_INVESTIGATION_NOT_ACCEPTED'
        assert not truth.query('rc72_native_coverage_repair')
        _accept_task(truth,pipeline.release_id,diagnosed['investigation_workitem_id'],'coverage_path_investigation')
        prepared=repair.prepare(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        repair_task=truth.query('rc7_task',task_id=prepared['repair_workitem_id'])[0]
        assert repair_task['task_type']=='COVERAGE_PATH_REPAIR_EXECUTION'
        assert repair_task['gap_refs']==[gap] and repair_task['required_capabilities']==['coverage_path_repair']
        not_applied=repair.activate(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert not_applied['reason']=='COVERAGE_PATH_REPAIR_EXECUTION_NOT_ACCEPTED'
        assert not truth.query('rc72_native_coverage_repair')
        _accept_task(truth,pipeline.release_id,prepared['repair_workitem_id'],'coverage_path_repair')
        activated=repair.activate(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert activated['status']=='FRESH_N7_REQUIRED'
        boundary=truth.query('rc72_native_coverage_repair')[0]
        assert boundary['origin_measurement_id']==truth.query('rc72_native_coverage_diagnosis')[0]['measurement_id']
        assert boundary['state']=='FRESH_N7_REQUIRED'
        assert 'product_defect' not in boundary and not truth.query('rc7_defect')
        calls=len(server.calls);business_calls=len(business.calls);before=truth.store.path.read_bytes()
        blocked=diagnosis.measurement.collect(release_batch_id=BATCH,application_id=server.app)
        assert blocked['reason']=='LIBRA_POST_REPAIR_FRESH_N7_REQUIRED'
        cold=NativeLibraMeasurementService(diagnosis.measurement.expected_scope,diagnosis.measurement.n9,capture_root=diagnosis.measurement.root)
        with pytest.raises(ContractError,match='LIBRA_POST_REPAIR_FRESH_N7_REQUIRED'):
            cold.audit(release_batch_id=BATCH,application_id=server.app)
        assert truth.store.path.read_bytes()==before and len(server.calls)==calls and len(business.calls)==business_calls
        control=NativeN10ControlService(diagnosis.measurement.expected_scope,diagnosis.measurement.n9,
            diagnosis.measurement,diagnosis.intake,diagnosis,repair=repair)
        result=control.complete(release_batch_id=BATCH)
        assert result['reason']=='N10_COVERAGE_INVESTIGATION_REQUIRED'
        assert result['holds'][0]['reason']=='N10_POST_REPAIR_FRESH_N7_REQUIRED'
        assert len(server.calls)==calls and len(business.calls)==business_calls
        # Cold/repeated activation only audits the accepted repair; it never repeats work or changes R1.
        assert repair.activate(release_batch_id=BATCH,application_id=server.app,gap_id=gap)==activated
        assert truth.store.path.read_bytes()==before and len(server.calls)==calls
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_ambiguous_gap_cannot_create_repair_work_or_fence(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap=_diagnosis(tmp_path,monkeypatch,single=False)
    try:
        hold=diagnosis.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert hold['reason']=='COVERAGE_UNIQUE_MAPPING_INVESTIGATION_REQUIRED'
        repair=NativeCoverageRepairService(diagnosis)
        before=truth.store.path.read_bytes()
        result=repair.prepare(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert result['reason']=='ACCEPTED_COVERAGE_PATH_DIAGNOSIS_REQUIRED'
        assert truth.store.path.read_bytes()==before
        assert not truth.query('rc72_native_coverage_repair')
        assert not any(task['task_type']=='COVERAGE_PATH_REPAIR_EXECUTION' for task in truth.query('rc7_task'))
        assert not truth.query('rc7_defect')
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()
