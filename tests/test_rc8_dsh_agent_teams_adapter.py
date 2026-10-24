import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from rc8_center.control_plane import CenterControlPlane, MemoryCenterRepository
from rc8_center.dsh_agent_teams_adapter import (
    DshAgentTeamsAdapterError,
    DshAgentTeamsProcessConfig,
    LocalProcessDshAgentTeamsGateway,
)
from rc8_center.node_team_runtime import NodeTeamRuntime, TeamProfile
from rc8_runtime.contracts import (
    CapabilityQualification,
    CapabilityState,
    NodeIdentity,
    WorkItemIdentity,
)
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


BRIDGE_SOURCE = r'''
import json
import os
import sys

raw = sys.stdin.readline()
request = json.loads(raw)
mode = os.environ.get("RC8_FAKE_BRIDGE_MODE", "ok")
if mode == "nonzero":
    sys.stderr.write("bridge failed")
    sys.exit(7)
if mode == "invalid-json":
    print("not-json")
    sys.exit(0)

capture = os.environ.get("RC8_FAKE_BRIDGE_CAPTURE")
if capture:
    with open(capture, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(request, sort_keys=True) + "\n")

operation = request["operation"]
if operation == "start_team":
    result = {"team_id": "team-process-1"}
elif operation == "dispatch_member":
    result = {"agent_id": "agent-" + request["payload"]["role"].lower()}
elif operation == "start_tool":
    result = {"invocation_id": "invoke-process-1"}
elif operation in ("complete_team", "abort_team"):
    result = {}
else:
    result = {}

response = {
    "contract": request["contract"],
    "request_id": request["request_id"],
    "ok": True,
    "result": result,
}
if mode == "mismatch":
    response["request_id"] = "wrong-request"
print(json.dumps(response))
'''


class DshAgentTeamsAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.bridge = self.root / "bridge.py"
        self.bridge.write_text(BRIDGE_SOURCE, encoding="utf-8")
        self.capture = self.root / "capture.jsonl"

    def _gateway(self, mode="ok"):
        return LocalProcessDshAgentTeamsGateway(
            DshAgentTeamsProcessConfig(
                command=(sys.executable, str(self.bridge)),
                timeout_seconds=10,
                extra_env={
                    "RC8_FAKE_BRIDGE_MODE": mode,
                    "RC8_FAKE_BRIDGE_CAPTURE": str(self.capture),
                },
            )
        )

    def test_process_gateway_implements_all_node_local_team_operations(self):
        gateway = self._gateway()
        context = {
            "mission_id": "mission-1",
            "stage_id": "CODE_ANALYSIS",
            "work_item_id": "work-1",
            "attempt_id": "attempt-1",
            "node_id": "node-1",
        }
        team_id = gateway.start_team(
            profile_id="code-analysis-team",
            member_roles=("CODEGRAPH_ANALYZER",),
            context=context,
        )
        agent_id = gateway.dispatch_member(
            team_id=team_id,
            role="CODEGRAPH_ANALYZER",
            context=context,
        )
        invocation_id = gateway.start_tool(
            team_id=team_id,
            agent_id=agent_id,
            tool_id="codegraph",
            action="CODEGRAPH_EXECUTION",
            payload={"changed_file": "src/Foo.java"},
        )
        gateway.complete_team(team_id=team_id)

        self.assertEqual("team-process-1", team_id)
        self.assertEqual("agent-codegraph_analyzer", agent_id)
        self.assertEqual("invoke-process-1", invocation_id)
        requests = [json.loads(line) for line in self.capture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            ["start_team", "dispatch_member", "start_tool", "complete_team"],
            [item["operation"] for item in requests],
        )
        self.assertEqual("attempt-1", requests[0]["payload"]["context"]["attempt_id"])
        self.assertEqual("node-1", requests[0]["payload"]["context"]["node_id"])
        self.assertEqual("rc8.dsh-agent-teams.v1", requests[0]["contract"])

    def test_process_gateway_fail_closed_on_missing_command_nonzero_and_malformed_output(self):
        missing = LocalProcessDshAgentTeamsGateway(
            DshAgentTeamsProcessConfig(command=(str(self.root / "not-found"),), timeout_seconds=1)
        )
        with self.assertRaisesRegex(DshAgentTeamsAdapterError, "COMMAND_NOT_FOUND"):
            missing.start_team(profile_id="p", member_roles=("R",), context={})

        with self.assertRaisesRegex(DshAgentTeamsAdapterError, "EXIT_NONZERO:7"):
            self._gateway("nonzero").start_team(profile_id="p", member_roles=("R",), context={})

        with self.assertRaisesRegex(DshAgentTeamsAdapterError, "INVALID_JSON"):
            self._gateway("invalid-json").start_team(profile_id="p", member_roles=("R",), context={})

        with self.assertRaisesRegex(DshAgentTeamsAdapterError, "REQUEST_ID_MISMATCH"):
            self._gateway("mismatch").start_team(profile_id="p", member_roles=("R",), context={})

    def test_shell_bridge_factory_is_capability_based_and_requires_git_bash_on_windows(self):
        linux = DshAgentTeamsProcessConfig.for_shell_bridge(
            os_family="linux",
            bridge_script="bin/dsh-agent-teams-bridge.sh",
        )
        self.assertEqual(("bash", "bin/dsh-agent-teams-bridge.sh"), linux.command)

        with self.assertRaisesRegex(DshAgentTeamsAdapterError, "WINDOWS_DSH_NODE_REQUIRES_GIT_BASH"):
            DshAgentTeamsProcessConfig.for_shell_bridge(
                os_family="windows",
                bridge_script="bin/dsh-agent-teams-bridge.sh",
            )
        windows = DshAgentTeamsProcessConfig.for_shell_bridge(
            os_family="windows",
            bridge_script="bin/dsh-agent-teams-bridge.sh",
            git_bash_executable="C:/Program Files/Git/bin/bash.exe",
        )
        self.assertEqual("C:/Program Files/Git/bin/bash.exe", windows.command[0])

    def test_real_process_gateway_plugs_into_existing_node_team_runtime_and_r1(self):
        repo = MemoryCenterRepository()
        ledger = CentralR1RuntimeLedger(str(self.root / "event-stream.jsonl"))
        center = CenterControlPlane(repo, ledger, now_fn=lambda: 100)
        center.register_node(
            NodeIdentity(
                node_id="node-1",
                operator_ref="operator-test",
                os_family="linux",
                architecture="x86_64",
                shell="bash",
                registered_at=1,
            )
        )
        for capability in ("codegraph", "agent_teams"):
            center.qualify_capability(
                CapabilityQualification(
                    node_id="node-1",
                    capability_id=capability,
                    state=CapabilityState.VERIFIED,
                    probe_ref="probe://node-1/%s" % capability,
                    evidence_refs=["evidence://node-1/%s" % capability],
                    verified_at=1,
                )
            )
        center.register_work_item(
            WorkItemIdentity(
                work_item_id="work-1",
                test_run_id="run-1",
                stage="CODE_ANALYSIS",
                scope_refs=["scope-1"],
                required_capabilities=["codegraph", "agent_teams"],
            )
        )
        center.lease_work_item("work-1", "node-1", ttl_seconds=60)
        runtime = NodeTeamRuntime(
            center,
            self._gateway(),
            mission_id="mission-1",
            work_item_id="work-1",
            node_id="node-1",
            team_profile=TeamProfile(
                profile_id="code-analysis-team",
                member_roles=("CODEGRAPH_ANALYZER",),
            ),
        )

        claim = runtime.claim()
        runtime.start_team()
        agent_id = runtime.dispatch_member("CODEGRAPH_ANALYZER")
        runtime.start_tool(
            agent_id=agent_id,
            tool_id="codegraph",
            action="CODEGRAPH_EXECUTION",
            payload={"changed_file": "src/Foo.java"},
        )
        evidence = runtime.emit_evidence(
            agent_id=agent_id,
            tool_id="codegraph",
            evidence_id="graph-evidence-1",
            evidence_type="CODEGRAPH_EXECUTION",
            refs=["artifact://graph-evidence-1"],
        )
        runtime.complete_team()
        runtime.submit_result()
        runtime.center_evaluate(accepted=True, evaluator_ref="center-sufficiency")

        self.assertEqual(claim.attempt_id, evidence.attempt_id)
        self.assertEqual("node-1", evidence.node_id)
        events = ledger.runtime_events(test_run_id="run-1", work_item_id="work-1")
        self.assertIn("EVIDENCE_EMITTED", [event["event_type"] for event in events])
        self.assertEqual("team-process-1", evidence.team_id)


if __name__ == "__main__":
    unittest.main()
