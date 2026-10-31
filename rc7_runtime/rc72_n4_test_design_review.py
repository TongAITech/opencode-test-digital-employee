"""RC7.2 N4 independent Test Design review wiring.

A promoted Requirement x SST design artifact is still only a candidate.  This
adapter binds the candidate back to its raw DSH evidence anchor and chooses one
of two fail-closed review paths:

* complete candidate (no worker unknowns/gaps): run the mature independent DSH
  reviewer plus deterministic TestDesignClosedLoop;
* explicit incomplete candidate: deterministically create repair gaps without
  spending another model call or allowing an incomplete design to be reviewed
  into PASS.

A single scope review never completes N4 and never releases N5.  N4 aggregate
NodeDelivery/NodeGate remains a separate authority boundary.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_test_design_evaluator import DshTestDesignEvaluator
from .models import Evaluation, EvaluationResult, Gap, GapSeverity, TaskStatus
from .rc72_n4_test_design_anchor import install_rc72_n4_test_design_anchor_overlay


class N4TestDesignReviewError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4TestDesignReviewError(
            "RC72_N4_DESIGN_REVIEW_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _stable_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(value)


class N4TestDesignReviewService:
    """Review one promoted N4 Requirement x SST candidate without closing N4."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        evaluator: DshTestDesignEvaluator,
    ) -> None:
        install_rc72_n4_test_design_anchor_overlay()
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
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _anchor(
        self, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n4_test_design_evidence_anchor",
            release_batch_id=release_batch_id,
        )
        exact = [
            row for row in rows
            if row.get("requirement_id") == requirement_id
            and row.get("sst_id") == sst_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
            and row.get("candidate_schema") == "RC72_N4_TEST_DESIGN_CANDIDATE_V1"
        ]
        if len(exact) != 1:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d"
                % len(exact)
            )
        return exact[0]

    def _lineage(
        self, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
        anchor = self._anchor(release_batch_id, requirement_id, sst_id)
        attempt = self._one(
            "rc72_n4_test_design_attempt", attempt_id=str(anchor["attempt_id"])
        )
        assignment = self._one(
            "rc72_n4_test_design_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))

        immutable = (
            "mission_id",
            "release_batch_id",
            "source_commit",
            "requirement_id",
            "sst_id",
            "mission_node_id",
            "workitem_id",
            "worker_instance_id",
            "assignment_id",
            "dispatch_id",
        )
        for field in immutable:
            expected = anchor.get(field)
            for label, row in (("attempt", attempt), ("assignment", assignment)):
                if field in row and row.get(field) != expected:
                    raise N4TestDesignReviewError(
                        "RC72_N4_DESIGN_REVIEW_LINEAGE_MISMATCH:%s:%s"
                        % (label, field)
                    )
        if task.get("mission_id") != self.mission_id or task.get("node") != "TEST_DESIGN":
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_TASK_IDENTITY_MISMATCH"
            )
        if task.get("lease_owner") != anchor.get("worker_instance_id"):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_DESIGNER_IDENTITY_MISMATCH"
            )
        outputs = list(task.get("output_artifact_refs") or [])
        if len(outputs) != 1:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_SINGLE_CANDIDATE_REQUIRED:%d" % len(outputs)
            )
        artifact_id = str(outputs[0])
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("artifact_type_name") != "TEST_DESIGN_CANDIDATE"
            or artifact.get("producer_task_id") != task.get("task_id")
            or artifact.get("state") != "VALID"
        ):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_CANDIDATE_INVALID"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        expected_semantic = {
            "candidate_kind": "TEST_DESIGN_CANDIDATE",
            "release_batch_id": release_batch_id,
            "requirement_id": requirement_id,
            "sst_id": sst_id,
        }
        for field, expected in expected_semantic.items():
            if semantic.get(field) != expected:
                raise N4TestDesignReviewError(
                    "RC72_N4_DESIGN_REVIEW_CANDIDATE_LINEAGE_MISMATCH:%s" % field
                )
        runtime_lineage = durable.envelope.get("runtime_lineage")
        if not isinstance(runtime_lineage, dict):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_RUNTIME_LINEAGE_REQUIRED"
            )
        expected_runtime = {
            "attempt_id": anchor.get("attempt_id"),
            "assignment_id": anchor.get("assignment_id"),
            "dispatch_id": anchor.get("dispatch_id"),
            "dsh_session_id": anchor.get("dsh_session_id"),
            "raw_output_sha256": anchor.get("raw_output_sha256"),
            "evidence_anchor_id": anchor.get("anchor_id"),
            "source_commit": self.source_commit,
        }
        for field, expected in expected_runtime.items():
            if runtime_lineage.get(field) != expected:
                raise N4TestDesignReviewError(
                    "RC72_N4_DESIGN_REVIEW_RUNTIME_LINEAGE_MISMATCH:%s" % field
                )
        return anchor, task, artifact_id, semantic

    def _assert_downstream_locked(self) -> None:
        n4 = self._one(
            "rc72_mission_node",
            mission_id=self.mission_id,
            node_type="N4_TEST_DESIGN",
        )
        n5 = self._one(
            "rc72_mission_node",
            mission_id=self.mission_id,
            node_type="N5_TEST_DATA",
        )
        if n4.get("state") not in {"RUNNING", "REPAIR_REQUIRED"}:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_N4_PREMATURE_TERMINAL:%s" % n4.get("state")
            )
        if n5.get("state") != "NOT_STARTED":
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_N5_PREMATURE_RELEASE:%s" % n5.get("state")
            )
        if self.truth.query(
            "rc72_node_delivery",
            mission_id=self.mission_id,
            node_type="N4_TEST_DESIGN",
        ):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_DELIVERY_PREMATURE"
            )
        if self.truth.query(
            "rc72_node_gate",
            mission_id=self.mission_id,
            node_type="N4_TEST_DESIGN",
        ):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_NODE_GATE_PREMATURE"
            )

    def _deterministic_incomplete_review(
        self,
        *,
        artifact_id: str,
        semantic: Mapping[str, Any],
    ) -> Tuple[Evaluation, Tuple[Gap, ...]]:
        unknowns = list(semantic.get("candidate_unknowns") or [])
        explicit_gaps = list(semantic.get("candidate_gaps") or [])
        if not unknowns and not explicit_gaps:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_DETERMINISTIC_GAP_PATH_REQUIRES_GAP"
            )
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        evidence_refs = [
            str(ref) for ref in list(artifact.get("evidence_refs") or [])
            if isinstance(ref, str) and ref
        ]
        gaps: List[Gap] = []
        for kind, items, category, severity in (
            (
                "UNKNOWN",
                unknowns,
                "TEST_DESIGN_SOURCE_OBLIGATION_GAP",
                GapSeverity.BLOCKER,
            ),
            (
                "GAP",
                explicit_gaps,
                "TEST_DESIGN_REVIEW_GAP",
                GapSeverity.HIGH,
            ),
        ):
            for index, item in enumerate(items):
                detail = _stable_text(item)
                gaps.append(
                    Gap(
                        gap_id=_stable_id(
                            "GAP-N4-EXPLICIT",
                            self.mission_id,
                            artifact_id,
                            kind,
                            str(index),
                            detail,
                        ),
                        mission_id=self.mission_id,
                        source_node="TEST_DESIGN",
                        category=category,
                        severity=severity,
                        target_node="TEST_DESIGN",
                        description="N4_%s_REQUIRES_REPAIR:%s" % (kind, detail),
                        subject_refs=[
                            artifact_id,
                            str(semantic.get("requirement_id") or "UNKNOWN_REQUIREMENT"),
                            str(semantic.get("sst_id") or "UNKNOWN_SST"),
                        ],
                        evidence_refs=list(evidence_refs),
                        acceptance_criteria=[
                            "explicit N4 %s is resolved with evidence and a regenerated candidate"
                            % kind.lower()
                        ],
                    )
                )
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-N4-EXPLICIT",
                self.mission_id,
                artifact_id,
                ",".join(sorted(gap.gap_id for gap in gaps)),
            ),
            mission_id=self.mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="rc72-deterministic-n4-explicit-gap-gate",
            dimensions={
                "gate_status": "EXPLICIT_GAPS_OR_UNKNOWNS",
                "deterministic_first": True,
                "reviewer_model_invoked": False,
                "candidate_unknown_count": len(unknowns),
                "candidate_gap_count": len(explicit_gaps),
                "candidate_case_count": len(list(semantic.get("cases") or [])),
                "candidate_obligation_count": len(list(semantic.get("obligations") or [])),
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(evidence_refs),
        )
        return evaluation, tuple(gaps)

    def review(
        self, *, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        sst_id = _required(sst_id, "sst_id")
        anchor, task, artifact_id, semantic = self._lineage(
            release_batch_id, requirement_id, sst_id
        )
        state = str(task.get("state") or "")
        if state in {TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value}:
            self._assert_downstream_locked()
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "requirement_id": requirement_id,
                "sst_id": sst_id,
                "task_id": str(task["task_id"]),
                "artifact_id": artifact_id,
                "task_state": state,
                "evaluation_id": task.get("evaluation_id"),
                "designer_worker_id": str(anchor["worker_instance_id"]),
                "designer_session_id": str(anchor["dsh_session_id"]),
            }
        if state != TaskStatus.OUTPUT_PRODUCED.value:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_OUTPUT_PRODUCED_REQUIRED:%s" % state
            )

        if list(semantic.get("candidate_unknowns") or []) or list(
            semantic.get("candidate_gaps") or []
        ):
            evaluation, gaps = self._deterministic_incomplete_review(
                artifact_id=artifact_id,
                semantic=semantic,
            )
            self.control.accept_evaluation(
                str(task["task_id"]),
                evaluation=evaluation,
                gaps=gaps,
            )
            updated = self._one("rc7_task", task_id=str(task["task_id"]))
            if updated.get("state") != TaskStatus.REPAIR_REQUIRED.value:
                raise N4TestDesignReviewError(
                    "RC72_N4_DESIGN_REVIEW_EXPLICIT_GAP_MUST_REPAIR"
                )
            self._assert_downstream_locked()
            return {
                "status": "DETERMINISTIC_REPAIR_REQUIRED",
                "release_batch_id": release_batch_id,
                "requirement_id": requirement_id,
                "sst_id": sst_id,
                "task_id": str(task["task_id"]),
                "artifact_id": artifact_id,
                "task_state": str(updated["state"]),
                "evaluation_id": updated.get("evaluation_id"),
                "designer_worker_id": str(anchor["worker_instance_id"]),
                "designer_session_id": str(anchor["dsh_session_id"]),
                "reviewer_model_invoked": False,
                "gap_ids": [gap.gap_id for gap in gaps],
            }

        evaluated = self.evaluator.evaluate(
            self.control,
            str(task["task_id"]),
            artifact_id,
        )
        if evaluated.designer_worker_id != anchor.get("worker_instance_id"):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_EVALUATOR_DESIGNER_MISMATCH"
            )
        designer_session_id = _required(
            anchor.get("dsh_session_id"), "designer_session_id"
        )
        reviewer_session_id = _required(
            evaluated.reviewer_session_id, "reviewer_session_id"
        )
        if reviewer_session_id == designer_session_id:
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_FRESH_SESSION_REQUIRED"
            )
        if evaluated.reviewer_worker_id == anchor.get("worker_instance_id"):
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_INDEPENDENT_WORKER_REQUIRED"
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
            raise N4TestDesignReviewError(
                "RC72_N4_DESIGN_REVIEW_TERMINAL_TASK_STATE_INVALID:%s"
                % updated.get("state")
            )
        self._assert_downstream_locked()
        dimensions = dict(evaluated.loop_result.evaluation.dimensions)
        return {
            "status": "REVIEW_APPLIED",
            "release_batch_id": release_batch_id,
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "task_state": str(updated["state"]),
            "evaluation_id": updated.get("evaluation_id"),
            "designer_worker_id": str(anchor["worker_instance_id"]),
            "reviewer_worker_id": str(evaluated.reviewer_worker_id),
            "designer_session_id": designer_session_id,
            "reviewer_session_id": reviewer_session_id,
            "reviewer_evidence_ids": list(evaluated.reviewer_evidence_ids),
            "semantic_coverage": float(evaluated.loop_result.semantic_coverage),
            "case_count": int(evaluated.loop_result.case_count),
            "gate_status": dimensions.get("gate_status"),
            "review_gap_ids": list(dimensions.get("review_gap_ids") or []),
        }


__all__ = [
    "N4TestDesignReviewError",
    "N4TestDesignReviewService",
]
