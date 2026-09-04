"""Non-durable G5 integration contracts."""

from .contracts import (
    DuplicateCorrelationDecision,
    G4ObservationAdmission,
    G5OperationResult,
    G5WorkerBinding,
    GovernedEvidenceRequest,
)
from .policy import ConfirmationPolicyDecision, classify_confirmation_policy
from .service import G5Service, require_g5_worker_binding

__all__ = [
    "DuplicateCorrelationDecision",
    "G4ObservationAdmission",
    "G5OperationResult",
    "G5WorkerBinding",
    "GovernedEvidenceRequest",
    "ConfirmationPolicyDecision",
    "classify_confirmation_policy",
    "G5Service",
    "require_g5_worker_binding",
]
