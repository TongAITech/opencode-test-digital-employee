from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rc6_runtime import AutonomousMissionOrchestrator, MissionOrchestrationError, MissionRuntime, TruthRuntime
from rc6_runtime.stages import StageMachine, StageViolation
from rc6_release.mcp_server import handle


class AutonomousMissionOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.missions = MissionRuntime(str(root / "missions"))
        self.truth = TruthRuntime(root / "r1" / "event-stream.jsonl")
        self.rt = AutonomousMissionOrchestrator(self.missions, self.truth)
        self.missions.create("M-W13", "BLOAN-PF1.2.0")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_tick_enters_reality_recon_and_cannot_skip(self):
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REALITY_RECON")
        self.assertEqual(d.action, "RECONCILE_REALITY")
        state = self.missions.load("M-W13")
        self.assertIn("MISSION_REGISTERED", state.completed_gates)
        self.assertEqual(state.stage, "REALITY_RECON")
        with self.assertRaises(StageViolation):
            self.rt.stages.enter("REALITY_RECON", "REQUIREMENT_ANALYSIS", state.completed_gates)

    def test_reality_and_target_are_mandatory_before_requirement_analysis(self):
        self.rt.control_tick("M-W13")
        self.rt.record_verified_gate("M-W13", "REALITY_RECONCILED", "reality-proof")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "TARGET_QUALIFICATION")
        self.assertEqual(d.action, "BUILD_TARGET")
        self.rt.bind_target("M-W13", "TARGET-bank-fat1-001")
        self.rt.record_verified_gate("M-W13", "TARGET_QUALIFIED", "target-proof")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_ANALYSIS")
        self.assertEqual(d.required_role, "REQUIREMENT_ANALYZER")

    def test_gate_commit_is_stage_bound(self):
        self.rt.control_tick("M-W13")
        with self.assertRaises(MissionOrchestrationError) as ctx:
            self.rt.record_verified_gate("M-W13", "CODE_SUFFICIENT", "gate-result-1")
        self.assertEqual(str(ctx.exception), "GATE_STAGE_MISMATCH")

    def test_plan_next_is_idempotent_and_read_only(self):
        self.rt.control_tick("M-W13")
        a = self.rt.plan_next("M-W13")
        b = self.rt.plan_next("M-W13")
        self.assertEqual(a, b)
        self.assertEqual(a.idempotency_key, b.idempotency_key)
        self.assertEqual(self.missions.load("M-W13").stage, "REALITY_RECON")

    def test_three_session_rotations_require_fresh_successors(self):
        self.rt.control_tick("M-W13")
        state = self.missions.load("M-W13")
        self.missions.bind_coordinator_session(state, "coord://synthetic/A")
        refs = []
        for expected_generation, successor in ((1, "B"), (2, "C"), (3, "D")):
            d = self.rt.control_tick("M-W13", context_pressure=True)
            self.assertEqual(d.action, "ROTATE_SESSION")
            self.assertTrue(d.checkpoint_required)
            self.assertIn("/generation/%d" % expected_generation, d.resume_envelope_ref)
            refs.append(d.resume_envelope_ref)
            pending = self.missions.load("M-W13")
            self.assertTrue(pending.successor_pending)
            self.missions.activate_successor(pending, "coord://synthetic/%s" % successor)
        state = self.missions.load("M-W13")
        self.assertEqual(state.coordinator_generation, 3)
        self.assertEqual(state.checkpoint_seq, 3)
        self.assertEqual(state.stage, "REALITY_RECON")
        self.assertEqual(len(set(refs)), 3)
        self.assertEqual(state.coordinator_session_refs, [
            "coord://synthetic/A", "coord://synthetic/B", "coord://synthetic/C", "coord://synthetic/D"
        ])
        self.assertFalse(state.successor_pending)
        envelope = self.missions.resume_envelope(state)
        self.assertFalse(hasattr(envelope, "chat_history"))
        self.assertFalse(hasattr(envelope, "transcript"))

    def test_rotation_cannot_continue_without_successor_activation(self):
        self.rt.control_tick("M-W13")
        state = self.missions.load("M-W13")
        self.missions.bind_coordinator_session(state, "coord://synthetic/A")
        self.rt.control_tick("M-W13", context_pressure=True)
        with self.assertRaises(MissionOrchestrationError) as ctx:
            self.rt.control_tick("M-W13")
        self.assertEqual(str(ctx.exception), "SUCCESSOR_ACTIVATION_REQUIRED")

    def test_requirement_gap_enters_explicit_repair_loop(self):
        self.rt.control_tick("M-W13")
        self.rt.record_verified_gate("M-W13", "REALITY_RECONCILED", "reality")
        self.rt.control_tick("M-W13")
        self.rt.bind_target("M-W13", "TARGET-fat1")
        self.rt.record_verified_gate("M-W13", "TARGET_QUALIFIED", "target")
        self.rt.control_tick("M-W13")
        self.rt.record_verified_gate("M-W13", "REQUIREMENT_ANALYSIS_COMPLETE", "req-analysis")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_SUFFICIENCY")
        self.assertEqual(d.required_role, "REQUIREMENT_REVIEWER")
        self.rt.record_gate_blocked("M-W13", "REQUIREMENT_SUFFICIENT", "orphan-source")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_GAP_REPAIR")
        self.assertEqual(d.required_role, "REQUIREMENT_ANALYZER")
        self.assertNotEqual(d.action, "COMPLETE")
        self.rt.record_verified_gate("M-W13", "REQUIREMENT_REPAIR_COMPLETE", "repair-proof")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_SUFFICIENCY")

    def test_target_can_only_bind_during_target_qualification(self):
        self.rt.control_tick("M-W13")
        with self.assertRaises(MissionOrchestrationError) as ctx:
            self.rt.bind_target("M-W13", "TARGET-fat1")
        self.assertEqual(str(ctx.exception), "TARGET_BIND_STAGE_MISMATCH")

    def test_canonical_final_integration_stages_are_runtime_states(self):
        required = {"REGISTERED", "REALITY_RECON", "TARGET_QUALIFICATION", "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY", "REQUIREMENT_GAP_REPAIR", "CODE_ANALYSIS", "CODE_SUFFICIENCY", "CODE_GAP_REPAIR", "FUSION", "LAYER_APPLICABILITY", "L1_L7_DESIGN", "DESIGN_SUFFICIENCY", "DELTA_DESIGN", "ORACLE_CLOSURE", "CASE_FREEZE", "PREPARATION", "PRECONDITION_VERIFY", "TEST_DATA_PREPARE", "PREPARED_ATTEMPT_FREEZE", "L1_L7_EXECUTION", "EXECUTION_INTEGRITY", "FAILURE_DIAGNOSIS", "EMPIRICAL_COVERAGE", "DELTA_EXECUTION", "DEFECT", "REPORT", "ALLURE", "TRUTH_RECONCILIATION", "COMPLETE"}
        self.assertEqual(set(StageMachine.STAGES), required)


class AutonomousMcpSurfaceTests(unittest.TestCase):
    def test_wave13_tools_are_exposed(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {x["name"] for x in r["result"]["tools"]}
        self.assertTrue({"mission_plan_next", "mission_control_tick", "mission_gate_commit", "mission_gate_block", "mission_bind_target"}.issubset(names))

    def test_runtime_status_identifies_autonomous_orchestrator(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "runtime_status", "arguments": {}}})
        text = r["result"]["content"][0]["text"]
        self.assertIn('"autonomous_orchestrator": true', text)


if __name__ == "__main__":
    unittest.main()
