from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rc6_runtime import (
    AutonomousMissionLoop,
    AutonomousMissionOrchestrator,
    MissionActionOutcome,
    MissionOrchestrationError,
    MissionRuntime,
    TruthRuntime,
)


PASS_GATE = {
    "REALITY_RECON": "REALITY_RECONCILED",
    "TARGET_QUALIFICATION": "TARGET_QUALIFIED",
    "REQUIREMENT_ANALYSIS": "REQUIREMENT_ANALYSIS_COMPLETE",
    "REQUIREMENT_SUFFICIENCY": "REQUIREMENT_SUFFICIENT",
    "CODE_ANALYSIS": "CODE_ANALYSIS_COMPLETE",
    "CODE_SUFFICIENCY": "CODE_SUFFICIENT",
    "FUSION": "FUSION_COMPLETE",
    "LAYER_APPLICABILITY": "LAYER_APPLICABILITY_COMPLETE",
    "L1_L7_DESIGN": "L1_L7_DESIGN_COMPLETE",
    "DESIGN_SUFFICIENCY": "DESIGN_SUFFICIENT",
    "ORACLE_CLOSURE": "ORACLE_SUFFICIENT",
    "CASE_FREEZE": "CASE_SET_FROZEN",
    "EXECUTABLE_SPEC": "EXECUTABLE_SPEC_READY",
    "SCRIPT_BUILD": "SCRIPT_GENERATED",
    "SCRIPT_VALIDATE": "SCRIPT_READY",
    "SCRIPT_READY": "SCRIPT_READY_ADMITTED",
    "PREPARATION": "PREPARATION_STARTED",
    "PRECONDITION_VERIFY": "PRECONDITIONS_VERIFIED",
    "TEST_DATA_PREPARE": "TEST_DATA_READY",
    "PREPARED_ATTEMPT_FREEZE": "PREPARED_ATTEMPT_FROZEN",
    "L1_L7_EXECUTION": "L1_L7_EXECUTION_COMPLETE",
    "EXECUTION_INTEGRITY": "EXECUTION_INTEGRITY",
    "EMPIRICAL_COVERAGE": "COVERAGE_SUFFICIENT",
    "DEFECT": "DEFECT_RECONCILED",
    "REPORT": "REPORT_COMPLETE",
    "ALLURE": "ALLURE_COMPLETE",
    "TRUTH_RECONCILIATION": "TRUTH_RECONCILED",
}


class SyntheticSameMissionHandler:
    def __init__(self):
        self.actions = []
        self.rotations = 0

    def __call__(self, directive):
        self.actions.append(directive.action)
        if directive.action == "ROTATE_SESSION":
            self.rotations += 1
            return MissionActionOutcome(
                status="ROTATED",
                successor_session_ref="coord://synthetic/%d" % self.rotations,
            )
        gate = PASS_GATE.get(directive.stage)
        if gate is None:
            return MissionActionOutcome(status="BLOCKED", reason="NO_SYNTHETIC_HANDLER:%s" % directive.stage)
        target = "TARGET-SYNTHETIC-RC6" if directive.stage == "TARGET_QUALIFICATION" else None
        return MissionActionOutcome(
            status="COMPLETED",
            gate_name=gate,
            passed=True,
            evidence_ref="synthetic://%s/%s" % (directive.stage.lower(), directive.idempotency_key),
            target_id=target,
        )


class AutonomousMissionLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.missions = MissionRuntime(str(root / "missions"))
        self.truth = TruthRuntime(root / "r1" / "event-stream.jsonl")
        self.orchestrator = AutonomousMissionOrchestrator(self.missions, self.truth)
        self.missions.create("M-AUTO", "BLOAN-PF1.2.0")
        state = self.missions.load("M-AUTO")
        self.missions.bind_coordinator_session(state, "coord://synthetic/A")

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_run_crosses_three_generations_and_finishes_without_continue(self):
        handler = SyntheticSameMissionHandler()
        loop = AutonomousMissionLoop(
            self.orchestrator,
            self.missions,
            handler,
            context_pressure=lambda state: state.coordinator_generation < 3,
        )
        result = loop.run("M-AUTO", max_steps=64)
        self.assertEqual(result.status, "COMPLETE")
        self.assertEqual(result.stage, "COMPLETE")
        self.assertEqual(result.coordinator_generation, 3)
        self.assertEqual(result.checkpoint_seq, 3)
        self.assertEqual(handler.rotations, 3)
        self.assertEqual(len(result.coordinator_session_refs), 4)
        self.assertEqual(result.coordinator_session_refs[0], "coord://synthetic/A")
        self.assertEqual(len(set(result.coordinator_session_refs)), 4)
        self.assertFalse(any("CONTINUE" in action.upper() for action in handler.actions))
        # The autonomous happy path must now traverse execution closure rather
        # than jumping from frozen cases straight to preparation.
        for required_action in ("BUILD_EXECUTABLE_SPEC", "BUILD_SCRIPT", "VALIDATE_SCRIPT"):
            self.assertIn(required_action, handler.actions)
        envelope = self.missions.resume_envelope(self.missions.load("M-AUTO"))
        self.assertFalse(hasattr(envelope, "chat_history"))
        self.assertFalse(hasattr(envelope, "messages"))
        self.assertFalse(envelope.successor_pending)

    def test_rotation_fails_closed_when_handler_does_not_create_successor(self):
        def bad_handler(directive):
            return MissionActionOutcome(status="COMPLETED")

        loop = AutonomousMissionLoop(
            self.orchestrator,
            self.missions,
            bad_handler,
            context_pressure=lambda state: True,
        )
        with self.assertRaises(MissionOrchestrationError) as ctx:
            loop.run("M-AUTO", max_steps=1)
        self.assertEqual(str(ctx.exception), "SUCCESSOR_SESSION_REQUIRED")
        self.assertTrue(self.missions.load("M-AUTO").successor_pending)

    def test_runtime_block_stops_without_fabricating_pass(self):
        loop = AutonomousMissionLoop(
            self.orchestrator,
            self.missions,
            lambda directive: MissionActionOutcome(status="BLOCKED", reason="CAPABILITY_NOT_READY"),
        )
        result = loop.run("M-AUTO", max_steps=8)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.stage, "REALITY_RECON")
        self.assertEqual(result.blocking_reasons, ("CAPABILITY_NOT_READY",))
        self.assertNotIn("REALITY_RECONCILED", self.missions.load("M-AUTO").completed_gates)


if __name__ == "__main__":
    unittest.main()
