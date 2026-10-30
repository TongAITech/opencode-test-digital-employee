from pathlib import Path

import pytest

from rc7_runtime.rc72_n3_source_target_revision_handoff import (
    N3SourceTargetRevisionDshHandoffService,
)
from rc7_runtime.rc72_n3_source_target_revision_promotion import (
    N3SourceTargetRevisionCandidatePromotionService,
    N3SourceTargetRevisionEvidenceAnchorService,
    N3SourceTargetRevisionPromotionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_handoff import APPLICATION, TOOL, _launcher
from test_rc72_n3_source_target_promotion import _assert_downstream_locked
from test_rc72_n3_source_target_revision_handoff import _revision_ready


STATE_ROOT = "state-n3-source"


def _revision_attempt(tmp_path: Path):
    truth, promoted, reviewed, revision = _revision_ready(tmp_path)
    result = N3SourceTargetRevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-source-revision-promotion",
        ),
        allowed_tools=[TOOL],
    ).handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    attempt = truth.query(
        "rc72_n3_source_target_attempt",
        attempt_id=result["attempt_id"],
    )[0]
    return truth, promoted, reviewed, revision, result, attempt


def _anchor_service(tmp_path: Path, truth):
    return N3SourceTargetRevisionEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / STATE_ROOT),
    )


def _promotion_service(tmp_path: Path, truth):
    return N3SourceTargetRevisionCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / STATE_ROOT),
    )


def test_revision_anchor_selects_latest_generation_attempt_not_generation1(tmp_path: Path):
    truth, promoted, reviewed, revision, handoff, attempt = _revision_attempt(tmp_path)

    anchor = _anchor_service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert anchor["attempt_id"] == handoff["attempt_id"]
    assert anchor["attempt_id"] != truth.query(
        "rc72_n3_source_target_attempt",
        workitem_id=promoted["task_id"],
    )[0]["attempt_id"]
    assert anchor["assignment_id"] == revision["revision_id"]
    assert anchor["workitem_id"] == revision["revision_workitem_id"]
    assert anchor["worker_instance_id"] == revision["revision_worker_instance_id"]
    assert anchor["dsh_session_id"] == handoff["dsh_session_id"]
    assert anchor["raw_output_sha256"].startswith("sha256:")
    assert anchor["revision_generation"] == 2
    assert anchor["trigger_evaluation_id"] == reviewed.evaluation_id
    assert anchor["previous_artifact_id"] == promoted["artifact_id"]
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_DELIVERY"

    anchors = truth.query(
        "rc72_n3_dsh_evidence_anchor",
        release_batch_id=BATCH,
    )
    assert any(row["attempt_id"] == anchor["attempt_id"] for row in anchors)
    assert any(row["attempt_id"] != anchor["attempt_id"] for row in anchors)
    _assert_downstream_locked(truth)


def test_hash_bound_revision_promotes_new_candidate_with_immutable_prior_lineage(tmp_path: Path):
    truth, promoted, reviewed, revision, _handoff, _attempt = _revision_attempt(tmp_path)
    anchor = _anchor_service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    result = _promotion_service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert result["status"] == "PROMOTED"
    assert result["task_id"] == revision["revision_workitem_id"]
    assert result["revision_id"] == revision["revision_id"]
    assert result["revision_generation"] == 2
    assert result["trigger_evaluation_id"] == reviewed.evaluation_id
    assert result["previous_workitem_id"] == promoted["task_id"]
    assert result["previous_artifact_id"] == promoted["artifact_id"]
    assert result["evidence_anchor_id"] == anchor["anchor_id"]
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["artifact_id"] != promoted["artifact_id"]
    assert result["targets"]

    revision_task = truth.query(
        "rc7_task",
        task_id=revision["revision_workitem_id"],
    )[0]
    assert revision_task["state"] == "OUTPUT_PRODUCED"
    assert revision_task["output_artifact_refs"] == [result["artifact_id"]]
    previous_task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert previous_task["state"] == "STALE"

    artifact = truth.query("rc7_artifact", artifact_id=result["artifact_id"])[0]
    assert artifact["producer_task_id"] == revision["revision_workitem_id"]
    assert promoted["artifact_id"] in artifact["parent_refs"]
    assert artifact["state"] == "VALID"
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_revision_anchor_and_promotion_replay_are_idempotent(tmp_path: Path):
    truth, _promoted, _reviewed, revision, _handoff, _attempt = _revision_attempt(tmp_path)
    anchor_service = _anchor_service(tmp_path, truth)
    first_anchor = anchor_service.anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    second_anchor = anchor_service.anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert first_anchor["anchor_id"] == second_anchor["anchor_id"]

    service = _promotion_service(tmp_path, truth)
    first = service.promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    second = service.promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert first["status"] == "PROMOTED"
    assert second["status"] == "RESUMED"
    assert first["artifact_id"] == second["artifact_id"]
    assert second["revision_id"] == revision["revision_id"]
    assert second["revision_generation"] == 2
    assert len(truth.query("rc7_artifact", artifact_id=first["artifact_id"])) == 1
    _assert_downstream_locked(truth)


def test_revision_raw_bytes_changed_after_anchor_are_rejected(tmp_path: Path):
    truth, _promoted, _reviewed, revision, _handoff, _attempt = _revision_attempt(tmp_path)
    anchor = _anchor_service(tmp_path, truth).anchor(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert anchor["revision_id"] == revision["revision_id"]
    raw_ref = anchor["raw_output_ref"]
    assert raw_ref.startswith("file://")
    raw_path = Path(raw_ref[len("file://"):])
    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(
        N3SourceTargetRevisionPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _promotion_service(tmp_path, truth).promote(
            release_batch_id=BATCH,
            application_id=APPLICATION,
        )

    task = truth.query(
        "rc7_task",
        task_id=revision["revision_workitem_id"],
    )[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)
