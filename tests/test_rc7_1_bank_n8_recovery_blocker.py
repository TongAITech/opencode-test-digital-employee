from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_n8_recovery import BankN8RecoveryError
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)


MISSION = "MISSION-RC7-1-N8-RECOVERY-BLOCKER"
SOURCE = "TASK-EXEC-N8-RECOVERY-BLOCKER"


def _control_with_ready_direct_repair(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-RECOVERY-BLOCKER",
            goal="prove N8 recovery failures stop at a durable boundary",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one governed case",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(
        worker_ref="execution-worker",
        capabilities=("test_execution",),
    )
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    evidence = Evidence(
        evidence_id="EVD-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://attempt/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://attempt/ATT-1",
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    gap = Gap(
        gap_id="GAP-DIRECT-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="direct retry requires governed N8 authorization",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[evidence.evidence_id],
        acceptance_criteria=["authorize a fresh successor attempt"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={"attempt_id": "ATT-1", "recovery_action": "RETRY_SAME_STEP"},
        gap_refs=[gap.gap_id],
        evidence_refs=[evidence.evidence_id],
    )
    control.accept_evaluation(SOURCE, evaluation=evaluation, gaps=(gap,))
    repair_rows = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and row.get("node") == "EXECUTION"
        and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    return truth, control, gap, control.scheduler.task(str(repair_rows[0]["task_id"]))


def test_direct_n8_repair_failure_becomes_durable_block_not_driver_exception(tmp_path: Path):
    truth, control, gap, repair_task = _control_with_ready_direct_repair(tmp_path)

    class _FailingN8:
        @staticmethod
        def handle_execution_repair(control, task):
            raise BankN8RecoveryError("BROKEN_DIRECT_REPAIR_AUTHORIZATION")

    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.n8_recovery = _FailingN8()
    autopilot.evidence_root = tmp_path / "evidence"

    # This must return at a durable R1 boundary. Runtime recovery faults are not
    # allowed to escape into MissionAutonomousDriver and terminate the session.
    autopilot.run(control, repair_task)

    assert control.scheduler.task(repair_task.task_id).state == TaskStatus.BLOCKED
    assert control.scheduler.task(SOURCE).state == TaskStatus.REPAIR_REQUIRED
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "BLOCKED"
    assert truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "BLOCKED"

    blockers = [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "N8_RECOVERY_BLOCKER"
    ]
    assert len(blockers) == 1
    blocker = blockers[0]
    assert repair_task.task_id in set(blocker.get("subject_refs") or [])
    assert gap.gap_id in set(blocker.get("subject_refs") or [])
    assert "TC-1" in set(blocker.get("subject_refs") or [])
    assert str(blocker.get("content_ref") or "").startswith("file://")
    payload = json.loads(
        Path(str(blocker["content_ref"])[len("file://"):]).read_text(encoding="utf-8")
    )
    assert payload["phase"] == "DIRECT_REPAIR"
    assert payload["reason"] == "BROKEN_DIRECT_REPAIR_AUTHORIZATION"
    assert payload["business_action_executed"] is False
