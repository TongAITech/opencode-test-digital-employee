from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, canonical_sha256
from aitest_runtime.r3_1.contracts import R31State
from aitest_runtime.r3_2.contracts import R31Reference as UpstreamR31Reference, R32State
from aitest_runtime.r3_2.engine import r31_provenance_bundle_digest, validate_r31_reference
from aitest_runtime.r3_3.contracts import R33State, StandardTestCase

from .contracts import (
    APPROVE_ORACLE_SPECIFICATION, ASSESS_EXECUTION_READINESS, BUILD_REVIEW_CONTEXT,
    CASE_EXECUTION_ATTEMPT_REGISTERED, CASE_REVIEWED, EVALUATE_ORACLE,
    EXECUTION_READINESS_ASSESSED, ORACLE_EVALUATED, ORACLE_SPECIFICATION_APPROVED,
    PRECONDITION_RESOLVED, RECORD_TEST_RESULT, REGISTER_CASE_EXECUTION_ATTEMPT,
    RESOLVE_PRECONDITION, RESOLVE_TEST_DATA, REVIEW_CASE, REVIEWER_CONTEXT_BUILT,
    SEMANTIC_REUSE, TEST_DATA_RESOLVED, TEST_RESULT_RECORDED,
    CaseExecutionAttempt, CaseReview, EvidenceRequirement, ExecutionReadinessAssessment,
    OracleEvaluation, OracleSpecification, PreconditionRequirement, PreconditionResolution,
    R31Reference, R32Reference, R33CaseReference, R34Error, R34State, R34ReuseReference,
    ReviewerContextSnapshot, TestDataRequirement, TestDataResolution, TestResult,
    RECONCILIATION_SEMANTICS, REVIEW_DIMENSIONS, REVIEW_DIMENSION_STATES,
    REVIEW_STATUSES, READINESS_STATUSES, RESOLUTION_STATES, DATA_RESOLUTION_STATES,
    EXECUTION_STATUSES, ORACLE_DECISIONS, EVIDENCE_SUFFICIENCY, BUSINESS_VALIDATIONS,
    record_digest, request_from_mapping, _array, _text,
)


R31_ID = "r3_1_requirement_coverage_traceability"
R32_ID = "r3_2_change_impact_reconciliation"
R33_ID = "r3_3_test_strategy_standard_case_design"


def _state(composed: ComposedRuntimeState) -> R34State:
    value = composed.extension_state("r3_4_case_review_execution_readiness_oracle")
    if not isinstance(value, R34State):
        raise R34Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.4 extension state")
    return value


def _payload(value: Any, name: str = "command.payload") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R34Error("R3_4_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _request(command: Any) -> dict[str, Any]:
    payload = _payload(command.payload)
    if set(payload) != {"request"}:
        raise R34Error("R3_4_SCHEMA_INVALID", "R3.4 command payload must contain request only")
    request = request_from_mapping(payload["request"])
    if request.get("mission_id") != command.mission_id:
        raise R34Error("R3_4_MISSION_IDENTITY_MISMATCH", "request mission_id differs from command mission_id")
    if request.get("idempotency_key") != command.idempotency_key:
        raise R34Error("R3_4_IDEMPOTENCY_KEY_MISMATCH", "request idempotency_key differs from command")
    return request


def _r31_ref(request: Mapping[str, Any]) -> R31Reference:
    return R31Reference.from_dict(request["r3_1_reference"])


def _r32_ref(request: Mapping[str, Any]) -> R32Reference:
    return R32Reference.from_dict(request["r3_2_reference"])


def _r33_ref(request: Mapping[str, Any]) -> R33CaseReference:
    return R33CaseReference.from_dict(request["r3_3_case_reference"])


def _upstream(composed: ComposedRuntimeState, request: Mapping[str, Any]):
    try:
        r31 = composed.extension_state(R31_ID)
        r32 = composed.extension_state(R32_ID)
        r33 = composed.extension_state(R33_ID)
    except Exception as exc:
        raise R34Error("R3_4_UPSTREAM_EXTENSION_MISSING", "R3.1/R3.2/R3.3 extensions are required read-only inputs") from exc
    if not isinstance(r31, R31State) or not isinstance(r32, R32State) or not isinstance(r33, R33State):
        raise R34Error("R3_4_UPSTREAM_STATE_INVALID", "R3.1/R3.2/R3.3 state type is invalid")
    r31_ref = _r31_ref(request)
    try:
        snapshot = validate_r31_reference(r31, UpstreamR31Reference(**r31_ref.to_dict()))
    except Exception as exc:
        raise R34Error("R3_4_R31_REFERENCE_INVALID", str(exc)) from exc
    derivation = r32.derivation(_r32_ref(request).derivation_fingerprint)
    if derivation is None:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "referenced R3.2 derivation does not exist")
    r32_ref = _r32_ref(request)
    reconciliation = r32.reconciliation(r32_ref.reconciliation_id)
    if reconciliation is None:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "referenced R3.2 reconciliation does not exist")
    if derivation.derivation_version_id != r32_ref.derivation_version_id or derivation.derivation_fingerprint != r32_ref.derivation_fingerprint:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "R3.2 derivation identity mismatch")
    if reconciliation.derivation_fingerprint != derivation.derivation_fingerprint:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "R3.2 reconciliation identity mismatch")
    if canonical_sha256(derivation.identity.compare_identity.to_dict()) != r32_ref.compare_identity_digest:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "R3.2 compare identity digest mismatch")
    if canonical_sha256(derivation.code_intelligence.to_dict()) != r32_ref.provider_envelope_digest:
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "R3.2 provider envelope digest mismatch")
    if derivation.r3_1_reference.to_dict() != r31_ref.to_dict():
        raise R34Error("R3_4_R32_REFERENCE_INVALID", "R3.2 does not reference the supplied R3.1 identity")
    case_ref = _r33_ref(request)
    case = next((item for item in r33.standard_cases if item.case_version_id == case_ref.case_version_id), None)
    if case is None:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "referenced R3.3 StandardTestCase does not exist")
    if {
        "strategy_version_id": case.strategy_version_id,
        "test_point_id": case.test_point_id,
        "tc_id": case.tc_id,
        "case_version_id": case.case_version_id,
    } != {
        "strategy_version_id": case_ref.strategy_version_id,
        "test_point_id": case_ref.test_point_id,
        "tc_id": case_ref.tc_id,
        "case_version_id": case_ref.case_version_id,
    }:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 case identity fields do not match")
    if canonical_sha256(case.to_dict()) != case_ref.case_version_digest:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 case version digest mismatch")
    if canonical_sha256(case.source_provenance) != case_ref.source_provenance_digest:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 source provenance digest mismatch")
    if canonical_sha256(case.evidence_requirements) != case_ref.evidence_requirement_digest:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 evidence requirement digest mismatch")
    if canonical_sha256(case.oracle_contract) != case_ref.design_oracle_digest:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 design oracle digest mismatch")
    strategy = r33.strategy_by_id(case.strategy_version_id)
    if strategy is None:
        raise R34Error("R3_4_R33_CASE_REFERENCE_INVALID", "R3.3 strategy for case is missing")
    if strategy.mission_id != composed.mission_id:
        raise R34Error("R3_4_MISSION_IDENTITY_MISMATCH", "R3.3 strategy mission mismatch")
    scope_identity = request.get("scope_identity")
    if scope_identity != strategy.scope_identity or snapshot.identity.scope_identity != scope_identity or derivation.identity.scope_identity != scope_identity:
        raise R34Error("R3_4_SCOPE_IDENTITY_MISMATCH", "R3.1/R3.2/R3.3 scope identities must match")
    return r31, r32, r33, snapshot, derivation, reconciliation, strategy, case, r31_ref, r32_ref, case_ref


