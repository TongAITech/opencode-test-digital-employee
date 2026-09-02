from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import CommandResult, RuntimeError, RuntimeService

from .contracts import R15Error, redact
from .validate import ValidatedStartup


@dataclass(frozen=True)
class RecoveryRequest:
    recovery_id: str
    operation: str
    mission_id: str
    authorization_id: str
    artifact_digest: str
    configuration_digest: str
    command: Mapping[str, Any] | None = None
    max_operations: int = 1

    def __post_init__(self) -> None:
        for name in ("recovery_id", "operation", "mission_id", "authorization_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise R15Error("RECOVERY_REQUEST_INVALID", f"{name} is required")
        if self.max_operations != 1:
            raise R15Error("RECOVERY_BOUND_EXCEEDED", "R1.5 recovery is bounded to one operation per request")


@dataclass(frozen=True)
class RecoveryResult:
    outcome: str
    recovery_id: str
    mission_id: str
    operation: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome in {"APPLIED", "DUPLICATE", "NOT_NEEDED"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "recovery_id": self.recovery_id,
            "mission_id": self.mission_id,
            "operation": self.operation,
            "evidence": redact(dict(self.evidence)),
            "canonical": False,
        }


def recover(runtime: RuntimeService, startup: ValidatedStartup, request: RecoveryRequest) -> RecoveryResult:
    startup.require_valid()
    if request.artifact_digest != startup.artifact.manifest_digest or request.configuration_digest != startup.configuration.digest:
        raise R15Error("RECOVERY_PROVENANCE_MISMATCH", "recovery request is not anchored to the validated launch context")
    if request.operation == "REBUILD_PROJECTIONS":
        try:
            verification = runtime.verify_projection(request.mission_id)
        except RuntimeError as exc:
            if exc.code not in {"PROJECTION_DRIFT", "COMPOSED_PROJECTION_DRIFT"}:
                raise
            verification = {"ok": False, "code": exc.code}
        if verification.get("ok"):
            return RecoveryResult("NOT_NEEDED", request.recovery_id, request.mission_id, request.operation, {"as_of_seq": runtime.get_head_seq(request.mission_id)})
        result = runtime.rebuild_projections(request.mission_id)
        after = runtime.verify_projection(request.mission_id)
        if not after.get("ok"):
            raise R15Error("RECOVERY_FAILED", "projection rebuild did not restore a verified projection")
        return RecoveryResult("APPLIED", request.recovery_id, request.mission_id, request.operation, {"result": result, "as_of_seq": runtime.get_head_seq(request.mission_id)})
    if request.operation == "RETRY_COMMAND":
        if not isinstance(request.command, Mapping):
            raise R15Error("RECOVERY_REQUEST_INVALID", "RETRY_COMMAND requires a command envelope")
        command = dict(request.command)
        if not command.get("idempotency_key"):
            raise R15Error("RECOVERY_IDEMPOTENCY_REQUIRED", "recovery command retries require an idempotency key")
        result: CommandResult = runtime.execute(command)
        if not result.ok:
            raise R15Error("RECOVERY_COMMAND_REJECTED", "recovery command was rejected", {"result": result.to_dict()})
        return RecoveryResult(result.outcome, request.recovery_id, request.mission_id, request.operation, {"command_result": result.to_dict()})
    raise R15Error("RECOVERY_OPERATION_UNSUPPORTED", "unsupported recovery operation")
