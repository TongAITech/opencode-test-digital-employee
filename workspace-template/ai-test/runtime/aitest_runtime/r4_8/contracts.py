from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, ExtensionManifest
from aitest_runtime.r4_1.contracts import TypedReference

from .errors import R48ContractError, R48Error, R48ErrorCode


EXTENSION_ID = "r4_8_closed_loop_continuous_quality_runtime_integration"
EXTENSION_VERSION = "1.0.0"
SCHEMA_VERSION = 1

R4_8_REGISTER_CYCLE = "R4_8_REGISTER_CYCLE.v1"
R4_8_RECORD_CAPABILITY_OBSERVATION = "R4_8_RECORD_CAPABILITY_OBSERVATION.v1"
R4_8_REQUEST_AUTHORITY_ACTION = "R4_8_REQUEST_AUTHORITY_ACTION.v1"
R4_8_RECORD_AUTHORITY_RECEIPT = "R4_8_RECORD_AUTHORITY_RECEIPT.v1"
R4_8_MARK_WAITING = "R4_8_MARK_WAITING.v1"
R4_8_REENTER_CYCLE = "R4_8_REENTER_CYCLE.v1"
R4_8_RECORD_RECONCILIATION = "R4_8_RECORD_RECONCILIATION.v1"
R4_8_CLOSE_CYCLE = "R4_8_CLOSE_CYCLE.v1"

R48_CYCLE_REGISTERED = "r4.8.cycle.registered.v1"
R48_CAPABILITY_OBSERVED = "r4.8.capability.observed.v1"
R48_AUTHORITY_ACTION_REQUESTED = "r4.8.authority_action.requested.v1"
R48_AUTHORITY_ACTION_RECEIVED = "r4.8.authority_action.received.v1"
R48_CYCLE_WAITING = "r4.8.cycle.waiting.v1"
R48_CYCLE_REENTERED = "r4.8.cycle.reentered.v1"
R48_OPERATION_RECONCILED = "r4.8.operation.reconciled.v1"
R48_CYCLE_CLOSED = "r4.8.cycle.closed.v1"

COMMAND_TYPES = frozenset(
    {
        R4_8_REGISTER_CYCLE,
        R4_8_RECORD_CAPABILITY_OBSERVATION,
        R4_8_REQUEST_AUTHORITY_ACTION,
        R4_8_RECORD_AUTHORITY_RECEIPT,
        R4_8_MARK_WAITING,
        R4_8_REENTER_CYCLE,
        R4_8_RECORD_RECONCILIATION,
        R4_8_CLOSE_CYCLE,
    }
)
EVENT_TYPES = frozenset(
    {
        R48_CYCLE_REGISTERED,
        R48_CAPABILITY_OBSERVED,
        R48_AUTHORITY_ACTION_REQUESTED,
        R48_AUTHORITY_ACTION_RECEIVED,
        R48_CYCLE_WAITING,
        R48_CYCLE_REENTERED,
        R48_OPERATION_RECONCILED,
        R48_CYCLE_CLOSED,
    }
)


class R48AuthorityKind(str, Enum):
    R2 = "R2"
    R2_6 = "R2_6"
    R3 = "R3"
    R3_7 = "R3_7"
    R4_1 = "R4_1"
    R4_2 = "R4_2"
    R4_3 = "R4_3"
    R4_4 = "R4_4"
    R4_5 = "R4_5"
    R4_6 = "R4_6"
    R4_7 = "R4_7"
    FIELD_VALIDATION = "FIELD_VALIDATION"


class R48BindingSource(str, Enum):
    DIRECT_EXISTING_PUBLIC_SERVICE = "DIRECT_EXISTING_PUBLIC_SERVICE"
    EXISTING_BRIDGE = "EXISTING_BRIDGE"
    READ_ONLY_COMPOSED_STATE = "READ_ONLY_COMPOSED_STATE"
    CALLER_PROVIDED_PORT = "CALLER_PROVIDED_PORT"
    UNSUPPORTED = "UNSUPPORTED"


class R48OperationKind(str, Enum):
    CAPABILITY_OBSERVATION = "CAPABILITY_OBSERVATION"
    WORK_REQUEST = "WORK_REQUEST"
    HUMAN_GATE = "HUMAN_GATE"
    SUFFICIENCY_OBSERVATION = "SUFFICIENCY_OBSERVATION"
    READINESS_OBSERVATION = "READINESS_OBSERVATION"
    LEARNING_PROMOTION = "LEARNING_PROMOTION"
    LEGACY_RECONCILIATION = "LEGACY_RECONCILIATION"
    REENTRY_RECONCILIATION = "REENTRY_RECONCILIATION"


