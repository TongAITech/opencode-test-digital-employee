import unittest

from rc8_center.failure_diagnosis import (
    CenterFailureDiagnosisService,
    FailureClassification,
    FailureDiagnosisError,
    MemoryFailureDiagnosisRepository,
    RepairResult,
    RouteFailureScope,
)
from rc8_runtime.mission_nodes import MissionNodeType


class FailureDiagnosisTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.repo = MemoryFailureDiagnosisRepository()
        self.service = CenterFailureDiagnosisService(self.repo, now_fn=lambda: self.now)
        self.service.observe(
            observation_id="obs-1",
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE",
            source_attempt_id="attempt-1",
            source_case_id="case-1",
            summary="execution failed",
            evidence_refs=("evidence://attempt/1",),
        )

    def _route(self, classification, route_scope=None):
        diagnostic = self.service.diagnose(
            diagnostic_id="diag-%s" % classification.value.lower(),
            observation_id="obs-1",
            classification=classification,
            classifier_ref="classifier://n8",
            reason_code="reason-%s" % classification.value.lower(),
            evidence_refs=("evidence://diagnosis/%s" % classification.value.lower(),),
            route_scope=route_scope,
        )
        return self.service.route(
            decision_id="route-%s" % classification.value.lower(),
            diagnostic_id=diagnostic.diagnostic_id,
            gap_id="gap-%s" % classification.value.lower(),
        )

    def test_deterministic_route_policy(self):
        expected = {
            FailureClassification.SCRIPT: MissionNodeType.N6_SCRIPT_BUILD_READINESS,
            FailureClassification.SPEC_DESIGN: MissionNodeType.N4_TEST_DESIGN,
            FailureClassification.ORACLE: MissionNodeType.N4_TEST_DESIGN,
            FailureClassification.DATA: MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
            FailureClassification.PRECONDITION: MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
            FailureClassification.AUTH: MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
            FailureClassification.TOOL: MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
            FailureClassification.ENVIRONMENT: MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
            FailureClassification.DEPENDENCY: MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
            FailureClassification.TRANSIENT: MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
            FailureClassification.FLAKY: MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
            FailureClassification.PRODUCT: MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE,
            FailureClassification.UNKNOWN: MissionNodeType.N8_FAILURE_DIAGNOSIS_RECOVERY,
        }
        for classification, target in expected.items():
            decision = self._route(classification)
            self.assertEqual(target, decision.target_mission_node)
            self.assertEqual("CENTER", decision.authority)

    def test_route_failure_source_truth_and_binding_are_distinct(self):
        source = self._route(FailureClassification.ROUTE, RouteFailureScope.SOURCE_TRUTH)
        self.assertEqual(MissionNodeType.N3_CODE_ANALYSIS, source.target_mission_node)
        self.assertEqual("REDISCOVER_ROUTE_SOURCE_TRUTH", source.policy_code)

        self.service.observe(
            observation_id="obs-2",
            test_run_id="run-1",
            source_mission_node_id="run-1:scope:N7",
            source_attempt_id="attempt-2",
            source_case_id="case-2",
            summary="route binding failed",
            evidence_refs=("evidence://attempt/2",),
        )
        diagnostic = self.service.diagnose(
            diagnostic_id="diag-route-binding",
            observation_id="obs-2",
            classification=FailureClassification.ROUTE,
            route_scope=RouteFailureScope.EXECUTION_BINDING,
            classifier_ref="classifier://n8",
            reason_code="route-binding",
            evidence_refs=("evidence://route/binding",),
        )
        binding = self.service.route(decision_id="route-binding", diagnostic_id=diagnostic.diagnostic_id, gap_id="gap-route-binding")
        self.assertEqual(MissionNodeType.N6_SCRIPT_BUILD_READINESS, binding.target_mission_node)
        self.assertEqual("REBIND_EXECUTION_ROUTE", binding.policy_code)

    def test_product_and_unknown_cannot_be_blindly_repaired_or_retried(self):
        for classification in (FailureClassification.PRODUCT, FailureClassification.UNKNOWN):
            decision = self._route(classification)
            self.assertFalse(decision.repairable)
            with self.assertRaisesRegex(FailureDiagnosisError, "NON_REPAIRABLE_ROUTE"):
                self.service.create_repair_work_order(
                    work_order_id="wo-%s" % classification.value.lower(),
                    route_decision_id=decision.decision_id,
                    evidence_refs=("evidence://workorder",),
                )

    def test_successor_attempt_requires_repaired_receipt_and_is_new(self):
        decision = self._route(FailureClassification.AUTH)
        order = self.service.create_repair_work_order(
            work_order_id="wo-auth",
            route_decision_id=decision.decision_id,
            evidence_refs=("evidence://fresh-login/request",),
        )
        blocked = self.service.record_repair_receipt(
            receipt_id="receipt-blocked",
            work_order_id=order.work_order_id,
            result=RepairResult.BLOCKED,
            evidence_refs=("evidence://auth/blocked",),
        )
        with self.assertRaisesRegex(FailureDiagnosisError, "REQUIRES_REPAIRED_RECEIPT"):
            self.service.authorize_successor_attempt(
                successor_id="succ-blocked",
                work_order_id=order.work_order_id,
                repair_receipt_id=blocked.receipt_id,
                successor_attempt_id="attempt-2",
            )

        repaired = self.service.record_repair_receipt(
            receipt_id="receipt-repaired",
            work_order_id=order.work_order_id,
            result=RepairResult.REPAIRED,
            evidence_refs=("evidence://4a/fresh-login/2",),
        )
        successor = self.service.authorize_successor_attempt(
            successor_id="succ-1",
            work_order_id=order.work_order_id,
            repair_receipt_id=repaired.receipt_id,
            successor_attempt_id="attempt-2",
        )
        self.assertEqual("attempt-1", successor.predecessor_attempt_id)
        self.assertEqual("attempt-2", successor.successor_attempt_id)
        with self.assertRaisesRegex(FailureDiagnosisError, "ALREADY_HAS_SUCCESSOR"):
            self.service.authorize_successor_attempt(
                successor_id="succ-2",
                work_order_id=order.work_order_id,
                repair_receipt_id=repaired.receipt_id,
                successor_attempt_id="attempt-3",
            )

    def test_route_classification_requires_route_scope(self):
        with self.assertRaisesRegex(FailureDiagnosisError, "ROUTE_FAILURE_SCOPE_REQUIRED"):
            self.service.diagnose(
                diagnostic_id="diag-route",
                observation_id="obs-1",
                classification=FailureClassification.ROUTE,
                classifier_ref="classifier://n8",
                reason_code="route",
                evidence_refs=("evidence://route",),
            )


if __name__ == "__main__":
    unittest.main()
