from pathlib import Path

import pytest

from rc7_runtime.rc72_n4_test_design_assignment import (
    N4TestDesignAssignmentError,
    N4TestDesignAssignmentService,
)
from rc7_runtime.rc72_n4_test_design_dispatch import N4TestDesignDispatchService

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n4_test_design_dispatch import _n4_ready


def _dispatched(tmp_path: Path, monkeypatch):
    truth, snapshot = _n4_ready(tmp_path, monkeypatch)
    dispatched = N4TestDesignDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    return truth, snapshot, dispatched


def test_n4_assigns_one_distinct_fresh_worker_per_requirement_sst(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched = _dispatched(tmp_path, monkeypatch)
    result = N4TestDesignAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert result["mission_id"] == MISSION
    assert result["node_state"] == "RUNNING"
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert len(result["assignments"]) == len(dispatched["design_scopes"])

    scopes = [(row["requirement_id"], row["sst_id"]) for row in result["assignments"]]
    assert len(scopes) == len(set(scopes))
    worker_ids = [row["worker_instance_id"] for row in result["assignments"]]
    assert len(worker_ids) == len(set(worker_ids))

    receipts = truth.query("rc72_n4_test_design_assignment", release_batch_id=BATCH)
    assert len(receipts) == len(result["assignments"])
    by_scope = {(row["requirement_id"], row["sst_id"]): row for row in receipts}
    assert set(by_scope) == set(scopes)

    for assignment in result["assignments"]:
        scope = (assignment["requirement_id"], assignment["sst_id"])
        receipt = by_scope[scope]
        assert receipt["worker_instance_id"] == assignment["worker_instance_id"]
        assert receipt["task_state"] == "LEASED"
        assert receipt["status"] == "LEASED_FOR_HANDOFF"
        assert receipt["agent_id"] == "test-design"
        assert receipt["team_role"] == "TEST_DESIGN_WORKER"
        assert receipt["assignment_generation"] == 1
        assert receipt["recovered_orphan_lease"] is False
        assert "requirement://%s" % assignment["requirement_id"] in receipt["input_refs"]
        assert "sst://%s" % assignment["sst_id"] in receipt["input_refs"]
        assert any(ref.startswith("n4-parent-snapshot://") for ref in receipt["input_refs"])
        assert any(ref.startswith("artifact://") for ref in receipt["input_refs"])
        assert any(ref.startswith("obligation-source://") for ref in receipt["input_refs"])
        assert sum(ref.startswith("node-delivery://") for ref in receipt["input_refs"]) == 2
        assert sum(ref.startswith("node-gate://") for ref in receipt["input_refs"]) == 2
        assert "dsh_session_id" not in receipt
        assert "attempt_id" not in receipt
        assert "test_cases" not in receipt
        assert "obligations" not in receipt

        task = truth.query("rc7_task", task_id=assignment["workitem_id"])[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == assignment["worker_instance_id"]

    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_assignment_replay_is_idempotent_and_preserves_lease_owner(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched = _dispatched(tmp_path, monkeypatch)
    assert dispatched["design_scopes"]
    service = N4TestDesignAssignmentService(truth, source_commit=COMMIT)
    first = service.assign_all(release_batch_id=BATCH)
    second = service.assign_all(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    first_rows = sorted(
        (row["requirement_id"], row["sst_id"], row["assignment_id"], row["worker_instance_id"])
        for row in first["assignments"]
    )
    second_rows = sorted(
        (row["requirement_id"], row["sst_id"], row["assignment_id"], row["worker_instance_id"])
        for row in second["assignments"]
    )
    assert second_rows == first_rows
    assert len(truth.query("rc72_n4_test_design_assignment", release_batch_id=BATCH)) == len(first_rows)
    for row in second["assignments"]:
        task = truth.query("rc7_task", task_id=row["workitem_id"])[0]
        assert task["lease_owner"] == row["worker_instance_id"]


def test_n4_assignment_fails_closed_on_competing_lease_owner(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched = _dispatched(tmp_path, monkeypatch)
    target = dispatched["workitem_ids"][0]
    rows = truth.query("rc7_task", task_id=target)
    assert len(rows) == 1
    task = dict(rows[0])

    # Use the canonical scheduler once with an unauthorized owner to create the
    # exact state the assignment preflight must reject rather than overwriting.
    from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
    from rc72_n2_test_support import RELEASE

    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref="competing-worker",
        capabilities=list(task["required_capabilities"]),
    )
    assert leased is not None

    with pytest.raises(
        N4TestDesignAssignmentError,
        match="COMPETING_LEASE_OWNER",
    ):
        N4TestDesignAssignmentService(
            truth, source_commit=COMMIT
        ).assign_all(release_batch_id=BATCH)

    assert truth.query("rc72_n4_test_design_assignment", release_batch_id=BATCH) == []


def test_n4_assignment_has_no_authority_before_dispatch(tmp_path: Path, monkeypatch):
    truth, _snapshot = _n4_ready(tmp_path, monkeypatch)
    with pytest.raises(
        N4TestDesignAssignmentError,
        match="N4_NOT_RUNNING",
    ):
        N4TestDesignAssignmentService(
            truth, source_commit=COMMIT
        ).assign_all(release_batch_id=BATCH)
    assert truth.query("rc72_n4_test_design_assignment", release_batch_id=BATCH) == []
