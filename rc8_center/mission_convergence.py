"""RC8 N10 Center-owned global convergence.

N10 consumes durable truth summaries only. It never asks a model whether testing
is complete and it never lets report generation manufacture convergence.
Test sufficiency, product quality and release recommendation are independent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence, Tuple

from rc8_center.defect_closure import DefectSeverity, DefectState
from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeState, MissionNodeType


class MissionConvergenceError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionConvergenceError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise MissionConvergenceError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise MissionConvergenceError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class TestSufficiencyDecision(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"


class ProductQualityAssessment(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ReleaseRecommendation(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"
    HOLD = "HOLD"


class ResidualRiskLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class MissionNodeTruth:
    node_type: MissionNodeType
    state: MissionNodeState
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        if self.node_type == MissionNodeType.N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE:
            raise MissionConvergenceError("N10_CANNOT_BE_INPUT_TO_ITS_OWN_CONVERGENCE")
        if not isinstance(self.state, MissionNodeState):
            raise MissionConvergenceError("MISSION_NODE_STATE_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise MissionConvergenceError("MISSION_NODE_TRUTH_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class CoverageTruth:
    layer: str
    snapshot_id: str
    complete: bool
    blocked: int
    covered_fail: int
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", _required(self.layer, "layer"))
        object.__setattr__(self, "snapshot_id", _required(self.snapshot_id, "snapshot_id"))
        if not isinstance(self.complete, bool) or not isinstance(self.blocked, int) or self.blocked < 0 or not isinstance(self.covered_fail, int) or self.covered_fail < 0:
            raise MissionConvergenceError("COVERAGE_TRUTH_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise MissionConvergenceError("COVERAGE_TRUTH_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class DefectTruth:
    defect_case_id: str
    state: DefectState
    severity: Optional[DefectSeverity]
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "defect_case_id", _required(self.defect_case_id, "defect_case_id"))
        if not isinstance(self.state, DefectState):
            raise MissionConvergenceError("DEFECT_STATE_INVALID")
        if self.severity is not None and not isinstance(self.severity, DefectSeverity):
            raise MissionConvergenceError("DEFECT_SEVERITY_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise MissionConvergenceError("DEFECT_TRUTH_REQUIRES_EVIDENCE")

    @property
    def known_disposition(self) -> bool:
        return self.state in {
            DefectState.NOT_DEFECT,
            DefectState.DUPLICATE_LINKED,
            DefectState.FILED,
            DefectState.FIX_DETECTED,
            DefectState.FIX_VERIFIED,
            DefectState.REGRESSION_VERIFIED,
            DefectState.CLOSED,
            DefectState.REOPENED,
        }

    @property
    def open_product_issue(self) -> bool:
        return self.state in {
            DefectState.FILED,
            DefectState.FIX_DETECTED,
            DefectState.FIX_VERIFIED,
            DefectState.REOPENED,
        }


@dataclass(frozen=True)
class ResidualRisk:
    risk_id: str
    level: ResidualRiskLevel
    accepted: bool
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_id", _required(self.risk_id, "risk_id"))
        if not isinstance(self.level, ResidualRiskLevel) or not isinstance(self.accepted, bool):
            raise MissionConvergenceError("RESIDUAL_RISK_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise MissionConvergenceError("RESIDUAL_RISK_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class MissionConvergenceTruth:
    truth_snapshot_id: str
    test_run_id: str
    mission_nodes: Tuple[MissionNodeTruth, ...]
    coverage: Tuple[CoverageTruth, ...]
    active_blocking_gap_ids: Tuple[str, ...] = field(default_factory=tuple)
    unresolved_unknown_failure_ids: Tuple[str, ...] = field(default_factory=tuple)
    defects: Tuple[DefectTruth, ...] = field(default_factory=tuple)
    residual_risks: Tuple[ResidualRisk, ...] = field(default_factory=tuple)
    truth_refs: Tuple[str, ...] = field(default_factory=tuple)
    captured_at: int = 0

    def __post_init__(self) -> None:
        for name in ("truth_snapshot_id", "test_run_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        for name in ("active_blocking_gap_ids", "unresolved_unknown_failure_ids", "truth_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if not self.truth_refs:
            raise MissionConvergenceError("CONVERGENCE_REQUIRES_DURABLE_TRUTH_REFS")
        if not isinstance(self.captured_at, int) or self.captured_at < 0:
            raise MissionConvergenceError("CONVERGENCE_TRUTH_TIME_INVALID")
        expected = set(MISSION_NODE_SEQUENCE[:-1])
        actual = [value.node_type for value in self.mission_nodes]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise MissionConvergenceError("CONVERGENCE_REQUIRES_EXACT_N1_N9_TRUTH")
        if not self.coverage:
            raise MissionConvergenceError("CONVERGENCE_REQUIRES_COVERAGE_TRUTH")
        layers = [value.layer for value in self.coverage]
        if len(layers) != len(set(layers)):
            raise MissionConvergenceError("CONVERGENCE_COVERAGE_LAYER_DUPLICATE")
        if any(not isinstance(value, MissionNodeTruth) for value in self.mission_nodes):
            raise MissionConvergenceError("MISSION_NODE_TRUTH_INVALID")
        if any(not isinstance(value, CoverageTruth) for value in self.coverage):
            raise MissionConvergenceError("COVERAGE_TRUTH_INVALID")
        if any(not isinstance(value, DefectTruth) for value in self.defects):
            raise MissionConvergenceError("DEFECT_TRUTH_INVALID")
        if any(not isinstance(value, ResidualRisk) for value in self.residual_risks):
            raise MissionConvergenceError("RESIDUAL_RISK_INVALID")
        object.__setattr__(self, "mission_nodes", tuple(self.mission_nodes))
        object.__setattr__(self, "coverage", tuple(self.coverage))
        object.__setattr__(self, "defects", tuple(self.defects))
        object.__setattr__(self, "residual_risks", tuple(self.residual_risks))


@dataclass(frozen=True)
class MissionConvergenceDecision:
    decision_id: str
    truth_snapshot_id: str
    test_run_id: str
    test_sufficiency: TestSufficiencyDecision
    product_quality: ProductQualityAssessment
    release_recommendation: ReleaseRecommendation
    mission_converged: bool
    reason_codes: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    decided_at: int
    authority: str = "CENTER"

    def __post_init__(self) -> None:
        for name in ("decision_id", "truth_snapshot_id", "test_run_id", "authority"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.authority != "CENTER":
            raise MissionConvergenceError("CONVERGENCE_REQUIRES_CENTER_AUTHORITY")
        for value, expected, name in (
            (self.test_sufficiency, TestSufficiencyDecision, "TEST_SUFFICIENCY"),
            (self.product_quality, ProductQualityAssessment, "PRODUCT_QUALITY"),
            (self.release_recommendation, ReleaseRecommendation, "RELEASE_RECOMMENDATION"),
        ):
            if not isinstance(value, expected):
                raise MissionConvergenceError("%s_INVALID" % name)
        if not isinstance(self.mission_converged, bool):
            raise MissionConvergenceError("MISSION_CONVERGED_INVALID")
        object.__setattr__(self, "reason_codes", _refs(self.reason_codes, "reason_codes"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise MissionConvergenceError("CONVERGENCE_DECISION_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class ReportReleaseAuthorization:
    authorization_id: str
    decision_id: str
    report_id: str
    authorized_at: int

    def __post_init__(self) -> None:
        for name in ("authorization_id", "decision_id", "report_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))


class MissionConvergenceRepository(Protocol):
    def get_decision(self, decision_id: str) -> Optional[MissionConvergenceDecision]: ...
    def save_decision(self, value: MissionConvergenceDecision) -> None: ...
    def save_report_authorization(self, value: ReportReleaseAuthorization) -> None: ...


class MemoryMissionConvergenceRepository:
    def __init__(self) -> None:
        self.decisions = {}
        self.report_authorizations = {}

    def get_decision(self, decision_id: str) -> Optional[MissionConvergenceDecision]:
        return self.decisions.get(decision_id)

    def save_decision(self, value: MissionConvergenceDecision) -> None:
        existing = self.decisions.get(value.decision_id)
        if existing is not None and existing != value:
            raise MissionConvergenceError("CONVERGENCE_DECISION_ID_CONFLICT")
        self.decisions[value.decision_id] = value

    def save_report_authorization(self, value: ReportReleaseAuthorization) -> None:
        existing = self.report_authorizations.get(value.authorization_id)
        if existing is not None and existing != value:
            raise MissionConvergenceError("REPORT_AUTHORIZATION_ID_CONFLICT")
        self.report_authorizations[value.authorization_id] = value


class CenterMissionConvergenceService:
    def __init__(self, repository: MissionConvergenceRepository, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.now_fn = now_fn or (lambda: int(time.time()))

    def evaluate(self, *, decision_id: str, truth: MissionConvergenceTruth) -> MissionConvergenceDecision:
        existing = self.repository.get_decision(decision_id)
        if existing is not None:
            if existing.truth_snapshot_id != truth.truth_snapshot_id:
                raise MissionConvergenceError("CONVERGENCE_DECISION_TRUTH_CONFLICT")
            return existing

        node_states = {item.node_type: item.state for item in truth.mission_nodes}
        any_blocked = any(value == MissionNodeState.BLOCKED for value in node_states.values()) or any(item.blocked > 0 for item in truth.coverage)
        all_nodes_pass = all(value == MissionNodeState.PASS for value in node_states.values())
        all_coverage_complete = all(item.complete for item in truth.coverage)
        all_defects_known = all(item.known_disposition for item in truth.defects)
        no_blocking_gaps = not truth.active_blocking_gap_ids
        no_unknown_failures = not truth.unresolved_unknown_failure_ids

        reasons = []
        if any_blocked:
            sufficiency = TestSufficiencyDecision.BLOCKED
            reasons.append("TEST_BLOCKED")
        elif all_nodes_pass and all_coverage_complete and no_blocking_gaps and no_unknown_failures and all_defects_known:
            sufficiency = TestSufficiencyDecision.SUFFICIENT
            reasons.append("TEST_SUFFICIENCY_SATISFIED")
        else:
            sufficiency = TestSufficiencyDecision.INSUFFICIENT
            if not all_nodes_pass: reasons.append("MISSION_NODE_INCOMPLETE")
            if not all_coverage_complete: reasons.append("COVERAGE_INCOMPLETE")
            if not no_blocking_gaps: reasons.append("ACTIVE_BLOCKING_GAP")
            if not no_unknown_failures: reasons.append("UNKNOWN_FAILURE_UNRESOLVED")
            if not all_defects_known: reasons.append("DEFECT_DISPOSITION_UNKNOWN")

        open_defects = [item for item in truth.defects if item.open_product_issue]
        high_open = [item for item in open_defects if item.severity in {DefectSeverity.CRITICAL, DefectSeverity.HIGH}]
        lower_open = [item for item in open_defects if item.severity in {DefectSeverity.MEDIUM, DefectSeverity.LOW}]
        covered_fail = sum(item.covered_fail for item in truth.coverage)
        if high_open:
            quality = ProductQualityAssessment.FAIL
            reasons.append("HIGH_SEVERITY_PRODUCT_DEFECT_OPEN")
        elif lower_open or covered_fail > 0:
            quality = ProductQualityAssessment.DEGRADED
            reasons.append("KNOWN_PRODUCT_FAILURE_OR_LOWER_DEFECT")
        elif sufficiency == TestSufficiencyDecision.SUFFICIENT:
            quality = ProductQualityAssessment.PASS
            reasons.append("NO_KNOWN_PRODUCT_DEFECT")
        else:
            quality = ProductQualityAssessment.UNKNOWN
            reasons.append("PRODUCT_QUALITY_NOT_YET_DETERMINATE")

        unacceptable_risk = any(item.level in {ResidualRiskLevel.CRITICAL, ResidualRiskLevel.HIGH} and not item.accepted for item in truth.residual_risks)
        unaccepted_medium = any(item.level == ResidualRiskLevel.MEDIUM and not item.accepted for item in truth.residual_risks)
        if quality == ProductQualityAssessment.FAIL:
            release = ReleaseRecommendation.NO_GO
        elif sufficiency == TestSufficiencyDecision.SUFFICIENT and quality == ProductQualityAssessment.PASS and not unacceptable_risk and not unaccepted_medium:
            release = ReleaseRecommendation.GO
        else:
            release = ReleaseRecommendation.HOLD
        reasons.append("RELEASE_%s" % release.value)

        converged = sufficiency == TestSufficiencyDecision.SUFFICIENT and quality != ProductQualityAssessment.UNKNOWN
        if converged:
            reasons.append("MISSION_CONVERGED")
        else:
            reasons.append("MISSION_NOT_CONVERGED")

        evidence = list(truth.truth_refs)
        for item in truth.mission_nodes: evidence.extend(item.evidence_refs)
        for item in truth.coverage: evidence.extend(item.evidence_refs)
        for item in truth.defects: evidence.extend(item.evidence_refs)
        for item in truth.residual_risks: evidence.extend(item.evidence_refs)
        decision = MissionConvergenceDecision(
            decision_id=decision_id,
            truth_snapshot_id=truth.truth_snapshot_id,
            test_run_id=truth.test_run_id,
            test_sufficiency=sufficiency,
            product_quality=quality,
            release_recommendation=release,
            mission_converged=converged,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_refs=tuple(dict.fromkeys(evidence)),
            decided_at=int(self.now_fn()),
        )
        self.repository.save_decision(decision)
        return decision

    def authorize_report_release(self, *, authorization_id: str, decision_id: str, report_id: str) -> ReportReleaseAuthorization:
        decision = self.repository.get_decision(_required(decision_id, "decision_id"))
        if decision is None:
            raise MissionConvergenceError("REPORT_RELEASE_REQUIRES_CONVERGENCE_DECISION")
        if not decision.mission_converged:
            raise MissionConvergenceError("REPORT_RELEASE_REQUIRES_MISSION_CONVERGED")
        value = ReportReleaseAuthorization(authorization_id=authorization_id, decision_id=decision.decision_id, report_id=report_id, authorized_at=int(self.now_fn()))
        self.repository.save_report_authorization(value)
        return value
