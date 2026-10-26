from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_n8_dsh_bridge import BankN8AwareDshTaskWorkerBridge
from rc7_runtime.bank_n8_owner_repair_evaluator import (
    BankN8OwnerRepairEvaluationError,
    BankN8OwnerRepairEvaluator,
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


MISSION = "MISSION-RC7-1-N8-OWNER"
SOURCE = "TASK-EXEC-N8-OWNER"


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-OWNER",
            goal="prove independent N8 owner repair",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute governed case",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-N8-OWNER",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-N8-OWNER",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://diagnosis",
        content_ref="evidence://diagnosis/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-N8-OWNER",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://execution/ATT-1",
        evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(execution_artifact,),
            evidence=(execution_evidence, diagnosis_evidence),
        )
    )
    gap = Gap(
        gap_id="GAP-AUTH-N8-OWNER",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="AUTH_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="RUNTIME",
        description="fresh runtime authentication is required",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[diagnosis_evidence.evidence_id],
        acceptance_criteria=["restore fresh authentication with durable repair delta evidence"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-N8-OWNER",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[execution_artifact.artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="runtime-execution-gate",
            dimensions={"attempt_id": "ATT-1"},
            gap_refs=[gap.gap_id],
            evidence_refs=[diagnosis_evidence.evidence_id],
        ),
        gaps=(gap,),
    )
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-AUTH-1",
        source_attempt_id="ATT-1",
        action="REAUTH",
        mode="REPREPARE_THEN_RETRY",
        target_node="RUNTIME",
        retry_allowed=True,
        reprepare_required=True,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="fresh auth required",
    )
    orchestrator = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8"))
    order = orchestrator.create_work_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence.evidence_id,
        failure_signature_id="FSIG-AUTH-1",
    )
    repair_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "RUNTIME" and row.get("task_type") == "REPAIR"
    ]
    assert len(repair_rows) == 1
    return truth, control, order, control.scheduler.task(repair_rows[0]["task_id"])


def _candidate(
    tmp_path: Path,
    control: ClosedLoopControlPlane,
    repair_task: Task,
    *,
    work_order_id: str,
    before: str = "auth:expired",
    after: str = "auth:fresh",
    delta_alias: str = "file://repair/fresh-auth.json",
    semantic_alias: str | None = None,
):
    worker = "runtime-repair-worker"
    leased = control.lease_next(worker_ref=worker, capabilities=("runtime_recovery",))
    assert leased is not None and leased.task_id == repair_task.task_id
    control.start(repair_task.task_id, worker_ref=worker)
    delta_evidence = Evidence(
        evidence_id="EVD-RUNTIME-REPAIR-DELTA",
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="runtime://recovery_execute/foura_auth",
        content_ref=delta_alias,
        subject_refs=[repair_task.task_id, "GAP-AUTH-N8-OWNER"],
    )
    artifact_id = "ART-RUNTIME-REPAIR-CANDIDATE"
    semantic = {
        "repair_work_order_id": work_order_id,
        "repair_before_fingerprint": before,
        "repair_after_fingerprint": after,
        "repair_delta_evidence_refs": [semantic_alias or delta_alias],
    }
    envelope = {
        "task_id": repair_task.task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "RUNTIME_OUTPUT",
            "content_ref": "worker://runtime-repair",
            "parent_refs": [],
            "evidence_refs": [delta_alias],
        },
        "semantic_payload": semantic,
        "evidence": [
            {
                "kind": "REPAIR_DELTA_EVIDENCE",
                "source_ref": delta_evidence.source_ref,
                "content_ref": delta_alias,
                "subject_refs": list(delta_evidence.subject_refs),
            }
        ],
    }
    candidate_path = tmp_path / (repair_task.task_id + "-candidate.json")
    body = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    candidate_path.write_bytes(body)
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="RUNTIME_OUTPUT",
        producer_task_id=repair_task.task_id,
        content_ref="file://" + str(candidate_path),
        evidence_refs=[delta_evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair_task.task_id,
            worker_ref=worker,
            artifacts=(artifact,),
            evidence=(delta_evidence,),
        )
    )
    return artifact


