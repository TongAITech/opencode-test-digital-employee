"""RC7.2 N3 code-analysis independent-review wiring.

The mature DshCodeEvaluator already reconstructs real analyzer git/codegraph
proof, launches an independent DSH reviewer, and applies the deterministic code
sufficiency gate.  This RC7.2 adapter adds the missing mission-graph trust
boundaries: exact N3 lineage, analyzer/reviewer fresh-session separation, and a
hard stop that prevents one target review from releasing N4.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_code_evaluator import DshCodeEvaluator
from .models import TaskStatus
from .rc72_n3_code_analysis_anchor import install_rc72_n3_code_analysis_anchor_overlay


class N3CodeAnalysisReviewError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisReviewError(
            "RC72_N3_CODE_REVIEW_%s_REQUIRED" % name.upper()
        )
    return value.strip()


class N3CodeAnalysisReviewService:
    """Review one promoted code target without completing N3 as a whole."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        evaluator: DshCodeEvaluator,
    ) -> None:
        install_rc72_n3_code_analysis_anchor_overlay()
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.evaluator = evaluator
        self.control = ClosedLoopControlPlane(truth, self.release_id, self.mission_id)
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _anchor(self, release_batch_id: str, target_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n3_code_analysis_evidence_anchor",
            release_batch_id=release_batch_id,
        )
        exact = [
            row for row in rows
            if row.get("target_id") == target_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
        ]
        if len(exact) != 1:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    def _lineage(
        self, release_batch_id: str, target_id: str
    ) -> tuple[Dict[str, Any], Dict[str, Any], str]:
        anchor = self._anchor(release_batch_id, target_id)
        attempt = self._one(
            "rc72_n3_code_analysis_attempt", attempt_id=str(anchor["attempt_id"])
        )
        assignment = self._one(
            "rc72_n3_code_analysis_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))
        immutable = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "application_id", "target_id", "mission_node_id", "workitem_id",
            "worker_instance_id", "assignment_id", "dispatch_id",
        )
        for field in immutable:
            expected = anchor.get(field)
            for label, row in (("attempt", attempt), ("assignment", assignment)):
                if field == "release_id" and field not in row:
                    continue
                if field in row and row.get(field) != expected:
                    raise N3CodeAnalysisReviewError(
                        "RC72_N3_CODE_REVIEW_LINEAGE_MISMATCH:%s:%s"
                        % (label, field)
                    )
        for field in (
            "repository_ref", "source_revision", "source_mapping_generation",
            "source_mapping_task_id", "source_mapping_artifact_id",
            "source_mapping_evaluation_id",
        ):
            if attempt.get(field) != assignment.get(field):
                raise N3CodeAnalysisReviewError(
                    "RC72_N3_CODE_REVIEW_ANALYSIS_TARGET_MISMATCH:%s" % field
                )
        if task.get("mission_id") != self.mission_id or task.get("node") != "CODE_ANALYSIS":
            raise N3CodeAnalysisReviewError("RC72_N3_CODE_REVIEW_TASK_IDENTITY_MISMATCH")
        if task.get("lease_owner") != anchor.get("worker_instance_id"):
            raise N3CodeAnalysisReviewError("RC72_N3_CODE_REVIEW_ANALYZER_IDENTITY_MISMATCH")
        outputs = list(task.get("output_artifact_refs") or [])
        if len(outputs) != 1:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_SINGLE_CANDIDATE_REQUIRED:%d" % len(outputs)
            )
        artifact_id = outputs[0]
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("artifact_type_name") != "CODE_ANALYSIS_CANDIDATE"
            or artifact.get("producer_task_id") != task.get("task_id")
            or artifact.get("state") != "VALID"
        ):
            raise N3CodeAnalysisReviewError("RC72_N3_CODE_REVIEW_CANDIDATE_INVALID")
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        expected_semantic = {
            "application_id": assignment.get("application_id"),
            "target_id": target_id,
            "repository_ref": assignment.get("repository_ref"),
            "source_revision": assignment.get("source_revision"),
        }
        for field, expected in expected_semantic.items():
            if semantic.get(field) != expected:
                raise N3CodeAnalysisReviewError(
                    "RC72_N3_CODE_REVIEW_CANDIDATE_LINEAGE_MISMATCH:%s" % field
                )
        return anchor, task, artifact_id

    def _assert_downstream_locked(self) -> None:
        n3 = self._one(
            "rc72_mission_node",
            mission_id=self.mission_id,
            node_type="N3_CODE_ANALYSIS",
        )
        n4 = self._one(
            "rc72_mission_node",
            mission_id=self.mission_id,
            node_type="N4_TEST_DESIGN",
        )
        if n3.get("state") not in {"RUNNING", "REPAIR_REQUIRED"}:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_N3_PREMATURE_TERMINAL:%s" % n3.get("state")
            )
        if n4.get("state") != "NOT_STARTED":
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_N4_PREMATURE_RELEASE:%s" % n4.get("state")
            )
        if self.truth.query(
            "rc72_node_delivery",
            mission_id=self.mission_id,
            node_type="N3_CODE_ANALYSIS",
        ):
            raise N3CodeAnalysisReviewError("RC72_N3_CODE_REVIEW_DELIVERY_PREMATURE")
        if self.truth.query(
            "rc72_node_gate",
            mission_id=self.mission_id,
            node_type="N3_CODE_ANALYSIS",
        ):
            raise N3CodeAnalysisReviewError("RC72_N3_CODE_REVIEW_NODE_GATE_PREMATURE")

    def review(self, *, release_batch_id: str, target_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        target_id = _required(target_id, "target_id")
        anchor, task, artifact_id = self._lineage(release_batch_id, target_id)
        state = str(task.get("state") or "")
        if state in {TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value}:
            self._assert_downstream_locked()
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "target_id": target_id,
                "task_id": str(task["task_id"]),
                "artifact_id": artifact_id,
                "task_state": state,
                "evaluation_id": task.get("evaluation_id"),
                "analyzer_worker_id": str(anchor["worker_instance_id"]),
                "analyzer_session_id": str(anchor["dsh_session_id"]),
            }
        if state != TaskStatus.OUTPUT_PRODUCED.value:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_OUTPUT_PRODUCED_REQUIRED:%s" % state
            )

        evaluated = self.evaluator.evaluate(
            self.control,
            str(task["task_id"]),
            artifact_id,
            target_id=target_id,
        )
        if evaluated.analyzer_worker_id != anchor.get("worker_instance_id"):
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_EVALUATOR_ANALYZER_MISMATCH"
            )
        reviewer_session_id = _required(
            evaluated.reviewer_session_id, "reviewer_session_id"
        )
        analyzer_session_id = _required(anchor.get("dsh_session_id"), "analyzer_session_id")
        if reviewer_session_id == analyzer_session_id:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_FRESH_SESSION_REQUIRED"
            )
        if evaluated.reviewer_worker_id == anchor.get("worker_instance_id"):
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_INDEPENDENT_WORKER_REQUIRED"
            )

        self.control.accept_evaluation(
            str(task["task_id"]),
            evaluation=evaluated.loop_result.evaluation,
            gaps=evaluated.loop_result.gaps,
        )
        updated = self._one("rc7_task", task_id=str(task["task_id"]))
        if updated.get("state") not in {
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N3CodeAnalysisReviewError(
                "RC72_N3_CODE_REVIEW_TERMINAL_TASK_STATE_INVALID:%s"
                % updated.get("state")
            )
        self._assert_downstream_locked()
        return {
            "status": "REVIEW_APPLIED",
            "release_batch_id": release_batch_id,
            "target_id": target_id,
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "task_state": str(updated["state"]),
            "evaluation_id": updated.get("evaluation_id"),
            "analyzer_worker_id": str(anchor["worker_instance_id"]),
            "reviewer_worker_id": str(evaluated.reviewer_worker_id),
            "analyzer_session_id": analyzer_session_id,
            "reviewer_session_id": reviewer_session_id,
            "reviewer_evidence_ids": list(evaluated.reviewer_evidence_ids),
            "analyzer_tool_evidence_ids": list(evaluated.analyzer_tool_evidence_ids),
            "gate_status": str(evaluated.loop_result.gate_status),
            "gate_metrics": dict(evaluated.loop_result.gate_metrics),
        }
