"""R3.E2 additive SUT Authentication Context runtime extension."""

from .contracts import (
    ALLOWED_TRANSITIONS,
    ARM_RUNTIME_VERIFICATION,
    AUTHORIZE_RESUME,
    AUTH_REQUIRED,
    CLOSE_AUTH_CONTEXT,
    CONTEXT_CLOSED,
    CONTEXT_EXPIRED,
    CONTEXT_REVOKED,
    CONTEXT_STATUSES,
    EXPIRE_AUTH_CONTEXT,
    EXTENSION_ID,
    GATE_KINDS,
    HUMAN_GATE_LINKED,
    LINK_HUMAN_GATE,
    REQUEST_AUTH_CONTEXT,
    RESUME_AUTHORIZED,
    RUNTIME_VERIFIED,
    R3E2Error,
    R3E2State,
    REVOKE_AUTH_CONTEXT,
    RuntimeVerificationReceipt,
    SUTAuthContext,
    SUTAuthContextIdentity,
    SUTAuthContextScope,
    VERIFY_RUNTIME_AUTH,
    VALIDATION_STATUSES,
    VERIFICATION_PENDING,
    BrowserContextRef,
    ContinuationProof,
    AuthSourceRef,
    HumanGateReference,
    validate_transition,
)
from .extension import r3_e2_extension
from .ports import (
    BrowserAuthContextPort,
    ContextReuseReceipt,
    ContinuationPort,
    HumanGatePort,
    require_real_runtime_verification,
)
from .service import R3E2ApplicationService, R3E2OperationResult
from .vertical_slice import R3E2VerticalSliceResult, execute_vertical_slice

__all__ = [
    "ALLOWED_TRANSITIONS", "ARM_RUNTIME_VERIFICATION", "AUTHORIZE_RESUME", "AUTH_REQUIRED",
    "CLOSE_AUTH_CONTEXT", "CONTEXT_CLOSED", "CONTEXT_EXPIRED", "CONTEXT_REVOKED", "CONTEXT_STATUSES",
    "EXPIRE_AUTH_CONTEXT", "EXTENSION_ID", "GATE_KINDS", "HUMAN_GATE_LINKED", "LINK_HUMAN_GATE",
    "REQUEST_AUTH_CONTEXT", "RESUME_AUTHORIZED", "RUNTIME_VERIFIED", "R3E2Error", "R3E2State",
    "REVOKE_AUTH_CONTEXT", "RuntimeVerificationReceipt", "SUTAuthContext", "SUTAuthContextIdentity",
    "SUTAuthContextScope", "VERIFY_RUNTIME_AUTH", "VALIDATION_STATUSES", "VERIFICATION_PENDING",
    "BrowserContextRef", "ContinuationProof", "AuthSourceRef", "HumanGateReference", "validate_transition",
    "r3_e2_extension", "BrowserAuthContextPort", "ContextReuseReceipt", "ContinuationPort", "HumanGatePort",
    "require_real_runtime_verification", "R3E2ApplicationService", "R3E2OperationResult",
    "R3E2VerticalSliceResult", "execute_vertical_slice",
]
