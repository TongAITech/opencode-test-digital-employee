from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError as DurableRuntimeError


class R46Error(DurableRuntimeError):
    """Fail-closed error for the additive R4.6 boundary."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(self.code, self.message, self.details)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


R46_SCHEMA_INVALID = "R4_6_SCHEMA_INVALID"
R46_DIGEST_CONFLICT = "R4_6_DIGEST_CONFLICT"
R46_IDENTITY_CONFLICT = "R4_6_IDENTITY_CONFLICT"
R46_SCOPE_MISMATCH = "R4_6_SCOPE_MISMATCH"
R46_REFERENCE_INVALID = "R4_6_REFERENCE_INVALID"
R46_SEQUENCE_MISMATCH = "R4_6_SEQUENCE_MISMATCH"
R46_COMMAND_INVALID = "R4_6_COMMAND_INVALID"
R46_NOT_ELIGIBLE = "R4_6_NOT_ELIGIBLE"
R46_AUTHORITY_MISSING = "R4_6_AUTHORITY_MISSING"
R46_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
R46_UNKNOWN_EVENT = "R4_6_UNKNOWN_EVENT"
R46_CONFLICT = "R4_6_CONFLICT"
R46_BLOCKED = "R4_6_BLOCKED"
R46_INCOMPLETE = "R4_6_INCOMPLETE"
R46_STALE = "R4_6_STALE"
R46_HUMAN_GATE_INVALID = "R4_6_HUMAN_GATE_INVALID"


__all__ = [
    "R46Error",
    "R46_SCHEMA_INVALID",
    "R46_DIGEST_CONFLICT",
    "R46_IDENTITY_CONFLICT",
    "R46_SCOPE_MISMATCH",
    "R46_REFERENCE_INVALID",
    "R46_SEQUENCE_MISMATCH",
    "R46_COMMAND_INVALID",
    "R46_NOT_ELIGIBLE",
    "R46_AUTHORITY_MISSING",
    "R46_RECONCILIATION_REQUIRED",
    "R46_UNKNOWN_EVENT",
    "R46_CONFLICT",
    "R46_BLOCKED",
    "R46_INCOMPLETE",
    "R46_STALE",
    "R46_HUMAN_GATE_INVALID",
]
