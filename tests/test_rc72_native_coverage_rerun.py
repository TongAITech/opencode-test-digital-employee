"""Accepted repair physically re-executes the complete approved N7 denominator."""
from test_rc72_native_coverage_diagnosis import _diagnosis
from test_rc72_native_coverage_repair import _accept_task
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_native_coverage_rerun import NativeCoverageRerunService
from rc7_runtime.rc72_n10_control import NativeN10ControlService


def test_n10_runs_fresh_full_n7_then_fresh_libra_and_closes_original_gap(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,diagnosis,gap_id=_diagnosis(tmp_path,monkeypatch)
    try:
        measurement=diagnosis.measurement;repair=NativeCoverageRepairService(diagnosis);rerun=NativeCoverageRerunService(repair)
        control=NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,diagnosis.intake,diagnosis,repair=repair,rerun=rerun)
        first=control.complete(release_batch_id=BATCH)
        investigation=first['investigation_workitem_ids'][0]
        _accept_task(truth,pipeline.release_id,investigation,'coverage_path_investigation')
        second=control.complete(release_batch_id=BATCH);repair_workitem=second['repair_workitem_ids'][0]
        _accept_task(truth,pipeline.release_id,repair_workitem,'coverage_path_repair')
        third=control.complete(release_batch_id=BATCH)
        assert third['holds'][0]['reason']=='N10_POST_REPAIR_FRESH_N7_REQUIRED'
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
