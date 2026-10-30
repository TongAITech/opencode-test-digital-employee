from pathlib import Path

import pytest

from rc7_runtime.rc72_n3_source_target_revision import (
    N3SourceTargetRevisionError,
    N3SourceTargetRevisionService,
    validate_rc72_n3_source_target_revision,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n3_source_target_promotion import _assert_downstream_locked
from test_rc72_n3_source_target_review import (
    _promoted,
    _review_launcher,
    _service,
)


APPLICATION = "BLOAN"


def _repair_required(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    reviewed = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            decision="GAPS",
            gap_ids=["SOURCE_REVISION_NOT_PROVEN"],
        ),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "REPAIR_REQUIRED"
    assert reviewed.task_state == "REPAIR_REQUIRED"
    assert reviewed.gap_ids
    return truth, promoted, reviewed


def test_mapping_gap_creates_fresh_generation2_workitem_and_worker_only(tmp_path: Path):
    truth, promoted, reviewed = _repair_required(tmp_path)
    old_task_before = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    old_worker = old_task_before["lease_owner"]

    result = N3SourceTargetRevisionService(
        truth, source_commit=COMMIT
    ).plan_and_assign(release_batch_id=BATCH)

    assert result["status"] == "ASSIGNED"
    assert result["node_state"] == "RUNNING"
    assert result["n4_state"] == "NOT_STARTED"
    assert len(result["revisions"]) == 1
    revision = result["revisions"][0]
    assert revision["application_id"] == APPLICATION
    assert revision["revision_generation"] == 2
    assert revision["trigger_evaluation_id"] == reviewed.evaluation_id
    assert revision["previous_workitem_id"] == promoted["task_id"]
    assert revision["previous_artifact_id"] == promoted["artifact_id"]
    assert revision["revision_worker_instance_id"] != old_worker
    assert set(revision["gap_refs"]) == set(reviewed.gap_ids)
    assert promoted["artifact_id"] in revision["input_artifact_refs"]

    old_task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    new_task = truth.query(
        "rc7_task", task_id=revision["revision_workitem_id"]
    )[0]
    assert old_task["state"] == "STALE"
    assert new_task["state"] == "LEASED"
    assert new_task["lease_owner"] == revision["revision_worker_instance_id"]
    assert new_task["node"] == "SOURCE_TARGET_DISCOVERY"
    assert new_task["required_capabilities"] == ["source_target_discovery"]
    assert set(new_task["gap_refs"]) == set(reviewed.gap_ids)

    rows = truth.query("rc72_n3_source_target_revision", release_batch_id=BATCH)
    assert len(rows) == 1
    assert rows[0]["revision_id"] == revision["revision_id"]
    assert rows[0]["recovered_orphan_lease"] is False
    assert truth.query("rc72_n3_source_target_attempt", workitem_id=revision["revision_workitem_id"]) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_same_failed_mapping_review_replay_does_not_mint_generation3(tmp_path: Path):
    truth, _promoted_row, _reviewed = _repair_required(tmp_path)
    service = N3SourceTargetRevisionService(truth, source_commit=COMMIT)

    first = service.plan_and_assign(release_batch_id=BATCH)
    second = service.plan_and_assign(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert first["revisions"] == second["revisions"]
    assert first["revisions"][0]["revision_generation"] == 2
    assert len(truth.query("rc72_n3_source_target_revision", release_batch_id=BATCH)) == 1
    assert len([
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "SOURCE_TARGET_DISCOVERY"
        and row.get("task_id") == first["revisions"][0]["revision_workitem_id"]
    ]) == 1
    _assert_downstream_locked(truth)


def test_source_mapping_pass_has_no_revision_workitem(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    reviewed = _service(
        tmp_path,
        truth,
        _review_launcher(tmp_path, truth),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "PASS"

    with pytest.raises(
        N3SourceTargetRevisionError,
        match="AFFECTED_APPLICATION_REQUIRED",
    ):
        N3SourceTargetRevisionService(
            truth, source_commit=COMMIT
        ).plan_and_assign(release_batch_id=BATCH)

    assert truth.query("rc72_n3_source_target_revision", release_batch_id=BATCH) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_revision_receipt_rejects_source_truth_or_execution_claim_smuggling(tmp_path: Path):
    truth, _promoted_row, _reviewed = _repair_required(tmp_path)
    result = N3SourceTargetRevisionService(
        truth, source_commit=COMMIT
    ).plan_and_assign(release_batch_id=BATCH)
    revision_id = result["revisions"][0]["revision_id"]
    row = dict(
        truth.query("rc72_n3_source_target_revision", revision_id=revision_id)[0]
    )

    for field, value in (
        ("repository_ref", "git://guessed/repository"),
        ("source_revision", "deadbeef"),
        ("dsh_session_id", "session-fake"),
        ("code_analysis_result", "PASS"),
    ):
        tampered = dict(row)
        tampered[field] = value
        with pytest.raises(Exception, match="EXECUTION_CLAIM_FORBIDDEN:%s" % field):
            validate_rc72_n3_source_target_revision(tampered)
