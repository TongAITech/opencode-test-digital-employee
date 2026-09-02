from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeError, RuntimeService

from .contracts import DERIVE_REQUIREMENT_COVERAGE, DerivationRequest, DerivationVersion, R31State
from .extension import r3_1_extension


@dataclass(frozen=True)
class R31OperationResult:
    command_result: CommandResult
    derivation: DerivationVersion | None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code


class R31ApplicationService:
    """Application boundary for R3.1; it delegates durability to the existing R1 RuntimeService."""

    def __init__(self, runtime: RuntimeService, *, actor: ActorRef | None = None) -> None:
        self.runtime = runtime
        self.actor = actor or ActorRef("SYSTEM", "r3.1")

    def derive(self, request: DerivationRequest) -> R31OperationResult:
        if not isinstance(request, DerivationRequest):
            raise TypeError("request must be a DerivationRequest")
        fingerprint = request.identity().fingerprint
        composed = self.runtime.replay_composed(request.mission_id)
        state = composed.extension_state("r3_1_requirement_coverage_traceability")
        if isinstance(state, R31State):
            existing = state.derivation(fingerprint)
            if existing is not None and existing.idempotency_key == request.idempotency_key:
                command_id = f"r3.1:{request.idempotency_key}:{fingerprint}:derive"
                duplicate = CommandResult(
                    "DUPLICATE", command_id, request.mission_id,
                    first_seq=existing.created_seq, last_seq=existing.created_seq,
                    duplicate_of=existing.derivation_version_id,
                )
                return R31OperationResult(duplicate, existing)
        command_id = f"r3.1:{request.idempotency_key}:{fingerprint}:derive"
        result = self.runtime.execute({
            "command_id": command_id,
            "type": DERIVE_REQUIREMENT_COVERAGE,
            "mission_id": request.mission_id,
            "session_id": None,
            "expected_seq": self.runtime.get_head_seq(request.mission_id),
            "actor": self.actor.to_dict(),
            "payload": request.to_payload(),
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.correlation_id,
            "schema_version": 1,
        })
        if not result.ok:
            return R31OperationResult(result, None)
        composed = self.runtime.replay_composed(request.mission_id)
        state = composed.extension_state("r3_1_requirement_coverage_traceability")
        if not isinstance(state, R31State):
            raise RuntimeError("R3_1_STATE_INVALID", "R3.1 extension state is not registered")
        return R31OperationResult(result, state.derivation(fingerprint))


def request_from_mapping(value: Mapping[str, Any]) -> DerivationRequest:
    return DerivationRequest(
        mission_id=value["mission_id"], scope_identity=value["scope_identity"],
        source_bundle_digest=value["source_bundle_digest"], source_bundle=value["source_bundle"],
        derivation_policy_version=value["derivation_policy_version"], idempotency_key=value["idempotency_key"],
        requested_by=value["requested_by"], correlation_id=value["correlation_id"],
    )
