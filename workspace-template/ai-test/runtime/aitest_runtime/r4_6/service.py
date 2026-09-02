from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService
from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError

from .contracts import *
from .errors import *
from .extension import r4_6_extension


_REQUIRED_PROVENANCE: dict[CandidateType, frozenset[str]] = {
    CandidateType.DEFECT_LEARNING: frozenset({"R3_6_DEFECT_ASSESSMENT", "R3_6_EVIDENCE_ASSESSMENT", "R3_6_REPRODUCIBILITY", "R3_6_FALSE_POSITIVE"}),
    CandidateType.TEST_STRATEGY_LEARNING: frozenset({"R3_4_REQUIREMENT_OR_JOURNEY", "R3_4_COVERAGE", "R3_4_TEST_RESULT", "R3_4_EVIDENCE", "R3_7_TEST_SUFFICIENCY"}),
    CandidateType.ORACLE_LEARNING: frozenset({"R3_4_ORACLE", "R3_4_TEST_RESULT", "R3_4_EVIDENCE", "R3_4_REQUIREMENT_OR_JOURNEY"}),
    CandidateType.BUSINESS_JOURNEY_LEARNING: frozenset({"R3_4_REQUIREMENT_OR_JOURNEY", "R3_4_ORACLE", "R3_4_TEST_RESULT", "R3_4_EVIDENCE"}),
    CandidateType.ENVIRONMENT_OR_RUNTIME_LEARNING: frozenset({"R3_6_EVIDENCE_ASSESSMENT", "R4_2_TRIGGER", "R4_2_IMPACT_ASSESSMENT"}),
    CandidateType.HUMAN_TAUGHT_LEARNING: frozenset({"HUMAN_TEACHING"}),
    CandidateType.KNOWLEDGE_CORRECTION_LEARNING: frozenset({"R3_E1_KNOWLEDGE_VERSION"}),
}