class R48ReentryKind(str, Enum):
    RESUME = "RESUME"
    RETRY = "RETRY"
    RECONCILE = "RECONCILE"
    REVALIDATE = "REVALIDATE"


class R48OperationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class R48AuthorityOutcome(str, Enum):
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class R48ProcessingOutcome(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class R48StageDisposition(str, Enum):
    REQUIRED = "REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"


class R48Phase(str, Enum):
    REGISTERED = "REGISTERED"
    TRIGGER_OBSERVED = "TRIGGER_OBSERVED"
    IMPACT_OBSERVED = "IMPACT_OBSERVED"
    WORK_ACTIVE = "WORK_ACTIVE"
    DEFECT_FIX_OBSERVED = "DEFECT_FIX_OBSERVED"
    FIX_VALIDATION_OBSERVED = "FIX_VALIDATION_OBSERVED"
    REGRESSION_OBSERVED = "REGRESSION_OBSERVED"
    SUFFICIENCY_OBSERVED = "SUFFICIENCY_OBSERVED"
    READINESS_OBSERVED = "READINESS_OBSERVED"
    LEARNING_ELIGIBLE = "LEARNING_ELIGIBLE"
    PROMOTION_OBSERVED = "PROMOTION_OBSERVED"
    LEGACY_RECONCILIATION_OBSERVED = "LEGACY_RECONCILIATION_OBSERVED"
    CLOSED = "CLOSED"


class R48CoordinationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPLETE = "COMPLETE"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, TypedReference):
        return value.to_dict()
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _ref(value: Any) -> TypedReference | None:
    if value is None or isinstance(value, TypedReference):
        return value
    return TypedReference.from_dict(value)


def _refs(value: Any) -> tuple[TypedReference, ...]:
    return tuple(_ref(item) for item in (value or ()))


@dataclass(frozen=True)
class R48CycleRegistrationInput:
    schema_version: int
    owner_mission_id: str
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    trigger_ref: TypedReference
    impact_ref: TypedReference | None
    source_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CycleRegistrationInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), TypedReference.from_dict(value["quality_version_ref"]), TypedReference.from_dict(value["campaign_ref"]), TypedReference.from_dict(value["trigger_ref"]), _ref(value.get("impact_ref")), int(value["source_cursor"]))


@dataclass(frozen=True)
class R48CapabilityObservationInput:
    schema_version: int
    owner_mission_id: str
    cycle_id: str
    target_phase: R48Phase
    authority: R48AuthorityKind
    operation_kind: R48OperationKind
    input_refs: tuple[TypedReference, ...]
    source_cursor: int
    stage_disposition: R48StageDisposition
    policy_digest: str
    reason_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CapabilityObservationInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["cycle_id"]), R48Phase(value["target_phase"]), R48AuthorityKind(value["authority"]), R48OperationKind(value["operation_kind"]), _refs(value.get("input_refs")), int(value["source_cursor"]), R48StageDisposition(value["stage_disposition"]), str(value["policy_digest"]), value.get("reason_code"))


@dataclass(frozen=True)
class R48AuthorityOperationInput:
    schema_version: int
    owner_mission_id: str
    cycle_id: str
    step_id: str
    step_revision: int
    authority: R48AuthorityKind
    operation_kind: R48OperationKind
    request_ref: TypedReference | None
    input_refs: tuple[TypedReference, ...]
    policy_digest: str
    source_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48AuthorityOperationInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["cycle_id"]), str(value["step_id"]), int(value["step_revision"]), R48AuthorityKind(value["authority"]), R48OperationKind(value["operation_kind"]), _ref(value.get("request_ref")), _refs(value.get("input_refs")), str(value["policy_digest"]), int(value["source_cursor"]))


@dataclass(frozen=True)
class R48AuthorityReceiptInput:
    schema_version: int
    owner_mission_id: str
    operation_id: str
    authority_result: "R48AuthorityResult"
    observed_source_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48AuthorityReceiptInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["operation_id"]), R48AuthorityResult.from_dict(value["authority_result"]), int(value["observed_source_cursor"]))


@dataclass(frozen=True)
class R48ReentryInput:
    schema_version: int
    owner_mission_id: str
    cycle_id: str
    target_phase: R48Phase
    kind: R48ReentryKind
    prior_step_id: str
    prior_step_revision: int
    new_input_refs: tuple[TypedReference, ...]
    observed_owner_cursor: int | None
    reason_code: str
    reconciliation_evidence: TypedReference | None
    operation_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48ReentryInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["cycle_id"]), R48Phase(value["target_phase"]), R48ReentryKind(value["kind"]), str(value["prior_step_id"]), int(value["prior_step_revision"]), _refs(value.get("new_input_refs")), value.get("observed_owner_cursor"), str(value["reason_code"]), _ref(value.get("reconciliation_evidence")), value.get("operation_id"))


