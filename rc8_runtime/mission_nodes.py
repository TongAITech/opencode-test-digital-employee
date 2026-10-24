"""RC8 N1-N10 mission-node adoption spine.

N1-N10 are the autonomous-test semantic layer above the existing RC8
MissionStage/WorkItem runtime.  This module deliberately does not replace the
existing stage state machine and it does not create a second PASS authority.

The physical dsh-node is called an ExecutionNode here to keep it distinct from
MissionNode (N1..N10).

Python 3.8 compatible for the bank runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple, Union

from .contracts import EventPlane, RC8ContractError, RuntimeEventEnvelope, RuntimeProducerKind
from .governance import StageInstance
from .mission_graph import MissionStageType


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


class MissionNodeType(str, Enum):
    N1_REALITY_ENVIRONMENT_RECON = "N1_REALITY_ENVIRONMENT_RECON"
    N2_REQUIREMENT_ANALYSIS = "N2_REQUIREMENT_ANALYSIS"
    N3_CODE_ANALYSIS = "N3_CODE_ANALYSIS"
    N4_TEST_DESIGN = "N4_TEST_DESIGN"
    N5_TEST_DATA_PRECONDITIONS = "N5_TEST_DATA_PRECONDITIONS"
    N6_SCRIPT_BUILD_READINESS = "N6_SCRIPT_BUILD_READINESS"
    N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE = "N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE"
    N8_FAILURE_DIAGNOSIS_RECOVERY = "N8_FAILURE_DIAGNOSIS_RECOVERY"
    N9_DEFECT_EVIDENCE_CLOSURE = "N9_DEFECT_EVIDENCE_CLOSURE"
    N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE = "N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE"


MISSION_NODE_SEQUENCE = (
    MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
    MissionNodeType.N2_REQUIREMENT_ANALYSIS,
    MissionNodeType.N3_CODE_ANALYSIS,
    MissionNodeType.N4_TEST_DESIGN,
    MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
    MissionNodeType.N6_SCRIPT_BUILD_READINESS,
    MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
    MissionNodeType.N8_FAILURE_DIAGNOSIS_RECOVERY,
    MissionNodeType.N9_DEFECT_EVIDENCE_CLOSURE,
    MissionNodeType.N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE,
)


class MissionNodeState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_DIRECTOR_REVIEW = "READY_FOR_DIRECTOR_REVIEW"
    REVIEW_ACCEPTED = "REVIEW_ACCEPTED"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"
    PASS = "PASS"
    INVALIDATED = "INVALIDATED"


class DirectorReviewDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    REJECTED = "REJECTED"


class MissionNodeGateResult(str, Enum):
    PASS = "PASS"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class MissionNodeStageBinding:
    stage_type: str
    mission_node_type: MissionNodeType
    semantic_note: str = "ADOPTED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_type", _required(self.stage_type, "stage_type"))
        if not isinstance(self.mission_node_type, MissionNodeType):
            raise RC8ContractError("MISSION_NODE_TYPE_INVALID")
        object.__setattr__(self, "semantic_note", _required(self.semantic_note, "semantic_note"))


_STAGE_BINDINGS = {
    MissionStageType.SCOPE_INTAKE: MissionNodeStageBinding(
        MissionStageType.SCOPE_INTAKE.value,
        MissionNodeType.N1_REALITY_ENVIRONMENT_RECON,
        "legacy scope intake is adopted by N1; real capability probes are added by N1 strengthening",
    ),
    MissionStageType.REQUIREMENT_ANALYSIS: MissionNodeStageBinding(
        MissionStageType.REQUIREMENT_ANALYSIS.value, MissionNodeType.N2_REQUIREMENT_ANALYSIS
    ),
    MissionStageType.REQUIREMENT_SUFFICIENCY: MissionNodeStageBinding(
        MissionStageType.REQUIREMENT_SUFFICIENCY.value, MissionNodeType.N2_REQUIREMENT_ANALYSIS
    ),
    MissionStageType.CODE_ANALYSIS: MissionNodeStageBinding(
        MissionStageType.CODE_ANALYSIS.value, MissionNodeType.N3_CODE_ANALYSIS
    ),
    MissionStageType.CODE_SUFFICIENCY: MissionNodeStageBinding(
        MissionStageType.CODE_SUFFICIENCY.value, MissionNodeType.N3_CODE_ANALYSIS
    ),
    MissionStageType.RISK_TEST_MODEL: MissionNodeStageBinding(
        MissionStageType.RISK_TEST_MODEL.value, MissionNodeType.N4_TEST_DESIGN
    ),
    MissionStageType.TEST_DESIGN: MissionNodeStageBinding(
        MissionStageType.TEST_DESIGN.value, MissionNodeType.N4_TEST_DESIGN
    ),
    MissionStageType.DESIGN_SUFFICIENCY: MissionNodeStageBinding(
        MissionStageType.DESIGN_SUFFICIENCY.value, MissionNodeType.N4_TEST_DESIGN
    ),
    MissionStageType.EXECUTABLE_SPEC: MissionNodeStageBinding(
        MissionStageType.EXECUTABLE_SPEC.value,
        MissionNodeType.N6_SCRIPT_BUILD_READINESS,
        "legacy graph orders N6 before N5; N5/N6 strengthening must reorder without hiding the debt",
    ),
    MissionStageType.PRECONDITION_DATA_PREP: MissionNodeStageBinding(
        MissionStageType.PRECONDITION_DATA_PREP.value,
        MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
        "legacy graph orders N6 before N5; PreparedAttempt adoption will repair ordering",
    ),
    MissionStageType.APPLICABLE_LAYER_EXECUTION: MissionNodeStageBinding(
        MissionStageType.APPLICABLE_LAYER_EXECUTION.value,
        MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
    ),
    MissionStageType.FAILURE_COVERAGE_EVALUATION: MissionNodeStageBinding(
        MissionStageType.FAILURE_COVERAGE_EVALUATION.value,
        MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
        "legacy mixed stage remains N7 until failure diagnosis is extracted into N8",
    ),
    MissionStageType.DELTA_REPAIR: MissionNodeStageBinding(
        MissionStageType.DELTA_REPAIR.value,
        MissionNodeType.N8_FAILURE_DIAGNOSIS_RECOVERY,
    ),
    MissionStageType.TARGETED_REEXECUTION: MissionNodeStageBinding(
        MissionStageType.TARGETED_REEXECUTION.value,
        MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE,
        "targeted re-execution returns repaired work to N7 coverage closure",
    ),
    MissionStageType.MISSION_SUFFICIENCY: MissionNodeStageBinding(
        MissionStageType.MISSION_SUFFICIENCY.value,
        MissionNodeType.N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE,
    ),
    MissionStageType.REPORT_RELEASE: MissionNodeStageBinding(
        MissionStageType.REPORT_RELEASE.value,
        MissionNodeType.N10_MISSION_EVIDENCE_GLOBAL_CONVERGENCE,
        "legacy report stage is retained but must become post-convergence reporting in N10 strengthening",
    ),
}

# Explicit semantic debt, never silently normalized.  The legacy graph currently
# runs EXECUTABLE_SPEC (N6) before PRECONDITION_DATA_PREP (N5).  Adoption keeps
# runtime compatibility; N5/N6 strengthening will repair this edge.
LEGACY_CROSS_NODE_TRANSITIONS = {
    (
        MissionNodeType.N6_SCRIPT_BUILD_READINESS,
        MissionNodeType.N5_TEST_DATA_PRECONDITIONS,
    ): "LEGACY_N6_BEFORE_N5_REQUIRES_REORDER",
}


def binding_for_stage(stage_type: Union[MissionStageType, str]) -> MissionNodeStageBinding:
    try:
        normalized = stage_type if isinstance(stage_type, MissionStageType) else MissionStageType(str(stage_type))
    except ValueError as exc:
        raise RC8ContractError("MISSION_STAGE_TYPE_UNKNOWN:%s" % stage_type) from exc
    binding = _STAGE_BINDINGS.get(normalized)
    if binding is None:
        raise RC8ContractError("MISSION_STAGE_UNBOUND:%s" % normalized.value)
    return binding


def all_stage_bindings() -> Tuple[MissionNodeStageBinding, ...]:
    """Return one deterministic N1-N10 binding for every existing RC8 stage."""
    return tuple(binding_for_stage(stage_type) for stage_type in MissionStageType)


@dataclass(frozen=True)
class MissionNodeInstance:
    mission_node_id: str
    test_run_id: str
    node_type: MissionNodeType
    scope_version: str
    state: MissionNodeState = MissionNodeState.PENDING
    stage_instance_ids: Tuple[str, ...] = field(default_factory=tuple)
    predecessor_node_ids: Tuple[str, ...] = field(default_factory=tuple)
    output_refs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("mission_node_id", "test_run_id", "scope_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.node_type, MissionNodeType):
            raise RC8ContractError("MISSION_NODE_TYPE_INVALID")
        if not isinstance(self.state, MissionNodeState):
            raise RC8ContractError("MISSION_NODE_STATE_INVALID")
        for name in ("stage_instance_ids", "predecessor_node_ids", "output_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))


@dataclass(frozen=True)
class NodeDeliveryPackage:
    package_id: str
    test_run_id: str
    mission_node_id: str
    attempt_ref: str
    evidence_refs: Tuple[str, ...]
    output_refs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("package_id", "test_run_id", "mission_node_id", "attempt_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "output_refs", _refs(self.output_refs, "output_refs"))
        if not self.evidence_refs:
            raise RC8ContractError("NODE_DELIVERY_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class DirectorReviewReceipt:
    receipt_id: str
    test_run_id: str
    mission_node_id: str
    director_execution_node_id: str
    decision: DirectorReviewDecision
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("receipt_id", "test_run_id", "mission_node_id", "director_execution_node_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.decision, DirectorReviewDecision):
            raise RC8ContractError("DIRECTOR_REVIEW_DECISION_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise RC8ContractError("DIRECTOR_REVIEW_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class MissionNodeGateDecision:
    decision_id: str
    test_run_id: str
    mission_node_id: str
    result: MissionNodeGateResult
    policy_version: str
    evidence_refs: Tuple[str, ...]
    authority: str = "CENTER"

    def __post_init__(self) -> None:
        for name in ("decision_id", "test_run_id", "mission_node_id", "policy_version", "authority"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.authority != "CENTER":
            raise RC8ContractError("MISSION_NODE_GATE_REQUIRES_CENTER_AUTHORITY")
        if not isinstance(self.result, MissionNodeGateResult):
            raise RC8ContractError("MISSION_NODE_GATE_RESULT_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise RC8ContractError("MISSION_NODE_GATE_REQUIRES_EVIDENCE")


class MissionNodeAdoptionGraph:
    """Compatibility aggregate binding existing StageInstances to N1-N10.

    This is not a second workflow engine.  Stage execution/state remains owned by
    MissionGraphRuntime; this aggregate only supplies the durable semantic parent
    identity needed by N1-N10 and R1 provenance.
    """

    def __init__(self, test_run_id: str, scope_version: str) -> None:
        self.test_run_id = _required(test_run_id, "test_run_id")
        self.scope_version = _required(scope_version, "scope_version")
        self._nodes: Dict[MissionNodeType, MissionNodeInstance] = {}
        for node_type in MISSION_NODE_SEQUENCE:
            mission_node_id = "%s:%s:%s" % (self.test_run_id, self.scope_version, node_type.value)
            self._nodes[node_type] = MissionNodeInstance(
                mission_node_id=mission_node_id,
                test_run_id=self.test_run_id,
                node_type=node_type,
                scope_version=self.scope_version,
            )

    def node(self, node_type: MissionNodeType) -> MissionNodeInstance:
        if not isinstance(node_type, MissionNodeType):
            raise RC8ContractError("MISSION_NODE_TYPE_INVALID")
        return self._nodes[node_type]

    def bind_stage(self, stage: StageInstance) -> MissionNodeInstance:
        if not isinstance(stage, StageInstance):
            raise RC8ContractError("STAGE_INSTANCE_REQUIRED")
        if stage.test_run_id != self.test_run_id:
            raise RC8ContractError("MISSION_NODE_STAGE_TEST_RUN_MISMATCH")
        if stage.scope_version != self.scope_version:
            raise RC8ContractError("MISSION_NODE_STAGE_SCOPE_MISMATCH")
        binding = binding_for_stage(stage.stage_type)
        current = self._nodes[binding.mission_node_type]
        stage_ids = current.stage_instance_ids
        if stage.stage_instance_id not in stage_ids:
            stage_ids = stage_ids + (stage.stage_instance_id,)
        updated = replace(current, stage_instance_ids=stage_ids)
        self._nodes[binding.mission_node_type] = updated
        return updated

    def mission_node_for_stage(self, stage_instance_id: str) -> MissionNodeInstance:
        stage_instance_id = _required(stage_instance_id, "stage_instance_id")
        for node_type in MISSION_NODE_SEQUENCE:
            node = self._nodes[node_type]
            if stage_instance_id in node.stage_instance_ids:
                return node
        raise RC8ContractError("MISSION_NODE_STAGE_INSTANCE_UNBOUND:%s" % stage_instance_id)

    def nodes(self) -> Tuple[MissionNodeInstance, ...]:
        return tuple(self._nodes[node_type] for node_type in MISSION_NODE_SEQUENCE)


@dataclass(frozen=True)
class MissionRuntimeEventEnvelope(RuntimeEventEnvelope):
    """Runtime event with top-level MissionNode and ExecutionNode provenance."""

    mission_node_id: str = ""
    mission_node_type: str = ""
    execution_node_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "mission_node_id", _required(self.mission_node_id, "mission_node_id"))
        object.__setattr__(self, "mission_node_type", _required(self.mission_node_type, "mission_node_type"))
        object.__setattr__(self, "execution_node_id", _required(self.execution_node_id, "execution_node_id"))
        try:
            MissionNodeType(self.mission_node_type)
        except ValueError as exc:
            raise RC8ContractError("MISSION_NODE_TYPE_INVALID") from exc
        if self.execution_node_id != self.node_id:
            raise RC8ContractError("RUNTIME_EXECUTION_NODE_MISMATCH")


def mission_runtime_event(
    *,
    event_id: str,
    test_run_id: str,
    work_item_id: str,
    execution_node_id: str,
    mission_node_id: str,
    mission_node_type: MissionNodeType,
    producer_kind: RuntimeProducerKind,
    producer_ref: str,
    event_type: str,
    sequence: int,
    **kwargs: object
) -> MissionRuntimeEventEnvelope:
    """Construct an R1-compatible event carrying N1-N10 provenance."""
    if not isinstance(mission_node_type, MissionNodeType):
        raise RC8ContractError("MISSION_NODE_TYPE_INVALID")
    occurred_at = kwargs.get("occurred_at")
    if occurred_at is not None and (not isinstance(occurred_at, int) or occurred_at < 0):
        raise RC8ContractError("RUNTIME_EVENT_OCCURRED_AT_INVALID")
    values = {
        "event_id": event_id,
        "test_run_id": test_run_id,
        "work_item_id": work_item_id,
        "node_id": execution_node_id,
        "execution_node_id": execution_node_id,
        "mission_node_id": mission_node_id,
        "mission_node_type": mission_node_type.value,
        "producer_kind": producer_kind,
        "producer_ref": producer_ref,
        "event_type": event_type,
        "sequence": sequence,
        "case_id": kwargs.get("case_id") if isinstance(kwargs.get("case_id"), str) else None,
        "attempt_id": kwargs.get("attempt_id") if isinstance(kwargs.get("attempt_id"), str) else None,
        "step_id": kwargs.get("step_id") if isinstance(kwargs.get("step_id"), str) else None,
        "refs": list(kwargs.get("refs") or []),
        "data": dict(kwargs.get("data") or {}),
        "plane": EventPlane.RUNTIME,
    }
    if occurred_at is not None:
        values["occurred_at"] = occurred_at
    return MissionRuntimeEventEnvelope(**values)
