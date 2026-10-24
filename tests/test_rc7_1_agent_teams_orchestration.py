from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc6_runtime.agent_runtime import WorkerInvocation
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission, MissionTaskGraphCompiler
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge, DshWorkerBridgeError


MISSION_ID = "MISSION-AGENT-TEAMS-HARD-GATE"


def _control(tmp_path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION_ID,
            release_id="RC7.1",
            goal="prove Director cannot bypass AgentTeams",
        ),
    )
    graph = MissionTaskGraphCompiler().install(control, MISSION_ID)
    return truth, control, graph


def _launcher(tmp_path, truth):
    return Rc7AuthorizedDshHeadlessWorkerLauncher(
        dsh_bin=str(tmp_path / "dsh-not-executed"),
        patch_path=str(tmp_path / "rc7-dsh.patch.yml"),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC7AuthorityRuntime(b"agent-teams-test-secret-0123456789abcdef"),
        coordinator_instance_id="rc7.1-bank-autopilot",
        release_id="RC7.1",
        state_root=str(tmp_path / "runtime-state"),
        timeout_seconds=30,
    )


def _write_team(
    tmp_path,
    task,
    *,
    assignee="requirements",
    member_status="idle",
    task_status="pending",
    task_description=None,
):
    folder = tmp_path / ".agent-teams" / "rc7-bank-team"
    folder.mkdir(parents=True, exist_ok=True)
    team_task = {
        "id": "team-task-requirements",
        "subject": "RC7_TASK_ID=%s analyze requirements" % task.task_id,
        "status": task_status,
        "assignee": assignee,
        "dependencies": [],
        "createdAt": 1,
        "updatedAt": 1,
    }
    if task_description is not None:
        team_task["description"] = task_description
    payload = {
        "name": "rc7-bank-team",
        "id": "rc7-bank-team",
        "description": "RC7_MISSION_ID=%s bank mission team" % MISSION_ID,
        "captainSessionId": "captain-session-1",
        "createdAt": 1,
        "phase": "running",
        "members": [
            {
                "id": "member-session-requirements",
                "name": "requirements",
                "role": "requirements analyst",
                "joinedAt": 1,
                "status": member_status,
            }
        ],
        "tasks": [team_task],
        "taskSeq": 1,
    }
    path = folder / "team.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _running_task(control, task, assignment):
    leased = control.lease_next(
        worker_ref=assignment.worker_instance_id,
        capabilities=task.required_capabilities,
    )
    assert leased is not None
    assert leased.task_id == task.task_id
    return control.start(task.task_id, worker_ref=assignment.worker_instance_id)


def _invocation(assignment, *, attempt_id=None):
    return WorkerInvocation(
        worker_instance_id=assignment.worker_instance_id,
        agent_id=assignment.agent_id,
        mission_id=assignment.mission_id,
        attempt_id=attempt_id or assignment.attempt_id,
        assignment_id=assignment.assignment_id,
        lease_id=assignment.lease.lease_id,
        parent_worker_id=assignment.parent_worker_id,
        scope=assignment.scope,
        input_refs=list(assignment.input_refs),
        tool_calls=[{"call_ref": "dsh-event://tool-call/1", "tool_name": "filesystem"}],
        output_refs=["handoff://%s/%s" % (assignment.worker_instance_id, attempt_id or assignment.attempt_id)],
        evidence_refs=["dsh://session/session-specialist-1"],
        started_at=1,
        finished_at=2,
        result="PASS",
        dsh_session_id="session-specialist-1",
        exit_code=0,
    )


def _emit_success_terminal(launcher, invocation, *, include_handoff=True):
    launcher._emit("WORKER_STARTED", invocation)
    launcher._emit("WORKER_OUTPUT_PRODUCED", invocation)
    launcher._emit("WORKER_COMPLETED", invocation)
    if include_handoff:
        launcher._emit("HANDOFF_RETURNED", invocation)


def _raw_output(bridge, task):
    artifact_id, artifact_type = bridge.expected_output(task)
    return {
        "task_id": task.task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "content_ref": "worker://candidate/%s" % task.task_id,
            "parent_refs": list(task.input_artifact_refs),
            "evidence_refs": [],
        },
        "semantic_payload": {"summary": "specialist result backed by a real tool call"},
        "evidence": [
            {
                "kind": "SPECIALIST_RESULT_PROOF",
                "source_ref": "dsh://worker/test",
                "content_ref": "evidence://specialist/result",
                "subject_refs": [task.task_id],
            }
        ],
    }


