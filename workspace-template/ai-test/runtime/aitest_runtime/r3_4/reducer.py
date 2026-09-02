from __future__ import annotations

from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import EventEnvelope, RuntimeState

from .contracts import (
    CASE_EXECUTION_ATTEMPT_REGISTERED, CASE_REVIEWED, EXECUTION_READINESS_ASSESSED,
    ORACLE_EVALUATED, ORACLE_SPECIFICATION_APPROVED, PRECONDITION_RESOLVED,
    REVIEWER_CONTEXT_BUILT, SEMANTIC_REUSE, TEST_DATA_RESOLVED, TEST_RESULT_RECORDED,
    CaseExecutionAttempt, CaseReview, EvidenceRequirement, ExecutionReadinessAssessment,
    OracleEvaluation, OracleSpecification, PreconditionRequirement, PreconditionResolution,
    R34Error, R34State, R34ReuseReference, ReviewerContextSnapshot, TestDataRequirement,
    TestDataResolution, TestResult,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R34Error("R3_4_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    return payload


def _same_mission(value: Any, mission_id: str) -> None:
    if getattr(value, "mission_id", mission_id) != mission_id:
        raise R34Error("R3_4_EVENT_INVALID", "R3.4 record mission identity mismatch")


def _immutable(values: tuple[Any, ...], record: Any, identity_name: str) -> tuple[Any, ...]:
    identity = getattr(record, identity_name)
    if any(getattr(item, identity_name) == identity for item in values):
        raise R34Error("R3_4_IDENTITY_CONFLICT", f"{identity_name} is immutable")
    return values + (record,)


class R34ReducerContribution:
    def reduce(self, state: R34State, event: EventEnvelope, core_state: RuntimeState) -> R34State:
        if not isinstance(state, R34State):
            raise R34Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.4 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R34Error("R3_4_EVENT_INVALID", "R3.4 event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R34Error("R3_4_EVENT_INVALID", "R3.4 event does not share the Core sequence")

        if event.event_type == REVIEWER_CONTEXT_BUILT:
            payload = _payload(event, {"reviewer_context"})
            record = ReviewerContextSnapshot.from_dict(payload["reviewer_context"])
            _same_mission(record, event.mission_id)
            if any(item.reviewer_context_digest == record.reviewer_context_digest for item in state.reviewer_contexts):
                raise R34Error("R3_4_EVENT_INVALID", "reviewer context digest is immutable")
            return replace(state, reviewer_contexts=_immutable(state.reviewer_contexts, record, "reviewer_context_id"))

        if event.event_type == CASE_REVIEWED:
            payload = _payload(event, {"case_review"})
            record = CaseReview.from_dict(payload["case_review"])
            _same_mission(record, event.mission_id)
            context = state.reviewer_context(record.reviewer_context_id)
            if context is None or context.reviewer_context_digest != record.reviewer_context_digest:
                raise R34Error("R3_4_EVENT_INVALID", "CaseReview references an unknown or mismatched ReviewerContext")
            if any(item.case_review_id == record.case_review_id for item in state.case_reviews):
                raise R34Error("R3_4_EVENT_INVALID", "CaseReview identity is immutable")
            return replace(state, case_reviews=state.case_reviews + (replace(record, created_seq=event.seq, created_at=event.created_at),))

        if event.event_type == EXECUTION_READINESS_ASSESSED:
            payload = _payload(event, {"readiness", "precondition_requirements", "test_data_requirements"})
            readiness = ExecutionReadinessAssessment.from_dict(payload["readiness"])
            preconditions = tuple(PreconditionRequirement.from_dict(item) for item in payload["precondition_requirements"])
            data = tuple(TestDataRequirement.from_dict(item) for item in payload["test_data_requirements"])
            _same_mission(readiness, event.mission_id)
            review = state.review(readiness.case_review_id)
            oracle = state.oracle(readiness.oracle_specification_id)
            if review is None or review.review_fingerprint != readiness.review_digest or oracle is None or oracle.oracle_fingerprint != readiness.oracle_specification_digest:
                raise R34Error("R3_4_EVENT_INVALID", "readiness approval chain is invalid")
            for item in preconditions + data:
                if item.case_version_id != readiness.case_version_id:
                    raise R34Error("R3_4_EVENT_INVALID", "readiness requirement case identity mismatch")
            if any(item.execution_readiness_id == readiness.execution_readiness_id for item in state.execution_readiness):
                raise R34Error("R3_4_EVENT_INVALID", "readiness identity is immutable")
            return replace(
                state,
                execution_readiness=state.execution_readiness + (replace(readiness, created_seq=event.seq),),
                precondition_requirements=_append_unique(state.precondition_requirements, preconditions, "precondition_requirement_id"),
                test_data_requirements=_append_unique(state.test_data_requirements, data, "test_data_requirement_id"),
            )

        if event.event_type == PRECONDITION_RESOLVED:
            resolution = PreconditionResolution.from_dict(_payload(event, {"resolution"})["resolution"])
            requirement = state.precondition_requirement(resolution.requirement_id)
            if requirement is None:
                raise R34Error("R3_4_EVENT_INVALID", "precondition resolution references an unknown requirement")
            if any(item.precondition_resolution_id == resolution.precondition_resolution_id for item in state.precondition_resolutions):
                raise R34Error("R3_4_EVENT_INVALID", "precondition resolution identity is immutable")
            return replace(state, precondition_resolutions=state.precondition_resolutions + (replace(resolution, created_seq=event.seq),))

        if event.event_type == TEST_DATA_RESOLVED:
            resolution = TestDataResolution.from_dict(_payload(event, {"resolution"})["resolution"])
            requirement = state.test_data_requirement(resolution.requirement_id)
            if requirement is None:
                raise R34Error("R3_4_EVENT_INVALID", "test-data resolution references an unknown requirement")
            if any(item.test_data_resolution_id == resolution.test_data_resolution_id for item in state.test_data_resolutions):
                raise R34Error("R3_4_EVENT_INVALID", "test-data resolution identity is immutable")
            return replace(state, test_data_resolutions=state.test_data_resolutions + (replace(resolution, created_seq=event.seq),))

        if event.event_type == ORACLE_SPECIFICATION_APPROVED:
            payload = _payload(event, {"oracle_specification", "evidence_requirements"})
            oracle = OracleSpecification.from_dict(payload["oracle_specification"])
            evidence = tuple(EvidenceRequirement.from_dict(item) for item in payload["evidence_requirements"])
            _same_mission(oracle, event.mission_id)
            review = state.review(oracle.case_review_id)
            if review is None or review.review_status != "APPROVED" or review.review_fingerprint != oracle.review_digest:
                raise R34Error("R3_4_EVENT_INVALID", "oracle requires the matching approved review")
            if not evidence:
                raise R34Error("R3_4_EVENT_INVALID", "oracle approval requires non-empty evidence requirements")
            if any(item.oracle_specification_id not in {None, oracle.oracle_specification_id} for item in evidence):
                raise R34Error("R3_4_EVENT_INVALID", "evidence requirement oracle identity mismatch")
            if any(item.case_review_id == oracle.case_review_id for item in state.oracle_specifications):
                raise R34Error("R3_4_ORACLE_IMMUTABILITY_VIOLATION", "an approved oracle already exists for this review")
            if any(item.oracle_specification_id == oracle.oracle_specification_id for item in state.oracle_specifications):
                raise R34Error("R3_4_EVENT_INVALID", "approved oracle is immutable")
            if any(item.evidence_requirement_id in {existing.evidence_requirement_id for existing in state.evidence_requirements} for item in evidence):
                raise R34Error("R3_4_EVENT_INVALID", "evidence requirement identity is immutable")
            return replace(state, oracle_specifications=state.oracle_specifications + (replace(oracle, created_seq=event.seq),), evidence_requirements=state.evidence_requirements + tuple(replace(item, created_seq=event.seq, oracle_specification_id=oracle.oracle_specification_id) for item in evidence))

        if event.event_type == CASE_EXECUTION_ATTEMPT_REGISTERED:
            attempt = CaseExecutionAttempt.from_dict(_payload(event, {"attempt"})["attempt"])
            _same_mission(attempt, event.mission_id)
            readiness = state.readiness(attempt.execution_readiness_id)
            oracle = state.oracle(attempt.oracle_specification_id)
            if readiness is None or readiness.readiness_status != "READY" or readiness.readiness_fingerprint != attempt.readiness_digest or oracle is None or oracle.oracle_fingerprint != attempt.oracle_specification_digest:
                raise R34Error("R3_4_EVENT_INVALID", "attempt approval chain is invalid")
            if any(item.case_execution_attempt_id == attempt.case_execution_attempt_id for item in state.case_execution_attempts):
                raise R34Error("R3_4_EVENT_INVALID", "CaseExecutionAttempt identity is immutable")
            return replace(state, case_execution_attempts=state.case_execution_attempts + (replace(attempt, created_seq=event.seq),))

        if event.event_type == ORACLE_EVALUATED:
            evaluation = OracleEvaluation.from_dict(_payload(event, {"evaluation"})["evaluation"])
            attempt = state.attempt(evaluation.case_execution_attempt_id)
            oracle = state.oracle(evaluation.oracle_specification_id)
            if attempt is None or oracle is None or attempt.oracle_specification_digest != evaluation.oracle_specification_digest or oracle.oracle_fingerprint != evaluation.oracle_specification_digest:
                raise R34Error("R3_4_EVENT_INVALID", "oracle evaluation lineage or digest mismatch")
            if evaluation.evidence_sufficiency != "SUFFICIENT" and evaluation.oracle_decision == "PASS":
                raise R34Error("R3_4_EVENT_INVALID", "insufficient evidence cannot produce PASS")
            if any(item.oracle_evaluation_id == evaluation.oracle_evaluation_id for item in state.oracle_evaluations):
                raise R34Error("R3_4_EVENT_INVALID", "OracleEvaluation identity is immutable")
            return replace(state, oracle_evaluations=state.oracle_evaluations + (replace(evaluation, created_seq=event.seq),))

        if event.event_type == TEST_RESULT_RECORDED:
            result = TestResult.from_dict(_payload(event, {"result"})["result"])
            attempt = state.attempt(result.case_execution_attempt_id)
            evaluation = state.evaluation(result.oracle_evaluation_id) if result.oracle_evaluation_id else None
            if attempt is None or evaluation is None or evaluation.case_execution_attempt_id != attempt.case_execution_attempt_id:
                raise R34Error("R3_4_EVENT_INVALID", "TestResult lineage is invalid")
            if result.evidence_sufficiency != "SUFFICIENT" and result.result_status == "PASS":
                raise R34Error("R3_4_EVENT_INVALID", "insufficient evidence cannot produce PASS")
            if attempt.execution_status != "EXECUTION_SUCCEEDED" and result.business_validation_status == "PASS":
                raise R34Error("R3_4_EVENT_INVALID", "execution failure or non-success cannot produce business PASS")
            if result.result_status == "PASS" and (attempt.execution_status != "EXECUTION_SUCCEEDED" or evaluation.business_validation != "PASS"):
                raise R34Error("R3_4_EVENT_INVALID", "execution success and business validation must remain separate")
            if any(item.test_result_id == result.test_result_id for item in state.test_results):
                raise R34Error("R3_4_EVENT_INVALID", "TestResult identity is immutable")
            return replace(state, test_results=state.test_results + (replace(result, created_seq=event.seq),))

        if event.event_type == SEMANTIC_REUSE:
            reuse = R34ReuseReference.from_dict(_payload(event, {"reuse"})["reuse"])
            if any(item.reuse_id == reuse.reuse_id for item in state.reuses):
                raise R34Error("R3_4_EVENT_INVALID", "reuse identity is immutable")
            return replace(state, reuses=state.reuses + (replace(reuse, created_seq=event.seq, created_at=event.created_at),))

        raise R34Error("R3_4_EVENT_NOT_OWNED", f"unsupported R3.4 event: {event.event_type}")


def _append_unique(existing: tuple[Any, ...], incoming: tuple[Any, ...], identity_name: str) -> tuple[Any, ...]:
    result = list(existing)
    known = {getattr(item, identity_name) for item in existing}
    for item in incoming:
        identity = getattr(item, identity_name)
        if identity not in known:
            result.append(item)
            known.add(identity)
    return tuple(result)
