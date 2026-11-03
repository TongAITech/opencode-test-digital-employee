"""Actual N10 advancement and accepted-prefix driver; terminal release stays open."""
import pytest
from test_rc72_libra_measurement import _setup
from test_rc72_native_coverage_diagnosis import _diagnosis
from test_rc72_native_coverage_repair import _accept_task
from rc72_n2_test_support import BATCH,COMMIT
from rc7_runtime.rc72_n10_control import NativeN10ControlService
from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
from rc7_runtime.rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService


def _control(measurement,tmp_path,*,repair=False):
    intake=NativeCoverageGapIntakeService(measurement)
    diagnosis=NativeCoveragePathDiagnosisService(intake,evidence_root=tmp_path/'n10-diagnosis')
    repair_service=NativeCoverageRepairService(diagnosis) if repair else None
    return NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,intake,diagnosis,repair=repair_service)


def test_controller_collects_actual_unmapped_gaps_and_restarts_without_duplicate_reads(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch)
    try:
        control=_control(measurement,tmp_path)
        result=control.complete(release_batch_id=BATCH)
        assert result['reason']=='N10_COVERAGE_INVESTIGATION_REQUIRED'
        assert result['holds'][0]['reason']=='COVERAGE_UNIQUE_MAPPING_INVESTIGATION_REQUIRED'
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
        assert not truth.query('rc72_native_coverage_diagnosis')
        before=truth.store.path.read_bytes()
        assert control.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        assert truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]['state']=='RUNNING'
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_full_measured_coverage_cannot_complete_original_missing_levels_through_controller(tmp_path,monkeypatch):
    def all_covered(row):
        for unit in row['units']:unit['covered']=True
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch,all_covered)
    try:
        control=_control(measurement,tmp_path)
        result=control.complete(release_batch_id=BATCH)
        assert result['reason']=='N10_RELEASE_NOT_CONVERGED' and result['convergence_result']=='NOT_CONVERGED'
        assert any(b.startswith('scope:missing-level:') for b in result['blockers'])
        missing=[issue for issue in result['issues'] if issue['gap_reason']=='REQUIRED_TEST_LEVEL_MISSING']
        assert missing and all(issue['responsible_node']=='N4_TEST_DESIGN'
            and issue['priority']=='P0' and any(ref.startswith('sst://') for ref in issue['scope_refs'])
            and any(ref.startswith('test-level://L') for ref in issue['scope_refs'])
            and any(ref.startswith('r1://artifact/') for ref in issue['evidence_refs'])
            for issue in missing)
        assert not result['investigation_workitem_ids'] and len(server.calls)==1
        assert all(len(levels)==7 for levels in truth.query('rc72_release_scope_manifest')[0]['required_levels_by_sst'].values())
        assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE')
        assert not truth.query('rc72_node_delivery',node_type='N10_RELEASE_CONVERGENCE')
        assert not truth.query('rc72_n10_terminal_review')
        before_repeat=truth.store.path.read_bytes()
        assert control.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before_repeat
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_controller_runs_actual_independent_diagnosis_and_returns_pending_original_n8_work(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        measurement=diagnosis.measurement
        control=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis)
        result=control.complete(release_batch_id=BATCH)
        assert result['reason']=='N10_RELEASE_NOT_CONVERGED' and len(result['investigation_workitem_ids'])==1
        task=truth.query('rc7_task',task_id=result['investigation_workitem_ids'][0])[0]
        assert task['task_type']=='COVERAGE_PATH_INVESTIGATION' and task['state'] in {'REGISTERED','READY'}
        assert any(b.startswith('gap:') or b.startswith('coverage-gap:') for b in result['blockers'])
        mapped=[issue for issue in result['issues'] if issue['blocker']=='coverage-gap:'+gap]
        assert len(mapped)==1
        assert mapped[0]['gap_reason']=='PATH_NOT_REACHED'
        assert mapped[0]['responsible_node']=='N8_DIAGNOSIS_RECOVERY'
        assert 'obligation://'+truth.query('rc72_coverage_gap',gap_id=gap)[0]['obligation_id'] in mapped[0]['scope_refs']
        assert not truth.query('rc7_defect')
        assert len(truth.query('rc72_native_coverage_diagnosis'))==1 and len(server.calls)==1
        assert control.complete(release_batch_id=BATCH)['reason']=='N10_RELEASE_NOT_CONVERGED'
        assert len(truth.query('rc72_native_coverage_diagnosis'))==1 and len(server.calls)==1
        from rc7_runtime.rc72_n10_feedback import NativeN10FeedbackService
        from rc7_runtime.rc72_release_convergence import ReleaseConvergenceSnapshot
        from rc7_runtime.rc72_state_machine import ReleaseConvergenceFacts, ReleaseConvergenceResult
        from rc7_runtime.models import ContractError
        saved=truth.query('rc72_release_convergence_snapshot',
            snapshot_id=result['convergence_snapshot_id'])[0]
        native_snapshot=ReleaseConvergenceSnapshot(
            snapshot_id=saved['snapshot_id'],mission_id=saved['mission_id'],
            release_batch_id=saved['release_batch_id'],manifest_id=saved['manifest_id'],
            scope_snapshot_id=saved['scope_snapshot_id'],
            facts=ReleaseConvergenceFacts(**saved['facts']),
            result=ReleaseConvergenceResult(saved['result']),blockers=saved['blockers'],
            proven_obligation_ids=saved['proven_obligation_ids'],
            unproven_obligation_ids=saved['unproven_obligation_ids'],
            coverage_observation_ids=saved['coverage_observation_ids'],created_at=saved['created_at'])
        feedback=NativeN10FeedbackService(truth,release_id=pipeline.release_id)
        assert feedback.derive(snapshot=native_snapshot)==result['issues']
        original_gap=truth.query('rc72_coverage_gap',gap_id=gap)[0]
        truth.append_atomic('RC72_COVERAGE_GAP_UPSERTED',dict(original_gap,
            requirement_id='FORGED-REQUIREMENT-NOT-IN-BATCH',
            artifact_version=original_gap['artifact_version']+1))
        before_tamper=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='N10_FEEDBACK_COVERAGE_OBLIGATION_LINEAGE_CHANGED'):
            feedback.derive(snapshot=native_snapshot)
        assert truth.store.path.read_bytes()==before_tamper and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_controller_promotes_only_accepted_worker_proof_into_repair_fence(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap=_diagnosis(tmp_path,monkeypatch)
    try:
        measurement=diagnosis.measurement
        repair=NativeCoverageRepairService(diagnosis)
        control=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis,repair=repair)

        first=control.complete(release_batch_id=BATCH)
        assert first['reason']=='N10_COVERAGE_INVESTIGATION_REQUIRED'
        assert first['holds'][0]['reason']=='COVERAGE_PATH_INVESTIGATION_NOT_ACCEPTED'
        assert len(first['investigation_workitem_ids'])==1 and not first['repair_workitem_ids']
        assert not truth.query('rc72_native_coverage_repair') and not truth.query('rc7_defect')
        before=truth.store.path.read_bytes();calls=len(server.calls)
        assert control.complete(release_batch_id=BATCH)==first
        assert truth.store.path.read_bytes()==before and len(server.calls)==calls

        investigation=first['investigation_workitem_ids'][0]
        _accept_task(truth,pipeline.release_id,investigation,'coverage_path_investigation')
        second=control.complete(release_batch_id=BATCH)
        assert second['holds'][0]['reason']=='COVERAGE_PATH_REPAIR_EXECUTION_NOT_ACCEPTED'
        assert len(second['repair_workitem_ids'])==1
        repair_workitem=second['repair_workitem_ids'][0]
        task=truth.query('rc7_task',task_id=repair_workitem)[0]
        assert task['task_type']=='COVERAGE_PATH_REPAIR_EXECUTION'
        assert task['gap_refs']==[gap] and task['state'] in {'REGISTERED','READY'}
        assert not truth.query('rc72_native_coverage_repair')

        _accept_task(truth,pipeline.release_id,repair_workitem,'coverage_path_repair')
        third=control.complete(release_batch_id=BATCH)
        assert third['holds'][0]['reason']=='N10_POST_REPAIR_FRESH_N7_REQUIRED'
        boundary=truth.query('rc72_native_coverage_repair')[0]
        assert boundary['state']=='FRESH_N7_REQUIRED' and boundary['gap_id']==gap
        assert boundary['repair_workitem_id']==repair_workitem
        assert not truth.query('rc7_defect')

        # Cold/repeated N10 sees the durable freshness fence and performs no new read or repair side effect.
        cold_repair=NativeCoverageRepairService(diagnosis)
        cold=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis,repair=cold_repair)
        before=truth.store.path.read_bytes();calls=len(server.calls);business_calls=len(business.calls)
        blocked=cold.complete(release_batch_id=BATCH)
        assert blocked['holds'][0]['reason']=='N10_POST_REPAIR_FRESH_N7_REQUIRED'
        assert truth.store.path.read_bytes()==before
        assert len(server.calls)==calls and len(business.calls)==business_calls
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_controller_with_repair_provider_still_refuses_ambiguous_mapping_without_side_effect(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap=_diagnosis(tmp_path,monkeypatch,single=False)
    try:
        repair=NativeCoverageRepairService(diagnosis)
        control=NativeN10ControlService(diagnosis.measurement.expected_scope,diagnosis.measurement.n9,
            diagnosis.measurement,diagnosis.intake,diagnosis,repair=repair)
        before=truth.store.path.read_bytes()
        result=control.complete(release_batch_id=BATCH)
        assert result['holds'][0]['reason']=='COVERAGE_UNIQUE_MAPPING_INVESTIGATION_REQUIRED'
        assert not truth.query('rc72_native_coverage_repair')
        assert not any(task['task_type']=='COVERAGE_PATH_REPAIR_EXECUTION' for task in truth.query('rc7_task'))
        assert not truth.query('rc7_defect')
        # The fixture already admitted N10; ambiguous mapping cannot even
        # append another control event, let alone create repair or business I/O.
        after=truth.store.path.read_bytes()
        repeat=control.complete(release_batch_id=BATCH)
        assert repeat==result and truth.store.path.read_bytes()==after
        assert before==after and len(server.calls)==1
        assert len(business.calls)==len(plan['items'])
        assert not truth.query('rc72_native_coverage_rerun')
        assert not truth.query('rc72_native_coverage_diagnosis')
        # A new controller over the same R1 must make the same refusal,
        # without replaying the actual Libra read or any business execution.
        cold=NativeN10ControlService(diagnosis.measurement.expected_scope,diagnosis.measurement.n9,
            diagnosis.measurement,diagnosis.intake,diagnosis,repair=NativeCoverageRepairService(diagnosis))
        assert cold.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


@pytest.mark.parametrize('tamper', ['blockers', 'facts', 'manifest_id', 'scope_snapshot_id',
    'proven_obligation_ids', 'coverage_observation_ids', 'created_at'])
def test_n10_structured_feedback_rejects_mutated_r1_snapshot_without_new_io(tmp_path,monkeypatch,tamper):
    """An N10 issue must resolve to the independently calculated R1 snapshot."""
    from rc7_runtime.models import ContractError
    from rc7_runtime.rc72_n10_feedback import NativeN10FeedbackService
    from rc7_runtime.rc72_release_convergence import ReleaseConvergenceSnapshot
    from rc7_runtime.rc72_state_machine import ReleaseConvergenceFacts, ReleaseConvergenceResult

    def all_covered(row):
        for unit in row['units']:unit['covered']=True
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch,all_covered)
    try:
        result=_control(measurement,tmp_path).complete(release_batch_id=BATCH)
        row=truth.query('rc72_release_convergence_snapshot',snapshot_id=result['convergence_snapshot_id'])[0]
        snapshot=ReleaseConvergenceSnapshot(
            snapshot_id=row['snapshot_id'],mission_id=row['mission_id'],
            release_batch_id=row['release_batch_id'],manifest_id=row['manifest_id'],
            scope_snapshot_id=row['scope_snapshot_id'],facts=ReleaseConvergenceFacts(**row['facts']),
            result=ReleaseConvergenceResult(row['result']),blockers=row['blockers'],
            proven_obligation_ids=row['proven_obligation_ids'],
            unproven_obligation_ids=row['unproven_obligation_ids'],
            coverage_observation_ids=row['coverage_observation_ids'],created_at=row['created_at'])
        service=NativeN10FeedbackService(truth,release_id=pipeline.release_id)
        assert service.derive(snapshot=snapshot)==result['issues']
        forged=dict(row)
        if tamper=='facts':
            forged['facts']=dict(row['facts'],incremental_coverage_met=not row['facts']['incremental_coverage_met'])
        elif tamper in {'proven_obligation_ids', 'coverage_observation_ids'}:
            forged[tamper]=list(row[tamper])+['FORGED-R1-PROOF']
        elif tamper=='created_at':
            forged[tamper]=int(row[tamper])+1
        elif tamper=='blockers':
            forged[tamper]=['scope:missing-level:foreign:L1']
        else:
            forged[tamper]='FOREIGN-RELEASE-SNAPSHOT'
        forged['artifact_version']=row['artifact_version']+1
        truth.append_atomic('RC72_RELEASE_CONVERGENCE_SNAPSHOT_UPSERTED',forged)
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='N10_FEEDBACK_SNAPSHOT_CHANGED'):
            service.derive(snapshot=snapshot)
        assert truth.store.path.read_bytes()==before
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_n10_historical_pass_is_staled_if_original_release_denominator_is_no_longer_met(tmp_path,monkeypatch):
    """No historical N10 PASS can survive a freshly derived incomplete scope."""
    def all_covered(row):
        for unit in row['units']:unit['covered']=True
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch,all_covered)
    try:
        control=_control(measurement,tmp_path)
        result=control.complete(release_batch_id=BATCH)
        assert result['convergence_result']=='NOT_CONVERGED'
        n10=truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]
        # Adversarial R1 mutation represents a stale/forged terminal label;
        # it does not create an authentic independent reviewer or Gate.
        truth.append_atomic('RC72_MISSION_NODE_UPSERTED',
            dict(n10,state='PASS',artifact_version=n10['artifact_version']+1))
        before_calls=(len(server.calls),len(business.calls))
        rechecked=control.complete(release_batch_id=BATCH)
        assert rechecked['status']=='HOLD' and rechecked['reason']=='N10_TERMINAL_SCOPE_REGRESSED'
        assert rechecked['convergence_result']=='NOT_CONVERGED'
        assert truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]['state']=='STALE'
        assert not truth.query('rc72_n10_terminal_review')
        assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE')
        assert (len(server.calls),len(business.calls))==before_calls
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()
