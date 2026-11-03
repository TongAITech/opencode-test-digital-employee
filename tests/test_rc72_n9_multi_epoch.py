"""N9 delivery identity is monotonic across distinct accepted N7 epochs."""
from copy import deepcopy

from rc72_n2_test_support import BATCH,MISSION
from test_rc72_n9_accepted_scope import _accepted
from rc7_runtime.rc72_domain import AutonomousMissionNode as Node,MissionNodeState as State
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service


def test_distinct_accepted_n7_epoch_gets_next_n9_delivery_version_and_replay_is_stable(tmp_path,monkeypatch):
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        n9=AcceptedScopeN9Service(pipeline)
        first=n9.complete(release_batch_id=BATCH)
        first_delivery=truth.query('rc72_node_delivery',delivery_id=truth.query('rc72_node_gate',gate_id=first['gate_id'])[0]['delivery_id'])[0]
        assert first_delivery['version']==1
        original_snapshot=n9._snapshot(BATCH)[0]
        second_snapshot=deepcopy(original_snapshot)
        second_snapshot['proof']=dict(second_snapshot['proof'],n7_gate_id='N7GATE-ACCEPTED-FRESH-EPOCH',
            review_result_id='N7REVIEW-ACCEPTED-FRESH-EPOCH')
        # AcceptedObligationExecutionProof owns physical N7 validation.  This
        # focused N9 contract test substitutes its already-accepted next-epoch
        # result only to verify N9's own version/recovery behavior.
        monkeypatch.setattr(n9,'_snapshot',lambda release_batch_id:(deepcopy(second_snapshot),[]))
        runtime=n9.runtime
        n10=runtime.node_by_type(MISSION,Node.N10_RELEASE_CONVERGENCE)
        if n10['state']!='STALE':runtime.mark_stale(n10['mission_node_id'],reason='accepted fresh N7 epoch supersedes N10')
        node=runtime.node_by_type(MISSION,Node.N9_DEFECT)
        runtime.mark_stale(node['mission_node_id'],reason='accepted fresh N7 epoch supersedes N9')
        runtime.transition_state(node['mission_node_id'],State.READY,reason='accepted fresh N7 forward handoff')
        second=n9.complete(release_batch_id=BATCH)
        assert second['clearance_id']!=first['clearance_id'] and second['gate_id']!=first['gate_id']
        second_gate=truth.query('rc72_node_gate',gate_id=second['gate_id'])[0]
        second_delivery=truth.query('rc72_node_delivery',delivery_id=second_gate['delivery_id'])[0]
        assert second_delivery['version']==2
        current=runtime.node_by_type(MISSION,Node.N9_DEFECT)
        assert current['state']=='PASS' and current['active_delivery_version']==2
        assert sorted(row['version'] for row in truth.query('rc72_node_delivery',mission_node_id=current['mission_node_id']))==[1,2]
        before=truth.store.path.read_bytes()
        replay=n9.complete(release_batch_id=BATCH)
        assert replay==second and truth.store.path.read_bytes()==before
        assert sorted(row['version'] for row in truth.query('rc72_node_delivery',mission_node_id=current['mission_node_id']))==[1,2]
    finally:
        server.shutdown();server.server_close()
