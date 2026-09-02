"""R4.6 validated learning candidate and Knowledge promotion boundary."""

from .contracts import (
    EXTENSION_ID, EXTENSION_VERSION, SCHEMA_VERSION, COMMAND_TYPES, EVENT_TYPES,
    R4_6_RECORD_CANDIDATE_REVISION, R4_6_RECORD_PROMOTION_ELIGIBILITY,
    R4_6_CREATE_PROMOTION_REQUEST, R4_6_SUBMIT_PROMOTION_REQUEST,
    R4_6_RECORD_PROMOTION_RECEIPT, R4_6_RECORD_CANDIDATE_DISPOSITION,
    R46_CANDIDATE_REVISION_RECORDED, R46_PROMOTION_ELIGIBILITY_RECORDED,
    R46_PROMOTION_REQUEST_CREATED, R46_PROMOTION_REQUEST_SUBMITTED,
    R46_PROMOTION_RECEIPT_RECORDED, R46_CANDIDATE_DISPOSITION_RECORDED,
    CandidateType, CandidateClaimKind, CandidateValidationOutcome, CandidateLifecycleState,
    PromotionEligibilityStatus, CandidateDispositionKind, PromotionRequestState,
    PromotionReceiptStatus, R46ScopeClass, R46ScopeWideningDecision, R46ProvenanceClass,
    R46FreshnessRequirement, R46AvailabilityRequirement, R46FieldValidationRequirement,
    R46Error, R46ScopeReference, R46CandidateClaim, R46PolicySnapshot,
    R46KnowledgeAuthorityResultRef, R46CandidateRevision, R46ValidatedLearningCandidate,
    R46PromotionEligibilityAssessment, R46KnowledgePromotionRequest,
    R46KnowledgePromotionReceipt, R46CandidateDisposition, R46CandidateCurrentResolution,
    R46State, R46OperationResult, R46ProvenanceReference, candidate_id_for,
    candidate_revision_id_for, eligibility_id_for, promotion_request_id_for,
    receipt_id_for, disposition_id_for, record_digest,
)
from .reducer import R46ReducerContribution
from .handlers import R46CommandContribution
from .extension import R46StateContribution, r4_6_extension
from .projections import R46ProjectionContribution, R46MigrationContribution
from .service import R46ApplicationService, compose_r4_6_runtime
from .knowledge_promotion_bridge import KnowledgePromotionBridge


__all__ = [
    "EXTENSION_ID", "EXTENSION_VERSION", "SCHEMA_VERSION", "COMMAND_TYPES", "EVENT_TYPES",
    "R4_6_RECORD_CANDIDATE_REVISION", "R4_6_RECORD_PROMOTION_ELIGIBILITY", "R4_6_CREATE_PROMOTION_REQUEST",
    "R4_6_SUBMIT_PROMOTION_REQUEST", "R4_6_RECORD_PROMOTION_RECEIPT", "R4_6_RECORD_CANDIDATE_DISPOSITION",
    "R46_CANDIDATE_REVISION_RECORDED", "R46_PROMOTION_ELIGIBILITY_RECORDED", "R46_PROMOTION_REQUEST_CREATED",
    "R46_PROMOTION_REQUEST_SUBMITTED", "R46_PROMOTION_RECEIPT_RECORDED", "R46_CANDIDATE_DISPOSITION_RECORDED",
    "CandidateType", "CandidateClaimKind", "CandidateValidationOutcome", "CandidateLifecycleState",
    "PromotionEligibilityStatus", "CandidateDispositionKind", "PromotionRequestState", "PromotionReceiptStatus",
    "R46ScopeClass", "R46ScopeWideningDecision", "R46ProvenanceClass", "R46FreshnessRequirement",
    "R46AvailabilityRequirement", "R46FieldValidationRequirement", "R46Error", "R46ScopeReference",
    "R46CandidateClaim", "R46PolicySnapshot", "R46KnowledgeAuthorityResultRef", "R46CandidateRevision",
    "R46ValidatedLearningCandidate", "R46PromotionEligibilityAssessment", "R46KnowledgePromotionRequest",
    "R46KnowledgePromotionReceipt", "R46CandidateDisposition", "R46CandidateCurrentResolution", "R46State",
    "R46OperationResult", "R46ApplicationService", "KnowledgePromotionBridge", "R46CommandContribution",
    "R46ReducerContribution", "R46StateContribution", "R46ProjectionContribution", "R46MigrationContribution",
    "r4_6_extension", "compose_r4_6_runtime", "candidate_id_for", "candidate_revision_id_for", "eligibility_id_for",
    "promotion_request_id_for", "receipt_id_for", "disposition_id_for", "record_digest",
]
