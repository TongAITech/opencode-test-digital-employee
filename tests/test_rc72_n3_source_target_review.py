from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n3_source_target_review import (
    N3SourceTargetReviewError,
    N3SourceTargetReviewService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_anchor import _attempt, _raw_path
from test_rc72_n3_source_target_handoff import APPLICATION
from test_rc72_n3_source_target_promotion import (
    _anchor,
    _assert_downstream_locked,
    _promotion,
    _rewrite_final_candidate,
)


TOOL = "source-target-review-probe"
TARGET = "SRC-TARGET-BLOAN"


def _promoted(tmp_path: Path):
    truth, _attempt_row = _attempt(tmp_path)
    _anchor(tmp_path, truth)
    promoted = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert promoted["task_state"] == "OUTPUT_PRODUCED"
    return truth, promoted


def _review_launcher(
    tmp_path: Path,
    truth,
    *,
    decision="PASS",
    reviewed_target_ids=None,
    gap_ids=None,
    include_tool=True,
    calls=None,
    fixed_session=None,
):
    dsh = tmp_path / "dsh-n3-source-review"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n3-source-review.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        session_id = fixed_session or "session-n3-source-review-%d" % counter["count"]
        output = {
            "decision": decision,
            "reviewed_target_ids": list(
                reviewed_target_ids if reviewed_target_ids is not None else [TARGET]
            ),
            "gap_ids": list(gap_ids or []),
            "summary": "independent source mapping review fixture",
        }
        events = [{"type": "session", "session_id": session_id}]
        if include_tool:
            events.append({"type": "tool_call", "tool_name": TOOL})
        events.append({"type": "final", "text": json.dumps(output, ensure_ascii=False)})
        stdout = "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n3-source-review-signing-key"),
        coordinator_instance_id="coordinator-n3-source-review",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n3-source-review"),
        command_runner=runner,
    )


def _service(tmp_path: Path, truth, launcher):
    return N3SourceTargetReviewService(
        ClosedLoopControlPlane(truth, RELEASE, MISSION),
        launcher,
        allowed_tools=[TOOL],
    )


def test_independent_source_mapping_review_passes_without_releasing_code_analysis(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    calls = {"count": 0}
    service = _service(
        tmp_path,
        truth,
        _review_launcher(tmp_path, truth, calls=calls),
    )

    first = service.review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )
    second = service.review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )

    assert first.evaluation_result == "PASS"
    assert first.task_state == "PASS"
    assert first.application_id == APPLICATION
    assert first.reviewer_worker_id
    assert first.reviewer_worker_id != truth.query(
        "rc7_task", task_id=promoted["task_id"]
    )[0]["lease_owner"]
    analyzer_attempt = truth.query(
        "rc72_n3_source_target_attempt", workitem_id=promoted["task_id"]
    )[0]
    assert first.reviewer_session_id != analyzer_attempt["dsh_session_id"]
    assert first.gap_ids == ()
    assert first.deterministic_reasons == ()
    assert second.evaluation_id == first.evaluation_id
    assert second.reviewer_worker_id == first.reviewer_worker_id
    assert calls["count"] == 1

    evaluation = truth.query(
        "rc7_evaluation", evaluation_id=first.evaluation_id
    )[0]
    assert evaluation["dimensions"]["mapping_gate"] == "PASS"
    review_evidence = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in evaluation["evidence_refs"]
        if truth.query("rc7_evidence", evidence_id=evidence_id)
        and truth.query("rc7_evidence", evidence_id=evidence_id)[0]["kind"]
        == "INDEPENDENT_SOURCE_TARGET_REVIEW_PROOF"
    ]
    assert review_evidence
    _assert_downstream_locked(truth)


def test_reviewer_gaps_force_repair_required_and_keep_n4_locked(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    result = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            decision="GAPS",
            gap_ids=["REPOSITORY_OWNERSHIP_NOT_PROVEN"],
        ),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )

    assert result.evaluation_result == "REPAIR_REQUIRED"
    assert result.task_state == "REPAIR_REQUIRED"
    assert result.gap_ids
    gaps = [truth.query("rc7_gap", gap_id=gap_id)[0] for gap_id in result.gap_ids]
    assert all(gap["category"] == "SOURCE_TARGET_MAPPING_GAP" for gap in gaps)
    assert all(gap["target_node"] == "SOURCE_TARGET_DISCOVERY" for gap in gaps)
    mission = truth.query("rc7_mission", mission_id=MISSION)[0]
    assert mission["state"] == "REPAIRING"
    _assert_downstream_locked(truth)


def test_reviewer_pass_cannot_override_ambiguous_repository_revision(tmp_path: Path):
    truth, attempt = _attempt(tmp_path)
    raw_path = _raw_path(attempt)

    def add_conflicting_target(candidate):
        first = dict(candidate["targets"][0])
        second = dict(first)
        second["target_id"] = "SRC-TARGET-BLOAN-SECOND"
        second["source_revision"] = "b" * 40
        second["evidence_refs"] = ["tool://source-target-probe/BLOAN-second"]
        candidate["targets"].append(second)

    _rewrite_final_candidate(raw_path, add_conflicting_target)
    _anchor(tmp_path, truth)
    promoted = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        application_id=APPLICATION,
    )
    assert len(promoted["targets"]) == 2

    result = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            reviewed_target_ids=[TARGET, "SRC-TARGET-BLOAN-SECOND"],
        ),
    ).review_and_apply(
        task_id=promoted["task_id"],
        artifact_id=promoted["artifact_id"],
    )

    assert result.evaluation_result == "REPAIR_REQUIRED"
    assert result.task_state == "REPAIR_REQUIRED"
    assert any(
        reason.startswith("AMBIGUOUS_REPOSITORY_REVISION:")
        for reason in result.deterministic_reasons
    )
    assert result.gap_ids
    _assert_downstream_locked(truth)


def test_source_mapping_review_requires_complete_target_coverage(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    service = _service(
        tmp_path,
        truth,
        _review_launcher(
            tmp_path,
            truth,
            reviewed_target_ids=["WRONG-TARGET"],
        ),
    )

    with pytest.raises(
        N3SourceTargetReviewError,
        match="TARGET_COVERAGE_MISMATCH",
    ):
        service.review_and_apply(
            task_id=promoted["task_id"],
            artifact_id=promoted["artifact_id"],
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["evaluation_id"] is None
    _assert_downstream_locked(truth)


def test_source_mapping_review_requires_real_tool_call(tmp_path: Path):
    truth, promoted = _promoted(tmp_path)
    service = _service(
        tmp_path,
        truth,
        _review_launcher(tmp_path, truth, include_tool=False),
    )

    with pytest.raises(
        AgentRuntimeError,
        match="REAL_TOOL_CALL_MISSING",
    ):
        service.review_and_apply(
            task_id=promoted["task_id"],
            artifact_id=promoted["artifact_id"],
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["evaluation_id"] is None
    _assert_downstream_locked(truth)