def test_bank_worker_without_team_auto_bootstrap_fails_closed_if_dsh_unavailable(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    bridge = DshTaskWorkerBridge(control, _launcher(tmp_path, truth))
    task = graph.task("REQUIREMENT_ANALYSIS")

    with pytest.raises(
        DshWorkerBridgeError,
        match="AGENT_TEAMS_BOOTSTRAP_FAILED:AGENT_TEAMS_BOOTSTRAP_DSH_NOT_AVAILABLE",
    ):
        bridge._assign(task, bridge.node_policies[task.node])

    assert truth.query("rc7_evidence", mission_id=MISSION_ID) == []


def test_captain_cannot_be_professional_task_assignee(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task, assignee="captain")
    bridge = DshTaskWorkerBridge(control, _launcher(tmp_path, truth))

    with pytest.raises(DshWorkerBridgeError, match="DIRECTOR_SELF_EXECUTION_FORBIDDEN"):
        bridge._assign(task, bridge.node_policies[task.node])


def test_bank_worker_is_parented_by_agent_teams_member_and_receipt_is_in_r1(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task)
    launcher = _launcher(tmp_path, truth)
    bridge = DshTaskWorkerBridge(control, launcher)

    assignment = bridge._assign(task, bridge.node_policies[task.node])

    assert assignment.parent_worker_id == "member-session-requirements"
    assert assignment.parent_worker_id != launcher.coordinator_instance_id
    assert assignment.worker_instance_id not in {
        assignment.parent_worker_id,
        launcher.coordinator_instance_id,
        "captain-session-1",
    }

    rows = truth.query("rc7_evidence", mission_id=MISSION_ID)
    team_rows = [row for row in rows if row.get("kind") == "DSH_AGENT_TEAMS_ASSIGNMENT"]
    execution_rows = [row for row in rows if row.get("kind") == "DSH_AGENT_TEAMS_EXECUTION_BINDING"]
    assert len(team_rows) == 1
    assert len(execution_rows) == 1
    receipt_path = Path(team_rows[0]["content_ref"][len("file://") :])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["team"]["team_id"] == "rc7-bank-team"
    assert receipt["team"]["member_id"] == "member-session-requirements"
    assert receipt["parent_worker_id"] == "member-session-requirements"
    assert receipt["worker_instance_id"] == assignment.worker_instance_id
    assert receipt["director_self_execution_forbidden"] is True
    assert receipt["local_fallback_forbidden"] is True

    execution_path = Path(execution_rows[0]["content_ref"][len("file://") :])
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    assert execution["team_id"] == "rc7-bank-team"
    assert execution["team_task_id"] == "team-task-requirements"
    assert execution["member_id"] == "member-session-requirements"
    assert execution["worker_instance_id"] == assignment.worker_instance_id
    assert execution["worker_assignment_id"] == assignment.assignment_id
    assert execution["attempt_id"] == assignment.attempt_id
    assert execution["lease_id"] == assignment.lease.lease_id
    assert execution["assignment_evidence_id"] == team_rows[0]["evidence_id"]

    prompt = bridge.compile_prompt(task, assignment)
    assert "TEAM_ASSIGNMENT_CONTRACT=" in prompt
    assert '"member_id": "member-session-requirements"' in prompt

    reopened = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    reopened_rows = reopened.query("rc7_evidence", evidence_id=execution_rows[0]["evidence_id"])
    assert len(reopened_rows) == 1
    assert reopened_rows[0]["content_hash"] == execution_rows[0]["content_hash"]


def test_terminal_binding_requires_same_agent_teams_identity_and_full_terminal_chain(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task)
    launcher = _launcher(tmp_path, truth)
    bridge = DshTaskWorkerBridge(control, launcher)
    assignment = bridge._assign(task, bridge.node_policies[task.node])
    running = _running_task(control, task, assignment)
    invocation = _invocation(assignment)
    _emit_success_terminal(launcher, invocation)

    bridge.normalize_output(running, invocation, _raw_output(bridge, running))

    terminal_rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_TERMINAL_BINDING"
    ]
    assert len(terminal_rows) == 1
    receipt = json.loads(Path(terminal_rows[0]["content_ref"][len("file://") :]).read_text(encoding="utf-8"))
    assert receipt["team_id"] == "rc7-bank-team"
    assert receipt["team_task_id"] == "team-task-requirements"
    assert receipt["member_id"] == "member-session-requirements"
    assert receipt["worker_instance_id"] == assignment.worker_instance_id
    assert receipt["worker_assignment_id"] == assignment.assignment_id
    assert receipt["attempt_id"] == assignment.attempt_id
    assert receipt["lease_id"] == assignment.lease.lease_id
    assert receipt["result"] == "PASS"
    assert set(receipt["terminal_event_ids"]) == {
        "WORKER_STARTED",
        "WORKER_OUTPUT_PRODUCED",
        "WORKER_COMPLETED",
        "HANDOFF_RETURNED",
    }

    bridge.normalize_output(running, invocation, _raw_output(bridge, running))
    replay_rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_TERMINAL_BINDING"
    ]
    assert len(replay_rows) == 1
    assert replay_rows[0]["evidence_id"] == terminal_rows[0]["evidence_id"]


