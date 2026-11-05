"""N10 Gate never derives from a caller flag or legacy manifest-shaped PASS.

Process unit checks are NOT evidence of a genuine native full L1-L7 release.
The production terminal service accepts only the source-auditing native
aggregator and a separately reviewed process receipt over current R1.
"""
import hashlib
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n10_review_worker import canonical, review, _REQUIRED_TRUE, _REQUIRED_FALSE
from rc7_runtime.rc72_n10_terminal import NativeN10TerminalReviewService
from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from test_rc72_phase8_n10_r1_convergence_contract import _full_truth


@pytest.mark.parametrize('alter',['missing-level','open-defect','unproven','human-gate','hash','blocker'])
def test_isolated_n10_reviewer_rejects_mandatory_scope_or_source_mutation(alter):
    # This is a process protocol fixture, not an R1 acceptance receipt.
    snapshot=dict(snapshot_id='SNAPSHOT-PROTOCOL-ONLY',result='CONVERGED',
        blockers=[],proven_obligation_ids=['PROTOCOL-TEST-OBLIGATION'],
        unproven_obligation_ids=[],coverage_observation_ids=['PROTOCOL-OBSERVATION'],
        facts=dict([(k,True) for k in _REQUIRED_TRUE]+[(k,False) for k in _REQUIRED_FALSE]))
    data=dict(snapshot=snapshot,snapshot_id=snapshot['snapshot_id'],
        snapshot_sha256=hashlib.sha256(canonical(snapshot)).hexdigest(),
        review_id='PROTO-REVIEW',reviewer_worker_id='PROTO-REVIEWER',
        reviewer_session_id='PROTO-SESSION',
        criteria=['all mandatory release proof verified'])
    assert review(data)['accepted'] is True
    if alter=='missing-level':
        snapshot['facts']['required_l1_l7_completion']=False
    elif alter=='open-defect':
        snapshot['facts']['critical_defects_closed']=False
    elif alter=='unproven':
        snapshot['unproven_obligation_ids']=['NOT-VERIFIED']
    elif alter=='human-gate':
        snapshot['facts']['human_gate_required']=True
    elif alter=='blocker':
        snapshot['blockers']=['scope:missing-level:SST-1:L6']
    if alter=='hash':
        data['snapshot_sha256']='0'*64
    else:
        data['snapshot_sha256']=hashlib.sha256(canonical(snapshot)).hexdigest()
    assert review(data)['accepted'] is False


def test_legacy_self_declared_green_cannot_be_accepted_as_native_n10_gate(tmp_path):
    truth,runtime,repo=_full_truth(tmp_path)
    agg=ReleaseConvergenceAggregator(truth,release_id='RC7.2',runtime=runtime,
        replay_safe=True)
    result=agg.aggregate(mission_id='M-1')
    assert result.result.value=='CONVERGED'  # legacy contract fixture, NOT native Field
    before=truth.store.path.read_bytes()
    with pytest.raises(ContractError,match='N10_TERMINAL_NATIVE_PROOF_AND_FRESH_REVIEWER_REQUIRED'):
        NativeN10TerminalReviewService(agg,authority=RC72AuthorityRuntime(b'protocol-not-field'),
            source_commit='protocol-not-source',review_root=tmp_path/'never-run',
            lifecycle=WorkerLifecycleService(truth,release_id='RC7.2'))
    assert truth.store.path.read_bytes()==before
    assert not truth.query('rc72_node_delivery',node_type='N10_RELEASE_CONVERGENCE')
    assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE')
    assert not truth.query('rc72_n10_terminal_review')


@pytest.mark.parametrize('review_id,accepted',[
    ('REV-'+'a'*20,True),('N10REV-'+'b'*24,True),
    ('REV-'+'c'*32,False),('../N10REV-'+'d'*24,False),
    ('REV-../../foreign',False),('REV-'+'a'*19,False)])
