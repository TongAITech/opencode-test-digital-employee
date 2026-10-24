from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission
from rc7_runtime.agent_teams_bootstrap import (
    AgentTeamsBootstrapError,
    AgentTeamsMissionPlanCompiler,
    COORDINATION_TOOL_POLICY,
    DshAgentTeamsMissionBootstrapper,
)
from rc7_runtime.mission_graph import MissionTaskGraphCompiler


MISSION_ID = "MISSION-AGENT-TEAMS-BOOTSTRAP"
CAPTAIN_SESSION = "session-agent-teams-captain"


def _control(tmp_path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION_ID,
            release_id="RC7.1",
            goal="bootstrap real dsh-agent-teams ownership",
        ),
    )
    graph = MissionTaskGraphCompiler(
        MissionTaskGraphCompiler.GRAPH_V2
    ).install(control, MISSION_ID)
    return truth, control, graph


def _team_state(plan, *, bad_policy_member=None, missing_member_id=None):
    members = []
    for index, planned in enumerate(plan.members, start=1):
        name = planned["name"]
        policy = (
            "unsafe-wide-policy"
            if name == bad_policy_member
            else planned["tool_policy"]
        )
        member_id = "" if name == missing_member_id else "session-member-%02d-%s" % (index, name)
        members.append(
            {
                "id": member_id,
                "name": name,
                "role": planned["role"],
                "joinedAt": index,
                "status": "idle",
                "toolPolicy": policy,
            }
        )
    tasks = []
    for index, planned in enumerate(plan.tasks, start=1):
        tasks.append(
            {
                "id": "durable-team-task-%02d" % index,
                "profileSeedId": planned["id"],
                "subject": planned["subject"],
                "description": planned["description"],
                "status": "completed",
                "assignee": planned["assignee"],
                "dependencies": [],
                "createdAt": index,
                "updatedAt": index,
            }
        )
    return {
        "name": plan.team_name,
        "id": plan.team_name,
        "description": plan.description,
        "captainSessionId": CAPTAIN_SESSION,
        "createdAt": 1,
        "phase": "running",
        "members": members,
        "tasks": tasks,
        "taskSeq": len(tasks),
    }


