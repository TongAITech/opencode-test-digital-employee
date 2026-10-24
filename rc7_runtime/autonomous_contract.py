"""Shared RC7.1 autonomous-loop foundation contracts.

Runtime representation of RC-AUTONOMOUS-TEST-LOOP@1.0.0.  This module is
intentionally dependency-light so node/layer identities and coverage/delivery
contracts cannot drift between execution, evidence, reporting and CI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Mapping, Tuple


class AutonomousContractError(ValueError):
    pass


class CanonicalNode(str, Enum):
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    N4 = "N4"
    N5 = "N5"
    N6 = "N6"
    N7 = "N7"
    N8 = "N8"
    N9 = "N9"
    N10 = "N10"


NODE_NAMES: Dict[CanonicalNode, str] = {
    CanonicalNode.N1: "REALITY_ENVIRONMENT_RECON",
    CanonicalNode.N2: "REQUIREMENT_ANALYSIS",
    CanonicalNode.N3: "CODE_ANALYSIS",
    CanonicalNode.N4: "TEST_DESIGN",
    CanonicalNode.N5: "TEST_DATA_PRECONDITIONS",
    CanonicalNode.N6: "SCRIPT_BUILD_READINESS",
    CanonicalNode.N7: "COVERAGE_DRIVEN_EXECUTION_CLOSURE",
    CanonicalNode.N8: "FAILURE_DIAGNOSIS_RECOVERY",
    CanonicalNode.N9: "DEFECT_EVIDENCE_CLOSURE",
    CanonicalNode.N10: "MISSION_EVIDENCE_GLOBAL_CONVERGENCE",
}


class CanonicalLayer(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"


LAYER_ACTION_KINDS: Dict[CanonicalLayer, str] = {
    CanonicalLayer.L1: "CODE_UNIT",
    CanonicalLayer.L2: "DB_COMPONENT",
    CanonicalLayer.L3: "API_SERVICE",
    CanonicalLayer.L4: "UI_BROWSER",
    CanonicalLayer.L5: "CROSS_SYSTEM_E2E",
    CanonicalLayer.L6: "PERFORMANCE",
    CanonicalLayer.L7: "SECURITY",
}

LAYER_REQUIRED_TOOLS: Dict[CanonicalLayer, Tuple[str, ...]] = {
    CanonicalLayer.L1: ("maven", "junit"),
    CanonicalLayer.L2: ("database",),
    CanonicalLayer.L3: ("api-runtime",),
    CanonicalLayer.L4: ("browser-skill",),
    CanonicalLayer.L5: ("e2e-orchestrator",),
    CanonicalLayer.L6: ("k6",),
    CanonicalLayer.L7: ("zap",),
}

LAYER_ROLES: Dict[CanonicalLayer, str] = {
    layer: "%s_EXECUTE" % layer.value for layer in CanonicalLayer
}

CANONICAL_COVERAGE_TARGETS: Dict[CanonicalLayer, Dict[str, float]] = {
    CanonicalLayer.L1: {"line_coverage": 1.0, "logic_coverage": 1.0},
    CanonicalLayer.L2: {"mandatory_db_obligation_coverage": 1.0},
    CanonicalLayer.L3: {"mandatory_api_obligation_coverage": 1.0},
    CanonicalLayer.L4: {"mandatory_ui_obligation_coverage": 1.0},
    CanonicalLayer.L5: {"mandatory_e2e_journey_coverage": 1.0},
    CanonicalLayer.L6: {"planned_scenario_execution": 1.0, "threshold_evaluation": 1.0},
    CanonicalLayer.L7: {"security_obligation_execution": 1.0, "finding_disposition": 1.0},
}


class NodeLoopState(str, Enum):
    PENDING = "PENDING"
    TEAM_ASSIGNED = "TEAM_ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SELF_REVIEW = "SELF_REVIEW"
    GAP_DETECTED = "GAP_DETECTED"
    REPAIRING = "REPAIRING"
    READY_FOR_DIRECTOR_REVIEW = "READY_FOR_DIRECTOR_REVIEW"
    DIRECTOR_REJECTED = "DIRECTOR_REJECTED"
    BLOCKED = "BLOCKED"
    PASS = "PASS"


class CoverageObligationState(str, Enum):
    UNEXECUTED = "UNEXECUTED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COVERED_PASS = "COVERED_PASS"
    COVERED_FAIL = "COVERED_FAIL"
    BLOCKED = "BLOCKED"
    EXCLUDED_WITH_EVIDENCE = "EXCLUDED_WITH_EVIDENCE"


def require_node(value: str) -> CanonicalNode:
    try:
        return CanonicalNode(str(value))
    except ValueError as exc:
        raise AutonomousContractError("NON_CANONICAL_NODE:%s" % value) from exc


def require_layer(value: str) -> CanonicalLayer:
    try:
        return CanonicalLayer(str(value))
    except ValueError as exc:
        raise AutonomousContractError("NON_CANONICAL_LAYER:%s" % value) from exc


def canonical_execution_profile_specs() -> Dict[str, Dict[str, object]]:
    return {
        layer.value: {
            "role": LAYER_ROLES[layer],
            "required_tools": LAYER_REQUIRED_TOOLS[layer],
            "action_kind": LAYER_ACTION_KINDS[layer],
        }
        for layer in CanonicalLayer
    }


def canonical_coverage_targets() -> Dict[str, Dict[str, float]]:
    return {layer.value: dict(CANONICAL_COVERAGE_TARGETS[layer]) for layer in CanonicalLayer}


@dataclass(frozen=True)
class CoverageDenominatorSnapshot:
    mission_id: str
    layer: str
    source_revision: str
    target_id: str
    denominator_version: str
    denominator_hash: str
    obligation_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    excluded_obligation_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_layer(self.layer)
        for name in ("mission_id", "source_revision", "target_id", "denominator_version", "denominator_hash"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise AutonomousContractError("%s_REQUIRED" % name.upper())
        if not self.obligation_ids:
            raise AutonomousContractError("COVERAGE_DENOMINATOR_EMPTY")
        if len(set(self.obligation_ids)) != len(self.obligation_ids):
            raise AutonomousContractError("COVERAGE_DENOMINATOR_DUPLICATE_OBLIGATION")
        if not self.evidence_refs:
            raise AutonomousContractError("COVERAGE_DENOMINATOR_EVIDENCE_REQUIRED")
        unknown = set(self.excluded_obligation_ids) - set(self.obligation_ids)
        if unknown:
            raise AutonomousContractError("COVERAGE_EXCLUSION_OUTSIDE_DENOMINATOR")


@dataclass(frozen=True)
class LayerCoverageContract:
    layer: str
    metric_targets: Mapping[str, float]
    measurement_provider: str
    evidence_contract: str
    gap_routing_policy: str
    stop_policy: str

    def __post_init__(self) -> None:
        require_layer(self.layer)
        if not self.metric_targets:
            raise AutonomousContractError("LAYER_COVERAGE_TARGET_REQUIRED")
        canonical = CANONICAL_COVERAGE_TARGETS[require_layer(self.layer)]
        if dict(self.metric_targets) != canonical:
            raise AutonomousContractError("LAYER_COVERAGE_TARGET_DRIFT:%s" % self.layer)
        for name in ("measurement_provider", "evidence_contract", "gap_routing_policy", "stop_policy"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise AutonomousContractError("%s_REQUIRED" % name.upper())


@dataclass(frozen=True)
class LayerCoverageReceipt:
    layer: str
    source_revision: str
    target_id: str
    denominator_version: str
    denominator_hash: str
    covered: int
    total: int
    covered_pass: int
    covered_fail: int
    excluded_with_evidence: int
    open_gap_ids: Tuple[str, ...]
    blocked_obligation_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        require_layer(self.layer)
        if self.total <= 0 or self.covered < 0 or self.covered > self.total:
            raise AutonomousContractError("LAYER_COVERAGE_COUNTER_INVALID")
        if self.covered_pass < 0 or self.covered_fail < 0 or self.excluded_with_evidence < 0:
            raise AutonomousContractError("LAYER_COVERAGE_BREAKDOWN_INVALID")
        if self.covered_pass + self.covered_fail > self.covered:
            raise AutonomousContractError("LAYER_COVERAGE_RESULT_EXCEEDS_COVERED")
        if not self.evidence_refs:
            raise AutonomousContractError("LAYER_COVERAGE_EVIDENCE_REQUIRED")
        if self.status not in {"IN_PROGRESS", "READY", "BLOCKED"}:
            raise AutonomousContractError("LAYER_COVERAGE_STATUS_INVALID")

    @property
    def percent(self) -> float:
        return float(self.covered) / float(self.total)


@dataclass(frozen=True)
class NodeDeliveryPackage:
    mission_id: str
    run_id: str
    node_id: str
    input_version: str
    iteration_count: int
    artifact_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    unresolved_gap_ids: Tuple[str, ...]
    blocked_item_ids: Tuple[str, ...]
    terminal_status: str
    r1_refs: Tuple[str, ...]
    team_id: str = ""
    assignment_ids: Tuple[str, ...] = ()
    member_ids: Tuple[str, ...] = ()
    coverage_summary: Mapping[str, object] = field(default_factory=dict)
    risk_summary: Mapping[str, object] = field(default_factory=dict)
    reviewer_result: Mapping[str, object] = field(default_factory=dict)
    sufficiency_result: Mapping[str, object] = field(default_factory=dict)
    completion_receipt_ref: str = ""

    def __post_init__(self) -> None:
        require_node(self.node_id)
        for name in ("mission_id", "run_id", "input_version", "terminal_status"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise AutonomousContractError("%s_REQUIRED" % name.upper())
        if not isinstance(self.iteration_count, int) or self.iteration_count < 1:
            raise AutonomousContractError("NODE_ITERATION_COUNT_INVALID")
        if not self.artifact_refs:
            raise AutonomousContractError("NODE_DELIVERY_ARTIFACT_REQUIRED")
        if not self.evidence_refs:
            raise AutonomousContractError("NODE_DELIVERY_EVIDENCE_REQUIRED")
        if not self.r1_refs:
            raise AutonomousContractError("NODE_DELIVERY_R1_REF_REQUIRED")
        if self.terminal_status == NodeLoopState.PASS.value:
            raise AutonomousContractError("AGENT_DELIVERY_CANNOT_SELF_DECLARE_PASS")


CANONICAL_LAYER_IDS: Tuple[str, ...] = tuple(layer.value for layer in CanonicalLayer)
CANONICAL_NODE_IDS: Tuple[str, ...] = tuple(node.value for node in CanonicalNode)
