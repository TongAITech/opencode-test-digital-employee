from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
)
from rc7_runtime.rc72_field_mission_start import (
    ReleaseBatchFieldMissionLauncher,
    install_rc72_field_mission_start_overlay,
)
from rc7_runtime.rc72_mission_node_dispatch import (
    N1AutonomousDispatchService,
    install_rc72_mission_node_dispatch_overlay,
)
from rc7_runtime.rc72_n1_completion import install_rc72_n1_completion_overlay
from rc7_runtime.rc72_n2_requirement_dispatch import (
    N2RequirementDispatchError,
    N2RequirementDispatchService,
    install_rc72_n2_requirement_dispatch_overlay,
    validate_rc72_n2_requirement_dispatch,
)
from rc7_runtime.rc72_q7_admission import install_rc72_q7_admission_overlay
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "1111111111111111111111111111111111111111"
OTHER_COMMIT = "2222222222222222222222222222222222222222"
RELEASE = "BLOAN-PF1.2.1"
MISSION = "MISSION-BLOAN-PF121"
BATCH = "RB-BLOAN-PF121"
REQUIREMENTS = ["STBB19-320", "STBB19-322"]


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_q7_admission_overlay()
    install_rc72_field_mission_start_overlay()
    install_rc72_mission_node_dispatch_overlay()
    install_rc72_n1_completion_overlay()
    install_rc72_n2_requirement_dispatch_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _start_n1(truth: TruthRuntime) -> dict:
    truth.append_atomic(
        "RC72_RELEASE_BATCH_UPSERTED",
        {
            "release_batch_id": BATCH,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "name": RELEASE,
            "planned_release_time": None,
            "version_ids": [RELEASE],
            "application_ids": ["BLOAN"],
            "requirement_ids": list(REQUIREMENTS),
            "state": "REGISTERED",
            "readiness": "READY",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_Q7_ADMISSION_UPSERTED",
        {
            "admission_id": "Q7ADM-BLOAN-PF121",
            "release_id": RELEASE,
            "mission_id": MISSION,
            "release_batch_id": BATCH,
            "source_commit": COMMIT,
            "status": "ADMITTED",
            "reason": "FIELD_PREREQUISITES_COMPLETE",
            "provenance_id": "PROV-BLOAN-PF121",
            "scope_snapshot_id": "SCOPE-BLOAN-PF121",
            "qualification_receipt_ids": ["QUAL-Q3", "QUAL-Q4", "QUAL-Q5", "QUAL-Q6"],
            "hold_reasons": [],
            "input_digest": "a" * 64,
            "field_verified": False,
            "bank_final": False,
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
        release_batch_id=BATCH
    )
    return N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
        release_batch_id=BATCH
    )


def _complete_n1(truth: TruthRuntime) -> dict:
    dispatch = _start_n1(truth)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref="N1-WORKER",
        capabilities=["reality_recon", "field_evidence"],
    )
    assert leased is not None
    assert leased.task_id == dispatch["workitem_id"]
    control.start(dispatch["workitem_id"], worker_ref="N1-WORKER")

    evidence = Evidence(
        evidence_id="EV-N1-REALITY",
        mission_id=MISSION,
        kind="N1_REALITY_RAW",
        source_ref="dsh://session/session-n1",
        content_ref="file:///tmp/n1-reality.jsonl",
        subject_refs=[dispatch["workitem_id"], dispatch["mission_node_id"]],
        content_hash="sha256:" + "1" * 64,
    )
    artifact = Artifact(
        artifact_id="ART-N1-REALITY",
        mission_id=MISSION,
        artifact_type="N1_REALITY_CANDIDATE",
        producer_task_id=dispatch["workitem_id"],
        content_ref="file:///tmp/n1-reality.jsonl",
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + "1" * 64,
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=dispatch["workitem_id"],
            worker_ref="N1-WORKER",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )

    runtime = RC72StateMachine(truth, release_id=RELEASE)
    delivery = NodeDelivery(
        delivery_id="ND-N1-PASS",
        mission_id=MISSION,
        mission_node_id=dispatch["mission_node_id"],
        node_type=AutonomousMissionNode.N1_REALITY,
        version=1,
        producer_ref="N1-WORKER",
        artifact_refs=[artifact.artifact_id],
        evidence_refs=[evidence.evidence_id],
        created_by_workitems=[dispatch["workitem_id"]],
        known_gaps=[],
        sufficiency_score=1.0,
    )
    runtime.submit_delivery(delivery)
    control.accept_evaluation(
        dispatch["workitem_id"],
        evaluation=Evaluation(
            evaluation_id="EVAL-N1-PASS",
            mission_id=MISSION,
            node="REALITY_RECON",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="N1-INDEPENDENT-EVALUATOR",
            dimensions={"reality": "PASS"},
            evidence_refs=[evidence.evidence_id],
        ),
    )
    gate = NodeGate(
        gate_id="NG-N1-PASS",
        mission_id=MISSION,
        mission_node_id=dispatch["mission_node_id"],
        node_type=AutonomousMissionNode.N1_REALITY,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="rc72-runtime-n1-gate",
        reviewer_session_id="runtime://rc72/n1-gate/v1",
        criteria=["N1_CANONICAL_REALITY"],
        passed=["N1_CANONICAL_REALITY"],
        failed=[],
        evidence_refs=[evidence.evidence_id],
        reason="fixture canonical N1 PASS",
    )
    runtime.apply_gate(gate)
    runtime.forward(
        AutonomousMissionNode.N1_REALITY,
        AutonomousMissionNode.N2_REQUIREMENT,
        source_gate_id=gate.gate_id,
    )
    return {
        "dispatch": dispatch,
        "delivery": delivery,
        "gate": gate,
        "artifact": artifact,
        "evidence": evidence,
    }


