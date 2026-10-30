from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc7_runtime.rc72_field_mission_start import (
    ReleaseBatchFieldMissionLauncher,
    install_rc72_field_mission_start_overlay,
)
from rc7_runtime.rc72_mission_node_assignment import (
    MissionNodeAssignmentError,
    N1AgentTeamsAssignmentService,
    install_rc72_mission_node_assignment_overlay,
    validate_rc72_mission_node_worker_assignment,
)
from rc7_runtime.rc72_mission_node_dispatch import (
    N1AutonomousDispatchService,
    install_rc72_mission_node_dispatch_overlay,
)
from rc7_runtime.rc72_q7_admission import install_rc72_q7_admission_overlay
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "1111111111111111111111111111111111111111"
OTHER_COMMIT = "2222222222222222222222222222222222222222"


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_q7_admission_overlay()
    install_rc72_field_mission_start_overlay()
    install_rc72_mission_node_dispatch_overlay()
    install_rc72_mission_node_assignment_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _bootstrap(
    truth: TruthRuntime,
    *,
    release_id: str,
    mission_id: str,
    batch_id: str,
    source_commit: str = COMMIT,
) -> dict:
    truth.append_atomic(
        "RC72_RELEASE_BATCH_UPSERTED",
        {
            "release_batch_id": batch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "name": release_id,
            "planned_release_time": None,
            "version_ids": [release_id],
            "application_ids": ["APP-%s" % batch_id],
            "requirement_ids": ["REQ-%s" % batch_id],
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
            "admission_id": "Q7ADM-%s" % batch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": batch_id,
            "source_commit": source_commit,
            "status": "ADMITTED",
            "reason": "FIELD_PREREQUISITES_COMPLETE",
            "provenance_id": "PROV-%s" % batch_id,
            "scope_snapshot_id": "SCOPE-%s" % batch_id,
            "qualification_receipt_ids": [
                "QUAL-%s-Q3" % batch_id,
                "QUAL-%s-Q4" % batch_id,
                "QUAL-%s-Q5" % batch_id,
                "QUAL-%s-Q6" % batch_id,
            ],
            "hold_reasons": [],
            "input_digest": "a" * 64,
            "field_verified": False,
            "bank_final": False,
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    ReleaseBatchFieldMissionLauncher(
        truth, source_commit=source_commit
    ).start(release_batch_id=batch_id)
    return N1AutonomousDispatchService(
        truth, source_commit=source_commit
    ).dispatch(release_batch_id=batch_id)


@pytest.mark.parametrize(
    "release_id,mission_id,batch_id",
    [
        ("PAYMENT-R9.1.4", "MISSION-PAY-914", "RB-PAY-914"),
        ("CONFIG-X5.2.7", "MISSION-CFG-527", "RB-CFG-527"),
    ],
)
def test_n1_dispatch_is_leased_to_fresh_agentteams_worker_without_execution_claims(
    tmp_path: Path,
    release_id: str,
    mission_id: str,
    batch_id: str,
):
    truth = _truth(tmp_path)
    dispatch = _bootstrap(
        truth,
        release_id=release_id,
        mission_id=mission_id,
        batch_id=batch_id,
    )

    result = N1AgentTeamsAssignmentService(
        truth, source_commit=COMMIT
    ).assign(release_batch_id=batch_id)

    assert result["status"] == "ASSIGNED"
    assert result["dispatch_id"] == dispatch["dispatch_id"]
    assert result["workitem_id"] == dispatch["workitem_id"]
    assert result["workitem_state"] == "LEASED"
    assert result["node_state"] == "RUNNING"
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert result["team_role"] == "REALITY_RECON_WORKER"
    assert result["agent_id"] == "reality-recon"
    assert result["worker_instance_id"].startswith("RC72FW-")

    task = truth.query("rc7_task", task_id=result["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == result["worker_instance_id"]

    assignment = truth.query(
        "rc72_mission_node_worker_assignment",
        assignment_id=result["assignment_id"],
    )[0]
    assert assignment["status"] == "LEASED_FOR_HANDOFF"
    assert assignment["task_state"] == "LEASED"
    assert assignment["worker_instance_id"] == result["worker_instance_id"]
    assert assignment["dispatch_id"] == dispatch["dispatch_id"]
    assert assignment["recovered_orphan_lease"] is False
    assert assignment["input_refs"]
    assert assignment["required_capabilities"] == ["reality_recon", "field_evidence"]

    for forbidden in (
        "session_id", "dsh_session_id", "attempt_id", "execution_attempt_id",
        "execution_result", "output_refs", "evidence_refs", "node_gate",
        "q7_pass", "field_verified", "bank_final",
    ):
        assert forbidden not in result
        assert forbidden not in assignment

    assert truth.query("rc72_etu", mission_id=mission_id) == []
    n2 = truth.query(
        "rc72_mission_node",
        mission_id=mission_id,
        node_type=AutonomousMissionNode.N2_REQUIREMENT.value,
    )[0]
    assert n2["state"] == "NOT_STARTED"


def test_assignment_is_idempotent_and_does_not_duplicate_worker(tmp_path: Path):
    truth = _truth(tmp_path)
    _bootstrap(
        truth,
        release_id="DEPOSIT-R3.1.0",
        mission_id="MISSION-DEP-310",
        batch_id="RB-DEP-310",
    )
    service = N1AgentTeamsAssignmentService(truth, source_commit=COMMIT)

    first = service.assign(release_batch_id="RB-DEP-310")
    second = service.assign(release_batch_id="RB-DEP-310")

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert first["assignment_id"] == second["assignment_id"]
    assert first["worker_instance_id"] == second["worker_instance_id"]
    assert len(truth.query(
        "rc72_mission_node_worker_assignment",
        mission_id="MISSION-DEP-310",
    )) == 1
    task = truth.query("rc7_task", task_id=first["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == first["worker_instance_id"]


def test_assignment_requires_exact_current_source_dispatch(tmp_path: Path):
    truth = _truth(tmp_path)
    _bootstrap(
        truth,
        release_id="RISK-R4.4.1",
        mission_id="MISSION-RISK-441",
        batch_id="RB-RISK-441",
        source_commit=OTHER_COMMIT,
    )

    with pytest.raises(MissionNodeAssignmentError, match="EXACT_DISPATCH_REQUIRED:0"):
        N1AgentTeamsAssignmentService(
            truth, source_commit=COMMIT
        ).assign(release_batch_id="RB-RISK-441")

    task = truth.query("rc7_task", mission_id="MISSION-RISK-441")[0]
    assert task["state"] == "READY"
    assert task.get("lease_owner") in {None, ""}


def test_competing_task_lease_cannot_be_relabelled_as_assignment(tmp_path: Path):
    truth = _truth(tmp_path)
    dispatch = _bootstrap(
        truth,
        release_id="CARD-R7.0.2",
        mission_id="MISSION-CARD-702",
        batch_id="RB-CARD-702",
    )
    control = ClosedLoopControlPlane(
        truth, "CARD-R7.0.2", "MISSION-CARD-702"
    )
    leased = control.lease_next(
        worker_ref="FOREIGN-WORKER",
        capabilities=["reality_recon", "field_evidence"],
    )
    assert leased is not None
    assert leased.task_id == dispatch["workitem_id"]

    with pytest.raises(MissionNodeAssignmentError, match="COMPETING_LEASE_OWNER"):
        N1AgentTeamsAssignmentService(
            truth, source_commit=COMMIT
        ).assign(release_batch_id="RB-CARD-702")

    assert truth.query(
        "rc72_mission_node_worker_assignment",
        mission_id="MISSION-CARD-702",
    ) == []
    task = truth.query("rc7_task", task_id=dispatch["workitem_id"])[0]
    assert task["lease_owner"] == "FOREIGN-WORKER"


def test_orphan_deterministic_lease_is_recovered_without_new_worker(tmp_path: Path):
    truth = _truth(tmp_path)
    dispatch = _bootstrap(
        truth,
        release_id="LEDGER-R8.5.0",
        mission_id="MISSION-LEDGER-850",
        batch_id="RB-LEDGER-850",
    )
    service = N1AgentTeamsAssignmentService(truth, source_commit=COMMIT)
    assignment_id = service._assignment_id(
        dispatch["dispatch_id"], dispatch["workitem_id"]
    )
    expected_worker = service._worker_instance_id(assignment_id)

    control = ClosedLoopControlPlane(
        truth, "LEDGER-R8.5.0", "MISSION-LEDGER-850"
    )
    leased = control.lease_next(
        worker_ref=expected_worker,
        capabilities=["reality_recon", "field_evidence"],
    )
    assert leased is not None

    result = service.assign(release_batch_id="RB-LEDGER-850")

    assert result["status"] == "RECOVERED"
    assert result["worker_instance_id"] == expected_worker
    receipt = truth.query(
        "rc72_mission_node_worker_assignment",
        assignment_id=assignment_id,
    )[0]
    assert receipt["recovered_orphan_lease"] is True
    assert receipt["worker_instance_id"] == expected_worker


def test_assignment_validator_rejects_fake_session_attempt_and_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _bootstrap(
        truth,
        release_id="ACCOUNT-R6.0.3",
        mission_id="MISSION-ACC-603",
        batch_id="RB-ACC-603",
    )
    result = N1AgentTeamsAssignmentService(
        truth, source_commit=COMMIT
    ).assign(release_batch_id="RB-ACC-603")
    receipt = truth.query(
        "rc72_mission_node_worker_assignment",
        assignment_id=result["assignment_id"],
    )[0]

    for field, value in (
        ("dsh_session_id", "DSH-FAKE"),
        ("attempt_id", "ATT-FAKE"),
        ("execution_result", "PASS"),
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
            validate_rc72_mission_node_worker_assignment(invalid)