def test_missing_handoff_cannot_create_agent_teams_terminal_binding(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task)
    launcher = _launcher(tmp_path, truth)
    bridge = DshTaskWorkerBridge(control, launcher)
    assignment = bridge._assign(task, bridge.node_policies[task.node])
    running = _running_task(control, task, assignment)
    invocation = _invocation(assignment)
    _emit_success_terminal(launcher, invocation, include_handoff=False)

    with pytest.raises(
        DshWorkerBridgeError,
        match="AGENT_TEAMS_TERMINAL_EVENT_NOT_UNIQUE:HANDOFF_RETURNED:0",
    ):
        bridge.normalize_output(running, invocation, _raw_output(bridge, running))

    assert not [
        row for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_TERMINAL_BINDING"
    ]


def test_attempt_identity_drift_is_rejected_even_with_worker_pass(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task)
    launcher = _launcher(tmp_path, truth)
    bridge = DshTaskWorkerBridge(control, launcher)
    assignment = bridge._assign(task, bridge.node_policies[task.node])
    running = _running_task(control, task, assignment)
    invocation = _invocation(assignment, attempt_id="ATT-DRIFTED")
    _emit_success_terminal(launcher, invocation)

    with pytest.raises(DshWorkerBridgeError, match="AGENT_TEAMS_TERMINAL_ATTEMPT_ID_MISMATCH"):
        bridge.normalize_output(running, invocation, _raw_output(bridge, running))

    assert not [
        row for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_TERMINAL_BINDING"
    ]


def test_removed_agent_teams_member_cannot_receive_rc7_execution(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(tmp_path, task, member_status="removed")
    bridge = DshTaskWorkerBridge(control, _launcher(tmp_path, truth))

    with pytest.raises(DshWorkerBridgeError, match="AGENT_TEAMS_MEMBER_REMOVED"):
        bridge._assign(task, bridge.node_policies[task.node])


def test_completed_coordination_slot_still_dispatches_governed_child_worker(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(
        tmp_path,
        task,
        task_status="completed",
        task_description=(
            "RC7_COORDINATION_SLOT=true; durable ownership handoff only; "
            "business execution remains governed by canonical RC7 child worker"
        ),
    )
    launcher = _launcher(tmp_path, truth)
    bridge = DshTaskWorkerBridge(control, launcher)

    assignment = bridge._assign(task, bridge.node_policies[task.node])

    assert assignment.parent_worker_id == "member-session-requirements"
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION_ID)
        if row.get("kind") == "DSH_AGENT_TEAMS_ASSIGNMENT"
    ]
    assert len(rows) == 1
    receipt = json.loads(Path(rows[0]["content_ref"][len("file://") :]).read_text(encoding="utf-8"))
    assert receipt["team"]["team_task_status"] == "completed"
    assert receipt["director_self_execution_forbidden"] is True


def test_completed_non_coordination_task_cannot_impersonate_execution_pass(tmp_path) -> None:
    truth, control, graph = _control(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    _write_team(
        tmp_path,
        task,
        task_status="completed",
        task_description="ordinary team task with no RC7 coordination marker",
    )
    bridge = DshTaskWorkerBridge(control, _launcher(tmp_path, truth))

    with pytest.raises(DshWorkerBridgeError, match="AGENT_TEAMS_TASK_NOT_DISPATCHABLE:completed"):
        bridge._assign(task, bridge.node_policies[task.node])

    assert truth.query("rc7_evidence", mission_id=MISSION_ID) == []
