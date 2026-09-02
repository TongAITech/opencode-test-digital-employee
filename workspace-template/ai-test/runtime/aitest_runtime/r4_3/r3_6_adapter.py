from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, RuntimeService, canonical_sha256
from aitest_runtime.r3_6.contracts import DefectAssessment, R36State
from aitest_runtime.r4_1.contracts import Availability, FieldValidationState, Freshness, TypedReference

from .contracts import R43_LIFECYCLE_OPENED
from .errors import ARCHITECTURE_BOUNDARY_VIOLATION, NOT_FOUND, R3_ASSESSMENT_DIGEST_CONFLICT, R3_CONFIRMATION_INVALID, R43Error, SCOPE_MISMATCH


R36_EXTENSION_ID = "r3_6_defect_investigation_rca"


def _admission_field_state(assessment: DefectAssessment, assessment_ref: TypedReference) -> FieldValidationState:
    """Preserve upstream field semantics without making an R4.3 claim."""
    if assessment.evidence_class == "ENGINEERING_EVIDENCE":
        return FieldValidationState.NOT_APPLICABLE
    return assessment_ref.field_validation_state


def _ref(
    ref_type: str,
    object_id: str,
    digest: str,
    *,
    cursor: int | str | None,
    observed_at: str,
    origin: str,
    freshness: Freshness = Freshness.CURRENT,
    availability: Availability = Availability.AVAILABLE,
    field_validation_state: FieldValidationState = FieldValidationState.PENDING,
    correlation_id: str,
) -> TypedReference:
    return TypedReference(
        ref_type=ref_type,
        object_id=object_id,
        object_version="1",
        revision=1,
        source_digest=digest,
        source_cursor=cursor,
        origin=origin,
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        field_validation_state=field_validation_state,
        correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class R36AssessmentAdmission:
    mission_id: str
    assessment_ref: TypedReference
    assessment_digest: str
    candidate_ref: TypedReference
    evidence_refs: tuple[TypedReference, ...]
    reproducibility_ref: TypedReference
    false_positive_ref: TypedReference
    rca_refs: tuple[TypedReference, ...]
    evidence_class: str
    field_validation_state: FieldValidationState
    origin_lineage: Mapping[str, Any]
    event_metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "assessment_ref": self.assessment_ref.to_dict(),
            "assessment_digest": self.assessment_digest,
            "candidate_ref": self.candidate_ref.to_dict(),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "reproducibility_ref": self.reproducibility_ref.to_dict(),
            "false_positive_ref": self.false_positive_ref.to_dict(),
            "rca_refs": [item.to_dict() for item in self.rca_refs],
            "evidence_class": self.evidence_class,
            "field_validation_state": self.field_validation_state.value,
            "origin_lineage": dict(self.origin_lineage),
            "event_metadata": dict(self.event_metadata),
        }


def _assessment_event(runtime_service: RuntimeService, mission_id: str, assessment_id: str):
    for event in runtime_service.list_events(mission_id):
        if event.event_type == "r3.6.defect_truth_assessed.v1" and event.entity_id == assessment_id:
            return event
    return None


def _assessment_from_state(composed: ComposedRuntimeState, mission_id: str, assessment_id: str) -> tuple[R36State, DefectAssessment]:
    try:
        state = composed.extension_state(R36_EXTENSION_ID)
    except Exception as exc:
        raise R43Error(NOT_FOUND, "R3.6 extension state is unavailable") from exc
    if not isinstance(state, R36State):
        raise R43Error(NOT_FOUND, "R3.6 extension state is not replayable")
    assessment = state.defect_assessment(assessment_id)
    if assessment is None:
        raise R43Error(NOT_FOUND, f"R3.6 DefectAssessment is unavailable: {assessment_id}")
    origin_mission = assessment.origin_lineage.get("mission_id")
    if origin_mission not in (None, mission_id) or state.mission_id != mission_id:
        raise R43Error(SCOPE_MISMATCH, "R3.6 DefectAssessment belongs to a different Mission")
    return state, assessment


