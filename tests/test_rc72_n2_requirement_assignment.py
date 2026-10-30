import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_n2_requirement_assignment import (
    N2RequirementAssignmentError,
    N2RequirementAssignmentService,
    install_rc72_n2_requirement_assignment_overlay,
    validate_rc72_n2_requirement_assignment,
)

from rc72_n2_test_support import (
    BATCH,
    COMMIT,
    MISSION,
    N1_WORKER,
    RELEASE,
    REQUIREMENTS,
    build_truth,
    dispatch_n2,
)


def _ready(truth, tmp_path):
    install_rc72_n2_requirement_assignment_overlay()
    truth = truth or build_truth(tmp_path)
    fixture = dispatch_n2(truth)
    return truth, fixture


def test_n2_assignment_leases_each_requirement_to_distinct_fresh_worker(tmp_path):
    truth, fixture = _ready(None, tmp_path)

    result = N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert result["node_state"] == "RUNNING"
    assert len(result["assignments"]) == len(REQUIREMENTS)
    assert {item["requirement_id"] for item in result["assignments"]} == set(REQUIREMENTS)
    workers = {item["worker_instance_id"] for item in result["assignments"]}
    assert len(workers) == len(REQUIREMENTS)
    assert N1_WORKER not in workers

    n2_dispatches = {
        row["requirement_id"]: row
        for row in truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH)
    }
    for item in result["assignments"]:
        assert item["status"] == "ASSIGNED"
        assert item["workitem_state"] == "LEASED"
        task = truth.query("rc7_task", task_id=item["workitem_id"])[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == item["worker_instance_id"]
        receipt = truth.query(
            "rc72_n2_requirement_assignment",
            assignment_id=item["assignment_id"],
        )[0]
        dispatch = n2_dispatches[item["requirement_id"]]
        assert receipt["dispatch_id"] == dispatch["dispatch_id"]
        assert receipt["worker_instance_id"] == item["worker_instance_id"]
        assert receipt["required_capabilities"] == ["requirement_reasoning"]
        assert receipt["input_refs"][0] == "requirement://%s" % item["requirement_id"]
        assert receipt["recovered_orphan_lease"] is False

    assert truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT") == []
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N2_REQUIREMENT") == []


def test_n2_assignment_is_idempotent_and_does_not_rotate_worker_without_revision(tmp_path):
    truth, _ = _ready(None, tmp_path)
    service = N2RequirementAssignmentService(truth, source_commit=COMMIT)

    first = service.assign_all(release_batch_id=BATCH)
    second = service.assign_all(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    first_by_req = {item["requirement_id"]: item for item in first["assignments"]}
    second_by_req = {item["requirement_id"]: item for item in second["assignments"]}
    assert set(first_by_req) == set(second_by_req)
    for requirement_id in REQUIREMENTS:
        assert first_by_req[requirement_id]["assignment_id"] == second_by_req[requirement_id]["assignment_id"]
        assert first_by_req[requirement_id]["worker_instance_id"] == second_by_req[requirement_id]["worker_instance_id"]
    assert len(truth.query("rc72_n2_requirement_assignment", mission_id=MISSION)) == len(REQUIREMENTS)


def test_n2_assignment_rejects_competing_lease_before_creating_any_receipt(tmp_path):
    truth, fixture = _ready(None, tmp_path)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    foreign = control.lease_next(
        worker_ref="FOREIGN-N2-WORKER",
        capabilities=["requirement_reasoning"],
    )
    assert foreign is not None
    assert foreign.task_id in fixture["n2"]["workitem_ids"]

    with pytest.raises(
        N2RequirementAssignmentError,
        match="COMPETING_LEASE_OWNER",
    ):
        N2RequirementAssignmentService(
            truth, source_commit=COMMIT
        ).assign_all(release_batch_id=BATCH)

    assert truth.query("rc72_n2_requirement_assignment", mission_id=MISSION) == []
    leased = truth.query("rc7_task", task_id=foreign.task_id)[0]
    assert leased["lease_owner"] == "FOREIGN-N2-WORKER"
    other = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS" and row.get("task_id") != foreign.task_id
    ]
    assert len(other) == len(REQUIREMENTS) - 1
    assert all(row["state"] == "READY" for row in other)


def test_n2_assignment_recovers_expected_orphan_lease_and_assigns_remaining(tmp_path):
    truth, _ = _ready(None, tmp_path)
    service = N2RequirementAssignmentService(truth, source_commit=COMMIT)
    dispatches = sorted(
        truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH),
        key=lambda row: row["workitem_id"],
    )
    first = dispatches[0]
    assignment_id = service._assignment_id(first["dispatch_id"], first["workitem_id"])
    expected_worker = service._worker_instance_id(assignment_id)

    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref=expected_worker,
        capabilities=["requirement_reasoning"],
    )
    assert leased is not None
    assert leased.task_id == first["workitem_id"]

    result = service.assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    recovered = [item for item in result["assignments"] if item["assignment_id"] == assignment_id]
    assert len(recovered) == 1
    assert recovered[0]["status"] == "RECOVERED"
    receipt = truth.query(
        "rc72_n2_requirement_assignment", assignment_id=assignment_id
    )[0]
    assert receipt["recovered_orphan_lease"] is True
    assert receipt["worker_instance_id"] == expected_worker
    assert len(truth.query("rc72_n2_requirement_assignment", mission_id=MISSION)) == len(REQUIREMENTS)


def test_n2_assignment_validator_rejects_execution_and_pass_claims(tmp_path):
    truth, _ = _ready(None, tmp_path)
    result = N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    receipt = truth.query(
        "rc72_n2_requirement_assignment",
        assignment_id=result["assignments"][0]["assignment_id"],
    )[0]

    for field, value in (
        ("dsh_session_id", "session-fake"),
        ("attempt_id", "ATT-FAKE"),
        ("execution_result", "PASS"),
        ("delivery_id", "ND-FAKE"),
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
            validate_rc72_n2_requirement_assignment(invalid)
