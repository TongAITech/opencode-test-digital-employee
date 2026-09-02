from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError as DurableRuntimeError


class R45Error(DurableRuntimeError):
    """Fail-closed error raised by the R4.5 additive boundary."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(self.code, self.message, self.details)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


R45_SCHEMA_INVALID = "R4_5_SCHEMA_INVALID"
R45_DIGEST_CONFLICT = "R4_5_DIGEST_CONFLICT"
R45_IDENTITY_CONFLICT = "R4_5_IDENTITY_CONFLICT"
R45_SCOPE_MISMATCH = "R4_5_SCOPE_MISMATCH"
R45_REFERENCE_INVALID = "R4_5_REFERENCE_INVALID"
R45_SEQUENCE_MISMATCH = "R4_5_SEQUENCE_MISMATCH"
R45_COMMAND_INVALID = "R4_5_COMMAND_INVALID"
R45_NOT_ELIGIBLE = "R4_5_NOT_ELIGIBLE"
R45_AUTHORITY_MISSING = "R4_5_AUTHORITY_MISSING"
R45_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
R45_UNKNOWN_EVENT = "R4_5_UNKNOWN_EVENT"


__all__ = [
    "R45Error",
    "R45_SCHEMA_INVALID",
    "R45_DIGEST_CONFLICT",
    "R45_IDENTITY_CONFLICT",
    "R45_SCOPE_MISMATCH",
    "R45_REFERENCE_INVALID",
    "R45_SEQUENCE_MISMATCH",
    "R45_COMMAND_INVALID",
    "R45_NOT_ELIGIBLE",
    "R45_AUTHORITY_MISSING",
    "R45_RECONCILIATION_REQUIRED",
    "R45_UNKNOWN_EVENT",
]
