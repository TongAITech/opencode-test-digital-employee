from pathlib import Path

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_n3_source_target_assignment import (
    N3SourceTargetAssignmentError,
    N3SourceTargetAssignmentService,
    validate_rc72_n3_source_target_assignment,
)
from rc7_runtime.rc72_n3_source_target_dispatch import N3SourceTargetDispatchService

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_dispatch import _n2_pass


def _dispatched(tmp_path: Path):
    truth = _n2_pass(tmp_path)
    dispatch = N3SourceTargetDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    return truth, dispatch


def test_n3_source_discovery_assignment_leases_exact_workitem_to_fresh_worker(tmp_path: Path):
    truth, dispatch = _dispatched(tmp_path)

    result = N3SourceTargetAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert len(result["assignments"]) == len(dispatch["dispatches"]) == 1
    assignment = result["assignments"][0]
    source_dispatch = dispatch["dispatches"][0]
    assert assignment["dispatch_id"] == source_dispatch["dispatch_id"]
    assert assignment["application_id"] == source_dispatch["application_id"]
    assert assignment["worker_instance_id"].startswith("RC72N3SRCFW-")
    assert assignment["assignment_generation"] == 1
    task = truth.query("rc7_task", task_id=assignment["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == assignment["worker_instance_id"]
    assert truth.query("agent_runtime_event", mission_id=MISSION) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []


def test_n3_source_discovery_assignment_is_idempotent(tmp_path: Path):
    truth, _dispatch = _dispatched(tmp_path)
    service = N3SourceTargetAssignmentService(truth, source_commit=COMMIT)

    first = service.assign_all(release_batch_id=BATCH)
    second = service.assign_all(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert first["assignments"] == second["assignments"]
    assert len(truth.query("rc72_n3_source_target_assignment", release_batch_id=BATCH)) == 1


def test_n3_source_discovery_assignment_rejects_competing_lease(tmp_path: Path):
    truth, dispatch = _dispatched(tmp_path)
    source = dispatch["dispatches"][0]
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref="FOREIGN-SOURCE-DISCOVERY-WORKER",
        capabilities=["source_target_discovery"],
    )
    assert leased is not None and leased.task_id == source["workitem_id"]

    with pytest.raises(N3SourceTargetAssignmentError, match="COMPETING_LEASE_OWNER"):
        N3SourceTargetAssignmentService(
            truth, source_commit=COMMIT
        ).assign_all(release_batch_id=BATCH)

    assert truth.query("rc72_n3_source_target_assignment", release_batch_id=BATCH) == []


def test_n3_assignment_contract_forbids_source_mapping_claims(tmp_path: Path):
    truth, _dispatch = _dispatched(tmp_path)
    result = N3SourceTargetAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    row = truth.query(
        "rc72_n3_source_target_assignment",
        assignment_id=result["assignments"][0]["assignment_id"],
    )[0]
    tampered = dict(row)
    tampered["repository_ref"] = "guessed://repo"
    with pytest.raises(Exception, match="EXECUTION_CLAIM_FORBIDDEN:repository_ref"):
        validate_rc72_n3_source_target_assignment(tampered)
