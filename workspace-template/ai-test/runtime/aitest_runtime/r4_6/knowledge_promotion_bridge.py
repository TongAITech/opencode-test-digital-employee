from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, RuntimeService, canonical_sha256
from aitest_runtime.r3_e1.contracts import KnowledgeFact, KnowledgeScopeIdentity, KnowledgeSourceRef, KnowledgeVersion
from aitest_runtime.r3_e1.service import R3E1ApplicationService, R3E1OperationResult

from .contracts import *
from .errors import *
from .service import R46ApplicationService


class KnowledgePromotionBridge:
    """The only R4.6 boundary allowed to invoke the R3.E1 Knowledge authority."""

    def __init__(self, runtime_service: RuntimeService, r46_service: R46ApplicationService | None = None, r3e1_service: R3E1ApplicationService | None = None, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        runtime_service.extension_registry.manifest("r3_e1_durable_knowledge_substrate")
        if r46_service is not None and r46_service.runtime_service is not runtime_service:
            raise R46Error(R46_SCOPE_MISMATCH, "R4.6 service must use the same RuntimeService")
        if r3e1_service is not None and r3e1_service.runtime_service is not runtime_service:
            raise R46Error(R46_SCOPE_MISMATCH, "R3.E1 service must use the same RuntimeService")
        self.runtime_service = runtime_service
        self.r46_service = r46_service or R46ApplicationService(runtime_service, actor=actor)
        self.r3e1_service = r3e1_service or R3E1ApplicationService(runtime_service)
        self.actor = actor or self.r46_service.actor

    def _request(self, request_id: str) -> tuple[str, R46KnowledgePromotionRequest]:
        for mission_id in self._mission_ids():
            request = self.r46_service.request(mission_id, request_id)
            if request is not None:
                return mission_id, request
        raise R46Error(R46_REFERENCE_INVALID, "promotion request was not found")

    def _mission_ids(self) -> tuple[str, ...]:
        # The runtime API intentionally exposes no global candidate store. The bridge discovers
        # only Mission ids represented by the existing core event stream.
        missions: set[str] = set()
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(self.runtime_service.db_path)
            rows = conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id").fetchall()
            missions.update(str(row[0]) for row in rows)
        finally:
            if conn is not None:
                conn.close()
        return tuple(sorted(missions))

    def _candidate_inputs(self, request: R46KnowledgePromotionRequest) -> tuple[KnowledgeFact, KnowledgeVersion, tuple[KnowledgeSourceRef, ...], R46CandidateRevision]:
        state = self.r46_service.state(request.owner_mission_id)
        candidate = state.candidate_revision(request.candidate_revision_ref.object_id if request.candidate_revision_ref else "")
        if candidate is None or candidate.record_digest != request.candidate_revision_digest:
            raise R46Error(R46_REFERENCE_INVALID, "request candidate lineage is stale")
        resolution = state.current_candidate(candidate.candidate_id)
        current_ref = resolution.current.current_revision_ref if resolution.current is not None else None
        if resolution.status != "CURRENT" or current_ref is None or current_ref.object_id != candidate.revision_id:
            raise R46Error(R46_STALE, "candidate is no longer the current promotable revision")
        if candidate.promotion_target_scope.scope_class is not R46ScopeClass.CANONICAL_KNOWLEDGE_SCOPE or candidate.promotion_target_scope.knowledge_scope_identity is None:
            raise R46Error(R46_SCOPE_MISMATCH, "canonical promotion requires exact KnowledgeScopeIdentity")
        scope = candidate.promotion_target_scope.knowledge_scope_identity
        claim = candidate.candidate_claim
        payload = dict(claim.normalized_claim)
        fact = KnowledgeFact(request.target_fact_id, scope, str(payload.get("subject", claim.claim_kind.value)), str(payload.get("predicate", "validated_learning")), payload.get("value", payload), request.target_version_id, tuple(request.expected_source_ref_ids), {"r4_6_candidate_id": candidate.candidate_id})
        source_refs: list[KnowledgeSourceRef] = []
        for index, ref in enumerate(candidate.authoritative_provenance_refs + candidate.evidence_refs):
            source_refs.append(KnowledgeSourceRef(f"r4.6:{candidate.candidate_id}:{index}", "RUNTIME" if "RUNTIME" in ref.ref_type.upper() else "BUSINESS", ref.object_id, str(ref.object_version), ref.source_digest, scope, ref.observed_at, ref.observed_at, "r4.6-provenance", metadata={"r4_6_ref_type": ref.ref_type, "source_cursor": ref.source_cursor}))
        source_ids = tuple(item.source_ref_id for item in source_refs)
        if request.expected_source_ref_ids and set(request.expected_source_ref_ids) != set(source_ids):
            # Preserve the exact request identity; an input change is a reconciliation conflict.
            raise R46Error(R46_DIGEST_CONFLICT, "request source ref identity differs from current candidate")
        proof = candidate.validation_facts.get("verification_proof") or {}
        version = KnowledgeVersion(request.target_version_id, request.target_fact_id, 1, payload, scope, request.requested_knowledge_status, "VALIDATED", source_ids, verification_proof=proof)
        return fact, version, tuple(source_refs), candidate

    @staticmethod
    def _authority_ref(operation: R3E1OperationResult, mission_id: str, version: KnowledgeVersion) -> R46KnowledgeAuthorityResultRef:
        result = operation.command_result
        return R46KnowledgeAuthorityResultRef("r3_e1_durable_knowledge_substrate", result.command_id, "DUPLICATE" if result.outcome == "DUPLICATE" else result.outcome, result.duplicate_of, mission_id, version.fact_id, version.version_id, version.version_number, version.scope_identity, version.status, version.payload_digest or canonical_sha256(version.payload), version.fingerprint or canonical_sha256(version.to_dict()), result.first_seq or 0, result.last_seq or 0, result.state_hash or canonical_sha256(result.to_dict()), result.last_seq or 0)

    def _receipt(self, request: R46KnowledgePromotionRequest, status: PromotionReceiptStatus, authority_ref: R46KnowledgeAuthorityResultRef | None = None, *, reconciled: bool = False, error_code: str | None = None) -> R46OperationResult:
        receipt = R46KnowledgePromotionReceipt(owner_mission_id=request.owner_mission_id, owner_stream_key=request.owner_stream_key, revision=request.revision, record_digest=None, as_of_seq=self.runtime_service.get_head_seq(request.owner_mission_id), source_cursor=request.source_cursor, correlation_id=request.correlation_id, causation_id=request.authority_command_id or request.request_id, created_by=self.actor, created_seq=0, created_at="seq:0", receipt_id=receipt_id_for(request.request_id, request.authority_command_id or request.authority_idempotency_key, authority_ref.result_digest if authority_ref else error_code or status.value), request_ref=TypedReference("R4_6_KNOWLEDGE_PROMOTION_REQUEST", request.request_id, request.revision, request.revision, request.record_digest or request.request_digest, request.source_cursor, "r4.6", "seq:0", Freshness.CURRENT, Availability.AVAILABLE, FieldValidationState.PASSED, request.correlation_id), request_digest=request.request_digest or request.record_digest, candidate_revision_ref=request.candidate_revision_ref, candidate_revision_digest=request.candidate_revision_digest, status=status, authority_result_ref=authority_ref, canonical_knowledge_ref=authority_ref if status in {PromotionReceiptStatus.ACCEPTED, PromotionReceiptStatus.DUPLICATE} else None, reason_refs=(), error_code=error_code, reconciled_from_existing=reconciled, receipt_digest=None)
        return self.r46_service.record_promotion_receipt(receipt)

    def submit(self, request_id: str, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R46OperationResult:
        mission_id, request = self._request(request_id)
        eligibility = self.r46_service.eligibility(mission_id, request.eligibility_ref.object_id if request.eligibility_ref else "")
        if eligibility is None or eligibility.status is not PromotionEligibilityStatus.ELIGIBLE:
            return self._r46_error(request, R46_NOT_ELIGIBLE, "promotion request is no longer ELIGIBLE")
        submitted = self.r46_service.submit_promotion_request(request_id, request.request_digest or request.record_digest, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        if not submitted.ok:
            return submitted
        request = self.r46_service.request(mission_id, request_id)
        if request is None:
            return self._r46_error(request, R46_REFERENCE_INVALID, "submitted request disappeared")
        try:
            fact, version, source_refs, _ = self._candidate_inputs(request)
            operation = self.r3e1_service.register_version(mission_id=mission_id, fact=fact, version=version, source_refs=source_refs, actor=actor or self.actor, origin_lineage={"r4_6_request_id": request.request_id}, idempotency_key=request.authority_idempotency_key, correlation_id=request.correlation_id, command_id=request.authority_command_id)
            authority_ref = self._authority_ref(operation, mission_id, version) if operation.ok else None
            status = PromotionReceiptStatus.DUPLICATE if operation.command_result.outcome == "DUPLICATE" else PromotionReceiptStatus.ACCEPTED if operation.ok else PromotionReceiptStatus.REJECTED
            return self._receipt(request, status, authority_ref, error_code=operation.command_result.error_code)
        except R46Error as exc:
            return self._receipt(request, PromotionReceiptStatus.RECONCILIATION_REQUIRED, error_code=exc.code)
        except Exception as exc:
            return self._receipt(request, PromotionReceiptStatus.RECONCILIATION_REQUIRED, error_code=str(exc))

    def _r46_error(self, request: R46KnowledgePromotionRequest | None, code: str, message: str) -> R46OperationResult:
        return R46OperationResult(__import__("aitest_runtime.durable_core", fromlist=["CommandResult"]).CommandResult("REJECTED", request.request_id if request else "", request.owner_mission_id if request else "", error=R46Error(code, message)))

    def reconcile(self, request_id: str, *, actor: ActorRef | None = None) -> R46OperationResult:
        mission_id, request = self._request(request_id)
        existing_receipt = self.r46_service.state(mission_id).receipt_for_request(request_id)
        if existing_receipt is not None:
            return R46OperationResult(
                __import__("aitest_runtime.durable_core", fromlist=["CommandResult"]).CommandResult(
                    "DUPLICATE", existing_receipt.receipt_id, mission_id,
                    duplicate_of=existing_receipt.receipt_id,
                    first_seq=existing_receipt.created_seq,
                    last_seq=existing_receipt.created_seq,
                ),
                existing_receipt,
            )
        state = self.runtime_service.replay_composed(mission_id).extension_state("r3_e1_durable_knowledge_substrate")
        try:
            _, expected_version, _, _ = self._candidate_inputs(request)
            existing = state.version(expected_version.version_id)
            if existing is not None and existing.fingerprint == expected_version.fingerprint and existing.payload_digest == expected_version.payload_digest:
                ref = R46KnowledgeAuthorityResultRef("r3_e1_durable_knowledge_substrate", request.authority_command_id or "reconciled", "DUPLICATE", request.authority_command_id, mission_id, existing.fact_id, existing.version_id, existing.version_number, existing.scope_identity, existing.status, existing.payload_digest or "", existing.fingerprint or "", 0, 0, canonical_sha256(existing.to_dict()), 0)
                return self._receipt(request, PromotionReceiptStatus.DUPLICATE, ref, reconciled=True)
            fact, version, source_refs, _ = self._candidate_inputs(request)
            operation = self.r3e1_service.register_version(mission_id=mission_id, fact=fact, version=version, source_refs=source_refs, actor=actor or self.actor, origin_lineage={"r4_6_reconciliation": request.request_id}, idempotency_key=request.authority_idempotency_key, correlation_id=request.correlation_id, command_id=request.authority_command_id)
            if operation.ok:
                return self._receipt(request, PromotionReceiptStatus.DUPLICATE if operation.command_result.outcome == "DUPLICATE" else PromotionReceiptStatus.ACCEPTED, self._authority_ref(operation, mission_id, version), reconciled=True)
            return self._receipt(request, PromotionReceiptStatus.RECONCILIATION_REQUIRED, error_code=operation.command_result.error_code)
        except Exception as exc:
            return self._receipt(request, PromotionReceiptStatus.RECONCILIATION_REQUIRED, error_code=getattr(exc, "code", str(exc)))


__all__ = ["KnowledgePromotionBridge"]
