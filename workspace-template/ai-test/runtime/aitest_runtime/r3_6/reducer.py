from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    ANOMALY_RECORDED,
    CANDIDATE_CREATED,
    CHECKPOINT_RECORDED,
    CROSS_SOURCE_CORRELATED,
    DEFECT_TRUTH_ASSESSED,
    EVIDENCE_ASSESSED,
    EVIDENCE_DEEPENING_REQUESTED,
    EXTENSION_ID,
    FALSE_POSITIVE_ASSESSED,
    RCA_RECORDED,
    REPRODUCIBILITY_EVALUATED,
    SEMANTIC_REUSE_RECORDED,
    R36State,
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
)
from .errors import R36Error


def _event_entity(event: EventEnvelope) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(event.payload)
    if set(payload) != {"entity", "origin_lineage", "payload_digest"}:
        raise R36Error("R3_6_SCHEMA_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    entity = payload["entity"]
    origin = payload["origin_lineage"]
    if not isinstance(entity, Mapping) or not isinstance(origin, Mapping):
        raise R36Error("R3_6_SCHEMA_INVALID", "R3.6 event entity and origin_lineage must be objects")
    if origin.get("mission_id") != event.mission_id:
        raise R36Error("R3_6_SCOPE_MISMATCH", "origin_lineage must identify the Event Mission")
    expected = canonical_sha256({"entity": dict(entity), "origin_lineage": dict(origin)})
    if payload.get("payload_digest") != expected:
        raise R36Error("R3_6_SCHEMA_INVALID", "immutable event payload digest does not match")
    return dict(entity), dict(origin)


def _append(values: tuple[Any, ...], value: Any, identity: str) -> tuple[Any, ...]:
    current = getattr(value, identity)
    if any(getattr(item, identity) == current for item in values):
        raise R36Error("R3_6_SECOND_TRUTH_FORBIDDEN", f"{identity} already exists: {current}")
    return values + (value,)


def initial_state(mission_id: str) -> R36State:
    return R36State(mission_id)


class R36ReducerContribution:
    def reduce(self, state: R36State, event: EventEnvelope, core_state: RuntimeState) -> R36State:
        if not isinstance(state, R36State):
            raise R36Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.6 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id or core_state.seq != event.seq:
            raise R36Error("R3_6_SCHEMA_INVALID", "R3.6 Event does not share Runtime Mission/sequence")

        if event.event_type == ANOMALY_RECORDED:
            entity, _ = _event_entity(event)
            return replace(state, anomalies=_append(state.anomalies, TestAnomaly.from_dict(entity), "anomaly_id"))

        if event.event_type == CANDIDATE_CREATED:
            entity, _ = _event_entity(event)
            candidate = DefectCandidate.from_dict(entity)
            for anomaly_id in candidate.anomaly_refs:
                anomaly = state.anomaly(anomaly_id)
                if anomaly is None:
                    raise R36Error("R3_6_UPSTREAM_REF_MISSING", f"candidate references missing anomaly: {anomaly_id}")
                if dict(anomaly.scope) != dict(candidate.scope):
                    raise R36Error("R3_6_SCOPE_MISMATCH", "candidate and anomaly scope mismatch")
            return replace(state, candidates=_append(state.candidates, candidate, "candidate_id"))

        if event.event_type == EVIDENCE_DEEPENING_REQUESTED:
            entity, _ = _event_entity(event)
            deepening = EvidenceDeepeningReceipt.from_dict(entity)
            if state.candidate(deepening.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "evidence deepening references missing candidate")
            return replace(state, deepenings=_append(state.deepenings, deepening, "deepening_id"))

        if event.event_type == EVIDENCE_ASSESSED:
            entity, _ = _event_entity(event)
            assessment = EvidenceAssessment.from_dict(entity)
            if state.candidate(assessment.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "evidence assessment references missing candidate")
            return replace(state, evidence_assessments=_append(state.evidence_assessments, assessment, "assessment_id"))

        if event.event_type == CROSS_SOURCE_CORRELATED:
            entity, _ = _event_entity(event)
            correlation = CrossSourceCorrelation.from_dict(entity)
            if state.candidate(correlation.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "correlation references missing candidate")
            return replace(state, correlations=_append(state.correlations, correlation, "correlation_id"))

        if event.event_type == REPRODUCIBILITY_EVALUATED:
            entity, _ = _event_entity(event)
            assessment = ReproducibilityAssessment.from_dict(entity)
            if state.candidate(assessment.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "reproducibility references missing candidate")
            return replace(state, reproducibility_assessments=_append(state.reproducibility_assessments, assessment, "reproducibility_id"))

        if event.event_type == FALSE_POSITIVE_ASSESSED:
            entity, _ = _event_entity(event)
            assessment = FalsePositiveAssessment.from_dict(entity)
            if state.candidate(assessment.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "false-positive review references missing candidate")
            return replace(state, false_positive_assessments=_append(state.false_positive_assessments, assessment, "false_positive_id"))

        if event.event_type == DEFECT_TRUTH_ASSESSED:
            entity, _ = _event_entity(event)
            assessment = DefectAssessment.from_dict(entity)
            if state.candidate(assessment.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "defect assessment references missing candidate")
            evidence = [item for item in state.evidence_assessments if item.candidate_id == assessment.candidate_id]
            repro = state.reproducibility(assessment.reproducibility_ref)
            false_positive = state.false_positive(assessment.false_positive_ref)
            if not evidence or repro is None or false_positive is None:
                raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "DefectAssessment requires evidence, reproducibility, and false-positive stages")
            if assessment.outcome == "CONFIRMED_DEFECT":
                if assessment.final_classification != "PRODUCT_DEFECT":
                    raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "confirmed outcome requires final PRODUCT_DEFECT classification")
                if not any(item.evidence_sufficiency == "SUFFICIENT" for item in evidence):
                    raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "insufficient evidence cannot confirm a defect")
                if false_positive.status != "NOT_FALSE_POSITIVE":
                    raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "false-positive rejection is required before confirmation")
                if repro.status != "REPRODUCED" and not assessment.causal_basis_refs:
                    raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "reproducibility or established causal basis is required")
                if assessment.unresolved_contradiction_refs:
                    raise R36Error("R3_6_DEFECT_CONFIRMATION_UNSUPPORTED", "critical source contradiction blocks confirmation")
            return replace(state, defect_assessments=_append(state.defect_assessments, assessment, "assessment_id"))

        if event.event_type == RCA_RECORDED:
            entity, _ = _event_entity(event)
            rca = RCARecord.from_dict(entity)
            if state.candidate(rca.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "RCA references missing candidate")
            if not any(item.candidate_id == rca.candidate_id for item in state.defect_assessments):
                raise R36Error("R3_6_RCA_BASIS_MISSING", "RCA requires a recorded DefectAssessment")
            return replace(state, rca_records=_append(state.rca_records, rca, "rca_id"))

        if event.event_type == CHECKPOINT_RECORDED:
            entity, _ = _event_entity(event)
            checkpoint = InvestigationCheckpoint.from_dict(entity)
            if state.candidate(checkpoint.candidate_id) is None:
                raise R36Error("R3_6_CANDIDATE_REQUIRES_ANOMALY", "checkpoint references missing candidate")
            return replace(state, checkpoints=_append(state.checkpoints, checkpoint, "checkpoint_id"))

        if event.event_type == SEMANTIC_REUSE_RECORDED:
            entity, _ = _event_entity(event)
            return replace(state, reuses=_append(state.reuses, SemanticReuse.from_dict(entity), "reuse_id"))

        raise R36Error("R3_6_SCHEMA_INVALID", f"R3.6 event is not owned: {event.event_type}")


class R36StateContribution:
    def initial_state(self, mission_id: str) -> R36State:
        return initial_state(mission_id)

    def encode(self, state: R36State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: Mapping[str, Any]) -> R36State:
        return R36State.from_dict(value)

    def hash(self, state: R36State) -> str:
        return canonical_sha256(self.encode(state))
