from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_n8_recovery import BankN8RecoveryCoordinator, _stable_id
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
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-N8-BUDGET"
SOURCE = "TASK-EXEC-N8-BUDGET"
ATTEMPT = "ATT-BUDGET-1"
TC_ID = "TC-BUDGET-1"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-BUDGET",
            goal="prove N8 retry budget becomes a durable blocked boundary",
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


def _source_repair_required(
    control: ClosedLoopControlPlane,
    *,
    gap_id: str,
    category: str,
    target_node: str,
):
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-" + gap_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/" + ATTEMPT,
        subject_refs=[SOURCE, ATTEMPT, TC_ID],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-" + gap_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://execution/" + ATTEMPT,
        evidence_refs=[execution_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(artifact,),
            evidence=(execution_evidence,),
        )
    )
    gap = Gap(
        gap_id=gap_id,
        mission_id=MISSION,
        source_node="EXECUTION",
        category=category,
        severity=GapSeverity.HIGH,
        target_node=target_node,
        description="repeat failure exceeded governed retry budget",
        subject_refs=[ATTEMPT, TC_ID],
        evidence_refs=[execution_evidence.evidence_id],
        acceptance_criteria=["do not retry indefinitely; stop at a durable blocked boundary"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-" + gap_id,
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="runtime-execution-gate",
            dimensions={"attempt_id": ATTEMPT, "test_result": "INCONCLUSIVE"},
            gap_refs=[gap.gap_id],
            evidence_refs=[execution_evidence.evidence_id],
        ),
        gaps=(gap,),
    )
    repair_rows = [
        row for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and row.get("node") == target_node
        and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    return gap, control.scheduler.task(str(repair_rows[0]["task_id"]))


def _diagnosis(
    tmp_path: Path,
    truth: TruthRuntime,
    *,
    plan: RecoveryWorkPlan,
    failure_signature_id: str,
    gap_id: str,
) -> Evidence:
    payload = {
        "diagnosis": {"failure_signature": {"signature_id": failure_signature_id}},
        "recovery": {"attempt_id": ATTEMPT, "diagnosis_id": plan.diagnosis_id},
        "work_plan": asdict(plan),
    }
    body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = tmp_path / (gap_id + "-diagnosis.json")
    path.write_bytes(body)
    evidence = Evidence(
        evidence_id="EVD-DIAG-" + gap_id,
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://execution-diagnosis",
        content_ref="file://" + str(path.resolve()),
        subject_refs=[SOURCE, ATTEMPT, TC_ID],
        content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
    )
    append_entity(truth, evidence, release_id="RC7.1-N8-BUDGET", artifact_version=1)
    return evidence


def _result(gap: Gap, diagnosis: Evidence):
    return SimpleNamespace(
        execution_record=SimpleNamespace(attempt_id=ATTEMPT),
        evidence_ids=(diagnosis.evidence_id,),
        loop_result=SimpleNamespace(
            evaluation=SimpleNamespace(result=EvaluationResult.REPAIR_REQUIRED),
            gaps=(gap,),
        ),
    )


def _seed_receipts(
    truth: TruthRuntime,
    *,
    kind: str,
    signature: str,
    strategy_key: str,
    count: int,
) -> None:
    for index in range(count):
        append_entity(
            truth,
            Evidence(
                evidence_id="EVD-PRIOR-%s-%d" % (kind, index),
                mission_id=MISSION,
                kind=kind,
                source_ref="runtime://prior-recovery",
                content_ref="evidence://prior/%d" % index,
                subject_refs=[signature, strategy_key, "DELTA-%d" % index],
            ),
            release_id="RC7.1-N8-BUDGET",
            artifact_version=1,
        )


def _assert_durable_budget_block(
    truth: TruthRuntime,
    control: ClosedLoopControlPlane,
    *,
    evidence_id: str,
    gap_id: str,
    repair_task_id: str,
    expected_reason: str,
):
    evidence_rows = truth.query("rc7_evidence", evidence_id=evidence_id)
    assert len(evidence_rows) == 1
    evidence = evidence_rows[0]
    assert evidence["kind"] == BankN8RecoveryCoordinator.BUDGET_BLOCK_TYPE
    ref = str(evidence["content_ref"])
    assert ref.startswith("file://")
    payload = json.loads(Path(ref[len("file://"):]).read_text(encoding="utf-8"))
    assert payload["reason"] == expected_reason
    assert payload["business_action_executed"] is False
    assert payload["source_task_id"] == SOURCE
    assert payload["repair_task_id"] == repair_task_id
    assert payload["gap_id"] == gap_id

    assert control.scheduler.task(SOURCE).state == TaskStatus.REPAIR_REQUIRED
    assert control.scheduler.task(repair_task_id).state == TaskStatus.BLOCKED
    assert truth.query("rc7_gap", gap_id=gap_id)[0]["state"] == "BLOCKED"
    assert truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "BLOCKED"
    assert evidence_id in set(truth.query("rc7_gap", gap_id=gap_id)[0].get("evidence_refs") or [])


def test_direct_retry_budget_exhaustion_becomes_durable_blocked_boundary(tmp_path: Path):
    truth, control = _control(tmp_path)
    gap, repair = _source_repair_required(
        control,
        gap_id="GAP-DIRECT-BUDGET",
        category="TRANSIENT_FAILURE",
        target_node="EXECUTION",
    )
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-DIRECT-BUDGET",
        source_attempt_id=ATTEMPT,
        action="RETRY_SAME_STEP",
        mode="DIRECT_RETRY",
        target_node="EXECUTION",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-BUDGET-2",
        reason="same transient failure repeated",
    )
    signature = "FSIG-DIRECT-BUDGET"
    diagnosis = _diagnosis(tmp_path, truth, plan=plan, failure_signature_id=signature, gap_id=gap.gap_id)
    coordinator = BankN8RecoveryCoordinator(
        evidence_root=str(tmp_path / "evidence"),
        max_same_signature_direct_retries=1,
    )
    strategy = _stable_id("N8-DIRECT-STRATEGY", plan.action, plan.mode, plan.target_node)
    _seed_receipts(
        truth,
        kind=coordinator.DIRECT_RECEIPT_TYPE,
        signature=signature,
        strategy_key=strategy,
        count=1,
    )

    evidence_id = coordinator.capture_after_execution(
        control,
        source_task_id=SOURCE,
        result=_result(gap, diagnosis),
    )

    _assert_durable_budget_block(
        truth,
        control,
        evidence_id=evidence_id,
        gap_id=gap.gap_id,
        repair_task_id=repair.task_id,
        expected_reason="BANK_N8_DIRECT_RETRY_BUDGET_EXHAUSTED",
    )
    assert not [
        row for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == coordinator.DIRECT_ORDER_TYPE
    ]


