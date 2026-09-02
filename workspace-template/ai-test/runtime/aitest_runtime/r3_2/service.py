from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService

from .contracts import (
    DERIVE_CHANGE_IMPACT_RECONCILIATION,
    ChangeImpactDerivation,
    ChangeImpactRequest,
    R32State,
    ReconciliationSnapshot,
    R32Error,
)
from .engine import build_derivation
from .providers import CodeIntelligenceProvider, GitCodeIntelligenceProvider


@dataclass(frozen=True)
class R32OperationResult:
    command_result: CommandResult
    derivation: ChangeImpactDerivation | None
    reconciliation: ReconciliationSnapshot | None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code


class R32ApplicationService:
    """R3.2 application boundary over the shared R1 RuntimeService."""

    def __init__(
        self,
        runtime: RuntimeService,
        *,
        provider: CodeIntelligenceProvider | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        if runtime is None:
            raise ValueError("runtime is required")
        runtime.extension_registry.manifest("r3_2_change_impact_reconciliation")
        self.runtime = runtime
        self.provider = provider or GitCodeIntelligenceProvider()
        self.actor = actor or ActorRef("SYSTEM", "r3.2")

    def state(self, mission_id: str) -> R32State:
        state = self.runtime.replay_composed(mission_id).extension_state("r3_2_change_impact_reconciliation")
        if not isinstance(state, R32State):
            raise R32Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.2 extension state")
        return state

    get_state = state

    def derive(self, request: ChangeImpactRequest) -> R32OperationResult:
        if not isinstance(request, ChangeImpactRequest):
            raise TypeError("request must be a ChangeImpactRequest")
        composed = self.runtime.replay_composed(request.mission_id)
        r31_state = composed.extension_state("r3_1_requirement_coverage_traceability")
        state = composed.extension_state("r3_2_change_impact_reconciliation")
        if not isinstance(state, R32State):
            raise R32Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.2 extension state")
        envelope = self.provider.collect(request.repository, request.code_intelligence, policy_version=request.policy_version)
        derivation, reconciliation = build_derivation(request, r31_state, envelope)
        existing = state.derivation(derivation.derivation_fingerprint)
        command_id = f"r3.2:{request.idempotency_key}:{derivation.derivation_fingerprint}:derive"
        if existing is not None and existing.idempotency_key == request.idempotency_key:
            existing_reconciliation = state.reconciliation(f"r3.2:reconciliation:{derivation.derivation_fingerprint}")
            duplicate = CommandResult(
                "DUPLICATE", command_id, request.mission_id,
                first_seq=existing.created_seq, last_seq=existing.created_seq, duplicate_of=existing.derivation_version_id,
            )
            return R32OperationResult(duplicate, existing, existing_reconciliation)
        result = self.runtime.execute({
            "command_id": command_id,
            "type": DERIVE_CHANGE_IMPACT_RECONCILIATION,
            "mission_id": request.mission_id,
            "session_id": None,
            "expected_seq": self.runtime.get_head_seq(request.mission_id),
            "actor": self.actor.to_dict(),
            "payload": {"derivation": derivation.to_dict(), "reconciliation": reconciliation.to_dict()},
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.correlation_id,
            "schema_version": 1,
        })
        if not result.ok:
            return R32OperationResult(result, None, None)
        new_state = self.state(request.mission_id)
        resolved_derivation = new_state.derivation(derivation.derivation_fingerprint)
        resolved_reconciliation = new_state.reconciliation(reconciliation.reconciliation_id)
        return R32OperationResult(result, resolved_derivation, resolved_reconciliation)


def request_from_mapping(value: Mapping[str, Any]) -> ChangeImpactRequest:
    return ChangeImpactRequest.from_payload(value, correlation_id=value.get("correlation_id") or value.get("idempotency_key"))
