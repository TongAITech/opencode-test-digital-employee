from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task
from rc7_runtime.rc72_domain import AutonomousMissionNode, MissionNodeState
from rc7_runtime.rc72_field_mission_start import (
    ReleaseBatchFieldMissionLauncher,
    install_rc72_field_mission_start_overlay,
)
from rc7_runtime.rc72_mission_node_dispatch import (
    MissionNodeDispatchError,
    N1AutonomousDispatchService,
    install_rc72_mission_node_dispatch_overlay,
    validate_rc72_mission_node_dispatch,
)
from rc7_runtime.rc72_q7_admission import install_rc72_q7_admission_overlay
from rc7_runtime.rc72_state_machine import RC72StateMachine
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
    return TruthRuntime(tmp_path / "r1.jsonl")


def _batch_and_admission(
    truth: TruthRuntime,
    *,
    release_id: str,
    mission_id: str,
    batch_id: str,
    source_commit: str = COMMIT,
) -> None:
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


def _started(
    truth: TruthRuntime,
    *,
    release_id: str,
    mission_id: str,
    batch_id: str,
    source_commit: str = COMMIT,
) -> dict:
    _batch_and_admission(
        truth,
        release_id=release_id,
        mission_id=mission_id,
        batch_id=batch_id,
        source_commit=source_commit,
    )
    return ReleaseBatchFieldMissionLauncher(
        truth,
        source_commit=source_commit,
    ).start(release_batch_id=batch_id)


@pytest.mark.parametrize(
    "release_id,mission_id,batch_id",
    [
        ("PAYMENT-R8.2.6", "MISSION-PAY-826", "RB-PAY-826"),
        ("CONFIG-X4.7.3", "MISSION-CFG-473", "RB-CFG-473"),
    ],
)
def test_admitted_field_mission_materializes_generic_n1_workitem_and_dispatch(
    tmp_path: Path,
    release_id: str,
    mission_id: str,
    batch_id: str,
):
    truth = _truth(tmp_path)
    start = _started(
        truth,
        release_id=release_id,
        mission_id=mission_id,
        batch_id=batch_id,
    )

    result = N1AutonomousDispatchService(
        truth,
        source_commit=COMMIT,
    ).dispatch(release_batch_id=batch_id)

    assert result["status"] == "DISPATCHED"
    assert result["release_id"] == release_id
    assert result["mission_id"] == mission_id
    assert result["release_batch_id"] == batch_id
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert result["team_role"] == "REALITY_RECON_WORKER"
    assert result["node_state"] == "RUNNING"
    assert result["workitem_state"] == "READY"

    mission_rows = truth.query("rc7_mission", mission_id=mission_id)
    assert len(mission_rows) == 1
    assert mission_rows[0]["release_id"] == release_id

    task_rows = truth.query("rc7_task", task_id=result["workitem_id"])
    assert len(task_rows) == 1
    task = task_rows[0]
    assert task["mission_id"] == mission_id
    assert task["node"] == "REALITY_RECON"
    assert task["task_type"] == "RC72_NODE_WORK"
    assert task["state"] == "READY"
    assert "reality_recon" in task["required_capabilities"]
    assert "field_evidence" in task["required_capabilities"]

    n1 = truth.query(
        "rc72_mission_node",
        mission_id=mission_id,
        node_type=AutonomousMissionNode.N1_REALITY.value,
    )[0]
    assert n1["mission_node_id"] == start["n1_mission_node_id"]
    assert n1["state"] == "RUNNING"

    dispatch = truth.query("rc72_mission_node_dispatch", dispatch_id=result["dispatch_id"])[0]
    assert dispatch["field_start_receipt_id"] == start["start_receipt_id"]
    assert dispatch["mission_node_id"] == start["n1_mission_node_id"]
    assert dispatch["workitem_id"] == result["workitem_id"]
    assert dispatch["status"] == "READY_FOR_ASSIGNMENT"


def test_dispatch_requires_exact_governed_field_start_before_any_rc7_task_side_effect(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch_and_admission(
        truth,
        release_id="ORDER-R1.8.0",
        mission_id="MISSION-ORDER-180",
        batch_id="RB-ORDER-180",
    )
    # N1-N10 exist, but no governed field-start receipt is present.
    from rc7_runtime.rc72_domain import ReleaseBatch

    RC72StateMachine(truth, release_id="ORDER-R1.8.0").bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-ORDER-180",
            mission_id="MISSION-ORDER-180",
            name="ORDER-R1.8.0",
            version_ids=["ORDER-R1.8.0"],
            application_ids=["APP-ORDER"],
            requirement_ids=["REQ-ORDER"],
            readiness="READY",
        )
    )

    with pytest.raises(MissionNodeDispatchError, match="EXACT_FIELD_START_REQUIRED:0"):
        N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
            release_batch_id="RB-ORDER-180"
        )

    assert truth.query("rc7_mission", mission_id="MISSION-ORDER-180") == []
    assert truth.query("rc7_task", mission_id="MISSION-ORDER-180") == []
    assert truth.query("rc72_mission_node_dispatch", mission_id="MISSION-ORDER-180") == []


