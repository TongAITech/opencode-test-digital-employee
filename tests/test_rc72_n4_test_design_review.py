from pathlib import Path

import pytest

from rc7_runtime.dsh_test_design_evaluator import DshTestDesignEvaluator
from rc7_runtime.rc72_n4_test_design_review import (
    N4TestDesignReviewError,
    N4TestDesignReviewService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc7_dsh_test_design_evaluator import FakeDesignReviewerLauncher
from test_rc72_n4_test_design_promotion import _anchored, _service as _promotion_service


class SameSessionReviewerLauncher(FakeDesignReviewerLauncher):
    def __init__(self, session_id: str) -> None:
        super().__init__(tool_mode="full", decision="PASS")
        self.session_id = session_id

    def execute(self, assignment, prompt):
        reviewer, output = super().execute(assignment, prompt)
        reviewer.dsh_session_id = self.session_id
        reviewer.evidence_refs = ("dsh://session/%s" % self.session_id,)
        return reviewer, output


class FailIfReviewerInvoked:
    coordinator_instance_id = "coordinator-should-not-run"

    def assign(self, **_kwargs):
        raise AssertionError("explicit-gap candidate must not spend a reviewer model call")


def _promoted(tmp_path: Path, monkeypatch, *, gap=False):
    truth, scope, anchor = _anchored(tmp_path, monkeypatch, gap=gap)
    promoted = _promotion_service(tmp_path, truth).promote(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    return truth, scope, anchor, promoted


def _review_service(truth, launcher):
    return N4TestDesignReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=DshTestDesignEvaluator(launcher),
    )


def test_n4_complete_candidate_uses_fresh_independent_reviewer_then_deterministic_gate(
    tmp_path: Path, monkeypatch
):
    truth, scope, anchor, promoted = _promoted(tmp_path, monkeypatch)
    launcher = FakeDesignReviewerLauncher(tool_mode="full", decision="PASS")

    result = _review_service(truth, launcher).review(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert result["status"] == "REVIEW_APPLIED"
    assert result["task_state"] == "PASS"
    assert result["artifact_id"] == promoted["artifact_id"]
    assert result["designer_worker_id"] == anchor["worker_instance_id"]
    assert result["reviewer_worker_id"] != result["designer_worker_id"]
    assert result["designer_session_id"] == anchor["dsh_session_id"]
    assert result["reviewer_session_id"] != result["designer_session_id"]
    assert result["semantic_coverage"] == 1.0
    assert result["case_count"] >= 1
    assert len(launcher.prompts) == 1

    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "PASS"
    assert task["evaluation_id"] == result["evaluation_id"]

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_reviewer_must_use_session_fresh_from_designer(
    tmp_path: Path, monkeypatch
):
    truth, scope, anchor, promoted = _promoted(tmp_path, monkeypatch)
    launcher = SameSessionReviewerLauncher(str(anchor["dsh_session_id"]))

    with pytest.raises(
        N4TestDesignReviewError,
        match="FRESH_SESSION_REQUIRED",
    ):
        _review_service(truth, launcher).review(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n5["state"] == "NOT_STARTED"


def test_n4_explicit_gap_is_deterministically_rejected_without_reviewer_model_call(
    tmp_path: Path, monkeypatch
):
    truth, scope, anchor, promoted = _promoted(tmp_path, monkeypatch, gap=True)

    result = _review_service(truth, FailIfReviewerInvoked()).review(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert result["status"] == "DETERMINISTIC_REPAIR_REQUIRED"
    assert result["task_state"] == "REPAIR_REQUIRED"
    assert result["reviewer_model_invoked"] is False
    assert result["designer_session_id"] == anchor["dsh_session_id"]
    assert result["gap_ids"]

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "REPAIR_REQUIRED"
    assert task["evaluation_id"] == result["evaluation_id"]
    evaluation = truth.query("rc7_evaluation", evaluation_id=result["evaluation_id"])[0]
    assert evaluation["result"] == "REPAIR_REQUIRED"
    assert evaluation["dimensions"]["deterministic_first"] is True
    assert evaluation["dimensions"]["reviewer_model_invoked"] is False

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_completed_scope_review_is_idempotent_and_does_not_launch_second_reviewer(
    tmp_path: Path, monkeypatch
):
    truth, scope, _anchor, _promoted = _promoted(tmp_path, monkeypatch)
    launcher = FakeDesignReviewerLauncher(tool_mode="full", decision="PASS")
    service = _review_service(truth, launcher)

    first = service.review(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    second = service.review(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )

    assert first["status"] == "REVIEW_APPLIED"
    assert second["status"] == "RESUMED"
    assert second["task_state"] == "PASS"
    assert second["evaluation_id"] == first["evaluation_id"]
    assert len(launcher.prompts) == 1
