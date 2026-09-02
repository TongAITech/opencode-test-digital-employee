from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, canonical_sha256

from .contracts import (
    ANOMALY_RECORDED,
    ASSESS_DEFECT_TRUTH,
    ASSESS_FALSE_POSITIVE,
    CANDIDATE_CREATED,
    CHECKPOINT_RECORDED,
    CREATE_DEFECT_CANDIDATE,
    CROSS_SOURCE_CORRELATED,
    DEFECT_TRUTH_ASSESSED,
    EVALUATE_REPRODUCIBILITY,
    EVIDENCE_ASSESSED,
    EVIDENCE_DEEPENING_REQUESTED,
    EXTENSION_ID,
    FALSE_POSITIVE_ASSESSED,
    RCA_RECORDED,
    RECORD_CROSS_SOURCE_CORRELATION,
    RECORD_EVIDENCE_ASSESSMENT,
    RECORD_INVESTIGATION_CHECKPOINT,
    RECORD_RCA,
    RECORD_TEST_ANOMALY,
    REPRODUCIBILITY_EVALUATED,
    REQUEST_EVIDENCE_DEEPENING,
    SEMANTIC_REUSE,
    SEMANTIC_REUSE_RECORDED,
    TestAnomaly,
    DefectCandidate,
    EvidenceDeepeningReceipt,
    EvidenceAssessment,
    CrossSourceCorrelation,
    ReproducibilityAssessment,
    FalsePositiveAssessment,
    DefectAssessment,
    RCARecord,
    InvestigationCheckpoint,
    SemanticReuse,
    R36State,
)
from .errors import R36Error


def _request(command: Any) -> dict[str, Any]:
    payload = dict(command.payload)
    if set(payload) != {"request"} or not isinstance(payload.get("request"), Mapping):
        raise R36Error("R3_6_SCHEMA_INVALID", f"{command.type} payload must contain only request")
    request = dict(payload["request"])
    if request.get("mission_id") != command.mission_id:
        raise R36Error("R3_6_SCOPE_MISMATCH", "request mission_id must match command mission_id")
    origin = request.get("origin_lineage")
    if not isinstance(origin, Mapping) or origin.get("mission_id") != command.mission_id:
        raise R36Error("R3_6_SCOPE_MISMATCH", "origin_lineage must identify command Mission")
    return request


def _entity_request(request: Mapping[str, Any], key: str, cls: type[Any], command: Any) -> Any:
    raw = request.get(key)
    if not isinstance(raw, Mapping):
        raise R36Error("R3_6_SCHEMA_INVALID", f"request.{key} must be an object")
    value = dict(raw)
    value.setdefault("origin_lineage", dict(request["origin_lineage"]))
    entity = cls.from_dict(value)
    if entity.origin_lineage.get("mission_id") != command.mission_id:
        raise R36Error("R3_6_SCOPE_MISMATCH", f"{key}.origin_lineage must identify command Mission")
    return entity


def _event(event_type: str, entity_type: str, entity_id: str, entity: Any, command: Any) -> list[PendingEvent]:
    origin = dict(entity.origin_lineage)
    body = {"entity": entity.to_dict(), "origin_lineage": origin}
    payload = {**body, "payload_digest": canonical_sha256(body)}
    return [PendingEvent(event_type, entity_type, entity_id, payload, session_id=command.session_id)]


def _state(composed: ComposedRuntimeState) -> R36State:
    state = composed.extension_state(EXTENSION_ID)
    if not isinstance(state, R36State):
        raise R36Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.6 command state")
    return state


def _validate_defect_assessment(state: R36State, entity: DefectAssessment) -> None:
    if state.candidate(entity.candidate_id) is None:
        raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "defect assessment references missing candidate")
    evidence = []
    for assessment_id in entity.evidence_assessment_refs:
        assessment = state.evidence_assessment(assessment_id)
        if assessment is None or assessment.candidate_id != entity.candidate_id:
            raise R36Error("R3_6_EVIDENCE_INSUFFICIENT", "DefectAssessment references missing or cross-candidate evidence")
        evidence.append(assessment)
    repro = state.reproducibility(entity.reproducibility_ref)
    false_positive = state.false_positive(entity.false_positive_ref)
    if repro is None or false_positive is None:
        raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "DefectAssessment requires reproducibility and false-positive stages")
    if entity.outcome == "CONFIRMED_DEFECT":
        if entity.final_classification != "PRODUCT_DEFECT":
            raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "confirmed outcome requires final PRODUCT_DEFECT classification")
        if not any(item.evidence_sufficiency == "SUFFICIENT" for item in evidence):
            raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "insufficient evidence cannot confirm a defect")
        if false_positive.status != "NOT_FALSE_POSITIVE":
            raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "false-positive rejection is required before confirmation")
        if repro.status != "REPRODUCED" and not entity.causal_basis_refs:
            raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "reproducibility or established causal basis is required")
        if entity.unresolved_contradiction_refs:
            raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "critical source contradiction blocks confirmation")