class FakeAgentTeamsCreateRunner:
    def __init__(self, workspace: Path, plan, *, write_state=True, bad_policy_member=None, missing_member_id=None):
        self.workspace = workspace
        self.plan = plan
        self.write_state = write_state
        self.bad_policy_member = bad_policy_member
        self.missing_member_id = missing_member_id
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        prompt = command[-1]
        assert command[1:3] == ["--profile", "headless"]
        assert "/agent-teams" in prompt
        assert "agent_teams_create" in prompt
        assert '"approval": "automatic"' in prompt
        assert COORDINATION_TOOL_POLICY in prompt
        if self.write_state:
            folder = self.workspace / ".agent-teams" / self.plan.team_name
            folder.mkdir(parents=True, exist_ok=True)
            state = _team_state(
                self.plan,
                bad_policy_member=self.bad_policy_member,
                missing_member_id=self.missing_member_id,
            )
            (folder / "team.json").write_text(
                json.dumps(state, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        stdout = "\n".join(
            [
                json.dumps({"type": "session", "id": CAPTAIN_SESSION}),
                json.dumps(
                    {
                        "type": "tool_call",
                        "tool_name": "agent_teams_create",
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _bootstrapper(tmp_path, control, graph, runner):
    dsh = tmp_path / "dsh"
    dsh.write_text("fake executable", encoding="utf-8")
    patch = tmp_path / "rc7-dsh.patch.yml"
    patch.write_text("plugins: []\n", encoding="utf-8")
    return DshAgentTeamsMissionBootstrapper(
        control,
        graph=graph,
        dsh_bin=str(dsh),
        patch_path=str(patch),
        workspace_root=str(tmp_path),
        evidence_root=str(tmp_path / "runtime-state" / "evidence"),
        timeout_seconds=30,
        command_runner=runner,
    )


def test_plan_compiles_only_professional_nodes_and_keeps_r1_as_single_dag(tmp_path) -> None:
    _, _, graph = _control(tmp_path)
    plan = AgentTeamsMissionPlanCompiler().compile(graph)

    assert [item["name"] for item in plan.members] == [
        "requirements",
        "code-analysis",
        "test-design",
        "automation",
        "execution",
    ]
    assert all(item["tool_policy"] == COORDINATION_TOOL_POLICY for item in plan.members)
    assert len(plan.tasks) == 5
    assert all(item["dependencies"] == [] for item in plan.tasks)
    assert all("RC7_COORDINATION_SLOT=true" in item["description"] for item in plan.tasks)
    assert all("RC7_R1_DEPENDENCIES=" in item["description"] for item in plan.tasks)
    assert not any("REALITY_RECON" in item["subject"] for item in plan.tasks)


def test_bootstrap_requires_real_tool_call_and_real_plugin_state_then_reuses_idempotently(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    plan = AgentTeamsMissionPlanCompiler().compile(graph)
    runner = FakeAgentTeamsCreateRunner(tmp_path, plan)
    bootstrapper = _bootstrapper(tmp_path, control, graph, runner)

    first = bootstrapper.bootstrap()
    assert first.reused is False
    assert len(runner.calls) == 1
    assert first.team_id == plan.team_name
    assert first.captain_session_id == CAPTAIN_SESSION

    rows = [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_BOOTSTRAP"
    ]
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == first.evidence_id
    receipt = json.loads(
        Path(rows[0]["content_ref"][len("file://") :]).read_text(encoding="utf-8")
    )
    assert receipt["r1_is_execution_dag_authority"] is True
    assert receipt["director_self_execution_forbidden"] is True
    assert receipt["coordination_tool_policy"] == COORDINATION_TOOL_POLICY

    second = bootstrapper.bootstrap()
    assert second.reused is True
    assert len(runner.calls) == 1
    assert second.evidence_id == first.evidence_id
    rows_after = [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_BOOTSTRAP"
    ]
    assert len(rows_after) == 1

    reopened = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    assert len(reopened.query("rc7_evidence", evidence_id=first.evidence_id)) == 1


def test_tool_call_text_without_plugin_state_cannot_fake_bootstrap(tmp_path) -> None:
    _, control, graph = _control(tmp_path)
    plan = AgentTeamsMissionPlanCompiler().compile(graph)
    runner = FakeAgentTeamsCreateRunner(tmp_path, plan, write_state=False)
    bootstrapper = _bootstrapper(tmp_path, control, graph, runner)

    with pytest.raises(AgentTeamsBootstrapError, match="AGENT_TEAMS_BOOTSTRAP_STATE_MISSING"):
        bootstrapper.bootstrap()


def test_widened_member_tool_policy_is_rejected_fail_closed(tmp_path) -> None:
    _, control, graph = _control(tmp_path)
    plan = AgentTeamsMissionPlanCompiler().compile(graph)
    runner = FakeAgentTeamsCreateRunner(
        tmp_path,
        plan,
        bad_policy_member="requirements",
    )
    bootstrapper = _bootstrapper(tmp_path, control, graph, runner)

    with pytest.raises(
        AgentTeamsBootstrapError,
        match="AGENT_TEAMS_COORDINATION_POLICY_REQUIRED:requirements",
    ):
        bootstrapper.bootstrap()


def test_member_without_durable_session_is_rejected_fail_closed(tmp_path) -> None:
    _, control, graph = _control(tmp_path)
    plan = AgentTeamsMissionPlanCompiler().compile(graph)
    runner = FakeAgentTeamsCreateRunner(
        tmp_path,
        plan,
        missing_member_id="code-analysis",
    )
    bootstrapper = _bootstrapper(tmp_path, control, graph, runner)

    with pytest.raises(
        AgentTeamsBootstrapError,
        match="AGENT_TEAMS_MEMBER_SESSION_NOT_READY:code-analysis",
    ):
        bootstrapper.bootstrap()
