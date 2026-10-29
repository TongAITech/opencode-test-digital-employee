"""RC7.2 evaluator-amplification audit over canonical reviewer and usage truth.

Step-7 scope is deliberately narrow. It detects repeated evaluator/reviewer
assignments for the same immutable MissionNode delivery and, when runtime usage
lineage exists, quantifies the model-token amplification.  Reviewer identity is
never inferred from agent names, prompts, stages or scope strings.

Canonical lineage is:

    rc72_reviewer_assignment
      -> rc72_worker_session(purpose=REVIEW)
      -> runtime_assignment_id / runtime_attempt_id
      -> rc72_token_usage

Missing or conflicting runtime lineage is surfaced as UNRESOLVED. UNKNOWN token
usage remains UNKNOWN rather than becoming zero.  This audit is advisory and
never suppresses mandatory review or Mission progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .rc72_model_usage import install_rc72_token_usage_overlay
from .rc72_worker_lifecycle import install_rc72_worker_lifecycle_overlay


_REVIEWER = "rc72_reviewer_assignment"
_SESSION = "rc72_worker_session"
_USAGE = "rc72_token_usage"


class EvaluatorAmplificationProofStatus(str, Enum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvaluatorAmplificationQualification:
    status: str
    reason: str
    mission_progress_allowed: bool = True


@dataclass(frozen=True)
class EvaluatorSubjectAmplification:
    mission_node_id: str
    delivery_id: str
    reviewer_assignment_count: int
    unique_reviewer_worker_count: int
    unique_reviewer_session_count: int
    resolved_usage_count: int
    measured_usage_count: int
    unknown_usage_count: int
    unresolved_usage_count: int
    measured_total_tokens: int
    total_tokens: Optional[int]
    first_review_tokens: Optional[int]
    repeated_review_tokens: Optional[int]
    token_amplification_factor: Optional[float]
    proof_status: EvaluatorAmplificationProofStatus
    review_ids: Tuple[str, ...]
    usage_ids: Tuple[str, ...]
    signals: Tuple[str, ...]
    mission_progress_allowed: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_node_id": self.mission_node_id,
            "delivery_id": self.delivery_id,
            "reviewer_assignment_count": self.reviewer_assignment_count,
            "unique_reviewer_worker_count": self.unique_reviewer_worker_count,
            "unique_reviewer_session_count": self.unique_reviewer_session_count,
            "resolved_usage_count": self.resolved_usage_count,
            "measured_usage_count": self.measured_usage_count,
            "unknown_usage_count": self.unknown_usage_count,
            "unresolved_usage_count": self.unresolved_usage_count,
            "measured_total_tokens": self.measured_total_tokens,
            "total_tokens": self.total_tokens,
            "first_review_tokens": self.first_review_tokens,
            "repeated_review_tokens": self.repeated_review_tokens,
            "token_amplification_factor": self.token_amplification_factor,
            "proof_status": self.proof_status.value,
            "review_ids": list(self.review_ids),
            "usage_ids": list(self.usage_ids),
            "signals": list(self.signals),
            "mission_progress_allowed": self.mission_progress_allowed,
        }


@dataclass(frozen=True)
class EvaluatorAmplificationReport:
    mission_id: str
    reviewer_assignment_count: int
    subject_count: int
    repeated_subject_count: int
    resolved_usage_count: int
    measured_usage_count: int
    unknown_usage_count: int
    unresolved_assignment_count: int
    measured_total_tokens: int
    total_tokens: Optional[int]
    subjects: Tuple[EvaluatorSubjectAmplification, ...]
    unresolved_assignments: Tuple[Dict[str, str], ...]
    qualification: EvaluatorAmplificationQualification

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "reviewer_assignment_count": self.reviewer_assignment_count,
            "subject_count": self.subject_count,
            "repeated_subject_count": self.repeated_subject_count,
            "resolved_usage_count": self.resolved_usage_count,
            "measured_usage_count": self.measured_usage_count,
            "unknown_usage_count": self.unknown_usage_count,
            "unresolved_assignment_count": self.unresolved_assignment_count,
            "measured_total_tokens": self.measured_total_tokens,
            "total_tokens": self.total_tokens,
            "subjects": [subject.as_dict() for subject in self.subjects],
            "unresolved_assignments": [dict(item) for item in self.unresolved_assignments],
            "qualification": {
                "status": self.qualification.status,
                "reason": self.qualification.reason,
                "mission_progress_allowed": self.qualification.mission_progress_allowed,
            },
        }


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    for artifact_type in (_REVIEWER, _SESSION, _USAGE):
        bucket = _truth.BUCKETS.get(artifact_type)
        if not bucket:
            continue
        if not hasattr(projection, bucket):
            setattr(projection, bucket, {})
        versions = getattr(projection, "_versions", None)
        if isinstance(versions, dict):
            versions.setdefault(artifact_type, {})


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("EVALUATOR_AMPLIFICATION_%s_REQUIRED" % name.upper())
    return value.strip()


class EvaluatorAmplificationAuditService:
    """Quantify repeated canonical review assignments without a Mission kill switch."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_worker_lifecycle_overlay()
        install_rc72_token_usage_overlay()
        _ensure_projection_buckets(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    @staticmethod
    def _sort_reviewers(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                int(row.get("created_at") or 0),
                str(row.get("review_id") or ""),
            ),
        )

    def _resolve_usage(self, review: Mapping[str, Any]) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
        review_id = str(review.get("review_id") or "")
        sessions = self.truth.query(_SESSION, session_id=review.get("session_id"))
        if len(sessions) != 1:
            return None, "REVIEWER_SESSION_NOT_UNIQUE:%d" % len(sessions)
        session = sessions[0]
        for actual, expected, reason in (
            (session.get("release_id"), self.release_id, "REVIEWER_SESSION_RELEASE_MISMATCH"),
            (session.get("mission_id"), review.get("mission_id"), "REVIEWER_SESSION_MISSION_MISMATCH"),
            (session.get("worker_id"), review.get("worker_id"), "REVIEWER_SESSION_WORKER_MISMATCH"),
            (session.get("mission_node_id"), review.get("mission_node_id"), "REVIEWER_SESSION_NODE_MISMATCH"),
            (session.get("delivery_id"), review.get("delivery_id"), "REVIEWER_SESSION_DELIVERY_MISMATCH"),
        ):
            if actual != expected:
                return None, reason
        if str(session.get("purpose") or "").upper() != "REVIEW":
            return None, "REVIEWER_SESSION_PURPOSE_NOT_REVIEW"

        assignment_id = session.get("runtime_assignment_id")
        attempt_id = session.get("runtime_attempt_id")
        if not isinstance(assignment_id, str) or not assignment_id.strip():
            return None, "REVIEWER_RUNTIME_ASSIGNMENT_MISSING"
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            return None, "REVIEWER_RUNTIME_ATTEMPT_MISSING"

        usages = self.truth.query(
            _USAGE,
            release_id=self.release_id,
            mission_id=review.get("mission_id"),
            assignment_id=assignment_id,
        )
        if len(usages) != 1:
            return None, "REVIEWER_TOKEN_USAGE_NOT_UNIQUE:%d" % len(usages)
        usage = usages[0]
        if usage.get("attempt_id") != attempt_id:
            return None, "REVIEWER_TOKEN_USAGE_ATTEMPT_MISMATCH"

        session_dsh = session.get("dsh_session_id")
        usage_dsh = usage.get("dsh_session_id")
        if (
            isinstance(session_dsh, str)
            and session_dsh.strip()
            and isinstance(usage_dsh, str)
            and usage_dsh.strip()
            and session_dsh != usage_dsh
        ):
            return None, "REVIEWER_TOKEN_USAGE_DSH_SESSION_MISMATCH"

        # The review_id is deliberately used only for diagnostics. Linkage itself
        # is through exact session/runtime assignment identities above.
        if not review_id:
            return None, "REVIEWER_ASSIGNMENT_ID_MISSING"
        return usage, None

    @staticmethod
    def _proof_status(
        assignment_count: int,
        usages: Sequence[Optional[Mapping[str, Any]]],
    ) -> EvaluatorAmplificationProofStatus:
        linked = [usage for usage in usages if usage is not None]
        if not linked:
            return EvaluatorAmplificationProofStatus.UNKNOWN
        measured_total = [
            usage for usage in linked
            if usage.get("observation_status") == "OBSERVED"
            and isinstance(usage.get("total_tokens"), int)
            and not isinstance(usage.get("total_tokens"), bool)
        ]
        if len(linked) == assignment_count and len(measured_total) == assignment_count:
            return EvaluatorAmplificationProofStatus.MEASURED
        if measured_total:
            return EvaluatorAmplificationProofStatus.PARTIAL
        return EvaluatorAmplificationProofStatus.UNKNOWN

    @staticmethod
    def _token_factor(total_tokens: Optional[int], first_tokens: Optional[int]) -> Optional[float]:
        if total_tokens is None or first_tokens is None or first_tokens <= 0:
            return None
        return float(total_tokens) / float(first_tokens)

    def report(self, mission_id: str) -> EvaluatorAmplificationReport:
        mission_id = _required(mission_id, "mission_id")
        reviews = self._sort_reviewers(
            self.truth.query(
                _REVIEWER,
                release_id=self.release_id,
                mission_id=mission_id,
            )
        )

        grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for review in reviews:
            node_id = _required(review.get("mission_node_id"), "mission_node_id")
            delivery_id = _required(review.get("delivery_id"), "delivery_id")
            grouped.setdefault((node_id, delivery_id), []).append(review)

        subjects: List[EvaluatorSubjectAmplification] = []
        unresolved_assignments: List[Dict[str, str]] = []

        for (node_id, delivery_id), subject_reviews in sorted(grouped.items()):
            resolved_usages: List[Optional[Mapping[str, Any]]] = []
            usage_ids: List[str] = []
            signals: List[str] = []

            for review in subject_reviews:
                usage, reason = self._resolve_usage(review)
                resolved_usages.append(usage)
                if usage is None:
                    unresolved_assignments.append({
                        "review_id": str(review.get("review_id") or ""),
                        "mission_node_id": node_id,
                        "delivery_id": delivery_id,
                        "reason": str(reason or "EVALUATOR_USAGE_LINEAGE_UNRESOLVED"),
                    })
                else:
                    usage_ids.append(str(usage.get("token_usage_id") or ""))

            assignment_count = len(subject_reviews)
            linked = [usage for usage in resolved_usages if usage is not None]
            observed = [
                usage for usage in linked
                if usage.get("observation_status") == "OBSERVED"
            ]
            unknown = [
                usage for usage in linked
                if usage.get("observation_status") != "OBSERVED"
            ]
            observed_totals: List[int] = [
                int(usage["total_tokens"])
                for usage in observed
                if isinstance(usage.get("total_tokens"), int)
                and not isinstance(usage.get("total_tokens"), bool)
            ]
            proof_status = self._proof_status(assignment_count, resolved_usages)
            total_tokens = (
                sum(observed_totals)
                if proof_status == EvaluatorAmplificationProofStatus.MEASURED
                else None
            )

            ordered_totals: List[Optional[int]] = []
            for usage in resolved_usages:
                value = None
                if (
                    usage is not None
                    and usage.get("observation_status") == "OBSERVED"
                    and isinstance(usage.get("total_tokens"), int)
                    and not isinstance(usage.get("total_tokens"), bool)
                ):
                    value = int(usage["total_tokens"])
                ordered_totals.append(value)
            first_review_tokens = ordered_totals[0] if ordered_totals else None
            repeated_review_tokens = (
                sum(int(value) for value in ordered_totals[1:] if value is not None)
                if len(ordered_totals) > 1
                and all(value is not None for value in ordered_totals[1:])
                else (0 if len(ordered_totals) == 1 else None)
            )

            worker_ids = {
                str(review.get("worker_id") or "")
                for review in subject_reviews
                if str(review.get("worker_id") or "")
            }
            session_ids = {
                str(review.get("session_id") or "")
                for review in subject_reviews
                if str(review.get("session_id") or "")
            }

            if assignment_count > 1:
                signals.append("REPEATED_EVALUATOR_ASSIGNMENT")
            if len(worker_ids) != assignment_count:
                signals.append("EVALUATOR_WORKER_REUSED")
            if len(session_ids) != assignment_count:
                signals.append("EVALUATOR_SESSION_REUSED")
            if len(linked) != assignment_count:
                signals.append("EVALUATOR_USAGE_LINEAGE_UNRESOLVED")
            if unknown:
                signals.append("EVALUATOR_TOKEN_USAGE_UNKNOWN")
            if len(observed_totals) != len(observed):
                signals.append("EVALUATOR_TOTAL_TOKENS_NOT_EXPOSED")

            subjects.append(
                EvaluatorSubjectAmplification(
                    mission_node_id=node_id,
                    delivery_id=delivery_id,
                    reviewer_assignment_count=assignment_count,
                    unique_reviewer_worker_count=len(worker_ids),
                    unique_reviewer_session_count=len(session_ids),
                    resolved_usage_count=len(linked),
                    measured_usage_count=len(observed),
                    unknown_usage_count=len(unknown),
                    unresolved_usage_count=assignment_count - len(linked),
                    measured_total_tokens=sum(observed_totals),
                    total_tokens=total_tokens,
                    first_review_tokens=first_review_tokens,
                    repeated_review_tokens=repeated_review_tokens,
                    token_amplification_factor=self._token_factor(total_tokens, first_review_tokens),
                    proof_status=proof_status,
                    review_ids=tuple(str(row.get("review_id") or "") for row in subject_reviews),
                    usage_ids=tuple(usage_ids),
                    signals=tuple(dict.fromkeys(signals)),
                    mission_progress_allowed=True,
                )
            )

        repeated_subject_count = sum(
            1 for subject in subjects if subject.reviewer_assignment_count > 1
        )
        resolved_usage_count = sum(subject.resolved_usage_count for subject in subjects)
        measured_usage_count = sum(subject.measured_usage_count for subject in subjects)
        unknown_usage_count = sum(subject.unknown_usage_count for subject in subjects)
        measured_total_tokens = sum(subject.measured_total_tokens for subject in subjects)

        if not subjects:
            total_tokens: Optional[int] = 0
            qualification = EvaluatorAmplificationQualification(
                "PASS", "NO_EVALUATOR_ASSIGNMENTS_OBSERVED", True
            )
        else:
            fully_measured = all(
                subject.proof_status == EvaluatorAmplificationProofStatus.MEASURED
                for subject in subjects
            )
            total_tokens = (
                sum(int(subject.total_tokens or 0) for subject in subjects)
                if fully_measured else None
            )
            if repeated_subject_count:
                qualification = EvaluatorAmplificationQualification(
                    "DEGRADED", "EVALUATOR_ASSIGNMENT_AMPLIFICATION_OBSERVED", True
                )
            elif not fully_measured:
                qualification = EvaluatorAmplificationQualification(
                    "UNKNOWN", "EVALUATOR_AMPLIFICATION_PROOF_INCOMPLETE", True
                )
            else:
                qualification = EvaluatorAmplificationQualification(
                    "PASS", "EVALUATOR_AMPLIFICATION_NOT_OBSERVED", True
                )

        return EvaluatorAmplificationReport(
            mission_id=mission_id,
            reviewer_assignment_count=len(reviews),
            subject_count=len(subjects),
            repeated_subject_count=repeated_subject_count,
            resolved_usage_count=resolved_usage_count,
            measured_usage_count=measured_usage_count,
            unknown_usage_count=unknown_usage_count,
            unresolved_assignment_count=len(unresolved_assignments),
            measured_total_tokens=measured_total_tokens,
            total_tokens=total_tokens,
            subjects=tuple(subjects),
            unresolved_assignments=tuple(unresolved_assignments),
            qualification=qualification,
        )
