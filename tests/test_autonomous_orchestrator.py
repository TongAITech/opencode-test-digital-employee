from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rc6_runtime import AutonomousMissionOrchestrator, MissionOrchestrationError, MissionRuntime, TruthRuntime
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

    def test_first_tick_enters_requirement_analysis_and_cannot_skip(self):
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_ANALYSIS")
        self.assertEqual(d.action, "SPAWN_WORKER")
        self.assertEqual(d.required_role, "REQUIREMENT_ANALYZER")
        state = self.missions.load("M-W13")
        self.assertIn("MISSION_REGISTERED", state.completed_gates)
        self.assertEqual(state.stage, "REQUIREMENT_ANALYSIS")

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
        self.assertEqual(self.missions.load("M-W13").stage, "REQUIREMENT_ANALYSIS")

    def test_three_session_rotations_preserve_mission_without_chat_history(self):
        self.rt.control_tick("M-W13")
        refs = []
        for expected_generation in (1, 2, 3):
            d = self.rt.control_tick("M-W13", context_pressure=True)
            self.assertEqual(d.action, "ROTATE_SESSION")
            self.assertTrue(d.checkpoint_required)
            self.assertIn("/generation/%d" % expected_generation, d.resume_envelope_ref)
            refs.append(d.resume_envelope_ref)
        state = self.missions.load("M-W13")
        self.assertEqual(state.coordinator_generation, 3)
        self.assertEqual(state.checkpoint_seq, 3)
        self.assertEqual(state.stage, "REQUIREMENT_ANALYSIS")
        self.assertEqual(len(set(refs)), 3)

    def test_failed_gate_never_advances_stage(self):
        self.rt.control_tick("M-W13")
        self.rt.record_gate_blocked("M-W13", "REQUIREMENT_SUFFICIENT", "orphan-source")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "REQUIREMENT_ANALYSIS")
        self.assertNotEqual(d.action, "COMPLETE")
        self.assertIn("GATE_BLOCKED:REQUIREMENT_SUFFICIENT", self.missions.load("M-W13").open_gaps)

    def test_stage_transition_requires_verified_gate(self):
        self.rt.control_tick("M-W13")
        self.rt.record_verified_gate("M-W13", "REQUIREMENT_SUFFICIENT", "req-gate-evidence")
        d = self.rt.control_tick("M-W13")
        self.assertEqual(d.stage, "CODE_ANALYSIS")
        self.assertEqual(d.required_role, "CODE_ANALYZER")
        self.assertIn("codegraph", d.required_tools)


class AutonomousMcpSurfaceTests(unittest.TestCase):
    def test_wave13_tools_are_exposed(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {x["name"] for x in r["result"]["tools"]}
        self.assertTrue({
            "mission_plan_next", "mission_control_tick", "mission_gate_commit",
            "mission_gate_block", "mission_bind_target",
        }.issubset(names))

    def test_runtime_status_identifies_autonomous_orchestrator(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "runtime_status", "arguments": {}}})
        text = r["result"]["content"][0]["text"]
        self.assertIn('"autonomous_orchestrator": true', text)


if __name__ == "__main__":
    unittest.main()
