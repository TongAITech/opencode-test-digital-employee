from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService, canonical_sha256
from aitest_runtime.r3_e1.contracts import KnowledgeScopeIdentity
from aitest_runtime.r4_1.contracts import Availability, FieldValidationState, Freshness, TypedReference
from aitest_runtime.r4_6.contracts import (
    R46CandidateRevision,
    R46KnowledgePromotionRequest,
    R46PolicySnapshot,
)
from aitest_runtime.r4_6.knowledge_promotion_bridge import KnowledgePromotionBridge
from aitest_runtime.r4_6.service import R46ApplicationService

from .contracts import *
from .errors import (
    R47_AUTHORITY_MISSING,
    R47_BLOCKED,
    R47_COMMAND_INVALID,
    R47_CONFLICT,
    R47_DIGEST_CONFLICT,
    R47_HANDOFF_INVALID,
    R47_RECONCILIATION_REQUIRED,
    R47_REFERENCE_INVALID,
    R47Error,
)
from .service import R47ApplicationService


class R47CanonicalHandoffBridge:
    """Carry R4.7 handoffs through the existing R4.6 promotion boundary."""

    def __init__(self, runtime_service: RuntimeService | None = None, *, actor: ActorRef | None = None) -> None:
        self.runtime_service = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.7-bridge")

    @staticmethod
    def _value(value: Any, cls: type[Any]) -> Any:
        return value if isinstance(value, cls) else cls.from_dict(value)

    def prepare_handoff(
        self,
        decision: ReconciliationDecision | Mapping[str, Any],
        mapping: LegacyCanonicalMapping | Mapping[str, Any],
        observation: LegacySourceObservation | Mapping[str, Any],
        *,
        target_scope_ref: Any = None,
        handoff_kind: HandoffKind | str | None = None,
    ) -> CanonicalHandoffLinkage:
        value = self._value(decision, ReconciliationDecision)
        mapped = self._value(mapping, LegacyCanonicalMapping)
        source = self._value(observation, LegacySourceObservation)
        if value.decision not in {DecisionKind.REQUEST_CANONICAL_HANDOFF, DecisionKind.RECONCILE_EXISTING}:
            raise R47Error(R47_REFERENCE_INVALID, "handoff requires an explicit canonical handoff decision")
        if mapped.target_authority in {CanonicalAuthority.NO_CANONICAL_TARGET, CanonicalAuthority.OUT_OF_SCOPE}:
            raise R47Error(R47_AUTHORITY_MISSING, "handoff target has no canonical authority")
        kind = handoff_kind if handoff_kind is not None else (HandoffKind.KNOWLEDGE_PROMOTION if mapped.target_authority is CanonicalAuthority.R3_E1 else HandoffKind.EXISTING_KNOWLEDGE_RECONCILIATION)
        handoff = CanonicalHandoffLinkage(
            owner_mission_id=value.owner_mission_id,
            owner_stream_key=value.owner_stream_key,
            decision_ref={"object_id": value.decision_id, "source_digest": value.record_digest},
            decision_digest=value.record_digest or "0" * 64,
            target_authority=mapped.target_authority,
            target_scope_ref=target_scope_ref,
            target_object_ref=mapped.target_object_ref,
            target_object_digest=mapped.target_object_digest,
            handoff_kind=kind,
            state=HandoffState.READY,
            source_observation_ref={"object_id": source.observation_id, "source_digest": source.record_digest},
            source_observation_digest=source.record_digest or "0" * 64,
            assessment_ref=value.assessment_ref,
            mapping_ref={"object_id": mapped.mapping_id, "source_digest": mapped.record_digest},
            policy_snapshot_ref=value.policy_snapshot_ref,
            source_cursor=source.source_cursor or source.created_seq,
        )
        return handoff

    def prepare_canonical_authority_request(self, handoff: CanonicalHandoffLinkage | Mapping[str, Any]) -> dict[str, Any]:
        value = self._value(handoff, CanonicalHandoffLinkage)
        if value.state is not HandoffState.READY:
            raise R47Error(R47_REFERENCE_INVALID, "only READY handoffs may be prepared")
        if value.handoff_kind is HandoffKind.REFERENCE_ONLY:
            return {"handoff_id": value.handoff_id, "request_ref": value.request_ref, "actual_runtime_execution": False, "requires_external_authority_caller": False}
        if value.target_authority is CanonicalAuthority.R3_E1 and value.handoff_kind is HandoffKind.KNOWLEDGE_PROMOTION:
            # R4.7 may carry exact R4.6 lineage, but may not call R3.E1 directly.
            return {
                "handoff_id": value.handoff_id,
                "target_authority": value.target_authority.value,
                "request_ref": value.request_ref,
                "authority_command_id": value.authority_command_id,
                "authority_idempotency_key": value.authority_idempotency_key,
                "handoff_kind": value.handoff_kind.value,
                "actual_runtime_execution": False,
                "requires_r4_6_promotion_boundary": True,
                "requires_external_authority_caller": True,
            }
        return {
            "handoff_id": value.handoff_id,
            "target_authority": value.target_authority.value,
            "request_ref": value.request_ref,
            "authority_command_id": value.authority_command_id,
            "authority_idempotency_key": value.authority_idempotency_key,
            "actual_runtime_execution": False,
            "requires_external_authority_caller": True,
        }

    def _runtime(self) -> RuntimeService:
        runtime = getattr(self, "runtime_service", None)
        if not isinstance(runtime, RuntimeService):
            raise R47Error(R47_COMMAND_INVALID, "R4.7 handoff execution requires the existing RuntimeService")
        return runtime

    @staticmethod
    def _operation_error(command_id: str, mission_id: str, exc: Exception) -> R47OperationResult:
        error = exc if isinstance(exc, R47Error) else R47Error(R47_RECONCILIATION_REQUIRED, str(exc))
        return R47OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    @staticmethod
    def _typed_reference(ref_type: str, value: Any, *, correlation_id: str) -> TypedReference:
        return TypedReference(
            ref_type,
            value.revision_id if hasattr(value, "revision_id") else value.eligibility_id,
            value.revision if hasattr(value, "revision") else value.revision,
            value.revision if hasattr(value, "revision") else value.revision,
            value.record_digest if hasattr(value, "record_digest") else value.assessment_digest,
            value.created_seq,
            "r4.6",
            value.created_at,
            Freshness.CURRENT,
            Availability.AVAILABLE,
            FieldValidationState.PASSED,
            correlation_id,
        )

    @staticmethod
    def _handoff_ref(value: Any, field: str) -> dict[str, Any] | None:
        ref = getattr(value, field, None)
        return dict(ref) if isinstance(ref, Mapping) else None

    def _current_handoff(self, value: CanonicalHandoffLinkage) -> tuple[R47ApplicationService, CanonicalHandoffLinkage]:
        service = R47ApplicationService(self._runtime(), actor=self.actor)
        current = service.handoff(value.owner_mission_id, value.handoff_id)
        if current is None:
            raise R47Error(R47_REFERENCE_INVALID, "handoff does not exist")
        if current.record_digest != value.record_digest:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "handoff digest is stale")
        return service, current

    def _validate_knowledge_handoff(
        self,
        value: CanonicalHandoffLinkage,
        candidate: R46CandidateRevision,
        policy: R46PolicySnapshot,
    ) -> tuple[R47ApplicationService, CanonicalHandoffLinkage, LegacyCanonicalMapping]:
        service, current = self._current_handoff(value)
        if value.handoff_kind is not HandoffKind.KNOWLEDGE_PROMOTION:
            raise R47Error(R47_HANDOFF_INVALID, "knowledge submission requires KNOWLEDGE_PROMOTION")
        if value.target_authority is not CanonicalAuthority.R3_E1:
            raise R47Error(R47_AUTHORITY_MISSING, "Knowledge promotion must target R3.E1")
        if current.state is not HandoffState.READY:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "only READY handoffs may start a promotion")
        if candidate.owner_mission_id != value.owner_mission_id:
            raise R47Error(R47_REFERENCE_INVALID, "candidate and handoff Mission differ")
        if candidate.policy_snapshot.policy_digest != policy.policy_digest:
            raise R47Error(R47_DIGEST_CONFLICT, "candidate policy snapshot is stale")
        state = service.state(value.owner_mission_id)
        observation_ref = self._handoff_ref(value, "source_observation_ref")
        assessment_ref = self._handoff_ref(value, "assessment_ref")
        mapping_ref = self._handoff_ref(value, "mapping_ref")
        decision_ref = self._handoff_ref(value, "decision_ref")
        observation = state.observation(str((observation_ref or {}).get("object_id", "")))
        assessment = state.assessment(str((assessment_ref or {}).get("object_id", "")))
        mapping = state.mapping(str((mapping_ref or {}).get("object_id", "")))
        decision = state.decision(str((decision_ref or {}).get("object_id", "")))
        if any(item is None for item in (observation, assessment, mapping, decision)):
            raise R47Error(R47_REFERENCE_INVALID, "handoff lineage is incomplete")
        if observation.record_digest != value.source_observation_digest:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "source observation is no longer current")
        if assessment.record_digest != (assessment_ref or {}).get("source_digest"):
            raise R47Error(R47_RECONCILIATION_REQUIRED, "assessment reference is stale")
        if mapping.record_digest != (mapping_ref or {}).get("source_digest"):
            raise R47Error(R47_RECONCILIATION_REQUIRED, "mapping reference is stale")
        if decision.record_digest != (decision_ref or {}).get("source_digest"):
            raise R47Error(R47_RECONCILIATION_REQUIRED, "decision reference is stale")
        if assessment.outcome in {AssessmentOutcome.BLOCKED, AssessmentOutcome.CONFLICT, AssessmentOutcome.STALE, AssessmentOutcome.REVALIDATION_REQUIRED}:
            raise R47Error(R47_BLOCKED if assessment.outcome is AssessmentOutcome.BLOCKED else R47_RECONCILIATION_REQUIRED, f"handoff basis is {assessment.outcome.value}")
        if decision.decision not in {DecisionKind.REQUEST_CANONICAL_HANDOFF, DecisionKind.RECONCILE_EXISTING}:
            raise R47Error(R47_HANDOFF_INVALID, "decision does not authorize Knowledge handoff")
        if mapping.target_object_ref != value.target_object_ref or mapping.target_object_digest != value.target_object_digest:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "canonical target is no longer current")
        policy_ref = self._handoff_ref(value, "policy_snapshot_ref")
        if policy_ref is not None and policy_ref.get("source_digest") != policy.policy_digest:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "policy snapshot is stale")
        return service, current, mapping

    def _promotion_request(
        self,
        value: CanonicalHandoffLinkage,
        candidate: R46CandidateRevision,
        policy: R46PolicySnapshot,
        mapping: LegacyCanonicalMapping,
        r46: R46ApplicationService,
    ) -> R46KnowledgePromotionRequest:
        evaluated = r46.evaluate_candidate_revision(candidate, policy=policy)
        recorded_candidate = r46.record_candidate_revision(evaluated, actor=self.actor)
        if not recorded_candidate.ok or recorded_candidate.entity is None:
            raise R47Error(R47_RECONCILIATION_REQUIRED, recorded_candidate.error_code or "candidate revision was not recorded")
        stored_candidate = recorded_candidate.entity
        candidate_ref = self._typed_reference("R4_6_CANDIDATE_REVISION", stored_candidate, correlation_id=value.handoff_id)
        eligibility = r46.evaluate_promotion_eligibility(value.owner_mission_id, candidate_ref, policy)
        recorded_eligibility = r46.record_promotion_eligibility(eligibility, actor=self.actor)
        if not recorded_eligibility.ok or recorded_eligibility.entity is None:
            raise R47Error(R47_RECONCILIATION_REQUIRED, recorded_eligibility.error_code or "eligibility was not recorded")
        stored_eligibility = recorded_eligibility.entity
        eligibility_ref = self._typed_reference("R4_6_PROMOTION_ELIGIBILITY", stored_eligibility, correlation_id=value.handoff_id)
        request = R46KnowledgePromotionRequest(
            owner_mission_id=value.owner_mission_id,
            owner_stream_key=f"r4.6:{value.owner_mission_id}",
            request_id=value.request_ref or f"r4.7:request:{value.handoff_id}",
            candidate_revision_ref=candidate_ref,
            candidate_revision_digest=stored_candidate.record_digest,
            eligibility_ref=eligibility_ref,
            eligibility_digest=stored_eligibility.assessment_digest,
            promotion_target_scope=stored_candidate.promotion_target_scope,
            target_fact_id=value.target_object_ref or "",
            target_version_id=mapping.target_object_version or value.target_object_ref or "",
            requested_knowledge_status="SOURCE_VERIFIED",
            expected_source_ref_ids=(),
            expected_knowledge_input_digest=value.target_object_digest or canonical_sha256(stored_candidate.candidate_claim.normalized_claim),
            policy_snapshot=policy,
            human_gate_linkage=stored_eligibility.human_gate_linkage,
            idempotency_identity=value.authority_idempotency_key or f"r4.7:authority-idempotency:{value.handoff_id}",
            authority_command_id=value.authority_command_id or f"r4.7:authority-command:{value.handoff_id}",
            authority_idempotency_key=value.authority_idempotency_key or f"r4.7:authority-idempotency:{value.handoff_id}",
        )
        created = r46.create_promotion_request(request, actor=self.actor)
        if not created.ok or created.entity is None:
            raise R47Error(R47_RECONCILIATION_REQUIRED, created.error_code or "promotion request was not recorded")
        return created.entity

    def _authority_result_receipt(
        self,
        service: R47ApplicationService,
        submitted: CanonicalHandoffLinkage,
        promotion: Any,
    ) -> R47OperationResult:
        r46_receipt = getattr(promotion, "entity", None)
        if r46_receipt is None or getattr(r46_receipt, "authority_result_ref", None) is None:
            code = getattr(promotion, "error_code", None) or R47_RECONCILIATION_REQUIRED
            raise R47Error(R47_RECONCILIATION_REQUIRED, f"R4.6 promotion did not produce a canonical result: {code}")
        authority_ref = r46_receipt.authority_result_ref
        result_status = ReceiptStatus.DUPLICATE if r46_receipt.status.value == "DUPLICATE" else ReceiptStatus.ACCEPTED
        current = service.handoff(submitted.owner_mission_id, submitted.handoff_id)
        if current is None:
            raise R47Error(R47_REFERENCE_INVALID, "handoff disappeared before terminal recording")
        if current.state is HandoffState.SUBMITTED:
            terminal_result = service.record_handoff(
                replace(
                    current,
                    state=HandoffState.COMPLETED,
                    authority_result_ref=authority_ref.version_id,
                    authority_result_digest=authority_ref.result_digest or authority_ref.fingerprint,
                    record_digest=None,
                ),
                actor=self.actor,
            )
            if not terminal_result.ok or terminal_result.entity is None:
                return terminal_result
            current = service.handoff(submitted.owner_mission_id, submitted.handoff_id)
        if current is None or current.state is not HandoffState.COMPLETED:
            raise R47Error(R47_RECONCILIATION_REQUIRED, "canonical result must precede a COMPLETED handoff revision")
        receipt = self.reconcile_receipt(
            current,
            result_status=result_status,
            authority_operation_id=authority_ref.operation_command_id,
            canonical_result_ref=authority_ref.version_id,
            canonical_result_digest=authority_ref.result_digest or authority_ref.fingerprint,
        )
        return service.record_reconciliation_receipt(receipt, actor=self.actor)

    def submit_knowledge_handoff(
        self,
        handoff: CanonicalHandoffLinkage | Mapping[str, Any],
        candidate_revision: R46CandidateRevision | Mapping[str, Any],
        *,
        policy: R46PolicySnapshot | Mapping[str, Any],
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
    ) -> R47OperationResult:
        value = self._value(handoff, CanonicalHandoffLinkage)
        candidate = self._value(candidate_revision, R46CandidateRevision)
        selected_policy = self._value(policy, R46PolicySnapshot)
        command_identifier = command_id or f"r4.7:submit-knowledge:{value.handoff_id}"
        try:
            runtime = self._runtime()
            service = R47ApplicationService(runtime, actor=actor or self.actor)
            current = service.handoff(value.owner_mission_id, value.handoff_id)
            if current is None:
                raise R47Error(R47_REFERENCE_INVALID, "handoff does not exist")
            prior_receipt = next((item for item in service.state(value.owner_mission_id).receipts if isinstance(item.handoff_ref, Mapping) and item.handoff_ref.get("object_id") == value.handoff_id), None)
            if current.state is HandoffState.COMPLETED and prior_receipt is not None:
                return R47OperationResult(CommandResult("DUPLICATE", command_identifier, value.owner_mission_id, duplicate_of=prior_receipt.receipt_id, first_seq=prior_receipt.created_seq, last_seq=prior_receipt.created_seq), current)
            submitted = current
            if current.state is HandoffState.READY:
                service, current, mapping = self._validate_knowledge_handoff(value, candidate, selected_policy)
                submitted_result = service.submit_handoff(value.handoff_id, value.record_digest or "", mission_id=value.owner_mission_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor or self.actor)
                if not submitted_result.ok or submitted_result.entity is None:
                    return submitted_result
                submitted = submitted_result.entity
                r46 = R46ApplicationService(runtime, actor=actor or self.actor)
                request = r46.state(value.owner_mission_id).request(value.request_ref or "")
                if request is None:
                    request = self._promotion_request(value, candidate, selected_policy, mapping, r46)
            elif current.state is HandoffState.SUBMITTED:
                mapping_ref = self._handoff_ref(value, "mapping_ref")
                mapping = service.state(value.owner_mission_id).mapping(str((mapping_ref or {}).get("object_id", "")))
                if mapping is None:
                    raise R47Error(R47_REFERENCE_INVALID, "submitted handoff mapping is missing")
                submitted = current
                r46 = R46ApplicationService(runtime, actor=actor or self.actor)
                request = r46.state(value.owner_mission_id).request(value.request_ref or "")
                if request is None:
                    request = self._promotion_request(value, candidate, selected_policy, mapping, r46)
            elif current.state is HandoffState.COMPLETED:
                r46 = R46ApplicationService(runtime, actor=actor or self.actor)
                request = r46.state(value.owner_mission_id).request(current.request_ref or value.request_ref or "")
                if request is None:
                    raise R47Error(R47_RECONCILIATION_REQUIRED, "completed handoff has no R4.6 promotion request")
            else:
                raise R47Error(R47_RECONCILIATION_REQUIRED, f"handoff is {current.state.value}")
            promotion_bridge = KnowledgePromotionBridge(runtime, r46_service=r46, actor=actor or self.actor)
            r46_receipt = r46.state(value.owner_mission_id).receipt_for_request(request.request_id)
            if r46_receipt is not None:
                promotion = promotion_bridge.reconcile(request.request_id, actor=actor or self.actor)
            else:
                promotion = promotion_bridge.submit(
                    request.request_id,
                    expected_seq=expected_seq,
                    correlation_id=correlation_id or value.correlation_id,
                    actor=actor or self.actor,
                )
            return self._authority_result_receipt(service, submitted, promotion)
        except Exception as exc:
            return self._operation_error(command_identifier, value.owner_mission_id, exc)

    def reconcile_knowledge_existing(
        self,
        handoff: CanonicalHandoffLinkage | Mapping[str, Any],
        *,
        expected_fact_id: str,
        expected_version_id: str,
        expected_scope: KnowledgeScopeIdentity | Mapping[str, Any],
        expected_payload_digest: str,
        expected_fingerprint: str,
        expected_source_ref_ids: tuple[str, ...],
        expected_status: str,
        expected_proof: Mapping[str, Any],
    ) -> ExistingKnowledgeReconciliation:
        value = self._value(handoff, CanonicalHandoffLinkage)
        runtime = self._runtime()
        scope = expected_scope if isinstance(expected_scope, KnowledgeScopeIdentity) else KnowledgeScopeIdentity.from_dict(expected_scope)
        state = runtime.get_composed_state(value.owner_mission_id).extension_state("r3_e1_durable_knowledge_substrate")
        fact = state.fact(expected_fact_id)
        version = state.version(expected_version_id)
        if fact is None or version is None:
            return ExistingKnowledgeReconciliation.UNKNOWN
        exact = (
            fact.fact_id == expected_fact_id
            and fact.current_version_id == expected_version_id
            and version.version_id == expected_version_id
            and version.fact_id == expected_fact_id
            and fact.scope_identity == scope
            and version.scope_identity == scope
            and version.payload_digest == expected_payload_digest
            and version.fingerprint == expected_fingerprint
            and tuple(version.source_ref_ids) == tuple(expected_source_ref_ids)
            and version.status == expected_status
            and dict(version.verification_proof) == dict(expected_proof)
        )
        return ExistingKnowledgeReconciliation.SAME if exact else ExistingKnowledgeReconciliation.CONFLICT

    def record_reference_only(
        self,
        handoff: CanonicalHandoffLinkage | Mapping[str, Any],
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
    ) -> R47OperationResult:
        value = self._value(handoff, CanonicalHandoffLinkage)
        command_identifier = command_id or f"r4.7:reference-only:{value.handoff_id}"
        try:
            if value.handoff_kind is not HandoffKind.REFERENCE_ONLY:
                raise R47Error(R47_HANDOFF_INVALID, "reference-only recording requires REFERENCE_ONLY handoff")
            service, current = self._current_handoff(value)
            submitted = current
            prior = next((item for item in service.state(value.owner_mission_id).receipts if isinstance(item.handoff_ref, Mapping) and item.handoff_ref.get("object_id") == value.handoff_id), None)
            if current.state is HandoffState.COMPLETED and prior is not None:
                return R47OperationResult(CommandResult("DUPLICATE", command_identifier, value.owner_mission_id, duplicate_of=prior.receipt_id, first_seq=prior.created_seq, last_seq=prior.created_seq), current)
            if current.state is HandoffState.READY:
                submitted_result = service.submit_handoff(value.handoff_id, value.record_digest or "", mission_id=value.owner_mission_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor or self.actor)
                if not submitted_result.ok or submitted_result.entity is None:
                    return submitted_result
                submitted = submitted_result.entity
            elif current.state is not HandoffState.SUBMITTED:
                if current.state is not HandoffState.COMPLETED:
                    raise R47Error(R47_RECONCILIATION_REQUIRED, f"reference-only handoff is {current.state.value}")
            if submitted.state is HandoffState.SUBMITTED:
                terminal_result = service.record_handoff(replace(submitted, state=HandoffState.COMPLETED, record_digest=None), actor=actor or self.actor)
                if not terminal_result.ok or terminal_result.entity is None:
                    return terminal_result
                submitted = service.handoff(value.owner_mission_id, value.handoff_id)
            if submitted is None or submitted.state is not HandoffState.COMPLETED:
                raise R47Error(R47_RECONCILIATION_REQUIRED, "reference-only receipt requires a terminal handoff revision")
            receipt = self.reconcile_receipt(submitted, result_status=ReceiptStatus.REFERENCE_ONLY, reason_code="REFERENCE_ONLY")
            return service.record_reconciliation_receipt(receipt, actor=actor or self.actor)
        except Exception as exc:
            return self._operation_error(command_identifier, value.owner_mission_id, exc)

    def reconcile_receipt(
        self,
        handoff: CanonicalHandoffLinkage | Mapping[str, Any],
        *,
        result_status: ReceiptStatus | str,
        authority_operation_id: str | None = None,
        canonical_result_ref: str | None = None,
        canonical_result_digest: str | None = None,
        existing_receipt: ReconciliationReceipt | Mapping[str, Any] | None = None,
        reason_code: str | None = None,
    ) -> ReconciliationReceipt:
        value = self._value(handoff, CanonicalHandoffLinkage)
        prior = self._value(existing_receipt, ReconciliationReceipt) if existing_receipt is not None else None
        status = result_status if isinstance(result_status, ReceiptStatus) else ReceiptStatus(result_status)
        reconciled = False
        duplicate_of = None
        if prior is not None:
            if prior.handoff_ref is None or prior.handoff_ref.get("object_id") != value.handoff_id:
                raise R47Error(R47_REFERENCE_INVALID, "existing receipt belongs to another handoff")
            semantic = (prior.authority_operation_id, prior.canonical_result_ref, prior.canonical_result_digest)
            current = (authority_operation_id, canonical_result_ref, canonical_result_digest)
            if semantic == current:
                status = ReceiptStatus.DUPLICATE
                duplicate_of = prior.receipt_id
            else:
                status = ReceiptStatus.CONFLICT
            reconciled = True
        if canonical_result_digest is not None and len(canonical_result_digest) != 64:
            raise R47Error(R47_DIGEST_CONFLICT, "canonical_result_digest must be SHA-256")
        terminal_digest = value.record_digest or "0" * 64
        exact_receipt_id = receipt_id_for(
            value.handoff_id,
            terminal_digest,
            authority_operation_id,
            canonical_result_ref,
            canonical_result_digest,
        )
        return ReconciliationReceipt(
            owner_mission_id=value.owner_mission_id,
            owner_stream_key=value.owner_stream_key,
            receipt_id=exact_receipt_id,
            source_observation_ref=value.source_observation_ref,
            source_observation_digest=value.source_observation_digest,
            assessment_ref=value.assessment_ref,
            assessment_digest=(value.assessment_ref or {}).get("source_digest", "0" * 64),
            mapping_ref=value.mapping_ref,
            mapping_digest=(value.mapping_ref or {}).get("source_digest", "0" * 64),
            decision_ref=value.decision_ref,
            decision_digest=value.decision_digest,
            handoff_ref={"object_id": value.handoff_id, "source_digest": terminal_digest},
            handoff_digest=terminal_digest,
            handoff_authority=value.target_authority,
            handoff_request_ref=value.request_ref,
            canonical_result_ref=canonical_result_ref,
            canonical_result_digest=canonical_result_digest,
            result_status=status,
            duplicate_of=duplicate_of,
            reconciled_from_existing=reconciled,
            reason_code=reason_code,
            authority_operation_id=authority_operation_id,
            source_cursor=value.source_cursor,
        )


__all__ = ["R47CanonicalHandoffBridge"]
