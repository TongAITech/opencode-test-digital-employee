import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import (
    BankFinalAgentRuntimeProofValidator,
    BankFinalDshHeadlessWorkerLauncher,
    WORKER_RUNTIME_KIND,
    authorize_requirement_analysis_write,
)
from rc6_runtime.authority import AuthorityError, AuthorityRuntime
from rc6_runtime.truth import TruthRuntime


class HardeningTests(unittest.TestCase):
    def _launcher(self, root, runner, coordinator="coord-1"):
        dsh = Path(root) / "dsh"
        dsh.write_text("stub", encoding="utf-8")
        patch = Path(root) / "rc6.cordis.yml"
        patch.write_text("stub", encoding="utf-8")
        truth = TruthRuntime(Path(root) / "r1.jsonl")
        authority = AuthorityRuntime(b"0123456789abcdef-agent-runtime-hardening")
        launcher = BankFinalDshHeadlessWorkerLauncher(
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
        return launcher, truth, authority

    @staticmethod
    def _runner_for(records):
        queue = list(records)

        def run(command, **kwargs):
            session_id, tool_name, payload, terminal_json = queue.pop(0)
            final_text = json.dumps({"qualification_payload": payload}) if terminal_json else "done"
            stdout = "\n".join([
                json.dumps({"type": "session", "sessionId": session_id}),
                json.dumps({"type": "tool_call", "tool": tool_name, "callId": "call-1"}),
                json.dumps({"type": "tool_result", "tool": tool_name, "callId": "call-1", "ok": True}),
                json.dumps({"type": "final", "text": final_text}),
            ])
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        return run

    def _assign(self, launcher, agent_id, role, attempt_id, generation=0):
        artifacts = ("requirement_analysis",) if role == "REQUIREMENT_ANALYZER" else ("requirement_review", "analysis_gap")
        return launcher.assign(
            agent_id=agent_id,
            role=role,
            phase="REQUIREMENT_ANALYSIS",
            mission_id="M-1",
            attempt_id=attempt_id,
            scope="REQ-1",
            input_refs=("input://1",),
            allowed_artifact_types=artifacts,
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            generation=generation,
        )

    def test_unleased_real_tool_call_is_routing_integrity_fail(self):
        runner = self._runner_for([
            ("session-worker-1", "mcp__forbidden__tool", {"ok": True}, True),
        ])
        with tempfile.TemporaryDirectory() as root:
            launcher, truth, _ = self._launcher(root, runner)
            assignment = self._assign(
                launcher,
                "pfc-requirement-analysis",
                "REQUIREMENT_ANALYZER",
                "analysis-attempt-1",
            )
            with self.assertRaises(AgentRuntimeError) as ctx:
                launcher.execute(assignment, "analyze")
            self.assertIn("LEASE_TOOL_AUTHORIZATION_FAILED", str(ctx.exception))
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertIn("ROUTING_INTEGRITY_FAIL", names)
            self.assertNotIn("HANDOFF_RETURNED", names)

    def test_non_json_terminal_final_cannot_use_earlier_text_as_handoff(self):
        runner = self._runner_for([
            ("session-worker-1", "mcp__pfc_aitest_rc6__runtime_status", {"ok": True}, False),
        ])
        with tempfile.TemporaryDirectory() as root:
            launcher, truth, _ = self._launcher(root, runner)
            assignment = self._assign(
                launcher,
                "pfc-requirement-analysis",
                "REQUIREMENT_ANALYZER",
                "analysis-attempt-1",
            )
            with self.assertRaises(AgentRuntimeError) as ctx:
                launcher.execute(assignment, "analyze")
            self.assertEqual(str(ctx.exception), "STRICT_JSON_OUTPUT_MISSING")
            names = [event["event_type"] for event in truth.store.iter_raw()]
            self.assertNotIn("HANDOFF_RETURNED", names)

    def test_professional_write_must_match_worker_signed_lease(self):
        runner = self._runner_for([])
        with tempfile.TemporaryDirectory() as root:
            launcher, truth, authority = self._launcher(root, runner)
            reviewer = self._assign(
                launcher,
                "pfc-requirement-sufficiency",
                "REQUIREMENT_REVIEWER",
                "sufficiency-attempt-1",
            )
            with self.assertRaises(AuthorityError):
                authorize_requirement_analysis_write(
                    authority,
                    reviewer,
                    truth,
                    {
                        "analysis_id": "A-1",
                        "release_id": "R-1",
                        "requirement_id": "REQ-1",
                        "analyzer_worker_id": reviewer.worker_instance_id,
                        "source_assertions": [],
                        "atomic_statements": [],
                        "trace_links": [],
                        "evidence_refs": [],
                    },
                )

    def test_exact_independent_four_worker_gap_repair_chain_passes(self):
        tool = "mcp__pfc_aitest_rc6__runtime_status"
        runner = self._runner_for([
            ("session-a1", tool, {"attempt": 1}, True),
            ("session-r1", tool, {"decision": "GAPS"}, True),
            ("session-a2", tool, {"attempt": 2}, True),
            ("session-r2", tool, {"decision": "PASS"}, True),
        ])
        with tempfile.TemporaryDirectory() as root:
            launcher, truth, _ = self._launcher(root, runner)

            a1 = self._assign(launcher, "pfc-requirement-analysis", "REQUIREMENT_ANALYZER", "analysis-attempt-1")
            a1_run, _ = launcher.execute(a1, "a1")

            r1 = self._assign(launcher, "pfc-requirement-sufficiency", "REQUIREMENT_REVIEWER", "sufficiency-attempt-1")
            launcher.emit_control_event(
                "SUFFICIENCY_STARTED", "M-1",
                reviewer_worker_instance_id=r1.worker_instance_id,
                analysis_id="A-1", attempt="1",
            )
            r1_run, _ = launcher.execute(r1, "r1")
            launcher.emit_control_event(
                "SUFFICIENCY_GAP_FOUND", "M-1",
                analysis_id="A-1", review_id="RV-1",
                gap_id="missing_boundary_rule", gap_artifact_id="G-1",
            )
            launcher.emit_control_event(
                "REPAIR_REQUESTED", "M-1",
                gap_id="missing_boundary_rule", requested_agent_id="pfc-requirement-analysis",
            )

            a2 = self._assign(
                launcher, "pfc-requirement-analysis", "REQUIREMENT_ANALYZER",
                "analysis-attempt-2", generation=1,
            )
            launcher.emit_reassigned(a1_run, a2)
            a2_run, _ = launcher.execute(a2, "a2")

            r2 = self._assign(
                launcher, "pfc-requirement-sufficiency", "REQUIREMENT_REVIEWER",
                "sufficiency-attempt-2", generation=1,
            )
            launcher.emit_control_event(
                "SUFFICIENCY_REEVALUATED", "M-1",
                reviewer_worker_instance_id=r2.worker_instance_id,
                analysis_id="A-2", attempt="2",
            )
            r2_run, _ = launcher.execute(r2, "r2")
            launcher.emit_control_event(
                "SUFFICIENCY_PASSED", "M-1",
                analysis_id="A-2", review_id="RV-2", gate_status="SUFFICIENT",
                reviewer_worker_instance_id=r2_run.worker_instance_id,
            )

            status, proof_ids = BankFinalAgentRuntimeProofValidator().validate(truth, "M-1", "coord-1")
            self.assertEqual(status, "PASS")
            self.assertTrue(proof_ids)
            handoffs = [
                event["payload"] for event in truth.store.iter_raw()
                if event["event_type"] == "HANDOFF_RETURNED"
            ]
            self.assertEqual(len(handoffs), 4)
            self.assertEqual(len({h["worker_instance_id"] for h in handoffs}), 4)
            self.assertEqual(len({h["dsh_session_id"] for h in handoffs}), 4)
            self.assertTrue(all(h["worker_runtime"] == WORKER_RUNTIME_KIND for h in handoffs))
            self.assertNotEqual(a1_run.worker_instance_id, r1_run.worker_instance_id)
            self.assertNotEqual(a2_run.worker_instance_id, r2_run.worker_instance_id)

    def test_any_routing_integrity_fail_invalidates_otherwise_good_proof(self):
        tool = "mcp__pfc_aitest_rc6__runtime_status"
        runner = self._runner_for([
            ("session-a1", tool, {"attempt": 1}, True),
            ("session-r1", tool, {"decision": "GAPS"}, True),
            ("session-a2", tool, {"attempt": 2}, True),
            ("session-r2", tool, {"decision": "PASS"}, True),
        ])
        with tempfile.TemporaryDirectory() as root:
            launcher, truth, _ = self._launcher(root, runner)
            a1 = self._assign(launcher, "pfc-requirement-analysis", "REQUIREMENT_ANALYZER", "analysis-attempt-1")
            a1_run, _ = launcher.execute(a1, "a1")
            r1 = self._assign(launcher, "pfc-requirement-sufficiency", "REQUIREMENT_REVIEWER", "sufficiency-attempt-1")
            launcher.emit_control_event("SUFFICIENCY_STARTED", "M-1", reviewer_worker_instance_id=r1.worker_instance_id, analysis_id="A-1", attempt="1")
            launcher.execute(r1, "r1")
            launcher.emit_control_event("SUFFICIENCY_GAP_FOUND", "M-1", gap_id="missing_boundary_rule", analysis_id="A-1", review_id="RV-1")
            launcher.emit_control_event("REPAIR_REQUESTED", "M-1", gap_id="missing_boundary_rule")
            a2 = self._assign(launcher, "pfc-requirement-analysis", "REQUIREMENT_ANALYZER", "analysis-attempt-2", generation=1)
            launcher.emit_reassigned(a1_run, a2)
            launcher.execute(a2, "a2")
            r2 = self._assign(launcher, "pfc-requirement-sufficiency", "REQUIREMENT_REVIEWER", "sufficiency-attempt-2", generation=1)
            launcher.emit_control_event("SUFFICIENCY_REEVALUATED", "M-1", reviewer_worker_instance_id=r2.worker_instance_id, analysis_id="A-2", attempt="2")
            r2_run, _ = launcher.execute(r2, "r2")
            launcher.emit_control_event("SUFFICIENCY_PASSED", "M-1", gate_status="SUFFICIENT", reviewer_worker_instance_id=r2_run.worker_instance_id)
            launcher.emit_control_event("ROUTING_INTEGRITY_FAIL", "M-1", reason="synthetic-integrity-break")
            with self.assertRaises(AgentRuntimeError) as ctx:
                BankFinalAgentRuntimeProofValidator().validate(truth, "M-1", "coord-1")
            self.assertEqual(str(ctx.exception), "R1_PROOF_CONTAINS_ROUTING_INTEGRITY_FAIL")


if __name__ == "__main__":
    unittest.main()
