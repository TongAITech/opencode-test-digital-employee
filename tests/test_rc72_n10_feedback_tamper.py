"""Same original N10 signed-R1 tamper rejection cases, isolated per Q1 file.

Windows Q1 runs each selected test module with an unchanged 180-second
process budget; separating expensive independently bootstrapped scenarios
avoids hiding one slow file behind a larger timeout. No case is skipped.
"""
import pytest

from rc72_n2_test_support import BATCH
from test_rc72_libra_measurement import _setup
from test_rc72_n10_control import _control


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
