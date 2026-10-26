from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_autonomous_preparation_closure import BankAutonomousPreparationClosureError
from rc7_runtime.bank_n5_recovery_closure import BankN5RecoveryAwarePreparationClosureCoordinator
from rc7_runtime.bank_n8_recovery import BankN8RecoveryCoordinator
from rc7_runtime.bank_n8_successor import BankN8SuccessorCoordinator
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
from rc7_runtime.truth_overlay import append_entity
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND, _state_ref, _write_immutable_json


MISSION = "MISSION-RC7-1-N5-RECOVERY"
SOURCE = "TASK-EXEC-N5-RECOVERY"
TARGET = "BANK-TARGET"


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7.1-N5-RECOVERY", goal="select current N8 successor preparation"),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute current recovery attempt",
            required_capabilities=["test_execution"],
        )
    )
    return truth, control


def _prepared_evidence(truth, state_root: Path, attempt_id: str, *, source_ref: str, extra_refs=()):
    payload = {
        "status": "PREPARED",
        "attempt_id": attempt_id,
        "tc_id": "TC-1",
        "case_version": 1,
        "target_id": TARGET,
        "precondition_evidence": [],
        "initial_state_bindings": {},
        "input_data_bindings": {"amount": 100},
        "binding_evidence": [],
        "cleanup_policy": {"mode": "NONE"},
        "oracle_snapshot": {"type": "API", "expected": "OK"},
    }
    path, digest = _write_immutable_json(
        state_root,
        Path(MISSION) / attempt_id / "prepared-attempt.json",
        payload,
    )
    evidence = Evidence(
        evidence_id="EVD-PREP-%s" % attempt_id,
        mission_id=MISSION,
        kind=PREPARED_ATTEMPT_KIND,
        source_ref=source_ref,
        content_ref=_state_ref(state_root, path),
        subject_refs=[SOURCE, "worker", attempt_id, "TC-1", TARGET] + list(extra_refs),
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id="RC7.1-N5-RECOVERY")
    return evidence


def _repair_ready(control):
    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    ev = Evidence(
        evidence_id="EVD-EXEC-FAIL",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    art = Artifact(
        artifact_id="ART-EXEC-FAIL",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://ATT-1",
        evidence_refs=[ev.evidence_id],
    )
    control.submit_worker_output(WorkerOutput(task_id=SOURCE, worker_ref="execution-worker", artifacts=(art,), evidence=(ev,)))
    gap = Gap(
        gap_id="GAP-N5-RETRY",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="controlled retry",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[ev.evidence_id],
        acceptance_criteria=["fresh successor attempt"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-FAIL",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[art.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={"attempt_id": "ATT-1"},
        gap_refs=[gap.gap_id],
        evidence_refs=[ev.evidence_id],
    )
    control.accept_evaluation(SOURCE, evaluation=evaluation, gaps=(gap,))
    repair = [
        row for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "EXECUTION" and row.get("task_type") == "REPAIR"
    ]
    assert len(repair) == 1
    return gap, control.scheduler.task(repair[0]["task_id"])


def _authorize_and_materialize(tmp_path: Path, truth, control):
    state_root = tmp_path / "state"
    _prepared_evidence(truth, state_root, "ATT-1", source_ref="runtime://case-runtime/preparation")
    gap, repair = _repair_ready(control)
    n8 = BankN8RecoveryCoordinator(evidence_root=str(tmp_path / "evidence"))
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-1",
        source_attempt_id="ATT-1",
        action="RETRY_SAME_STEP",
        mode="DIRECT_RETRY",
        target_node="EXECUTION",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="transient",
    )
    n8._create_direct_retry_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id="EVD-DIAG-1",
        failure_signature_id="FSIG-1",
    )
    assert n8.handle_execution_repair(control, repair) == "ATT-2"
    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    result = BankN8SuccessorCoordinator(state_root=state_root).materialize_direct_successor(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id="TC-1",
        target_id=TARGET,
    )
    assert result is not None and result["prepared_attempt"]["attempt_id"] == "ATT-2"
    return result


def test_n5_selects_only_n8_authorized_successor_as_current(tmp_path: Path):
    truth, control = _setup(tmp_path)
    _authorize_and_materialize(tmp_path, truth, control)
    coordinator = BankN5RecoveryAwarePreparationClosureCoordinator(
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "n5-evidence"),
        target_id=TARGET,
    )
    first = ("ART-FINAL-1", "EVD-FINAL-1", {"attempt_id": "ATT-1", "tc_id": "TC-1"})
    second = ("ART-FINAL-2", "EVD-FINAL-2", {"attempt_id": "ATT-2", "tc_id": "TC-1"})

    selected = coordinator._select_current_finalization(
        control,
        execution_task_id=SOURCE,
        tc_id="TC-1",
        candidates=[first, second],
    )

    assert selected is second


def test_n5_rejects_duplicate_finalizations_without_complete_n8_chain(tmp_path: Path):
    truth, control = _setup(tmp_path)
    state_root = tmp_path / "state"
    _prepared_evidence(truth, state_root, "ATT-1", source_ref="runtime://case-runtime/preparation")
    _prepared_evidence(truth, state_root, "ATT-ROGUE", source_ref="runtime://case-runtime/preparation")
    coordinator = BankN5RecoveryAwarePreparationClosureCoordinator(
        state_root=str(state_root),
        evidence_root=str(tmp_path / "n5-evidence"),
        target_id=TARGET,
    )
    first = ("ART-FINAL-1", "EVD-FINAL-1", {"attempt_id": "ATT-1", "tc_id": "TC-1"})
    rogue = ("ART-FINAL-X", "EVD-FINAL-X", {"attempt_id": "ATT-ROGUE", "tc_id": "TC-1"})

    with pytest.raises(
        BankAutonomousPreparationClosureError,
        match="BANK_N5_FINALIZATION_DUPLICATE_TC_WITHOUT_COMPLETE_N8_CHAIN",
    ):
        coordinator._select_current_finalization(
            control,
            execution_task_id=SOURCE,
            tc_id="TC-1",
            candidates=[first, rogue],
        )
