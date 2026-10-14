import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from rc6_runtime import (
    AgentRuntimeError,
    AgentRuntimeProofValidator,
    AuthorityRuntime,
    DshHeadlessWorkerLauncher,
    IndependentRequirementSufficiencyGate,
    TruthRuntime,
)


class AgentRuntimeGateTests(unittest.TestCase):
    def _analysis(self, boundaries):
        return {
            "analysis_id": "A-1",
            "release_id": "R-1",
            "requirement_id": "REQ-1",
            "analyzer_worker_id": "wrk-analyzer",
            "source_assertions": [{"id": "S1", "text": "amount <= 500000"}],
            "atomic_statements": [{"id": "A1", "text": "limit", "source_ref": "S1", "testable": True}],
            "trace_links": [{"source_id": "S1", "atomic_id": "A1", "evidence_ref": "source://1"}],
            "evidence_refs": ["source://1"],
            "business_rules": [{}],
            "roles": [{}],
            "preconditions": [{}],
            "normal_paths": [{}],
            "negative_paths": [{}],
            "boundaries": boundaries,
            "states": [{}],
            "data_constraints": [{}],
            "dependencies": [{}],
            "side_effects": [{}],
        }

    def _review(self, decision="PASS", gaps=None):
        return {
            "review_id": "RV-1",
            "subject_analysis_id": "A-1",
            "reviewer_worker_id": "wrk-reviewer",
            "analyzer_worker_id": "wrk-analyzer",
            "decision": decision,
            "evidence_refs": ["review://1"],
            "gap_ids": list(gaps or []),
        }

    def test_model_pass_cannot_hide_missing_boundary_rule(self):
        result = IndependentRequirementSufficiencyGate().evaluate(self._analysis([]), self._review("PASS"))
        self.assertFalse(result.passed)
        self.assertIn("REQ_BOUNDARY_RULE_MISSING", result.reasons)

    def test_complete_boundary_can_pass_deterministic_gate(self):
        result = IndependentRequirementSufficiencyGate().evaluate(
            self._analysis([{"max": 500000, "inclusive": True}, {"over": 500000.01, "reject": True}]),
            self._review("PASS"),
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.status, "SUFFICIENT")


