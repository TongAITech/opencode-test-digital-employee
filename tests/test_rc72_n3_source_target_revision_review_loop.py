from pathlib import Path

from rc7_runtime.rc72_n3_source_target_revision_review_loop import (
    N3SourceTargetRevisionReviewLoopService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_handoff import APPLICATION
from test_rc72_n3_source_target_promotion import _assert_downstream_locked
from test_rc72_n3_source_target_review import (
    TOOL as REVIEW_TOOL,
    _review_launcher,
)
from test_rc72_n3_source_target_revision_promotion import (
    _anchor_service,
    _promotion_service,
    _revision_attempt,
)


def _promoted_revision(tmp_path: Path):
    truth, initial_promoted, initial_reviewed, revision, handoff, attempt = (
        _revision_attempt(tmp_path)
    )
    _anchor_service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    promoted = _promotion_service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert promoted["revision_generation"] == 2
    assert promoted["task_state"] == "OUTPUT_PRODUCED"
    return (
        truth,
        initial_promoted,
        initial_reviewed,
        revision,
        handoff,
        attempt,
        promoted,
    )


def _service(tmp_path: Path, truth, launcher):
    return N3SourceTargetRevisionReviewLoopService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[REVIEW_TOOL],
    )


def test_generation2_independent_pass_resolves_full_ancestor_gap_chain(tmp_path: Path):
    (
        truth,
        _initial_promoted,
        _initial_reviewed,
        revision,
        handoff,
        _attempt,
        promoted,
    ) = _promoted_revision(tmp_path)
    calls = {"count": 0}
    service = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            calls=calls,
            fixed_session="session-n3-source-revision-review-pass",
        ),
    )

    first = service.close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    second = service.close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert first["status"] == "CLOSED"
    assert second["status"] == "RESUMED"
    assert first["revision_id"] == revision["revision_id"]
    assert first["revision_generation"] == 2
    assert first["revision_artifact_id"] == promoted["artifact_id"]
    assert first["evaluation_result"] == "PASS"
    assert first["task_state"] == "PASS"
    assert first["reviewer_worker_id"] != revision["revision_worker_instance_id"]
    assert first["reviewer_session_id"] != handoff["dsh_session_id"]
    assert first["next_revision"] is None
    assert first["resolved_gap_refs"] == first["ancestor_gap_refs"]
    assert calls["count"] == 1

    for gap_id in first["ancestor_gap_refs"]:
        gap = truth.query("rc7_gap", gap_id=gap_id)[0]
        assert gap["state"] == "RESOLVED"
        assert gap["resolution_evaluation_id"] == first["evaluation_id"]

    task = truth.query(
        "rc7_task", task_id=revision["revision_workitem_id"]
    )[0]
    assert task["state"] == "PASS"
    assert task["evaluation_id"] == first["evaluation_id"]
    mission = truth.query("rc7_mission", mission_id=MISSION)[0]
    assert mission["state"] == "RUNNING"
    assert mission["open_gap_ids"] == []
    revisions = truth.query(
        "rc72_n3_source_target_revision", release_batch_id=BATCH
    )
    assert len(revisions) == 1
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_failed_generation2_review_schedules_fresh_generation3_without_closing_ancestor_gap(tmp_path: Path):
    (
        truth,
        _initial_promoted,
        _initial_reviewed,
        revision2,
        handoff2,
        _attempt2,
        promoted2,
    ) = _promoted_revision(tmp_path)
    service = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            decision="GAPS",
            gap_ids=["REVISION_MAPPING_STILL_AMBIGUOUS"],
            fixed_session="session-n3-source-revision-review-fail",
        ),
    )

    result = service.close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert result["status"] == "REVISION_SCHEDULED"
    assert result["evaluation_result"] == "REPAIR_REQUIRED"
    assert result["revision_id"] == revision2["revision_id"]
    assert result["revision_generation"] == 2
    assert result["revision_artifact_id"] == promoted2["artifact_id"]
    assert result["reviewer_session_id"] != handoff2["dsh_session_id"]
    assert result["new_gap_refs"]
    assert result["resolved_gap_refs"] == []

    for gap_id in result["ancestor_gap_refs"]:
        gap = truth.query("rc7_gap", gap_id=gap_id)[0]
        assert gap["state"] == "OPEN"
        assert gap.get("resolution_evaluation_id") in {None, ""}
    for gap_id in result["new_gap_refs"]:
        gap = truth.query("rc7_gap", gap_id=gap_id)[0]
        assert gap["state"] == "OPEN"
        assert gap["category"] == "SOURCE_TARGET_MAPPING_GAP"

    next_revision = result["next_revision"]
    assert next_revision["revision_generation"] == 3
    assert next_revision["trigger_evaluation_id"] == result["evaluation_id"]
    assert next_revision["previous_workitem_id"] == revision2["revision_workitem_id"]
    assert next_revision["previous_artifact_id"] == promoted2["artifact_id"]
    assert next_revision["revision_worker_instance_id"] != revision2["revision_worker_instance_id"]
    assert set(next_revision["gap_refs"]) == set(result["new_gap_refs"])

    old_task = truth.query(
        "rc7_task", task_id=revision2["revision_workitem_id"]
    )[0]
    new_task = truth.query(
        "rc7_task", task_id=next_revision["revision_workitem_id"]
    )[0]
    assert old_task["state"] == "STALE"
    assert new_task["state"] == "LEASED"
    assert new_task["lease_owner"] == next_revision["revision_worker_instance_id"]
    assert new_task["output_artifact_refs"] == []

    revisions = truth.query(
        "rc72_n3_source_target_revision", release_batch_id=BATCH
    )
    assert sorted(row["revision_generation"] for row in revisions) == [2, 3]
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_revision_pass_resolution_records_legal_gap_state_history(tmp_path: Path):
    truth, *_rest = _promoted_revision(tmp_path)
    result = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-source-revision-review-history",
        ),
    ).close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert result["evaluation_result"] == "PASS"
    for gap_id in result["ancestor_gap_refs"]:
        history = truth.projection.history("rc7_gap", gap_id)
        states = [str(row["state"]) for row in history]
        for expected in (
            "OPEN",
            "PLANNED",
            "REPAIRING",
            "EVIDENCE_PENDING",
            "RESOLVED",
        ):
            assert expected in states
        assert states.index("OPEN") < states.index("PLANNED")
        assert states.index("PLANNED") < states.index("REPAIRING")
        assert states.index("REPAIRING") < states.index("EVIDENCE_PENDING")
        assert states.index("EVIDENCE_PENDING") < states.index("RESOLVED")

    _assert_downstream_locked(truth)
