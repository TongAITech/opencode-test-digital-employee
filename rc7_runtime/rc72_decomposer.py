"""RC7.2 adaptive TestObligation -> ETU decomposition.

Decomposer decides WHAT cohesive work units should exist. It never schedules
workers or acquires leases. ReleaseBatch/Requirement/SST/TestObligation remain
the asset root; coverage and runtime history are feedback signals only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .models import ContractError
from .rc72_domain import ExecutionTaskUnit, TestObligation


@dataclass(frozen=True)
class PlanningCase:
    case_id: str
    release_batch_id: str
    requirement_id: str
    sst_id: str
    obligation_id: str
    business_scenario: str
    code_slice: str
    test_level: str
    data_domain: str
    auth_role: str
    oracle_family: str
    execution_tool: str
    browser_context: str
    environment: str
    case_kind: str = "POSITIVE"
    estimated_duration_minutes: int = 1
    estimated_cost: float = 0.0
    data_strategy: str = "SHARED_REFERENCE"
    data_resource_key: str = ""
    requires_isolated_data: bool = False

    def __post_init__(self) -> None:
        for name in (
            "case_id", "release_batch_id", "requirement_id", "sst_id", "obligation_id",
            "business_scenario", "code_slice", "test_level", "data_domain", "auth_role",
            "oracle_family", "execution_tool", "browser_context", "environment", "case_kind",
            "data_strategy",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError("PLANNING_CASE_%s_REQUIRED" % name.upper())
        if not isinstance(self.data_resource_key, str):
            raise ContractError("PLANNING_CASE_DATA_RESOURCE_KEY_INVALID")
        if not isinstance(self.requires_isolated_data, bool):
            raise ContractError("PLANNING_CASE_DATA_ISOLATION_INVALID")
        if self.requires_isolated_data and not self.data_resource_key.strip():
            raise ContractError("PLANNING_CASE_ISOLATED_DATA_RESOURCE_REQUIRED")
        if not isinstance(self.estimated_duration_minutes, int) or self.estimated_duration_minutes <= 0:
            raise ContractError("PLANNING_CASE_DURATION_INVALID")
        if not isinstance(self.estimated_cost, (int, float)) or self.estimated_cost < 0:
            raise ContractError("PLANNING_CASE_COST_INVALID")


@dataclass(frozen=True)
class CoverageGapSignal:
    signal_id: str
    code_slice: str
    uncovered_units: int
    requirement_id: Optional[str] = None
    sst_id: Optional[str] = None
    obligation_id: Optional[str] = None
    gap_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.signal_id, str) or not self.signal_id.strip():
            raise ContractError("COVERAGE_SIGNAL_ID_REQUIRED")
        if not isinstance(self.code_slice, str) or not self.code_slice.strip():
            raise ContractError("COVERAGE_CODE_SLICE_REQUIRED")
        if not isinstance(self.uncovered_units, int) or self.uncovered_units < 0:
            raise ContractError("COVERAGE_UNCOVERED_UNITS_INVALID")


@dataclass(frozen=True)
class CoverageRoute:
    signal_id: str
    gap_reason: str
    responsible_nodes: List[str]
    action: str
    obligation_id: Optional[str] = None


@dataclass(frozen=True)
class ExecutionHistoryMetric:
    metric_id: str
    obligation_id: str
    predicted_coverage_yield: float
    actual_coverage_delta: float
    execution_duration_minutes: int
    tool_calls: int
    token_cost: int
    failure_classification: str = "NONE"

    def __post_init__(self) -> None:
        for name in ("metric_id", "obligation_id", "failure_classification"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError("EXECUTION_HISTORY_%s_REQUIRED" % name.upper())
        for name in ("predicted_coverage_yield", "actual_coverage_delta"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value < 0:
                raise ContractError("EXECUTION_HISTORY_%s_INVALID" % name.upper())
        for name in ("execution_duration_minutes", "tool_calls", "token_cost"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ContractError("EXECUTION_HISTORY_%s_INVALID" % name.upper())


@dataclass(frozen=True)
class ObligationPlanningSignal:
    obligation_id: str
    requirement_priority: float = 0.0
    sst_criticality: float = 0.0
    change_impact: float = 0.0
    historical_defect_density: float = 0.0
    uncovered_changed_code: float = 0.0
    coverage_yield_estimate: float = 0.0
    production_blast_radius: float = 0.0
    blocked_downstream_work: float = 0.0
    execution_cost: float = 0.0
    resource_contention: float = 0.0
    uncertainty_reduction: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_id, str) or not self.obligation_id.strip():
            raise ContractError("PLANNING_SIGNAL_OBLIGATION_ID_REQUIRED")
        for name in (
            "requirement_priority", "sst_criticality", "change_impact",
            "historical_defect_density", "uncovered_changed_code", "coverage_yield_estimate",
            "production_blast_radius", "blocked_downstream_work", "execution_cost",
            "resource_contention", "uncertainty_reduction",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise ContractError("PLANNING_SIGNAL_%s_INVALID" % name.upper())


@dataclass(frozen=True)
class DecompositionConfig:
    target_min_cases: int = 3
    target_max_cases: int = 8
    target_duration_minutes: int = 15
    priority_weights: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.target_min_cases, int) or self.target_min_cases < 1:
            raise ContractError("DECOMPOSER_TARGET_MIN_INVALID")
        if not isinstance(self.target_max_cases, int) or self.target_max_cases < self.target_min_cases:
            raise ContractError("DECOMPOSER_TARGET_MAX_INVALID")
        if not isinstance(self.target_duration_minutes, int) or self.target_duration_minutes < 1:
            raise ContractError("DECOMPOSER_DURATION_TARGET_INVALID")
        if not isinstance(self.priority_weights, dict):
            raise ContractError("DECOMPOSER_PRIORITY_WEIGHTS_INVALID")
        for key, value in self.priority_weights.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, (int, float)):
                raise ContractError("DECOMPOSER_PRIORITY_WEIGHT_INVALID")


@dataclass(frozen=True)
class DecompositionSnapshot:
    snapshot_id: str
    mission_id: str
    release_batch_id: str
    current_node: str
    obligations: List[TestObligation]
    cases: List[PlanningCase]
    coverage_gaps: List[CoverageGapSignal] = field(default_factory=list)
    completed_case_ids: List[str] = field(default_factory=list)
    execution_history: List[ExecutionHistoryMetric] = field(default_factory=list)
    planning_signals: List[ObligationPlanningSignal] = field(default_factory=list)
    config_version: str = "v1"

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "mission_id", "release_batch_id", "current_node", "config_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError("DECOMPOSITION_%s_REQUIRED" % name.upper())
        if not isinstance(self.obligations, list) or not all(isinstance(v, TestObligation) for v in self.obligations):
            raise ContractError("DECOMPOSITION_OBLIGATIONS_INVALID")
        if not isinstance(self.cases, list) or not all(isinstance(v, PlanningCase) for v in self.cases):
            raise ContractError("DECOMPOSITION_CASES_INVALID")
        if not isinstance(self.coverage_gaps, list) or not all(isinstance(v, CoverageGapSignal) for v in self.coverage_gaps):
            raise ContractError("DECOMPOSITION_COVERAGE_GAPS_INVALID")
        if not isinstance(self.execution_history, list) or not all(isinstance(v, ExecutionHistoryMetric) for v in self.execution_history):
            raise ContractError("DECOMPOSITION_EXECUTION_HISTORY_INVALID")
        if not isinstance(self.planning_signals, list) or not all(isinstance(v, ObligationPlanningSignal) for v in self.planning_signals):
            raise ContractError("DECOMPOSITION_PLANNING_SIGNALS_INVALID")
        if not isinstance(self.completed_case_ids, list) or not all(isinstance(v, str) and v.strip() for v in self.completed_case_ids):
            raise ContractError("DECOMPOSITION_COMPLETED_CASE_IDS_INVALID")


@dataclass(frozen=True)
class DecompositionResult:
    etus: List[ExecutionTaskUnit]
    case_index: Dict[str, PlanningCase]
    coverage_routes: List[CoverageRoute]
    obligation_priorities: Dict[str, float]
    generated_case_ids: List[str]
    skipped_completed_case_ids: List[str]
    replan_reasons: Dict[str, List[str]] = field(default_factory=dict)
    priority_explanations: Dict[str, Dict[str, float]] = field(default_factory=dict)


_COVERAGE_ROUTES = {
    "NO_REQUIREMENT_MAPPING": (["N2_REQUIREMENT", "N3_CODE_ANALYSIS"], "INVESTIGATE"),
    "ANALYSIS_MISSING": (["N3_CODE_ANALYSIS"], "REPAIR_ANALYSIS"),
    "CASE_MISSING": (["N4_TEST_DESIGN"], "REPAIR_OBLIGATION"),
    "DATA_BLOCKED": (["N5_TEST_DATA"], "REPAIR_DATA"),
    "EXECUTABLE_BLOCKED": (["N6_EXECUTABLE_READINESS"], "REPAIR_EXECUTABLE"),
    "PATH_NOT_REACHED": (["N8_DIAGNOSIS_RECOVERY"], "DIAGNOSE"),
    "UNREACHABLE": (["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"], "COVERAGE_EXCLUSION_CANDIDATE"),
    "ALREADY_COVERED_NO_GAIN": (["N10_RELEASE_CONVERGENCE"], "DEPRIORITIZE_OR_INVESTIGATE"),
}

_NON_LOW_YIELD_FAILURES = {
    "PRODUCT_DEFECT", "VALID_TEST_FAILURE", "ENVIRONMENT_GAP",
    "PROVIDER_AUTH", "PROVIDER_QUOTA", "PROVIDER_TIMEOUT",
}
_SIGNAL_DIMENSIONS = (
    "requirement_priority", "sst_criticality", "change_impact",
    "historical_defect_density", "uncovered_changed_code", "coverage_yield_estimate",
    "production_blast_radius", "blocked_downstream_work", "execution_cost",
    "resource_contention", "uncertainty_reduction",
)


class AdaptiveTaskDecomposer:
    def __init__(self, config: Optional[DecompositionConfig] = None) -> None:
        self.config = config or DecompositionConfig()

    def decompose(self, snapshot: DecompositionSnapshot) -> DecompositionResult:
        obligations = self._obligation_index(snapshot)
        case_index = self._case_index(snapshot, obligations)
        self._validate_history(snapshot, obligations)
        signals = self._planning_signal_index(snapshot, obligations)
        completed = set(snapshot.completed_case_ids)
        active_cases = sorted(
            [case for case in case_index.values() if case.case_id not in completed],
            key=lambda case: case.case_id,
        )
        routes = [
            self._coverage_route(signal, obligations)
            for signal in sorted(snapshot.coverage_gaps, key=lambda x: x.signal_id)
        ]
        priorities, replan_reasons, explanations = self._priorities(
            obligations, routes, snapshot.coverage_gaps, snapshot.execution_history, signals
        )
        grouped: Dict[Tuple[str, ...], List[PlanningCase]] = {}
        for case in active_cases:
            grouped.setdefault(self._cohesion_key(case), []).append(case)
        etus: List[ExecutionTaskUnit] = []
        for key in sorted(grouped.keys()):
            group = sorted(grouped[key], key=lambda case: case.case_id)
            for chunk in self._chunks(group):
                etus.append(self._build_etu(snapshot, obligations[chunk[0].obligation_id], chunk))
        etus.sort(key=lambda etu: etu.etu_id)
        return DecompositionResult(
            etus=etus,
            case_index=case_index,
            coverage_routes=routes,
            obligation_priorities=priorities,
            generated_case_ids=[],
            skipped_completed_case_ids=sorted(cid for cid in snapshot.completed_case_ids if cid in case_index),
            replan_reasons=replan_reasons,
            priority_explanations=explanations,
        )

    def _obligation_index(self, snapshot: DecompositionSnapshot) -> Dict[str, TestObligation]:
        result: Dict[str, TestObligation] = {}
        for obligation in snapshot.obligations:
            if obligation.mission_id != snapshot.mission_id:
                raise ContractError("DECOMPOSER_OBLIGATION_MISSION_MISMATCH")
            if obligation.release_batch_id != snapshot.release_batch_id:
                raise ContractError("DECOMPOSER_OBLIGATION_RELEASE_BATCH_MISMATCH")
            if obligation.obligation_id in result:
                raise ContractError("DECOMPOSER_DUPLICATE_OBLIGATION")
            result[obligation.obligation_id] = obligation
        return result

    def _case_index(self, snapshot: DecompositionSnapshot, obligations: Mapping[str, TestObligation]) -> Dict[str, PlanningCase]:
        result: Dict[str, PlanningCase] = {}
        for case in snapshot.cases:
            if case.case_id in result:
                raise ContractError("DECOMPOSER_DUPLICATE_CASE")
            obligation = obligations.get(case.obligation_id)
            if obligation is None:
                raise ContractError("DECOMPOSER_ORPHAN_CASE_FORBIDDEN")
            if case.release_batch_id != snapshot.release_batch_id:
                raise ContractError("DECOMPOSER_CASE_RELEASE_BATCH_MISMATCH")
            if case.requirement_id != obligation.requirement_id:
                raise ContractError("DECOMPOSER_CASE_REQUIREMENT_MISMATCH")
            if case.sst_id != obligation.sst_id:
                raise ContractError("DECOMPOSER_CASE_SST_MISMATCH")
            if case.test_level.upper() != obligation.test_level.upper():
                raise ContractError("DECOMPOSER_CASE_TEST_LEVEL_MISMATCH")
            result[case.case_id] = case
        return result

    @staticmethod
    def _validate_history(snapshot: DecompositionSnapshot, obligations: Mapping[str, TestObligation]) -> None:
        seen = set()
        for metric in snapshot.execution_history:
            if metric.metric_id in seen:
                raise ContractError("DECOMPOSER_DUPLICATE_HISTORY_METRIC")
            seen.add(metric.metric_id)
            if metric.obligation_id not in obligations:
                raise ContractError("DECOMPOSER_HISTORY_ORPHAN_OBLIGATION")

    @staticmethod
    def _planning_signal_index(
        snapshot: DecompositionSnapshot,
        obligations: Mapping[str, TestObligation],
    ) -> Dict[str, ObligationPlanningSignal]:
        result: Dict[str, ObligationPlanningSignal] = {}
        for signal in snapshot.planning_signals:
            if signal.obligation_id not in obligations:
                raise ContractError("DECOMPOSER_SIGNAL_ORPHAN_OBLIGATION")
            if signal.obligation_id in result:
                raise ContractError("DECOMPOSER_DUPLICATE_PLANNING_SIGNAL")
            result[signal.obligation_id] = signal
        return result

    @staticmethod
    def _cohesion_key(case: PlanningCase) -> Tuple[str, ...]:
        isolation = "shared"
        if case.requires_isolated_data:
            isolation = "isolated:%s:%s" % (case.data_resource_key, case.case_id)
        return (
            case.requirement_id, case.sst_id, case.obligation_id, case.business_scenario,
            case.code_slice, case.test_level.upper(), case.data_domain, case.data_strategy,
            isolation, case.auth_role, case.oracle_family, case.execution_tool,
            case.browser_context, case.environment,
        )

    def _chunks(self, cases: Sequence[PlanningCase]) -> List[List[PlanningCase]]:
        chunks: List[List[PlanningCase]] = []
        current: List[PlanningCase] = []
        duration = 0
        for case in cases:
            if len(current) >= self.config.target_max_cases or (
                current and duration + case.estimated_duration_minutes > self.config.target_duration_minutes
            ):
                chunks.append(current)
                current = []
                duration = 0
            current.append(case)
            duration += case.estimated_duration_minutes
        if current:
            chunks.append(current)
        return chunks

    def _build_etu(
        self,
        snapshot: DecompositionSnapshot,
        obligation: TestObligation,
        cases: Sequence[PlanningCase],
    ) -> ExecutionTaskUnit:
        case_ids = [case.case_id for case in cases]
        digest = hashlib.sha256(
            "|".join([snapshot.snapshot_id, snapshot.config_version, obligation.obligation_id] + case_ids).encode("utf-8")
        ).hexdigest()[:16]
        first = cases[0]
        explanation = (
            "same_requirement=%s; same_sst=%s; same_obligation=%s; same_business_scenario=%s; "
            "same_code_slice=%s; same_test_level=%s; same_data_domain=%s; data_strategy=%s; "
            "same_auth_role=%s; same_oracle_family=%s; same_execution_tool=%s; "
            "same_browser_context=%s; same_environment=%s"
            % (
                first.requirement_id, first.sst_id, first.obligation_id, first.business_scenario,
                first.code_slice, first.test_level.upper(), first.data_domain, first.data_strategy,
                first.auth_role, first.oracle_family, first.execution_tool,
                first.browser_context, first.environment,
            )
        )
        if first.requires_isolated_data:
            explanation += "; exclusive_data_isolation=%s" % first.data_resource_key
        capabilities = ["tool:%s" % first.execution_tool]
        if first.execution_tool == "browser":
            capabilities.extend([
                "browser_context:%s" % first.browser_context,
                "auth_role:%s" % first.auth_role,
            ])
        return ExecutionTaskUnit(
            etu_id="ETU-%s" % digest,
            mission_id=snapshot.mission_id,
            release_batch_id=snapshot.release_batch_id,
            obligation_id=obligation.obligation_id,
            case_ids=case_ids,
            primary_goal=obligation.business_rule,
            primary_code_slice=first.code_slice,
            test_level=first.test_level.upper(),
            primary_oracle=first.oracle_family,
            data_domain=first.data_domain,
            primary_tool_family=first.execution_tool,
            planning_snapshot_ref=snapshot.snapshot_id,
            cohesion_score=1.0,
            cohesion_explanation=explanation,
            required_capabilities=capabilities,
            estimated_duration_minutes=max(1, sum(c.estimated_duration_minutes for c in cases)),
            estimated_cost=sum(float(c.estimated_cost) for c in cases),
        )

    def _coverage_route(
        self,
        signal: CoverageGapSignal,
        obligations: Mapping[str, TestObligation],
    ) -> CoverageRoute:
        mapped = bool(signal.requirement_id and signal.sst_id)
        reason = (signal.gap_reason or ("CASE_MISSING" if mapped else "NO_REQUIREMENT_MAPPING")).upper()
        if not mapped:
            reason = "NO_REQUIREMENT_MAPPING"
        if reason not in _COVERAGE_ROUTES:
            raise ContractError("COVERAGE_GAP_REASON_UNSUPPORTED:%s" % reason)
        if signal.obligation_id is not None:
            obligation = obligations.get(signal.obligation_id)
            if obligation is None:
                raise ContractError("COVERAGE_OBLIGATION_NOT_CANONICAL")
            if signal.requirement_id != obligation.requirement_id or signal.sst_id != obligation.sst_id:
                raise ContractError("COVERAGE_OBLIGATION_LINEAGE_MISMATCH")
        nodes, action = _COVERAGE_ROUTES[reason]
        return CoverageRoute(signal.signal_id, reason, list(nodes), action, signal.obligation_id)

    def _priorities(
        self,
        obligations: Mapping[str, TestObligation],
        routes: Sequence[CoverageRoute],
        coverage_signals: Sequence[CoverageGapSignal],
        history: Sequence[ExecutionHistoryMetric],
        planning_signals: Mapping[str, ObligationPlanningSignal],
    ) -> Tuple[Dict[str, float], Dict[str, List[str]], Dict[str, Dict[str, float]]]:
        weights = self.config.priority_weights
        coverage_by_id = {signal.signal_id: signal for signal in coverage_signals}
        priorities: Dict[str, float] = {}
        reasons: Dict[str, List[str]] = {}
        explanations: Dict[str, Dict[str, float]] = {}
        for obligation_id, obligation in obligations.items():
            risk_value = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}.get(
                obligation.risk_level.upper(), 0.3
            )
            signal = planning_signals.get(obligation_id) or ObligationPlanningSignal(obligation_id)
            dimensions: Dict[str, float] = {"business_risk": risk_value}
            for name in _SIGNAL_DIMENSIONS:
                dimensions[name] = float(getattr(signal, name))
            score = 0.0
            for name, value in dimensions.items():
                score += float(weights.get(name, 0.0 if name != "business_risk" else 1.0)) * value
            coverage_gap_value = 0.0
            for route in routes:
                if route.obligation_id == obligation_id:
                    raw = coverage_by_id[route.signal_id]
                    coverage_gap_value = max(coverage_gap_value, min(1.0, float(raw.uncovered_units) / 100.0))
            score += float(weights.get("coverage_gap", 0.0)) * coverage_gap_value
            dimensions["coverage_gap"] = coverage_gap_value
            dimensions["history_low_yield_penalty"] = 0.0
            for metric in history:
                if metric.obligation_id != obligation_id or metric.failure_classification.upper() in _NON_LOW_YIELD_FAILURES:
                    continue
                ratio = 1.0 if metric.predicted_coverage_yield <= 0 else (
                    float(metric.actual_coverage_delta) / float(metric.predicted_coverage_yield)
                )
                expensive = (
                    metric.tool_calls >= 20
                    or metric.token_cost >= 50000
                    or metric.execution_duration_minutes >= self.config.target_duration_minutes
                )
                if ratio <= 0.1 and expensive:
                    penalty = abs(float(weights.get("coverage_yield", 1.0))) + abs(float(weights.get("execution_cost", -0.5)))
                    score -= penalty
                    dimensions["history_low_yield_penalty"] -= penalty
                    reasons.setdefault(obligation_id, []).append("LOW_COVERAGE_YIELD")
            priorities[obligation_id] = round(score, 6)
            explanations[obligation_id] = {key: round(value, 6) for key, value in dimensions.items()}
        return priorities, reasons, explanations
