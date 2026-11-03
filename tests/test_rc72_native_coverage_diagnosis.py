"""Actual independent process routing, never product-defect causality or Field."""
import pytest
from test_rc72_libra_measurement import _setup
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
from rc7_runtime.rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService


def _diagnosis(tmp_path,monkeypatch,*,single=True):
    import rc72_n2_test_support as base
    if single:
        # A fresh one-Requirement original batch; never amend an admitted scope.
        import test_rc72_n2_completion as n2
        import test_rc72_n3_completion as n3
        import test_rc72_n4_parent_truth as n4
        for module in (base,n2,n3,n4):monkeypatch.setattr(module,'REQUIREMENTS',[base.REQUIREMENTS[0]])
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch)
    obligations=truth.query('rc72_test_obligation');code=obligations[0]['code_slice_refs'][0]
    def target(row):
        for unit in row['units']:unit['code_slice']=code
    server.mutate=target
    try:
        measurement.collect(release_batch_id=BATCH,application_id=server.app)
        intake=NativeCoverageGapIntakeService(measurement)
        admitted=intake.intake(release_batch_id=BATCH,application_id=server.app)
        service=NativeCoveragePathDiagnosisService(intake,evidence_root=tmp_path/'actual-coverage-diagnosis')
        return truth,plan,pipeline,business,server,service,admitted['gap_ids'][0]
    except BaseException:server.shutdown();server.server_close();business.shutdown();business.server_close();raise


def test_observed_uncovered_path_independently_classifies_and_queues_original_n8_work(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        assert truth.query('rc72_coverage_gap',gap_id=gap)[0]['status']=='MAPPED'
        result=service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        receipt=truth.query('rc72_native_coverage_diagnosis')[0]
        assert receipt['diagnostic_process']['pid']!=receipt['review_process']['pid']
        assert receipt['result']['reason']=='PATH_NOT_REACHED'
        assert not truth.query('rc7_defect')
        classified=truth.query('rc72_coverage_gap',gap_id=gap)[0]
        assert classified['status']=='CLASSIFIED' and classified['responsible_nodes']==['N8_DIAGNOSIS_RECOVERY']
        queued=truth.query('rc7_task',task_id=result['investigation_workitem_id'])[0]
        assert queued['task_type']=='COVERAGE_PATH_INVESTIGATION' and queued['state'] in {'REGISTERED','READY'}
        assert queued['gap_refs']==[gap] and queued['evaluation_id'] is None
        assert truth.query('rc7_task',task_id=receipt['workitem_id'])[0]['state']=='PASS'
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
        before=truth.store.path.read_bytes()
        assert service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)==result
        assert service.audit(release_batch_id=BATCH,application_id=server.app,gap_id=gap)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
        from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
        aggregator=ReleaseConvergenceAggregator(truth,release_id=pipeline.release_id,runtime=service.measurement.n9.runtime,
            execution_proof=AcceptedObligationExecutionProof(pipeline),expected_scope=service.measurement.expected_scope,
            coverage_proof=service.measurement,coverage_intake=service.intake)
        unverified=aggregator.aggregate(mission_id=receipt['mission_id'])
        assert 'coverage:NATIVE_DIAGNOSIS_PROOF_REQUIRED' in unverified.blockers
        assert unverified.facts.no_unresolved_gaps is False
        aggregator.coverage_diagnosis=service
        admitted=aggregator.aggregate(mission_id=receipt['mission_id'])
        assert 'coverage:NATIVE_DIAGNOSIS_PROOF_REQUIRED' not in admitted.blockers
        assert admitted.facts.no_unresolved_gaps is False and admitted.facts.no_blocked_workitems is False
        classified=truth.query('rc72_coverage_gap',gap_id=gap)[0]
        truth.append_atomic('RC72_COVERAGE_GAP_UPSERTED',dict(classified,status='RESOLVED',
            resolution_verification_id='caller-fake-proof',resolved_at=classified['created_at'],artifact_version=classified['artifact_version']+1))
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='ACCEPTED_CLOSURE_REQUIRED'):
            aggregator.aggregate(mission_id=receipt['mission_id'])
        # Scope snapshots may be emitted by aggregation, but no business/read/process is replayed.
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_ambiguous_original_mapping_does_not_invent_diagnosis_or_professional_work(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service,gap=_diagnosis(tmp_path,monkeypatch,single=False)
    try:
        assert truth.query('rc72_coverage_gap',gap_id=gap)[0]['status']=='AMBIGUOUS'
        before=truth.store.path.read_bytes()
        result=service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert result['reason']=='COVERAGE_UNIQUE_MAPPING_INVESTIGATION_REQUIRED'
        assert truth.store.path.read_bytes()==before and not truth.query('rc72_native_coverage_diagnosis')
        assert len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_diagnosis_returned_metadata_resumes_without_new_process_or_http(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        accept=service._accept
        def interrupted(*args):raise RuntimeError('injected before classification metadata')
        monkeypatch.setattr(service,'_accept',interrupted)
        with pytest.raises(RuntimeError,match='classification metadata'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert truth.query('rc72_native_coverage_diagnosis')[0]['state']=='RETURNED'
        monkeypatch.setattr(service,'_accept',accept)
        def forbidden(*args):raise AssertionError('no process replay')
        monkeypatch.setattr(service,'_process',forbidden)
        result=service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert result['status']=='COVERAGE_PATH_DIAGNOSIS_QUEUED' and len(server.calls)==1
        row=truth.query('rc72_native_coverage_diagnosis')[0]
        task=truth.query('rc7_task',task_id=row['workitem_id'])[0]
        artifact=truth.query('rc7_artifact',artifact_id=task['output_artifact_refs'][0])[0]
        truth.append_atomic('RC7_ARTIFACT_UPSERTED',dict(artifact,content_hash='0'*64,artifact_version=artifact['artifact_version']+1))
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='ACCEPTED_PROOF_CHANGED'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_unknown_actual_diagnosis_process_never_replays_or_classifies(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service,gap=_diagnosis(tmp_path,monkeypatch)
    calls=[];process=service._process
    def interrupted(*args):
        calls.append(1);process(*args);raise RuntimeError('injected after actual diagnostic process')
    monkeypatch.setattr(service,'_process',interrupted)
    try:
        with pytest.raises(RuntimeError,match='actual diagnostic process'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='UNKNOWN_PROCESS_NO_REPLAY'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert truth.store.path.read_bytes()==before and calls==[1] and len(server.calls)==1
        assert truth.query('rc72_coverage_gap',gap_id=gap)[0]['status']=='MAPPED'
        assert not any(t['task_type']=='COVERAGE_PATH_INVESTIGATION' for t in truth.query('rc7_task'))
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_validly_signed_wrong_reason_and_changed_review_capture_are_rejected(tmp_path,monkeypatch):
    from pathlib import Path
    truth,plan,pipeline,business,server,service,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        receipt=truth.query('rc72_native_coverage_diagnosis')[0]
        wrong=dict(receipt,result=dict(receipt['result'],reason='DATA_BLOCKED'))
        service._persist(wrong)
        with pytest.raises(Exception,match='PROCESS_BINDING_CHANGED'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        service._persist(receipt)
        path=Path(receipt['review_process']['stdout_ref'][7:]);path.write_bytes(path.read_bytes()+b'tamper')
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='PROCESS_EVIDENCE_CHANGED'):
            service.run(release_batch_id=BATCH,application_id=server.app,gap_id=gap)
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()
