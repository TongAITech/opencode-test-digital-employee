import unittest

from rc8_center.distributed_orchestration import ActorRole
from rc8_center.mission_node_gate import CenterMissionNodeReviewGate, MissionNodeDeliverySubmission
from rc8_center.mission_node_repository import MemoryMissionNodeRepository
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


class MissionNodeGatePersistenceTest(unittest.TestCase):
    def test_center_gate_persists_each_authoritative_transition(self):
        repository = MemoryMissionNodeRepository()
        gate = CenterMissionNodeReviewGate(repository)
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        node = graph.node(MissionNodeType.N3_CODE_ANALYSIS)

        node = gate.begin(node)
        self.assertEqual(MissionNodeState.IN_PROGRESS, repository.get(node.mission_node_id).state)

        delivery = NodeDeliveryPackage(
            package_id="pkg-1",
            test_run_id="run-1",
            mission_node_id=node.mission_node_id,
            attempt_ref="attempt-1",
            evidence_refs=("evidence://codegraph/1",),
            output_refs=("trace://codegraph/1",),
        )
        node = gate.submit_delivery(
            node,
            MissionNodeDeliverySubmission(
                package=delivery,
                transport_role=ActorRole.DSH_NODE,
                evidence_producer_role=ActorRole.TEAM_WORKER,
            ),
        )
        self.assertEqual(
            MissionNodeState.READY_FOR_DIRECTOR_REVIEW,
            repository.get(node.mission_node_id).state,
        )

        review = DirectorReviewReceipt(
            receipt_id="review-1",
            test_run_id="run-1",
            mission_node_id=node.mission_node_id,
            director_execution_node_id="pc-director",
            decision=DirectorReviewDecision.ACCEPTED,
            evidence_refs=("evidence://review/1",),
        )
        node = gate.record_director_review(node, review)
        self.assertEqual(MissionNodeState.REVIEW_ACCEPTED, repository.get(node.mission_node_id).state)

        decision = MissionNodeGateDecision(
            decision_id="gate-1",
            test_run_id="run-1",
            mission_node_id=node.mission_node_id,
            result=MissionNodeGateResult.PASS,
            policy_version="center-ledger:v1",
            evidence_refs=("ledger://n3/current",),
        )
        node = gate.evaluate_center_gate(
            node,
            delivery=delivery,
            review=review,
            decision=decision,
            current_attempt_ref="attempt-1",
            blocking_gap_ids=(),
            evidence_complete=True,
            denominator_satisfied=True,
            prerequisites_satisfied=True,
        )
        persisted = repository.get(node.mission_node_id)
        self.assertEqual(MissionNodeState.PASS, persisted.state)
        self.assertIn("center-gate:gate-1", persisted.output_refs)


if __name__ == "__main__":
    unittest.main()
