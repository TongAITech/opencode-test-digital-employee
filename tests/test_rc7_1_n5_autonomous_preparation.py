from __future__ import annotations

import hashlib
import json
import time

import pytest

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_preparation_node import (
    AutonomousPreparationNodeError,
    AutonomousPreparationNodeService,
    WaveCNodeAdoptionControl,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Evidence, Mission, Task, TaskStatus
from rc7_runtime.preparation_control import RuntimePreparedAttempt
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-WAVE-C-N5"
MISSION = "MISSION-RC7-1-N5"
RUN = "RUN-RC7-1-N5"
EXEC_TASK = "TASK-EXEC-N5-001"
ATTEMPT = "ATTEMPT-N5-001"
TARGET = "BANK-PFC-UAT"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def _case():
    return {
        "status": "FROZEN",
        "tc_id": "TC-N5-001",
        "case_version": 1,
        "layer": "L4",
        "preconditions": [
            {"id": "PRE-AUTH", "type": "AUTH", "requirement": "fresh 4A login"},
            {"id": "PRE-STATE", "type": "BUSINESS_STATE", "requirement": "loan is editable"},
        ],
        "test_data": {
            "initial_state": [
                {"id": "loan", "selectors": {"status": "DRAFT"}, "allowed_strategies": ["REUSE_EXISTING"]},
            ],
            "input_data": [],
            "cleanup_policy": {"mode": "RESTORE"},
        },
        "oracle": {"type": "BUSINESS_STATE", "expected": "SAVED"},
    }


def _setup(tmp_path, *, auth_created_at=None):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="N5 autonomous preparation"), release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=EXEC_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="RUNTIME",
            objective="execute frozen case",
            state=TaskStatus.READY,
        ),
        release_id=RELEASE,
    )
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    case = _case()
    case_sha = hashlib.sha256(_canonical(case)).hexdigest()

    auth = Evidence(
        evidence_id="EVD-PREP-AUTH",
        mission_id=MISSION,
        kind="PRECONDITION_EVIDENCE",
        source_ref="runtime://preparation",
        content_ref="runtime://foura-auth/session-fresh",
        subject_refs=[EXEC_TASK, ATTEMPT, "TC-N5-001"],
        created_at=int(time.time()) if auth_created_at is None else int(auth_created_at),
    )
    state = Evidence(
        evidence_id="EVD-PREP-STATE",
        mission_id=MISSION,
        kind="PRECONDITION_EVIDENCE",
        source_ref="runtime://preparation",
        content_ref="runtime://business-state/verified",
        subject_refs=[EXEC_TASK, ATTEMPT, "TC-N5-001"],
    )
    binding = Evidence(
        evidence_id="EVD-PREP-BINDING",
        mission_id=MISSION,
        kind="PREPARATION_BINDING_EVIDENCE",
        source_ref="runtime://preparation",
        content_ref="runtime://data/loan-1001/verified",
        subject_refs=[EXEC_TASK, ATTEMPT, "TC-N5-001"],
    )
    for item in (auth, state, binding):
        append_entity(truth, item, release_id=RELEASE)

    prepared_body = {
        "mission_id": MISSION,
        "task_id": EXEC_TASK,
        "attempt_id": ATTEMPT,
        "target_id": TARGET,
        "case_sha256": case_sha,
    }
    prepared_bytes = _canonical(prepared_body)
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_bytes(prepared_bytes)
    prepared_hash = "sha256:" + hashlib.sha256(prepared_bytes).hexdigest()
    prepared_artifact_id = "ART-PREPARED-N5"
    append_entity(
        truth,
        Artifact(
            artifact_id=prepared_artifact_id,
            mission_id=MISSION,
            artifact_type="PREPARED_ATTEMPT",
            producer_task_id=EXEC_TASK,
            content_ref="file://" + str(prepared_path),
            evidence_refs=[auth.evidence_id, state.evidence_id, binding.evidence_id],
            content_hash=prepared_hash,
        ),
        release_id=RELEASE,
    )
    prepared = RuntimePreparedAttempt(
        prepared=PreparedAttempt(
            status="PREPARED",
            attempt_id=ATTEMPT,
            tc_id="TC-N5-001",
            case_version=1,
            target_id=TARGET,
            precondition_evidence=(auth.content_ref, state.content_ref),
            initial_state_bindings={"loan": {"loan_id": "1001", "status": "DRAFT"}},
            input_data_bindings={},
            binding_evidence=(binding.content_ref,),
            cleanup_policy={"mode": "RESTORE"},
            oracle_snapshot={"type": "BUSINESS_STATE", "expected": "SAVED"},
        ),
        artifact_id=prepared_artifact_id,
        evidence_ids=(auth.evidence_id, state.evidence_id, binding.evidence_id),
        content_ref="file://" + str(prepared_path),
        content_hash=prepared_hash,
        case_sha256=case_sha,
    )
    return truth, control, case, prepared