class R36CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)
        request = _request(command)

        if command.type == RECORD_TEST_ANOMALY:
            entity = _entity_request(request, "anomaly", TestAnomaly, command)
            if state.anomaly(entity.anomaly_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"anomaly already exists: {entity.anomaly_id}")
            return _event(ANOMALY_RECORDED, "R3_6_TEST_ANOMALY", entity.anomaly_id, entity, command)

        if command.type == CREATE_DEFECT_CANDIDATE:
            entity = _entity_request(request, "candidate", DefectCandidate, command)
            if state.candidate(entity.candidate_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"candidate already exists: {entity.candidate_id}")
            return _event(CANDIDATE_CREATED, "R3_6_DEFECT_CANDIDATE", entity.candidate_id, entity, command)

        if command.type == REQUEST_EVIDENCE_DEEPENING:
            entity = _entity_request(request, "deepening", EvidenceDeepeningReceipt, command)
            if state.deepening(entity.deepening_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"deepening already exists: {entity.deepening_id}")
            return _event(EVIDENCE_DEEPENING_REQUESTED, "R3_6_EVIDENCE_DEEPENING", entity.deepening_id, entity, command)

        if command.type == RECORD_EVIDENCE_ASSESSMENT:
            entity = _entity_request(request, "evidence_assessment", EvidenceAssessment, command)
            if state.evidence_assessment(entity.assessment_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"evidence assessment already exists: {entity.assessment_id}")
            return _event(EVIDENCE_ASSESSED, "R3_6_EVIDENCE_ASSESSMENT", entity.assessment_id, entity, command)

        if command.type == RECORD_CROSS_SOURCE_CORRELATION:
            entity = _entity_request(request, "correlation", CrossSourceCorrelation, command)
            if state.correlation(entity.correlation_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"correlation already exists: {entity.correlation_id}")
            return _event(CROSS_SOURCE_CORRELATED, "R3_6_CROSS_SOURCE_CORRELATION", entity.correlation_id, entity, command)

        if command.type == EVALUATE_REPRODUCIBILITY:
            entity = _entity_request(request, "reproducibility", ReproducibilityAssessment, command)
            if state.reproducibility(entity.reproducibility_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"reproducibility already exists: {entity.reproducibility_id}")
            return _event(REPRODUCIBILITY_EVALUATED, "R3_6_REPRODUCIBILITY", entity.reproducibility_id, entity, command)

        if command.type == ASSESS_FALSE_POSITIVE:
            entity = _entity_request(request, "false_positive", FalsePositiveAssessment, command)
            if state.false_positive(entity.false_positive_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"false-positive assessment already exists: {entity.false_positive_id}")
            return _event(FALSE_POSITIVE_ASSESSED, "R3_6_FALSE_POSITIVE", entity.false_positive_id, entity, command)

        if command.type == ASSESS_DEFECT_TRUTH:
            entity = _entity_request(request, "defect_assessment", DefectAssessment, command)
            _validate_defect_assessment(state, entity)
            if state.defect_assessment(entity.assessment_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"defect assessment already exists: {entity.assessment_id}")
            return _event(DEFECT_TRUTH_ASSESSED, "R3_6_DEFECT_ASSESSMENT", entity.assessment_id, entity, command)

        if command.type == RECORD_RCA:
            entity = _entity_request(request, "rca", RCARecord, command)
            if state.rca(entity.rca_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"RCA already exists: {entity.rca_id}")
            return _event(RCA_RECORDED, "R3_6_RCA", entity.rca_id, entity, command)

        if command.type == RECORD_INVESTIGATION_CHECKPOINT:
            entity = _entity_request(request, "checkpoint", InvestigationCheckpoint, command)
            if state.checkpoint(entity.checkpoint_id) is not None:
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"checkpoint already exists: {entity.checkpoint_id}")
            return _event(CHECKPOINT_RECORDED, "R3_6_CHECKPOINT", entity.checkpoint_id, entity, command)

        if command.type == SEMANTIC_REUSE:
            entity = _entity_request(request, "reuse", SemanticReuse, command)
            if any(item.reuse_id == entity.reuse_id for item in state.reuses):
                raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"reuse already exists: {entity.reuse_id}")
            return _event(SEMANTIC_REUSE_RECORDED, "R3_6_REUSE", entity.reuse_id, entity, command)

        raise R36Error("R3_6_SCHEMA_INVALID", f"R3.6 command is not owned: {command.type}")
