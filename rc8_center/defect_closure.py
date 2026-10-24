"""RC8 N9 defect evidence closure.

Only an N8 PRODUCT route can create a defect candidate. A test failure alone is
never a defect. The Center persists an evidence-backed lifecycle covering
independent reproduction, qualification, RCA, deduplication, impact/severity,
review, filing, fix verification, impact regression and close/reopen.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple

from rc8_center.failure_diagnosis import FailureClassification, FailureDiagnosisRepository
from rc8_runtime.mission_nodes import MissionNodeType


class DefectClosureError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DefectClosureError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise DefectClosureError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise DefectClosureError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class DefectState(str, Enum):
    CANDIDATE = "CANDIDATE"
    REPRODUCED = "REPRODUCED"
    QUALIFIED = "QUALIFIED"
    RCA_READY = "RCA_READY"
    DEDUPED = "DEDUPED"
    DUPLICATE_LINKED = "DUPLICATE_LINKED"
    ASSESSED = "ASSESSED"
    REVIEW_ACCEPTED = "REVIEW_ACCEPTED"
    NOT_DEFECT = "NOT_DEFECT"
    FILED = "FILED"
    FIX_DETECTED = "FIX_DETECTED"
    FIX_VERIFIED = "FIX_VERIFIED"
    REGRESSION_VERIFIED = "REGRESSION_VERIFIED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class DefectSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DefectReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass(frozen=True)
class DefectCase:
    defect_case_id: str
    test_run_id: str
    route_decision_id: str
    source_observation_id: str
    source_case_id: str
    source_attempt_id: str
    state: DefectState
    candidate_evidence_refs: Tuple[str, ...]
    created_at: int
    updated_at: int
    reproduction_attempt_id: Optional[str] = None
    reproducer_ref: Optional[str] = None
    reproduction_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    qualification_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    rca_summary: Optional[str] = None
    rca_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    duplicate_of: Optional[str] = None
    dedup_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    impact_refs: Tuple[str, ...] = field(default_factory=tuple)
    impact_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    severity: Optional[DefectSeverity] = None
    review_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    external_defect_ref: Optional[str] = None
    filing_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    fix_revision_ref: Optional[str] = None
    fix_detected_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    fix_verification_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    impact_regression_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    closure_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("defect_case_id", "test_run_id", "route_decision_id", "source_observation_id", "source_case_id", "source_attempt_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.state, DefectState):
            raise DefectClosureError("DEFECT_STATE_INVALID")
        for name in ("candidate_evidence_refs", "reproduction_evidence_refs", "qualification_evidence_refs", "rca_evidence_refs", "dedup_evidence_refs", "impact_refs", "impact_evidence_refs", "review_evidence_refs", "filing_evidence_refs", "fix_detected_evidence_refs", "fix_verification_evidence_refs", "impact_regression_evidence_refs", "closure_evidence_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if not self.candidate_evidence_refs:
            raise DefectClosureError("DEFECT_CANDIDATE_REQUIRES_EVIDENCE")
        for name in ("reproduction_attempt_id", "reproducer_ref", "rca_summary", "duplicate_of", "external_defect_ref", "fix_revision_ref"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        if self.severity is not None and not isinstance(self.severity, DefectSeverity):
            raise DefectClosureError("DEFECT_SEVERITY_INVALID")
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise DefectClosureError("%s_INVALID" % name.upper())
        if self.updated_at < self.created_at:
            raise DefectClosureError("DEFECT_TIME_REGRESSION")

    @property
    def disposition_complete(self) -> bool:
        return self.state in {DefectState.CLOSED, DefectState.DUPLICATE_LINKED, DefectState.NOT_DEFECT}


class DefectClosureRepository(Protocol):
    def get_defect_case(self, defect_case_id: str) -> Optional[DefectCase]: ...
    def by_route_decision(self, route_decision_id: str) -> Optional[DefectCase]: ...
    def save_defect_case(self, value: DefectCase) -> None: ...


class MemoryDefectClosureRepository:
    def __init__(self) -> None:
        self.values: Dict[str, DefectCase] = {}

    def get_defect_case(self, defect_case_id: str) -> Optional[DefectCase]:
        return self.values.get(defect_case_id)

    def by_route_decision(self, route_decision_id: str) -> Optional[DefectCase]:
        matches = [value for value in self.values.values() if value.route_decision_id == route_decision_id]
        if len(matches) > 1:
            raise DefectClosureError("MULTIPLE_DEFECT_CASES_FOR_ROUTE")
        return matches[0] if matches else None

    def save_defect_case(self, value: DefectCase) -> None:
        existing = self.by_route_decision(value.route_decision_id)
        if existing is not None and existing.defect_case_id != value.defect_case_id:
            raise DefectClosureError("DEFECT_ROUTE_ALREADY_LINKED")
        self.values[value.defect_case_id] = value


class CenterDefectClosureService:
    def __init__(self, repository: DefectClosureRepository, diagnosis_repository: FailureDiagnosisRepository, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.diagnosis_repository = diagnosis_repository
        self.now_fn = now_fn or (lambda: int(time.time()))

    def create_candidate(self, *, defect_case_id: str, route_decision_id: str, evidence_refs: Sequence[str]) -> DefectCase:
        route = self.diagnosis_repository.get_route(route_decision_id)
        if route is None:
            raise DefectClosureError("N9_REQUIRES_N8_ROUTE")
        if route.classification != FailureClassification.PRODUCT or route.target_mission_node != MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE or route.repairable:
            raise DefectClosureError("N9_REQUIRES_PRODUCT_ROUTE")
        observation = self.diagnosis_repository.get_observation(route.observation_id)
        if observation is None:
            raise DefectClosureError("N9_SOURCE_OBSERVATION_NOT_FOUND")
        existing = self.repository.by_route_decision(route_decision_id)
        if existing is not None:
            return existing
        now = int(self.now_fn())
        value = DefectCase(defect_case_id=defect_case_id, test_run_id=route.test_run_id, route_decision_id=route.decision_id, source_observation_id=observation.observation_id, source_case_id=observation.source_case_id, source_attempt_id=observation.source_attempt_id, state=DefectState.CANDIDATE, candidate_evidence_refs=tuple(evidence_refs) + tuple(route.evidence_refs), created_at=now, updated_at=now)
        return self._save(value)

    def reproduce(self, defect_case_id: str, *, reproduction_attempt_id: str, reproducer_ref: str, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.CANDIDATE})
        reproduction_attempt_id = _required(reproduction_attempt_id, "reproduction_attempt_id")
        if reproduction_attempt_id == current.source_attempt_id:
            raise DefectClosureError("INDEPENDENT_REPRODUCTION_REQUIRES_NEW_ATTEMPT")
        evidence = self._require_evidence(evidence_refs, "DEFECT_REPRODUCTION_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.REPRODUCED, reproduction_attempt_id=reproduction_attempt_id, reproducer_ref=_required(reproducer_ref, "reproducer_ref"), reproduction_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def qualify(self, defect_case_id: str, *, qualified: bool, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.REPRODUCED})
        if not isinstance(qualified, bool):
            raise DefectClosureError("DEFECT_QUALIFICATION_INVALID")
        evidence = self._require_evidence(evidence_refs, "DEFECT_QUALIFICATION_REQUIRES_EVIDENCE")
        target = DefectState.QUALIFIED if qualified else DefectState.NOT_DEFECT
        return self._save(replace(current, state=target, qualification_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def record_rca(self, defect_case_id: str, *, rca_summary: str, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.QUALIFIED})
        evidence = self._require_evidence(evidence_refs, "DEFECT_RCA_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.RCA_READY, rca_summary=_required(rca_summary, "rca_summary"), rca_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def deduplicate(self, defect_case_id: str, *, evidence_refs: Sequence[str], duplicate_of: Optional[str] = None) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.RCA_READY})
        evidence = self._require_evidence(evidence_refs, "DEFECT_DEDUP_REQUIRES_EVIDENCE")
        if duplicate_of is not None:
            return self._save(replace(current, state=DefectState.DUPLICATE_LINKED, duplicate_of=_required(duplicate_of, "duplicate_of"), dedup_evidence_refs=evidence, updated_at=int(self.now_fn())))
        return self._save(replace(current, state=DefectState.DEDUPED, dedup_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def assess(self, defect_case_id: str, *, severity: DefectSeverity, impact_refs: Sequence[str], evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.DEDUPED})
        if not isinstance(severity, DefectSeverity):
            raise DefectClosureError("DEFECT_SEVERITY_INVALID")
        impacts = _refs(impact_refs, "impact_refs")
        if not impacts:
            raise DefectClosureError("DEFECT_IMPACT_REQUIRED")
        evidence = self._require_evidence(evidence_refs, "DEFECT_ASSESSMENT_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.ASSESSED, severity=severity, impact_refs=impacts, impact_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def review(self, defect_case_id: str, *, decision: DefectReviewDecision, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.ASSESSED})
        if not isinstance(decision, DefectReviewDecision):
            raise DefectClosureError("DEFECT_REVIEW_DECISION_INVALID")
        evidence = self._require_evidence(evidence_refs, "DEFECT_REVIEW_REQUIRES_EVIDENCE")
        target = DefectState.REVIEW_ACCEPTED if decision == DefectReviewDecision.ACCEPT else DefectState.NOT_DEFECT
        return self._save(replace(current, state=target, review_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def file(self, defect_case_id: str, *, external_defect_ref: str, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.REVIEW_ACCEPTED})
        evidence = self._require_evidence(evidence_refs, "DEFECT_FILING_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.FILED, external_defect_ref=_required(external_defect_ref, "external_defect_ref"), filing_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def detect_fix(self, defect_case_id: str, *, fix_revision_ref: str, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.FILED, DefectState.REOPENED})
        evidence = self._require_evidence(evidence_refs, "DEFECT_FIX_DETECTION_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.FIX_DETECTED, fix_revision_ref=_required(fix_revision_ref, "fix_revision_ref"), fix_detected_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def verify_fix(self, defect_case_id: str, *, passed: bool, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.FIX_DETECTED})
        if not isinstance(passed, bool):
            raise DefectClosureError("FIX_VERIFICATION_RESULT_INVALID")
        evidence = self._require_evidence(evidence_refs, "FIX_VERIFICATION_REQUIRES_EVIDENCE")
        target = DefectState.FIX_VERIFIED if passed else DefectState.REOPENED
        return self._save(replace(current, state=target, fix_verification_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def record_impact_regression(self, defect_case_id: str, *, passed: bool, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.FIX_VERIFIED})
        if not isinstance(passed, bool):
            raise DefectClosureError("IMPACT_REGRESSION_RESULT_INVALID")
        evidence = self._require_evidence(evidence_refs, "IMPACT_REGRESSION_REQUIRES_EVIDENCE")
        target = DefectState.REGRESSION_VERIFIED if passed else DefectState.REOPENED
        return self._save(replace(current, state=target, impact_regression_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def close(self, defect_case_id: str, *, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.REGRESSION_VERIFIED})
        evidence = self._require_evidence(evidence_refs, "DEFECT_CLOSE_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.CLOSED, closure_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def reopen(self, defect_case_id: str, *, evidence_refs: Sequence[str]) -> DefectCase:
        current = self._require_state(defect_case_id, {DefectState.CLOSED})
        evidence = self._require_evidence(evidence_refs, "DEFECT_REOPEN_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=DefectState.REOPENED, closure_evidence_refs=current.closure_evidence_refs + evidence, updated_at=int(self.now_fn())))

    def _get(self, defect_case_id: str) -> DefectCase:
        value = self.repository.get_defect_case(_required(defect_case_id, "defect_case_id"))
        if value is None:
            raise DefectClosureError("DEFECT_CASE_NOT_FOUND")
        return value

    def _require_state(self, defect_case_id: str, allowed) -> DefectCase:
        value = self._get(defect_case_id)
        if value.state not in allowed:
            raise DefectClosureError("DEFECT_STATE_FORBIDS_TRANSITION:%s" % value.state.value)
        return value

    @staticmethod
    def _require_evidence(values: Sequence[str], message: str) -> Tuple[str, ...]:
        evidence = _refs(values, "evidence_refs")
        if not evidence:
            raise DefectClosureError(message)
        return evidence

    def _save(self, value: DefectCase) -> DefectCase:
        self.repository.save_defect_case(value)
        return value
