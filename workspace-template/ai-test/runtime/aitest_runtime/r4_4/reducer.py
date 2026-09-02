from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState

from .contracts import (
    EVENT_TYPES,
    R44_EXECUTION_LINKAGE_RECORDED,
    R44_FIX_VALIDATION_ASSESSED,
    R44_OPERATION_SUPERSEDED,
    R44_POST_FIX_VALIDATION_OPENED,
    R44_R3_SUFFICIENCY_EVALUATION_ACKNOWLEDGED,
    R44_R3_SUFFICIENCY_EVALUATION_REQUESTED,
    R44_REGRESSION_CLOSURE_RECORDED,
    R44_TARGETED_REGRESSION_WORKSET_ASSEMBLED,
    ExecutionLinkage,
    FixValidationAssessment,
    PostFixOperationalState,
    PostFixValidationCycle,
    SufficiencyHandoffReceipt,
    SufficiencyHandoffStatus,
    TargetedRegressionClosure,
    TargetedRegressionWorkSet,
)
from .errors import CONFLICT, NOT_FOUND, R44Error, UNKNOWN_EVENT, UNKNOWN_SCHEMA


def _unique(values: tuple[Any, ...], name: str) -> None:
    ids = [getattr(item, "cycle_id", getattr(item, "workset_id", getattr(item, "linkage_id", getattr(item, "fix_validation_id", getattr(item, "closure_id", getattr(item, "receipt_id", None)))))) for item in values]
    if len(ids) != len(set(ids)):
        raise R44Error(CONFLICT, f"{name} identity is already present")


