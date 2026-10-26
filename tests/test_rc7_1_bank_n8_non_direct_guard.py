from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_n8_successor import BankN8SuccessorCoordinator, BankN8SuccessorError
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
)


MISSION = "MISSION-RC7-1-N8-NON-DIRECT-GUARD"
SOURCE = "TASK-EXEC-N8-NON-DIRECT-GUARD"


def test_non_direct_owner_repair_cannot_fall_back_to_predecessor_attempt(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-NON-DIRECT-GUARD",
            goal="forbid predecessor replay after non-direct owner repair",
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

    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-NON-DIRECT-GUARD",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-NON-DIRECT-GUARD",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://diagnosis",
        content_ref="evidence://diagnosis/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-NON-DIRECT-GUARD",
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
        gap_id="GAP-AUTH-NON-DIRECT-GUARD",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="AUTH_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="RUNTIME",
        description="fresh auth required",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[diagnosis_evidence.evidence_id],
        acceptance_criteria=["repair auth and authorize a fresh successor attempt"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-NON-DIRECT-GUARD",
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
        diagnosis_id="DIAG-AUTH-NON-DIRECT-GUARD",
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
    order = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8")).create_work_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence.evidence_id,
        failure_signature_id="FSIG-AUTH-NON-DIRECT-GUARD",
    )

    repair_rows = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    repair_task_id = str(repair_rows[0]["task_id"])
    worker = "runtime-repair-worker"
    repair = control.lease_next(worker_ref=worker, capabilities=("runtime_recovery",))
    assert repair is not None and repair.task_id == repair_task_id
    control.start(repair_task_id, worker_ref=worker)
    delta = Evidence(
        evidence_id="EVD-DELTA-NON-DIRECT-GUARD",
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="runtime://recovery_execute/foura_auth",
        content_ref="evidence://repair/fresh-auth",
        subject_refs=[repair_task_id, gap.gap_id],
    )
    repair_artifact = Artifact(
        artifact_id="ART-REPAIR-NON-DIRECT-GUARD",
        mission_id=MISSION,
        artifact_type="OWNER_REPAIR_OUTPUT",
        producer_task_id=repair_task_id,
        content_ref="artifact://repair/fresh-auth",
        evidence_refs=[delta.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair_task_id,
            worker_ref=worker,
            artifacts=(repair_artifact,),
            evidence=(delta,),
        )
    )
    control.accept_evaluation(
        repair_task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-NON-DIRECT-GUARD",
            mission_id=MISSION,
            node="RUNTIME",
            artifact_refs=[repair_artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-n8-owner-repair-independent-gate",
            dimensions={
                "repair_work_order_id": order.work_order_id,
                "repair_before_fingerprint": "auth:expired",
                "repair_after_fingerprint": "auth:fresh",
                "repair_delta_refs": [delta.evidence_id],
            },
            evidence_refs=[delta.evidence_id],
        ),
    )

    source = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert source is not None and source.task_id == SOURCE
    with pytest.raises(
        BankN8SuccessorError,
        match="BANK_N8_NON_DIRECT_SUCCESSOR_AUTHORIZATION_REQUIRED",
    ):
        BankN8SuccessorCoordinator(state_root=tmp_path / "state").materialize_direct_successor(
            control,
            source_task_id=SOURCE,
            worker_id="retry-worker",
            tc_id="TC-1",
            target_id="BANK-TARGET",
        )
