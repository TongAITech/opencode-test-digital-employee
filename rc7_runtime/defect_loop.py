"""RC7 Defect qualification / RCA / fix verification / regression closed loop.

TEST_FAIL is not a Defect. A defect enters this lifecycle only from a trusted
PRODUCT_DEFECT execution Gap. Root cause remains an evidence-backed hypothesis
until engineering confirmation, and closure requires both fix verification and
impact regression evidence.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, List, Optional, Sequence, Tuple

from .models import Evaluation, EvaluationResult, Gap, GapSeverity


class DefectContractError(RuntimeError):
    pass


class DefectStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    QUALIFYING = "QUALIFYING"
    EVIDENCE_READY = "EVIDENCE_READY"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    CONFIRMED = "CONFIRMED"
    FIX_PENDING = "FIX_PENDING"
    FIX_DETECTED = "FIX_DETECTED"
    VERIFYING = "VERIFYING"
    FIXED = "FIXED"
    REGRESSION_TESTING = "REGRESSION_TESTING"
    CLOSED = "CLOSED"
    DUPLICATE = "DUPLICATE"
    NOT_A_DEFECT = "NOT_A_DEFECT"
    DEFERRED = "DEFERRED"
    REOPENED = "REOPENED"


@dataclass(frozen=True)
class RootCauseHypothesis:
    hypothesis_id: str
    statement: str
    suspected_symbols: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.statement:
            raise DefectContractError("RCA_HYPOTHESIS_ID_AND_STATEMENT_REQUIRED")
        if not self.evidence_refs:
            raise DefectContractError("RCA_HYPOTHESIS_EVIDENCE_REQUIRED")
        if self.confidence < 0 or self.confidence > 1:
            raise DefectContractError("RCA_HYPOTHESIS_CONFIDENCE_INVALID")


@dataclass
class DefectRecord:
    defect_id: str
    mission_id: str
    source_gap_id: str
    requirement_refs: List[str]
    test_case_ids: List[str]
    execution_attempt_ids: List[str]
    expected: Any
    actual: Any
    evidence_refs: List[str]
    severity: str = "HIGH"
    state: DefectStatus = DefectStatus.CANDIDATE
    reproduction_attempts: int = 0
    reproduction_passes: int = 0
    root_cause_hypothesis: Optional[RootCauseHypothesis] = None
    duplicate_of: Optional[str] = None
    fix_revision: Optional[str] = None
    verification_refs: List[str] = field(default_factory=list)
    regression_refs: List[str] = field(default_factory=list)
    latest_evaluation_id: Optional[str] = None
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        for name in ("defect_id", "mission_id", "source_gap_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DefectContractError("%s_REQUIRED" % name.upper())
        if not self.evidence_refs:
            raise DefectContractError("DEFECT_EVIDENCE_REQUIRED")
        if not self.test_case_ids or not self.execution_attempt_ids:
            raise DefectContractError("DEFECT_EXECUTION_TRACE_REQUIRED")
        if self.reproduction_attempts < 0 or self.reproduction_passes < 0:
            raise DefectContractError("DEFECT_REPRODUCTION_COUNTER_INVALID")
        if self.reproduction_passes > self.reproduction_attempts:
            raise DefectContractError("DEFECT_REPRODUCTION_PASS_EXCEEDS_ATTEMPTS")


@dataclass(frozen=True)
class DefectQualificationInput:
    execution_trusted: bool
    oracle_valid: bool
    evidence_complete: bool
    script_issue_excluded: bool
    data_issue_excluded: bool
    environment_issue_excluded: bool
    reproducible: bool

    def passed(self) -> bool:
        return all(asdict(self).values())


@dataclass(frozen=True)
class DefectLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    qualified: bool


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class DefectClosedLoop:
    TERMINAL = {
        DefectStatus.CLOSED,
        DefectStatus.DUPLICATE,
        DefectStatus.NOT_A_DEFECT,
        DefectStatus.DEFERRED,
    }

    _TRANSITIONS = {
        DefectStatus.CANDIDATE: {DefectStatus.QUALIFYING},
        DefectStatus.QUALIFYING: {
            DefectStatus.EVIDENCE_READY,
            DefectStatus.DUPLICATE,
            DefectStatus.NOT_A_DEFECT,
            DefectStatus.DEFERRED,
        },
        DefectStatus.EVIDENCE_READY: {DefectStatus.READY_FOR_REVIEW},
        DefectStatus.READY_FOR_REVIEW: {
            DefectStatus.CONFIRMED,
            DefectStatus.NOT_A_DEFECT,
            DefectStatus.DUPLICATE,
            DefectStatus.DEFERRED,
        },
        DefectStatus.CONFIRMED: {DefectStatus.FIX_PENDING, DefectStatus.DEFERRED},
        DefectStatus.FIX_PENDING: {DefectStatus.FIX_DETECTED, DefectStatus.DEFERRED},
        DefectStatus.FIX_DETECTED: {DefectStatus.VERIFYING},
        DefectStatus.VERIFYING: {DefectStatus.FIXED, DefectStatus.REOPENED},
        DefectStatus.FIXED: {DefectStatus.REGRESSION_TESTING},
        DefectStatus.REGRESSION_TESTING: {DefectStatus.CLOSED, DefectStatus.REOPENED},
        DefectStatus.REOPENED: {DefectStatus.FIX_PENDING, DefectStatus.DEFERRED},
        DefectStatus.CLOSED: set(),
        DefectStatus.DUPLICATE: set(),
        DefectStatus.NOT_A_DEFECT: set(),
        DefectStatus.DEFERRED: set(),
    }

    def create_candidate(
        self,
        *,
        mission_id: str,
        product_gap: Gap,
        requirement_refs: Sequence[str],
        test_case_id: str,
        execution_attempt_id: str,
        expected: Any,
        actual: Any,
        evidence_refs: Sequence[str],
        severity: str = "HIGH",
    ) -> DefectRecord:
        if product_gap.category != "PRODUCT_DEFECT" or product_gap.target_node != "DEFECT":
            raise DefectContractError("DEFECT_CANDIDATE_REQUIRES_PRODUCT_DEFECT_GAP")
        if product_gap.mission_id != mission_id:
            raise DefectContractError("DEFECT_GAP_MISSION_MISMATCH")
        evidence = list(dict.fromkeys(list(product_gap.evidence_refs) + list(evidence_refs)))
        if not evidence:
            raise DefectContractError("DEFECT_EVIDENCE_REQUIRED")
        defect_id = _stable_id("DEFECT", mission_id, product_gap.gap_id, test_case_id)
        return DefectRecord(
            defect_id=defect_id,
            mission_id=mission_id,
            source_gap_id=product_gap.gap_id,
            requirement_refs=list(dict.fromkeys(requirement_refs)),
            test_case_ids=[test_case_id],
            execution_attempt_ids=[execution_attempt_id],
            expected=expected,
            actual=actual,
            evidence_refs=evidence,
            severity=severity.upper(),
        )

    def evaluate_qualification(
        self,
        defect: DefectRecord,
        qualification: DefectQualificationInput,
        *,
        evaluator_ref: str = "rc7-defect-qualification-gate",
    ) -> DefectLoopResult:
        if defect.state != DefectStatus.QUALIFYING:
            raise DefectContractError("DEFECT_MUST_BE_QUALIFYING_BEFORE_EVALUATION")
        reasons = [name.upper() for name, value in asdict(qualification).items() if not value]
        gaps: List[Gap] = []
        if reasons:
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-DEFECT", defect.defect_id, *reasons),
                    mission_id=defect.mission_id,
                    source_node="DEFECT",
                    category="DEFECT_QUALIFICATION_INCOMPLETE",
                    severity=GapSeverity.HIGH,
                    target_node="DEFECT",
                    description="DEFECT_QUALIFICATION_INCOMPLETE:%s" % ",".join(reasons),
                    subject_refs=[defect.defect_id, defect.source_gap_id],
                    evidence_refs=list(defect.evidence_refs),
                    acceptance_criteria=["all defect qualification predicates are evidence-backed"],
                )
            )
        result = EvaluationResult.PASS if not gaps else EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-DEFECT", defect.defect_id, result.value, *reasons),
            mission_id=defect.mission_id,
            node="DEFECT",
            artifact_refs=[defect.defect_id],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={"qualification": asdict(qualification), "state": defect.state.value},
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(defect.evidence_refs),
        )
        defect.latest_evaluation_id = evaluation.evaluation_id
        if result == EvaluationResult.PASS:
            self.transition(defect, DefectStatus.EVIDENCE_READY, evaluation_id=evaluation.evaluation_id)
        return DefectLoopResult(evaluation, tuple(gaps), qualified=(result == EvaluationResult.PASS))

    def transition(
        self,
        defect: DefectRecord,
        target: DefectStatus,
        *,
        evaluation_id: str = "",
        fix_revision: str = "",
        verification_refs: Sequence[str] = (),
        regression_refs: Sequence[str] = (),
    ) -> DefectRecord:
        if target not in self._TRANSITIONS[defect.state]:
            raise DefectContractError(
                "DEFECT_TRANSITION_FORBIDDEN:%s->%s" % (defect.state.value, target.value)
            )
        if target == DefectStatus.EVIDENCE_READY:
            if not evaluation_id:
                raise DefectContractError("DEFECT_EVIDENCE_READY_REQUIRES_EVALUATION")
            defect.latest_evaluation_id = evaluation_id
        elif target == DefectStatus.READY_FOR_REVIEW:
            if not defect.latest_evaluation_id:
                raise DefectContractError("DEFECT_REVIEW_REQUIRES_QUALIFICATION_EVALUATION")
        elif target == DefectStatus.CONFIRMED:
            if not evaluation_id:
                raise DefectContractError("DEFECT_CONFIRMATION_REQUIRES_EVALUATION")
            defect.latest_evaluation_id = evaluation_id
        elif target == DefectStatus.FIX_DETECTED:
            if not fix_revision:
                raise DefectContractError("DEFECT_FIX_REVISION_REQUIRED")
            defect.fix_revision = fix_revision
        elif target == DefectStatus.FIXED:
            if not verification_refs:
                raise DefectContractError("DEFECT_FIX_VERIFICATION_EVIDENCE_REQUIRED")
            defect.verification_refs = list(dict.fromkeys(verification_refs))
        elif target == DefectStatus.CLOSED:
            if not defect.verification_refs:
                raise DefectContractError("DEFECT_CLOSE_REQUIRES_FIX_VERIFICATION")
            if not regression_refs:
                raise DefectContractError("DEFECT_CLOSE_REQUIRES_REGRESSION_EVIDENCE")
            if not evaluation_id:
                raise DefectContractError("DEFECT_CLOSE_REQUIRES_EVALUATION")
            defect.regression_refs = list(dict.fromkeys(regression_refs))
            defect.latest_evaluation_id = evaluation_id
        defect.state = target
        defect.updated_at = int(time.time())
        return defect

    @staticmethod
    def attach_root_cause_hypothesis(defect: DefectRecord, hypothesis: RootCauseHypothesis) -> DefectRecord:
        missing = [ref for ref in hypothesis.evidence_refs if ref not in defect.evidence_refs]
        defect.evidence_refs.extend(ref for ref in missing if ref not in defect.evidence_refs)
        defect.root_cause_hypothesis = hypothesis
        defect.updated_at = int(time.time())
        return defect

    @staticmethod
    def record_reproduction(
        defect: DefectRecord,
        *,
        attempt_id: str,
        reproduced: bool,
        evidence_refs: Sequence[str],
    ) -> DefectRecord:
        if not evidence_refs:
            raise DefectContractError("DEFECT_REPRODUCTION_EVIDENCE_REQUIRED")
        if attempt_id not in defect.execution_attempt_ids:
            defect.execution_attempt_ids.append(attempt_id)
        defect.reproduction_attempts += 1
        if reproduced:
            defect.reproduction_passes += 1
        for ref in evidence_refs:
            if ref not in defect.evidence_refs:
                defect.evidence_refs.append(ref)
        defect.updated_at = int(time.time())
        return defect

    @staticmethod
    def mark_duplicate(defect: DefectRecord, *, duplicate_of: str, evaluation_id: str) -> DefectRecord:
        if defect.state not in {DefectStatus.QUALIFYING, DefectStatus.READY_FOR_REVIEW}:
            raise DefectContractError("DEFECT_DUPLICATE_STATE_INVALID")
        if not duplicate_of or duplicate_of == defect.defect_id:
            raise DefectContractError("DEFECT_DUPLICATE_TARGET_INVALID")
        if not evaluation_id:
            raise DefectContractError("DEFECT_DUPLICATE_REQUIRES_EVALUATION")
        defect.duplicate_of = duplicate_of
        defect.latest_evaluation_id = evaluation_id
        defect.state = DefectStatus.DUPLICATE
        defect.updated_at = int(time.time())
        return defect

    @staticmethod
    def persist(
        truth,
        *,
        release_id: str,
        defect: DefectRecord,
        artifact_version: int = 1,
    ):
        # Local import avoids making defect lifecycle depend on the persistence
        # overlay at module import time.
        from .truth_overlay import append_entity

        return append_entity(
            truth,
            defect,
            release_id=release_id,
            artifact_version=artifact_version,
        )