@dataclass(frozen=True)
class R44State:
    mission_id: str
    validation_cycles: tuple[PostFixValidationCycle, ...] = ()
    regression_worksets: tuple[TargetedRegressionWorkSet, ...] = ()
    execution_linkages: tuple[ExecutionLinkage, ...] = ()
    fix_validation_assessments: tuple[FixValidationAssessment, ...] = ()
    regression_closures: tuple[TargetedRegressionClosure, ...] = ()
    sufficiency_handoff_receipts: tuple[SufficiencyHandoffReceipt, ...] = ()
    supersession_relations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str) or not self.mission_id.strip():
            raise R44Error("R4_4_STATE_INVALID", "mission_id is required")
        for name in ("validation_cycles", "regression_worksets", "execution_linkages", "fix_validation_assessments", "regression_closures", "sufficiency_handoff_receipts"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise R44Error("R4_4_STATE_INVALID", f"{name} must be immutable")
            _unique(values, name)
            if any(getattr(item, "stream_owner_mission_id", getattr(item, "owner_mission_id", self.mission_id)) != self.mission_id for item in values if hasattr(item, "stream_owner_mission_id") or hasattr(item, "owner_mission_id")):
                raise R44Error("R4_4_SCOPE_MISMATCH", f"{name} contains a cross-Mission record")
        if not isinstance(self.supersession_relations, tuple):
            raise R44Error("R4_4_STATE_INVALID", "supersession_relations must be immutable")

    def cycle(self, cycle_id: str) -> PostFixValidationCycle | None:
        return next((item for item in self.validation_cycles if item.cycle_id == cycle_id), None)

    def workset(self, workset_id: str) -> TargetedRegressionWorkSet | None:
        return next((item for item in self.regression_worksets if item.workset_id == workset_id), None)

    def linkage(self, linkage_id: str) -> ExecutionLinkage | None:
        return next((item for item in self.execution_linkages if item.linkage_id == linkage_id), None)

    def assessment(self, fix_validation_id: str) -> FixValidationAssessment | None:
        return next((item for item in self.fix_validation_assessments if item.fix_validation_id == fix_validation_id), None)

    def closure(self, closure_id: str) -> TargetedRegressionClosure | None:
        return next((item for item in self.regression_closures if item.closure_id == closure_id), None)

    def receipt(self, receipt_id: str) -> SufficiencyHandoffReceipt | None:
        return next((item for item in self.sufficiency_handoff_receipts if item.receipt_id == receipt_id), None)

    def current_cycle(self, cycle_id: str) -> PostFixValidationCycle | None:
        cycle = self.cycle(cycle_id)
        if cycle is None or self.is_superseded("CYCLE", cycle_id):
            return None
        return cycle

    def worksets_for_cycle(self, cycle_id: str) -> tuple[TargetedRegressionWorkSet, ...]:
        return tuple(item for item in self.regression_worksets if item.cycle_ref.object_id == cycle_id)

    def current_workset(self, cycle_id: str) -> TargetedRegressionWorkSet | None:
        candidates = [item for item in self.worksets_for_cycle(cycle_id) if not self.is_superseded("WORKSET", item.workset_id)]
        return max(candidates, key=lambda item: item.created_seq, default=None)

    def assessments_for_cycle(self, cycle_id: str) -> tuple[FixValidationAssessment, ...]:
        return tuple(item for item in self.fix_validation_assessments if item.cycle_ref.object_id == cycle_id)

    def closures_for_workset(self, workset_id: str) -> tuple[TargetedRegressionClosure, ...]:
        return tuple(item for item in self.regression_closures if item.workset_ref.object_id == workset_id)

    def receipts_for_cycle(self, cycle_id: str) -> tuple[SufficiencyHandoffReceipt, ...]:
        return tuple(item for item in self.sufficiency_handoff_receipts if item.cycle_ref.object_id == cycle_id)

    def latest_receipt(self, handoff_request_id: str) -> SufficiencyHandoffReceipt | None:
        values = [item for item in self.sufficiency_handoff_receipts if item.handoff_request_id == handoff_request_id]
        return max(values, key=lambda item: item.created_seq, default=None)

    def is_superseded(self, operation_kind: str, operation_id: str) -> bool:
        return any(str(item.get("operation_kind")) == operation_kind and str(item.get("operation_id")) == operation_id for item in self.supersession_relations)

    @property
    def cycle_by_fix_detection_scope(self) -> Mapping[str, str]:
        return {item.fix_detection_ref.object_id: item.cycle_id for item in self.validation_cycles if not self.is_superseded("CYCLE", item.cycle_id)}

    @property
    def worksets_by_cycle(self) -> Mapping[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {}
        for item in self.regression_worksets:
            result.setdefault(item.cycle_ref.object_id, []).append(item.workset_id)
        return {key: tuple(sorted(value)) for key, value in sorted(result.items())}

    @property
    def assessment_by_cycle(self) -> Mapping[str, str]:
        return {item.cycle_ref.object_id: item.fix_validation_id for item in self.fix_validation_assessments}

    @property
    def closure_by_workset(self) -> Mapping[str, str]:
        return {item.workset_ref.object_id: item.closure_id for item in self.regression_closures}

    @property
    def current_operational_state(self) -> Mapping[str, str]:
        return {item.cycle_id: self.derive_operational_state(item.cycle_id).value for item in self.validation_cycles}

    def derive_operational_state(self, cycle_id: str) -> PostFixOperationalState:
        cycle = self.cycle(cycle_id)
        if cycle is None:
            raise R44Error(NOT_FOUND, f"cycle not found: {cycle_id}")
        if self.is_superseded("CYCLE", cycle_id):
            return PostFixOperationalState.SUPERSEDED
        assessments = self.assessments_for_cycle(cycle_id)
        assessment = max(assessments, key=lambda item: item.created_seq, default=None)
        if assessment is not None:
            if assessment.outcome.value == "FAIL":
                return PostFixOperationalState.VALIDATION_FAILED
            if assessment.outcome.value in {"BLOCKED", "CONFLICT"}:
                return PostFixOperationalState.VALIDATION_BLOCKED
            if assessment.outcome.value == "INCOMPLETE":
                return PostFixOperationalState.INCOMPLETE
        workset = self.current_workset(cycle_id)
        if assessment is None:
            return PostFixOperationalState.REGRESSION_PENDING if workset else PostFixOperationalState.VALIDATION_PENDING
        if assessment.outcome.value == "PASS":
            if workset is None:
                return PostFixOperationalState.REGRESSION_PENDING
            closures = self.closures_for_workset(workset.workset_id)
            closure = max(closures, key=lambda item: item.created_seq, default=None)
            receipt = self.latest_receipt_for_cycle(cycle_id)
            if closure is not None and closure.outcome.value == "FAIL":
                return PostFixOperationalState.REGRESSION_FAILED
            if closure is not None and closure.outcome.value in {"BLOCKED", "CONFLICT"}:
                return PostFixOperationalState.VALIDATION_BLOCKED
            if closure is None or closure.outcome.value != "PASS" or receipt is None or receipt.request_status is not SufficiencyHandoffStatus.ACKNOWLEDGED:
                return PostFixOperationalState.REGRESSION_PENDING
            return PostFixOperationalState.POST_FIX_VALIDATION_COMPLETE
        return PostFixOperationalState.VALIDATION_PENDING

    def latest_receipt_for_cycle(self, cycle_id: str) -> SufficiencyHandoffReceipt | None:
        values = self.receipts_for_cycle(cycle_id)
        return max(values, key=lambda item: item.created_seq, default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "validation_cycles": [item.to_dict() for item in self.validation_cycles],
            "regression_worksets": [item.to_dict() for item in self.regression_worksets],
            "execution_linkages": [item.to_dict() for item in self.execution_linkages],
            "fix_validation_assessments": [item.to_dict() for item in self.fix_validation_assessments],
            "regression_closures": [item.to_dict() for item in self.regression_closures],
            "sufficiency_handoff_receipts": [item.to_dict() for item in self.sufficiency_handoff_receipts],
            "supersession_relations": [dict(item) for item in self.supersession_relations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R44State":
        return cls(
            mission_id=str(value["mission_id"]),
            validation_cycles=tuple(PostFixValidationCycle.from_dict(item) for item in value.get("validation_cycles") or ()),
            regression_worksets=tuple(TargetedRegressionWorkSet.from_dict(item) for item in value.get("regression_worksets") or ()),
            execution_linkages=tuple(ExecutionLinkage.from_dict(item) for item in value.get("execution_linkages") or ()),
            fix_validation_assessments=tuple(FixValidationAssessment.from_dict(item) for item in value.get("fix_validation_assessments") or ()),
            regression_closures=tuple(TargetedRegressionClosure.from_dict(item) for item in value.get("regression_closures") or ()),
            sufficiency_handoff_receipts=tuple(SufficiencyHandoffReceipt.from_dict(item) for item in value.get("sufficiency_handoff_receipts") or ()),
            supersession_relations=tuple(dict(item) for item in value.get("supersession_relations") or ()),
        )


def initial_state(mission_id: str) -> R44State:
    return R44State(mission_id)


def _context(state: R44State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != 1:
        raise R44Error(UNKNOWN_SCHEMA, f"unsupported R4.4 event schema: {event.schema_version}")
    if event.event_type not in EVENT_TYPES:
        raise R44Error(UNKNOWN_EVENT, f"unsupported R4.4 event: {event.event_type}")
    if event.mission_id != state.mission_id or event.mission_id != core_state.mission_id:
        raise R44Error("R4_4_SCOPE_MISMATCH", "event Mission differs from R4.4 state")
    if event.seq != core_state.seq:
        raise R44Error("R4_4_SEQUENCE_MISMATCH", "extension event must share the Core sequence")
    if event.session_id is not None:
        raise R44Error("R4_4_EVENT_INVALID", "R4.4 events are session-independent")
    if not event.entity_id or not event.command_id or not event.correlation_id:
        raise R44Error("R4_4_EVENT_INVALID", "event causation and entity identity are required")


class R44ReducerContribution:
    def reduce(self, state: R44State, event: EventEnvelope, core_state: RuntimeState) -> R44State:
        _context(state, event, core_state)
        payload = dict(event.payload)
        if event.event_type == R44_POST_FIX_VALIDATION_OPENED:
            cycle = PostFixValidationCycle.from_dict(payload)
            if event.entity_id != cycle.cycle_id or cycle.stream_owner_mission_id != state.mission_id:
                raise R44Error("R4_4_EVENT_INVALID", "cycle event identity mismatch")
            if state.cycle(cycle.cycle_id) is not None:
                raise R44Error(CONFLICT, "cycle identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles + (cycle,), state.regression_worksets, state.execution_linkages, state.fix_validation_assessments, state.regression_closures, state.sufficiency_handoff_receipts, state.supersession_relations)
        if event.event_type == R44_TARGETED_REGRESSION_WORKSET_ASSEMBLED:
            workset = TargetedRegressionWorkSet.from_dict(payload)
            cycle = state.cycle(workset.cycle_ref.object_id)
            if cycle is None or cycle.cycle_digest != workset.cycle_ref.source_digest:
                raise R44Error(NOT_FOUND, "workset references a missing or stale cycle")
            if event.entity_id != workset.workset_id or workset.owner_mission_id != state.mission_id:
                raise R44Error("R4_4_EVENT_INVALID", "workset event identity mismatch")
            if state.workset(workset.workset_id) is not None:
                raise R44Error(CONFLICT, "workset identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets + (workset,), state.execution_linkages, state.fix_validation_assessments, state.regression_closures, state.sufficiency_handoff_receipts, state.supersession_relations)
        if event.event_type == R44_EXECUTION_LINKAGE_RECORDED:
            linkage = ExecutionLinkage.from_dict(payload)
            cycle = state.cycle(linkage.cycle_ref.object_id)
            if cycle is None or cycle.cycle_digest != linkage.cycle_ref.source_digest:
                raise R44Error(NOT_FOUND, "linkage references a missing or stale cycle")
            if event.entity_id != linkage.linkage_id:
                raise R44Error("R4_4_EVENT_INVALID", "linkage event identity mismatch")
            if state.linkage(linkage.linkage_id) is not None:
                raise R44Error(CONFLICT, "linkage identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets, state.execution_linkages + (linkage,), state.fix_validation_assessments, state.regression_closures, state.sufficiency_handoff_receipts, state.supersession_relations)
        if event.event_type == R44_FIX_VALIDATION_ASSESSED:
            assessment = FixValidationAssessment.from_dict(payload)
            cycle = state.cycle(assessment.cycle_ref.object_id)
            if cycle is None or cycle.cycle_digest != assessment.cycle_ref.source_digest:
                raise R44Error(NOT_FOUND, "assessment references a missing or stale cycle")
            if event.entity_id != assessment.fix_validation_id:
                raise R44Error("R4_4_EVENT_INVALID", "assessment event identity mismatch")
            if assessment.outcome.value == "PASS" and not assessment.can_pass:
                raise R44Error(RESULT_INCOMPLETE, "FixValidation PASS lacks complete authoritative lineage")
            if state.assessment(assessment.fix_validation_id) is not None:
                raise R44Error(CONFLICT, "assessment identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets, state.execution_linkages, state.fix_validation_assessments + (assessment,), state.regression_closures, state.sufficiency_handoff_receipts, state.supersession_relations)
        if event.event_type == R44_REGRESSION_CLOSURE_RECORDED:
            closure = TargetedRegressionClosure.from_dict(payload)
            workset = state.workset(closure.workset_ref.object_id)
            if workset is None or workset.workset_digest != closure.workset_ref.source_digest:
                raise R44Error(NOT_FOUND, "closure references a missing or stale workset")
            if event.entity_id != closure.closure_id:
                raise R44Error("R4_4_EVENT_INVALID", "closure event identity mismatch")
            if closure.outcome.value == "PASS" and not closure.can_pass:
                raise R44Error("REGRESSION_CLOSURE_INCOMPLETE", "regression PASS lacks complete selection/results")
            if state.closure(closure.closure_id) is not None:
                raise R44Error(CONFLICT, "closure identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets, state.execution_linkages, state.fix_validation_assessments, state.regression_closures + (closure,), state.sufficiency_handoff_receipts, state.supersession_relations)
        if event.event_type in {R44_R3_SUFFICIENCY_EVALUATION_REQUESTED, R44_R3_SUFFICIENCY_EVALUATION_ACKNOWLEDGED}:
            receipt = SufficiencyHandoffReceipt.from_dict(payload)
            cycle = state.cycle(receipt.cycle_ref.object_id)
            workset = state.workset(receipt.workset_ref.object_id)
            if cycle is None or workset is None:
                raise R44Error(NOT_FOUND, "sufficiency receipt references missing cycle/workset")
            if event.entity_id != receipt.receipt_id:
                raise R44Error("R4_4_EVENT_INVALID", "receipt event identity mismatch")
            if state.receipt(receipt.receipt_id) is not None:
                raise R44Error(CONFLICT, "receipt identity is immutable and already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets, state.execution_linkages, state.fix_validation_assessments, state.regression_closures, state.sufficiency_handoff_receipts + (receipt,), state.supersession_relations)
        if event.event_type == R44_OPERATION_SUPERSEDED:
            relation = dict(payload)
            for key in ("operation_kind", "operation_id", "superseding_ref"):
                if not relation.get(key):
                    raise R44Error("R4_4_EVENT_INVALID", f"supersession field is required: {key}")
            if relation in state.supersession_relations:
                raise R44Error(CONFLICT, "supersession relation already exists")
            return R44State(state.mission_id, state.validation_cycles, state.regression_worksets, state.execution_linkages, state.fix_validation_assessments, state.regression_closures, state.sufficiency_handoff_receipts, state.supersession_relations + (relation,))
        raise R44Error(UNKNOWN_EVENT, f"unsupported R4.4 event: {event.event_type}")


SUPPORTED_EVENTS = EVENT_TYPES

__all__ = ["R44State", "R44ReducerContribution", "SUPPORTED_EVENTS", "initial_state"]
