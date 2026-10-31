from pathlib import Path

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_n5_data_discovery_assignment import (
    N5DataDiscoveryAssignmentError,
    N5DataDiscoveryAssignmentService,
)
from rc7_runtime.rc72_n5_data_discovery_dispatch import (
    N5DataDiscoveryDispatchService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_discovery_dispatch import (
    _bind_requirement,
    _resolved_inventory,
)


def _dispatched(tmp_path: Path, monkeypatch, *, all_reused=False):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    if all_reused:
        for index, data_requirement_id in enumerate(inventory["data_requirement_ids"]):
            _bind_requirement(
                truth,
                resolver,
                data_requirement_id,
                "assignment-reuse-%03d" % index,
            )
        resolver.resolve_all(release_batch_id=BATCH)
    dispatched = N5DataDiscoveryDispatchService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).dispatch(release_batch_id=BATCH)
    return truth, inventory, dispatched


def test_n5_assignment_leases_each_discovery_workitem_to_distinct_fresh_worker(
    tmp_path: Path, monkeypatch
):
    truth, inventory, dispatched = _dispatched(tmp_path, monkeypatch)
    assert dispatched["dispatch_count"] == inventory["data_requirement_count"]

    result = N5DataDiscoveryAssignmentService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert result["node_state"] == "RUNNING"
    assert result["n6_state"] == "NOT_STARTED"
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert len(result["assignments"]) == inventory["data_requirement_count"]
    worker_ids = [row["worker_instance_id"] for row in result["assignments"]]
    assert len(worker_ids) == len(set(worker_ids))

    receipts = truth.query(
        "rc72_n5_data_discovery_assignment", release_batch_id=BATCH
    )
    assert len(receipts) == inventory["data_requirement_count"]
    for receipt in receipts:
        assert receipt["task_state"] == "LEASED"
        assert receipt["status"] == "LEASED_FOR_HANDOFF"
        assert receipt["team_role"] == "DATA_PREPARER"
        assert receipt["agent_id"] == "data-preparer"
        assert receipt["assignment_generation"] == 1
        assert receipt["recovered_orphan_lease"] is False
        assert "data-requirement://%s" % receipt["data_requirement_id"] in receipt["input_refs"]
        assert "data-resolution-plan://%s" % receipt["resolution_plan_id"] in receipt["input_refs"]
        assert "case://%s" % receipt["case_id"] in receipt["input_refs"]
        assert any(ref.startswith("artifact://") for ref in receipt["input_refs"])
        assert "dsh_session_id" not in receipt
        assert "attempt_id" not in receipt
        assert "data_ref" not in receipt
        assert "data_lease_id" not in receipt
        task = truth.query("rc7_task", task_id=receipt["workitem_id"])[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == receipt["worker_instance_id"]

    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []


def test_n5_assignment_replay_is_idempotent_and_does_not_rotate_worker_early(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, dispatched = _dispatched(tmp_path, monkeypatch)
    assert dispatched["dispatch_count"] >= 1
    service = N5DataDiscoveryAssignmentService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    first = service.assign_all(release_batch_id=BATCH)
    second = service.assign_all(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    first_rows = sorted(
        (row["data_requirement_id"], row["assignment_id"], row["worker_instance_id"])
        for row in first["assignments"]
    )
    second_rows = sorted(
        (row["data_requirement_id"], row["assignment_id"], row["worker_instance_id"])
        for row in second["assignments"]
    )
    assert second_rows == first_rows
    assert len(
        truth.query("rc72_n5_data_discovery_assignment", release_batch_id=BATCH)
    ) == len(first_rows)
    assert truth.query("rc72_data_lease") == []


def test_n5_assignment_creates_no_worker_when_all_data_requirements_reuse_verified(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, dispatched = _dispatched(
        tmp_path, monkeypatch, all_reused=True
    )
    assert dispatched["status"] == "NO_DISCOVERY_REQUIRED"

    result = N5DataDiscoveryAssignmentService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "NO_ASSIGNMENT_REQUIRED"
    assert result["assignments"] == []
    assert result["node_state"] == "RUNNING"
    assert result["n6_state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_n5_data_discovery_assignment", release_batch_id=BATCH
    ) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="TEST_DATA") == []
    assert truth.query("rc72_data_lease") == []


def test_n5_assignment_rejects_competing_task_lease_owner(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, dispatched = _dispatched(tmp_path, monkeypatch)
    assert dispatched["workitem_ids"]
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref="competing-data-worker",
        capabilities=["test_data"],
    )
    assert leased is not None

    with pytest.raises(
        N5DataDiscoveryAssignmentError,
        match="COMPETING_LEASE_OWNER",
    ):
        N5DataDiscoveryAssignmentService(
            truth,
            release_id=RELEASE,
            source_commit=COMMIT,
        ).assign_all(release_batch_id=BATCH)

    assert truth.query(
        "rc72_n5_data_discovery_assignment", release_batch_id=BATCH
    ) == []
    assert truth.query("rc72_data_lease") == []
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n6["state"] == "NOT_STARTED"
