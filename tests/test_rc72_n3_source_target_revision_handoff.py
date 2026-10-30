from pathlib import Path

import pytest

from rc7_runtime.rc72_n3_source_target_revision import N3SourceTargetRevisionService
from rc7_runtime.rc72_n3_source_target_revision_handoff import (
    N3SourceTargetRevisionDshHandoffService,
    validate_rc72_n3_source_target_revision_attempt_link,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n3_source_target_handoff import APPLICATION, TOOL, _launcher
from test_rc72_n3_source_target_promotion import _assert_downstream_locked
from test_rc72_n3_source_target_revision import _repair_required


def _revision_ready(tmp_path: Path):
    truth, promoted, reviewed = _repair_required(tmp_path)
    planned = N3SourceTargetRevisionService(
        truth, source_commit=COMMIT
    ).plan_and_assign(release_batch_id=BATCH)
    assert planned["status"] == "ASSIGNED"
    assert len(planned["revisions"]) == 1
    revision = planned["revisions"][0]
    assert revision["revision_generation"] == 2
    return truth, promoted, reviewed, revision


def test_generation2_revision_runs_in_fresh_dsh_session_and_binds_attempt_lineage(tmp_path: Path):
    truth, promoted, reviewed, revision = _revision_ready(tmp_path)
    original_attempt = truth.query(
        "rc72_n3_source_target_attempt", workitem_id=promoted["task_id"]
    )[0]
    calls = {"count": 0}
    service = N3SourceTargetRevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            calls=calls,
            fixed_session="session-n3-source-revision-2",
        ),
        allowed_tools=[TOOL],
    )

    result = service.handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert calls["count"] == 1
    assert result["status"] == "SESSION_OBSERVED"
    assert result["revision_id"] == revision["revision_id"]
    assert result["revision_generation"] == 2
    assert result["dsh_session_id"] == "session-n3-source-revision-2"
    assert result["dsh_session_id"] != original_attempt["dsh_session_id"]
    assert result["worker_instance_id"] == revision["revision_worker_instance_id"]

    attempt = truth.query(
        "rc72_n3_source_target_attempt", attempt_id=result["attempt_id"]
    )[0]
    assert attempt["assignment_id"] == revision["revision_id"]
    assert attempt["workitem_id"] == revision["revision_workitem_id"]
    assert attempt["worker_instance_id"] == revision["revision_worker_instance_id"]
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    assert attempt["observed_tool_calls"][0]["tool_name"] == TOOL
    assert any(ref.startswith("file://") for ref in attempt["runtime_evidence_refs"])
    for forbidden in ("targets", "repository_ref", "source_revision", "code_analysis_result"):
        assert forbidden not in attempt

    link = truth.query(
        "rc72_n3_source_target_revision_attempt_link",
        link_id=result["revision_attempt_link_id"],
    )[0]
    assert link["revision_id"] == revision["revision_id"]
    assert link["revision_generation"] == 2
    assert link["trigger_evaluation_id"] == reviewed.evaluation_id
    assert link["previous_workitem_id"] == promoted["task_id"]
    assert link["previous_artifact_id"] == promoted["artifact_id"]
    assert link["revision_workitem_id"] == revision["revision_workitem_id"]
    assert link["revision_worker_instance_id"] == revision["revision_worker_instance_id"]
    assert link["attempt_id"] == result["attempt_id"]
    assert link["dsh_session_id"] == result["dsh_session_id"]

    revision_task = truth.query(
        "rc7_task", task_id=revision["revision_workitem_id"]
    )[0]
    assert revision_task["state"] == "LEASED"
    assert revision_task["lease_owner"] == revision["revision_worker_instance_id"]
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    _assert_downstream_locked(truth)


def test_generation2_revision_handoff_replay_does_not_launch_second_dsh_session(tmp_path: Path):
    truth, _promoted, _reviewed, revision = _revision_ready(tmp_path)
    calls = {"count": 0}
    service = N3SourceTargetRevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            calls=calls,
            fixed_session="session-n3-source-revision-replay",
        ),
        allowed_tools=[TOOL],
    )

    first = service.handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    second = service.handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert first["revision_attempt_link_id"] == second["revision_attempt_link_id"]
    assert first["revision_id"] == revision["revision_id"]
    assert calls["count"] == 1
    assert len(truth.query(
        "rc72_n3_source_target_revision_attempt_link",
        revision_id=revision["revision_id"],
    )) == 1
    _assert_downstream_locked(truth)


def test_revision_attempt_link_rejects_source_truth_and_downstream_claim_smuggling(tmp_path: Path):
    truth, _promoted, _reviewed, _revision = _revision_ready(tmp_path)
    result = N3SourceTargetRevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            fixed_session="session-n3-source-revision-contract",
        ),
        allowed_tools=[TOOL],
    ).handoff_revision(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    row = dict(truth.query(
        "rc72_n3_source_target_revision_attempt_link",
        link_id=result["revision_attempt_link_id"],
    )[0])

    for field, value in (
        ("repository_ref", "git://guessed/repo"),
        ("source_revision", "deadbeef"),
        ("targets", ["fake"]),
        ("code_analysis_result", "PASS"),
        ("node_pass", True),
    ):
        tampered = dict(row)
        tampered[field] = value
        with pytest.raises(Exception, match="TRUTH_CLAIM_FORBIDDEN:%s" % field):
            validate_rc72_n3_source_target_revision_attempt_link(tampered)