def test_non_direct_same_strategy_budget_exhaustion_becomes_durable_blocked_boundary(tmp_path: Path):
    truth, control = _control(tmp_path)
    gap, repair = _source_repair_required(
        control,
        gap_id="GAP-SCRIPT-BUDGET",
        category="SCRIPT_DEFECT",
        target_node="SCRIPT_READINESS",
    )
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-SCRIPT-BUDGET",
        source_attempt_id=ATTEMPT,
        action="REPAIR_SCRIPT",
        mode="UPSTREAM_REPAIR_THEN_RETRY",
        target_node="SCRIPT_READINESS",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-BUDGET-2",
        reason="same script repair strategy repeated",
    )
    signature = "FSIG-SCRIPT-BUDGET"
    diagnosis = _diagnosis(tmp_path, truth, plan=plan, failure_signature_id=signature, gap_id=gap.gap_id)
    coordinator = BankN8RecoveryCoordinator(evidence_root=str(tmp_path / "evidence"))
    strategy = _stable_id("RECOVERY-STRATEGY", plan.action, plan.mode, plan.target_node)
    _seed_receipts(
        truth,
        kind=N8RecoveryOrchestrator.RECEIPT_TYPE,
        signature=signature,
        strategy_key=strategy,
        count=coordinator.orchestrator.max_same_strategy_repairs,
    )

    evidence_id = coordinator.capture_after_execution(
        control,
        source_task_id=SOURCE,
        result=_result(gap, diagnosis),
    )

    _assert_durable_budget_block(
        truth,
        control,
        evidence_id=evidence_id,
        gap_id=gap.gap_id,
        repair_task_id=repair.task_id,
        expected_reason="SAME_FAILURE_SIGNATURE_STRATEGY_BUDGET_EXHAUSTED",
    )
    assert not [
        row for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == N8RecoveryOrchestrator.WORK_ORDER_TYPE
    ]
