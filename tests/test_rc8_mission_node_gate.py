import unittest

from rc8_center.control_plane import CenterControlError
from rc8_center.distributed_orchestration import ActorRole
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


class CenterMissionNodeReviewGateTest(unittest.TestCase):
    def setUp(self):
        self.service = CenterMissionNodeReviewGate()
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        self.node = graph.node(MissionNodeType.N3_CODE_ANALYSIS)
        self.node = self.service.begin(self.node)
        self.delivery = NodeDeliveryPackage(
            package_id="pkg-1",
            test_run_id="run-1",
            mission_node_id=self.node.mission_node_id,
            attempt_ref="attempt-2",
            evidence_refs=("evidence://codegraph/2",),
            output_refs=("trace://graph/2",),
        )
        self.review = DirectorReviewReceipt(
            receipt_id="review-1",
            test_run_id="run-1",
            mission_node_id=self.node.mission_node_id,
            director_execution_node_id="pc-director",
            decision=DirectorReviewDecision.ACCEPTED,
            evidence_refs=("evidence://review/1",),
        )
        self.decision = MissionNodeGateDecision(
            decision_id="gate-1",
            test_run_id="run-1",
            mission_node_id=self.node.mission_node_id,
            result=MissionNodeGateResult.PASS,
            policy_version="center-ledger:v1",
            evidence_refs=("ledger://n3/current",),
        )

    def _submit_and_review(self):
        submitted = self.service.submit_delivery(
            self.node,
            MissionNodeDeliverySubmission(
                package=self.delivery,
                transport_role=ActorRole.DSH_NODE,
                evidence_producer_role=ActorRole.TEAM_WORKER,
            ),
        )
        self.assertEqual(MissionNodeState.READY_FOR_DIRECTOR_REVIEW, submitted.state)
        reviewed = self.service.record_director_review(submitted, self.review)
        self.assertEqual(MissionNodeState.REVIEW_ACCEPTED, reviewed.state)
        return reviewed

    def test_happy_path_requires_director_acceptance_then_center_gate(self):
        reviewed = self._submit_and_review()
        passed = self.service.evaluate_center_gate(
            reviewed,
            delivery=self.delivery,
            review=self.review,
            decision=self.decision,
            current_attempt_ref="attempt-2",
            blocking_gap_ids=(),
            evidence_complete=True,
            denominator_satisfied=True,
            prerequisites_satisfied=True,
        )
        self.assertEqual(MissionNodeState.PASS, passed.state)
        self.assertIn("center-gate:gate-1", passed.output_refs)
        self.assertIn("director-review:review-1", passed.output_refs)

    def test_director_review_never_directly_sets_pass(self):
        reviewed = self._submit_and_review()
        self.assertEqual(MissionNodeState.REVIEW_ACCEPTED, reviewed.state)
        self.assertNotEqual(MissionNodeState.PASS, reviewed.state)

    def test_director_generated_domain_delivery_is_rejected(self):
        with self.assertRaisesRegex(CenterControlError, "DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN"):
            self.service.submit_delivery(
                self.node,
                MissionNodeDeliverySubmission(
                    package=self.delivery,
                    transport_role=ActorRole.DSH_NODE,
                    evidence_producer_role=ActorRole.DIRECTOR,
                ),
            )

    def test_director_cannot_transport_domain_delivery(self):
        with self.assertRaisesRegex(CenterControlError, "DELIVERY_TRANSPORT_FORBIDDEN"):
            self.service.submit_delivery(
                self.node,
                MissionNodeDeliverySubmission(
                    package=self.delivery,
                    transport_role=ActorRole.DIRECTOR,
                    evidence_producer_role=ActorRole.TEAM_WORKER,
                ),
            )

    def test_stale_attempt_cannot_satisfy_center_gate(self):
        reviewed = self._submit_and_review()
        with self.assertRaisesRegex(CenterControlError, "STALE_ATTEMPT_EVIDENCE_FORBIDDEN"):
            self.service.evaluate_center_gate(
                reviewed,
                delivery=self.delivery,
                review=self.review,
                decision=self.decision,
                current_attempt_ref="attempt-3",
                blocking_gap_ids=(),
                evidence_complete=True,
                denominator_satisfied=True,
                prerequisites_satisfied=True,
            )

    def test_blocking_gap_prevents_pass(self):
        reviewed = self._submit_and_review()
        with self.assertRaisesRegex(CenterControlError, "MISSION_NODE_BLOCKING_GAP_PRESENT"):
            self.service.evaluate_center_gate(
                reviewed,
                delivery=self.delivery,
                review=self.review,
                decision=self.decision,
                current_attempt_ref="attempt-2",
                blocking_gap_ids=("gap-1",),
                evidence_complete=True,
                denominator_satisfied=True,
                prerequisites_satisfied=True,
            )

    def test_denominator_evidence_and_prerequisites_are_fail_closed(self):
        reviewed = self._submit_and_review()
        scenarios = (
            ({"evidence_complete": False, "denominator_satisfied": True, "prerequisites_satisfied": True}, "EVIDENCE_INCOMPLETE"),
            ({"evidence_complete": True, "denominator_satisfied": False, "prerequisites_satisfied": True}, "DENOMINATOR_UNSATISFIED"),
            ({"evidence_complete": True, "denominator_satisfied": True, "prerequisites_satisfied": False}, "PREREQUISITES_UNSATISFIED"),
        )
        for flags, expected in scenarios:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(CenterControlError, expected):
                    self.service.evaluate_center_gate(
                        reviewed,
                        delivery=self.delivery,
                        review=self.review,
                        decision=self.decision,
                        current_attempt_ref="attempt-2",
                        blocking_gap_ids=(),
                        **flags
                    )

    def test_nonaccepted_review_cannot_reach_center_pass(self):
        submitted = self.service.submit_delivery(
            self.node,
            MissionNodeDeliverySubmission(
                package=self.delivery,
                transport_role=ActorRole.DSH_NODE,
                evidence_producer_role=ActorRole.TEAM_WORKER,
            ),
        )
        changes_required = DirectorReviewReceipt(
            receipt_id="review-changes",
            test_run_id="run-1",
            mission_node_id=self.node.mission_node_id,
            director_execution_node_id="pc-director",
            decision=DirectorReviewDecision.CHANGES_REQUIRED,
            evidence_refs=("evidence://review/changes",),
        )
        reviewed = self.service.record_director_review(submitted, changes_required)
        self.assertEqual(MissionNodeState.INSUFFICIENT, reviewed.state)
        with self.assertRaisesRegex(CenterControlError, "REQUIRES_DIRECTOR_ACCEPTANCE"):
            self.service.evaluate_center_gate(
                reviewed,
                delivery=self.delivery,
                review=changes_required,
                decision=self.decision,
                current_attempt_ref="attempt-2",
                blocking_gap_ids=(),
                evidence_complete=True,
                denominator_satisfied=True,
                prerequisites_satisfied=True,
            )

    def test_center_can_record_insufficient_or_blocked_without_fabricating_pass(self):
        reviewed = self._submit_and_review()
        insufficient = MissionNodeGateDecision(
            decision_id="gate-insufficient",
            test_run_id="run-1",
            mission_node_id=self.node.mission_node_id,
            result=MissionNodeGateResult.INSUFFICIENT,
            policy_version="center-ledger:v1",
            evidence_refs=("ledger://n3/missing",),
        )
        result = self.service.evaluate_center_gate(
            reviewed,
            delivery=self.delivery,
            review=self.review,
            decision=insufficient,
            current_attempt_ref="attempt-2",
            blocking_gap_ids=("gap-allowed-for-negative-result",),
            evidence_complete=False,
            denominator_satisfied=False,
            prerequisites_satisfied=False,
        )
        self.assertEqual(MissionNodeState.INSUFFICIENT, result.state)


if __name__ == "__main__":
    unittest.main()
