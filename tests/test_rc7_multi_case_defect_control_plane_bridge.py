from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.defect_review_conformance import DefectReviewConformanceChecker
from rc7_runtime.execution_fanout_conformance import (
    EXECUTION_TERMINAL_KIND,
    deferred_product_defect_gaps,
)
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-MULTI-CASE-DEFECT-BRIDGE"
RELEASE = "REL-MULTI-CASE-DEFECT-BRIDGE"
EXECUTION_TASK = "TASK-EXEC-MULTI-CASE-BRIDGE"
PASS_ARTIFACT = "ART-EXEC-CASE-PASS"
DEFECT_ARTIFACT = "ART-EXEC-CASE-DEFECT"
PASS_RECEIPT = "EVD-CASE-EXEC-PASS"
DEFECT_RECEIPT = "EVD-CASE-EXEC-DEFECT"
DEFECT_GAP = "GAP-PRODUCT-TC-DEFECT"


def _write_receipt(tmp_path: Path, truth: TruthRuntime, *, receipt_id: str, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path = tmp_path / "case-fanout" / MISSION / (receipt_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    append_entity(
        truth,
        Evidence(
            evidence_id=receipt_id,
            mission_id=MISSION,
            kind=EXECUTION_TERMINAL_KIND,
            source_ref="runtime://case-fanout/execution-terminal",
            content_ref="file://" + str(path.resolve()),
            subject_refs=[EXECUTION_TASK],
            content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )


def test_multi_case_aggregate_hands_deferred_defect_to_real_control_plane(tmp_path: Path) -> None:
    r1 = tmp_path / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove multi-case deferred defect reaches governed defect lifecycle",
        ),
    )

    execution = Task(
        task_id=EXECUTION_TASK,
        mission_id=MISSION,
        node="EXECUTION",
        task_type="PRODUCE",
        objective="aggregate two accepted execution Cases",
        required_capabilities=["test_execution"],
    )
    control.scheduler.register(execution)
    control.scheduler.refresh_ready(MISSION)
    leased = control.lease_next(worker_ref="runtime-execution", capabilities=["test_execution"])
    assert leased is not None and leased.task_id == EXECUTION_TASK
    control.start(EXECUTION_TASK, worker_ref="runtime-execution")

    pass_artifact = Artifact(
        artifact_id=PASS_ARTIFACT,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=EXECUTION_TASK,
        content_ref="runtime://execution/tc-pass",
        evidence_refs=["EVD-RUNNER-PASS"],
    )
    defect_artifact = Artifact(
        artifact_id=DEFECT_ARTIFACT,
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=EXECUTION_TASK,
        content_ref="runtime://execution/tc-defect",
        evidence_refs=["EVD-RUNNER-DEFECT"],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=EXECUTION_TASK,
            worker_ref="runtime-execution",
            artifacts=(pass_artifact, defect_artifact),
            evidence=(
                Evidence(
                    evidence_id="EVD-RUNNER-PASS",
                    mission_id=MISSION,
                    kind="RUNTIME_EXECUTION_RECORD",
                    source_ref="runtime://formal-execution",
                    content_ref="evidence://tc-pass",
                    subject_refs=[EXECUTION_TASK, "TC-PASS"],
                ),
                Evidence(
                    evidence_id="EVD-RUNNER-DEFECT",
                    mission_id=MISSION,
                    kind="RUNTIME_EXECUTION_RECORD",
                    source_ref="runtime://formal-execution",
                    content_ref="evidence://tc-defect",
                    subject_refs=[EXECUTION_TASK, "TC-DEFECT"],
                ),
            ),
        )
    )
    assert control.scheduler.task(EXECUTION_TASK).state == TaskStatus.OUTPUT_PRODUCED

    _write_receipt(
        tmp_path,
        truth,
        receipt_id=PASS_RECEIPT,
        payload={
            "schema_version": "pfc.aitest.rc7.case-execution-terminal.v1",
            "mission_id": MISSION,
            "tc_id": "TC-PASS",
            "outcome": "PASS",
            "execution_task_id": EXECUTION_TASK,
            "execution_artifact_id": PASS_ARTIFACT,
        },
    )
    defect_snapshot = {
        "gap_id": DEFECT_GAP,
        "mission_id": MISSION,
        "source_node": "EXECUTION",
        "category": "PRODUCT_DEFECT",
        "severity": GapSeverity.HIGH.value,
        "target_node": "DEFECT",
        "description": "TC-DEFECT deterministic business mismatch",
        "subject_refs": ["ATTEMPT-DEFECT", "TC-DEFECT"],
        "evidence_refs": ["EVD-RUNNER-DEFECT"],
        "root_gap_id": None,
        "acceptance_criteria": [
            "reproduce TC-DEFECT through governed runtime",
            "independently qualify terminal defect truth",
        ],
    }
    _write_receipt(
        tmp_path,
        truth,
        receipt_id=DEFECT_RECEIPT,
        payload={
            "schema_version": "pfc.aitest.rc7.case-execution-terminal.v1",
            "mission_id": MISSION,
            "tc_id": "TC-DEFECT",
            "outcome": "PRODUCT_DEFECT",
            "execution_task_id": EXECUTION_TASK,
            "execution_artifact_id": DEFECT_ARTIFACT,
            "product_defect_gap": defect_snapshot,
        },
    )

    gaps = deferred_product_defect_gaps(
        truth,
        mission_id=MISSION,
        receipt_ids=(PASS_RECEIPT, DEFECT_RECEIPT),
    )
    assert len(gaps) == 1
    assert gaps[0].gap_id == DEFECT_GAP
    assert gaps[0].evidence_refs[-1] == DEFECT_RECEIPT

    aggregate = Evaluation(
        evaluation_id="EVAL-EXEC-MULTI-CASE-BRIDGE",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[PASS_ARTIFACT, DEFECT_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-runtime-case-execution-fanout-barrier",
        dimensions={
            "case_fanout_contract": "PASS",
            "required_case_count": 2,
            "pass_ready_case_count": 2,
            "product_defect_count": 1,
            "test_result": "FAIL",
            "recovery_action": "PRODUCT_DEFECT",
        },
        gap_refs=[DEFECT_GAP],
        evidence_refs=[PASS_RECEIPT, DEFECT_RECEIPT],
    )
    accepted = control.accept_evaluation(
        EXECUTION_TASK,
        evaluation=aggregate,
        gaps=gaps,
    )
    assert accepted.state == TaskStatus.PASS

    gap_rows = truth.query("rc7_gap", gap_id=DEFECT_GAP)
    assert len(gap_rows) == 1
    assert gap_rows[0]["state"] == "PLANNED"

    reproduction = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "DEFECT_REPRODUCTION"
    ]
    qualification = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "QUALIFY_DEFECT"
    ]
    assert len(reproduction) == 1
    assert len(qualification) == 1

    reproduction_row = reproduction[0]
    qualification_row = qualification[0]
    assert reproduction_row["node"] == "EXECUTION"
    assert reproduction_row["dependency_task_ids"] == [EXECUTION_TASK]
    assert reproduction_row["input_artifact_refs"] == [DEFECT_ARTIFACT]
    assert reproduction_row["gap_refs"] == [DEFECT_GAP]
    assert reproduction_row["state"] == "READY"
    assert PASS_ARTIFACT not in reproduction_row["input_artifact_refs"]

    assert qualification_row["node"] == "DEFECT"
    assert qualification_row["dependency_task_ids"] == [reproduction_row["task_id"]]
    assert qualification_row["input_artifact_refs"] == [DEFECT_ARTIFACT]
    assert qualification_row["gap_refs"] == [DEFECT_GAP]
    assert qualification_row["state"] == "REGISTERED"

    snapshot = control.snapshot()
    assert DEFECT_GAP in snapshot["open_gap_ids"]
    assert reproduction_row["task_id"] in snapshot["ready_task_ids"]

    review = DefectReviewConformanceChecker(truth).check_mission(MISSION)
    assert review.triggered is True
    assert review.status == "FAIL"
    assert "PRODUCT_DEFECT_GAP_NOT_RESOLVED:%s" % DEFECT_GAP in review.violations
    assert "PRODUCT_DEFECT_RECORD_NOT_UNIQUE:%s:0" % DEFECT_GAP in review.violations

    # Process/session recreation must preserve both the exact defect source and
    # the unresolved review gate. R1 alone remains the continuation truth.
    resumed_truth = TruthRuntime(r1)
    resumed = ClosedLoopControlPlane(resumed_truth, RELEASE, MISSION)
    resumed_repro = resumed.scheduler.task(reproduction_row["task_id"])
    resumed_qualify = resumed.scheduler.task(qualification_row["task_id"])
    assert resumed_repro.input_artifact_refs == [DEFECT_ARTIFACT]
    assert resumed_qualify.input_artifact_refs == [DEFECT_ARTIFACT]
    assert resumed.snapshot()["gap_states"][DEFECT_GAP] == "PLANNED"
    resumed_review = DefectReviewConformanceChecker(resumed_truth).check_mission(MISSION)
    assert resumed_review.status == "FAIL"
    assert "PRODUCT_DEFECT_GAP_NOT_RESOLVED:%s" % DEFECT_GAP in resumed_review.violations
