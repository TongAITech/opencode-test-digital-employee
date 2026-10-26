from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_n8_recovery import BankN8RecoveryCoordinator
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
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


MISSION = "MISSION-RC7-1-BANK-N8"
SOURCE = "TASK-EXEC-N8-BANK"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-BANK",
            goal="prove bank N8 production retry gate",
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
    return truth, control


def _make_source_repair_required(control: ClosedLoopControlPlane):
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    evidence = Evidence(
        evidence_id="EVD-EXEC-N8-BANK",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://attempt/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-N8-BANK",
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
        gap_id="GAP-TRANSIENT-N8-BANK",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="transient failure requires controlled successor attempt",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[evidence.evidence_id],
        acceptance_criteria=["authorize a fresh successor attempt without executing business work in the repair task"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-N8-BANK",
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
        row for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and row.get("node") == "EXECUTION"
        and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    return gap, control.scheduler.task(repair_rows[0]["task_id"])


def test_bank_execution_repair_is_n8_authorization_not_business_execution():
    calls = []

    class _N8:
        def handle_execution_repair(self, control, task):
            calls.append((control, task.task_id))
            return "ATT-2"

    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.n8_recovery = _N8()
    control = object()
    task = SimpleNamespace(task_id="TASK-REPAIR", node="EXECUTION", task_type="REPAIR")

    # No business execution collaborators are installed on this object. If run()
    # falls through into bundle resolution / activation / runner execution, this
    # test fails immediately with AttributeError.
    autopilot.run(control, task)

    assert calls == [(control, "TASK-REPAIR")]


def test_direct_retry_repair_produces_authorization_receipt_without_business_action(tmp_path: Path):
    truth, control = _control(tmp_path)
    gap, repair_task = _make_source_repair_required(control)
    coordinator = BankN8RecoveryCoordinator(evidence_root=str(tmp_path / "evidence"))
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-ATT-1",
        source_attempt_id="ATT-1",
        action="RETRY_SAME_STEP",
        mode="DIRECT_RETRY",
        target_node="EXECUTION",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="runtime-classified transient failure",
    )
    order = coordinator._create_direct_retry_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id="EVD-DIAG-ATT-1",
        failure_signature_id="FSIG-ATT-1",
    )

    successor = coordinator.handle_execution_repair(control, repair_task)

    assert successor == "ATT-2"
    assert control.scheduler.task(repair_task.task_id).state == TaskStatus.PASS
    assert control.scheduler.task(SOURCE).state == TaskStatus.READY
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "EVIDENCE_PENDING"

    receipts = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == coordinator.DIRECT_RECEIPT_TYPE
        and order.order_id in set(row.get("subject_refs") or [])
    ]
    assert len(receipts) == 1
    ref = receipts[0]["content_ref"]
    assert ref.startswith("file://")
    payload = json.loads(Path(ref[len("file://"):]).read_text(encoding="utf-8"))
    assert payload["source_attempt_id"] == "ATT-1"
    assert payload["successor_attempt_id"] == "ATT-2"
    assert payload["business_action_executed"] is False
