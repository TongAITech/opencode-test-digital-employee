"""RC6 Wave 11 empirical L1-L7 execution coverage closure.

Semantic design coverage was closed in Wave 7. This module closes a different
question: what did real execution actually exercise? Coverage is derived only
from evidence-backed observations bound to a real ExecutionRecord, exact
TargetIdentity, Case version, attempt and layer. Case counts and model-reported
percentages are never inputs to the closure decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .authority import AuthorityError, AuthorityRuntime
from .capability import ToolCapabilityBroker, ToolCapabilityError
from .execution import ExecutionRecord


class ExecutionCoverageError(RuntimeError):
    pass


LAYERS = {f"L{i}" for i in range(1, 8)}
RISKS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


@dataclass(frozen=True)
class LayerCoverageProfile:
    layer: str
    dimensions: Tuple[str, ...]
    dimension_tools: Mapping[str, Tuple[str, ...]]


DEFAULT_LAYER_COVERAGE_PROFILES: Dict[str, LayerCoverageProfile] = {
    "L1": LayerCoverageProfile(
        "L1",
        ("changed_method", "changed_line", "changed_branch", "mutation"),
        {
            "changed_method": ("jacoco",),
            "changed_line": ("jacoco",),
            "changed_branch": ("jacoco",),
            "mutation": ("pit",),
        },
    ),
    "L2": LayerCoverageProfile(
        "L2",
        ("db_object", "sql_path", "transaction", "state_transition"),
        {x: ("database",) for x in ("db_object", "sql_path", "transaction", "state_transition")},
    ),
    "L3": LayerCoverageProfile(
        "L3",
        ("route", "method", "schema", "auth", "business_rule", "error_path"),
        {x: ("api-runtime",) for x in ("route", "method", "schema", "auth", "business_rule", "error_path")},
    ),
    "L4": LayerCoverageProfile(
        "L4",
        ("page", "control", "ui_state", "network", "frontend_branch"),
        {
            "page": ("browser-skill", "playwright"),
            "control": ("browser-skill", "playwright"),
            "ui_state": ("browser-skill", "playwright"),
            "network": ("browser-skill", "playwright"),
            "frontend_branch": ("playwright", "browser-skill"),
        },
    ),
    "L5": LayerCoverageProfile(
        "L5",
        ("journey_node", "state_transition", "system_hop", "consistency_assertion"),
        {x: ("e2e-orchestrator",) for x in ("journey_node", "state_transition", "system_hop", "consistency_assertion")},
    ),
    "L6": LayerCoverageProfile(
        "L6",
        ("workload", "latency_slo", "throughput_slo", "error_rate_slo", "resource_envelope"),
        {x: ("k6",) for x in ("workload", "latency_slo", "throughput_slo", "error_rate_slo", "resource_envelope")},
    ),
    "L7": LayerCoverageProfile(
        "L7",
        ("attack_surface", "authn", "authz", "input_validation", "security_control", "security_error_path"),
        {x: ("zap",) for x in ("attack_surface", "authn", "authz", "input_validation", "security_control", "security_error_path")},
    ),
}


@dataclass(frozen=True)
class EmpiricalCoverageSubject:
    subject_id: str
    layer: str
    dimension: str
    risk: str
    required: bool
    expected_refs: Tuple[str, ...]
    source_refs: Tuple[str, ...]
    existing_case_refs: Tuple[str, ...]


@dataclass(frozen=True)
class CoverageObservation:
    observation_id: str
    subject_id: str
    layer: str
    target_id: str
    attempt_id: str
    tc_id: str
    case_version: int
    tool_id: str
    tool_call_ref: str
    evidence_ref: str
    observed_refs: Tuple[str, ...]
    metrics: Dict[str, Any]
    covered: bool


@dataclass(frozen=True)
class EmpiricalCoverageGap:
    subject_id: str
    layer: str
    dimension: str
    risk: str
    reason: str
    existing_case_refs: Tuple[str, ...]


@dataclass(frozen=True)
class LayerCoverageResult:
    layer: str
    status: str
    required_subject_count: int
    covered_required_count: int
    coverage_ratio: float
    evidence_refs: Tuple[str, ...]
    gaps: Tuple[EmpiricalCoverageGap, ...]
    optional_gaps: Tuple[EmpiricalCoverageGap, ...]


@dataclass(frozen=True)
class EmpiricalClosureResult:
    passed: bool
    status: str
    target_id: str
    layer_results: Tuple[LayerCoverageResult, ...]
    required_subject_count: int
    covered_required_count: int
    critical_high_gap_ids: Tuple[str, ...]
    gap_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]


@dataclass(frozen=True)
class CoverageDeltaRequest:
    layer: str
    action: str
    subject_ids: Tuple[str, ...]
    reason: str
    target_id: str


class EmpiricalCoverageRegistry:
    def __init__(
        self,
        raw_subjects: Iterable[Dict[str, Any]],
        profiles: Optional[Mapping[str, LayerCoverageProfile]] = None,
    ):
        self.profiles = dict(profiles or DEFAULT_LAYER_COVERAGE_PROFILES)
        if set(self.profiles) != LAYERS:
            raise ExecutionCoverageError("SEVEN_LAYER_COVERAGE_PROFILES_REQUIRED")
        self.subjects: Dict[str, EmpiricalCoverageSubject] = {}
        for raw in raw_subjects:
            subject = self._validate(raw)
            if subject.subject_id in self.subjects:
                raise ExecutionCoverageError("DUPLICATE_EMPIRICAL_COVERAGE_SUBJECT")
            self.subjects[subject.subject_id] = subject
        if not self.subjects:
            raise ExecutionCoverageError("EMPIRICAL_COVERAGE_SUBJECTS_EMPTY")

    def _validate(self, raw: Dict[str, Any]) -> EmpiricalCoverageSubject:
        if not isinstance(raw, dict):
            raise ExecutionCoverageError("INVALID_EMPIRICAL_COVERAGE_SUBJECT")
        sid = raw.get("subject_id")
        layer = str(raw.get("layer", "")).upper()
        dimension = str(raw.get("dimension", "")).lower()
        risk = str(raw.get("risk", "")).upper()
        required = raw.get("required")
        expected_refs = raw.get("expected_refs")
        source_refs = raw.get("source_refs")
        existing_case_refs = raw.get("existing_case_refs", [])
        if not isinstance(sid, str) or not sid.strip():
            raise ExecutionCoverageError("EMPIRICAL_SUBJECT_ID_REQUIRED")
        if layer not in LAYERS:
            raise ExecutionCoverageError("INVALID_EMPIRICAL_SUBJECT_LAYER")
        if dimension not in self.profiles[layer].dimensions:
            raise ExecutionCoverageError("INVALID_LAYER_COVERAGE_DIMENSION")
        if risk not in RISKS:
            raise ExecutionCoverageError("INVALID_EMPIRICAL_SUBJECT_RISK")
        if not isinstance(required, bool):
            raise ExecutionCoverageError("EMPIRICAL_SUBJECT_REQUIRED_FLAG_MISSING")
        if not isinstance(expected_refs, list) or not expected_refs or not all(isinstance(x, str) and x.strip() for x in expected_refs):
            raise ExecutionCoverageError("EMPIRICAL_SUBJECT_EXPECTED_REFS_REQUIRED")
        if not isinstance(source_refs, list) or not source_refs or not all(isinstance(x, str) and x.strip() for x in source_refs):
            raise ExecutionCoverageError("EMPIRICAL_SUBJECT_SOURCE_REFS_REQUIRED")
        if not isinstance(existing_case_refs, list) or not all(isinstance(x, str) and x.strip() for x in existing_case_refs):
            raise ExecutionCoverageError("EMPIRICAL_SUBJECT_CASE_REFS_INVALID")
        return EmpiricalCoverageSubject(
            subject_id=sid.strip(),
            layer=layer,
            dimension=dimension,
            risk=risk,
            required=required,
            expected_refs=tuple(sorted(set(expected_refs))),
            source_refs=tuple(sorted(set(source_refs))),
            existing_case_refs=tuple(sorted(set(existing_case_refs))),
        )

    def required(self) -> Tuple[EmpiricalCoverageSubject, ...]:
        return tuple(self.subjects[k] for k in sorted(self.subjects) if self.subjects[k].required)

    def applicable_layers(self) -> Tuple[str, ...]:
        return tuple(sorted({s.layer for s in self.subjects.values()}))


class CoverageObservationRuntime:
    """Accept coverage only from real execution evidence and real tool calls."""

    def __init__(self, *, authority: AuthorityRuntime, tool_broker: ToolCapabilityBroker, registry: EmpiricalCoverageRegistry):
        self.authority = authority
        self.tool_broker = tool_broker
        self.registry = registry
        self._observations: Dict[str, CoverageObservation] = {}

    def record(
        self,
        *,
        execution: ExecutionRecord,
        subject_id: str,
        tool_id: str,
        tool_call_ref: str,
        evidence_ref: str,
        observed_refs: Iterable[str],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> CoverageObservation:
        subject = self.registry.subjects.get(subject_id)
        if subject is None:
            raise ExecutionCoverageError("UNKNOWN_EMPIRICAL_COVERAGE_SUBJECT")
        if not execution.integrity_passed or not isinstance(execution.actual_result, dict) or not execution.actual_result:
            raise ExecutionCoverageError("REAL_EXECUTION_INTEGRITY_REQUIRED_FOR_COVERAGE")
        if execution.layer != subject.layer:
            raise ExecutionCoverageError("CROSS_LAYER_COVERAGE_FORBIDDEN")
        if execution.status not in {"PASS", "FAIL"}:
            raise ExecutionCoverageError("NON_EXECUTED_STATUS_CANNOT_PRODUCE_COVERAGE")
        profile = self.registry.profiles[subject.layer]
        allowed_tools = profile.dimension_tools[subject.dimension]
        if tool_id not in allowed_tools:
            raise ExecutionCoverageError("COVERAGE_TOOL_NOT_ALLOWED_FOR_DIMENSION")
        if not all(isinstance(x, str) and x.strip() for x in (tool_call_ref, evidence_ref)):
            raise ExecutionCoverageError("COVERAGE_TOOL_EVIDENCE_REQUIRED")
        observed = tuple(sorted(set(x for x in observed_refs if isinstance(x, str) and x.strip())))
        if not observed:
            raise ExecutionCoverageError("OBSERVED_COVERAGE_REFS_REQUIRED")
        try:
            self.authority.authorize_artifact(execution.worker_id, execution.lease_id, "coverage_observation")
            self.authority.authorize_tool(execution.worker_id, execution.lease_id, tool_id)
        except AuthorityError as exc:
            raise ExecutionCoverageError(str(exc))
        admission = self.tool_broker.admit(execution.worker_id, [tool_id], execution.target_id)
        if not admission.ready:
            raise ExecutionCoverageError(f"COVERAGE_TOOL_NOT_READY:{admission.blocked.get(tool_id)}")
        try:
            self.tool_broker.record_tool_call(
                tool_id,
                worker_id=execution.worker_id,
                target_id=execution.target_id,
                call_ref=tool_call_ref,
                evidence_ref=evidence_ref,
            )
        except ToolCapabilityError as exc:
            raise ExecutionCoverageError(str(exc))
        covered = set(subject.expected_refs).issubset(set(observed))
        observation_id = f"covobs:{execution.attempt_id}:{subject.subject_id}:{tool_id}:{tool_call_ref}"
        observation = CoverageObservation(
            observation_id=observation_id,
            subject_id=subject.subject_id,
            layer=subject.layer,
            target_id=execution.target_id,
            attempt_id=execution.attempt_id,
            tc_id=execution.tc_id,
            case_version=execution.case_version,
            tool_id=tool_id,
            tool_call_ref=tool_call_ref,
            evidence_ref=evidence_ref,
            observed_refs=observed,
            metrics=dict(metrics or {}),
            covered=covered,
        )
        previous = self._observations.get(observation_id)
        if previous is not None and previous != observation:
            raise ExecutionCoverageError("COVERAGE_OBSERVATION_IMMUTABLE")
        self._observations[observation_id] = observation
        return observation

    def observations(self) -> Tuple[CoverageObservation, ...]:
        return tuple(self._observations[k] for k in sorted(self._observations))


class EmpiricalCoverageEvaluator:
    """Deterministic closure over observed evidence; claimed metrics are ignored."""

    def evaluate(
        self,
        *,
        registry: EmpiricalCoverageRegistry,
        observations: Iterable[CoverageObservation],
        target_id: str,
        claimed_metrics: Optional[Dict[str, Any]] = None,
    ) -> EmpiricalClosureResult:
        del claimed_metrics  # self-reported percentages never influence closure
        obs = [x for x in observations if x.target_id == target_id]
        by_subject: Dict[str, List[CoverageObservation]] = {}
        for item in obs:
            subject = registry.subjects.get(item.subject_id)
            if subject is None:
                raise ExecutionCoverageError("OBSERVATION_REFERENCES_UNKNOWN_SUBJECT")
            if item.layer != subject.layer:
                raise ExecutionCoverageError("OBSERVATION_LAYER_MISMATCH")
            by_subject.setdefault(item.subject_id, []).append(item)

        layer_results: List[LayerCoverageResult] = []
        all_gap_ids: List[str] = []
        critical_high: List[str] = []
        all_evidence: List[str] = []
        total_required = 0
        total_covered = 0

        for layer in sorted(registry.applicable_layers()):
            subjects = [s for s in registry.subjects.values() if s.layer == layer]
            required = sorted([s for s in subjects if s.required], key=lambda s: s.subject_id)
            optional = sorted([s for s in subjects if not s.required], key=lambda s: s.subject_id)
            gaps: List[EmpiricalCoverageGap] = []
            optional_gaps: List[EmpiricalCoverageGap] = []
            layer_evidence: List[str] = []
            covered_count = 0

            def gap_for(subject: EmpiricalCoverageSubject, reason: str) -> EmpiricalCoverageGap:
                return EmpiricalCoverageGap(
                    subject.subject_id, subject.layer, subject.dimension, subject.risk, reason, subject.existing_case_refs
                )

            for subject in required:
                subject_obs = by_subject.get(subject.subject_id, [])
                covered_obs = [x for x in subject_obs if x.covered]
                if covered_obs:
                    covered_count += 1
                    for item in covered_obs:
                        layer_evidence.append(item.evidence_ref)
                else:
                    reason = "NO_EXECUTION_COVERAGE_EVIDENCE" if not subject_obs else "EXPECTED_RUNTIME_REF_NOT_OBSERVED"
                    gap = gap_for(subject, reason)
                    gaps.append(gap)
                    all_gap_ids.append(subject.subject_id)
                    if subject.risk in {"CRITICAL", "HIGH"}:
                        critical_high.append(subject.subject_id)

            for subject in optional:
                subject_obs = by_subject.get(subject.subject_id, [])
                if not any(x.covered for x in subject_obs):
                    reason = "OPTIONAL_EVIDENCE_NOT_AVAILABLE" if not subject_obs else "OPTIONAL_EXPECTED_REF_NOT_OBSERVED"
                    optional_gaps.append(gap_for(subject, reason))
                else:
                    for item in subject_obs:
                        if item.covered:
                            layer_evidence.append(item.evidence_ref)

            required_count = len(required)
            total_required += required_count
            total_covered += covered_count
            if required_count and not layer_evidence:
                # Explicitly prevent a layer with applicable required subjects from passing with no real evidence.
                if not gaps:
                    raise ExecutionCoverageError("LAYER_REQUIRED_EVIDENCE_INCONSISTENCY")
            status = "SUFFICIENT" if not gaps else "NOT_SUFFICIENT"
            layer_results.append(
                LayerCoverageResult(
                    layer=layer,
                    status=status,
                    required_subject_count=required_count,
                    covered_required_count=covered_count,
                    coverage_ratio=(covered_count / required_count) if required_count else 1.0,
                    evidence_refs=tuple(sorted(set(layer_evidence))),
                    gaps=tuple(gaps),
                    optional_gaps=tuple(optional_gaps),
                )
            )
            all_evidence.extend(layer_evidence)

        if total_required == 0:
            raise ExecutionCoverageError("NO_REQUIRED_EMPIRICAL_COVERAGE_SUBJECTS")
        passed = not all_gap_ids
        return EmpiricalClosureResult(
            passed=passed,
            status="SUFFICIENT" if passed else "NOT_SUFFICIENT",
            target_id=target_id,
            layer_results=tuple(layer_results),
            required_subject_count=total_required,
            covered_required_count=total_covered,
            critical_high_gap_ids=tuple(sorted(set(critical_high))),
            gap_ids=tuple(sorted(set(all_gap_ids))),
            evidence_refs=tuple(sorted(set(all_evidence))),
        )


class ExecutionCoverageDeltaPlanner:
    """Route gaps back to exactly one professional layer.

    If a gap already has a frozen Case, the first action is DELTA_EXECUTION /
    evidence collection. If no Case can exercise the subject, route to the same
    layer Design Worker for DELTA_DESIGN.
    """

    def plan(self, *, result: EmpiricalClosureResult, registry: EmpiricalCoverageRegistry) -> Tuple[CoverageDeltaRequest, ...]:
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for sid in result.gap_ids:
            subject = registry.subjects[sid]
            action = "DELTA_EXECUTION" if subject.existing_case_refs else "DELTA_DESIGN"
            grouped.setdefault((subject.layer, action), []).append(sid)
        requests: List[CoverageDeltaRequest] = []
        for (layer, action), ids in sorted(grouped.items()):
            requests.append(
                CoverageDeltaRequest(
                    layer=layer,
                    action=action,
                    subject_ids=tuple(sorted(ids)),
                    reason="EMPIRICAL_EXECUTION_COVERAGE_GAP",
                    target_id=result.target_id,
                )
            )
        return tuple(requests)
