from __future__ import annotations

import json
import os

from rc8_center.distributed_orchestration import ActorRole
from rc8_center.infrastructure.postgres import PostgresStore, build_engine
from rc8_center.infrastructure.postgres_mission_node import PostgresMissionNodeRepository
from rc8_center.mission_node_gate import CenterMissionNodeReviewGate, MissionNodeDeliverySubmission
from rc8_runtime.mission_nodes import (
    DirectorReviewDecision,
    DirectorReviewReceipt,
    MissionNodeAdoptionGraph,
    MissionNodeGateDecision,
    MissionNodeGateResult,
    MissionNodeState,
    MissionNodeType,
    NodeDeliveryPackage,
)


database_url = os.environ["RC8_DATABASE_URL"]
store = PostgresStore(build_engine(database_url))
repo = PostgresMissionNodeRepository(store)
gate = CenterMissionNodeReviewGate(repo)

run_id = "n10-mission-node-reality"
graph = MissionNodeAdoptionGraph(run_id, "scope-v1")
node = graph.node(MissionNodeType.N3_CODE_ANALYSIS)
node = gate.begin(node)

delivery = NodeDeliveryPackage(
    package_id="pkg-reality-1",
    test_run_id=run_id,
    mission_node_id=node.mission_node_id,
    attempt_ref="attempt-reality-1",
    evidence_refs=("evidence://codegraph/reality",),
    output_refs=("trace://codegraph/reality",),
)
node = gate.submit_delivery(
    node,
    MissionNodeDeliverySubmission(
        package=delivery,
        transport_role=ActorRole.DSH_NODE,
        evidence_producer_role=ActorRole.TEAM_WORKER,
    ),
)
review = DirectorReviewReceipt(
    receipt_id="review-reality-1",
    test_run_id=run_id,
    mission_node_id=node.mission_node_id,
    director_execution_node_id="pc-director",
    decision=DirectorReviewDecision.ACCEPTED,
    evidence_refs=("evidence://review/reality",),
)
node = gate.record_director_review(node, review)
decision = MissionNodeGateDecision(
    decision_id="gate-reality-1",
    test_run_id=run_id,
    mission_node_id=node.mission_node_id,
    result=MissionNodeGateResult.PASS,
    policy_version="center-ledger:v1",
    evidence_refs=("postgres://mission-node/gate-reality-1",),
)
node = gate.evaluate_center_gate(
    node,
    delivery=delivery,
    review=review,
    decision=decision,
    current_attempt_ref="attempt-reality-1",
    blocking_gap_ids=(),
    evidence_complete=True,
    denominator_satisfied=True,
    prerequisites_satisfied=True,
)

reconstructed = PostgresMissionNodeRepository(store)
persisted = reconstructed.get(node.mission_node_id)
assert persisted is not None
assert persisted.state == MissionNodeState.PASS
assert "center-gate:gate-reality-1" in persisted.output_refs
assert reconstructed.list_for_test_run(run_id) == (persisted,)

print(
    json.dumps(
        {
            "status": "RC8_N10_MISSION_NODE_POSTGRES_REALITY_VERIFIED",
            "test_run_id": run_id,
            "mission_node_id": persisted.mission_node_id,
            "state": persisted.state.value,
            "authority_ref": "center-gate:gate-reality-1",
            "reconstructed_from_postgres": True,
        },
        sort_keys=True,
    )
)
