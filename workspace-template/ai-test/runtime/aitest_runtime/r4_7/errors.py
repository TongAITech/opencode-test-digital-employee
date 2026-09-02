from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError


class R47Error(DurableRuntimeError):
    """Fail-closed error for the additive R4.7 reconciliation boundary."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(self.code, self.message, self.details)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


R47_SCHEMA_INVALID = "R4_7_SCHEMA_INVALID"
R47_DIGEST_CONFLICT = "R4_7_DIGEST_CONFLICT"
R47_IDENTITY_CONFLICT = "R4_7_IDENTITY_CONFLICT"
R47_REFERENCE_INVALID = "R4_7_REFERENCE_INVALID"
R47_SEQUENCE_MISMATCH = "R4_7_SEQUENCE_MISMATCH"
R47_COMMAND_INVALID = "R4_7_COMMAND_INVALID"
R47_AUTHORITY_MISSING = "R4_7_AUTHORITY_MISSING"
R47_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
R47_UNKNOWN_EVENT = "R4_7_UNKNOWN_EVENT"
R47_CONFLICT = "R4_7_CONFLICT"
R47_BLOCKED = "R4_7_BLOCKED"
R47_STALE = "R4_7_STALE"
R47_OUT_OF_SCOPE = "R4_7_OUT_OF_SCOPE"
R47_HANDOFF_INVALID = "R4_7_HANDOFF_INVALID"
R47_RECEIPT_CONFLICT = "R4_7_RECEIPT_CONFLICT"


class R47ErrorCode(str, Enum):
    SCHEMA_INVALID = R47_SCHEMA_INVALID
    DIGEST_CONFLICT = R47_DIGEST_CONFLICT
    IDENTITY_CONFLICT = R47_IDENTITY_CONFLICT
    REFERENCE_INVALID = R47_REFERENCE_INVALID
    SEQUENCE_MISMATCH = R47_SEQUENCE_MISMATCH
    COMMAND_INVALID = R47_COMMAND_INVALID
    AUTHORITY_MISSING = R47_AUTHORITY_MISSING
    RECONCILIATION_REQUIRED = R47_RECONCILIATION_REQUIRED
    CONFLICT = R47_CONFLICT
    BLOCKED = R47_BLOCKED
    STALE = R47_STALE
    OUT_OF_SCOPE = R47_OUT_OF_SCOPE


R47ContractError = R47Error


__all__ = [
    "R47Error",
    "R47_SCHEMA_INVALID",
    "R47_DIGEST_CONFLICT",
    "R47_IDENTITY_CONFLICT",
    "R47_REFERENCE_INVALID",
    "R47_SEQUENCE_MISMATCH",
    "R47_COMMAND_INVALID",
    "R47_AUTHORITY_MISSING",
    "R47_RECONCILIATION_REQUIRED",
    "R47_UNKNOWN_EVENT",
    "R47_CONFLICT",
    "R47_BLOCKED",
    "R47_STALE",
    "R47_OUT_OF_SCOPE",
    "R47_HANDOFF_INVALID",
    "R47_RECEIPT_CONFLICT",
    "R47ErrorCode",
    "R47ContractError",
]
