from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission, MissionTaskGraphCompiler, TaskStatus
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge, DshWorkerBridgeError


class FakeDshLauncher:
    """Interface fake only; not a reality qualification substitute."""

    def __init__(self, graph, *, wrong_artifact_id: bool = False, no_tool_calls: bool = False) -> None:
        self.coordinator_instance_id = "coordinator-session-A"
        self.graph = graph
        self.wrong_artifact_id = wrong_artifact_id
        self.no_tool_calls = no_tool_calls
        self.prompts = []
        self.assignments = []

    def assign(
        self,
        *,
        agent_id,
        role,
        phase,
        mission_id,
        attempt_id,
        scope,
        input_refs,
        allowed_artifact_types,
        allowed_tools,
        parent_worker_id=None,
        generation=0,
    ):
        assignment = SimpleNamespace(
            worker_instance_id="worker-dsh-req-1",
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-dsh-req-1",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )
        self.assignments.append(assignment)
        return assignment

    def execute(self, assignment, prompt):
        self.prompts.append(prompt)
        invocation = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-worker-req-1",
            tool_calls=(
                ()
                if self.no_tool_calls
                else ({"call_ref": "dsh-event://tool-call/1", "tool_name": "filesystem"},)
            ),
            evidence_refs=(
                "dsh://session/session-worker-req-1",
                "file:///tmp/rc7-dsh-worker-req-1.jsonl",
            ),
        )
        expected_id = self.graph.artifact_ids["REQUIREMENT_ANALYSIS"]
        output = {
            "task_id": self.graph.task("REQUIREMENT_ANALYSIS").task_id,
            "artifact": {
                "artifact_id": "ART-WORKER-INVENTED-ID" if self.wrong_artifact_id else expected_id,
                "artifact_type": "REQUIREMENT_MODEL",
                "content_ref": "artifact://requirement-analysis/e2e",
                "parent_refs": [],
                "evidence_refs": ["source://sst/1"],
            },
            "evidence": [
                {
                    "kind": "SOURCE_DOCUMENT",
                    "source_ref": "filesystem://sst.md",
                    "content_ref": "evidence://sst/1",
                    "subject_refs": [self.graph.task("REQUIREMENT_ANALYSIS").task_id],
                }
            ],
        }
        return invocation, output


def _runtime(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="MISSION-DSH-BRIDGE",
            release_id="RC7",
            goal="prove DSH worker boundary",
        ),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(control, "MISSION-DSH-BRIDGE")
    return truth, control, graph


def test_dsh_worker_bridge_stops_at_candidate_output_and_persists_runtime_evidence(tmp_path) -> None:
    truth, control, graph = _runtime(tmp_path)
    launcher = FakeDshLauncher(graph)
    bridge = DshTaskWorkerBridge(control, launcher)

    result = bridge.run_next()
    assert result is not None
    requirement_task = graph.task("REQUIREMENT_ANALYSIS")
    assert result.task_id == requirement_task.task_id
    assert result.worker_instance_id == "worker-dsh-req-1"
    assert result.dsh_session_id == "session-worker-req-1"
    assert result.tool_call_count == 1
    assert result.raw_output_ref == "file:///tmp/rc7-dsh-worker-req-1.jsonl"
    assert result.task_state == TaskStatus.OUTPUT_PRODUCED.value

    # A successful DSH process is never acceptance authority.
    persisted_task = control.scheduler.task(requirement_task.task_id)
    assert persisted_task.state == TaskStatus.OUTPUT_PRODUCED
    assert persisted_task.state != TaskStatus.PASS
    assert persisted_task.evaluation_id is None

    expected_id = graph.artifact_ids["REQUIREMENT_ANALYSIS"]
    assert result.output_artifact_ids == (expected_id,)
    artifact = truth.query("rc7_artifact", artifact_id=expected_id)[0]
    assert artifact["producer_task_id"] == requirement_task.task_id
    assert artifact["artifact_type_name"] == "REQUIREMENT_MODEL"

    evidence_rows = truth.query("rc7_evidence", mission_id="MISSION-DSH-BRIDGE")
    assert len(evidence_rows) >= 3
    contents = {row["content_ref"] for row in evidence_rows}
    assert "dsh://session/session-worker-req-1" in contents
    assert "file:///tmp/rc7-dsh-worker-req-1.jsonl" in contents
    assert "evidence://sst/1" in contents

    assert len(launcher.prompts) == 1
    prompt = launcher.prompts[0]
    assert requirement_task.task_id in prompt
    assert expected_id in prompt
    assert "Do not evaluate or mark the task PASS" in prompt
    assert "previous chat transcript" not in prompt.lower()

    # Downstream Code remains locked because Requirement has not been accepted
    # by an independent evaluator yet.
    assert control.scheduler.task(graph.task("CODE_ANALYSIS").task_id).state == TaskStatus.REGISTERED


def test_dsh_worker_cannot_invent_canonical_artifact_identity(tmp_path) -> None:
    _truth, control, graph = _runtime(tmp_path)
    launcher = FakeDshLauncher(graph, wrong_artifact_id=True)
    bridge = DshTaskWorkerBridge(control, launcher)

    with pytest.raises(DshWorkerBridgeError, match="DSH_OUTPUT_ARTIFACT_ID_MISMATCH"):
        bridge.run_next()

    task = control.scheduler.task(graph.task("REQUIREMENT_ANALYSIS").task_id)
    assert task.state == TaskStatus.RUNNING
    assert task.output_artifact_refs == []


def test_dsh_worker_handoff_without_real_tool_call_is_rejected(tmp_path) -> None:
    _truth, control, graph = _runtime(tmp_path)
    launcher = FakeDshLauncher(graph, no_tool_calls=True)
    bridge = DshTaskWorkerBridge(control, launcher)

    with pytest.raises(DshWorkerBridgeError, match="DSH_REAL_TOOL_CALL_REQUIRED"):
        bridge.run_next()

    task = control.scheduler.task(graph.task("REQUIREMENT_ANALYSIS").task_id)
    assert task.state == TaskStatus.RUNNING
    assert task.output_artifact_refs == []
