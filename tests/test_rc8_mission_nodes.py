import tempfile
import unittest
from pathlib import Path

from rc8_runtime.contracts import RC8ContractError, RuntimeProducerKind
from rc8_runtime.governance import StageInstance
from rc8_runtime.mission_graph import MissionStageType
from rc8_runtime.mission_nodes import (
    LEGACY_CROSS_NODE_TRANSITIONS,
    DirectorReviewDecision,
    DirectorReviewReceipt,
    MISSION_NODE_SEQUENCE,
    MissionNodeAdoptionGraph,
    MissionNodeGateDecision,
    MissionNodeGateResult,
    MissionNodeType,
    NodeDeliveryPackage,
    all_stage_bindings,
    binding_for_stage,
    mission_runtime_event,
)
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class MissionNodeAdoptionSpineTest(unittest.TestCase):
    def test_every_existing_stage_has_exactly_one_mission_node_binding(self):
        bindings = all_stage_bindings()
        self.assertEqual(len(MissionStageType), len(bindings))
        self.assertEqual(
            {stage.value for stage in MissionStageType},
            {binding.stage_type for binding in bindings},
        )
        self.assertEqual(len(MISSION_NODE_SEQUENCE), len(set(MISSION_NODE_SEQUENCE)))

    def test_frozen_stage_mapping_and_semantic_debt_are_explicit(self):
        self.assertEqual(
            MissionNodeType.N2_REQUIREMENT_ANALYSIS,
            binding_for_stage(MissionStageType.REQUIREMENT_SUFFICIENCY).mission_node_type,
        )
        self.assertEqual(
            MissionNodeType.N3_CODE_ANALYSIS,
            binding_for_stage(MissionStageType.CODE_SUFFICIENCY).mission_node_type,
        )
        self.assertEqual(
            MissionNodeType.N6_SCRIPT_BUILD_READINESS,
            binding_for_stage(MissionStageType.EXECUTABLE_SPEC).mission_node_type,
        )
        self.assertEqual(
            MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
            binding_for_stage(MissionStageType.PRECONDITION_DATA_PREP).mission_node_type,
        )
        self.assertIn(
            (
                MissionNodeType.N6_SCRIPT_BUILD_READINESS,
                MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
            ),
            LEGACY_CROSS_NODE_TRANSITIONS,
        )
        self.assertEqual(
            MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
            binding_for_stage(MissionStageType.TARGETED_REEXECUTION).mission_node_type,
        )
        self.assertEqual(
            MissionNodeType.N8_FAILURE_DIAGNOSIS_RECOVERY,
            binding_for_stage(MissionStageType.DELTA_REPAIR).mission_node_type,
        )

    def test_n9_is_first_class_even_without_legacy_stage(self):
        bound_nodes = {binding.mission_node_type for binding in all_stage_bindings()}
        self.assertNotIn(MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE, bound_nodes)
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        self.assertEqual(
            MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE,
            graph.node(MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE).node_type,
        )

    def test_existing_stage_binds_to_semantic_parent_without_replacing_stage(self):
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        stage = StageInstance(
            stage_instance_id="stage-code-1",
            test_run_id="run-1",
            stage_type=MissionStageType.CODE_ANALYSIS.value,
            scope_version="scope-v1",
            attempt_no=1,
        )
        node = graph.bind_stage(stage)
        self.assertEqual(MissionNodeType.N3_CODE_ANALYSIS, node.node_type)
        self.assertEqual(("stage-code-1",), node.stage_instance_ids)
        traced = graph.mission_node_for_stage("stage-code-1")
        self.assertEqual(node.mission_node_id, traced.mission_node_id)
        self.assertEqual(MissionStageType.CODE_ANALYSIS.value, stage.stage_type)

    def test_stage_binding_rejects_cross_run_and_cross_scope_contamination(self):
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        wrong_run = StageInstance(
            stage_instance_id="stage-1",
            test_run_id="run-2",
            stage_type=MissionStageType.SCOPE_INTAKE.value,
            scope_version="scope-v1",
            attempt_no=1,
        )
        with self.assertRaisesRegex(RC8ContractError, "TEST_RUN_MISMATCH"):
            graph.bind_stage(wrong_run)

        wrong_scope = StageInstance(
            stage_instance_id="stage-2",
            test_run_id="run-1",
            stage_type=MissionStageType.SCOPE_INTAKE.value,
            scope_version="scope-v2",
            attempt_no=1,
        )
        with self.assertRaisesRegex(RC8ContractError, "SCOPE_MISMATCH"):
            graph.bind_stage(wrong_scope)

    def test_delivery_review_and_gate_contracts_are_evidence_backed(self):
        package = NodeDeliveryPackage(
            package_id="pkg-1",
            test_run_id="run-1",
            mission_node_id="node-n3",
            attempt_ref="attempt-1",
            evidence_refs=("evidence://codegraph/1",),
            output_refs=("trace://graph/1",),
        )
        self.assertEqual("attempt-1", package.attempt_ref)
        review = DirectorReviewReceipt(
            receipt_id="review-1",
            test_run_id="run-1",
            mission_node_id="node-n3",
            director_execution_node_id="pc-director",
            decision=DirectorReviewDecision.ACCEPTED,
            evidence_refs=("evidence://review/1",),
        )
        self.assertEqual(DirectorReviewDecision.ACCEPTED, review.decision)
        gate = MissionNodeGateDecision(
            decision_id="gate-1",
            test_run_id="run-1",
            mission_node_id="node-n3",
            result=MissionNodeGateResult.PASS,
            policy_version="center-ledger:v1",
            evidence_refs=("ledger://n3/1",),
        )
        self.assertEqual("CENTER", gate.authority)
        with self.assertRaisesRegex(RC8ContractError, "CENTER_AUTHORITY"):
            MissionNodeGateDecision(
                decision_id="gate-2",
                test_run_id="run-1",
                mission_node_id="node-n3",
                result=MissionNodeGateResult.PASS,
                policy_version="worker:v1",
                evidence_refs=("evidence://worker/1",),
                authority="WORKER",
            )

    def test_r1_replay_preserves_top_level_mission_and_execution_node_provenance(self):
        graph = MissionNodeAdoptionGraph("run-1", "scope-v1")
        node = graph.node(MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE)
        event = mission_runtime_event(
            event_id="evt-1",
            test_run_id="run-1",
            work_item_id="wi-1",
            execution_node_id="pc-worker-1",
            mission_node_id=node.mission_node_id,
            mission_node_type=node.node_type,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="team-1",
            event_type="EVIDENCE_EMITTED",
            sequence=1,
            attempt_id="attempt-1",
            refs=["evidence://1"],
            occurred_at=100,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = CentralR1RuntimeLedger(str(Path(tmpdir) / "r1.jsonl"))
            result = ledger.append_runtime(event)
            self.assertEqual("PERSISTENCE_VERIFIED", result["status"])
            replayed = ledger.runtime_events(test_run_id="run-1", work_item_id="wi-1")
        self.assertEqual(1, len(replayed))
        self.assertEqual(node.mission_node_id, replayed[0]["mission_node_id"])
        self.assertEqual(node.node_type.value, replayed[0]["mission_node_type"])
        self.assertEqual("pc-worker-1", replayed[0]["execution_node_id"])
        self.assertEqual("pc-worker-1", replayed[0]["node_id"])

    def test_execution_node_identity_cannot_diverge_from_runtime_node_identity(self):
        event = mission_runtime_event(
            event_id="evt-1",
            test_run_id="run-1",
            work_item_id="wi-1",
            execution_node_id="pc-worker-1",
            mission_node_id="node-n1",
            mission_node_type=MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="team-1",
            event_type="NODE_CLAIMED",
            sequence=1,
        )
        with self.assertRaisesRegex(RC8ContractError, "EXECUTION_NODE_MISMATCH"):
            type(event)(
                event_id=event.event_id,
                test_run_id=event.test_run_id,
                work_item_id=event.work_item_id,
                node_id="different-node",
                producer_kind=event.producer_kind,
                producer_ref=event.producer_ref,
                event_type=event.event_type,
                sequence=event.sequence,
                mission_node_id=event.mission_node_id,
                mission_node_type=event.mission_node_type,
                execution_node_id=event.execution_node_id,
            )


if __name__ == "__main__":
    unittest.main()
