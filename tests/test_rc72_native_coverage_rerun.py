"""Accepted repair physically re-executes the complete approved N7 denominator."""
from test_rc72_native_coverage_diagnosis import _diagnosis
from test_rc72_native_coverage_repair import _accept_task
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_native_coverage_rerun import NativeCoverageRerunService
from rc7_runtime.rc72_n10_control import NativeN10ControlService


def _advance_to_repair_fence(truth,pipeline,diagnosis,server):
    measurement=diagnosis.measurement;repair=NativeCoverageRepairService(diagnosis);rerun=NativeCoverageRerunService(repair)
    control=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis,repair=repair,rerun=rerun)
    first=control.complete(release_batch_id=BATCH)
    investigation=first['investigation_workitem_ids'][0]
    _accept_task(truth,pipeline.release_id,investigation,'coverage_path_investigation')
    second=control.complete(release_batch_id=BATCH);repair_workitem=second['repair_workitem_ids'][0]
    _accept_task(truth,pipeline.release_id,repair_workitem,'coverage_path_repair')
    third=control.complete(release_batch_id=BATCH)
    assert third['holds'][0]['reason']=='N10_POST_REPAIR_FRESH_N7_REQUIRED'
    return measurement,repair,rerun,control


def test_n10_runs_fresh_full_n7_then_fresh_libra_and_closes_original_gap(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap_id=_diagnosis(tmp_path,monkeypatch)
    try:
        measurement,repair,rerun,control=_advance_to_repair_fence(truth,pipeline,diagnosis,server)
        boundary=truth.query('rc72_native_coverage_repair')[0];origin_gate=boundary['origin_n7_gate_id']
        original_attempts={case['attempt_id'] for bundle in truth.query('rc72_n7_evidence_bundle') for case in bundle['case_results']}
        original_business_calls=len(business.calls);original_coverage_calls=len(server.calls)
        code=truth.query('rc72_coverage_gap',gap_id=gap_id)[0]['code_slice']
        def covered(row):
            for unit in row['units']:
                unit['code_slice']=code;unit['covered']=True
        server.mutate=covered
        fourth=control.complete(release_batch_id=BATCH)
        assert fourth['reason']=='N10_RELEASE_NOT_CONVERGED'
        assert len(business.calls)==original_business_calls+len(plan['items'])
        assert len(server.calls)==original_coverage_calls+1
        rerun_row=truth.query('rc72_native_coverage_rerun')[0]
        assert rerun_row['state']=='N7_PASS' and rerun_row['fresh_n7_gate_id']!=origin_gate
        assert len(rerun_row['fresh_attempt_ids'])==len(plan['items']) and not (set(rerun_row['fresh_attempt_ids']) & original_attempts)
        fresh_bundle=truth.query('rc72_n7_evidence_bundle',bundle_id=rerun_row['fresh_bundle_id'])[0]
        assert fresh_bundle['plan_id']==rerun_row['rerun_plan_id']
        fresh_gate=truth.query('rc72_node_gate',gate_id=rerun_row['fresh_n7_gate_id'])[0]
        fresh_delivery=truth.query('rc72_node_delivery',delivery_id=fresh_gate['delivery_id'])[0]
        # The durable rerun bundle must be the actual independently accepted
        # N7 delivery artifact, not a caller-supplied or historical bundle ID.
        assert fresh_gate['decision']=='PASS'
        assert fresh_delivery['artifact_refs']==[fresh_bundle['bundle_id']]
        assert fresh_delivery['version']>boundary['origin_n7_delivery_version']
        assert all(case['workitem_id'].startswith('N7COVWI-') for case in fresh_bundle['case_results'])
        n7=truth.query('rc72_mission_node',mission_id=rerun_row['mission_id'],node_type='N7_EXECUTION')[0]
        assert n7['state']=='PASS' and n7['active_delivery_version']>boundary['origin_n7_delivery_version']
        n9=truth.query('rc72_mission_node',mission_id=rerun_row['mission_id'],node_type='N9_DEFECT')[0]
        assert n9['state']=='PASS' and n9['active_delivery_version']==2
        assert sorted(row['version'] for row in truth.query('rc72_node_delivery',mission_node_id=n9['mission_node_id']))==[1,2]
        closed=truth.query('rc72_native_coverage_repair',repair_id=boundary['repair_id'])[0]
        assert closed['state']=='CLOSED' and closed['fresh_n7_gate_id']==rerun_row['fresh_n7_gate_id']
        assert truth.query('rc72_coverage_gap',gap_id=gap_id)[0]['status']=='RESOLVED'
        measurements=truth.query('rc72_libra_measurement',application_id=server.app)
        assert len(measurements)==2 and len({row['n7_gate_id'] for row in measurements})==2
        assert not truth.query('rc7_defect')
        before=truth.store.path.read_bytes();bc=len(business.calls);cc=len(server.calls)
        repeat=control.complete(release_batch_id=BATCH)
        assert repeat==fourth and truth.store.path.read_bytes()==before
        assert len(business.calls)==bc and len(server.calls)==cc
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_cold_resume_after_fresh_n7_before_libra_never_reexecutes_business(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap_id=_diagnosis(tmp_path,monkeypatch)
    try:
        measurement,repair,rerun,control=_advance_to_repair_fence(truth,pipeline,diagnosis,server)
        boundary=truth.query('rc72_native_coverage_repair')[0]
        original_business_calls=len(business.calls);original_coverage_calls=len(server.calls)
        # Simulate the crash window exactly after physical fresh N7 acceptance and
        # before N9/Fresh Libra/coverage reconciliation are allowed to continue.
        n7_result=rerun.run(release_batch_id=BATCH)
        assert n7_result['state']=='N7_PASS' and n7_result['gate_id']!=boundary['origin_n7_gate_id']
        assert len(business.calls)==original_business_calls+len(plan['items'])
        after_n7_calls=len(business.calls)
        assert len(server.calls)==original_coverage_calls
        code=truth.query('rc72_coverage_gap',gap_id=gap_id)[0]['code_slice']
        def covered(row):
            for unit in row['units']:
                unit['code_slice']=code;unit['covered']=True
        server.mutate=covered
        # Reconstruct the control services over durable R1.  The prior origin Gate
        # is now historical, so recovery must verify it without demanding that it
        # is still the active N7 Gate and must not replay any N7 business I/O.
        cold_repair=NativeCoverageRepairService(diagnosis)
        cold_rerun=NativeCoverageRerunService(cold_repair)
        cold=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis,
            repair=cold_repair,rerun=cold_rerun)
        result=cold.complete(release_batch_id=BATCH)
        assert result['reason']=='N10_RELEASE_NOT_CONVERGED'
        assert len(business.calls)==after_n7_calls
        assert len(server.calls)==original_coverage_calls+1
        rerun_row=truth.query('rc72_native_coverage_rerun')[0]
        assert rerun_row['state']=='N7_PASS' and rerun_row['fresh_n7_gate_id']==n7_result['gate_id']
        assert truth.query('rc72_native_coverage_repair',repair_id=boundary['repair_id'])[0]['state']=='CLOSED'
        assert truth.query('rc72_coverage_gap',gap_id=gap_id)[0]['status']=='RESOLVED'
        before=truth.store.path.read_bytes();bc=len(business.calls);cc=len(server.calls)
        assert cold.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(business.calls)==bc and len(server.calls)==cc
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_accepted_origin_is_reviewable_without_reopening_n7_execution(tmp_path,monkeypatch):
    """Historical PASS proof may be audited, but it never reauthorizes an old Attempt."""
    import pytest
    from rc7_runtime.rc72_n7_execution_admission import ExecutionAdmissionError
    truth,plan,pipeline,business,server,diagnosis,gap_id=_diagnosis(tmp_path,monkeypatch)
    try:
        planner=pipeline.preparation.planning
        # Native N7 already has its accepted Gate; this is NOT a new dispatch.
        n7=truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]
        assert n7['state']=='PASS'
        with pytest.raises(ExecutionAdmissionError,match='N7_NODE_NOT_ADMITTED'):
            planner.assert_current(plan['plan_id'])
        before=truth.store.path.read_bytes()
        audited=planner.assert_current(plan['plan_id'],review_only=True)
        assert audited['plan_id']==plan['plan_id']
        assert truth.store.path.read_bytes()==before
        assert len(business.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close();business.shutdown();business.server_close()
