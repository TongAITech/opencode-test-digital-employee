from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService, canonical_sha256

from .authority_ports import R48AuthorityPort
from .composition import validate_r4_8_composition
from .contracts import (
    R48AuthorityBinding,
    R48AuthorityKind,
    R48AuthorityOperation,
    R48AuthorityOperationInput,
    R48AuthorityProcessingResult,
    R48AuthorityReceipt,
    R48AuthorityReceiptInput,
    R48AuthorityResult,
    R48AuthorityOutcome,
    R48CapabilityObservationInput,
    R48CompositionSpec,
    R48CoordinationStatus,
    R48CycleCloseInput,
    R48CycleContext,
    R48CyclePolicySnapshot,
    R48CycleRegistrationInput,
    R48CycleState,
    R48Phase,
    R48ProcessingOutcome,
    R48OperationStatus,
    R48ReconciliationInput,
    R48ReentryInput,
    R48StageDisposition,
    R48State,
    R48WaitingInput,
)
from .errors import R48Error
from .handlers import R48CommandContribution, _input_digest, _step_id
from .reducer import _state_digest


def _actor(value: ActorRef | Mapping[str, Any] | None) -> ActorRef:
    if value is None:
        return ActorRef("R4_8", "closed-loop-service")
    if isinstance(value, ActorRef):
        return value
    return ActorRef(str(value["type"]), str(value["id"]))


def _input(value: Any, cls: type[Any]) -> Any:
    if isinstance(value, cls):
        return value
    if isinstance(value, Mapping):
        return cls.from_dict(value)
    raise TypeError(f"expected {cls.__name__}")


def _result_state_hash(state: R48State) -> str:
    return canonical_sha256(state.to_dict())