def test_n2_dispatch_fans_out_one_governed_workitem_per_requirement(tmp_path: Path):
    truth = _truth(tmp_path)
    n1 = _complete_n1(truth)

    result = N2RequirementDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["node_state"] == "RUNNING"
    assert result["requirement_ids"] == REQUIREMENTS
    assert len(result["workitem_ids"]) == len(REQUIREMENTS)
    assert len(set(result["workitem_ids"])) == len(REQUIREMENTS)
    assert result["source_n1_gate_id"] == n1["gate"].gate_id
    assert result["source_n1_delivery_id"] == n1["delivery"].delivery_id

    receipts = truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH)
    assert len(receipts) == len(REQUIREMENTS)
    assert {row["requirement_id"] for row in receipts} == set(REQUIREMENTS)
    for row in receipts:
        assert row["source_n1_artifact_refs"] == [n1["artifact"].artifact_id]
        assert row["source_n1_evidence_refs"] == [n1["evidence"].evidence_id]
        assert row["required_capabilities"] == ["requirement_reasoning"]
        assert row["status"] == "READY_FOR_ASSIGNMENT"
        task = truth.query("rc7_task", task_id=row["workitem_id"])[0]
        assert task["state"] == "READY"
        assert task["node"] == "REQUIREMENT_ANALYSIS"
        assert task["dependency_task_ids"] == [n1["dispatch"]["workitem_id"]]
        assert task["input_artifact_refs"] == [n1["artifact"].artifact_id]

    n2 = truth.query(
        "rc72_mission_node", mission_id=MISSION,
        node_type=AutonomousMissionNode.N2_REQUIREMENT.value,
    )[0]
    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION,
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS.value,
    )[0]
    assert n2["state"] == "RUNNING"
    assert n3["state"] == "NOT_STARTED"


def test_n2_dispatch_is_idempotent_without_duplicate_workitems(tmp_path: Path):
    truth = _truth(tmp_path)
    _complete_n1(truth)
    service = N2RequirementDispatchService(truth, source_commit=COMMIT)

    first = service.dispatch(release_batch_id=BATCH)
    second = service.dispatch(release_batch_id=BATCH)

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert first["workitem_ids"] == second["workitem_ids"]
    assert first["dispatch_ids"] == second["dispatch_ids"]
    n2_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ]
    assert len(n2_tasks) == len(REQUIREMENTS)


def test_n2_dispatch_rejects_source_commit_drift_without_side_effects(tmp_path: Path):
    truth = _truth(tmp_path)
    _complete_n1(truth)

    with pytest.raises(
        N2RequirementDispatchError,
        match="N1_SOURCE_COMMIT_LINEAGE_MISMATCH",
    ):
        N2RequirementDispatchService(
            truth, source_commit=OTHER_COMMIT
        ).dispatch(release_batch_id=BATCH)

    assert truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH) == []
    assert [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ] == []
    n2 = truth.query(
        "rc72_mission_node", mission_id=MISSION,
        node_type=AutonomousMissionNode.N2_REQUIREMENT.value,
    )[0]
    assert n2["state"] == "READY"


def test_n2_dispatch_requires_n1_gate_forward_before_any_workitem(tmp_path: Path):
    truth = _truth(tmp_path)
    _start_n1(truth)

    with pytest.raises(N2RequirementDispatchError, match="N2_STATE_INVALID"):
        N2RequirementDispatchService(
            truth, source_commit=COMMIT
        ).dispatch(release_batch_id=BATCH)

    assert truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH) == []
    assert [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ] == []


def test_n2_dispatch_validator_rejects_execution_and_field_claims(tmp_path: Path):
    truth = _truth(tmp_path)
    _complete_n1(truth)
    result = N2RequirementDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    receipt = truth.query(
        "rc72_n2_requirement_dispatch", dispatch_id=result["dispatch_ids"][0]
    )[0]

    for field, value in (
        ("worker_instance_id", "FAKE-WORKER"),
        ("dsh_session_id", "session-fake"),
        ("attempt_id", "ATT-FAKE"),
        ("execution_result", "PASS"),
        ("node_pass", True),
        ("q7_pass", True),
        ("field_verified", True),
        ("bank_final", True),
    ):
        invalid = dict(receipt)
        invalid[field] = value
        with pytest.raises(
            Exception,
            match="EXECUTION_CLAIM_FORBIDDEN:%s" % field,
        ):
            validate_rc72_n2_requirement_dispatch(invalid)
