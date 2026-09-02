from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import *
from .errors import *
from .reducer import R44State


def _state(composed: ComposedRuntimeState) -> R44State:
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, R44State):
        raise R44Error("R4_4_STATE_INVALID", "R4.4 extension state is invalid")
    return value


def _common(command: Any) -> None:
    if command.type not in COMMAND_TYPES:
        raise R44Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R4.4 command: {command.type}")
    if command.session_id is not None:
        raise R44Error("R4_4_COMMAND_INVALID", "R4.4 commands require session_id=null")
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.strip():
        raise R44Error("R4_4_COMMAND_INVALID", "R4.4 commands require idempotency_key")
    if not isinstance(command.correlation_id, str) or not command.correlation_id.strip():
        raise R44Error("R4_4_COMMAND_INVALID", "R4.4 commands require correlation_id")
    if command.schema_version != 1:
        raise R44Error(UNKNOWN_SCHEMA, f"unsupported R4.4 command schema: {command.schema_version}")


def _payload(command: Any) -> dict[str, Any]:
    if not isinstance(command.payload, Mapping):
        raise R44Error("R4_4_COMMAND_INVALID", "command payload must be an object")
    return dict(command.payload)


def _allowed(cls: type[Any], payload: Mapping[str, Any]) -> None:
    allowed = {item.name for item in fields(cls)}
    unknown = set(payload) - allowed
    if unknown:
        raise R44Error("R4_4_COMMAND_INVALID", f"unknown fields: {sorted(unknown)}")


def _r43_detection(composed: ComposedRuntimeState, cycle: PostFixValidationCycle) -> Mapping[str, Any] | None:
    supplied = cycle.origin_lineage.get("fix_detection_assessment")
    if isinstance(supplied, Mapping):
        return supplied
    for extension_id, extension_state in composed.extension_states.items():
        if extension_id != "r4_3_confirmed_defect_fix_resolution_lifecycle":
            continue
        getter = getattr(extension_state, "detection", None)
        if callable(getter):
            value = getter(cycle.fix_detection_ref.object_id)
            if value is not None and hasattr(value, "to_dict"):
                return value.to_dict()
    return None


def _validate_cycle(composed: ComposedRuntimeState, cycle: PostFixValidationCycle, command: Any) -> None:
    if cycle.stream_owner_mission_id != command.mission_id:
        raise R44Error("R4_4_SCOPE_MISMATCH", "cycle Mission differs from command Mission")
    if cycle.quality_version_ref.object_id == "" or cycle.campaign_ref.object_id == "":
        raise R44Error("R4_4_SCOPE_MISMATCH", "cycle requires exact QualityVersion and Campaign refs")
    detection = _r43_detection(composed, cycle)
    if detection is None:
        if cycle.origin_lineage.get("admission") != "REAL_SUT_READY":
            raise R44Error(FIX_DETECTION_NOT_READY, "R4.3 FixDetectionAssessment is not available at the read boundary")
        return
    if detection.get("fix_detection_id") not in {None, cycle.fix_detection_ref.object_id}:
        raise R44Error(VALIDATION_SCOPE_MISMATCH, "FixDetection identity mismatch")
    if detection.get("detection_digest") and detection.get("detection_digest") != cycle.fix_detection_ref.source_digest:
        raise R44Error(VALIDATION_SCOPE_MISMATCH, "FixDetection digest mismatch")
    result = validate_fix_detection_admission(detection, target_deployment_ref=cycle.target_deployment_ref, target_environment_ref=cycle.target_environment_ref)
    if not result["ready"]:
        raise R44Error(result["code"], "FixDetection does not establish REAL_SUT_READY", result)


def _same_cycle(state: R44State, reference: ExactReference) -> PostFixValidationCycle:
    cycle = state.cycle(reference.object_id)
    if cycle is None:
        raise R44Error(NOT_FOUND, f"cycle not found: {reference.object_id}")
    if cycle.cycle_digest != reference.source_digest:
        raise R44Error(VALIDATION_SCOPE_MISMATCH, "cycle reference digest is stale")
    return cycle


def _same_refs(left: Any, right: Any) -> bool:
    return tuple(item.to_dict() for item in left) == tuple(item.to_dict() for item in right)