def test_owner_repair_candidate_is_independently_accepted_only_with_real_delta(tmp_path: Path):
    truth, control, order, repair = _setup(tmp_path)
    artifact = _candidate(
        tmp_path,
        control,
        repair,
        work_order_id=order.work_order_id,
    )

    evaluation = BankN8OwnerRepairEvaluator().evaluate_and_apply(
        control,
        repair.task_id,
        artifact.artifact_id,
    )

    assert evaluation.result == EvaluationResult.PASS
    assert evaluation.evaluator_ref == BankN8OwnerRepairEvaluator.EVALUATOR_REF
    assert evaluation.dimensions["repair_work_order_id"] == order.work_order_id
    assert evaluation.dimensions["repair_before_fingerprint"] == "auth:expired"
    assert evaluation.dimensions["repair_after_fingerprint"] == "auth:fresh"
    assert evaluation.dimensions["repair_delta_refs"] == ["EVD-RUNTIME-REPAIR-DELTA"]
    assert control.scheduler.task(repair.task_id).state == TaskStatus.PASS
    assert control.scheduler.task(SOURCE).state == TaskStatus.READY
    assert truth.query("rc7_gap", gap_id="GAP-AUTH-N8-OWNER")[0]["state"] == "EVIDENCE_PENDING"


def test_owner_repair_rejects_same_before_after_without_self_pass(tmp_path: Path):
    _truth, control, order, repair = _setup(tmp_path)
    artifact = _candidate(
        tmp_path,
        control,
        repair,
        work_order_id=order.work_order_id,
        before="auth:same",
        after="auth:same",
    )

    with pytest.raises(BankN8OwnerRepairEvaluationError, match="SAME_FAILURE_SIGNATURE_NO_DELTA"):
        BankN8OwnerRepairEvaluator().evaluate_and_apply(
            control,
            repair.task_id,
            artifact.artifact_id,
        )
    assert control.scheduler.task(repair.task_id).state == TaskStatus.OUTPUT_PRODUCED
    assert control.scheduler.task(SOURCE).state == TaskStatus.REPAIR_REQUIRED


def test_owner_repair_rejects_delta_alias_not_bound_to_candidate_evidence(tmp_path: Path):
    _truth, control, order, repair = _setup(tmp_path)
    artifact = _candidate(
        tmp_path,
        control,
        repair,
        work_order_id=order.work_order_id,
        semantic_alias="file://invented/not-returned.json",
    )

    with pytest.raises(
        BankN8OwnerRepairEvaluationError,
        match="N8_OWNER_REPAIR_DELTA_EVIDENCE_NOT_DURABLE",
    ):
        BankN8OwnerRepairEvaluator().evaluate_and_apply(
            control,
            repair.task_id,
            artifact.artifact_id,
        )
    assert control.scheduler.task(repair.task_id).state == TaskStatus.OUTPUT_PRODUCED


def test_n8_dsh_bridge_injects_exact_owner_repair_handoff(tmp_path: Path):
    _truth, control, order, repair = _setup(tmp_path)
    bridge = object.__new__(BankN8AwareDshTaskWorkerBridge)
    bridge.control = control
    assignment = SimpleNamespace(scope="task:" + repair.task_id, allowed_tools=())

    prompt = bridge.compile_prompt(repair, assignment)

    assert "N8_OWNER_REPAIR_HANDOFF_CONTRACT=" in prompt
    assert order.work_order_id in prompt
    assert '"successor_attempt_id": "ATT-2"' in prompt
    assert "repair_before_fingerprint" in prompt
    assert "repair_after_fingerprint" in prompt
    assert "repair_delta_evidence_refs" in prompt
    assert "REPAIR_DELTA_EVIDENCE" in prompt
