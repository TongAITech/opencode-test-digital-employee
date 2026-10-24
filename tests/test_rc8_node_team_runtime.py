import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import (
    CenterControlError,
    CenterControlPlane,
    MemoryCenterRepository,
    WorkItemState,
)
from rc8_center.distributed_orchestration import ActorRole
from rc8_center.node_team_runtime import (
    NodeTeamLifecycle,
    NodeTeamRuntime,
    NodeTeamRuntimeError,
    TeamProfile,
)
from rc8_runtime.contracts import (
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    WorkItemIdentity,
)
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


class FakeDshAgentTeamsGateway:
    def __init__(self):
        self.fail_team_start = False
        self.fail_tool_start = False
        self.team_starts = []
        self.member_dispatches = []
        self.tool_starts = []
        self.completed = []
        self.aborted = []

    def start_team(self, *, profile_id, member_roles, context):
        if self.fail_team_start:
            raise RuntimeError("agent teams unavailable")
        self.team_starts.append((profile_id, tuple(member_roles), dict(context)))
        return "team-1"

    def dispatch_member(self, *, team_id, role, context):
        self.member_dispatches.append((team_id, role, dict(context)))
        return "agent-%s" % role.lower()

    def start_tool(self, *, team_id, agent_id, tool_id, action, payload):
        if self.fail_tool_start:
            raise RuntimeError("tool unavailable")
        self.tool_starts.append((team_id, agent_id, tool_id, action, dict(payload)))
        return "invoke-%s" % (len(self.tool_starts),)

    def complete_team(self, *, team_id):
        self.completed.append(team_id)

    def abort_team(self, *, team_id, reason):
        self.aborted.append((team_id, reason))


class NodeTeamRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.now = [100]
        self.repo = MemoryCenterRepository()
        self.ledger = CentralR1RuntimeLedger(str(Path(self.temp_dir.name) / "event-stream.jsonl"))
        self.center = CenterControlPlane(self.repo, self.ledger, now_fn=lambda: self.now[0])
        self.gateway = FakeDshAgentTeamsGateway()
        self.profile = TeamProfile(
            profile_id="code-analysis-team",
            member_roles=("CHANGE_ANALYZER", "CODEGRAPH_ANALYZER"),
        )
        self._add_node("node-1")
        self._register_and_lease("node-1")

    def _add_node(self, node_id):
        self.center.register_node(
            NodeIdentity(
                node_id=node_id,
                operator_ref="operator-test",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        for capability in ("codegraph", "agent_teams"):
            self.center.qualify_capability(
                CapabilityQualification(
                    node_id=node_id,
                    capability_id=capability,
                    state=CapabilityState.VERIFIED,
                    probe_ref="probe://%s/%s" % (node_id, capability),
                    evidence_refs=["evidence://%s/%s" % (node_id, capability)],
                    verified_at=1,
                )
            )

    def _register_and_lease(self, node_id):
        self.center.register_work_item(
            WorkItemIdentity(
                work_item_id="work-1",
                test_run_id="run-1",
                stage="CODE_ANALYSIS",
                scope_refs=["scope-1"],
                required_capabilities=["codegraph", "agent_teams"],
            )
        )
        return self.center.lease_work_item("work-1", node_id, ttl_seconds=60)

    def _runtime(self, node_id="node-1"):
        return NodeTeamRuntime(
            self.center,
            self.gateway,
            mission_id="mission-1",
            work_item_id="work-1",
            node_id=node_id,
            team_profile=self.profile,
        )

    def _to_dispatched_agent(self, runtime):
        claim = runtime.claim()
        runtime.start_team()
        agent_id = runtime.dispatch_member("CODEGRAPH_ANALYZER")
        return claim, agent_id

    def test_happy_path_writes_node_team_tool_and_evidence_provenance_to_r1(self):
        runtime = self._runtime()
        claim, agent_id = self._to_dispatched_agent(runtime)
        invocation_id = runtime.start_tool(
            agent_id=agent_id,
            tool_id="codegraph",
            action="CODEGRAPH_EXECUTION",
            payload={"changed_file": "src/Foo.java"},
        )
        evidence = runtime.emit_evidence(
            agent_id=agent_id,
            tool_id="codegraph",
            evidence_id="evidence-graph-1",
            evidence_type="CODEGRAPH_EXECUTION",
            refs=["artifact://graph-evidence/1"],
        )
        runtime.complete_team()
        runtime.submit_result()
        runtime.center_evaluate(accepted=True, evaluator_ref="center-sufficiency")

        self.assertEqual("invoke-1", invocation_id)
        self.assertEqual(claim.attempt_id, evidence.attempt_id)
        self.assertEqual("team-1", evidence.team_id)
        self.assertEqual(agent_id, evidence.agent_id)
        self.assertEqual("codegraph", evidence.tool_id)
        self.assertEqual("evidence-graph-1", evidence.evidence_id)

        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        event_types = [event["event_type"] for event in events]
        self.assertEqual(
            [
                "NODE_CLAIMED",
                "TEAM_STARTED",
                "TEAM_MEMBER_DISPATCHED",
                "TOOL_EXECUTION_STARTED",
                "EVIDENCE_EMITTED",
                "TEAM_COMPLETED",
                "NODE_RESULT_SUBMITTED",
                "CENTER_EVALUATED",
            ],
            event_types,
        )
        evidence_event = [event for event in events if event["event_type"] == "EVIDENCE_EMITTED"][0]
        data = evidence_event["data"]
        self.assertEqual("mission-1", data["mission_id"])
        self.assertEqual("CODE_ANALYSIS", data["stage_id"])
        self.assertEqual("work-1", data["work_item_id"])
        self.assertEqual(claim.attempt_id, data["attempt_id"])
        self.assertEqual("node-1", data["node_id"])
        self.assertEqual("team-1", data["team_id"])
        self.assertEqual(agent_id, data["agent_id"])
        self.assertEqual("codegraph", data["tool_id"])
        self.assertEqual("evidence-graph-1", data["evidence_id"])

        work = self.repo.get_work_item("work-1")
        self.assertEqual(WorkItemState.COMPLETED, work.state)
        self.assertIsNone(work.lease_id)

    def test_director_cannot_execute_domain_tool_even_on_same_node(self):
        runtime = self._runtime()
        _, agent_id = self._to_dispatched_agent(runtime)

        with self.assertRaisesRegex(CenterControlError, "DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN"):
            runtime.start_tool(
                agent_id=agent_id,
                tool_id="codegraph",
                action="CODEGRAPH_EXECUTION",
                actor_role=ActorRole.DIRECTOR,
            )

        self.assertEqual([], self.gateway.tool_starts)
        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        self.assertNotIn("TOOL_EXECUTION_STARTED", [event["event_type"] for event in events])

    def test_old_attempt_is_rejected_after_expiry_and_re_lease_on_same_node(self):
        runtime = self._runtime()
        first = runtime.claim()
        self.now[0] = 200
        second_lease = self.center.lease_work_item("work-1", "node-1", ttl_seconds=60)
        self.assertNotEqual(first.attempt_id, second_lease.lease_id)

        with self.assertRaisesRegex(NodeTeamRuntimeError, "STALE_ATTEMPT:LEASE_ID_CHANGED"):
            runtime.start_team()

        self.assertEqual(NodeTeamLifecycle.STALE_ATTEMPT, runtime.state)
        self.assertEqual([], self.gateway.team_starts)

    def test_wrong_node_cannot_claim_work_item(self):
        self._add_node("node-2")
        runtime = self._runtime(node_id="node-2")
        with self.assertRaisesRegex(NodeTeamRuntimeError, "WORK_ITEM_ASSIGNED_TO_DIFFERENT_NODE"):
            runtime.claim()

    def test_evidence_is_rejected_before_matching_tool_execution(self):
        runtime = self._runtime()
        _, agent_id = self._to_dispatched_agent(runtime)
        with self.assertRaisesRegex(NodeTeamRuntimeError, "EVIDENCE_REQUIRES_TOOL_EXECUTION"):
            runtime.emit_evidence(
                agent_id=agent_id,
                tool_id="codegraph",
                evidence_id="fake-evidence",
                evidence_type="CODEGRAPH_EXECUTION",
            )

    def test_team_formation_failure_is_first_class_r1_event(self):
        runtime = self._runtime()
        runtime.claim()
        self.gateway.fail_team_start = True

        with self.assertRaisesRegex(NodeTeamRuntimeError, "TEAM_FORMATION_FAILED"):
            runtime.start_team()

        self.assertEqual(NodeTeamLifecycle.TEAM_FORMATION_FAILED, runtime.state)
        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        self.assertEqual("TEAM_FORMATION_FAILED", events[-1]["event_type"])
        self.assertEqual("DSH_NODE", events[-1]["data"]["actor_role"])

    def test_tool_failure_is_first_class_and_cannot_become_evidence(self):
        runtime = self._runtime()
        _, agent_id = self._to_dispatched_agent(runtime)
        self.gateway.fail_tool_start = True

        with self.assertRaisesRegex(NodeTeamRuntimeError, "TOOL_UNAVAILABLE"):
            runtime.start_tool(
                agent_id=agent_id,
                tool_id="codegraph",
                action="CODEGRAPH_EXECUTION",
            )

        self.assertEqual(NodeTeamLifecycle.TOOL_UNAVAILABLE, runtime.state)
        events = self.ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        self.assertEqual("TOOL_UNAVAILABLE", events[-1]["event_type"])
        self.assertNotIn("EVIDENCE_EMITTED", [event["event_type"] for event in events])


if __name__ == "__main__":
    unittest.main()
