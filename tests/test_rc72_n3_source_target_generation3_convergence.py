from pathlib import Path

from rc7_runtime.rc72_n3_source_target_revision_handoff import (
    N3SourceTargetRevisionDshHandoffService,
)
from rc7_runtime.rc72_n3_source_target_revision_review_loop import (
    N3SourceTargetRevisionReviewLoopService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_handoff import APPLICATION, TOOL, _launcher
from test_rc72_n3_source_target_promotion import _assert_downstream_locked
from test_rc72_n3_source_target_review import (
    TOOL as REVIEW_TOOL,
    _review_launcher,
)
from test_rc72_n3_source_target_revision_promotion import (
    _anchor_service,
    _promotion_service,
)
from test_rc72_n3_source_target_revision_review_loop import (
    _promoted_revision,
)


def _review_loop(tmp_path: Path, truth, launcher):
    return N3SourceTargetRevisionReviewLoopService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[REVIEW_TOOL],
    )


def test_generation2_failure_generation3_fresh_dsh_eventually_converges(tmp_path: Path):
    (
        truth,
        _initial_promoted,
        _initial_reviewed,
        revision2,
        handoff2,
        _attempt2,
        promoted2,
    ) = _promoted_revision(tmp_path)

    failed2 = _review_loop(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            decision="GAPS",
            gap_ids=["GEN2_MAPPING_STILL_AMBIGUOUS"],
            fixed_session="session-n3-source-gen2-review-fail",
        ),
    ).close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert failed2["status"] == "REVISION_SCHEDULED"
    assert failed2["evaluation_result"] == "REPAIR_REQUIRED"
    revision3 = failed2["next_revision"]
    assert revision3["revision_generation"] == 3
    assert revision3["previous_workitem_id"] == revision2["revision_workitem_id"]
    assert revision3["previous_artifact_id"] == promoted2["artifact_id"]
    assert revision3["revision_worker_instance_id"] != revision2["revision_worker_instance_id"]

    gen3_handoff = N3SourceTargetRevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-source-revision-3",
        ),
        allowed_tools=[TOOL],
    ).handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert gen3_handoff["revision_id"] == revision3["revision_id"]
    assert gen3_handoff["revision_generation"] == 3
    assert gen3_handoff["worker_instance_id"] == revision3["revision_worker_instance_id"]
    assert gen3_handoff["dsh_session_id"] == "session-n3-source-revision-3"
    assert gen3_handoff["dsh_session_id"] != handoff2["dsh_session_id"]
    assert gen3_handoff["dsh_session_id"] != failed2["reviewer_session_id"]

    anchor3 = _anchor_service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert anchor3["revision_id"] == revision3["revision_id"]
    assert anchor3["revision_generation"] == 3
    assert anchor3["attempt_id"] == gen3_handoff["attempt_id"]
    assert anchor3["raw_output_sha256"].startswith("sha256:")

    promoted3 = _promotion_service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert promoted3["revision_id"] == revision3["revision_id"]
    assert promoted3["revision_generation"] == 3
    assert promoted3["task_id"] == revision3["revision_workitem_id"]
    assert promoted3["previous_workitem_id"] == revision2["revision_workitem_id"]
    assert promoted3["previous_artifact_id"] == promoted2["artifact_id"]
    assert promoted3["task_state"] == "OUTPUT_PRODUCED"

    closed3 = _review_loop(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-source-gen3-review-pass",
        ),
    ).close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert closed3["status"] == "CLOSED"
    assert closed3["revision_id"] == revision3["revision_id"]
    assert closed3["revision_generation"] == 3
    assert closed3["revision_artifact_id"] == promoted3["artifact_id"]
    assert closed3["evaluation_result"] == "PASS"
    assert closed3["task_state"] == "PASS"
    assert closed3["next_revision"] is None
    assert closed3["reviewer_worker_id"] != revision3["revision_worker_instance_id"]
    assert closed3["reviewer_session_id"] == "session-n3-source-gen3-review-pass"
    assert closed3["reviewer_session_id"] != gen3_handoff["dsh_session_id"]

    assert set(failed2["ancestor_gap_refs"]).issubset(
        set(closed3["ancestor_gap_refs"])
    )
    assert set(failed2["new_gap_refs"]).issubset(
        set(closed3["ancestor_gap_refs"])
    )
    assert closed3["resolved_gap_refs"] == closed3["ancestor_gap_refs"]
    for gap_id in closed3["resolved_gap_refs"]:
        gap = truth.query("rc7_gap", gap_id=gap_id)[0]
        assert gap["state"] == "RESOLVED"
        assert gap["resolution_evaluation_id"] == closed3["evaluation_id"]

    revision_rows = truth.query(
        "rc72_n3_source_target_revision", release_batch_id=BATCH
    )
    assert sorted(row["revision_generation"] for row in revision_rows) == [2, 3]
    task2 = truth.query(
        "rc7_task", task_id=revision2["revision_workitem_id"]
    )[0]
    task3 = truth.query(
        "rc7_task", task_id=revision3["revision_workitem_id"]
    )[0]
    assert task2["state"] == "STALE"
    assert task3["state"] == "PASS"

    mission = truth.query("rc7_mission", mission_id=MISSION)[0]
    assert mission["state"] == "RUNNING"
    assert mission["open_gap_ids"] == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)