def _policy(request: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    raw = _payload(request.get("review_policy") or {}, "review_policy")
    version = raw.get("policy_version") or request.get("review_policy_version")
    if not isinstance(version, str) or not version.strip():
        raise R34Error("R3_4_REVIEW_POLICY_REQUIRED", "review policy version is required")
    supplied = raw.get("policy_digest") or request.get("review_policy_digest")
    semantic = {str(key): value for key, value in raw.items() if key != "policy_digest"}
    semantic.setdefault("policy_version", version)
    digest = supplied or canonical_sha256(semantic)
    return version, digest, semantic


def _latest_resolutions(values: tuple[Any, ...], requirement_name: str) -> tuple[Any, ...]:
    latest: dict[str, Any] = {}
    for item in values:
        requirement_id = getattr(item, requirement_name)
        prior = latest.get(requirement_id)
        if prior is None or getattr(item, "created_seq", 0) >= getattr(prior, "created_seq", 0):
            latest[requirement_id] = item
    return tuple(sorted(latest.values(), key=lambda item: (getattr(item, "created_seq", 0), getattr(item, requirement_name))))


def _actor(command: Any) -> dict[str, str]:
    return command.actor.to_dict()


def _case_ref_payload(case: StandardTestCase) -> R33CaseReference:
    return R33CaseReference(
        strategy_version_id=case.strategy_version_id, test_point_id=case.test_point_id, tc_id=case.tc_id,
        case_version_id=case.case_version_id, case_version_digest=canonical_sha256(case.to_dict()),
        source_provenance_digest=canonical_sha256(case.source_provenance),
        evidence_requirement_digest=canonical_sha256(case.evidence_requirements),
        design_oracle_digest=canonical_sha256(case.oracle_contract),
    )


def _reviewer_context(request: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> ReviewerContextSnapshot:
    _, r32, _, snapshot, derivation, reconciliation, _, case, r31_ref, r32_ref, case_ref = _upstream(composed, request)
    policy_version, policy_digest, policy = _policy(request)
    coverage_refs = tuple(dict.fromkeys(
        [item.obligation_id for item in snapshot.obligations]
        + [item.reconciliation_item_id for item in reconciliation.items]
    ))
    source_refs = tuple(dict.fromkeys(
        list(derivation.evidence_references) + list(getattr(r32.derivation(r32_ref.derivation_fingerprint), "evidence_references", ()))
        + list(case.source_provenance)
    ))
    evidence_refs = tuple(dict.fromkeys(list(case.evidence_refs) + list(derivation.evidence_references)))
    semantic = {
        "mission_id": request["mission_id"], "scope_identity": request["scope_identity"], "r3_1_reference": r31_ref.to_dict(),
        "r3_2_reference": r32_ref.to_dict(), "r3_3_case_reference": case_ref.to_dict(), "coverage_obligation_refs": list(coverage_refs),
        "case_version_snapshot": case.to_dict(), "review_policy_version": policy_version, "review_policy_digest": policy_digest,
        "review_policy_snapshot": policy, "source_provenance": list(source_refs), "evidence_refs": list(evidence_refs),
    }
    digest = canonical_sha256(semantic)
    context_id = request.get("reviewer_context_id") or f"r34-context:{digest}"
    return ReviewerContextSnapshot(
        reviewer_context_id=context_id, version=int(request.get("version", 1)), mission_id=request["mission_id"], scope_identity=request["scope_identity"],
        r3_1_reference=r31_ref, r3_2_reference=r32_ref, r3_3_case_reference=case_ref, source_truth_refs={"r3_1": r31_ref.to_dict(), "r3_2": r32_ref.to_dict(), "source_refs": list(source_refs)},
        coverage_obligation_refs=coverage_refs, case_version_snapshot=case.to_dict(), review_policy_version=policy_version, review_policy_digest=policy_digest, review_policy_snapshot=policy,
        reviewer_context_digest=digest, source_provenance=source_refs, evidence_refs=evidence_refs, created_seq=0, created_at="pending", correlation_id=request["correlation_id"],
    )


def _case_review(request: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> CaseReview:
    state = _state(composed)
    if not request.get("reviewer_context_id"):
        raise R34Error("R3_4_REVIEW_CONTEXT_REQUIRED", "CaseReview requires a persisted rebuilt ReviewerContextSnapshot")
    context_id = _text(request.get("reviewer_context_id"), "reviewer_context_id")
    context = state.reviewer_context(context_id)
    if context is None:
        raise R34Error("R3_4_REVIEW_CONTEXT_REQUIRED", "CaseReview requires a persisted rebuilt ReviewerContextSnapshot")
    _, _, _, _, _, _, _, case, r31_ref, r32_ref, case_ref = _upstream(composed, request)
    if context.reviewer_context_digest != request.get("reviewer_context_digest", context.reviewer_context_digest):
        raise R34Error("R3_4_REVIEW_CONTEXT_MISMATCH", "reviewer context digest mismatch")
    dimensions = dict(request.get("dimension_assessments") or {name: "PASS" for name in REVIEW_DIMENSIONS})
    if set(dimensions) != set(REVIEW_DIMENSIONS) or any(value not in REVIEW_DIMENSION_STATES for value in dimensions.values()):
        raise R34Error("R3_4_REVIEW_DIMENSION_INVALID", "review requires all five independent dimensions")
    findings = tuple(request.get("findings") or ())
    snapshot = _upstream(composed, request)[3]
    reconciliation = _upstream(composed, request)[5]
    gap_semantics = tuple(
        str(gap.kind)
        for obligation in snapshot.obligations
        for gap in obligation.coverage_gaps
        if str(gap.kind) in RECONCILIATION_SEMANTICS
    )
    mapping_semantics = tuple(
        str(obligation.mapping_state)
        for obligation in snapshot.obligations
        if str(obligation.mapping_state) in RECONCILIATION_SEMANTICS
    )
    semantics = tuple(dict.fromkeys(case.reconciliation_semantics + tuple(item.semantic for item in reconciliation.items) + mapping_semantics + gap_semantics))
    missing = tuple(dict.fromkeys(
        list(request.get("unmapped_or_partial_obligations") or ())
        + [item.obligation_id for item in _upstream(composed, request)[3].obligations if item.mapping_state in {"PARTIAL", "UNMAPPED"} or item.coverage_gaps]
        + [item.reconciliation_item_id for item in _upstream(composed, request)[5].items if item.semantic in {"UNMAPPED", "PARTIAL", "UNCOVERED", "REQUIREMENT_CODE_GAP"}]
    ))
    status = request.get("review_status") or ("APPROVED" if all(value == "PASS" for value in dimensions.values()) and case.oracle_contract and case.evidence_requirements else "CHANGES_REQUESTED")
    if status == "APPROVED" and (not case.oracle_contract or not case.evidence_requirements):
        raise R34Error("R3_4_REVIEW_INCOMPLETE", "approved review requires oracle and evidence requirements")
    if status == "APPROVED" and any(value != "PASS" for value in dimensions.values()):
        raise R34Error("R3_4_REVIEW_INCOMPLETE", "approved review requires all review dimensions to pass")
    if status == "APPROVED" and any(
        isinstance(item, Mapping)
        and str(item.get("disposition") or item.get("status") or "").upper() in {"BLOCKED", "OPEN", "UNRESOLVED"}
        for item in findings
    ):
        raise R34Error("R3_4_REVIEW_INCOMPLETE", "approved review cannot retain blocking findings")
    review_digest = canonical_sha256({
        "case_version_digest": case_ref.case_version_digest, "r3_1_reference": r31_ref.to_dict(), "r3_2_reference": r32_ref.to_dict(),
        "reviewer_context_digest": context.reviewer_context_digest, "review_policy_digest": context.review_policy_digest,
        "dimension_assessments": dimensions, "findings": list(findings), "coverage_semantics": list(semantics),
    })
    return CaseReview(
        case_review_id=request.get("case_review_id") or f"r34-review:{review_digest}", review_version=int(request.get("review_version", 1)), mission_id=request["mission_id"], scope_identity=request["scope_identity"],
        case_version_id=case.case_version_id, case_version_digest=case_ref.case_version_digest, tc_id=case.tc_id, strategy_version_id=case.strategy_version_id, test_point_id=case.test_point_id,
        r3_1_reference=r31_ref, r3_2_reference=r32_ref, r3_3_case_reference=case_ref, reviewer_context_id=context.reviewer_context_id, reviewer_context_digest=context.reviewer_context_digest,
        review_policy_version=context.review_policy_version, review_policy_digest=context.review_policy_digest, reviewer_session_ref=request.get("reviewer_session_ref"), dimension_assessments=dimensions, findings=findings,
        coverage_semantics=semantics, unmapped_or_partial_obligations=missing, oracle_specification_candidate_digest=canonical_sha256(case.oracle_contract), evidence_requirement_set_digest=canonical_sha256(case.evidence_requirements),
        review_status=status, approved_at=(request.get("approved_at") or (f"seq:{composed.seq + 1}" if status == "APPROVED" else None)), approved_by=_actor(command) if status == "APPROVED" else None,
        source_provenance=case.source_provenance, evidence_refs=case.evidence_refs, review_fingerprint=review_digest, idempotency_key=request["idempotency_key"], correlation_id=request["correlation_id"], created_at="pending",
    )


def _requirements(case: StandardTestCase, review: CaseReview, request: Mapping[str, Any]):
    preconditions = request.get("precondition_requirements")
    if preconditions is None:
        preconditions = [
            {"precondition_requirement_id": f"r34-precondition:{case.case_version_id}:{index}", "case_version_id": case.case_version_id, "requirement_kind": item.get("kind", "SYSTEM_STATE"), "condition_expression": item.get("condition_expression") or item.get("condition") or str(item), "expected_state": item.get("expected_state") or item, "source_refs": item.get("source_refs") or list(case.source_provenance), "provenance_refs": item.get("provenance_refs") or list(case.source_provenance), "evidence_requirement_refs": item.get("evidence_requirement_refs") or list(case.evidence_refs), "resolution_policy_version": request.get("resolution_policy_version", "r3.4.resolution.v1"), "expiry_policy": item.get("expiry_policy") or {}, "required": item.get("required", True)}
            for index, item in enumerate(case.preconditions)
        ]
    data = request.get("test_data_requirements")
    if data is None:
        data = [
            {"test_data_requirement_id": f"r34-test-data:{case.case_version_id}:{index}", "case_version_id": case.case_version_id, "data_kind": item.get("data_kind", "FIXTURE"), "data_contract": item, "dataset_ref": item.get("dataset_ref"), "fixture_ref": item.get("fixture_ref"), "provider_capability_ref": item.get("provider_capability_ref"), "classification": item.get("classification", "NON_SECRET"), "masking_policy_version": item.get("masking_policy_version", "r3.4.masking.v1"), "isolation_policy_version": item.get("isolation_policy_version", "r3.4.isolation.v1"), "seed_or_existing_policy": item.get("seed_or_existing_policy", "EXISTING_OR_SEED"), "cleanup_policy": item.get("cleanup_policy", "CASE_SCOPED"), "source_refs": item.get("source_refs") or list(case.source_provenance), "evidence_requirement_refs": item.get("evidence_requirement_refs") or list(case.evidence_refs), "required": item.get("required", True)}
            for index, item in enumerate(case.test_data)
        ]
    return tuple(PreconditionRequirement.from_dict(item) for item in preconditions), tuple(TestDataRequirement.from_dict(item) for item in data)


def _oracle_and_evidence(request: Mapping[str, Any], review: CaseReview, case: StandardTestCase, command: Any):
    raw = _payload(request.get("oracle_specification") or case.oracle_contract, "oracle_specification")
    oracle_id = raw.get("oracle_specification_id") or request.get("oracle_specification_id") or f"r34-oracle:{review.case_version_digest}:{review.case_review_id}"
    evidence_raw = request.get("evidence_requirements") or [
        {"evidence_requirement_id": f"r34-evidence:{case.case_version_id}:{index}", "set_id": request.get("evidence_requirement_set_id") or f"r34-evidence-set:{case.case_version_id}", "version": 1, "case_version_id": case.case_version_id, "case_review_id": review.case_review_id, "capture_stage": item.get("capture_stage", "ORACLE"), "evidence_type": item.get("evidence_type", "OBSERVATION"), "required": item.get("required", True), "minimum_verification": item.get("minimum_verification", "VERIFIED"), "observation_fields": item.get("observation_fields") or ([{"field": field, "source": "R1.EvidenceRecord", "type": "ANY", "normalization": "identity"} for field in raw.get("observation_fields", [])] or [{"field": "result", "source": "R1.EvidenceRecord", "type": "ANY"}]), "artifact_kind": item.get("artifact_kind", "REFERENCE"), "locator_policy": item.get("locator_policy") or {"mode": "R1_REFERENCE"}, "provenance_policy": item.get("provenance_policy") or {"owner": "R1"}, "source_refs": item.get("source_refs") or list(case.source_provenance), "requirement_refs": item.get("requirement_refs") or list(case.coverage_obligation_refs), "evidence_requirement_fingerprint": item.get("evidence_requirement_fingerprint") or canonical_sha256(item)}
        for index, item in enumerate(case.evidence_requirements)
    ]
    evidence = []
    for item in evidence_raw:
        value = dict(item)
        value.setdefault("oracle_specification_id", oracle_id)
        value.setdefault("evidence_requirement_fingerprint", canonical_sha256({key: value[key] for key in value if key != "evidence_requirement_fingerprint"}))
        evidence.append(EvidenceRequirement.from_dict(value))
    evidence_set_id = evidence[0].set_id if evidence else request.get("evidence_requirement_set_id") or f"r34-evidence-set:{case.case_version_id}"
    evidence_digest = canonical_sha256([item.to_dict() for item in evidence])
    observation_schema = raw.get("observation_schema") or [{"field": field, "source": "R1.EvidenceRecord", "type": "ANY", "normalization": "identity"} for field in raw.get("observation_fields", [])]
    oracle = OracleSpecification(
        oracle_specification_id=oracle_id, oracle_version=int(raw.get("oracle_version", 1)), mission_id=request["mission_id"], scope_identity=request["scope_identity"], case_version_id=case.case_version_id, case_version_digest=review.case_version_digest, case_review_id=review.case_review_id, review_digest=review.review_fingerprint,
        business_property=raw.get("business_property") or "business property", observation_schema=tuple(observation_schema), pass_condition=raw.get("pass_condition") or "approved pass condition", fail_condition=raw.get("fail_condition") or "approved fail condition", insufficient_evidence_condition=raw.get("insufficient_evidence_condition") or "required evidence is insufficient", allowed_observation_refs=tuple(raw.get("allowed_observation_refs") or ()), evaluation_policy_version=raw.get("evaluation_policy_version", "r3.4.evaluation.v1"), evaluation_policy_digest=raw.get("evaluation_policy_digest") or canonical_sha256({"version": raw.get("evaluation_policy_version", "r3.4.evaluation.v1"), "pass": raw.get("pass_condition"), "fail": raw.get("fail_condition")}), evidence_requirement_set_id=evidence_set_id, evidence_requirement_digest=evidence_digest, source_refs=tuple(raw.get("source_refs") or case.source_provenance), provenance_refs=tuple(raw.get("provenance_refs") or case.source_provenance), evidence_refs=tuple(raw.get("evidence_refs") or case.evidence_refs), approved_by=_actor(command), approved_at=raw.get("approved_at") or f"seq:{command.command_id}", oracle_fingerprint=canonical_sha256({"case_review_id": review.case_review_id, "case_version_digest": review.case_version_digest, "business_property": raw.get("business_property"), "observation_schema": observation_schema, "pass_condition": raw.get("pass_condition"), "fail_condition": raw.get("fail_condition"), "insufficient_evidence_condition": raw.get("insufficient_evidence_condition"), "evidence_requirement_digest": evidence_digest}), immutability_guard_digest=canonical_sha256({"oracle_id": oracle_id, "case_version_digest": review.case_version_digest, "review_digest": review.review_fingerprint}),
    )
    return oracle, tuple(evidence)


def _readiness(request: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> tuple[ExecutionReadinessAssessment, tuple[PreconditionRequirement, ...], tuple[TestDataRequirement, ...]]:
    state = _state(composed)
    review = state.review(_text(request.get("case_review_id"), "case_review_id"))
    if review is None or review.review_status != "APPROVED":
        raise R34Error("R3_4_REVIEW_NOT_APPROVED", "ExecutionReadiness requires an approved CaseReview")
    oracle = state.oracle(_text(request.get("oracle_specification_id"), "oracle_specification_id"))
    if oracle is None:
        raise R34Error("R3_4_ORACLE_NOT_APPROVED", "ExecutionReadiness requires an approved OracleSpecification")
    case = StandardTestCase.from_dict(_payload(next((item.case_version_snapshot for item in state.reviewer_contexts if item.reviewer_context_id == review.reviewer_context_id), {}), "case_version_snapshot"))
    preconditions, data = _requirements(case, review, request)
    if not request.get("precondition_requirements"):
        existing = tuple(item for item in state.precondition_requirements if item.case_version_id == case.case_version_id)
        if existing:
            preconditions = existing
    if not request.get("test_data_requirements"):
        existing = tuple(item for item in state.test_data_requirements if item.case_version_id == case.case_version_id)
        if existing:
            data = existing
    precondition_refs = tuple(item.precondition_requirement_id for item in preconditions)
    data_refs = tuple(item.test_data_requirement_id for item in data)
    pre_resolutions = _latest_resolutions(tuple(item for item in state.precondition_resolutions if item.requirement_id in set(precondition_refs)), "requirement_id")
    data_resolutions = _latest_resolutions(tuple(item for item in state.test_data_resolutions if item.requirement_id in set(data_refs)), "requirement_id")
    unresolved_pre = [item.precondition_requirement_id for item in preconditions if item.required and not any(res.requirement_id == item.precondition_requirement_id and res.resolution_state in {"RESOLVED", "NOT_APPLICABLE"} for res in pre_resolutions)]
    unresolved_data = [item.test_data_requirement_id for item in data if item.required and not any(res.requirement_id == item.test_data_requirement_id and res.resolution_state in {"RESOLVED", "NOT_APPLICABLE"} for res in data_resolutions)]
    blockers = tuple(request.get("blockers") or ())
    missing = tuple(dict.fromkeys(unresolved_pre + unresolved_data + list(request.get("missing_inputs") or ())))
    conflicts = tuple(request.get("conflicts") or ())
    status = request.get("readiness_status") or ("READY" if not blockers and not missing and not conflicts else "NOT_READY")
    if status == "READY" and (blockers or missing or conflicts):
        status = "NOT_READY"
    fingerprint = canonical_sha256({"review": review.review_fingerprint, "oracle": oracle.oracle_fingerprint, "preconditions": [item.to_dict() for item in pre_resolutions], "test_data": [item.to_dict() for item in data_resolutions], "runtime_binding_plan": request.get("runtime_binding_plan") or {"lineage_only": True}})
    readiness = ExecutionReadinessAssessment(
        execution_readiness_id=request.get("execution_readiness_id") or f"r34-readiness:{fingerprint}", version=int(request.get("version", 1)), mission_id=request["mission_id"], scope_identity=request["scope_identity"], case_version_id=review.case_version_id, case_version_digest=review.case_version_digest, case_review_id=review.case_review_id, review_digest=review.review_fingerprint, oracle_specification_id=oracle.oracle_specification_id, oracle_specification_digest=oracle.oracle_fingerprint, evidence_requirement_set_id=oracle.evidence_requirement_set_id, evidence_requirement_digest=oracle.evidence_requirement_digest, precondition_requirement_refs=precondition_refs, precondition_resolution_refs=tuple(item.precondition_resolution_id for item in pre_resolutions), test_data_requirement_refs=data_refs, test_data_resolution_refs=tuple(item.test_data_resolution_id for item in data_resolutions), runtime_fact_refs=tuple(request.get("runtime_fact_refs") or ()), capability_refs=tuple(request.get("capability_refs") or ()), environment_refs=tuple(request.get("environment_refs") or ()), dimension_assessments={"REVIEW": "PASS", "PRECONDITIONS": "PASS" if not unresolved_pre else "BLOCKED", "TEST_DATA": "PASS" if not unresolved_data else "BLOCKED", "RUNTIME_BINDING": "PASS" if (request.get("runtime_binding_plan") or {"lineage_only": True}) else "BLOCKED"}, readiness_status=status, blockers=blockers, missing_inputs=missing, conflicts=conflicts, runtime_binding_plan=request.get("runtime_binding_plan") or {"lineage_only": True}, valid_until=request.get("valid_until"), assessed_at=request.get("assessed_at") or f"seq:{composed.seq + 1}", assessed_by=_actor(command), readiness_fingerprint=fingerprint, source_provenance=review.source_provenance, evidence_refs=review.evidence_refs,
    )
    return readiness, preconditions, data


def _validate_r1_attempt(composed: ComposedRuntimeState, request: Mapping[str, Any]) -> dict[str, Any]:
    raw = _payload(request.get("r1_runtime_attempt") or {}, "r1_runtime_attempt")
    attempt_id = raw.get("attempt_id") or request.get("r1_runtime_attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise R34Error("R3_4_R1_ATTEMPT_LINEAGE_MISSING", "CaseExecutionAttempt requires an existing R1 attempt reference")
    if "r1_3b_execution_resume" in composed.extension_states:
        upstream = composed.extension_state("r1_3b_execution_resume")
        attempt = upstream.attempt(attempt_id) if hasattr(upstream, "attempt") else None
        if attempt is None:
            raise R34Error("R3_4_R1_ATTEMPT_LINEAGE_MISSING", "referenced R1 attempt does not exist")
        raw = {**raw, **attempt.to_dict()}
    elif raw.get("existing") is not True:
        raise R34Error("R3_4_R1_ATTEMPT_LINEAGE_MISSING", "R1 attempt must be explicitly marked as existing when the R1 extension is not registered")
    required = ("root_attempt_id", "runtime_session_id", "task_id", "plan_id", "plan_revision_id")
    if raw.get("mission_id") not in {None, composed.mission_id}:
        raise R34Error("R3_4_R1_ATTEMPT_LINEAGE_INVALID", "R1 attempt Mission identity does not match")
    for name in required:
        if not isinstance(raw.get(name), str) or not raw[name].strip():
            raise R34Error("R3_4_R1_ATTEMPT_LINEAGE_INVALID", f"R1 attempt lineage field is missing: {name}")
    raw.setdefault("lineage_digest", canonical_sha256({name: raw[name] for name in ("attempt_id", "mission_id", "root_attempt_id", "predecessor_attempt_id", "attempt_kind", "runtime_session_id", "task_id", "plan_id", "plan_revision_id", "ordinal", "context_cursor", "context_semantic_digest", "context_schema_version", "context_builder_version", "context_canonicalization_version", "policy_id", "policy_version", "knowledge_set_digest") if name in raw}))
    return raw


def _validate_r2_session(composed: ComposedRuntimeState, request: Mapping[str, Any]) -> None:
    reference = _text(request.get("r2_executor_session_ref"), "r2_executor_session_ref")
    if "r2_5_session_orchestration" not in composed.extension_states:
        return
    state = composed.extension_state("r2_5_session_orchestration")
    bindings = getattr(state, "bindings", ())
    if not any(reference in {getattr(item, "binding_id", None), getattr(item, "session_id", None)} for item in bindings):
        raise R34Error("R3_4_R2_SESSION_LINEAGE_MISSING", "referenced R2.5 executor session binding does not exist")


def _validate_r1_evidence(composed: ComposedRuntimeState, evidence_manifest: list[Any]) -> None:
    if "r1_4_tool_execution" not in composed.extension_states:
        return
    state = composed.extension_state("r1_4_tool_execution")
    records = {item.evidence_id: item for item in getattr(state, "evidence_records", ())}
    for item in evidence_manifest:
        if not isinstance(item, Mapping):
            continue
        evidence_id = item.get("evidence_id") or item.get("evidence_ref")
        if evidence_id not in records:
            raise R34Error("R3_4_R1_EVIDENCE_REFERENCE_INVALID", "evidence manifest references an unknown R1 EvidenceRecord")
        if item.get("verified") is True and not records[evidence_id].verified:
            raise R34Error("R3_4_R1_EVIDENCE_REFERENCE_INVALID", "evidence manifest cannot upgrade an unverified R1 EvidenceRecord")


def _attempt(request: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> CaseExecutionAttempt:
    state = _state(composed)
    readiness = state.readiness(_text(request.get("execution_readiness_id"), "execution_readiness_id"))
    if readiness is None or readiness.readiness_status != "READY":
        raise R34Error("R3_4_READINESS_NOT_READY", "CaseExecutionAttempt requires READY ExecutionReadiness")
    review = state.review(readiness.case_review_id)
    oracle = state.oracle(readiness.oracle_specification_id)
    if review is None or oracle is None:
        raise R34Error("R3_4_APPROVAL_CHAIN_MISSING", "approved review and oracle are required")
    r1 = _validate_r1_attempt(composed, request)
    _validate_r2_session(composed, request)
    attempt_identity = {"readiness": readiness.readiness_fingerprint, "r1": r1["lineage_digest"], "idempotency": request["idempotency_key"]}
    attempt_id = request.get("case_execution_attempt_id") or f"r34-attempt:{canonical_sha256(attempt_identity)}"
    execution_status = request.get("execution_status", "CREATED")
    if execution_status not in EXECUTION_STATUSES:
        raise R34Error("R3_4_STATUS_INVALID", "unsupported execution_status")
    return CaseExecutionAttempt(
        case_execution_attempt_id=attempt_id, version=int(request.get("version", 1)), mission_id=request["mission_id"], scope_identity=request["scope_identity"], case_version_id=review.case_version_id, case_version_digest=review.case_version_digest, case_review_id=review.case_review_id, review_digest=review.review_fingerprint, execution_readiness_id=readiness.execution_readiness_id, readiness_digest=readiness.readiness_fingerprint, precondition_resolution_digest=canonical_sha256(readiness.precondition_resolution_refs), test_data_resolution_digest=canonical_sha256(readiness.test_data_resolution_refs), oracle_specification_id=oracle.oracle_specification_id, oracle_specification_digest=oracle.oracle_fingerprint, evidence_requirement_set_id=oracle.evidence_requirement_set_id, evidence_requirement_digest=oracle.evidence_requirement_digest, r1_runtime_attempt_id=r1["attempt_id"], r1_root_attempt_id=r1["root_attempt_id"], r1_attempt_lineage_digest=r1["lineage_digest"], runtime_session_id=r1["runtime_session_id"], task_id=r1["task_id"], plan_id=r1["plan_id"], plan_revision_id=r1["plan_revision_id"], r2_executor_session_ref=_text(request.get("r2_executor_session_ref"), "r2_executor_session_ref"), execution_status=execution_status, started_at=request.get("started_at") or f"seq:{composed.seq + 1}", completed_at=request.get("completed_at"), execution_fact_refs=tuple(request.get("execution_fact_refs") or ()), evidence_refs=tuple(request.get("evidence_refs") or ()), source_provenance=review.source_provenance, attempt_fingerprint=canonical_sha256({"case": review.case_version_digest, "review": review.review_fingerprint, "readiness": readiness.readiness_fingerprint, "oracle": oracle.oracle_fingerprint, "r1": r1["lineage_digest"], "executor": request.get("r2_executor_session_ref")}), idempotency_key=request["idempotency_key"], correlation_id=request["correlation_id"],
    )


def _evaluation(request: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> OracleEvaluation:
    state = _state(composed)
    attempt = state.attempt(_text(request.get("case_execution_attempt_id"), "case_execution_attempt_id"))
    if attempt is None:
        raise R34Error("R3_4_ATTEMPT_NOT_FOUND", "OracleEvaluation requires a CaseExecutionAttempt")
    oracle = state.oracle(attempt.oracle_specification_id)
    if oracle is None or request.get("oracle_specification_digest", oracle.oracle_fingerprint) != oracle.oracle_fingerprint:
        raise R34Error("R3_4_ORACLE_IMMUTABILITY_VIOLATION", "evaluation oracle digest does not match approved oracle")
    observations = _payload(request.get("observations") or {}, "observations")
    evidence_manifest = _array(request.get("evidence_manifest") or request.get("evidence_records") or (), "evidence_manifest")
    _validate_r1_evidence(composed, evidence_manifest)
    evidence_refs = tuple(_text(item.get("evidence_id") or item.get("evidence_ref"), "evidence_id") for item in evidence_manifest if isinstance(item, Mapping) and (item.get("evidence_id") or item.get("evidence_ref")))
    required_fields = {str(item.get("field")) for item in oracle.observation_schema if item.get("field")}
    missing_fields = sorted(required_fields - set(observations))
    unexpected_fields = sorted(set(observations) - required_fields)
    if unexpected_fields:
        raise R34Error("R3_4_OBSERVATION_SCHEMA_INVALID", f"observations contain fields outside the approved schema: {unexpected_fields}")
    explicit_sufficiency = request.get("evidence_sufficiency")
    if explicit_sufficiency not in EVIDENCE_SUFFICIENCY and explicit_sufficiency is not None:
        raise R34Error("R3_4_EVIDENCE_STATE_INVALID", "invalid evidence_sufficiency")
    required_requirements = tuple(item for item in state.evidence_requirements if item.oracle_specification_id == oracle.oracle_specification_id and item.required)
    missing_requirements: list[str] = []
    for requirement in required_requirements:
        matches = [
            item for item in evidence_manifest
            if isinstance(item, Mapping)
            and (item.get("evidence_requirement_id") or item.get("requirement_id")) == requirement.evidence_requirement_id
        ]
        if not matches and len(required_requirements) == 1 and evidence_manifest:
            matches = [item for item in evidence_manifest if isinstance(item, Mapping)]
        if not matches:
            missing_requirements.append(requirement.evidence_requirement_id)
            continue
        if any((item.get("stage") or item.get("capture_stage")) not in {None, requirement.capture_stage} for item in matches):
            missing_requirements.append(requirement.evidence_requirement_id)
    verified = all(bool(item.get("verified")) for item in evidence_manifest if isinstance(item, Mapping)) if evidence_manifest else False
    derived_sufficiency = "SUFFICIENT" if evidence_refs and verified and not missing_fields and not missing_requirements else "INSUFFICIENT"
    sufficiency = explicit_sufficiency or derived_sufficiency
    if sufficiency == "SUFFICIENT" and derived_sufficiency != "SUFFICIENT":
        sufficiency = "INSUFFICIENT"
    decision = request.get("oracle_decision")
    if sufficiency != "SUFFICIENT":
        decision = "EVIDENCE_INSUFFICIENT"
        business = "NOT_EVALUATED"
        reasons = tuple(dict.fromkeys(("required evidence is missing, unverified, or schema-incomplete", *missing_fields, *missing_requirements)))
    elif attempt.execution_status != "EXECUTION_SUCCEEDED":
        decision = "NOT_EVALUATED"
        business = "NOT_EVALUATED"
        reasons = (f"execution status {attempt.execution_status} is not business-evaluable",)
    else:
        if decision is None:
            if request.get("pass_condition_met") is True:
                decision = "PASS"
            elif request.get("fail_condition_met") is True:
                decision = "FAIL"
            else:
                decision = "INCONCLUSIVE"
        if decision not in ORACLE_DECISIONS:
            raise R34Error("R3_4_ORACLE_DECISION_INVALID", "invalid oracle decision")
        if decision == "PASS" and request.get("pass_condition_met", True) is not True:
            decision = "FAIL"
        business = "PASS" if decision == "PASS" else "FAIL" if decision == "FAIL" else "INCONCLUSIVE" if decision == "INCONCLUSIVE" else "NOT_EVALUATED"
        reasons = tuple(_text(item, "reason") for item in (request.get("reasons") or ()))
    evidence_digest = canonical_sha256({"refs": list(evidence_refs), "manifest": [{"evidence_id": item.get("evidence_id") or item.get("evidence_ref"), "verified": item.get("verified"), "stage": item.get("stage")} for item in evidence_manifest if isinstance(item, Mapping)]})
    evaluation_digest = canonical_sha256({"attempt": attempt.attempt_fingerprint, "oracle": oracle.oracle_fingerprint, "observations": observations, "evidence_manifest_digest": evidence_digest})
    return OracleEvaluation(
        oracle_evaluation_id=request.get("oracle_evaluation_id") or f"r34-evaluation:{evaluation_digest}", version=int(request.get("version", 1)), case_execution_attempt_id=attempt.case_execution_attempt_id, oracle_specification_id=oracle.oracle_specification_id, oracle_specification_digest=oracle.oracle_fingerprint, observation_digest=canonical_sha256(observations), evidence_manifest_digest=evidence_digest, evidence_cutoff_ref=request.get("evidence_cutoff_ref") or f"r1:seq:{composed.seq}", evidence_sufficiency=sufficiency, oracle_decision=decision, business_validation=business, matched_observations=tuple(request.get("matched_observations") or ()), unmet_conditions=tuple(request.get("unmet_conditions") or ()), reasons=reasons, evaluated_at=request.get("evaluated_at") or f"seq:{composed.seq + 1}", evaluated_by=_actor(command), provenance_refs=tuple(request.get("provenance_refs") or attempt.source_provenance), evidence_refs=evidence_refs, evaluation_fingerprint=evaluation_digest, supersedes_evaluation_id=request.get("supersedes_evaluation_id"),
    )


def _result(request: Mapping[str, Any], composed: ComposedRuntimeState) -> TestResult:
    state = _state(composed)
    attempt = state.attempt(_text(request.get("case_execution_attempt_id"), "case_execution_attempt_id"))
    if attempt is None:
        raise R34Error("R3_4_ATTEMPT_NOT_FOUND", "TestResult requires a CaseExecutionAttempt")
    evaluation = state.evaluation(_text(request.get("oracle_evaluation_id"), "oracle_evaluation_id"))
    if evaluation is None:
        raise R34Error("R3_4_EVALUATION_NOT_FOUND", "TestResult requires an OracleEvaluation")
    if evaluation.case_execution_attempt_id != attempt.case_execution_attempt_id:
        raise R34Error("R3_4_RESULT_LINEAGE_INVALID", "evaluation and attempt identity mismatch")
    if evaluation.evidence_sufficiency != "SUFFICIENT":
        status = "EVIDENCE_INSUFFICIENT"
    elif attempt.execution_status == "EXECUTION_SUCCEEDED" and evaluation.oracle_decision == "PASS" and evaluation.business_validation == "PASS":
        status = "PASS"
    elif attempt.execution_status == "EXECUTION_SUCCEEDED" and evaluation.oracle_decision == "FAIL":
        status = "FAIL"
    elif attempt.execution_status in {"BLOCKED", "ABANDONED", "CANCELLED"}:
        status = "BLOCKED" if attempt.execution_status == "BLOCKED" else "NOT_EXECUTED"
    elif attempt.execution_status == "EXECUTION_FAILED":
        status = "ERROR"
    else:
        status = "INCONCLUSIVE"
    if status == "PASS" and (attempt.execution_status != "EXECUTION_SUCCEEDED" or evaluation.evidence_sufficiency != "SUFFICIENT"):
        raise R34Error("R3_4_RESULT_SAFETY_VIOLATION", "result PASS safety rule failed")
    result_identity = {"attempt": attempt.attempt_fingerprint, "evaluation": evaluation.evaluation_fingerprint, "status": status}
    return TestResult(
        test_result_id=request.get("test_result_id") or f"r34-result:{canonical_sha256(result_identity)}", version=int(request.get("version", 1)), case_execution_attempt_id=attempt.case_execution_attempt_id, case_version_id=attempt.case_version_id, case_version_digest=attempt.case_version_digest, execution_status=attempt.execution_status, oracle_evaluation_id=evaluation.oracle_evaluation_id, oracle_decision=evaluation.oracle_decision, evidence_sufficiency=evaluation.evidence_sufficiency, business_validation_status=evaluation.business_validation, result_status=status, result_reason=request.get("result_reason") or ("EVIDENCE_INSUFFICIENT" if status == "EVIDENCE_INSUFFICIENT" else evaluation.reasons[0] if evaluation.reasons else status), execution_fact_refs=attempt.execution_fact_refs, evidence_refs=evaluation.evidence_refs, result_fingerprint=canonical_sha256(result_identity), created_at=request.get("created_at") or f"seq:{composed.seq + 1}", provenance_refs=tuple(dict.fromkeys(attempt.source_provenance + evaluation.provenance_refs)),
    )


def _reuse_or_none(state: R34State, entity_type: str, fingerprint: str, idempotency_key: str, entity_id: str, command: Any) -> list[PendingEvent] | None:
    existing = next((item for item in state.reuses if item.entity_type == entity_type and item.fingerprint == fingerprint), None)
    existing_entity = existing.entity_id if existing is not None else entity_id
    if existing is None:
        collection = {
            "ReviewerContextSnapshot": state.reviewer_contexts,
            "CaseReview": state.case_reviews,
            "OracleSpecification": state.oracle_specifications,
            "ExecutionReadinessAssessment": state.execution_readiness,
            "CaseExecutionAttempt": state.case_execution_attempts,
            "OracleEvaluation": state.oracle_evaluations,
            "TestResult": state.test_results,
        }.get(entity_type, ())
        fingerprint_name = {
            "ReviewerContextSnapshot": "reviewer_context_digest",
            "CaseReview": "review_fingerprint",
            "OracleSpecification": "oracle_fingerprint",
            "ExecutionReadinessAssessment": "readiness_fingerprint",
            "CaseExecutionAttempt": "attempt_fingerprint",
            "OracleEvaluation": "evaluation_fingerprint",
            "TestResult": "result_fingerprint",
        }.get(entity_type)
        matched = next((item for item in collection if fingerprint_name and getattr(item, fingerprint_name) == fingerprint), None)
        if matched is not None:
            existing_entity = getattr(matched, next(iter(type(matched).__dataclass_fields__)))
            existing = R34ReuseReference("pending", entity_type, existing_entity, fingerprint, idempotency_key, 0, "pending", command.correlation_id)
    if existing is None:
        return None
    return [PendingEvent(SEMANTIC_REUSE, "R3_4_REUSE", f"r3.4:reuse:{command.command_id}", {"reuse": R34ReuseReference(f"r34-reuse:{command.command_id}", entity_type, existing_entity, fingerprint, idempotency_key, 0, "pending", command.correlation_id).to_dict()}, session_id=command.session_id)]


def handle(command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
    request = _request(command)
    state = _state(composed)
    if command.type == BUILD_REVIEW_CONTEXT:
        context = _reviewer_context(request, composed, command)
        reuse = _reuse_or_none(state, "ReviewerContextSnapshot", context.reviewer_context_digest, request["idempotency_key"], context.reviewer_context_id, command)
        return reuse or [PendingEvent(REVIEWER_CONTEXT_BUILT, "R3_4_REVIEWER_CONTEXT", context.reviewer_context_id, {"reviewer_context": context.to_dict()}, session_id=command.session_id)]
    if command.type == REVIEW_CASE:
        review = _case_review(request, composed, command)
        reuse = _reuse_or_none(state, "CaseReview", review.review_fingerprint, request["idempotency_key"], review.case_review_id, command)
        return reuse or [PendingEvent(CASE_REVIEWED, "R3_4_CASE_REVIEW", review.case_review_id, {"case_review": review.to_dict()}, session_id=command.session_id)]
    if command.type == APPROVE_ORACLE_SPECIFICATION:
        review = state.review(_text(request.get("case_review_id"), "case_review_id"))
        if review is None or review.review_status != "APPROVED":
            raise R34Error("R3_4_REVIEW_NOT_APPROVED", "Oracle approval requires an approved CaseReview")
        if any(item.case_review_id == review.case_review_id for item in state.oracle_specifications):
            raise R34Error("R3_4_ORACLE_IMMUTABILITY_VIOLATION", "an approved oracle already exists for this review")
        context = state.reviewer_context(review.reviewer_context_id)
        if context is None:
            raise R34Error("R3_4_REVIEW_CONTEXT_REQUIRED", "review context is missing")
        case = StandardTestCase.from_dict(context.case_version_snapshot)
        oracle, evidence = _oracle_and_evidence(request, review, case, command)
        reuse = _reuse_or_none(state, "OracleSpecification", oracle.oracle_fingerprint, request["idempotency_key"], oracle.oracle_specification_id, command)
        return reuse or [PendingEvent(ORACLE_SPECIFICATION_APPROVED, "R3_4_ORACLE_SPECIFICATION", oracle.oracle_specification_id, {"oracle_specification": oracle.to_dict(), "evidence_requirements": [item.to_dict() for item in evidence]}, session_id=command.session_id)]
    if command.type == ASSESS_EXECUTION_READINESS:
        readiness, preconditions, data = _readiness(request, composed, command)
        reuse = _reuse_or_none(state, "ExecutionReadinessAssessment", readiness.readiness_fingerprint, request["idempotency_key"], readiness.execution_readiness_id, command)
        return reuse or [PendingEvent(EXECUTION_READINESS_ASSESSED, "R3_4_EXECUTION_READINESS", readiness.execution_readiness_id, {"readiness": readiness.to_dict(), "precondition_requirements": [item.to_dict() for item in preconditions], "test_data_requirements": [item.to_dict() for item in data]}, session_id=command.session_id)]
    if command.type == RESOLVE_PRECONDITION:
        requirement_id = _text(request.get("requirement_id"), "requirement_id")
        requirement = state.precondition_requirement(requirement_id)
        if requirement is None:
            raise R34Error("R3_4_PRECONDITION_NOT_FOUND", "precondition requirement is missing")
        state_value = request.get("resolution_state", "RESOLVED")
        if state_value not in RESOLUTION_STATES:
            raise R34Error("R3_4_RESOLUTION_STATE_INVALID", "invalid precondition resolution state")
        digest = canonical_sha256({"requirement_id": requirement_id, "state": state_value, "observed_state_ref": request.get("observed_state_ref"), "runtime_fact_refs": list(request.get("runtime_fact_refs") or ()), "tool_execution_refs": list(request.get("tool_execution_refs") or ()), "evidence_refs": list(request.get("evidence_refs") or ())})
        resolution = PreconditionResolution(precondition_resolution_id=request.get("precondition_resolution_id") or f"r34-precondition-resolution:{digest}", requirement_id=requirement_id, version=int(request.get("version", 1)), resolution_state=state_value, observed_state_ref=request.get("observed_state_ref"), runtime_fact_refs=tuple(request.get("runtime_fact_refs") or ()), tool_execution_refs=tuple(request.get("tool_execution_refs") or ()), evidence_refs=tuple(request.get("evidence_refs") or ()), observation_digest=request.get("observation_digest") or digest, resolved_at=request.get("resolved_at") or f"seq:{composed.seq + 1}", valid_until=request.get("valid_until"), resolver_session_ref=request.get("resolver_session_ref"), resolution_fingerprint=digest, provenance=tuple(request.get("provenance") or requirement.provenance_refs))
        return [PendingEvent(PRECONDITION_RESOLVED, "R3_4_PRECONDITION_RESOLUTION", resolution.precondition_resolution_id, {"resolution": resolution.to_dict()}, session_id=command.session_id)]
    if command.type == RESOLVE_TEST_DATA:
        requirement_id = _text(request.get("requirement_id"), "requirement_id")
        requirement = state.test_data_requirement(requirement_id)
        if requirement is None:
            raise R34Error("R3_4_TEST_DATA_NOT_FOUND", "test-data requirement is missing")
        state_value = request.get("resolution_state", "RESOLVED")
        if state_value not in DATA_RESOLUTION_STATES:
            raise R34Error("R3_4_RESOLUTION_STATE_INVALID", "invalid test-data resolution state")
        digest = canonical_sha256({"requirement_id": requirement_id, "state": state_value, "dataset_ref": request.get("resolved_dataset_ref"), "dataset_digest": request.get("dataset_digest"), "lease_or_scope_ref": request.get("lease_or_scope_ref"), "evidence_refs": list(request.get("evidence_refs") or ())})
        resolution = TestDataResolution(test_data_resolution_id=request.get("test_data_resolution_id") or f"r34-test-data-resolution:{digest}", requirement_id=requirement_id, version=int(request.get("version", 1)), resolution_state=state_value, resolved_dataset_ref=request.get("resolved_dataset_ref"), dataset_digest=request.get("dataset_digest"), lease_or_scope_ref=request.get("lease_or_scope_ref"), runtime_fact_refs=tuple(request.get("runtime_fact_refs") or ()), tool_execution_refs=tuple(request.get("tool_execution_refs") or ()), evidence_refs=tuple(request.get("evidence_refs") or ()), resolved_at=request.get("resolved_at") or f"seq:{composed.seq + 1}", valid_until=request.get("valid_until"), resolution_fingerprint=digest, provenance=tuple(request.get("provenance") or requirement.source_refs))
        return [PendingEvent(TEST_DATA_RESOLVED, "R3_4_TEST_DATA_RESOLUTION", resolution.test_data_resolution_id, {"resolution": resolution.to_dict()}, session_id=command.session_id)]
    if command.type == REGISTER_CASE_EXECUTION_ATTEMPT:
        attempt = _attempt(request, composed, command)
        reuse = _reuse_or_none(state, "CaseExecutionAttempt", attempt.attempt_fingerprint, request["idempotency_key"], attempt.case_execution_attempt_id, command)
        return reuse or [PendingEvent(CASE_EXECUTION_ATTEMPT_REGISTERED, "R3_4_CASE_EXECUTION_ATTEMPT", attempt.case_execution_attempt_id, {"attempt": attempt.to_dict()}, session_id=command.session_id)]
    if command.type == EVALUATE_ORACLE:
        evaluation = _evaluation(request, composed, command)
        reuse = _reuse_or_none(state, "OracleEvaluation", evaluation.evaluation_fingerprint, request["idempotency_key"], evaluation.oracle_evaluation_id, command)
        return reuse or [PendingEvent(ORACLE_EVALUATED, "R3_4_ORACLE_EVALUATION", evaluation.oracle_evaluation_id, {"evaluation": evaluation.to_dict()}, session_id=command.session_id)]
    if command.type == RECORD_TEST_RESULT:
        result = _result(request, composed)
        reuse = _reuse_or_none(state, "TestResult", result.result_fingerprint, request["idempotency_key"], result.test_result_id, command)
        return reuse or [PendingEvent(TEST_RESULT_RECORDED, "R3_4_TEST_RESULT", result.test_result_id, {"result": result.to_dict()}, session_id=command.session_id)]
    raise R34Error("R3_4_UNSUPPORTED_COMMAND", f"unsupported R3.4 command: {command.type}")


class R34CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)
