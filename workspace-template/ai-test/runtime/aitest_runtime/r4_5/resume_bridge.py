from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import (
    HumanGateLinkage,
    R2ResumeIntent,
    R2ResumeReceipt,
    R2ResumeReceiptStatus,
    R2ResumeTarget,
    ResumeEligibilityAssessment,
    ScopedReference,
    ScopedReferenceAccessMode,
)
from .errors import R45_AUTHORITY_MISSING, R45_DIGEST_CONFLICT, R45_NOT_ELIGIBLE, R45_REFERENCE_INVALID, R45Error


class R45ResumeBridge:
    """A bounded lineage adapter; it owns no executor, service, or truth ledger."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def _eligibility(value: ResumeEligibilityAssessment | Mapping[str, Any]) -> ResumeEligibilityAssessment:
        return value if isinstance(value, ResumeEligibilityAssessment) else ResumeEligibilityAssessment.from_dict(value)

    @staticmethod
    def _gate(value: HumanGateLinkage | Mapping[str, Any]) -> HumanGateLinkage:
        return value if isinstance(value, HumanGateLinkage) else HumanGateLinkage.from_dict(value)

    @staticmethod
    def _target(value: R2ResumeTarget | Mapping[str, Any]) -> R2ResumeTarget:
        return value if isinstance(value, R2ResumeTarget) else R2ResumeTarget.from_dict(value)

    @staticmethod
    def _ref(value: ScopedReference | Mapping[str, Any], name: str) -> ScopedReference:
        ref = value if isinstance(value, ScopedReference) else ScopedReference.from_dict(value)
        if ref.source_cursor is None:
            raise R45Error(R45_REFERENCE_INVALID, f"{name} must be source-backed")
        if ref.source_cursor != ref.source_seq:
            raise R45Error(R45_REFERENCE_INVALID, f"{name} cursor does not match source sequence")
        return ref

    def prepare_r2_resume_handoff(
        self,
        eligibility: ResumeEligibilityAssessment | Mapping[str, Any],
        human_gate_linkage: HumanGateLinkage | Mapping[str, Any],
        r2_target: R2ResumeTarget | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        assessment = self._eligibility(eligibility)
        gate = self._gate(human_gate_linkage)
        target = self._target(r2_target or assessment.r2_target)
        if assessment.outcome.value != "ELIGIBLE":
            raise R45Error(R45_NOT_ELIGIBLE, "R2 handoff requires an ELIGIBLE assessment")
        if target.stream_owner_mission_id != assessment.stream_owner_mission_id:
            raise R45Error(R45_AUTHORITY_MISSING, "R2 target Mission differs from the eligibility Mission")
        gate_ref = self._ref(gate.gate_ref, "gate_ref")
        actor_ref = self._ref(gate.actor_ref, "actor_ref")
        policy_ref = self._ref(gate.policy_ref, "policy_ref")
        if gate.gate_id != gate_ref.object_id or str(gate.gate_revision) != str(gate_ref.object_revision):
            raise R45Error(R45_AUTHORITY_MISSING, "HumanGate identity is not exact")
        if gate.decision_outcome != "ALLOW":
            raise R45Error(R45_AUTHORITY_MISSING, "HumanGate decision is not ALLOW")
        if gate.decision_digest != gate_ref.object_digest:
            raise R45Error(R45_DIGEST_CONFLICT, "HumanGate decision digest differs from its exact gate reference")
        if gate.continuation_state in {"PENDING", "CONTINUATION_PENDING", "ROUTE_REVISION", "BLOCKED"}:
            raise R45Error(R45_NOT_ELIGIBLE, "continuation is pending, revised, or blocked")
        if gate.continuation_reference is None:
            raise R45Error(R45_AUTHORITY_MISSING, "continuation reference is missing")
        continuation_ref = self._ref(gate.continuation_reference, "continuation_reference")
        if not assessment.human_gate_refs or not any(item.to_dict() == gate_ref.to_dict() for item in assessment.human_gate_refs):
            raise R45Error(R45_AUTHORITY_MISSING, "eligibility does not carry the exact HumanGate lineage")
        expected_target_fields = (
            target.rotation_operation_id, target.predecessor_session_id, target.successor_session_id,
            target.predecessor_attempt_id, target.execution_attempt_id, target.task_id, target.plan_id,
            target.plan_revision_id,
        )
        if any(not item for item in expected_target_fields):
            raise R45Error(R45_AUTHORITY_MISSING, "R2.5 target lineage is incomplete")
        resume_identity = {
            "rotation_operation_id": target.rotation_operation_id,
            "predecessor_session_id": target.predecessor_session_id,
            "successor_session_id": target.successor_session_id,
            "execution_attempt_id": target.execution_attempt_id,
            "task_id": target.task_id,
            "plan_id": target.plan_id,
            "plan_revision_id": target.plan_revision_id,
        }
        authorization_ref = gate_ref
        intent_provenance = {
            "authority": "PRESERVED_BY_EXACT_DURABLE_PREAUTHORIZATION_LINEAGE",
            "human_gate": gate.to_dict(),
            "actor_ref": actor_ref.to_dict(),
            "policy_ref": policy_ref.to_dict(),
            "r2_target": target.to_dict(),
            "eligibility_ref": {
                "object_id": assessment.eligibility_id,
                "object_digest": assessment.record_digest,
                "source_cursor": assessment.as_of_cursor,
            },
            "runtime_execution": False,
        }
        return {
            "stream_owner_mission_id": assessment.stream_owner_mission_id,
            "release_scope": assessment.release_scope.to_dict(),
            "eligibility_ref": {
                "ref_kind": "RESUME_ELIGIBILITY_ASSESSMENT",
                "stream_owner_mission_id": assessment.stream_owner_mission_id,
                "object_id": assessment.eligibility_id,
                "object_revision": assessment.revision,
                "object_digest": assessment.record_digest,
                "source_seq": assessment.created_seq,
                "source_cursor": assessment.created_seq,
                "access_mode": ScopedReferenceAccessMode.LOCAL.value,
            },
            "r2_target": target.to_dict(),
            "r2_authorization_ref": authorization_ref.to_dict(),
            "continuation_ref": continuation_ref.to_dict(),
            "resume_identity": resume_identity,
            "idempotency_identity": canonical_sha256(resume_identity),
            "intent_provenance": intent_provenance,
            "actual_runtime_execution": False,
            "requires_external_r2_caller": True,
        }

    def reconcile_r2_resume_receipt(
        self,
        intent: R2ResumeIntent | Mapping[str, Any],
        r2_result_ref: ScopedReference | Mapping[str, Any],
        *,
        receipt_id: str,
        receipt_status: R2ResumeReceiptStatus | str = R2ResumeReceiptStatus.APPLIED,
        r2_result_digest: str | None = None,
        receipt_provenance: Mapping[str, Any] | None = None,
        existing_receipt: R2ResumeReceipt | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = intent if isinstance(intent, R2ResumeIntent) else R2ResumeIntent.from_dict(intent)
        result_ref = self._ref(r2_result_ref, "r2_result_ref")
        digest = r2_result_digest or result_ref.object_digest
        if digest != result_ref.object_digest:
            raise R45Error(R45_DIGEST_CONFLICT, "R2 result digest is not the exact result reference digest")
        prior = None
        if existing_receipt is not None:
            prior = existing_receipt if isinstance(existing_receipt, R2ResumeReceipt) else R2ResumeReceipt.from_dict(existing_receipt)
        status = receipt_status if isinstance(receipt_status, R2ResumeReceiptStatus) else R2ResumeReceiptStatus(receipt_status)
        reconciled = False
        if prior is not None:
            if prior.resume_intent_ref.object_id != value.resume_intent_id:
                raise R45Error(R45_REFERENCE_INVALID, "existing receipt belongs to another intent")
            if prior.r2_result_digest == digest:
                status = R2ResumeReceiptStatus.DUPLICATE
                reconciled = True
            else:
                status = R2ResumeReceiptStatus.RECONCILIATION_REQUIRED
                reconciled = True
        receipt = R2ResumeReceipt(
            resume_receipt_id="pending",
            stream_owner_mission_id=value.stream_owner_mission_id,
            release_scope=value.release_scope,
            revision=value.revision,
            resume_intent_ref=ScopedReference(
                ref_kind="R2_RESUME_INTENT",
                stream_owner_mission_id=value.stream_owner_mission_id,
                object_id=value.resume_intent_id,
                object_revision=value.revision,
                object_digest=value.record_digest,
                source_seq=value.created_seq,
                source_cursor=value.created_seq,
                access_mode=ScopedReferenceAccessMode.LOCAL,
            ),
            receipt_id=receipt_id,
            receipt_status=status,
            r2_result_ref=result_ref,
            r2_result_digest=digest,
            r2_authorization_ref=value.r2_authorization_ref,
            continuation_ref=value.continuation_ref,
            receipt_cursor=result_ref.source_cursor or result_ref.source_seq,
            receipt_provenance=dict(receipt_provenance or {"exact_r2_result_ref": result_ref.to_dict(), "raw_result_stored": False}),
            reconciled_from_existing_result=reconciled,
            as_of_seq=value.as_of_seq,
            correlation_id=value.correlation_id,
            causation_id=value.causation_id,
            created_by=value.created_by,
            created_seq=0,
            created_at="bridge",
            record_digest=None,
        )
        return receipt.to_dict()


__all__ = ["R45ResumeBridge"]
