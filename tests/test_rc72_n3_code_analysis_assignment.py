from pathlib import Path

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_n3_code_analysis_assignment import (
    N3CodeAnalysisAssignmentError,
    N3CodeAnalysisAssignmentService,
    validate_rc72_n3_code_analysis_assignment,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_code_analysis_dispatch import (
    _accepted,
    _accepted_two_targets,
    _dispatch,
)


def _dispatched(tmp_path: Path, *, two_targets=False):
    if two_targets:
        truth, _promoted, _reviewed = _accepted_two_targets(tmp_path)
    else:
        truth, _promoted, _reviewed = _accepted(tmp_path)
    dispatched = _dispatch(truth).dispatch(release_batch_id=BATCH)
    return truth, dispatched


def test_code_assignment_leases_each_target_to_distinct_fresh_worker(tmp_path: Path):
    truth, dispatched = _dispatched(tmp_path, two_targets=True)
    before_events = len(truth.query("agent_runtime_event", mission_id=MISSION))

    result = N3CodeAnalysisAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert len(result["assignments"]) == len(dispatched["workitem_ids"]) == 2
    assignments = result["assignments"]
    assert len({row["worker_instance_id"] for row in assignments}) == 2
    assert all(row["worker_instance_id"].startswith("RC72N3CODEFW-") for row in assignments)
    assert all(row["required_capabilities"] == ["code_reasoning", "code_reality"] for row in assignments)
    assert all(row["repository_ref"].startswith("git://") for row in assignments)
    assert all(row["source_revision"] for row in assignments)
    assert all(row["source_mapping_artifact_id"] for row in assignments)
    assert all(row["source_mapping_evaluation_id"] for row in assignments)
    for assignment in assignments:
        task = truth.query("rc7_task", task_id=assignment["workitem_id"])[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == assignment["worker_instance_id"]
        assert task["output_artifact_refs"] == []
        assert task["evaluation_id"] is None
    assert len(truth.query("agent_runtime_event", mission_id=MISSION)) == before_events
    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []


def test_code_assignment_replay_is_idempotent(tmp_path: Path):
    truth, _dispatched_row = _dispatched(tmp_path)
    service = N3CodeAnalysisAssignmentService(truth, source_commit=COMMIT)

    first = service.assign_all(release_batch_id=BATCH)
    second = service.assign_all(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert first["assignments"] == second["assignments"]
    assert len(truth.query("rc72_n3_code_analysis_assignment", release_batch_id=BATCH)) == 1


def test_code_assignment_rejects_competing_lease_before_any_receipt(tmp_path: Path):
    truth, dispatched = _dispatched(tmp_path, two_targets=True)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    leased = control.lease_next(
        worker_ref="FOREIGN-CODE-ANALYSIS-WORKER",
        capabilities=["code_reasoning", "code_reality"],
    )
    assert leased is not None
    assert leased.task_id in dispatched["workitem_ids"]

    with pytest.raises(
        N3CodeAnalysisAssignmentError,
        match="COMPETING_LEASE_OWNER",
    ):
        N3CodeAnalysisAssignmentService(
            truth, source_commit=COMMIT
        ).assign_all(release_batch_id=BATCH)

    assert truth.query("rc72_n3_code_analysis_assignment", release_batch_id=BATCH) == []


def test_code_assignment_contract_forbids_execution_and_pass_claims(tmp_path: Path):
    truth, _dispatched_row = _dispatched(tmp_path)
    result = N3CodeAnalysisAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    row = truth.query(
        "rc72_n3_code_analysis_assignment",
        assignment_id=result["assignments"][0]["assignment_id"],
    )[0]

    for field, value in (
        ("dsh_session_id", "session-forbidden"),
        ("attempt_id", "ATT-forbidden"),
        ("graph_evidence", {"forbidden": True}),
        ("node_pass", True),
        ("n4_started", True),
    ):
        tampered = dict(row)
        tampered[field] = value
        with pytest.raises(Exception, match="EXECUTION_CLAIM_FORBIDDEN:%s" % field):
            validate_rc72_n3_code_analysis_assignment(tampered)
