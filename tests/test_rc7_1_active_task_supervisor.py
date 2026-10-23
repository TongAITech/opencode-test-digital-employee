from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.active_task_supervisor import (
    MissionActiveTaskSupervisor,
    RecoverableDshTaskWorkerBridge,
)
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.bank_mission_autopilot import BankMissionAutopilot, discover_config
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import ControlPlaneError, WorkerOutput
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import Mission, MissionStatus, Task, TaskStatus


class RecoveryLauncher:
    def __init__(self, control, graph) -> None:
        self.control = control
        self.graph = graph
        self.coordinator_instance_id = "coordinator-recovery"
        self.assign_count = 0
        self.execute_count = 0
        self.late_predecessor_rejected = False

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
        self.assign_count += 1
        return SimpleNamespace(
            worker_instance_id="worker-recovery-%d" % self.assign_count,
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assignment-recovery-%d" % self.assign_count,
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment, prompt):
        self.execute_count += 1
        task = self.graph.task("REQUIREMENT_ANALYSIS")
        # The predecessor can be late, but the canonical lease has already been
        # fenced to the successor.  Its output must be rejected before it can
        # mutate R1.
        try:
            self.control.submit_worker_output(
                WorkerOutput(task_id=task.task_id, worker_ref="dead-worker")
            )
        except ControlPlaneError as exc:
            self.late_predecessor_rejected = "TASK_LEASE_OWNER_MISMATCH" in str(exc)

        invocation = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-recovery-%d" % self.execute_count,
            tool_calls=({"call_ref": "tool://read/1", "tool_name": "read_text"},),
            evidence_refs=("file:///tmp/recovery-worker.jsonl",),
        )
        output = {
            "task_id": task.task_id,
            "artifact": {
                "artifact_id": self.graph.artifact_ids["REQUIREMENT_ANALYSIS"],
                "artifact_type": "REQUIREMENT_MODEL",
                "content_ref": "candidate://recovered-requirement",
                "parent_refs": list(task.input_artifact_refs),
                "evidence_refs": [],
            },
            "semantic_payload": {"recovered": True},
            "evidence": [
                {
                    "kind": "SOURCE_DOCUMENT",
                    "source_ref": "file://source.md",
                    "content_ref": "evidence://recovered-source",
                    "subject_refs": [task.task_id],
                }
            ],
        }
        return invocation, output


def _v1_runtime(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="M-SUP", release_id="R-SUP", goal="supervisor recovery"),
    )
    graph = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V1).install(control, "M-SUP")
    return truth, control, graph