class R44CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        _common(command)
        state = _state(composed)
        payload = _payload(command)

        if command.type == R4_4_OPEN_POST_FIX_VALIDATION:
            _allowed(PostFixValidationCycle, payload)
            cycle = PostFixValidationCycle.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            _validate_cycle(composed, cycle, command)
            if cycle.cycle_id != cycle_id_for(cycle):
                raise R44Error("R4_4_IDENTITY_INVALID", "cycle_id is not deterministic")
            if state.cycle(cycle.cycle_id) is not None:
                raise R44Error(CONFLICT, "cycle identity already exists")
            return [PendingEvent(R44_POST_FIX_VALIDATION_OPENED, "R4_4_POST_FIX_VALIDATION_CYCLE", cycle.cycle_id, cycle.to_dict())]

        if command.type == R4_4_ASSEMBLE_TARGETED_REGRESSION_WORKSET:
            _allowed(TargetedRegressionWorkSet, payload)
            workset = TargetedRegressionWorkSet.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            cycle = _same_cycle(state, workset.cycle_ref)
            if workset.owner_mission_id != command.mission_id or workset.quality_version_ref.to_dict() != cycle.quality_version_ref.to_dict() or workset.campaign_ref.to_dict() != cycle.campaign_ref.to_dict() or workset.fix_link_ref.to_dict() != cycle.fix_link_ref.to_dict() or workset.fix_detection_ref.to_dict() != cycle.fix_detection_ref.to_dict():
                raise R44Error(VALIDATION_SCOPE_MISMATCH, "workset scope differs from cycle")
            if workset.workset_id != workset_id_for(workset):
                raise R44Error("R4_4_IDENTITY_INVALID", "workset_id is not deterministic")
            if state.workset(workset.workset_id) is not None:
                raise R44Error(CONFLICT, "workset identity already exists")
            if workset.selection_complete is False and not (workset.unknown_scope_refs or workset.blocked_scope_refs):
                raise R44Error(REGRESSION_SELECTION_INCOMPLETE, "incomplete selection must retain unknown or blocked scope")
            return [PendingEvent(R44_TARGETED_REGRESSION_WORKSET_ASSEMBLED, "R4_4_TARGETED_REGRESSION_WORKSET", workset.workset_id, workset.to_dict())]

        if command.type == R4_4_RECORD_EXECUTION_LINKAGE:
            _allowed(ExecutionLinkage, payload)
            linkage = ExecutionLinkage.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            _same_cycle(state, linkage.cycle_ref)
            if linkage.workset_ref is not None and state.workset(linkage.workset_ref.object_id) is None:
                raise R44Error(NOT_FOUND, "linkage workset not found")
            if state.linkage(linkage.linkage_id) is not None:
                raise R44Error(CONFLICT, "linkage identity already exists")
            return [PendingEvent(R44_EXECUTION_LINKAGE_RECORDED, "R4_4_EXECUTION_LINKAGE", linkage.linkage_id, linkage.to_dict())]

        if command.type == R4_4_RECORD_FIX_VALIDATION_ASSESSMENT:
            _allowed(FixValidationAssessment, payload)
            assessment = FixValidationAssessment.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            cycle = _same_cycle(state, assessment.cycle_ref)
            exact_fields = ("confirmed_defect_lifecycle_ref", "fix_link_ref", "fix_detection_ref", "quality_version_ref", "campaign_ref", "target_environment_ref", "target_deployment_ref")
            if assessment.stream_owner_mission_id != command.mission_id or any(getattr(assessment, name).to_dict() != getattr(cycle, name).to_dict() for name in exact_fields) or not _same_refs(assessment.validation_case_refs, cycle.validation_case_refs) or not _same_refs(assessment.case_review_refs, cycle.case_review_refs) or not _same_refs(assessment.oracle_specification_refs, cycle.oracle_specification_refs):
                raise R44Error(VALIDATION_SCOPE_MISMATCH, "assessment scope differs from cycle")
            if assessment.outcome is FixValidationOutcome.PASS and not assessment.can_pass:
                raise R44Error(RESULT_INCOMPLETE, "FixValidation PASS requires complete authoritative lineage")
            if state.assessment(assessment.fix_validation_id) is not None:
                raise R44Error(CONFLICT, "assessment identity already exists")
            return [PendingEvent(R44_FIX_VALIDATION_ASSESSED, "R4_4_FIX_VALIDATION_ASSESSMENT", assessment.fix_validation_id, assessment.to_dict())]

        if command.type == R4_4_RECORD_REGRESSION_CLOSURE:
            _allowed(TargetedRegressionClosure, payload)
            closure = TargetedRegressionClosure.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            workset = state.workset(closure.workset_ref.object_id)
            if workset is None or workset.workset_digest != closure.workset_ref.source_digest:
                raise R44Error(NOT_FOUND, "closure workset is missing or stale")
            _same_cycle(state, closure.cycle_ref)
            if not _same_refs(closure.selected_case_refs, workset.selected_case_refs):
                raise R44Error(VALIDATION_SCOPE_MISMATCH, "closure selected cases differ from authoritative workset")
            if closure.outcome is RegressionClosureOutcome.PASS and not closure.can_pass:
                raise R44Error(REGRESSION_SELECTION_INCOMPLETE, "regression PASS requires complete authoritative results")
            if state.closure(closure.closure_id) is not None:
                raise R44Error(CONFLICT, "closure identity already exists")
            return [PendingEvent(R44_REGRESSION_CLOSURE_RECORDED, "R4_4_REGRESSION_CLOSURE", closure.closure_id, closure.to_dict())]

        if command.type in {R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION, R4_4_ACK_R3_SUFFICIENCY_EVALUATION}:
            _allowed(SufficiencyHandoffReceipt, payload)
            receipt = SufficiencyHandoffReceipt.from_dict({**payload, "created_seq": composed.seq + 1, "created_at": "pending", "correlation_id": command.correlation_id})
            _same_cycle(state, receipt.cycle_ref)
            if state.workset(receipt.workset_ref.object_id) is None:
                raise R44Error(NOT_FOUND, "sufficiency handoff workset not found")
            latest = state.latest_receipt(receipt.handoff_request_id)
            if command.type == R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION and receipt.request_status is not SufficiencyHandoffStatus.REQUESTED:
                raise R44Error("R4_4_COMMAND_INVALID", "request command requires REQUESTED status")
            if command.type == R4_4_ACK_R3_SUFFICIENCY_EVALUATION:
                if latest is None:
                    raise R44Error(SUFFICIENCY_HANDOFF_FAILED, "acknowledgement has no prior request")
                if latest.input_digest != receipt.input_digest:
                    raise R44Error(RESULT_CONFLICT, "sufficiency input digest differs on retry")
                if receipt.request_status not in {SufficiencyHandoffStatus.ACKNOWLEDGED, SufficiencyHandoffStatus.RECONCILIATION_REQUIRED, SufficiencyHandoffStatus.BLOCKED, SufficiencyHandoffStatus.CONFLICT}:
                    raise R44Error("R4_4_COMMAND_INVALID", "acknowledgement status is invalid")
            if state.receipt(receipt.receipt_id) is not None:
                raise R44Error(CONFLICT, "receipt identity already exists")
            event_type = R44_R3_SUFFICIENCY_EVALUATION_REQUESTED if command.type == R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION else R44_R3_SUFFICIENCY_EVALUATION_ACKNOWLEDGED
            return [PendingEvent(event_type, "R4_4_SUFFICIENCY_HANDOFF_RECEIPT", receipt.receipt_id, receipt.to_dict())]

        if command.type == R4_4_SUPERSEDE_OPERATION:
            required = {"operation_kind", "operation_id", "superseding_ref", "reason"}
            if set(payload) != required:
                raise R44Error("R4_4_COMMAND_INVALID", "supersession payload must contain exactly four fields")
            kind = str(payload["operation_kind"])
            operation_id = str(payload["operation_id"])
            if kind not in {"CYCLE", "WORKSET"} or not operation_id.strip() or not isinstance(payload["superseding_ref"], Mapping):
                raise R44Error("R4_4_COMMAND_INVALID", "supersession identity is invalid")
            ExactReference.from_dict(payload["superseding_ref"])
            if kind == "CYCLE" and state.cycle(operation_id) is None:
                raise R44Error(NOT_FOUND, "cycle to supersede was not found")
            if kind == "WORKSET" and state.workset(operation_id) is None:
                raise R44Error(NOT_FOUND, "workset to supersede was not found")
            if state.is_superseded(kind, operation_id):
                raise R44Error(CONFLICT, "operation is already superseded")
            return [PendingEvent(R44_OPERATION_SUPERSEDED, "R4_4_SUPERSESSION", f"{kind}:{operation_id}", payload)]

        raise R44Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R4.4 command: {command.type}")


__all__ = ["R44CommandContribution"]