def _prepare_ready(service, control, case, prepared, *, freshness_time=None):
    batch = service.create_batch_plan(
        control,
        run_id=RUN,
        target_id=TARGET,
        cases=[case],
        producer_task_ids=[EXEC_TASK],
    )
    reservation = service.reserve_prepared_bindings(
        control,
        execution_task_id=EXEC_TASK,
        prepared=prepared,
    )
    freshness = service.record_freshness_check(
        control,
        execution_task_id=EXEC_TASK,
        prepared=prepared,
        reservation=reservation,
        raw_check_ref="runtime://data/freshness/loan-1001",
        verified_at=freshness_time,
    )
    return batch, reservation, freshness


def test_n5_batch_is_not_execution_proof_and_per_case_finalization_is_director_gated(tmp_path) -> None:
    truth, control, case, prepared = _setup(tmp_path)
    service = AutonomousPreparationNodeService(evidence_root=str(tmp_path / "evidence"), max_freshness_seconds=300)
    batch, reservation, freshness = _prepare_ready(service, control, case, prepared)

    batch_row = truth.query("rc7_artifact", artifact_id=batch.artifact_id)[0]
    payload = json.loads(open(batch_row["content_ref"][len("file://"):], "r", encoding="utf-8").read())
    assert payload["execution_proof"] is False

    ready = service.finalize_case(
        control,
        run_id=RUN,
        execution_task_id=EXEC_TASK,
        case=case,
        prepared=prepared,
        batch=batch,
        reservation=reservation,
        freshness=freshness,
    )
    assert truth.query("rc7_task", task_id=ready.task_id)[0]["state"] == "PASS"
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL" and row.get("data", {}).get("node_id") == "N5"
    ]

    adoption = WaveCNodeAdoptionControl(truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence"))
    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N5",
        director_ref="director-runtime-authority",
    )
    assert decision.accepted is True
    assert truth.query("rc7_control_event", event_id=decision.terminal_event_id)[0]["data"]["state"] == "PASS"


def test_n5_cannot_finalize_without_current_prepared_attempt(tmp_path) -> None:
    _truth, control, case, prepared = _setup(tmp_path)
    service = AutonomousPreparationNodeService(evidence_root=str(tmp_path / "evidence"))
    batch, reservation, freshness = _prepare_ready(service, control, case, prepared)
    broken = RuntimePreparedAttempt(
        prepared=prepared.prepared,
        artifact_id="ART-NOT-REAL",
        evidence_ids=prepared.evidence_ids,
        content_ref=prepared.content_ref,
        content_hash=prepared.content_hash,
        case_sha256=prepared.case_sha256,
    )
    with pytest.raises(AutonomousPreparationNodeError, match="N5_PREPARED_ATTEMPT_NOT_UNIQUE"):
        service.finalize_case(
            control,
            run_id=RUN,
            execution_task_id=EXEC_TASK,
            case=case,
            prepared=broken,
            batch=batch,
            reservation=reservation,
            freshness=freshness,
        )


def test_n5_auth_requires_current_foura_evidence(tmp_path) -> None:
    old = int(time.time()) - 3600
    _truth, control, case, prepared = _setup(tmp_path, auth_created_at=old)
    service = AutonomousPreparationNodeService(evidence_root=str(tmp_path / "evidence"), max_freshness_seconds=60)
    batch, reservation, freshness = _prepare_ready(service, control, case, prepared)
    with pytest.raises(AutonomousPreparationNodeError, match="N5_CURRENT_FOURA_AUTH_EVIDENCE_REQUIRED"):
        service.finalize_case(
            control,
            run_id=RUN,
            execution_task_id=EXEC_TASK,
            case=case,
            prepared=prepared,
            batch=batch,
            reservation=reservation,
            freshness=freshness,
        )


def test_n5_stale_freshness_forbids_finalization(tmp_path) -> None:
    _truth, control, case, prepared = _setup(tmp_path)
    service = AutonomousPreparationNodeService(evidence_root=str(tmp_path / "evidence"), max_freshness_seconds=30)
    old = int(time.time()) - 120
    batch, reservation, freshness = _prepare_ready(service, control, case, prepared, freshness_time=old)
    with pytest.raises(AutonomousPreparationNodeError, match="N5_FRESHNESS_EXPIRED"):
        service.finalize_case(
            control,
            run_id=RUN,
            execution_task_id=EXEC_TASK,
            case=case,
            prepared=prepared,
            batch=batch,
            reservation=reservation,
            freshness=freshness,
        )