def validate_r3_6_reference(
    runtime_service: RuntimeService,
    mission_id: str,
    assessment_ref: TypedReference | Mapping[str, Any],
) -> R36AssessmentAdmission:
    """Validate an exact R3.6 CONFIRMED_DEFECT reference from replayed shared state.

    This adapter intentionally returns bounded references only. It never writes R3.6,
    persists the source payload, reruns confirmation, or recalculates RCA.
    """
    if not isinstance(runtime_service, RuntimeService):
        raise R43Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R3.6 admission requires the caller-owned RuntimeService")
    if isinstance(assessment_ref, Mapping):
        assessment_ref = TypedReference.from_dict(assessment_ref)
    if not isinstance(assessment_ref, TypedReference):
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 admission requires a TypedReference")
    if assessment_ref.ref_type != "R3_6_DEFECT_ASSESSMENT" or assessment_ref.object_version != "1" or assessment_ref.revision != 1:
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 admission reference is not the exact R3.6 assessment shape")
    composed = runtime_service.replay_composed(mission_id)
    state, assessment = _assessment_from_state(composed, mission_id, assessment_ref.object_id)
    if assessment_ref.source_digest != assessment.defect_assessment_digest:
        raise R43Error(
            R3_ASSESSMENT_DIGEST_CONFLICT,
            "R3.6 assessment ID exists with a different immutable digest",
            {"assessment_id": assessment.assessment_id},
        )
    if assessment.outcome != "CONFIRMED_DEFECT":
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 assessment outcome is not CONFIRMED_DEFECT")
    candidate = state.candidate(assessment.candidate_id)
    if candidate is None:
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 confirmed assessment has no underlying candidate truth")
    evidence = []
    for evidence_id in assessment.evidence_assessment_refs:
        item = state.evidence_assessment(evidence_id)
        if item is None or item.candidate_id != assessment.candidate_id:
            raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 confirmed assessment has incomplete evidence truth")
        evidence.append(item)
    repro = state.reproducibility(assessment.reproducibility_ref)
    false_positive = state.false_positive(assessment.false_positive_ref)
    if repro is None or false_positive is None:
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 confirmed assessment has incomplete reproducibility truth")

    event = _assessment_event(runtime_service, mission_id, assessment.assessment_id)
    if event is not None:
        if assessment_ref.source_cursor != event.seq or assessment_ref.origin != event.event_type:
            raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 reference provenance does not match the frozen event stream")
    cursor = event.seq if event is not None else assessment_ref.source_cursor
    observed_at = event.created_at if event is not None else assessment_ref.observed_at
    correlation_id = event.correlation_id if event is not None else assessment_ref.correlation_id
    origin = event.event_type if event is not None else assessment_ref.origin
    field_state = _admission_field_state(assessment, assessment_ref)
    candidate_ref = _ref(
        "R3_6_DEFECT_CANDIDATE", candidate.candidate_id, candidate.candidate_digest,
        cursor=cursor, observed_at=observed_at, origin="r3.6.defect_candidate_created.v1",
        field_validation_state=field_state, correlation_id=correlation_id,
    )
    evidence_refs = tuple(
        _ref(
            "R3_6_EVIDENCE_ASSESSMENT", item.assessment_id, item.assessment_digest,
            cursor=cursor, observed_at=observed_at, origin="r3.6.evidence_assessed.v1",
            field_validation_state=field_state, correlation_id=correlation_id,
        )
        for item in evidence
    )
    repro_ref = _ref(
        "R3_6_REPRODUCIBILITY_ASSESSMENT", repro.reproducibility_id, repro.reproducibility_digest,
        cursor=cursor, observed_at=observed_at, origin="r3.6.reproducibility_evaluated.v1",
        field_validation_state=field_state, correlation_id=correlation_id,
    )
    false_ref = _ref(
        "R3_6_FALSE_POSITIVE_ASSESSMENT", false_positive.false_positive_id, false_positive.false_positive_digest,
        cursor=cursor, observed_at=observed_at, origin="r3.6.false_positive_assessed.v1",
        field_validation_state=field_state, correlation_id=correlation_id,
    )
    rca_refs = tuple(
        _ref(
            "R3_6_RCA", item.rca_id, item.rca_digest, cursor=cursor, observed_at=observed_at,
            origin="r3.6.rca_recorded.v1", field_validation_state=field_state, correlation_id=correlation_id,
        )
        for item in state.rca_records if item.candidate_id == assessment.candidate_id
    )
    exact_ref = _ref(
        "R3_6_DEFECT_ASSESSMENT", assessment.assessment_id, assessment.defect_assessment_digest,
        cursor=cursor, observed_at=observed_at, origin=origin, field_validation_state=field_state,
        correlation_id=correlation_id,
    )
    return R36AssessmentAdmission(
        mission_id=mission_id, assessment_ref=exact_ref, assessment_digest=assessment.defect_assessment_digest,
        candidate_ref=candidate_ref, evidence_refs=evidence_refs, reproducibility_ref=repro_ref,
        false_positive_ref=false_ref, rca_refs=rca_refs, evidence_class=assessment.evidence_class,
        field_validation_state=field_state, origin_lineage=dict(assessment.origin_lineage),
        event_metadata={
            "event_type": event.event_type if event is not None else None,
            "seq": event.seq if event is not None else None,
            "command_id": event.command_id if event is not None else None,
            "correlation_id": correlation_id,
            "created_at": observed_at,
        },
    )


