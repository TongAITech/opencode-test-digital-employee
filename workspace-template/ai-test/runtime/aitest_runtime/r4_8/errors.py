from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError


class R48Error(DurableRuntimeError):
    """Fail-closed error for the R4.8 coordination boundary."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(self.code, self.message, self.details)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


R48ErrorCode = Enum(
    "R48ErrorCode",
    {
        name: name
        for name in (
            "COMPOSITION_INVALID",
            "REQUIRED_EXTENSION_MISSING",
            "EXTENSION_ID_CONFLICT",
            "AUTHORITY_BINDING_MISSING",
            "AUTHORITY_BINDING_UNSUPPORTED",
            "RUNTIME_IDENTITY_MISMATCH",
            "CYCLE_IDENTITY_MISMATCH",
            "CYCLE_NOT_FOUND",
            "INVALID_PHASE_TRANSITION",
            "INVALID_STATUS_TRANSITION",
            "REFERENCE_DIGEST_CONFLICT",
            "OPERATION_ID_CONFLICT",
            "IDEMPOTENCY_CONFLICT",
            "RECEIPT_CONFLICT",
            "UNKNOWN_OPERATION",
            "REENTRY_NOT_ALLOWED",
            "CYCLE_NOT_CLOSABLE",
            "SUFFICIENCY_NOT_OBSERVED",
            "READINESS_AUTHORITY_VIOLATION",
            "KNOWLEDGE_BOUNDARY_VIOLATION",
            "LEGACY_BOUNDARY_VIOLATION",
            "FIELD_VALIDATION_REQUIRED",
        )
    },
)

R48ContractError = R48Error

__all__ = ["R48Error", "R48ErrorCode", "R48ContractError"]