def test_n10_reviewer_evidence_root_confined_to_canonical_lifecycle_identity(
        tmp_path,review_id,accepted):
    # Pure path policy; does not instantiate a release review or manufacture
    # a Gate. Source reviewer IDs are minted by native lifecycle with 20 hex.
    service=object.__new__(NativeN10TerminalReviewService)
    service.root=tmp_path.resolve()
    if accepted:
        assert service._safe_review_root(review_id)==service.root/review_id
    else:
        with pytest.raises(ContractError,match='N10_TERMINAL_REVIEWER_PATH_INVALID'):
            service._safe_review_root(review_id)
    assert list(tmp_path.iterdir())==[]


def test_actual_native_n10_refuses_terminal_on_100_percent_coverage_with_missing_l1_l7(
        tmp_path,monkeypatch):
    """Real native N1..N9, Libra read, signed scope and incomplete all-level batch.

    Even if measured coverage is 100%, independent N10 may not spawn a
    reviewer, create a Delivery, or apply a Gate for missing mandatory work.
    """
    from rc7_runtime.rc72_n10_control import NativeN10ControlService
    from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
    from rc7_runtime.rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
    from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
    from rc7_runtime.rc72_release_convergence import ReleaseConvergenceSnapshot
    from rc7_runtime.rc72_state_machine import ReleaseConvergenceFacts,ReleaseConvergenceResult
    from test_rc72_libra_measurement import _setup
    from rc72_n2_test_support import BATCH
    def covered(row):
        for unit in row['units']:
            unit['covered']=True
    truth,plan,pipeline,business,server,measurement=_setup(tmp_path,monkeypatch,covered)
    try:
        intake=NativeCoverageGapIntakeService(measurement)
        diagnosis=NativeCoveragePathDiagnosisService(intake,evidence_root=tmp_path/'diagnosis')
        control=NativeN10ControlService(measurement.expected_scope,measurement.n9,
            measurement,intake,diagnosis)
        result=control.complete(release_batch_id=BATCH)
        assert result['convergence_result']=='NOT_CONVERGED'
        assert any(v.startswith('scope:missing-level:') for v in result['blockers'])
        row=truth.query('rc72_release_convergence_snapshot',
            snapshot_id=result['convergence_snapshot_id'])[0]
        snapshot=ReleaseConvergenceSnapshot(
            snapshot_id=row['snapshot_id'],mission_id=row['mission_id'],
            release_batch_id=row['release_batch_id'],manifest_id=row['manifest_id'],
            scope_snapshot_id=row['scope_snapshot_id'],facts=ReleaseConvergenceFacts(**row['facts']),
            result=ReleaseConvergenceResult(row['result']),blockers=row['blockers'],
            proven_obligation_ids=row['proven_obligation_ids'],
            unproven_obligation_ids=row['unproven_obligation_ids'],
            coverage_observation_ids=row['coverage_observation_ids'],created_at=row['created_at'])
        aggregator=ReleaseConvergenceAggregator(truth,release_id=pipeline.release_id,
            runtime=measurement.n9.runtime,
            execution_proof=AcceptedObligationExecutionProof(pipeline),
            expected_scope=measurement.expected_scope,coverage_proof=measurement,
            coverage_intake=intake,coverage_diagnosis=diagnosis,replay_safe=True)
        terminal=NativeN10TerminalReviewService(aggregator,
            authority=measurement.authority,source_commit=pipeline.source_commit,
            review_root=tmp_path/'terminal-never-run',
            lifecycle=pipeline.preparation.lifecycle)
        before=truth.store.path.read_bytes()
        before_calls=len(business.calls),len(server.calls)
        with pytest.raises(ContractError,match='N10_TERMINAL_FULL_CONVERGENCE_REQUIRED'):
            terminal.finalize(snapshot=snapshot)
        assert truth.store.path.read_bytes()==before
        assert not (tmp_path/'terminal-never-run').exists()
        assert not truth.query('rc72_node_delivery',node_type='N10_RELEASE_CONVERGENCE')
        assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE')
        assert not truth.query('rc72_n10_terminal_review')
        assert (len(business.calls),len(server.calls))==before_calls
    finally:
        server.shutdown();server.server_close()
        business.shutdown();business.server_close()