def validate_r3_6_admission_from_state(
    composed: ComposedRuntimeState,
    mission_id: str,
    assessment_ref: TypedReference | Mapping[str, Any],
) -> R36AssessmentAdmission:
    """Pure handler-side equivalent using the already replayed composed state."""
    if isinstance(assessment_ref, Mapping):
        assessment_ref = TypedReference.from_dict(assessment_ref)
    if not isinstance(assessment_ref, TypedReference) or assessment_ref.ref_type != "R3_6_DEFECT_ASSESSMENT":
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 admission requires an exact assessment reference")
    state, assessment = _assessment_from_state(composed, mission_id, assessment_ref.object_id)
    if assessment_ref.source_digest != assessment.defect_assessment_digest:
        raise R43Error(R3_ASSESSMENT_DIGEST_CONFLICT, "R3.6 assessment digest conflict")
    if assessment.outcome != "CONFIRMED_DEFECT":
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 assessment outcome is not confirmed")
    candidate = state.candidate(assessment.candidate_id)
    if candidate is None or state.evidence_assessment(assessment.evidence_assessment_refs[0]) is None:
        raise R43Error(R3_CONFIRMATION_INVALID, "R3.6 confirmed truth is incomplete")
    field_state = _admission_field_state(assessment, assessment_ref)
    bounded_ref = replace(assessment_ref, field_validation_state=field_state)
    return R36AssessmentAdmission(
        mission_id=mission_id, assessment_ref=bounded_ref, assessment_digest=assessment.defect_assessment_digest,
        candidate_ref=bounded_ref, evidence_refs=(), reproducibility_ref=bounded_ref, false_positive_ref=bounded_ref,
        rca_refs=(), evidence_class=assessment.evidence_class, field_validation_state=field_state,
        origin_lineage=dict(assessment.origin_lineage), event_metadata={},
    )


R3_6ExactAdmissionValidator = validate_r3_6_reference
R36ExactAdmissionValidator = validate_r3_6_reference


__all__ = [
    "R36AssessmentAdmission", "validate_r3_6_reference", "validate_r3_6_admission_from_state",
    "R3_6ExactAdmissionValidator", "R36ExactAdmissionValidator",
]