@dataclass(frozen=True)
class R48WaitingInput:
    schema_version: int
    owner_mission_id: str
    cycle_id: str
    step_id: str
    reason_code: str
    source_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48WaitingInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["cycle_id"]), str(value["step_id"]), str(value["reason_code"]), int(value["source_cursor"]))


@dataclass(frozen=True)
class R48CycleCloseInput:
    schema_version: int
    owner_mission_id: str
    cycle_id: str
    closure_ref: TypedReference
    source_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CycleCloseInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["cycle_id"]), TypedReference.from_dict(value["closure_ref"]), int(value["source_cursor"]))


@dataclass(frozen=True)
class R48ReconciliationInput:
    schema_version: int
    owner_mission_id: str
    operation_id: str
    authority_result: "R48AuthorityResult"
    observed_source_cursor: int
    reconciliation_evidence: TypedReference | None
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48ReconciliationInput":
        return cls(int(value["schema_version"]), str(value["owner_mission_id"]), str(value["operation_id"]), R48AuthorityResult.from_dict(value["authority_result"]), int(value["observed_source_cursor"]), _ref(value.get("reconciliation_evidence")), str(value["reason_code"]))


@dataclass(frozen=True)
class R48CompositionSpec:
    upstream_extensions: tuple[ExtensionManifest, ...]
    authority_bindings: tuple["R48AuthorityBinding", ...]
    required_extension_ids: frozenset[str]
    field_validation_binding_required: bool
    learning_promotion_required: bool
    legacy_reconciliation_required: bool


@dataclass(frozen=True)
class R48CompositionValidationResult:
    ok: bool
    errors: tuple[R48ErrorCode, ...]
    normalized_extension_ids: tuple[str, ...]
    required_authorities: frozenset[R48AuthorityKind]


@dataclass(frozen=True)
class R48AuthorityBinding:
    authority: R48AuthorityKind
    source: R48BindingSource
    capability_version: str
    required: bool
    bind: Callable[[Any], object]


@dataclass(frozen=True)
class R48CyclePolicySnapshot:
    schema_version: int
    field_validation_required: bool
    learning_promotion_disposition: R48StageDisposition
    legacy_reconciliation_disposition: R48StageDisposition
    policy_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CyclePolicySnapshot":
        return cls(int(value["schema_version"]), bool(value["field_validation_required"]), R48StageDisposition(value["learning_promotion_disposition"]), R48StageDisposition(value["legacy_reconciliation_disposition"]), str(value["policy_digest"]))


@dataclass(frozen=True)
class R48AuthorityResult:
    schema_version: int
    authority: R48AuthorityKind
    authority_operation_id: str
    result_ref: TypedReference | None
    result_digest: str | None
    authority_revision: str | None
    owner_cursor: int | None
    outcome: R48AuthorityOutcome
    proof_refs: tuple[TypedReference, ...]
    proof_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48AuthorityResult":
        return cls(int(value["schema_version"]), R48AuthorityKind(value["authority"]), str(value["authority_operation_id"]), _ref(value.get("result_ref")), value.get("result_digest"), value.get("authority_revision"), value.get("owner_cursor"), R48AuthorityOutcome(value["outcome"]), _refs(value.get("proof_refs")), str(value["proof_digest"]))


@dataclass(frozen=True)
class R48CycleContext:
    schema_version: int
    cycle_id: str
    owner_mission_id: str
    quality_version_ref: TypedReference
    campaign_ref: TypedReference
    trigger_ref: TypedReference
    impact_ref: TypedReference | None
    source_cursor: int
    policy_snapshot: R48CyclePolicySnapshot
    correlation_id: str
    causation_id: str
    record_digest: str
    created_seq: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CycleContext":
        return cls(int(value["schema_version"]), str(value["cycle_id"]), str(value["owner_mission_id"]), TypedReference.from_dict(value["quality_version_ref"]), TypedReference.from_dict(value["campaign_ref"]), TypedReference.from_dict(value["trigger_ref"]), _ref(value.get("impact_ref")), int(value["source_cursor"]), R48CyclePolicySnapshot.from_dict(value["policy_snapshot"]), str(value["correlation_id"]), str(value["causation_id"]), str(value["record_digest"]), int(value["created_seq"]), str(value["created_at"]))


