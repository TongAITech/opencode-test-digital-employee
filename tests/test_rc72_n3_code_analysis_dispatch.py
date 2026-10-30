from pathlib import Path
import json

import pytest

from rc7_runtime.rc72_n3_code_analysis_dispatch import (
    N3CodeAnalysisDispatchError,
    N3CodeAnalysisDispatchService,
)
from rc7_runtime.rc72_n3_source_target_revision_review_loop import (
    N3SourceTargetRevisionReviewLoopService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_anchor import _attempt, _raw_path
from test_rc72_n3_source_target_handoff import APPLICATION
from test_rc72_n3_source_target_promotion import (
    _anchor,
    _promotion,
    _rewrite_final_candidate,
)
from test_rc72_n3_source_target_review import (
    TARGET,
    TOOL as REVIEW_TOOL,
    _promoted,
    _review_launcher,
    _service as _review_service,
)
from test_rc72_n3_source_target_revision_review_loop import _promoted_revision


SECOND_TARGET = "SRC-TARGET-BLOAN-SECOND"


def _dispatch(truth):
    return N3CodeAnalysisDispatchService(
        truth,
        source_commit=COMMIT,
    )


def _accepted(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    reviewed = _review_service(
        tmp_path,
        truth,
        _review_launcher(tmp_path, truth),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "PASS"
    return truth, promoted, reviewed


def _accepted_two_targets(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def add_target(candidate):
        second = dict(candidate["targets"][0])
        second["target_id"] = SECOND_TARGET
        second["repository_ref"] = "git://repo/BLOAN-secondary"
        second["source_revision"] = "b" * 40
        second["evidence_refs"] = ["tool://source-target-probe/BLOAN-secondary"]
        candidate["targets"].append(second)

    _rewrite_final_candidate(raw_path, add_target)
    _anchor(tmp_path, truth)
    promoted = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    reviewed = _review_service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            reviewed_target_ids=[TARGET, SECOND_TARGET],
        ),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "PASS"
    return truth, promoted, reviewed


def _assert_no_execution_side_effects(truth):
    tasks = truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS")
    assert tasks
    assert all(task["state"] == "READY" for task in tasks)
    assert all(task["lease_owner"] is None for task in tasks)
    assert all(task["output_artifact_refs"] == [] for task in tasks)
    assert all(task["evaluation_id"] is None for task in tasks)
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


def test_accepted_mapping_fans_out_one_durable_code_workitem_per_target(tmp_path: Path):
    truth, promoted, reviewed = _accepted_two_targets(tmp_path)

    result = _dispatch(truth).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["node_state"] == "RUNNING"
    assert len(result["dispatch_ids"]) == 2
    assert len(result["workitem_ids"]) == 2
    assert [row["target_id"] for row in result["targets"]] == [
        TARGET,
        SECOND_TARGET,
    ]
    assert all(row["source_mapping_generation"] == 1 for row in result["targets"])
    rows = truth.query("rc72_n3_code_analysis_dispatch", release_batch_id=BATCH)
    assert len(rows) == 2
    assert {row["source_mapping_task_id"] for row in rows} == {promoted["task_id"]}
    assert {row["source_mapping_artifact_id"] for row in rows} == {promoted["artifact_id"]}
    assert {row["source_mapping_evaluation_id"] for row in rows} == {
        reviewed.evaluation_id
    }
    assert all(row["required_capabilities"] == ["code_reasoning", "code_reality"] for row in rows)
    assert {row["repository_ref"] for row in rows} == {
        "git://repo/BLOAN",
        "git://repo/BLOAN-secondary",
    }
    for row in rows:
        assert row["source_evidence_refs"]
        assert row["canonical_evidence_ids"]
        assert "worker_instance_id" not in row
        assert "attempt_id" not in row
        assert "codegraph_result" not in row
        assert "graph_evidence" not in row
    _assert_no_execution_side_effects(truth)


def test_code_dispatch_replay_is_idempotent(tmp_path: Path):
    truth, _promoted_row, _reviewed = _accepted(tmp_path)
    service = _dispatch(truth)

    first = service.dispatch(release_batch_id=BATCH)
    second = service.dispatch(release_batch_id=BATCH)

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert first["dispatch_ids"] == second["dispatch_ids"]
    assert first["workitem_ids"] == second["workitem_ids"]
    assert len(truth.query("rc72_n3_code_analysis_dispatch", release_batch_id=BATCH)) == 1
    assert len(truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS")) == 1
    _assert_no_execution_side_effects(truth)


def test_mapping_review_not_pass_blocks_code_dispatch_without_partial_tasks(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    reviewed = _review_service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            decision="GAPS",
            gap_ids=["SOURCE_MAPPING_NOT_PROVEN"],
        ),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "REPAIR_REQUIRED"

    with pytest.raises(
        N3CodeAnalysisDispatchError,
        match="LATEST_MAPPING_NOT_PASS",
    ):
        _dispatch(truth).dispatch(release_batch_id=BATCH)

    assert truth.query("rc72_n3_code_analysis_dispatch", release_batch_id=BATCH) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []


def test_tampered_accepted_mapping_candidate_blocks_code_dispatch(tmp_path: Path):
    truth, promoted, _reviewed = _accepted(tmp_path)
    artifact = truth.query("rc7_artifact", artifact_id=promoted["artifact_id"])[0]
    path = Path(str(artifact["content_ref"])[len("file://"):])
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["semantic_payload"]["targets"][0]["source_revision"] = "c" * 40
    path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")

    with pytest.raises(Exception, match="CANDIDATE_CONTENT_HASH_MISMATCH"):
        _dispatch(truth).dispatch(release_batch_id=BATCH)

    assert truth.query("rc72_n3_code_analysis_dispatch", release_batch_id=BATCH) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []


def test_generation2_pass_dispatches_from_latest_revision_not_stale_generation1(tmp_path: Path):
    (
        truth,
        initial_promoted,
        _initial_reviewed,
        revision,
        _handoff,
        _attempt_row,
        revision_promoted,
    ) = _promoted_revision(tmp_path)
    closed = N3SourceTargetRevisionReviewLoopService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        launcher=_review_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-code-dispatch-revision-review-pass",
        ),
        allowed_tools=[REVIEW_TOOL],
    ).close_latest_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert closed["evaluation_result"] == "PASS"

    result = _dispatch(truth).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["targets"][0]["source_mapping_generation"] == 2
    row = truth.query("rc72_n3_code_analysis_dispatch", release_batch_id=BATCH)[0]
    assert row["source_mapping_generation"] == 2
    assert row["source_mapping_task_id"] == revision["revision_workitem_id"]
    assert row["source_mapping_artifact_id"] == revision_promoted["artifact_id"]
    assert row["source_mapping_artifact_id"] != initial_promoted["artifact_id"]
    assert row["source_mapping_evaluation_id"] == closed["evaluation_id"]
    _assert_no_execution_side_effects(truth)
