"""Actual N10 advancement and accepted-prefix driver; terminal release stays open."""
import pytest
from test_rc72_libra_measurement import _setup
from test_rc72_native_coverage_diagnosis import _diagnosis
from rc72_n2_test_support import BATCH,COMMIT
from rc7_runtime.rc72_n10_control import NativeN10ControlService
from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
from rc7_runtime.rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService


def _control(measurement,tmp_path):
    intake=NativeCoverageGapIntakeService(measurement)
    diagnosis=NativeCoveragePathDiagnosisService(intake,evidence_root=tmp_path/'n10-diagnosis')
    return NativeN10ControlService(measurement.expected_scope,measurement.n9,measurement,intake,diagnosis)


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
        assert not result['investigation_workitem_ids'] and len(server.calls)==1
        assert all(len(levels)==7 for levels in truth.query('rc72_release_scope_manifest')[0]['required_levels_by_sst'].values())
        assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE')
        assert control.complete(release_batch_id=BATCH)['convergence_result']=='NOT_CONVERGED'
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
        assert len(truth.query('rc72_native_coverage_diagnosis'))==1 and len(server.calls)==1
        assert control.complete(release_batch_id=BATCH)['reason']=='N10_RELEASE_NOT_CONVERGED'
        assert len(truth.query('rc72_native_coverage_diagnosis'))==1 and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