@dataclass(frozen=True)
class R48CoordinationStep:
    schema_version: int
    step_id: str
    cycle_id: str
    step_revision: int
    phase: R48Phase
    status: R48CoordinationStatus
    authority: R48AuthorityKind
    operation_kind: R48OperationKind
    input_refs: tuple[TypedReference, ...]
    input_digest: str
    source_cursor: int
    stage_disposition: R48StageDisposition
    policy_digest: str
    last_operation_id: str | None
    last_receipt_id: str | None
    reason_code: str | None
    origin_event_seq: int
    origin_event_at: str
    state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CoordinationStep":
        return cls(int(value["schema_version"]), str(value["step_id"]), str(value["cycle_id"]), int(value["step_revision"]), R48Phase(value["phase"]), R48CoordinationStatus(value["status"]), R48AuthorityKind(value["authority"]), R48OperationKind(value["operation_kind"]), _refs(value.get("input_refs")), str(value["input_digest"]), int(value["source_cursor"]), R48StageDisposition(value["stage_disposition"]), str(value["policy_digest"]), value.get("last_operation_id"), value.get("last_receipt_id"), value.get("reason_code"), int(value["origin_event_seq"]), str(value["origin_event_at"]), str(value["state_digest"]))


@dataclass(frozen=True)
class R48AuthorityOperation:
    schema_version: int
    operation_id: str
    owner_mission_id: str
    cycle_id: str
    step_id: str
    step_revision: int
    authority: R48AuthorityKind
    operation_kind: R48OperationKind
    request_ref: TypedReference | None
    input_refs: tuple[TypedReference, ...]
    input_digest: str
    policy_digest: str
    source_cursor: int
    authority_idempotency_key: str
    correlation_id: str
    causation_id: str
    request_record_digest: str
    request_created_seq: int
    request_created_at: str
    current_status: R48OperationStatus
    current_receipt_id: str | None
    authority_operation_id: str | None
    result_ref: TypedReference | None
    result_digest: str | None
    authority_revision: str | None
    authority_outcome: R48AuthorityOutcome | None
    proof_digest: str | None
    owner_cursor: int | None
    observed_source_cursor: int | None
    current_state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48AuthorityOperation":
        return cls(int(value["schema_version"]), str(value["operation_id"]), str(value["owner_mission_id"]), str(value["cycle_id"]), str(value["step_id"]), int(value["step_revision"]), R48AuthorityKind(value["authority"]), R48OperationKind(value["operation_kind"]), _ref(value.get("request_ref")), _refs(value.get("input_refs")), str(value["input_digest"]), str(value["policy_digest"]), int(value["source_cursor"]), str(value["authority_idempotency_key"]), str(value["correlation_id"]), str(value["causation_id"]), str(value["request_record_digest"]), int(value["request_created_seq"]), str(value["request_created_at"]), R48OperationStatus(value["current_status"]), value.get("current_receipt_id"), value.get("authority_operation_id"), _ref(value.get("result_ref")), value.get("result_digest"), value.get("authority_revision"), R48AuthorityOutcome(value["authority_outcome"]) if value.get("authority_outcome") else None, value.get("proof_digest"), value.get("owner_cursor"), value.get("observed_source_cursor"), str(value["current_state_digest"]))


@dataclass(frozen=True)
class R48AuthorityReceipt:
    schema_version: int
    receipt_id: str
    owner_mission_id: str
    operation_id: str
    cycle_id: str
    step_id: str
    step_revision: int
    authority: R48AuthorityKind
    authority_operation_id: str
    result_ref: TypedReference | None
    result_digest: str | None
    authority_revision: str | None
    owner_cursor: int | None
    outcome: R48AuthorityOutcome
    proof_refs: tuple[TypedReference, ...]
    proof_digest: str
    semantic_identity: str
    observed_source_cursor: int
    correlation_id: str
    causation_id: str
    record_digest: str
    created_seq: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48AuthorityReceipt":
        return cls(int(value["schema_version"]), str(value["receipt_id"]), str(value["owner_mission_id"]), str(value["operation_id"]), str(value["cycle_id"]), str(value["step_id"]), int(value["step_revision"]), R48AuthorityKind(value["authority"]), str(value["authority_operation_id"]), _ref(value.get("result_ref")), value.get("result_digest"), value.get("authority_revision"), value.get("owner_cursor"), R48AuthorityOutcome(value["outcome"]), _refs(value.get("proof_refs")), str(value["proof_digest"]), str(value["semantic_identity"]), int(value["observed_source_cursor"]), str(value["correlation_id"]), str(value["causation_id"]), str(value["record_digest"]), int(value["created_seq"]), str(value["created_at"]))