class R48ApplicationService:
    def __init__(
        self,
        runtime: RuntimeService,
        composition_spec: R48CompositionSpec,
        authority_bindings: Mapping[R48AuthorityKind, object] | None = None,
        clock: Any | None = None,
    ) -> None:
        if runtime is None:
            raise ValueError("runtime is required")
        result = validate_r4_8_composition(composition_spec)
        if not result.ok:
            raise R48Error("COMPOSITION_INVALID", "R4.8 service requires a valid composition", {"errors": [item.name for item in result.errors]})
        if runtime.extension_registry.manifest("r4_8_closed_loop_continuous_quality_runtime_integration").extension_id != "r4_8_closed_loop_continuous_quality_runtime_integration":
            raise R48Error("RUNTIME_IDENTITY_MISMATCH", "R4.8 extension identity is not registered")
        self.runtime = runtime
        self.composition_spec = composition_spec
        self.clock = clock
        if authority_bindings is None:
            values: dict[R48AuthorityKind, object] = {}
            for binding in composition_spec.authority_bindings:
                try:
                    values[binding.authority] = binding.bind(runtime)
                except TypeError:
                    values[binding.authority] = binding.bind(None)
            self.authority_bindings = values
        else:
            self.authority_bindings = dict(authority_bindings)

    def _metadata(
        self,
        mission_id: str,
        *,
        expected_seq: int | None,
        command_id: str | None,
        idempotency_key: str | None,
        correlation_id: str | None,
        causation_id: str | None,
        actor: ActorRef | Mapping[str, Any] | None,
        suffix: str,
    ) -> tuple[str, int, str, str, str, ActorRef]:
        current = self.runtime.get_head_seq(mission_id) if expected_seq is None else expected_seq
        command = command_id or f"r4.8:{suffix}:{current + 1}"
        idem = idempotency_key or command
        correlation = correlation_id or command
        causation = causation_id or command
        return command, current, idem, correlation, causation, _actor(actor)

    def _execute(
        self,
        command_type: str,
        mission_id: str,
        payload: Mapping[str, Any],
        *,
        expected_seq: int | None,
        command_id: str | None,
        idempotency_key: str | None,
        correlation_id: str | None,
        causation_id: str | None,
        actor: ActorRef | Mapping[str, Any] | None,
        suffix: str,
    ) -> CommandResult:
        command, seq, idem, correlation, causation, actor_ref = self._metadata(
            mission_id,
            expected_seq=expected_seq,
            command_id=command_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor=actor,
            suffix=suffix,
        )
        body = dict(payload)
        body["causation_id"] = causation
        return self.runtime.execute(
            {
                "command_id": command,
                "type": command_type,
                "mission_id": mission_id,
                "expected_seq": seq,
                "actor": actor_ref.to_dict(),
                "payload": body,
                "idempotency_key": idem,
                "correlation_id": correlation,
            }
        )

    def _policy(self) -> R48CyclePolicySnapshot:
        field_required = bool(self.composition_spec.field_validation_binding_required)
        learning = R48StageDisposition.REQUIRED if self.composition_spec.learning_promotion_required else R48StageDisposition.NOT_REQUIRED
        legacy = R48StageDisposition.REQUIRED if self.composition_spec.legacy_reconciliation_required else R48StageDisposition.NOT_REQUIRED
        raw = {
            "schema_version": 1,
            "field_validation_required": field_required,
            "learning_promotion_disposition": learning.value,
            "legacy_reconciliation_disposition": legacy.value,
        }
        return R48CyclePolicySnapshot(1, field_required, learning, legacy, canonical_sha256(raw))

    @staticmethod
    def _cycle_id(value: R48CycleRegistrationInput) -> str:
        return "r4.8/cycle/" + canonical_sha256({
            "owner_mission_id": value.owner_mission_id,
            "quality_version_ref": value.quality_version_ref.to_dict(),
            "campaign_ref": value.campaign_ref.to_dict(),
            "trigger_ref": value.trigger_ref.to_dict(),
        })

    def register_cycle(
        self,
        value: R48CycleRegistrationInput,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        actor: ActorRef | Mapping[str, Any] | None = None,
    ) -> CommandResult:
        value = _input(value, R48CycleRegistrationInput)
        cycle_id = self._cycle_id(value)
        current_state = self.state(value.owner_mission_id)
        existing = current_state.cycle(cycle_id)
        if existing is not None:
            return CommandResult("DUPLICATE", command_id or f"r4.8:register:{cycle_id}", value.owner_mission_id, duplicate_of=existing.context.cycle_id, state_hash=_result_state_hash(current_state))
        policy = self._policy()
        context = R48CycleContext(
            schema_version=value.schema_version,
            cycle_id=cycle_id,
            owner_mission_id=value.owner_mission_id,
            quality_version_ref=value.quality_version_ref,
            campaign_ref=value.campaign_ref,
            trigger_ref=value.trigger_ref,
            impact_ref=value.impact_ref,
            source_cursor=value.source_cursor,
            policy_snapshot=policy,
            correlation_id=correlation_id or command_id or cycle_id,
            causation_id=causation_id or command_id or cycle_id,
            record_digest="",
            created_seq=0,
            created_at="",
        )
        step_id = _step_id(cycle_id, R48Phase.REGISTERED)
        step = {
            "schema_version": value.schema_version,
            "step_id": step_id,
            "cycle_id": cycle_id,
            "step_revision": 1,
            "phase": R48Phase.REGISTERED.value,
            "status": R48CoordinationStatus.ACTIVE.value,
            "authority": R48AuthorityKind.R4_1.value,
            "operation_kind": "CAPABILITY_OBSERVATION",
            "input_refs": [value.quality_version_ref.to_dict(), value.campaign_ref.to_dict(), value.trigger_ref.to_dict()],
            "input_digest": _input_digest({"quality_version_ref": value.quality_version_ref.to_dict(), "campaign_ref": value.campaign_ref.to_dict(), "trigger_ref": value.trigger_ref.to_dict()}),
            "source_cursor": value.source_cursor,
            "stage_disposition": R48StageDisposition.REQUIRED.value,
            "policy_digest": policy.policy_digest,
            "last_operation_id": None,
            "last_receipt_id": None,
            "reason_code": None,
        }
        payload = {"registration": value.to_dict(), "cycle_id": cycle_id, "context": context.to_dict(), "step": step}
        return self._execute("R4_8_REGISTER_CYCLE.v1", value.owner_mission_id, payload, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="register")

    def record_capability_observation(
        self, value: R48CapabilityObservationInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None,
    ) -> CommandResult:
        value = _input(value, R48CapabilityObservationInput)
        return self._execute("R4_8_RECORD_CAPABILITY_OBSERVATION.v1", value.owner_mission_id, {"observation": value.to_dict()}, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="observe")

    def request_authority_action(
        self, value: R48AuthorityOperationInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None,
    ) -> CommandResult:
        value = _input(value, R48AuthorityOperationInput)
        operation_id = "r4.8/operation/" + canonical_sha256({"cycle_id": value.cycle_id, "step_id": value.step_id, "step_revision": value.step_revision, "authority": value.authority.value, "operation_kind": value.operation_kind.value, "request_ref": value.request_ref.to_dict() if value.request_ref else None, "input_refs": [item.to_dict() for item in value.input_refs], "input_digest": _input_digest(value.input_refs)})
        current_cycle = self.state(value.owner_mission_id).cycle(value.cycle_id)
        if current_cycle is not None:
            existing = current_cycle.operation(operation_id)
            if existing is not None:
                return CommandResult("DUPLICATE", command_id or operation_id, value.owner_mission_id, duplicate_of=existing.operation_id, state_hash=_result_state_hash(self.state(value.owner_mission_id)))
        input_digest = _input_digest({"input_refs": [item.to_dict() for item in value.input_refs], "request_ref": value.request_ref.to_dict() if value.request_ref else None})
        materialized = {
            "schema_version": value.schema_version, "operation_id": operation_id, "owner_mission_id": value.owner_mission_id, "cycle_id": value.cycle_id, "step_id": value.step_id, "step_revision": value.step_revision, "authority": value.authority.value, "operation_kind": value.operation_kind.value, "request_ref": value.request_ref.to_dict() if value.request_ref else None, "input_refs": [item.to_dict() for item in value.input_refs], "input_digest": input_digest, "policy_digest": value.policy_digest, "source_cursor": value.source_cursor, "authority_idempotency_key": "r4.8/authority-idempotency/" + operation_id, "correlation_id": correlation_id or command_id or operation_id, "causation_id": causation_id or command_id or operation_id, "request_record_digest": "", "request_created_seq": 0, "request_created_at": "", "current_status": "REQUESTED", "current_receipt_id": None, "authority_operation_id": None, "result_ref": None, "result_digest": None, "authority_revision": None, "authority_outcome": None, "proof_digest": None, "owner_cursor": None, "observed_source_cursor": None, "current_state_digest": "",
        }
        return self._execute("R4_8_REQUEST_AUTHORITY_ACTION.v1", value.owner_mission_id, {"operation": value.to_dict(), "operation_id": operation_id, "input_digest": input_digest, "materialized_operation": materialized}, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="request")

    def _find_operation(self, mission_id: str, operation_id: str) -> tuple[R48CycleState, R48AuthorityOperation]:
        state = self.state(mission_id)
        for cycle in state.cycles:
            for operation in cycle.operations:
                if operation.operation_id == operation_id:
                    return cycle, operation
        raise R48Error("UNKNOWN_OPERATION", f"operation not found: {operation_id}")

    @staticmethod
    def _semantic_identity(operation: R48AuthorityOperation, result: R48AuthorityResult) -> str:
        return canonical_sha256({"operation_id": operation.operation_id, "authority": result.authority.value, "authority_operation_id": result.authority_operation_id, "result_ref": result.result_ref.to_dict() if result.result_ref else None, "result_digest": result.result_digest, "authority_revision": result.authority_revision, "outcome": result.outcome.value, "proof_digest": result.proof_digest})

    def _receipt_payload(self, value: R48AuthorityReceiptInput, cycle: R48CycleState, operation: R48AuthorityOperation, command_id: str | None, correlation_id: str | None, causation_id: str | None) -> dict[str, Any]:
        result = value.authority_result
        semantic = self._semantic_identity(operation, result)
        return {"schema_version": value.schema_version, "receipt_id": "r4.8/receipt/" + semantic, "owner_mission_id": value.owner_mission_id, "operation_id": operation.operation_id, "cycle_id": cycle.context.cycle_id, "step_id": operation.step_id, "step_revision": operation.step_revision, "authority": result.authority.value, "authority_operation_id": result.authority_operation_id, "result_ref": result.result_ref.to_dict() if result.result_ref else None, "result_digest": result.result_digest, "authority_revision": result.authority_revision, "owner_cursor": result.owner_cursor, "outcome": result.outcome.value, "proof_refs": [item.to_dict() for item in result.proof_refs], "proof_digest": result.proof_digest, "semantic_identity": semantic, "observed_source_cursor": value.observed_source_cursor, "correlation_id": correlation_id or command_id or operation.operation_id, "causation_id": causation_id or command_id or operation.operation_id, "record_digest": ""}

    def _processing_without_event(self, mission_id: str, command_id: str | None, outcome: R48ProcessingOutcome, receipt: R48AuthorityReceipt | None = None, duplicate_of: str | None = None) -> R48AuthorityProcessingResult:
        return R48AuthorityProcessingResult(CommandResult("DUPLICATE" if outcome is R48ProcessingOutcome.DUPLICATE else "REJECTED", command_id or "r4.8:receipt:preflight", mission_id, duplicate_of=duplicate_of, state_hash=_result_state_hash(self.state(mission_id))), outcome, receipt, duplicate_of)

    def _record_receipt(self, value: R48AuthorityReceiptInput, *, reconciliation: bool, reconciliation_input: R48ReconciliationInput | None = None, expected_seq: int | None, command_id: str | None, idempotency_key: str | None, correlation_id: str | None, causation_id: str | None, actor: ActorRef | Mapping[str, Any] | None) -> R48AuthorityProcessingResult:
        value = _input(value, R48AuthorityReceiptInput)
        cycle, operation = self._find_operation(value.owner_mission_id, value.operation_id)
        incoming = value.authority_result
        if incoming.authority is not operation.authority:
            raise R48Error("RUNTIME_IDENTITY_MISMATCH", "receipt authority differs from operation authority")
        existing = next((item for item in cycle.receipts if item.operation_id == operation.operation_id and item.semantic_identity == self._semantic_identity(operation, incoming)), None)
        if existing is not None:
            return self._processing_without_event(value.owner_mission_id, command_id, R48ProcessingOutcome.DUPLICATE, existing, existing.receipt_id)
        if operation.authority_revision and incoming.authority_revision:
            try:
                older = int(incoming.authority_revision) < int(operation.authority_revision)
            except (TypeError, ValueError):
                older = incoming.authority_revision < operation.authority_revision
            if older:
                return self._processing_without_event(value.owner_mission_id, command_id, R48ProcessingOutcome.RECONCILIATION_REQUIRED)
        if operation.current_status in {R48OperationStatus.APPLIED, R48OperationStatus.REJECTED, R48OperationStatus.BLOCKED, R48OperationStatus.STALE, R48OperationStatus.CONFLICT}:
            return self._processing_without_event(value.owner_mission_id, command_id, R48ProcessingOutcome.CONFLICT)
        if operation.authority_operation_id and operation.authority_operation_id != incoming.authority_operation_id:
            return self._processing_without_event(value.owner_mission_id, command_id, R48ProcessingOutcome.RECONCILIATION_REQUIRED)
        materialized = self._receipt_payload(value, cycle, operation, command_id, correlation_id, causation_id)
        payload_key = "reconciliation" if reconciliation else "receipt"
        payload_value = reconciliation_input.to_dict() if reconciliation and reconciliation_input is not None else value.to_dict()
        payload = {payload_key: payload_value, "materialized_receipt": materialized}
        result = self._execute("R4_8_RECORD_RECONCILIATION.v1" if reconciliation else "R4_8_RECORD_AUTHORITY_RECEIPT.v1", value.owner_mission_id, payload, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="reconcile" if reconciliation else "receipt")
        if result.outcome != "APPLIED":
            return R48AuthorityProcessingResult(result, R48ProcessingOutcome.CONFLICT, None, None)
        after_cycle, _ = self._find_operation(value.owner_mission_id, value.operation_id)
        receipt = next((item for item in after_cycle.receipts if item.receipt_id == materialized["receipt_id"]), None)
        return R48AuthorityProcessingResult(result, R48ProcessingOutcome.APPLIED, receipt, None)

    def record_authority_receipt(self, value: R48AuthorityReceiptInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None) -> R48AuthorityProcessingResult:
        return self._record_receipt(value, reconciliation=False, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor)

    def mark_waiting(self, value: R48WaitingInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None) -> CommandResult:
        value = _input(value, R48WaitingInput)
        return self._execute("R4_8_MARK_WAITING.v1", value.owner_mission_id, {"waiting": value.to_dict()}, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="waiting")

    def reenter_cycle(self, value: R48ReentryInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None) -> CommandResult:
        value = _input(value, R48ReentryInput)
        reentry_id = "r4.8/reentry/" + canonical_sha256({"cycle_id": value.cycle_id, "prior_step_id": value.prior_step_id, "prior_step_revision": value.prior_step_revision, "target_phase": value.target_phase.value, "kind": value.kind.value, "new_input_refs": [item.to_dict() for item in value.new_input_refs], "operation_id": value.operation_id, "reason_code": value.reason_code})
        return self._execute("R4_8_REENTER_CYCLE.v1", value.owner_mission_id, {"reentry": value.to_dict(), "reentry_id": reentry_id}, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="reentry")

    def record_reconciliation(self, value: R48ReconciliationInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None) -> R48AuthorityProcessingResult:
        return self._record_receipt(R48AuthorityReceiptInput(value.schema_version, value.owner_mission_id, value.operation_id, value.authority_result, value.observed_source_cursor), reconciliation=True, reconciliation_input=value, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor)

    def close_cycle(self, value: R48CycleCloseInput, *, expected_seq: int | None = None, command_id: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, actor: ActorRef | Mapping[str, Any] | None = None) -> CommandResult:
        value = _input(value, R48CycleCloseInput)
        cycle = self.state(value.owner_mission_id).cycle(value.cycle_id)
        if cycle is None:
            raise R48Error("CYCLE_NOT_FOUND", value.cycle_id)
        if cycle.phase not in {R48Phase.READINESS_OBSERVED, R48Phase.PROMOTION_OBSERVED, R48Phase.LEGACY_RECONCILIATION_OBSERVED}:
            raise R48Error("CYCLE_NOT_CLOSABLE", "readiness must be observed before closure")
        applied = {item.authority for item in cycle.operations if item.current_status is R48OperationStatus.APPLIED}
        required = {R48AuthorityKind.R3_7, R48AuthorityKind.R4_5}
        if self.composition_spec.field_validation_binding_required:
            required.add(R48AuthorityKind.FIELD_VALIDATION)
        if not required.issubset(applied):
            raise R48Error("CYCLE_NOT_CLOSABLE", "required authoritative receipts are absent")
        return self._execute("R4_8_CLOSE_CYCLE.v1", value.owner_mission_id, {"close": value.to_dict()}, expected_seq=expected_seq, command_id=command_id, idempotency_key=idempotency_key, correlation_id=correlation_id, causation_id=causation_id, actor=actor, suffix="close")

    def _port(self, operation: R48AuthorityOperation) -> R48AuthorityPort:
        port = self.authority_bindings.get(operation.authority)
        if port is None:
            raise R48Error("AUTHORITY_BINDING_MISSING", operation.authority.value)
        return port  # type: ignore[return-value]

    def dispatch_authority_operation(self, operation_id: str) -> R48AuthorityResult:
        state = self.state_for_operation(operation_id)
        port = self._port(state[1])
        return port.submit(state[1], idempotency_key=state[1].authority_idempotency_key, correlation_id=state[1].correlation_id)

    def reconcile_authority_operation(self, operation_id: str) -> R48AuthorityResult:
        cycle, operation = self.state_for_operation(operation_id)
        port = self._port(operation)
        return port.reconcile(operation, idempotency_key=operation.authority_idempotency_key, correlation_id=operation.correlation_id)

    def state_for_operation(self, operation_id: str) -> tuple[R48CycleState, R48AuthorityOperation]:
        conn = sqlite3.connect(str(self.runtime.db_path))
        try:
            mission_ids = [row[0] for row in conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id").fetchall()]
        finally:
            conn.close()
        for mission_id in mission_ids:
            for cycle in self.state(mission_id).cycles:
                for operation in cycle.operations:
                    if operation.operation_id == operation_id:
                        return cycle, operation
        raise R48Error("UNKNOWN_OPERATION", operation_id)

    def state(self, mission_id: str) -> R48State:
        return self.runtime.replay_composed(mission_id).extension_state("r4_8_closed_loop_continuous_quality_runtime_integration")

    def cycle(self, mission_id: str, cycle_id: str) -> R48CycleState | None:
        return self.state(mission_id).cycle(cycle_id)

    def verify_projection(self, mission_id: str) -> dict[str, object]:
        return self.runtime.verify_projection(mission_id)

    def rebuild_projections(self, mission_id: str | None = None) -> dict[str, object]:
        return self.runtime.rebuild_projections(mission_id)


__all__ = ["R48ApplicationService"]
