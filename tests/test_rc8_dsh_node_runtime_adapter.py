import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import CenterControlPlane, MemoryCenterRepository
from rc8_center.dsh_node_runtime_adapter import (
    DshNodeRuntimeAdapter,
    DshNodeRuntimeAdapterError,
    NodeWorkAssignment,
)
from rc8_center.node_team_runtime import TeamProfile
from rc8_runtime.contracts import CapabilityQualification, CapabilityState, NodeIdentity, WorkItemIdentity
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class FakeGateway:
    def __init__(self):
        self.team_context = None
        self.tool_starts = []

    def start_team(self, *, profile_id, member_roles, context):
        self.team_context = dict(context)
        return "team-1"

    def dispatch_member(self, *, team_id, role, context):
        return "agent-1"

    def start_tool(self, *, team_id, agent_id, tool_id, action, payload):
        self.tool_starts.append((tool_id, action, dict(payload)))
        return "invoke-1"

    def complete_team(self, *, team_id):
        return None

    def abort_team(self, *, team_id, reason):
        return None


class DshNodeRuntimeAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repo = MemoryCenterRepository()
        self.ledger = CentralR1RuntimeLedger(str(Path(self.temp_dir.name) / "event-stream.jsonl"))
        self.center = CenterControlPlane(self.repo, self.ledger, now_fn=lambda: 100)
        self.center.register_node(NodeIdentity(
            node_id="node-1", operator_ref="operator-test", os_family="linux",
            architecture="x86_64", shell="bash", registered_at=1,
        ))
        for capability in ("codegraph", "agent_teams"):
            self.center.qualify_capability(CapabilityQualification(
                node_id="node-1", capability_id=capability, state=CapabilityState.VERIFIED,
                probe_ref="probe://%s" % capability,
                evidence_refs=["evidence://%s" % capability], verified_at=1,
            ))
        self.center.register_work_item(WorkItemIdentity(
            work_item_id="work-1", test_run_id="run-1", stage="CODE_ANALYSIS",
            scope_refs=["scope-1"], required_capabilities=["codegraph", "agent_teams"],
        ))
        self.center.lease_work_item("work-1", "node-1", ttl_seconds=60)
        self.gateway = FakeGateway()
        self.adapter = DshNodeRuntimeAdapter(self.center, self.gateway, node_id="node-1")
        self.profile = TeamProfile(profile_id="code-analysis-team", member_roles=("CODEGRAPH_ANALYZER",))

    def _assignment(self, **kwargs):
        values = dict(
            mission_id="mission-1", work_item_id="work-1", node_id="node-1",
            team_profile=self.profile, workspace_ref="workspace://mission-1/work-1",
            repo_ref="repo://pfc", evidence_contract=("CODEGRAPH_EXECUTION",),
            forbidden_actions=("SQL_EXECUTION",), trace_context={"trace_id": "trace-1"},
        )
        values.update(kwargs)
        return NodeWorkAssignment(**values)

    def test_bootstrap_claims_lease_starts_local_team_and_passes_assignment_context(self):
        attempt = self.adapter.start_assignment(self._assignment())
        self.assertEqual("team-1", attempt.team_id)
        self.assertEqual("workspace://mission-1/work-1", self.gateway.team_context["workspace_ref"])
        self.assertEqual("repo://pfc", self.gateway.team_context["repo_ref"])
        self.assertEqual(["CODEGRAPH_EXECUTION"], self.gateway.team_context["evidence_contract"])
        self.assertEqual({"trace_id": "trace-1"}, self.gateway.team_context["trace_context"])

    def test_assignment_node_mismatch_is_rejected_before_team_start(self):
        with self.assertRaisesRegex(DshNodeRuntimeAdapterError, "ASSIGNMENT_NODE_MISMATCH"):
            self.adapter.start_assignment(self._assignment(node_id="node-2"))
        self.assertIsNone(self.gateway.team_context)

    def test_forbidden_action_and_evidence_contract_fail_closed(self):
        attempt = self.adapter.start_assignment(self._assignment())
        agent = attempt.dispatch_member("CODEGRAPH_ANALYZER")
        with self.assertRaisesRegex(DshNodeRuntimeAdapterError, "WORK_ASSIGNMENT_ACTION_FORBIDDEN:SQL_EXECUTION"):
            attempt.start_tool(agent_id=agent, tool_id="sql", action="SQL_EXECUTION")
        self.assertEqual([], self.gateway.tool_starts)

        attempt.start_tool(agent_id=agent, tool_id="codegraph", action="CODEGRAPH_EXECUTION")
        with self.assertRaisesRegex(DshNodeRuntimeAdapterError, "EVIDENCE_TYPE_OUTSIDE_CONTRACT"):
            attempt.emit_evidence(
                agent_id=agent, tool_id="codegraph", evidence_id="bad-1", evidence_type="SQL_EXECUTION"
            )

    def test_happy_path_submits_raw_result_but_does_not_self_evaluate_sufficiency(self):
        attempt = self.adapter.start_assignment(self._assignment())
        agent = attempt.dispatch_member("CODEGRAPH_ANALYZER")
        attempt.start_tool(agent_id=agent, tool_id="codegraph", action="CODEGRAPH_EXECUTION")
        evidence = attempt.emit_evidence(
            agent_id=agent, tool_id="codegraph", evidence_id="graph-1",
            evidence_type="CODEGRAPH_EXECUTION", refs=["artifact://graph-1"],
        )
        result = attempt.complete_and_submit()
        self.assertEqual(attempt.attempt_id, evidence.attempt_id)
        self.assertEqual(attempt.attempt_id, result.attempt_id)
        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        self.assertEqual("NODE_RESULT_SUBMITTED", events[-1]["event_type"])
        self.assertNotIn("CENTER_EVALUATED", [event["event_type"] for event in events])


if __name__ == "__main__":
    unittest.main()