@dataclass(frozen=True)
class R48ReentryRecord:
    schema_version: int
    reentry_id: str
    owner_mission_id: str
    cycle_id: str
    prior_step_id: str
    prior_step_revision: int
    target_phase: R48Phase
    target_step_id: str
    target_step_revision: int
    kind: R48ReentryKind
    operation_id: str | None
    new_input_refs: tuple[TypedReference, ...]
    input_digest: str
    observed_owner_cursor: int | None
    reason_code: str
    reconciliation_evidence: TypedReference | None
    record_digest: str
    created_seq: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48ReentryRecord":
        return cls(int(value["schema_version"]), str(value["reentry_id"]), str(value["owner_mission_id"]), str(value["cycle_id"]), str(value["prior_step_id"]), int(value["prior_step_revision"]), R48Phase(value["target_phase"]), str(value["target_step_id"]), int(value["target_step_revision"]), R48ReentryKind(value["kind"]), value.get("operation_id"), _refs(value.get("new_input_refs")), str(value["input_digest"]), value.get("observed_owner_cursor"), str(value["reason_code"]), _ref(value.get("reconciliation_evidence")), str(value["record_digest"]), int(value["created_seq"]), str(value["created_at"]))


@dataclass(frozen=True)
class R48AuthorityProcessingResult:
    command_result: CommandResult
    processing_outcome: R48ProcessingOutcome
    receipt: R48AuthorityReceipt | None
    duplicate_of: str | None


@dataclass(frozen=True)
class R48CycleState:
    context: R48CycleContext
    phase: R48Phase
    status: R48CoordinationStatus
    steps: tuple[R48CoordinationStep, ...]
    operations: tuple[R48AuthorityOperation, ...]
    receipts: tuple[R48AuthorityReceipt, ...]
    reentries: tuple[R48ReentryRecord, ...]
    last_seq: int
    state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48CycleState":
        return cls(
            context=R48CycleContext.from_dict(value["context"]),
            phase=R48Phase(value["phase"]),
            status=R48CoordinationStatus(value["status"]),
            steps=tuple(R48CoordinationStep.from_dict(item) for item in value.get("steps", ())),
            operations=tuple(R48AuthorityOperation.from_dict(item) for item in value.get("operations", ())),
            receipts=tuple(R48AuthorityReceipt.from_dict(item) for item in value.get("receipts", ())),
            reentries=tuple(R48ReentryRecord.from_dict(item) for item in value.get("reentries", ())),
            last_seq=int(value.get("last_seq", 0)),
            state_digest=str(value.get("state_digest", "")),
        )

    def step(self, step_id: str) -> R48CoordinationStep | None:
        return next((item for item in self.steps if item.step_id == step_id), None)

    def operation(self, operation_id: str) -> R48AuthorityOperation | None:
        return next((item for item in self.operations if item.operation_id == operation_id), None)


@dataclass(frozen=True)
class R48State:
    owner_mission_id: str
    cycles: tuple[R48CycleState, ...]
    last_seq: int
    state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R48State":
        return cls(
            owner_mission_id=str(value["owner_mission_id"]),
            cycles=tuple(R48CycleState.from_dict(item) for item in value.get("cycles", ())),
            last_seq=int(value.get("last_seq", 0)),
            state_digest=str(value.get("state_digest", "")),
        )

    def cycle(self, cycle_id: str) -> R48CycleState | None:
        return next((item for item in self.cycles if item.context.cycle_id == cycle_id), None)


__all__ = (
    "R48CompositionSpec",
    "R48CompositionValidationResult",
    "R48AuthorityBinding",
    "R48AuthorityKind",
    "R48BindingSource",
    "R48AuthorityOutcome",
    "R48ProcessingOutcome",
    "R48StageDisposition",
    "R48OperationKind",
    "R48ReentryKind",
    "R48CycleRegistrationInput",
    "R48CapabilityObservationInput",
    "R48AuthorityOperationInput",
    "R48AuthorityReceiptInput",
    "R48ReentryInput",
    "R48WaitingInput",
    "R48CycleCloseInput",
    "R48ReconciliationInput",
    "R48AuthorityResult",
    "R48AuthorityProcessingResult",
    "R48CyclePolicySnapshot",
    "R48CycleContext",
    "R48CoordinationStep",
    "R48AuthorityOperation",
    "R48AuthorityReceipt",
    "R48ReentryRecord",
    "R48CycleState",
    "R48State",
    "R48Phase",
    "R48CoordinationStatus",
    "R48OperationStatus",
)
