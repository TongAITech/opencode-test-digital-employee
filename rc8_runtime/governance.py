"""RC8 no-discount runtime governance domain.

This module turns the frozen design contracts into executable invariants.  It
separates tool capability truth from stage/layer/mission sufficiency and release
policy, and provides append-only Mission/Attempt/Gap/Coverage primitives.

Python 3.8 compatible by design for the target bank environment.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .contracts import RC8ContractError


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    result: List[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


class StatusScope(str, Enum):
    TOOL = "TOOL"
    STAGE = "STAGE"
    LAYER = "LAYER"
    MISSION = "MISSION"
    RELEASE = "RELEASE"


class ClaimState(str, Enum):
    OPEN = "OPEN"
    IMPLEMENTED = "IMPLEMENTED"
    CI_VERIFIED = "CI_VERIFIED"
    REALITY_VERIFIED = "REALITY_VERIFIED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    SUFFICIENT = "SUFFICIENT"
    BLOCKED = "BLOCKED"
    HOLD = "HOLD"
    PASS = "PASS"


class StageState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    LEASED = "LEASED"
    EXECUTING = "EXECUTING"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    EVALUATING = "EVALUATING"
    INSUFFICIENT = "INSUFFICIENT"
    SUFFICIENT = "SUFFICIENT"
    BLOCKED = "BLOCKED"
    WAITING_HUMAN = "WAITING_HUMAN"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"
    FAILED_RUNTIME = "FAILED_RUNTIME"
    COMPLETED = "COMPLETED"


class AttemptStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED_RUNTIME = "FAILED_RUNTIME"
    BLOCKED = "BLOCKED"


class GapSeverity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    ROUTED = "ROUTED"
    REPAIRING = "REPAIRING"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class GapType(str, Enum):
    REQUIREMENT_UNCLEAR = "REQUIREMENT_UNCLEAR"
    CODE_UNCERTAIN = "CODE_UNCERTAIN"
    DESIGN_GAP = "DESIGN_GAP"
    COVERAGE_GAP = "COVERAGE_GAP"
    SCRIPT = "SCRIPT"
    SPEC = "SPEC"
    ORACLE = "ORACLE"
    TEST_DATA = "TEST_DATA"
    PRECONDITION = "PRECONDITION"
    AUTH = "AUTH"
    ROUTE = "ROUTE"
    ENVIRONMENT = "ENVIRONMENT"
    DEPENDENCY = "DEPENDENCY"
    TOOL = "TOOL"
    MODEL = "MODEL"
    SESSION_RUNTIME = "SESSION_RUNTIME"
    FLAKY = "FLAKY"
    PRODUCT_DEFECT_LINKED = "PRODUCT_DEFECT_LINKED"
    UNKNOWN = "UNKNOWN"


class FailureOwnership(str, Enum):
    PRODUCT = "PRODUCT"
    SCRIPT = "SCRIPT"
    SPEC = "SPEC"
    ORACLE = "ORACLE"
    DATA = "DATA"
    AUTH = "AUTH"
    ROUTE = "ROUTE"
    ENVIRONMENT = "ENVIRONMENT"
    DEPENDENCY = "DEPENDENCY"
    FLAKY = "FLAKY"
    TOOL = "TOOL"
    MODEL = "MODEL"
    SESSION_RUNTIME = "SESSION_RUNTIME"
    UNKNOWN = "UNKNOWN"


class CoverageDimension(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    BR = "BR"
    SR = "SR"
    TR = "TR"
    RISK = "RISK"
    VERIFICATION_POINT = "VERIFICATION_POINT"
    CHANGED_METHOD = "CHANGED_METHOD"
    CHANGED_LINE = "CHANGED_LINE"
    CHANGED_BRANCH = "CHANGED_BRANCH"
    API = "API"
    BUSINESS_FLOW = "BUSINESS_FLOW"
    STATE_TRANSITION = "STATE_TRANSITION"
    PERMISSION = "PERMISSION"
    TEST_DATA = "TEST_DATA"
    E2E_JOURNEY = "E2E_JOURNEY"
    PERFORMANCE_NFR = "PERFORMANCE_NFR"
    SECURITY_THREAT = "SECURITY_THREAT"
    ORACLE_ASSERTION = "ORACLE_ASSERTION"
    MUTATION_STRENGTH = "MUTATION_STRENGTH"


class SufficiencyResult(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    BASELINE_ONLY = "BASELINE_ONLY"
    BLOCKED = "BLOCKED"


class ReleaseDecision(str, Enum):
    PASS = "PASS"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"


_ALLOWED_CLAIM_STATES = {
    StatusScope.TOOL: {
        ClaimState.OPEN,
        ClaimState.IMPLEMENTED,
        ClaimState.CI_VERIFIED,
        ClaimState.REALITY_VERIFIED,
        ClaimState.PARTIAL,
        ClaimState.BLOCKED,
    },
    StatusScope.STAGE: {
        ClaimState.OPEN,
        ClaimState.IMPLEMENTED,
        ClaimState.CI_VERIFIED,
        ClaimState.REALITY_VERIFIED,
        ClaimState.PARTIAL,
        ClaimState.INSUFFICIENT,
        ClaimState.SUFFICIENT,
        ClaimState.BLOCKED,
    },
    StatusScope.LAYER: {
        ClaimState.OPEN,
        ClaimState.IMPLEMENTED,
        ClaimState.CI_VERIFIED,
        ClaimState.REALITY_VERIFIED,
        ClaimState.PARTIAL,
        ClaimState.INSUFFICIENT,
        ClaimState.SUFFICIENT,
        ClaimState.BLOCKED,
    },
    StatusScope.MISSION: {
        ClaimState.OPEN,
        ClaimState.PARTIAL,
        ClaimState.INSUFFICIENT,
        ClaimState.SUFFICIENT,
        ClaimState.BLOCKED,
    },
    StatusScope.RELEASE: {ClaimState.HOLD, ClaimState.PASS, ClaimState.BLOCKED},
}


@dataclass(frozen=True)
class ScopedStatusClaim:
    scope: StatusScope
    subject_id: str
    state: ClaimState
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    reality_refs: Tuple[str, ...] = field(default_factory=tuple)
    evaluator_ref: Optional[str] = None
    coverage_refs: Tuple[str, ...] = field(default_factory=tuple)
    unresolved_gap_ids: Tuple[str, ...] = field(default_factory=tuple)
    dependency_claim_refs: Tuple[str, ...] = field(default_factory=tuple)
    recorded_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, StatusScope):
            raise RC8ContractError("STATUS_SCOPE_INVALID")
        if not isinstance(self.state, ClaimState):
            raise RC8ContractError("CLAIM_STATE_INVALID")
        object.__setattr__(self, "subject_id", _required(self.subject_id, "subject_id"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "reality_refs", _refs(self.reality_refs, "reality_refs"))
        object.__setattr__(self, "coverage_refs", _refs(self.coverage_refs, "coverage_refs"))
        object.__setattr__(self, "unresolved_gap_ids", _refs(self.unresolved_gap_ids, "unresolved_gap_ids"))
        object.__setattr__(self, "dependency_claim_refs", _refs(self.dependency_claim_refs, "dependency_claim_refs"))
        if self.evaluator_ref is not None:
            object.__setattr__(self, "evaluator_ref", _required(self.evaluator_ref, "evaluator_ref"))
        if self.state not in _ALLOWED_CLAIM_STATES[self.scope]:
            raise RC8ContractError("CLAIM_STATE_NOT_ALLOWED_FOR_SCOPE:%s:%s" % (self.scope.value, self.state.value))

        # Reality is an explicit, scoped proof. CI or presence cannot fabricate it.
        if self.state == ClaimState.REALITY_VERIFIED:
            if not self.evidence_refs or not self.reality_refs:
                raise RC8ContractError("REALITY_VERIFIED_REQUIRES_REALITY_EVIDENCE")

        # Sufficiency always comes from an evaluator, never from execution-green.
        if self.state == ClaimState.SUFFICIENT:
            if self.scope not in {StatusScope.STAGE, StatusScope.LAYER, StatusScope.MISSION}:
                raise RC8ContractError("SUFFICIENT_SCOPE_INVALID")
            if not self.evaluator_ref or not self.evidence_refs:
                raise RC8ContractError("SUFFICIENT_REQUIRES_EVALUATOR_AND_EVIDENCE")
            if self.unresolved_gap_ids:
                raise RC8ContractError("SUFFICIENT_REQUIRES_ZERO_UNRESOLVED_GAPS")
            if self.scope == StatusScope.LAYER and not self.coverage_refs:
                raise RC8ContractError("LAYER_SUFFICIENT_REQUIRES_COVERAGE")
            if self.scope == StatusScope.MISSION and not self.dependency_claim_refs:
                raise RC8ContractError("MISSION_SUFFICIENT_REQUIRES_STAGE_LAYER_CLAIMS")

        if self.scope == StatusScope.RELEASE and self.state == ClaimState.PASS:
            if not self.evidence_refs or not self.dependency_claim_refs:
                raise RC8ContractError("RELEASE_PASS_REQUIRES_MISSION_EVIDENCE")


@dataclass(frozen=True)
class CoverageMetric:
    metric_id: str
    dimension: CoverageDimension
    covered: int
    total: int
    threshold: float
    evidence_refs: Tuple[str, ...]
    critical: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _required(self.metric_id, "metric_id"))
        if not isinstance(self.dimension, CoverageDimension):
            raise RC8ContractError("COVERAGE_DIMENSION_INVALID")
        if not isinstance(self.covered, int) or not isinstance(self.total, int) or self.covered < 0 or self.total < 0:
            raise RC8ContractError("COVERAGE_COUNTS_INVALID")
        if self.covered > self.total:
            raise RC8ContractError("COVERAGE_COVERED_EXCEEDS_TOTAL")
        if not isinstance(self.threshold, (int, float)) or self.threshold < 0.0 or self.threshold > 1.0:
            raise RC8ContractError("COVERAGE_THRESHOLD_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if self.total > 0 and not self.evidence_refs:
            raise RC8ContractError("COVERAGE_REQUIRES_EVIDENCE")

    @property
    def ratio(self) -> float:
        # Empty frozen denominators are UNKNOWN, never full coverage.
        if self.total == 0:
            return 0.0
        return float(self.covered) / float(self.total)

    @property
    def satisfied(self) -> bool:
        # Fail closed even when threshold is zero: UNKNOWN cannot be SUFFICIENT.
        if self.total == 0:
            return False
        return self.ratio >= float(self.threshold)


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    test_run_id: str
    stage_instance_id: str
    work_item_id: str
    producer_node_id: str
    producer_ref: str
    input_snapshot_ref: str
    status: AttemptStatus
    case_id: Optional[str] = None
    action_refs: Tuple[str, ...] = field(default_factory=tuple)
    assertion_refs: Tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    coverage_refs: Tuple[str, ...] = field(default_factory=tuple)
    gap_refs: Tuple[str, ...] = field(default_factory=tuple)
    defect_refs: Tuple[str, ...] = field(default_factory=tuple)
    failure_ownership: Optional[FailureOwnership] = None
    started_at: int = field(default_factory=_now)
    finished_at: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("attempt_id", "test_run_id", "stage_instance_id", "work_item_id", "producer_node_id", "producer_ref", "input_snapshot_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.status, AttemptStatus):
            raise RC8ContractError("ATTEMPT_STATUS_INVALID")
        for name in ("action_refs", "assertion_refs", "evidence_refs", "coverage_refs", "gap_refs", "defect_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if self.case_id is not None:
            object.__setattr__(self, "case_id", _required(self.case_id, "case_id"))
        if self.failure_ownership is not None and not isinstance(self.failure_ownership, FailureOwnership):
            raise RC8ContractError("FAILURE_OWNERSHIP_INVALID")
        if self.status == AttemptStatus.COMPLETED:
            if self.finished_at is None:
                raise RC8ContractError("COMPLETED_ATTEMPT_REQUIRES_FINISHED_AT")
            if not self.evidence_refs:
                raise RC8ContractError("COMPLETED_ATTEMPT_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class GapRecord:
    gap_id: str
    test_run_id: str
    source_stage_instance_id: str
    gap_type: GapType
    severity: GapSeverity
    description: str
    owner_stage: str
    repair_strategy: str
    status: GapStatus = GapStatus.OPEN
    source_attempt_id: Optional[str] = None
    source_case_id: Optional[str] = None
    source_assertion_id: Optional[str] = None
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    invalidates: Tuple[str, ...] = field(default_factory=tuple)
    closure_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    opened_at: int = field(default_factory=_now)
    closed_at: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("gap_id", "test_run_id", "source_stage_instance_id", "description", "owner_stage", "repair_strategy"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.gap_type, GapType):
            raise RC8ContractError("GAP_TYPE_INVALID")
        if not isinstance(self.severity, GapSeverity):
            raise RC8ContractError("GAP_SEVERITY_INVALID")
        if not isinstance(self.status, GapStatus):
            raise RC8ContractError("GAP_STATUS_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "invalidates", _refs(self.invalidates, "invalidates"))
        object.__setattr__(self, "closure_evidence_refs", _refs(self.closure_evidence_refs, "closure_evidence_refs"))
        for name in ("source_attempt_id", "source_case_id", "source_assertion_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        if self.status == GapStatus.CLOSED:
            if self.closed_at is None or not self.closure_evidence_refs:
                raise RC8ContractError("CLOSED_GAP_REQUIRES_CLOSURE_EVIDENCE")


@dataclass(frozen=True)
class InvalidationRecord:
    invalidation_id: str
    test_run_id: str
    source_ref: str
    target_refs: Tuple[str, ...]
    reason: str
    evidence_refs: Tuple[str, ...]
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("invalidation_id", "test_run_id", "source_ref", "reason"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "target_refs", _refs(self.target_refs, "target_refs"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.target_refs:
            raise RC8ContractError("INVALIDATION_TARGET_REQUIRED")
        if not self.evidence_refs:
            raise RC8ContractError("INVALIDATION_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class SufficiencyEvaluation:
    evaluation_id: str
    test_run_id: str
    scope: StatusScope
    subject_id: str
    evaluator_id: str
    policy_version: str
    result: SufficiencyResult
    dimension_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    satisfied_requirement_refs: Tuple[str, ...] = field(default_factory=tuple)
    unsatisfied_requirement_refs: Tuple[str, ...] = field(default_factory=tuple)
    unresolved_gap_ids: Tuple[str, ...] = field(default_factory=tuple)
    accepted_waiver_ids: Tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""
    evaluated_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("evaluation_id", "test_run_id", "subject_id", "evaluator_id", "policy_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.scope not in {StatusScope.STAGE, StatusScope.LAYER, StatusScope.MISSION}:
            raise RC8ContractError("SUFFICIENCY_SCOPE_INVALID")
        if not isinstance(self.result, SufficiencyResult):
            raise RC8ContractError("SUFFICIENCY_RESULT_INVALID")
        for name in (
            "dimension_refs",
            "evidence_refs",
            "satisfied_requirement_refs",
            "unsatisfied_requirement_refs",
            "unresolved_gap_ids",
            "accepted_waiver_ids",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "explanation", _required(self.explanation, "explanation"))
        if not self.evidence_refs:
            raise RC8ContractError("SUFFICIENCY_REQUIRES_EVIDENCE")
        if self.result == SufficiencyResult.SUFFICIENT:
            if self.unsatisfied_requirement_refs or self.unresolved_gap_ids:
                raise RC8ContractError("SUFFICIENT_REQUIRES_NO_UNSATISFIED_OR_UNRESOLVED")
            if self.scope == StatusScope.LAYER and not self.dimension_refs:
                raise RC8ContractError("LAYER_SUFFICIENCY_REQUIRES_DIMENSIONS")


@dataclass(frozen=True)
class StageInstance:
    stage_instance_id: str
    test_run_id: str
    stage_type: str
    scope_version: str
    attempt_no: int
    state: StageState = StageState.PENDING
    input_refs: Tuple[str, ...] = field(default_factory=tuple)
    output_refs: Tuple[str, ...] = field(default_factory=tuple)
    gap_refs: Tuple[str, ...] = field(default_factory=tuple)
    invalidation_refs: Tuple[str, ...] = field(default_factory=tuple)
    predecessor_ids: Tuple[str, ...] = field(default_factory=tuple)
    successor_ids: Tuple[str, ...] = field(default_factory=tuple)
    assigned_worker: Optional[str] = None
    evaluator_id: Optional[str] = None
    policy_version: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("stage_instance_id", "test_run_id", "stage_type", "scope_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.attempt_no, int) or self.attempt_no < 1:
            raise RC8ContractError("STAGE_ATTEMPT_NO_INVALID")
        if not isinstance(self.state, StageState):
            raise RC8ContractError("STAGE_STATE_INVALID")
        for name in ("input_refs", "output_refs", "gap_refs", "invalidation_refs", "predecessor_ids", "successor_ids"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        for name in ("assigned_worker", "evaluator_id", "policy_version"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        if self.state == StageState.SUFFICIENT and not self.evaluator_id:
            raise RC8ContractError("SUFFICIENT_STAGE_REQUIRES_EVALUATOR")


_ALLOWED_STAGE_TRANSITIONS = {
    StageState.PENDING: {StageState.READY, StageState.BLOCKED, StageState.INVALIDATED},
    StageState.READY: {StageState.LEASED, StageState.BLOCKED, StageState.INVALIDATED},
    StageState.LEASED: {StageState.EXECUTING, StageState.BLOCKED, StageState.FAILED_RUNTIME, StageState.INVALIDATED},
    StageState.EXECUTING: {StageState.EVIDENCE_PENDING, StageState.FAILED_RUNTIME, StageState.BLOCKED},
    StageState.EVIDENCE_PENDING: {StageState.EVALUATING, StageState.FAILED_RUNTIME, StageState.BLOCKED},
    StageState.EVALUATING: {StageState.INSUFFICIENT, StageState.SUFFICIENT, StageState.BLOCKED},
    StageState.INSUFFICIENT: {StageState.COMPLETED, StageState.SUPERSEDED, StageState.INVALIDATED},
    StageState.SUFFICIENT: {StageState.COMPLETED, StageState.INVALIDATED},
    StageState.BLOCKED: {StageState.READY, StageState.WAITING_HUMAN, StageState.SUPERSEDED, StageState.INVALIDATED},
    StageState.WAITING_HUMAN: {StageState.READY, StageState.BLOCKED, StageState.SUPERSEDED},
    StageState.FAILED_RUNTIME: {StageState.READY, StageState.SUPERSEDED, StageState.INVALIDATED},
    StageState.COMPLETED: {StageState.INVALIDATED, StageState.SUPERSEDED},
    StageState.INVALIDATED: {StageState.SUPERSEDED},
    StageState.SUPERSEDED: set(),
}


def transition_stage(stage: StageInstance, target: StageState, *, evaluator_id: Optional[str] = None) -> StageInstance:
    if not isinstance(stage, StageInstance) or not isinstance(target, StageState):
        raise RC8ContractError("STAGE_TRANSITION_INPUT_INVALID")
    if target not in _ALLOWED_STAGE_TRANSITIONS[stage.state]:
        raise RC8ContractError("STAGE_TRANSITION_FORBIDDEN:%s->%s" % (stage.state.value, target.value))
    values = {"state": target}
    if target == StageState.EXECUTING and stage.started_at is None:
        values["started_at"] = _now()
    if target in {StageState.SUFFICIENT, StageState.INSUFFICIENT}:
        values["evaluator_id"] = _required(evaluator_id or stage.evaluator_id or "", "evaluator_id")
    if target in {StageState.COMPLETED, StageState.SUPERSEDED, StageState.INVALIDATED}:
        values["finished_at"] = _now()
    return replace(stage, **values)


_GAP_ROUTE = {
    GapType.REQUIREMENT_UNCLEAR: "REQUIREMENT_ANALYSIS",
    GapType.CODE_UNCERTAIN: "CODE_ANALYSIS",
    GapType.DESIGN_GAP: "TEST_DESIGN",
    GapType.COVERAGE_GAP: "TEST_DESIGN",
    GapType.SCRIPT: "EXECUTABLE_SPEC",
    GapType.SPEC: "EXECUTABLE_SPEC",
    GapType.ORACLE: "ORACLE_REVIEW",
    GapType.TEST_DATA: "PRECONDITION_DATA_PREP",
    GapType.PRECONDITION: "PRECONDITION_DATA_PREP",
    GapType.AUTH: "AUTH_RECOVERY",
    GapType.ROUTE: "ROUTE_DISCOVERY",
    GapType.ENVIRONMENT: "ENV_RECOVERY",
    GapType.DEPENDENCY: "ENV_RECOVERY",
    GapType.TOOL: "ENV_RECOVERY",
    GapType.MODEL: "MODEL_RECOVERY",
    GapType.SESSION_RUNTIME: "SESSION_RECOVERY",
    GapType.FLAKY: "REPRODUCIBILITY_ANALYSIS",
    GapType.PRODUCT_DEFECT_LINKED: "DEFECT",
    GapType.UNKNOWN: "DURABLE_GAP",
}

_FAILURE_ROUTE = {
    FailureOwnership.PRODUCT: "DEFECT",
    FailureOwnership.SCRIPT: "EXECUTABLE_SPEC",
    FailureOwnership.SPEC: "EXECUTABLE_SPEC",
    FailureOwnership.ORACLE: "ORACLE_REVIEW",
    FailureOwnership.DATA: "PRECONDITION_DATA_PREP",
    FailureOwnership.AUTH: "AUTH_RECOVERY",
    FailureOwnership.ROUTE: "ROUTE_DISCOVERY",
    FailureOwnership.ENVIRONMENT: "ENV_RECOVERY",
    FailureOwnership.DEPENDENCY: "ENV_RECOVERY",
    FailureOwnership.FLAKY: "REPRODUCIBILITY_ANALYSIS",
    FailureOwnership.TOOL: "ENV_RECOVERY",
    FailureOwnership.MODEL: "MODEL_RECOVERY",
    FailureOwnership.SESSION_RUNTIME: "SESSION_RECOVERY",
    FailureOwnership.UNKNOWN: "DURABLE_GAP",
}


def route_gap(gap_type: GapType) -> str:
    if not isinstance(gap_type, GapType):
        raise RC8ContractError("GAP_TYPE_INVALID")
    return _GAP_ROUTE[gap_type]


def route_failure(ownership: FailureOwnership) -> str:
    if not isinstance(ownership, FailureOwnership):
        raise RC8ContractError("FAILURE_OWNERSHIP_INVALID")
    return _FAILURE_ROUTE[ownership]


@dataclass(frozen=True)
class ReleaseDecisionRecord:
    release_decision_id: str
    test_run_id: str
    decision: ReleaseDecision
    mission_evaluation_ref: str
    evidence_refs: Tuple[str, ...]
    blocking_defect_refs: Tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""
    recorded_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("release_decision_id", "test_run_id", "mission_evaluation_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.decision, ReleaseDecision):
            raise RC8ContractError("RELEASE_DECISION_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "blocking_defect_refs", _refs(self.blocking_defect_refs, "blocking_defect_refs"))
        object.__setattr__(self, "explanation", _required(self.explanation, "explanation"))
        if not self.evidence_refs:
            raise RC8ContractError("RELEASE_DECISION_REQUIRES_EVIDENCE")
        if self.decision == ReleaseDecision.PASS and self.blocking_defect_refs:
            raise RC8ContractError("RELEASE_PASS_FORBIDS_BLOCKING_DEFECTS")


class MissionRuntimeState:
    """In-memory aggregate that enforces append-only mission facts.

    Persistence belongs to Center repositories; this aggregate defines the legal
    state semantics used by those repositories and projections.
    """

    def __init__(self, test_run_id: str) -> None:
        self.test_run_id = _required(test_run_id, "test_run_id")
        self.stages: Dict[str, StageInstance] = {}
        self.attempts: Dict[str, AttemptRecord] = {}
        self.gaps: Dict[str, GapRecord] = {}
        self.coverage: Dict[str, CoverageMetric] = {}
        self.invalidations: Dict[str, InvalidationRecord] = {}
        self.evaluations: Dict[str, SufficiencyEvaluation] = {}

    def add_stage(self, stage: StageInstance) -> None:
        if stage.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_STAGE_TEST_RUN_MISMATCH")
        if stage.stage_instance_id in self.stages:
            raise RC8ContractError("STAGE_INSTANCE_APPEND_ONLY")
        self.stages[stage.stage_instance_id] = stage

    def transition_stage(self, stage_instance_id: str, target: StageState, *, evaluator_id: Optional[str] = None) -> StageInstance:
        stage_id = _required(stage_instance_id, "stage_instance_id")
        if stage_id not in self.stages:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        updated = transition_stage(self.stages[stage_id], target, evaluator_id=evaluator_id)
        self.stages[stage_id] = updated
        return updated

    def add_attempt(self, attempt: AttemptRecord) -> None:
        if attempt.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_ATTEMPT_TEST_RUN_MISMATCH")
        if attempt.stage_instance_id not in self.stages:
            raise RC8ContractError("ATTEMPT_STAGE_NOT_FOUND")
        if attempt.attempt_id in self.attempts:
            raise RC8ContractError("ATTEMPT_APPEND_ONLY")
        self.attempts[attempt.attempt_id] = attempt

    def add_coverage(self, metric: CoverageMetric) -> None:
        if metric.metric_id in self.coverage:
            raise RC8ContractError("COVERAGE_METRIC_APPEND_ONLY")
        self.coverage[metric.metric_id] = metric

    def open_gap(self, gap: GapRecord) -> None:
        if gap.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_GAP_TEST_RUN_MISMATCH")
        if gap.source_stage_instance_id not in self.stages:
            raise RC8ContractError("GAP_SOURCE_STAGE_NOT_FOUND")
        if gap.gap_id in self.gaps:
            raise RC8ContractError("GAP_APPEND_ONLY")
        expected_owner = route_gap(gap.gap_type)
        if gap.owner_stage != expected_owner:
            raise RC8ContractError("GAP_OWNER_ROUTE_MISMATCH:%s!=%s" % (gap.owner_stage, expected_owner))
        self.gaps[gap.gap_id] = gap

    def route_gap(self, gap_id: str) -> GapRecord:
        key = _required(gap_id, "gap_id")
        if key not in self.gaps:
            raise RC8ContractError("GAP_NOT_FOUND")
        current = self.gaps[key]
        if current.status not in {GapStatus.OPEN, GapStatus.REPAIRING}:
            raise RC8ContractError("GAP_ROUTE_STATE_INVALID")
        updated = replace(current, status=GapStatus.ROUTED)
        self.gaps[key] = updated
        return updated

    def close_gap(self, gap_id: str, closure_evidence_refs: Sequence[str]) -> GapRecord:
        key = _required(gap_id, "gap_id")
        if key not in self.gaps:
            raise RC8ContractError("GAP_NOT_FOUND")
        refs = _refs(closure_evidence_refs, "closure_evidence_refs")
        if not refs:
            raise RC8ContractError("GAP_CLOSE_REQUIRES_EVIDENCE")
        current = self.gaps[key]
        updated = replace(current, status=GapStatus.CLOSED, closure_evidence_refs=refs, closed_at=_now())
        self.gaps[key] = updated
        return updated

    def add_invalidation(self, invalidation: InvalidationRecord) -> None:
        if invalidation.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_INVALIDATION_TEST_RUN_MISMATCH")
        if invalidation.invalidation_id in self.invalidations:
            raise RC8ContractError("INVALIDATION_APPEND_ONLY")
        self.invalidations[invalidation.invalidation_id] = invalidation

    def record_evaluation(self, evaluation: SufficiencyEvaluation) -> None:
        if evaluation.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_EVALUATION_TEST_RUN_MISMATCH")
        if evaluation.evaluation_id in self.evaluations:
            raise RC8ContractError("EVALUATION_APPEND_ONLY")
        if evaluation.result == SufficiencyResult.SUFFICIENT:
            unresolved = [gap_id for gap_id in evaluation.unresolved_gap_ids if gap_id in self.gaps and self.gaps[gap_id].status != GapStatus.CLOSED]
            if unresolved:
                raise RC8ContractError("SUFFICIENCY_REFERENCES_OPEN_GAPS")
        self.evaluations[evaluation.evaluation_id] = evaluation

    def active_gap_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(gap_id for gap_id, gap in self.gaps.items() if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}))
