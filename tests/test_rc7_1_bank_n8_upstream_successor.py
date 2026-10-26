from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_n5_full_recovery_closure import BankN5FullRecoveryAwarePreparationClosureCoordinator
from rc7_runtime.bank_n8_upstream_successor import BankN8UpstreamSuccessorCoordinator
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND, _state_ref, _write_immutable_json
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-N8-UPSTREAM"
SOURCE = "TASK-EXEC-N8-UPSTREAM"
TARGET = "BANK-TARGET"
TC_ID = "TC-UPSTREAM-1"


def _persist_prepared(truth, state_root: Path, prepared: PreparedAttempt, worker: str = "execution-worker"):
    target, digest = _write_immutable_json(
        state_root,
        Path(MISSION) / prepared.attempt_id / "prepared-attempt.json",
        asdict(prepared),
    )
    evidence = Evidence(
        evidence_id="EVD-PREPARED-" + prepared.attempt_id,
        mission_id=MISSION,
        kind=PREPARED_ATTEMPT_KIND,
        source_ref="runtime://case-runtime/preparation",
        content_ref=_state_ref(state_root, target),
        subject_refs=[SOURCE, worker, prepared.attempt_id, prepared.tc_id, prepared.target_id],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id="RC7.1-N8-UPSTREAM", artifact_version=1)
    return target


def _prepared(attempt_id: str) -> PreparedAttempt:
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id=TC_ID,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=("EVD-PRE",),
        initial_state_bindings={"loan_id": "L-1"},
        input_data_bindings={"amount": 100},
        binding_evidence=("EVD-DATA",),
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


def test_upstream_owner_repair_authorizes_fresh_successor_and_n5_edge(tmp_path: Path):
    state_root = tmp_path / "state"
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-UPSTREAM",
            goal="prove upstream owner repair reaches fresh successor and N5",
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
    source_prepared = _prepared("ATT-1")
    source_path = _persist_prepared(truth, state_root, source_prepared)
    source_bytes = source_path.read_bytes()

    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-UPSTREAM",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-UPSTREAM",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://diagnosis",
        content_ref="evidence://diagnosis/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-UPSTREAM",
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
        gap_id="GAP-SCRIPT-UPSTREAM",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="SCRIPT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="SCRIPT_READINESS",
        description="script repair required",
        subject_refs=["ATT-1", TC_ID],
        evidence_refs=[diagnosis_evidence.evidence_id],
        acceptance_criteria=["owner repair produces real delta then authorize fresh successor"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-UPSTREAM",
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
        diagnosis_id="DIAG-SCRIPT-UPSTREAM",
        source_attempt_id="ATT-1",
        action="REPAIR_SCRIPT",
        mode="UPSTREAM_REPAIR_THEN_RETRY",
        target_node="SCRIPT_READINESS",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="repair script then retry exact case",
    )
    order = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8")).create_work_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence.evidence_id,
        failure_signature_id="FSIG-SCRIPT-UPSTREAM",
    )

    repair_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    repair_task_id = str(repair_rows[0]["task_id"])
    repair_worker = "script-repair-worker"
    repair = control.lease_next(worker_ref=repair_worker, capabilities=("test_automation",))
    assert repair is not None and repair.task_id == repair_task_id
    control.start(repair_task_id, worker_ref=repair_worker)
    delta = Evidence(
        evidence_id="EVD-DELTA-UPSTREAM",
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="runtime://script-repair",
        content_ref="evidence://script/delta",
        subject_refs=[repair_task_id, gap.gap_id],
    )
    repair_artifact = Artifact(
        artifact_id="ART-REPAIR-UPSTREAM",
        mission_id=MISSION,
        artifact_type="OWNER_REPAIR_OUTPUT",
        producer_task_id=repair_task_id,
        content_ref="artifact://script/delta",
        evidence_refs=[delta.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair_task_id,
            worker_ref=repair_worker,
            artifacts=(repair_artifact,),
            evidence=(delta,),
        )
    )
    control.accept_evaluation(
        repair_task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-UPSTREAM",
            mission_id=MISSION,
            node="SCRIPT_READINESS",
            artifact_refs=[repair_artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-n8-owner-repair-independent-gate",
            dimensions={
                "repair_work_order_id": order.work_order_id,
                "repair_before_fingerprint": "script:old",
                "repair_after_fingerprint": "script:new",
                "repair_delta_refs": [delta.evidence_id],
            },
            evidence_refs=[delta.evidence_id],
        ),
    )
    assert control.scheduler.task(SOURCE).state == TaskStatus.READY

    coordinator = BankN8UpstreamSuccessorCoordinator(
        state_root=str(state_root),
        evidence_root=str(tmp_path / "n8"),
    )
    receipt_id = coordinator.authorize_if_ready(
        control,
        source_task_id=SOURCE,
        tc_id=TC_ID,
        target_id=TARGET,
    )
    assert receipt_id
    receipts = truth.query("rc7_evidence", evidence_id=receipt_id)
    assert len(receipts) == 1
    assert receipts[0]["kind"] == N8RecoveryOrchestrator.RECEIPT_TYPE

    source = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert source is not None and source.task_id == SOURCE
    prepared_result = coordinator.materialize_if_authorized(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id=TC_ID,
        target_id=TARGET,
    )
    assert prepared_result is not None
    assert prepared_result["prepared_attempt"]["attempt_id"] == "ATT-2"
    assert prepared_result["source_attempt_id"] == "ATT-1"
    assert prepared_result["authorization_evidence_id"] == receipt_id
    assert source_path.read_bytes() == source_bytes

    edge = BankN5FullRecoveryAwarePreparationClosureCoordinator._n8_direct_edge(
        control,
        execution_task_id=SOURCE,
        tc_id=TC_ID,
        successor_attempt_id="ATT-2",
    )
    assert edge == ("ATT-1", "ATT-2")

    prepared_rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == PREPARED_ATTEMPT_KIND and "ATT-2" in set(row.get("subject_refs") or [])
    ]
    assert len(prepared_rows) == 1
    assert prepared_rows[0]["source_ref"] == BankN8UpstreamSuccessorCoordinator.SUCCESSOR_SOURCE_REF