def _raw(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    raise R46Error(R46_COMMAND_INVALID, "R4.6 value must be a record or mapping")


def _common_defaults(raw: dict[str, Any], *, mission_id: str | None = None, actor: ActorRef | None = None) -> dict[str, Any]:
    selected_mission = str(raw.get("owner_mission_id") or raw.get("mission_id") or mission_id or "")
    if selected_mission:
        raw["owner_mission_id"] = selected_mission
    raw.setdefault("owner_stream_key", f"r4.6:{selected_mission}")
    raw.setdefault("revision", 1)
    raw.setdefault("record_digest", None)
    raw.setdefault("as_of_seq", 0)
    raw.setdefault("source_cursor", raw.get("as_of_seq", 0))
    raw.setdefault("correlation_id", "r4.6")
    raw.setdefault("causation_id", "r4.6")
    raw.setdefault("created_by", (actor or ActorRef("SYSTEM", "r4.6")).to_dict())
    raw.setdefault("created_seq", 0)
    raw.setdefault("created_at", "seq:0")
    return raw


def _provisional(cls: type[Any], value: Any, *, mission_id: str | None = None, actor: ActorRef | None = None) -> Any:
    return cls.from_dict(_common_defaults(_raw(value), mission_id=mission_id, actor=actor))


def _ref(value: Any) -> TypedReference:
    return value if isinstance(value, TypedReference) else TypedReference.from_dict(value)


def _policy(value: Any) -> R46PolicySnapshot:
    return value if isinstance(value, R46PolicySnapshot) else R46PolicySnapshot.from_dict(value)


def _provenance_names(refs: Iterable[TypedReference]) -> set[str]:
    names: set[str] = set()
    for ref in refs:
        names.add(str(ref.ref_type))
        names.add(str(ref.origin))
    return names


def _required_for(candidate_type: CandidateType) -> set[str]:
    if candidate_type is CandidateType.ENVIRONMENT_OR_RUNTIME_LEARNING:
        return set()
    return set(_REQUIRED_PROVENANCE[candidate_type])


def _candidate_outcome(candidate: R46CandidateRevision, policy: R46PolicySnapshot) -> CandidateValidationOutcome:
    facts = dict(candidate.validation_facts)
    names = _provenance_names(candidate.authoritative_provenance_refs + candidate.evidence_refs)
    if facts.get("conflict") or facts.get("unresolved_conflict") or candidate.conflict_refs:
        return CandidateValidationOutcome.CONFLICT
    if facts.get("rejected") or facts.get("invalid") or candidate.candidate_scope.scope_class is R46ScopeClass.PERSONAL_PRIVATE and candidate.promotion_target_scope.scope_class is not R46ScopeClass.PERSONAL_PRIVATE:
        return CandidateValidationOutcome.REJECTED
    if facts.get("blocked") or facts.get("unavailable_prerequisite") or candidate.availability is Availability.UNAVAILABLE:
        return CandidateValidationOutcome.BLOCKED
    required = _required_for(candidate.candidate_type)
    if candidate.candidate_type is CandidateType.HUMAN_TAUGHT_LEARNING and names & {"Teaching Candidate", "UserProvidedFactCandidate", "ProjectKnowledgeCandidate"}:
        required = set()
    missing = required - names
    if candidate.candidate_type is CandidateType.ENVIRONMENT_OR_RUNTIME_LEARNING and not ({"R3_6_EVIDENCE_ASSESSMENT"} <= names or {"R4_2_TRIGGER", "R4_2_IMPACT_ASSESSMENT"} <= names):
        missing = {"R3_6_EVIDENCE_ASSESSMENT or R4_2_TRIGGER+R4_2_IMPACT_ASSESSMENT"}
    if missing or not candidate.authoritative_provenance_refs and not candidate.evidence_refs:
        return CandidateValidationOutcome.INCOMPLETE
    if policy.freshness_requirement is R46FreshnessRequirement.CURRENT_ONLY and candidate.freshness is not Freshness.CURRENT:
        return CandidateValidationOutcome.INCOMPLETE
    if policy.availability_requirement is R46AvailabilityRequirement.AVAILABLE_ONLY and candidate.availability is not Availability.AVAILABLE:
        return CandidateValidationOutcome.BLOCKED if candidate.availability is Availability.UNAVAILABLE else CandidateValidationOutcome.INCOMPLETE
    if policy.field_validation_requirement is R46FieldValidationRequirement.PASSED_REQUIRED and candidate.field_validation_state is not FieldValidationState.PASSED:
        return CandidateValidationOutcome.INCOMPLETE
    if candidate.source_cursor < policy.as_of_cursor:
        return CandidateValidationOutcome.INCOMPLETE
    return CandidateValidationOutcome.VALIDATED


def _eligibility_status(candidate: R46CandidateRevision, policy: R46PolicySnapshot, gate: HumanGateLinkage | None) -> PromotionEligibilityStatus:
    if candidate.validation_outcome is CandidateValidationOutcome.CONFLICT or candidate.conflict_refs:
        return PromotionEligibilityStatus.CONFLICT
    if candidate.validation_outcome is CandidateValidationOutcome.BLOCKED:
        return PromotionEligibilityStatus.BLOCKED
    if candidate.validation_outcome is not CandidateValidationOutcome.VALIDATED:
        return PromotionEligibilityStatus.INCOMPLETE
    if candidate.lifecycle_state is not CandidateLifecycleState.CURRENT:
        return PromotionEligibilityStatus.STALE
    if candidate.candidate_scope.scope_class is R46ScopeClass.PERSONAL_PRIVATE and candidate.promotion_target_scope.scope_class is not R46ScopeClass.PERSONAL_PRIVATE:
        return PromotionEligibilityStatus.NOT_ELIGIBLE
    widening = candidate.source_scope.scope_class is not candidate.promotion_target_scope.scope_class
    if widening:
        decision = candidate.promotion_target_scope.scope_widening_decision
        if decision in {R46ScopeWideningDecision.NOT_APPLICABLE, R46ScopeWideningDecision.DENIED}:
            return PromotionEligibilityStatus.BLOCKED
        if decision is R46ScopeWideningDecision.REQUIRES_HUMAN_GATE and (
            not policy.approval_required
            or gate is None
            or gate.decision_outcome != "ALLOW"
            or gate.continuation_state not in {"READY", "CONTINUED", "COMPLETE"}
        ):
            return PromotionEligibilityStatus.BLOCKED
    if policy.approval_required and (gate is None or gate.decision_outcome != "ALLOW" or gate.continuation_state not in {"READY", "CONTINUED", "COMPLETE"}):
        return PromotionEligibilityStatus.BLOCKED
    if candidate.freshness is not Freshness.CURRENT or candidate.availability is not Availability.AVAILABLE:
        return PromotionEligibilityStatus.STALE if candidate.freshness is Freshness.STALE else PromotionEligibilityStatus.INCOMPLETE
    if policy.field_validation_requirement is R46FieldValidationRequirement.PASSED_REQUIRED and candidate.field_validation_state is not FieldValidationState.PASSED:
        return PromotionEligibilityStatus.INCOMPLETE
    return PromotionEligibilityStatus.ELIGIBLE


class R46ApplicationService:
    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime = runtime_service
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.6")

    def state(self, mission_id: str) -> R46State:
        value = self._runtime.get_composed_state(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, R46State):
            raise R46Error(R46_COMMAND_INVALID, "R4.6 extension state is invalid")
        return value

    get_state = state

    def candidate(self, mission_id: str, candidate_id: str) -> R46ValidatedLearningCandidate | None:
        return self.state(mission_id).candidate(candidate_id)

    def current_candidate(self, mission_id: str, candidate_id: str) -> R46CandidateCurrentResolution:
        return self.state(mission_id).current_candidate(candidate_id)

    def eligibility(self, mission_id: str, eligibility_id: str) -> R46PromotionEligibilityAssessment | None:
        return self.state(mission_id).eligibility(eligibility_id)

    def request(self, mission_id: str, request_id: str) -> R46KnowledgePromotionRequest | None:
        return self.state(mission_id).request(request_id)

    def receipt(self, mission_id: str, receipt_id: str) -> R46KnowledgePromotionReceipt | None:
        return self.state(mission_id).receipt(receipt_id)

    def evaluate_candidate_revision(self, revision: R46CandidateRevision | Mapping[str, Any], *, policy: R46PolicySnapshot | Mapping[str, Any] | None = None) -> R46CandidateRevision:
        candidate = revision if isinstance(revision, R46CandidateRevision) else _provisional(R46CandidateRevision, revision, actor=self.actor)
        selected_policy = _policy(policy or candidate.policy_snapshot)
        if candidate.candidate_id == "pending":
            object.__setattr__(candidate, "candidate_id", candidate_id_for(candidate.candidate_type, candidate.candidate_claim.claim_digest, candidate.candidate_scope, candidate.promotion_target_scope))
        outcome = _candidate_outcome(candidate, selected_policy)
        return replace(candidate, policy_snapshot=selected_policy, validation_outcome=outcome, lifecycle_state=CandidateLifecycleState.CURRENT, candidate_digest=None, revision_digest=None, record_digest=None)

    def _error(self, command_id: str, mission_id: str, exc: Exception) -> R46OperationResult:
        error = exc if isinstance(exc, (R46Error, DurableRuntimeError)) else R46Error(R46_COMMAND_INVALID, str(exc))
        return R46OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    def _execute(self, *, command_type: str, record: Any, key: str, expected_seq: int | None, command_id: str | None, correlation_id: str | None, actor: ActorRef | None, payload_key: str) -> R46OperationResult:
        mission_id = record.owner_mission_id
        command_identifier = command_id or f"r4.6:{key}"
        try:
            current_state = self.state(mission_id)
            existing = None
            if payload_key == "candidate_revision":
                existing = current_state.candidate_revision(record.revision_id)
                same = existing is not None and existing.revision_digest == record.revision_digest
            elif payload_key == "eligibility":
                existing = current_state.eligibility(record.eligibility_id)
                same = existing is not None and existing.assessment_digest == record.assessment_digest
            elif payload_key == "request":
                existing = current_state.request(record.request_id)
                same = existing is not None and existing.request_digest == record.request_digest
            elif payload_key == "receipt":
                existing = current_state.receipt(record.receipt_id)
                same = existing is not None and existing.receipt_digest == record.receipt_digest
            else:
                existing = current_state.disposition(record.disposition_id)
                same = existing is not None and existing.disposition_digest == record.disposition_digest
            if existing is not None:
                if not same:
                    return self._error(command_identifier, mission_id, R46Error(R46_IDENTITY_CONFLICT, "identity already owns a different immutable digest"))
                return R46OperationResult(CommandResult("DUPLICATE", command_identifier, mission_id, duplicate_of=command_identifier, first_seq=existing.created_seq, last_seq=existing.created_seq), existing)
            result = self._runtime.execute({
                "command_id": command_identifier,
                "type": command_type,
                "mission_id": mission_id,
                "session_id": None,
                "expected_seq": self._runtime.get_head_seq(mission_id) if expected_seq is None else expected_seq,
                "actor": (actor or self.actor).to_dict(),
                "payload": {payload_key: record.to_dict()},
                "idempotency_key": f"r4.6:{key}",
                "correlation_id": correlation_id or command_identifier,
                "schema_version": 1,
            })
            entity = None
            if result.ok:
                state = self.state(mission_id)
                if payload_key == "candidate_revision":
                    entity = state.candidate_revision(record.revision_id)
                elif payload_key == "eligibility":
                    entity = state.eligibility(record.eligibility_id)
                elif payload_key == "request":
                    entity = state.request(record.request_id)
                elif payload_key == "receipt":
                    entity = state.receipt(record.receipt_id)
                elif payload_key == "disposition":
                    entity = state.disposition(record.disposition_id)
            return R46OperationResult(result, entity)
        except Exception as exc:
            return self._error(command_identifier, mission_id, exc)

    def record_candidate_revision(self, value: R46CandidateRevision | Mapping[str, Any], *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        try:
            record = self.evaluate_candidate_revision(value)
            return self._execute(command_type=R4_6_RECORD_CANDIDATE_REVISION, record=record, key=f"candidate-revision:{record.revision_id}", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor, payload_key="candidate_revision")
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("candidate_id") or ""), str(raw.get("owner_mission_id") or ""), exc)

    def evaluate_promotion_eligibility(self, mission_id: str, candidate_revision_ref: TypedReference | Mapping[str, Any], policy: R46PolicySnapshot | Mapping[str, Any]) -> R46PromotionEligibilityAssessment:
        reference = _ref(candidate_revision_ref)
        selected_policy = _policy(policy)
        candidate = self.state(mission_id).candidate_revision(reference.object_id)
        if candidate is None:
            raise R46Error(R46_REFERENCE_INVALID, "candidate revision is not present")
        if reference.source_digest not in {candidate.record_digest, candidate.revision_digest, candidate.candidate_digest}:
            raise R46Error(R46_DIGEST_CONFLICT, "candidate revision reference digest is stale")
        gate_raw = candidate.validation_facts.get("human_gate_linkage")
        gate = gate_raw if isinstance(gate_raw, HumanGateLinkage) else HumanGateLinkage.from_dict(gate_raw) if isinstance(gate_raw, Mapping) else None
        status = _eligibility_status(candidate, selected_policy, gate)
        input_snapshot = {"candidate_revision": reference.to_dict(), "candidate_digest": candidate.record_digest, "policy_digest": selected_policy.policy_digest, "source_cursor": candidate.source_cursor}
        identity = eligibility_id_for(reference, candidate.record_digest, selected_policy.policy_digest, input_snapshot)
        return R46PromotionEligibilityAssessment(
            owner_mission_id=mission_id,
            owner_stream_key=f"r4.6:{mission_id}",
            revision=1,
            record_digest=None,
            as_of_seq=self._runtime.get_head_seq(mission_id),
            source_cursor=candidate.source_cursor,
            correlation_id="r4.6",
            causation_id="r4.6:evaluate-eligibility",
            created_by=self.actor,
            created_seq=0,
            created_at="seq:0",
            eligibility_id=identity,
            candidate_revision_ref=reference,
            candidate_revision_digest=candidate.record_digest,
            policy_snapshot=selected_policy,
            status=status,
            observed_required_provenance_refs=candidate.authoritative_provenance_refs,
            observed_conditional_provenance_refs=(),
            observed_context_refs=candidate.evidence_refs,
            freshness=candidate.freshness,
            availability=candidate.availability,
            field_validation_state=candidate.field_validation_state,
            human_gate_required=selected_policy.approval_required,
            human_gate_linkage=gate,
            knowledge_target_scope=candidate.promotion_target_scope,
            knowledge_target_requirements=dict(selected_policy.target_scope_requirements),
            conflict_refs=candidate.conflict_refs,
            blocking_refs=(),
            unknown_refs=(),
            incomplete_refs=(),
            assessment_digest=None,
        )

    def record_promotion_eligibility(self, value: R46PromotionEligibilityAssessment | Mapping[str, Any], *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        try:
            record = _provisional(R46PromotionEligibilityAssessment, value, actor=actor or self.actor)
            return self._execute(command_type=R4_6_RECORD_PROMOTION_ELIGIBILITY, record=record, key=f"eligibility:{record.eligibility_id}", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor, payload_key="eligibility")
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("eligibility_id") or ""), str(raw.get("owner_mission_id") or ""), exc)

    def create_promotion_request(self, value: R46KnowledgePromotionRequest | Mapping[str, Any], *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        try:
            record = _provisional(R46KnowledgePromotionRequest, value, actor=actor or self.actor)
            return self._execute(command_type=R4_6_CREATE_PROMOTION_REQUEST, record=record, key=f"request:{record.request_id}", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor, payload_key="request")
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("request_id") or ""), str(raw.get("owner_mission_id") or ""), exc)

    def submit_promotion_request(self, request_id: str, request_digest: str, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        request = self.request(self._mission_for_request(request_id), request_id)
        if request is None:
            return self._error(command_id or f"r4.6:submit:{request_id}", "", R46Error(R46_REFERENCE_INVALID, "request not found"))
        authority_command_id = command_id or f"r4.6:authority:{request.request_id}"
        payload = {"request_id": request_id, "request_digest": request_digest, "submission_attempt": request.submission_attempt + 1, "source_cursor": request.source_cursor, "authority_command_id": authority_command_id, "authority_idempotency_key": request.idempotency_identity}
        try:
            result = self._runtime.execute({"command_id": command_id or f"r4.6:submit:{request_id}", "type": R4_6_SUBMIT_PROMOTION_REQUEST, "mission_id": request.owner_mission_id, "session_id": None, "expected_seq": self._runtime.get_head_seq(request.owner_mission_id) if expected_seq is None else expected_seq, "actor": (actor or self.actor).to_dict(), "payload": payload, "idempotency_key": f"r4.6:submit:{request_id}", "correlation_id": correlation_id or authority_command_id, "schema_version": 1})
            return R46OperationResult(result, self.request(request.owner_mission_id, request_id) if result.ok else None)
        except Exception as exc:
            return self._error(command_id or f"r4.6:submit:{request_id}", request.owner_mission_id, exc)

    def _mission_for_request(self, request_id: str) -> str:
        import sqlite3
        conn = sqlite3.connect(self._runtime.db_path)
        try:
            for row in conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id").fetchall():
                mission_id = str(row[0])
                if self.request(mission_id, request_id) is not None:
                    return mission_id
        finally:
            conn.close()
        raise R46Error(R46_REFERENCE_INVALID, "request not found")

    def record_promotion_receipt(self, value: R46KnowledgePromotionReceipt | Mapping[str, Any], *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        try:
            record = _provisional(R46KnowledgePromotionReceipt, value, actor=actor or self.actor)
            return self._execute(command_type=R4_6_RECORD_PROMOTION_RECEIPT, record=record, key=f"receipt:{record.receipt_id}", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor, payload_key="receipt")
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("receipt_id") or ""), str(raw.get("owner_mission_id") or ""), exc)

    def record_candidate_disposition(self, value: R46CandidateDisposition | Mapping[str, Any], *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        try:
            record = _provisional(R46CandidateDisposition, value, actor=actor or self.actor)
            return self._execute(command_type=R4_6_RECORD_CANDIDATE_DISPOSITION, record=record, key=f"disposition:{record.disposition_id}", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor, payload_key="disposition")
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("disposition_id") or ""), str(raw.get("owner_mission_id") or ""), exc)


def compose_r4_6_runtime(db_path: str | Path, base_extensions: Iterable[Any] = (), *, clock: Any = None, failure_injector: Any = None) -> RuntimeService:
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R46Error(R46_COMMAND_INVALID, "R4.6 extension is already present in explicit composition")
    return RuntimeService(db_path, clock=clock, failure_injector=failure_injector, extensions=extensions + (r4_6_extension(),))


__all__ = ["R46ApplicationService", "R46OperationResult", "compose_r4_6_runtime"]
