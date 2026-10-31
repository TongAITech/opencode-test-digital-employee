from pathlib import Path

import pytest

from rc7_runtime.code_loop import CodeLoopResult
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluation
from rc7_runtime.models import Evaluation, EvaluationResult
from rc7_runtime.rc72_n3_code_analysis_review import (
    N3CodeAnalysisReviewError,
    N3CodeAnalysisReviewService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_code_analysis_anchor import _attempt
from test_rc72_n3_code_analysis_promotion import _anchor, _promotion


class StubEvaluator:
    def __init__(
        self,
        *,
        reviewer_session_id="session-review-fresh",
        reviewer_worker_id="worker-code-review-fresh",
        analyzer_worker_id=None,
    ):
        self.reviewer_session_id = reviewer_session_id
        self.reviewer_worker_id = reviewer_worker_id
        self.analyzer_worker_id = analyzer_worker_id
        self.calls = 0

    def evaluate(self, control, task_id, artifact_id, *, target_id):
        self.calls += 1
        task = control.scheduler.task(task_id)
        analyzer_worker_id = self.analyzer_worker_id or str(task.lease_owner)
        evaluation = Evaluation(
            evaluation_id="EVAL-RC72-N3-CODE-%s" % target_id,
            mission_id=MISSION,
            node="CODE_ANALYSIS",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="dsh:%s+deterministic-code-gate" % self.reviewer_worker_id,
            dimensions={
                "gate_status": "SUFFICIENT",
                "metrics": {"stub": True},
                "reasons": [],
                "target_id": target_id,
            },
            gap_refs=[],
            evidence_refs=[],
        )
        loop_result = CodeLoopResult(
            evaluation=evaluation,
            gaps=(),
            gate_status="SUFFICIENT",
            gate_metrics={"stub": True},
        )
        return DshCodeEvaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            target_id=target_id,
            analyzer_worker_id=analyzer_worker_id,
            reviewer_worker_id=self.reviewer_worker_id,
            reviewer_session_id=self.reviewer_session_id,
            analyzer_tool_evidence_ids=("EVD-ANALYZER",),
            reviewer_evidence_ids=("EVD-REVIEWER",),
            analysis={},
            review={},
            loop_result=loop_result,
        )


def _ready_for_review(tmp_path: Path):
    truth, assignment, _attempt_row = _attempt(tmp_path)
    anchor = _anchor(tmp_path, truth, assignment)
    promoted = _promotion(tmp_path, truth).promote(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    return truth, assignment, anchor, promoted


def _service(truth, evaluator):
    return N3CodeAnalysisReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=evaluator,
    )


def _assert_node_not_released(truth):
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


def test_fresh_independent_reviewer_can_apply_target_pass_without_releasing_n4(
    tmp_path: Path,
):
    truth, assignment, anchor, promoted = _ready_for_review(tmp_path)
    evaluator = StubEvaluator()

    result = _service(truth, evaluator).review(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert result["status"] == "REVIEW_APPLIED"
    assert result["task_id"] == promoted["task_id"]
    assert result["artifact_id"] == promoted["artifact_id"]
    assert result["task_state"] == "PASS"
    assert result["analyzer_worker_id"] == anchor["worker_instance_id"]
    assert result["analyzer_session_id"] == anchor["dsh_session_id"]
    assert result["reviewer_worker_id"] == "worker-code-review-fresh"
    assert result["reviewer_session_id"] == "session-review-fresh"
    assert result["reviewer_session_id"] != result["analyzer_session_id"]
    assert result["gate_status"] == "SUFFICIENT"
    assert evaluator.calls == 1
    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "PASS"
    assert task["evaluation_id"] == result["evaluation_id"]
    _assert_node_not_released(truth)


def test_same_dsh_session_is_fail_closed_before_evaluation_application(tmp_path: Path):
    truth, assignment, anchor, promoted = _ready_for_review(tmp_path)
    evaluator = StubEvaluator(reviewer_session_id=anchor["dsh_session_id"])

    with pytest.raises(
        N3CodeAnalysisReviewError,
        match="FRESH_SESSION_REQUIRED",
    ):
        _service(truth, evaluator).review(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["evaluation_id"] is None
    assert evaluator.calls == 1
    _assert_node_not_released(truth)


def test_evaluator_cannot_switch_analyzer_identity(tmp_path: Path):
    truth, assignment, _anchor_row, promoted = _ready_for_review(tmp_path)
    evaluator = StubEvaluator(analyzer_worker_id="worker-not-the-analyzer")

    with pytest.raises(
        N3CodeAnalysisReviewError,
        match="EVALUATOR_ANALYZER_MISMATCH",
    ):
        _service(truth, evaluator).review(
            release_batch_id=BATCH,
            target_id=assignment["target_id"],
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    assert task["evaluation_id"] is None
    _assert_node_not_released(truth)


def test_review_resume_does_not_launch_a_second_reviewer(tmp_path: Path):
    truth, assignment, _anchor_row, promoted = _ready_for_review(tmp_path)
    evaluator = StubEvaluator()
    service = _service(truth, evaluator)
    first = service.review(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )
    second = service.review(
        release_batch_id=BATCH,
        target_id=assignment["target_id"],
    )

    assert first["status"] == "REVIEW_APPLIED"
    assert second["status"] == "RESUMED"
    assert second["task_state"] == "PASS"
    assert second["evaluation_id"] == first["evaluation_id"]
    assert evaluator.calls == 1
    _assert_node_not_released(truth)
