from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import (
    N8RecoveryOrchestrationError,
    N8RecoveryOrchestrator,
    _stable_id,
)
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


MISSION = "MISSION-N8-NON-DIRECT"
SOURCE_TASK = "TASK-EXEC-N8"
EXEC_WORKER = "execution-worker"


def _prepared(attempt_id="ATT-1"):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-N8",
        case_version=1,
        target_id="TARGET-1",
        precondition_evidence=("fresh-foura-auth://ATT-1",),
        initial_state_bindings={"loan_id": "L-1"},
        input_data_bindings={"amount": 100},
        binding_evidence=("data://L-1",),
        cleanup_policy={"mode": "RELEASE"},
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    )


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8",
            goal="prove non-direct recovery is owner repaired and runtime authorized",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one case",
            required_capabilities=["test_execution"],
        )
    )
    return truth, control


def _submit_failure(
    control: ClosedLoopControlPlane,
    *,
    gap_id: str,
    category: str,
    target_node: str,
    attempt_id: str = "ATT-1",
):
    leased = control.lease_next(worker_ref=EXEC_WORKER, capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE_TASK
    control.start(SOURCE_TASK, worker_ref=EXEC_WORKER)
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-" + gap_id,
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/" + attempt_id,
        subject_refs=[SOURCE_TASK, attempt_id, "TC-N8"],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-" + gap_id,
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://execution-diagnosis",
        content_ref="evidence://diagnosis/" + attempt_id,
        subject_refs=[SOURCE_TASK, attempt_id, "TC-N8"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-" + gap_id,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE_TASK,
        content_ref="artifact://execution/" + attempt_id,
        evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE_TASK,
            worker_ref=EXEC_WORKER,
            artifacts=(artifact,),
            evidence=(execution_evidence, diagnosis_evidence),
        )
    )
    gap = Gap(
        gap_id=gap_id,
        mission_id=MISSION,
        source_node="EXECUTION",
        category=category,
        severity=GapSeverity.HIGH,
        target_node=target_node,
        description="evidence-backed non-direct recovery",
        subject_refs=[attempt_id, "TC-N8"],
        evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
        acceptance_criteria=["owner repair produces evidence-backed delta before reexecution"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-" + gap_id,
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={"test_result": "INCONCLUSIVE", "attempt_id": attempt_id},
        gap_refs=[gap_id],
        evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
    )
    control.accept_evaluation(SOURCE_TASK, evaluation=evaluation, gaps=(gap,))
    return diagnosis_evidence.evidence_id


def _repair_task(control: ClosedLoopControlPlane, gap_id: str):
    rows = [
        row
        for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [gap_id]
    ]
    assert len(rows) == 1
    return rows[0]


def _complete_owner_repair(
    control: ClosedLoopControlPlane,
    *,
    work_order_id: str,
    gap_id: str,
    capability: str,
    before: str,
    after: str,
):
    row = _repair_task(control, gap_id)
    repair_task_id = row["task_id"]
    worker = "owner-" + capability
    leased = control.lease_next(worker_ref=worker, capabilities=(capability,))
    assert leased is not None and leased.task_id == repair_task_id
    control.start(repair_task_id, worker_ref=worker)
    evidence = Evidence(
        evidence_id="EVD-DELTA-" + gap_id,
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="owner://repair",
        content_ref="evidence://repair/" + gap_id,
        subject_refs=[repair_task_id, gap_id, before, after],
    )
    artifact = Artifact(
        artifact_id="ART-REPAIR-" + gap_id,
        mission_id=MISSION,
        artifact_type="OWNER_REPAIR_OUTPUT",
        producer_task_id=repair_task_id,
        content_ref="artifact://repair/" + gap_id,
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair_task_id,
            worker_ref=worker,
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    control.accept_evaluation(
        repair_task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-" + gap_id,
            mission_id=MISSION,
            node=row["node"],
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-owner-repair-gate",
            dimensions={
                "repair_work_order_id": work_order_id,
                "repair_before_fingerprint": before,
                "repair_after_fingerprint": after,
                "repair_delta_refs": [evidence.evidence_id],
            },
            evidence_refs=[evidence.evidence_id],
        ),
    )


def _plan(*, action: str, mode: str, target_node: str, reprepare: bool, successor: str = "ATT-2"):
    return RecoveryWorkPlan(
        diagnosis_id="DIAG-N8",
        source_attempt_id="ATT-1",
        action=action,
        mode=mode,
        target_node=target_node,
        retry_allowed=True,
        reprepare_required=reprepare,
        terminal=False,
        successor_attempt_id=successor,
        reason="evidence-backed owner repair",
    )


def test_script_repair_requires_owner_delta_before_successor_authorization(tmp_path: Path):
    truth, control = _control(tmp_path)
    diagnosis_evidence_id = _submit_failure(
        control,
        gap_id="GAP-SCRIPT-1",
        category="SCRIPT_DEFECT",
        target_node="SCRIPT_READINESS",
    )
    plan = _plan(
        action="REPAIR_SCRIPT",
        mode="UPSTREAM_REPAIR_THEN_RETRY",
        target_node="SCRIPT_READINESS",
        reprepare=False,
    )
    orchestrator = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8"))
    order = orchestrator.create_work_order(
        control,
        source_task_id=SOURCE_TASK,
        gap_id="GAP-SCRIPT-1",
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence_id,
        failure_signature_id="FSIG-SCRIPT-1",
    )
    assert truth.query("rc7_artifact", artifact_id=order.artifact_id)[0]["artifact_type_name"] == "N8_REPAIR_WORK_ORDER"

    _complete_owner_repair(
        control,
        work_order_id=order.work_order_id,
        gap_id="GAP-SCRIPT-1",
        capability="test_automation",
        before="script-sha:old",
        after="script-sha:new",
    )
    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.READY
    assert truth.query("rc7_gap", gap_id="GAP-SCRIPT-1")[0]["state"] == "EVIDENCE_PENDING"

    authorization = orchestrator.accept_repair_receipt(
        control,
        work_order=order,
        plan=plan,
        prepared_before=_prepared("ATT-1"),
    )
    assert authorization.prepared.attempt_id == "ATT-2"
    assert authorization.prepared.input_data_bindings == {"amount": 100}
    assert len(truth.query("rc7_evidence", evidence_id=authorization.repair_receipt_evidence_id)) == 1
    N8RecoveryOrchestrator.verify_successor(authorization, authorization.prepared)


def test_same_signature_strategy_without_delta_is_rejected(tmp_path: Path):
    _, control = _control(tmp_path)
    diagnosis_evidence_id = _submit_failure(
        control,
        gap_id="GAP-SCRIPT-NODELTA",
        category="SCRIPT_DEFECT",
        target_node="SCRIPT_READINESS",
    )
    plan = _plan(
        action="REPAIR_SCRIPT",
        mode="UPSTREAM_REPAIR_THEN_RETRY",
        target_node="SCRIPT_READINESS",
        reprepare=False,
    )
    orchestrator = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8"))
    order = orchestrator.create_work_order(
        control,
        source_task_id=SOURCE_TASK,
        gap_id="GAP-SCRIPT-NODELTA",
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence_id,
        failure_signature_id="FSIG-SAME",
    )
    _complete_owner_repair(
        control,
        work_order_id=order.work_order_id,
        gap_id="GAP-SCRIPT-NODELTA",
        capability="test_automation",
        before="script-sha:same",
        after="script-sha:same",
    )
    with pytest.raises(N8RecoveryOrchestrationError, match="SAME_FAILURE_SIGNATURE_NO_DELTA"):
        orchestrator.accept_repair_receipt(
            control,
            work_order=order,
            plan=plan,
            prepared_before=_prepared("ATT-1"),
        )


def test_reprepare_path_requires_durable_successor_prepared_attempt(tmp_path: Path):
    truth, control = _control(tmp_path)
    diagnosis_evidence_id = _submit_failure(
        control,
        gap_id="GAP-AUTH-1",
        category="AUTH_DEFECT",
        target_node="RUNTIME",
    )
    plan = _plan(
        action="REAUTH",
        mode="REPREPARE_THEN_RETRY",
        target_node="RUNTIME",
        reprepare=True,
    )
    orchestrator = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8"))
    order = orchestrator.create_work_order(
        control,
        source_task_id=SOURCE_TASK,
        gap_id="GAP-AUTH-1",
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence_id,
        failure_signature_id="FSIG-AUTH-1",
    )
    _complete_owner_repair(
        control,
        work_order_id=order.work_order_id,
        gap_id="GAP-AUTH-1",
        capability="runtime_recovery",
        before="auth-session:expired",
        after="auth-session:fresh",
    )
    successor = _prepared("ATT-2")
    with pytest.raises(N8RecoveryOrchestrationError, match="N8_SUCCESSOR_PREPARED_ARTIFACT_NOT_UNIQUE"):
        orchestrator.accept_repair_receipt(
            control,
            work_order=order,
            plan=plan,
            prepared_before=_prepared("ATT-1"),
            successor_prepared=successor,
        )

    prep_path = tmp_path / "successor-prepared.json"
    payload = {"prepared": asdict(successor)}
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    prep_path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    prep_evidence = Evidence(
        evidence_id="EVD-PREP-ATT-2",
        mission_id=MISSION,
        kind="RUNTIME_PREPARATION_RECORD",
        source_ref="runtime://preparation",
        content_ref="file://" + str(prep_path),
        subject_refs=[SOURCE_TASK, "ATT-2", "TC-N8"],
        content_hash="sha256:" + digest,
    )
    append_entity(truth, prep_evidence, release_id=control.release_id)
    append_entity(
        truth,
        Artifact(
            artifact_id=_stable_id("ART-PREPARED", MISSION, SOURCE_TASK, "ATT-2"),
            mission_id=MISSION,
            artifact_type="PREPARED_ATTEMPT",
            producer_task_id=SOURCE_TASK,
            content_ref="file://" + str(prep_path),
            evidence_refs=[prep_evidence.evidence_id],
            content_hash="sha256:" + digest,
        ),
        release_id=control.release_id,
    )

    authorization = orchestrator.accept_repair_receipt(
        control,
        work_order=order,
        plan=plan,
        prepared_before=_prepared("ATT-1"),
        successor_prepared=successor,
    )
    assert authorization.prepared.attempt_id == "ATT-2"


@pytest.mark.parametrize(
    "plan",
    [
        RecoveryWorkPlan(
            diagnosis_id="DIAG-N8",
            source_attempt_id="ATT-1",
            action="RETRY_SAME_STEP",
            mode="DIRECT_RETRY",
            target_node="EXECUTION",
            retry_allowed=True,
            reprepare_required=False,
            terminal=False,
            successor_attempt_id="ATT-2",
            reason="transient",
        ),
        RecoveryWorkPlan(
            diagnosis_id="DIAG-N8",
            source_attempt_id="ATT-1",
            action="PRODUCT_DEFECT",
            mode="TERMINAL",
            target_node="DEFECT",
            retry_allowed=False,
            reprepare_required=False,
            terminal=True,
            successor_attempt_id=None,
            reason="product",
        ),
    ],
)
def test_n8_non_direct_orchestrator_cannot_absorb_direct_or_terminal_paths(tmp_path: Path, plan):
    _, control = _control(tmp_path)
    diagnosis_evidence_id = _submit_failure(
        control,
        gap_id="GAP-SCRIPT-REJECT",
        category="SCRIPT_DEFECT",
        target_node="SCRIPT_READINESS",
    )
    with pytest.raises(N8RecoveryOrchestrationError, match="N8_NON_DIRECT_RECOVERY_PLAN_REQUIRED"):
        N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8")).create_work_order(
            control,
            source_task_id=SOURCE_TASK,
            gap_id="GAP-SCRIPT-REJECT",
            plan=plan,
            diagnosis_evidence_id=diagnosis_evidence_id,
            failure_signature_id="FSIG-REJECT",
        )