class DshWorkerRuntimeTests(unittest.TestCase):
    def _runner(self, session_id, payload=None, exit_code=0):
        payload = payload or {"ok": True}
        stdout = "\n".join([
            json.dumps({"type": "session", "session_id": session_id}),
            json.dumps({"type": "tool_call", "tool_name": "mcp__pfc_aitest_rc6__runtime_status"}),
            json.dumps({"type": "tool_result", "tool_name": "mcp__pfc_aitest_rc6__runtime_status", "ok": True}),
            json.dumps({"type": "text", "text": json.dumps({"qualification_payload": payload})}),
            json.dumps({"type": "final", "text": "done"}),
        ])

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, exit_code, stdout=stdout, stderr="")

        return run

    def _launcher(self, root, runner, coordinator="coord-1"):
        dsh = Path(root) / "dsh"
        dsh.write_text("stub", encoding="utf-8")
        patch = Path(root) / "rc6.cordis.yml"
        patch.write_text("stub", encoding="utf-8")
        truth = TruthRuntime(Path(root) / "r1.jsonl")
        authority = AuthorityRuntime(b"0123456789abcdef-agent-runtime")
        launcher = DshHeadlessWorkerLauncher(
            dsh_bin=str(dsh),
            patch_path=str(patch),
            cwd=root,
            truth=truth,
            authority=authority,
            coordinator_instance_id=coordinator,
            release_id="R-1",
            state_root=root,
            command_runner=runner,
        )
        return launcher, truth

    def test_real_worker_handoff_fields_are_persisted_in_r1(self):
        with tempfile.TemporaryDirectory() as root:
            launcher, truth = self._launcher(root, self._runner("session-worker-1", {"decision": "GAPS"}))
            assignment = launcher.assign(
                agent_id="pfc-requirement-sufficiency",
                role="REQUIREMENT_REVIEWER",
                phase="REQUIREMENT_ANALYSIS",
                mission_id="M-1",
                attempt_id="review-1",
                scope="A-1",
                input_refs=("analysis://1",),
                allowed_artifact_types=("requirement_review", "analysis_gap"),
                allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            )
            invocation, output = launcher.execute(assignment, "review")
            self.assertEqual(output["decision"], "GAPS")
            self.assertNotEqual(invocation.worker_instance_id, "coord-1")
            self.assertEqual(invocation.dsh_session_id, "session-worker-1")
            raw = list(truth.store.iter_raw())
            names = [x["event_type"] for x in raw]
            for name in (
                "WORKER_ASSIGN_REQUESTED", "WORKER_ADMITTED", "WORKER_STARTED",
                "WORKER_TOOL_CALLED", "WORKER_OUTPUT_PRODUCED", "WORKER_COMPLETED", "HANDOFF_RETURNED",
            ):
                self.assertIn(name, names)
            handoff = [x["payload"] for x in raw if x["event_type"] == "HANDOFF_RETURNED"][0]
            required = {
                "worker_instance_id", "agent_id", "mission_id", "attempt_id", "assignment_id", "lease_id",
                "parent_worker_id", "scope", "input_refs", "tool_calls", "output_refs", "evidence_refs",
                "started_at", "finished_at", "result",
            }
            self.assertTrue(required.issubset(handoff))
            self.assertTrue(handoff["tool_calls"])
            self.assertTrue(handoff["evidence_refs"])

    def test_missing_dsh_fails_routing_without_coordinator_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            patch = Path(root) / "rc6.cordis.yml"
            patch.write_text("stub", encoding="utf-8")
            truth = TruthRuntime(Path(root) / "r1.jsonl")
            launcher = DshHeadlessWorkerLauncher(
                dsh_bin=str(Path(root) / "does-not-exist"),
                patch_path=str(patch),
                cwd=root,
                truth=truth,
                authority=AuthorityRuntime(b"0123456789abcdef-agent-runtime"),
                coordinator_instance_id="coord-1",
                release_id="R-1",
                state_root=root,
            )
            assignment = launcher.assign(
                agent_id="pfc-requirement-analysis",
                role="REQUIREMENT_ANALYZER",
                phase="REQUIREMENT_ANALYSIS",
                mission_id="M-1",
                attempt_id="analysis-1",
                scope="REQ-1",
                input_refs=("source://1",),
                allowed_artifact_types=("requirement_analysis",),
                allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            )
            with self.assertRaises(AgentRuntimeError) as ctx:
                launcher.execute(assignment, "analyze")
            self.assertIn("ROUTING_INTEGRITY_FAIL", str(ctx.exception))
            names = [x["event_type"] for x in truth.store.iter_raw()]
            self.assertIn("ROUTING_INTEGRITY_FAIL", names)
            self.assertNotIn("HANDOFF_RETURNED", names)

    def test_worker_session_must_not_equal_coordinator(self):
        with tempfile.TemporaryDirectory() as root:
            launcher, _ = self._launcher(root, self._runner("session-coord"), coordinator="session-coord")
            assignment = launcher.assign(
                agent_id="pfc-requirement-analysis",
                role="REQUIREMENT_ANALYZER",
                phase="REQUIREMENT_ANALYSIS",
                mission_id="M-1",
                attempt_id="analysis-1",
                scope="REQ-1",
                input_refs=("source://1",),
                allowed_artifact_types=("requirement_analysis",),
                allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            )
            with self.assertRaises(AgentRuntimeError) as ctx:
                launcher.execute(assignment, "analyze")
            self.assertEqual(str(ctx.exception), "WORKER_SESSION_NOT_INDEPENDENT")

    def test_proof_validator_rejects_direct_pass_without_gap_repair(self):
        with tempfile.TemporaryDirectory() as root:
            launcher, truth = self._launcher(root, self._runner("session-worker-1"))
            launcher.emit_control_event("SUFFICIENCY_PASSED", "M-1", gate_status="SUFFICIENT")
            with self.assertRaises(AgentRuntimeError):
                AgentRuntimeProofValidator().validate(truth, "M-1", "coord-1")

    def test_agent_runtime_events_replay_deterministically(self):
        with tempfile.TemporaryDirectory() as root:
            launcher, truth = self._launcher(root, self._runner("session-worker-1"))
            launcher.emit_control_event("SUFFICIENCY_STARTED", "M-1", attempt="1")
            before = truth.projection.snapshot()
            truth.rebuild_projection()
            self.assertEqual(before, truth.projection.snapshot())
            self.assertEqual(len(truth.query("agent_runtime_event", mission_id="M-1")), 1)


if __name__ == "__main__":
    unittest.main()