def test_stale_source_commit_field_start_cannot_authorize_current_dispatch(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="RISK-R3.2.1",
        mission_id="MISSION-RISK-321",
        batch_id="RB-RISK-321",
        source_commit=OTHER_COMMIT,
    )

    with pytest.raises(MissionNodeDispatchError, match="EXACT_FIELD_START_REQUIRED:0"):
        N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
            release_batch_id="RB-RISK-321"
        )

    assert truth.query("rc7_task", mission_id="MISSION-RISK-321") == []


def test_n1_must_be_ready_or_already_running_to_dispatch(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="CARD-R6.1.2",
        mission_id="MISSION-CARD-612",
        batch_id="RB-CARD-612",
    )
    machine = RC72StateMachine(truth, release_id="CARD-R6.1.2")
    n1 = machine.node_by_type("MISSION-CARD-612", AutonomousMissionNode.N1_REALITY)
    machine.transition_state(
        n1["mission_node_id"],
        MissionNodeState.BLOCKED,
        reason="field prerequisite unresolved",
    )

    with pytest.raises(MissionNodeDispatchError, match="N1_STATE_INVALID:BLOCKED"):
        N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
            release_batch_id="RB-CARD-612"
        )

    assert truth.query("rc7_task", mission_id="MISSION-CARD-612") == []


def test_repeated_dispatch_resumes_same_workitem_without_duplicate_truth(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="DEPOSIT-R2.9.0",
        mission_id="MISSION-DEP-290",
        batch_id="RB-DEP-290",
    )
    service = N1AutonomousDispatchService(truth, source_commit=COMMIT)

    first = service.dispatch(release_batch_id="RB-DEP-290")
    second = service.dispatch(release_batch_id="RB-DEP-290")

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert first["dispatch_id"] == second["dispatch_id"]
    assert first["workitem_id"] == second["workitem_id"]
    assert len(truth.query("rc7_task", mission_id="MISSION-DEP-290")) == 1
    assert len(truth.query("rc72_mission_node_dispatch", mission_id="MISSION-DEP-290")) == 1


def test_preexisting_legacy_task_graph_is_not_silently_merged(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="LIMIT-R4.0.1",
        mission_id="MISSION-LIMIT-401",
        batch_id="RB-LIMIT-401",
    )
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="MISSION-LIMIT-401",
            release_id="LIMIT-R4.0.1",
            goal="legacy graph goal",
        ),
    )
    control.register_task(
        Task(
            task_id="LEGACY-WORK-1",
            mission_id="MISSION-LIMIT-401",
            node="REALITY_RECON",
            task_type="LEGACY",
            objective="legacy task",
        )
    )

    with pytest.raises(MissionNodeDispatchError, match="LEGACY_TASK_GRAPH_CONFLICT"):
        N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
            release_batch_id="RB-LIMIT-401"
        )

    assert truth.query("rc72_mission_node_dispatch", mission_id="MISSION-LIMIT-401") == []


def test_dispatch_truth_is_planning_only_and_cannot_claim_worker_attempt_or_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="ACCOUNT-R5.4.0",
        mission_id="MISSION-ACC-540",
        batch_id="RB-ACC-540",
    )
    result = N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
        release_batch_id="RB-ACC-540"
    )
    dispatch = truth.query("rc72_mission_node_dispatch", dispatch_id=result["dispatch_id"])[0]

    assert dispatch["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert dispatch["worker_policy"] == "FRESH_SESSION_REQUIRED"
    for forbidden in (
        "worker_id", "session_id", "attempt_id", "lease_id",
        "execution_result", "q7_pass", "field_verified", "bank_final",
    ):
        assert forbidden not in result
        assert forbidden not in dispatch

    invalid = dict(dispatch)
    invalid["worker_id"] = "pretend-worker"
    with pytest.raises(Exception, match="EXECUTION_CLAIM_FORBIDDEN:worker_id"):
        validate_rc72_mission_node_dispatch(invalid)


def test_n2_not_started_is_not_implicitly_dispatched_by_n1_slice(tmp_path: Path):
    truth = _truth(tmp_path)
    _started(
        truth,
        release_id="LEDGER-R7.3.0",
        mission_id="MISSION-LEDGER-730",
        batch_id="RB-LEDGER-730",
    )
    N1AutonomousDispatchService(truth, source_commit=COMMIT).dispatch(
        release_batch_id="RB-LEDGER-730"
    )

    n2 = truth.query(
        "rc72_mission_node",
        mission_id="MISSION-LEDGER-730",
        node_type=AutonomousMissionNode.N2_REQUIREMENT.value,
    )[0]
    assert n2["state"] == "NOT_STARTED"
    assert len(truth.query("rc7_task", mission_id="MISSION-LEDGER-730")) == 1
