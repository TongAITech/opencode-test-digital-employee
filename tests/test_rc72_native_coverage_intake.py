"""Actual captured units enter existing lineage; no generated test assets."""
import pytest
from test_rc72_libra_measurement import _setup
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService


def test_actual_units_form_exact_unmapped_gaps_without_orphan_assets_or_repeated_io(tmp_path,monkeypatch):
    def uncovered(row):
        for index,unit in enumerate(row['units']):unit.update(covered=False,code_slice='Unmapped#'+str(index%2))
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch,uncovered)
    try:
        measurement.collect(release_batch_id=BATCH,application_id=server.app)
        counts={kind:len(truth.query(kind)) for kind in ['rc7_task','rc7_artifact','rc72_test_obligation','rc72_etu']}
        intake=NativeCoverageGapIntakeService(measurement)
        result=intake.intake(release_batch_id=BATCH,application_id=server.app)
        assert result['uncovered_units']==4 and len(result['gap_ids'])==2
        for gap in truth.query('rc72_coverage_gap'):
            assert gap['uncovered_units']==2 and gap['status']=='UNMAPPED'
            assert gap['responsible_nodes']==['N2_REQUIREMENT','N3_CODE_ANALYSIS']
            assert not gap['candidate_obligation_ids'] and gap['evidence_refs']
        assert all(len(truth.query(kind))==count for kind,count in counts.items())
        before=truth.store.path.read_bytes()
        assert intake.intake(release_batch_id=BATCH,application_id=server.app)==result
        assert intake.audit(release_batch_id=BATCH,application_id=server.app)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        gap=truth.query('rc72_coverage_gap')[0]
        truth.append_atomic('RC72_COVERAGE_GAP_UPSERTED',dict(gap,uncovered_units=1,artifact_version=gap['artifact_version']+1))
        with pytest.raises(Exception,match='GAP_LINEAGE_CHANGED'):intake.intake(release_batch_id=BATCH,application_id=server.app)
        assert len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_intake_partial_mapping_recovers_same_actual_units_without_io(tmp_path,monkeypatch):
    from rc7_runtime.rc72_coverage_convergence import CoverageFeedbackService
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch)
    try:
        measurement.collect(release_batch_id=BATCH,application_id=server.app)
        intake=NativeCoverageGapIntakeService(measurement)
        original=CoverageFeedbackService.map_gap
        def interrupt(*args,**kwargs):raise RuntimeError('injected partial mapping')
        monkeypatch.setattr(CoverageFeedbackService,'map_gap',interrupt)
        with pytest.raises(RuntimeError,match='partial mapping'):intake.intake(release_batch_id=BATCH,application_id=server.app)
        assert truth.query('rc72_native_coverage_intake')[0]['state']=='BINDING'
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='ACCEPTED_INTAKE_REQUIRED'):intake.audit(release_batch_id=BATCH,application_id=server.app)
        assert truth.store.path.read_bytes()==before
        monkeypatch.setattr(CoverageFeedbackService,'map_gap',original)
        result=intake.intake(release_batch_id=BATCH,application_id=server.app)
        assert result['uncovered_units']==1 and len(result['gap_ids'])==1
        assert truth.query('rc72_native_coverage_intake')[0]['state']=='BOUND' and len(server.calls)==1
        receipt=truth.query('rc72_native_coverage_intake')[0]
        receipt['mappings'][0]['uncovered_units']=0
        intake._persist(receipt)
        with pytest.raises(Exception,match='INTAKE_SCOPE_CHANGED'):intake.intake(release_batch_id=BATCH,application_id=server.app)
        assert len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_existing_unattested_gap_is_not_adopted_by_actual_intake(tmp_path,monkeypatch):
    from rc7_runtime.rc72_coverage_convergence import CoverageFeedbackService
    from rc7_runtime.rc72_n7_execution_admission import _hash
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch)
    try:
        actual=measurement.collect(release_batch_id=BATCH,application_id=server.app)
        code_slice=actual['uncovered_code_slices'][0]
        gap_id='NATIVE-CG-'+_hash([actual['measurement_id'],code_slice])[:24]
        CoverageFeedbackService(truth,release_id=measurement.release_id).map_gap(gap_id=gap_id,
            observation_id=actual['observation_id'],code_slice=code_slice,uncovered_units=1)
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='UNATTESTED_GAP_NOT_ADOPTED'):
            NativeCoverageGapIntakeService(measurement).intake(release_batch_id=BATCH,application_id=server.app)
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        assert not truth.query('rc72_native_coverage_intake')
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_existing_approved_code_lineage_is_preserved_without_selecting_a_favorable_obligation(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch)
    obligations=truth.query('rc72_test_obligation')
    code_slice=obligations[0]['code_slice_refs'][0]
    matches=sorted([r for r in obligations if r['application_id']==server.app and code_slice in r['code_slice_refs']],key=lambda r:r['obligation_id'])
    def select(row):
        for unit in row['units']:unit['code_slice']=code_slice
    server.mutate=select
    try:
        measurement.collect(release_batch_id=BATCH,application_id=server.app)
        result=NativeCoverageGapIntakeService(measurement).intake(release_batch_id=BATCH,application_id=server.app)
        gap=truth.query('rc72_coverage_gap',gap_id=result['gap_ids'][0])[0]
        assert gap['candidate_obligation_ids']==[r['obligation_id'] for r in matches]
        assert gap['uncovered_units']==1
        if len(matches)==1:
            assert gap['status']=='MAPPED' and gap['obligation_id']==matches[0]['obligation_id']
            assert gap['requirement_id']==matches[0]['requirement_id'] and gap['sst_id']==matches[0]['sst_id']
        else:
            assert gap['status']=='AMBIGUOUS' and gap['obligation_id'] is None
            assert gap['responsible_nodes']==['N3_CODE_ANALYSIS','N10_RELEASE_CONVERGENCE']
        assert len(truth.query('rc72_test_obligation'))==len(obligations) and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()
