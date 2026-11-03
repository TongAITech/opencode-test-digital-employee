"""Native accepted success bypasses inactive N8 without manufacturing a PASS."""
import pytest
from test_rc72_n9_accepted_scope import _accepted
from rc72_n2_test_support import BATCH,MISSION,REQUIREMENTS
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
from rc7_runtime.rc72_release_scope import ReleaseScopeService,ReleaseScopeManifest
from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
from rc7_runtime.rc72_state_machine import RC72StateMachine


@pytest.mark.parametrize('negative',['no_native_proof','foreign_edge','active_blocked_n8','fitted_manifest'])
def test_native_n7_to_n9_success_is_not_an_unfinished_diagnosis(tmp_path,monkeypatch,negative):
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        AcceptedScopeN9Service(pipeline).complete(release_batch_id=BATCH)
        # Independent fixture policy retains ALL seven required levels, rather
        # than deriving a smaller denominator from observed L3-only Cases.
        requirements={req:['SST-'+req] for req in REQUIREMENTS}
        ReleaseScopeService(truth,release_id=pipeline.release_id).persist_manifest(ReleaseScopeManifest(
            manifest_id='EXPECTED-ALL-LEVELS',mission_id=MISSION,release_batch_id=BATCH,
            requirement_ssts=requirements,required_levels_by_sst={sst:['L1','L2','L3','L4','L5','L6','L7']
                for ssts in requirements.values() for sst in ssts},source_refs=['engineering://independent-all-levels-policy']))
        aggregator=ReleaseConvergenceAggregator(truth,release_id=pipeline.release_id,
            runtime=RC72StateMachine(truth,release_id=pipeline.release_id),
            execution_proof=AcceptedObligationExecutionProof(pipeline))
        snapshot=aggregator.aggregate(mission_id=MISSION)
        assert snapshot.facts.runtime_integrity is True
        assert snapshot.facts.required_l1_l7_completion is False
        assert snapshot.facts.incremental_coverage_met is False
        assert snapshot.result.value=='NOT_CONVERGED'
        assert truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]['state']=='NOT_STARTED'
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert 'scope:EXPECTED_INPUT_PROOF_REQUIRED' in snapshot.blockers
        if negative=='fitted_manifest':
            row=truth.query('rc72_release_scope_manifest')[0]
            row['required_levels_by_sst']={sst:['L3'] for sst in row['required_levels_by_sst']}
            row['artifact_version']+=1
            truth.append_atomic('RC72_RELEASE_SCOPE_MANIFEST_UPSERTED',row)
            snapshot=aggregator.aggregate(mission_id=MISSION)
            declared=truth.query('rc72_scope_denominator_snapshot',snapshot_id=snapshot.scope_snapshot_id)[0]
            assert declared['denominator_complete'] is True
            assert snapshot.facts.requirement_completion is False
            assert snapshot.facts.sst_completion is False
            assert snapshot.facts.obligation_completion is False
            assert 'scope:EXPECTED_INPUT_PROOF_REQUIRED' in snapshot.blockers
            assert len(server.calls)==len(plan['items'])
            return
        if negative=='no_native_proof':
            aggregator=ReleaseConvergenceAggregator(truth,release_id=pipeline.release_id,
                runtime=RC72StateMachine(truth,release_id=pipeline.release_id))
        elif negative=='foreign_edge':
            edge=next(e for e in truth.query('rc72_node_transition') if e['from_node_type']=='N7_EXECUTION')
            n10=truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]
            edge.update(to_node_type='N10_RELEASE_CONVERGENCE',to_mission_node_id=n10['mission_node_id'],artifact_version=edge['artifact_version']+1)
            truth.append_atomic('RC72_NODE_TRANSITION_UPSERTED',edge)
        else:
            node=truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]
            node.update(state='BLOCKED',blocked_reason='actual unresolved diagnosis',artifact_version=node['artifact_version']+1)
            truth.append_atomic('RC72_MISSION_NODE_UPSERTED',node)
        snapshot=aggregator.aggregate(mission_id=MISSION)
        assert snapshot.facts.runtime_integrity is False
        assert any(b.startswith('node:N8_DIAGNOSIS_RECOVERY:') for b in snapshot.blockers)
        assert snapshot.result.value!='CONVERGED'
        assert len(server.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close()
