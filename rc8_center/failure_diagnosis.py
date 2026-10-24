"""RC8 N8 failure diagnosis, deterministic gap routing and repair receipts.

N8 never turns a failing test directly into a defect or a blind retry. Workers
submit failure observations and diagnostic evidence. Center applies a frozen
routing policy, creates repair work only for repairable classes, and permits a
successor attempt only after an evidence-backed repair receipt.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple

from rc8_runtime.mission_nodes import MissionNodeType


class FailureDiagnosisError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FailureDiagnosisError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise FailureDiagnosisError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise FailureDiagnosisError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class FailureClassification(str, Enum):
    SCRIPT = "SCRIPT"
    SPEC_DESIGN = "SPEC_DESIGN"
    ORACLE = "ORACLE"
    DATA = "DATA"
    PRECONDITION = "PRECONDITION"
    AUTH = "AUTH"
    ROUTE = "ROUTE"
    TOOL = "TOOL"
    ENVIRONMENT = "ENVIRONMENT"
    DEPENDENCY = "DEPENDENCY"
    TRANSIENT = "TRANSIENT"
    FLAKY = "FLAKY"
    PRODUCT = "PRODUCT"
    UNKNOWN = "UNKNOWN"


class RouteFailureScope(str, Enum):
    SOURCE_TRUTH = "SOURCE_TRUTH"
    EXECUTION_BINDING = "EXECUTION_BINDING"


class RepairResult(str, Enum):
    REPAIRED = "REPAIRED"
    NOT_REPAIRED = "NOT_REPAIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class FailureObservation:
    observation_id: str
    test_run_id: str
    source_mission_node_id: str
    source_attempt_id: str
    source_case_id: str
    summary: str
    evidence_refs: Tuple[str, ...]
    observed_at: int
    source_assertion_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("observation_id", "test_run_id", "source_mission_node_id", "source_attempt_id", "source_case_id", "summary"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise FailureDiagnosisError("FAILURE_OBSERVATION_REQUIRES_EVIDENCE")
        if not isinstance(self.observed_at, int) or self.observed_at < 0:
            raise FailureDiagnosisError("FAILURE_OBSERVATION_TIME_INVALID")
        if self.source_assertion_id is not None:
            object.__setattr__(self, "source_assertion_id", _required(self.source_assertion_id, "source_assertion_id"))


@dataclass(frozen=True)
class DiagnosticEvidence:
    diagnostic_id: str
    observation_id: str
    classification: FailureClassification
    classifier_ref: str
    reason_code: str
    evidence_refs: Tuple[str, ...]
    diagnosed_at: int
    route_scope: Optional[RouteFailureScope] = None

    def __post_init__(self) -> None:
        for name in ("diagnostic_id", "observation_id", "classifier_ref", "reason_code"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.classification, FailureClassification):
            raise FailureDiagnosisError("FAILURE_CLASSIFICATION_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise FailureDiagnosisError("DIAGNOSTIC_EVIDENCE_REQUIRED")
        if not isinstance(self.diagnosed_at, int) or self.diagnosed_at < 0:
            raise FailureDiagnosisError("DIAGNOSTIC_TIME_INVALID")
        if self.classification == FailureClassification.ROUTE:
            if not isinstance(self.route_scope, RouteFailureScope):
                raise FailureDiagnosisError("ROUTE_FAILURE_SCOPE_REQUIRED")
        elif self.route_scope is not None:
            raise FailureDiagnosisError("ROUTE_FAILURE_SCOPE_ONLY_FOR_ROUTE")


@dataclass(frozen=True)
class GapRouteDecision:
    decision_id: str
    test_run_id: str
    observation_id: str
    diagnostic_id: str
    gap_id: str
    classification: FailureClassification
    target_mission_node: MissionNodeType
    policy_code: str
    repairable: bool
    evidence_refs: Tuple[str, ...]
    decided_at: int
    authority: str = "CENTER"

    def __post_init__(self) -> None:
        for name in ("decision_id", "test_run_id", "observation_id", "diagnostic_id", "gap_id", "policy_code", "authority"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.authority != "CENTER":
            raise FailureDiagnosisError("GAP_ROUTE_REQUIRES_CENTER_AUTHORITY")
        if not isinstance(self.classification, FailureClassification):
            raise FailureDiagnosisError("FAILURE_CLASSIFICATION_INVALID")
        if not isinstance(self.target_mission_node, MissionNodeType):
            raise FailureDiagnosisError("GAP_ROUTE_TARGET_INVALID")
        if not isinstance(self.repairable, bool):
            raise FailureDiagnosisError("GAP_ROUTE_REPAIRABLE_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise FailureDiagnosisError("GAP_ROUTE_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class RepairWorkOrder:
    work_order_id: str
    test_run_id: str
    route_decision_id: str
    gap_id: str
    predecessor_attempt_id: str
    target_mission_node: MissionNodeType
    repair_strategy: str
    evidence_refs: Tuple[str, ...]
    created_at: int

    def __post_init__(self) -> None:
        for name in ("work_order_id", "test_run_id", "route_decision_id", "gap_id", "predecessor_attempt_id", "repair_strategy"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.target_mission_node, MissionNodeType):
            raise FailureDiagnosisError("REPAIR_WORK_ORDER_TARGET_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise FailureDiagnosisError("REPAIR_WORK_ORDER_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class RepairReceipt:
    receipt_id: str
    work_order_id: str
    result: RepairResult
    evidence_refs: Tuple[str, ...]
    recorded_at: int

    def __post_init__(self) -> None:
        for name in ("receipt_id", "work_order_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.result, RepairResult):
            raise FailureDiagnosisError("REPAIR_RESULT_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise FailureDiagnosisError("REPAIR_RECEIPT_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class SuccessorAttempt:
    successor_id: str
    test_run_id: str
    work_order_id: str
    repair_receipt_id: str
    predecessor_attempt_id: str
    successor_attempt_id: str
    authorized_at: int

    def __post_init__(self) -> None:
        for name in ("successor_id", "test_run_id", "work_order_id", "repair_receipt_id", "predecessor_attempt_id", "successor_attempt_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.predecessor_attempt_id == self.successor_attempt_id:
            raise FailureDiagnosisError("SUCCESSOR_ATTEMPT_MUST_BE_NEW")


class FailureDiagnosisRepository(Protocol):
    def save_observation(self, value: FailureObservation) -> None: ...
    def get_observation(self, observation_id: str) -> Optional[FailureObservation]: ...
    def save_diagnostic(self, value: DiagnosticEvidence) -> None: ...
    def get_diagnostic(self, diagnostic_id: str) -> Optional[DiagnosticEvidence]: ...
    def save_route(self, value: GapRouteDecision) -> None: ...
    def get_route(self, decision_id: str) -> Optional[GapRouteDecision]: ...
    def save_work_order(self, value: RepairWorkOrder) -> None: ...
    def get_work_order(self, work_order_id: str) -> Optional[RepairWorkOrder]: ...
    def save_repair_receipt(self, value: RepairReceipt) -> None: ...
    def get_repair_receipt(self, receipt_id: str) -> Optional[RepairReceipt]: ...
    def save_successor(self, value: SuccessorAttempt) -> None: ...


class MemoryFailureDiagnosisRepository:
    def __init__(self) -> None:
        self.observations: Dict[str, FailureObservation] = {}
        self.diagnostics: Dict[str, DiagnosticEvidence] = {}
        self.routes: Dict[str, GapRouteDecision] = {}
        self.work_orders: Dict[str, RepairWorkOrder] = {}
        self.receipts: Dict[str, RepairReceipt] = {}
        self.successors: Dict[str, SuccessorAttempt] = {}

    @staticmethod
    def _put(store: Dict[str, object], key: str, value: object, conflict: str) -> None:
        existing = store.get(key)
        if existing is not None and existing != value:
            raise FailureDiagnosisError(conflict)
        store[key] = value

    def save_observation(self, value: FailureObservation) -> None: self._put(self.observations, value.observation_id, value, "FAILURE_OBSERVATION_ID_CONFLICT")
    def get_observation(self, observation_id: str) -> Optional[FailureObservation]: return self.observations.get(observation_id)
    def save_diagnostic(self, value: DiagnosticEvidence) -> None: self._put(self.diagnostics, value.diagnostic_id, value, "DIAGNOSTIC_ID_CONFLICT")
    def get_diagnostic(self, diagnostic_id: str) -> Optional[DiagnosticEvidence]: return self.diagnostics.get(diagnostic_id)
    def save_route(self, value: GapRouteDecision) -> None: self._put(self.routes, value.decision_id, value, "GAP_ROUTE_ID_CONFLICT")
    def get_route(self, decision_id: str) -> Optional[GapRouteDecision]: return self.routes.get(decision_id)
    def save_work_order(self, value: RepairWorkOrder) -> None: self._put(self.work_orders, value.work_order_id, value, "REPAIR_WORK_ORDER_ID_CONFLICT")
    def get_work_order(self, work_order_id: str) -> Optional[RepairWorkOrder]: return self.work_orders.get(work_order_id)
    def save_repair_receipt(self, value: RepairReceipt) -> None: self._put(self.receipts, value.receipt_id, value, "REPAIR_RECEIPT_ID_CONFLICT")
    def get_repair_receipt(self, receipt_id: str) -> Optional[RepairReceipt]: return self.receipts.get(receipt_id)
    def save_successor(self, value: SuccessorAttempt) -> None:
        if any(item.work_order_id == value.work_order_id for item in self.successors.values() if item.successor_id != value.successor_id):
            raise FailureDiagnosisError("REPAIR_WORK_ORDER_ALREADY_HAS_SUCCESSOR")
        self._put(self.successors, value.successor_id, value, "SUCCESSOR_ID_CONFLICT")


_ROUTE_POLICY = {
    FailureClassification.SCRIPT: (MissionNodeType.N6_SCRIPT_BUILD_READINESS, "REPAIR_SCRIPT", True),
    FailureClassification.SPEC_DESIGN: (MissionNodeType.N4_TEST_DESIGN, "REPAIR_DESIGN", True),
    FailureClassification.ORACLE: (MissionNodeType.N4_TEST_DESIGN, "REPAIR_ORACLE", True),
    FailureClassification.DATA: (MissionNodeType.N5_TEST_DATA_PRECONDITIONS, "REFRESH_TEST_DATA", True),
    FailureClassification.PRECONDITION: (MissionNodeType.N5_TEST_DATA_PRECONDITIONS, "REBUILD_PRECONDITION", True),
    FailureClassification.AUTH: (MissionNodeType.N5_TEST_DATA_PRECONDITIONS, "FRESH_AUTH_REBIND", True),
    FailureClassification.TOOL: (MissionNodeType.N1_REALITY_ENVIRONMENT_RECON, "RECOVER_TOOL_CAPABILITY", True),
    FailureClassification.ENVIRONMENT: (MissionNodeType.N1_REALITY_ENVIRONMENT_RECON, "RECOVER_ENVIRONMENT", True),
    FailureClassification.DEPENDENCY: (MissionNodeType.N1_REALITY_ENVIRONMENT_RECON, "RECOVER_DEPENDENCY", True),
    FailureClassification.TRANSIENT: (MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE, "TARGETED_REEXECUTION", True),
    FailureClassification.FLAKY: (MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE, "REPRODUCIBILITY_THEN_REEXECUTION", True),
    FailureClassification.PRODUCT: (MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE, "ENTER_DEFECT_CLOSURE", False),
    FailureClassification.UNKNOWN: (MissionNodeType.N8_FAILURE_DIAGNOSIS_RECOVERY, "CONTINUE_DIAGNOSIS", False),
}


class CenterFailureDiagnosisService:
    policy_version = "rc8-n8-gap-router-v1"

    def __init__(self, repository: FailureDiagnosisRepository, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.now_fn = now_fn or (lambda: int(time.time()))

    def observe(self, *, observation_id: str, test_run_id: str, source_mission_node_id: str, source_attempt_id: str, source_case_id: str, summary: str, evidence_refs: Sequence[str], source_assertion_id: Optional[str] = None) -> FailureObservation:
        value = FailureObservation(observation_id=observation_id, test_run_id=test_run_id, source_mission_node_id=source_mission_node_id, source_attempt_id=source_attempt_id, source_case_id=source_case_id, summary=summary, evidence_refs=tuple(evidence_refs), observed_at=int(self.now_fn()), source_assertion_id=source_assertion_id)
        self.repository.save_observation(value)
        return value

    def diagnose(self, *, diagnostic_id: str, observation_id: str, classification: FailureClassification, classifier_ref: str, reason_code: str, evidence_refs: Sequence[str], route_scope: Optional[RouteFailureScope] = None) -> DiagnosticEvidence:
        if self.repository.get_observation(observation_id) is None:
            raise FailureDiagnosisError("FAILURE_OBSERVATION_NOT_FOUND")
        value = DiagnosticEvidence(diagnostic_id=diagnostic_id, observation_id=observation_id, classification=classification, classifier_ref=classifier_ref, reason_code=reason_code, evidence_refs=tuple(evidence_refs), diagnosed_at=int(self.now_fn()), route_scope=route_scope)
        self.repository.save_diagnostic(value)
        return value

    def route(self, *, decision_id: str, diagnostic_id: str, gap_id: str) -> GapRouteDecision:
        diagnostic = self.repository.get_diagnostic(diagnostic_id)
        if diagnostic is None:
            raise FailureDiagnosisError("DIAGNOSTIC_NOT_FOUND")
        observation = self.repository.get_observation(diagnostic.observation_id)
        if observation is None:
            raise FailureDiagnosisError("FAILURE_OBSERVATION_NOT_FOUND")
        if diagnostic.classification == FailureClassification.ROUTE:
            if diagnostic.route_scope == RouteFailureScope.SOURCE_TRUTH:
                target, policy_code, repairable = MissionNodeType.N3_CODE_ANALYSIS, "REDISCOVER_ROUTE_SOURCE_TRUTH", True
            else:
                target, policy_code, repairable = MissionNodeType.N6_SCRIPT_BUILD_READINESS, "REBIND_EXECUTION_ROUTE", True
        else:
            target, policy_code, repairable = _ROUTE_POLICY[diagnostic.classification]
        decision = GapRouteDecision(decision_id=decision_id, test_run_id=observation.test_run_id, observation_id=observation.observation_id, diagnostic_id=diagnostic.diagnostic_id, gap_id=gap_id, classification=diagnostic.classification, target_mission_node=target, policy_code=policy_code, repairable=repairable, evidence_refs=diagnostic.evidence_refs, decided_at=int(self.now_fn()))
        self.repository.save_route(decision)
        return decision

    def create_repair_work_order(self, *, work_order_id: str, route_decision_id: str, evidence_refs: Sequence[str]) -> RepairWorkOrder:
        decision = self.repository.get_route(route_decision_id)
        if decision is None:
            raise FailureDiagnosisError("GAP_ROUTE_NOT_FOUND")
        if not decision.repairable:
            raise FailureDiagnosisError("NON_REPAIRABLE_ROUTE_FORBIDS_REPAIR_WORK_ORDER")
        observation = self.repository.get_observation(decision.observation_id)
        if observation is None:
            raise FailureDiagnosisError("FAILURE_OBSERVATION_NOT_FOUND")
        value = RepairWorkOrder(work_order_id=work_order_id, test_run_id=decision.test_run_id, route_decision_id=decision.decision_id, gap_id=decision.gap_id, predecessor_attempt_id=observation.source_attempt_id, target_mission_node=decision.target_mission_node, repair_strategy=decision.policy_code, evidence_refs=tuple(evidence_refs), created_at=int(self.now_fn()))
        self.repository.save_work_order(value)
        return value

    def record_repair_receipt(self, *, receipt_id: str, work_order_id: str, result: RepairResult, evidence_refs: Sequence[str]) -> RepairReceipt:
        if self.repository.get_work_order(work_order_id) is None:
            raise FailureDiagnosisError("REPAIR_WORK_ORDER_NOT_FOUND")
        value = RepairReceipt(receipt_id=receipt_id, work_order_id=work_order_id, result=result, evidence_refs=tuple(evidence_refs), recorded_at=int(self.now_fn()))
        self.repository.save_repair_receipt(value)
        return value

    def authorize_successor_attempt(self, *, successor_id: str, work_order_id: str, repair_receipt_id: str, successor_attempt_id: str) -> SuccessorAttempt:
        order = self.repository.get_work_order(work_order_id)
        if order is None:
            raise FailureDiagnosisError("REPAIR_WORK_ORDER_NOT_FOUND")
        receipt = self.repository.get_repair_receipt(repair_receipt_id)
        if receipt is None or receipt.work_order_id != work_order_id:
            raise FailureDiagnosisError("REPAIR_RECEIPT_MISMATCH")
        if receipt.result != RepairResult.REPAIRED:
            raise FailureDiagnosisError("SUCCESSOR_ATTEMPT_REQUIRES_REPAIRED_RECEIPT")
        value = SuccessorAttempt(successor_id=successor_id, test_run_id=order.test_run_id, work_order_id=order.work_order_id, repair_receipt_id=receipt.receipt_id, predecessor_attempt_id=order.predecessor_attempt_id, successor_attempt_id=successor_attempt_id, authorized_at=int(self.now_fn()))
        self.repository.save_successor(value)
        return value
