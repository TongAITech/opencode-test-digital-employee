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
    if alter!='hash':
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