def test_orphaned_leased_task_returns_to_ready_without_replay(tmp_path: Path):
    truth, control, graph = _v1_runtime(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    leased = control.lease_next(
        worker_ref="dead-worker",
        capabilities=task.required_capabilities,
    )
    assert leased is not None and leased.state == TaskStatus.LEASED
    launcher = RecoveryLauncher(control, graph)
    bridge = RecoverableDshTaskWorkerBridge(control, launcher)
    supervisor = MissionActiveTaskSupervisor(
        control, bridge, evidence_root=str(tmp_path / "supervisor")
    )

    result = supervisor.handle(control.scheduler.task(task.task_id))
    assert result.state == TaskStatus.READY
    assert result.lease_owner is None
    assert launcher.execute_count == 0
    evidence = [
        row for row in truth.query("rc7_evidence", mission_id="M-SUP")
        if row.get("kind") == "ACTIVE_TASK_RECOVERY"
    ]
    assert any("RESET_LEASED_TO_READY" in list(row.get("subject_refs") or []) for row in evidence)


def test_read_only_running_worker_is_fenced_and_resumed_in_fresh_session(tmp_path: Path):
    truth, control, graph = _v1_runtime(tmp_path)
    task = graph.task("REQUIREMENT_ANALYSIS")
    leased = control.lease_next(
        worker_ref="dead-worker",
        capabilities=task.required_capabilities,
    )
    assert leased is not None
    control.start(task.task_id, worker_ref="dead-worker")

    launcher = RecoveryLauncher(control, graph)
    bridge = RecoverableDshTaskWorkerBridge(control, launcher)
    supervisor = MissionActiveTaskSupervisor(
        control, bridge, evidence_root=str(tmp_path / "supervisor")
    )
    result = supervisor.handle(control.scheduler.task(task.task_id))

    assert result.task_state == TaskStatus.OUTPUT_PRODUCED.value
    assert launcher.execute_count == 1
    assert launcher.late_predecessor_rejected is True
    current = control.scheduler.task(task.task_id)
    assert current.state == TaskStatus.OUTPUT_PRODUCED
    assert current.lease_owner == "worker-recovery-1"
    handoffs = truth.query("rc7_session_handoff", mission_id="M-SUP")
    assert len(handoffs) == 1
    assert handoffs[0]["status"] == "ACTIVATED"
    assert handoffs[0]["predecessor_session_ref"] == "dead-worker"
    assert handoffs[0]["successor_session_ref"] == "worker-recovery-1"


def test_running_side_effect_capable_task_never_blind_replays(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="M-UNSAFE", release_id="R-UNSAFE", goal="no blind replay"),
    )
    task = Task(
        task_id="T-SCRIPT-UNSAFE",
        mission_id="M-UNSAFE",
        node="SCRIPT_READINESS",
        task_type="REPAIR",
        objective="repair generated executable script",
        required_capabilities=["test_automation"],
    )
    control.register_task(task)
    leased = control.lease_next(
        worker_ref="dead-script-worker",
        capabilities=("test_automation",),
    )
    assert leased is not None
    control.start(task.task_id, worker_ref="dead-script-worker")

    launcher = SimpleNamespace(coordinator_instance_id="unused")
    bridge = RecoverableDshTaskWorkerBridge(control, launcher)
    supervisor = MissionActiveTaskSupervisor(
        control, bridge, evidence_root=str(tmp_path / "supervisor")
    )
    result = supervisor.handle(control.scheduler.task(task.task_id))

    assert result.state == TaskStatus.HUMAN_REQUIRED
    assert result.lease_owner is None
    mission = control._mission()
    assert mission.state == MissionStatus.WAITING_HUMAN
    gaps = truth.query("rc7_gap", mission_id="M-UNSAFE")
    assert len(gaps) == 1
    assert gaps[0]["category"] == "RESIDUAL_RISK_REQUIRES_ACCEPTANCE"
    assert gaps[0]["target_node"] == "HUMAN_GATE"
    assert gaps[0]["state"] == "HUMAN_REQUIRED"
    evaluation = truth.query("rc7_evaluation", evaluation_id=result.evaluation_id)[0]
    assert evaluation["dimensions"]["recovery_action"] == "SIDE_EFFECT_UNCERTAIN"
    assert evaluation["dimensions"]["blind_replay_forbidden"] is True


def _autopilot_package(tmp_path: Path):
    root = tmp_path / "package"
    (root / "runtime-state" / "r1").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "SOURCE_COMMIT").write_text("0123456789abcdef", encoding="utf-8")
    (root / "state" / "rc7-dsh-runtime-profile.json").write_text(
        json.dumps({"runtime_profile": "rc7-bank"}), encoding="utf-8"
    )
    (root / "state" / "rc7-dsh.patch.yml").write_text("patch: true\n", encoding="utf-8")
    dsh = root / "dsh"
    dsh.write_text("stub", encoding="utf-8")
    return root, dsh


def test_production_drive_uses_current_dispatcher_driver_api_and_advances_reality_recon(tmp_path: Path):
    root, dsh = _autopilot_package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="M-DRIVE",
        release_id="R-DRIVE",
        goal="prove production Autopilot wiring",
    )
    config = discover_config(
        r1_path=str(r1),
        mission_id="M-DRIVE",
        release_id="R-DRIVE",
        goal="prove production Autopilot wiring",
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
        max_steps=1,
    )
    autopilot = BankMissionAutopilot(config)
    result = autopilot.drive()
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.step_count == 1
    reality = [
        row for row in autopilot.truth.query("rc7_task", mission_id="M-DRIVE")
        if row.get("node") == "REALITY_RECON"
    ]
    assert len(reality) == 1
    assert reality[0]["state"] == "PASS"
    requirement = [
        row for row in autopilot.truth.query("rc7_task", mission_id="M-DRIVE")
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ][0]
    assert requirement["state"] == "READY"
