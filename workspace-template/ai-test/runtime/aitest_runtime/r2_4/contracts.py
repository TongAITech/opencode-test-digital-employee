"""R2.4 Scheduler and bounded autonomous-loop contracts.

R2.4 is an orchestration boundary.  It consumes the R1.2 Work Graph and
caller-owned observations; it does not create a second durable runtime truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError as DurableRuntimeError
from aitest_runtime.durable_core import canonical_sha256


CONTRACT_VERSION = "R2.4_EXECUTION_CONTRACT_V1"
R2_4_CONTRACT_VERSION = CONTRACT_VERSION
SCHEMA_VERSION = 1


class R2_4Error(DurableRuntimeError):
    """A typed, fail-closed R2.4 contract error."""


class LoopState(str, Enum):
    OBSERVE = "OBSERVE"
    EVALUATE = "EVALUATE"
    REPLAN_REQUEST = "REPLAN_REQUEST"
    SCHEDULE = "SCHEDULE"
    DISPATCH = "DISPATCH"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"
    PLAN_COMPLETE = "PLAN_COMPLETE"


OBSERVE = LoopState.OBSERVE.value
EVALUATE = LoopState.EVALUATE.value
REPLAN_REQUEST = LoopState.REPLAN_REQUEST.value
SCHEDULE = LoopState.SCHEDULE.value
DISPATCH = LoopState.DISPATCH.value
WAIT = LoopState.WAIT.value
BLOCKED = LoopState.BLOCKED.value
PLAN_COMPLETE = LoopState.PLAN_COMPLETE.value
LOOP_STATES = frozenset(item.value for item in LoopState)

# Stable bounded-loop exhaustion reason codes.  These are decision reasons
# only; they never mutate the R1.2 Task truth.
LOOP_MAX_CYCLES_EXHAUSTED = "LOOP_MAX_CYCLES_EXHAUSTED"
LOOP_MAX_DISPATCHES_EXHAUSTED = "LOOP_MAX_DISPATCHES_EXHAUSTED"
LOOP_BUDGET_LIMIT_EXHAUSTED = "LOOP_BUDGET_LIMIT_EXHAUSTED"
LOOP_DEADLINE_EXCEEDED = "LOOP_DEADLINE_EXCEEDED"
LOOP_PROGRESS_REQUIRED = "LOOP_PROGRESS_REQUIRED"


class DispatchReceiptStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


ACCEPTED = DispatchReceiptStatus.ACCEPTED.value
REJECTED = DispatchReceiptStatus.REJECTED.value
UNKNOWN = DispatchReceiptStatus.UNKNOWN.value


class TaskReadinessStatus(str, Enum):
    READY = "READY"
    ACTIVE = "ACTIVE"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


READY = TaskReadinessStatus.READY.value
ACTIVE = TaskReadinessStatus.ACTIVE.value
NOT_ELIGIBLE = TaskReadinessStatus.NOT_ELIGIBLE.value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a finite number")
    if value < minimum:
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be >= {minimum}")
    return value


def _digest(value: Any, name: str) -> str:
    result = _text(value, name).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return result


def _plain(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item, f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict(), name)
    raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} contains an unsupported value")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be an object")
    return _plain(dict(value), name)


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_plain(item, f"{name}[{index}]") for index, item in enumerate(value))


@dataclass(frozen=True)
class SchedulingPolicy:
    policy_id: str
    policy_version: int
    max_dispatches_per_cycle: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "policy_version", _positive_int(self.policy_version, "policy_version"))
        object.__setattr__(
            self,
            "max_dispatches_per_cycle",
            _positive_int(self.max_dispatches_per_cycle, "max_dispatches_per_cycle"),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "SchedulingPolicy") -> "SchedulingPolicy":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "scheduling_policy")
        return cls(
            policy_id=raw.get("policy_id"),
            policy_version=raw.get("policy_version"),
            max_dispatches_per_cycle=raw.get("max_dispatches_per_cycle"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "max_dispatches_per_cycle": self.max_dispatches_per_cycle,
        }


@dataclass(frozen=True)
class LoopBudget:
    budget_id: str
    max_cycles: int
    max_dispatches: int
    deadline: str
    budget_limit: int | float

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _text(self.budget_id, "budget_id"))
        object.__setattr__(self, "max_cycles", _positive_int(self.max_cycles, "max_cycles"))
        object.__setattr__(self, "max_dispatches", _non_negative_int(self.max_dispatches, "max_dispatches"))
        object.__setattr__(self, "deadline", _text(self.deadline, "deadline"))
        object.__setattr__(self, "budget_limit", _number(self.budget_limit, "budget_limit"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "LoopBudget") -> "LoopBudget":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "loop_budget")
        return cls(
            budget_id=raw.get("budget_id"),
            max_cycles=raw.get("max_cycles"),
            max_dispatches=raw.get("max_dispatches"),
            deadline=raw.get("deadline"),
            budget_limit=raw.get("budget_limit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "max_cycles": self.max_cycles,
            "max_dispatches": self.max_dispatches,
            "deadline": self.deadline,
            "budget_limit": self.budget_limit,
        }


@dataclass(frozen=True)
class LoopProgress:
    loop_id: str
    budget_id: str
    cycle: int
    dispatches_used: int
    budget_used: int | float
    observed_at: str
    source_ref: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "loop_id", _text(self.loop_id, "loop_id"))
        object.__setattr__(self, "budget_id", _text(self.budget_id, "budget_id"))
        object.__setattr__(self, "cycle", _non_negative_int(self.cycle, "cycle"))
        object.__setattr__(self, "dispatches_used", _non_negative_int(self.dispatches_used, "dispatches_used"))
        object.__setattr__(self, "budget_used", _number(self.budget_used, "budget_used"))
        object.__setattr__(self, "observed_at", _text(self.observed_at, "observed_at"))
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source_digest"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "LoopProgress") -> "LoopProgress":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "loop_progress")
        return cls(
            loop_id=raw.get("loop_id"),
            budget_id=raw.get("budget_id"),
            cycle=raw.get("cycle"),
            dispatches_used=raw.get("dispatches_used"),
            budget_used=raw.get("budget_used"),
            observed_at=raw.get("observed_at"),
            source_ref=raw.get("source_ref"),
            source_digest=raw.get("source_digest"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "budget_id": self.budget_id,
            "cycle": self.cycle,
            "dispatches_used": self.dispatches_used,
            "budget_used": self.budget_used,
            "observed_at": self.observed_at,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True)
class LoopAccounting:
    budget_id: str
    observed_budget_delta: int | float
    source_ref: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _text(self.budget_id, "budget_id"))
        object.__setattr__(
            self,
            "observed_budget_delta",
            _number(self.observed_budget_delta, "observed_budget_delta"),
        )
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_digest", _digest(self.source_digest, "source_digest"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "LoopAccounting") -> "LoopAccounting":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "loop_accounting")
        return cls(
            budget_id=raw.get("budget_id"),
            observed_budget_delta=raw.get("observed_budget_delta"),
            source_ref=raw.get("source_ref"),
            source_digest=raw.get("source_digest"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "observed_budget_delta": self.observed_budget_delta,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True)
class DispatchBinding:
    mission_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    capability_id: str
    capability_version: str | int
    resolution_id: str
    snapshot_id: str
    binding_digest: str
    policy_refs: tuple[str, ...] = ()
    authorization_refs: tuple[str, ...] = ()
    valid_until: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "plan_id",
            "plan_revision_id",
            "task_id",
            "capability_id",
            "resolution_id",
            "snapshot_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        version = self.capability_version
        if isinstance(version, bool) or not isinstance(version, (str, int)) or not str(version).strip():
            raise R2_4Error("R2_4_SCHEMA_INVALID", "capability_version must be non-empty")
        object.__setattr__(self, "capability_version", str(version))
        object.__setattr__(self, "binding_digest", _digest(self.binding_digest, "binding_digest"))
        refs = _sequence(self.policy_refs, "policy_refs")
        auth = _sequence(self.authorization_refs, "authorization_refs")
        object.__setattr__(self, "policy_refs", tuple(_text(item, "policy_refs[]") for item in refs))
        object.__setattr__(self, "authorization_refs", tuple(_text(item, "authorization_refs[]") for item in auth))
        object.__setattr__(self, "valid_until", _optional_text(self.valid_until, "valid_until"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "DispatchBinding") -> "DispatchBinding":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "dispatch_binding")
        return cls(
            mission_id=raw.get("mission_id"),
            plan_id=raw.get("plan_id"),
            plan_revision_id=raw.get("plan_revision_id", raw.get("plan_revision")),
            task_id=raw.get("task_id"),
            capability_id=raw.get("capability_id"),
            capability_version=raw.get("capability_version"),
            resolution_id=raw.get("resolution_id"),
            snapshot_id=raw.get("snapshot_id"),
            binding_digest=raw.get("binding_digest", raw.get("dispatch_binding_digest")),
            policy_refs=raw.get("policy_refs", ()),
            authorization_refs=raw.get("authorization_refs", ()),
            valid_until=raw.get("valid_until"),
        )

    @property
    def dispatch_binding_digest(self) -> str:
        return self.binding_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "resolution_id": self.resolution_id,
            "snapshot_id": self.snapshot_id,
            "binding_digest": self.binding_digest,
            "policy_refs": list(self.policy_refs),
            "authorization_refs": list(self.authorization_refs),
            "valid_until": self.valid_until,
        }


@dataclass(frozen=True)
class ObservationCursor:
    mission_id: str
    observed_seq: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "observed_seq", _non_negative_int(self.observed_seq, "observed_seq"))

    @property
    def as_of_seq(self) -> int:
        return self.observed_seq

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "observed_seq": self.observed_seq}


@dataclass(frozen=True)
class TaskReadiness:
    task_id: str
    status: str
    reason_code: str | None = None
    reason: str | None = None
    binding: DispatchBinding | None = None
    capability_id: str | None = None
    capability_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        status = self.status.value if isinstance(self.status, Enum) else str(self.status).upper()
        if status not in {READY, ACTIVE, WAIT, BLOCKED, NOT_ELIGIBLE}:
            raise R2_4Error("R2_4_SCHEMA_INVALID", f"unsupported task readiness status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason_code", _optional_text(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))
        if self.binding is not None and not isinstance(self.binding, DispatchBinding):
            object.__setattr__(self, "binding", DispatchBinding.from_mapping(self.binding))
        object.__setattr__(self, "capability_id", _optional_text(self.capability_id, "capability_id"))
        object.__setattr__(self, "capability_version", _optional_text(self.capability_version, "capability_version"))

    @property
    def ready(self) -> bool:
        return self.status == READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "binding": self.binding.to_dict() if self.binding else None,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
        }


@dataclass(frozen=True)
class WaitCondition:
    reason_code: str
    wake_on: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "wake_on", tuple(_text(item, "wake_on[]") for item in _sequence(self.wake_on, "wake_on")))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {"reason_code": self.reason_code, "wake_on": list(self.wake_on), "reason": self.reason}


@dataclass(frozen=True)
class BlockReason:
    reason_code: str
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {"reason_code": self.reason_code, "reason": self.reason}


@dataclass(frozen=True)
class ReplanRequest:
    mission_id: str
    plan_id: str | None
    plan_revision_id: str | None
    reason_code: str
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "plan_id", _optional_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_revision_id", _optional_text(self.plan_revision_id, "plan_revision_id"))
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


def dispatch_id_for(
    mission_id: str,
    plan_id: str,
    plan_revision_id: str,
    task_id: str,
    capability_id: str,
    capability_version: str | int,
    dispatch_binding_digest: str,
) -> str:
    """Return the frozen canonical SHA-256 dispatch identity."""
    identity = ":".join(
        (
            "r2.4",
            _text(mission_id, "mission_id"),
            _text(plan_id, "plan_id"),
            _text(plan_revision_id, "plan_revision_id"),
            _text(task_id, "task_id"),
            _text(capability_id, "capability_id"),
            _text(str(capability_version), "capability_version"),
            _digest(dispatch_binding_digest, "dispatch_binding_digest"),
        )
    )
    return canonical_sha256(identity)


@dataclass(frozen=True)
class DispatchRequest:
    mission_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    capability_id: str
    capability_version: str | int
    dispatch_binding_digest: str
    binding: DispatchBinding
    dispatch_id: str = field(init=False)
    activation_command_id: str = field(init=False)
    activation_command_type: str = field(init=False, default="TRANSITION_TASK")

    def __post_init__(self) -> None:
        for name in ("mission_id", "plan_id", "plan_revision_id", "task_id", "capability_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "capability_version", str(self.capability_version))
        object.__setattr__(self, "dispatch_binding_digest", _digest(self.dispatch_binding_digest, "dispatch_binding_digest"))
        if not isinstance(self.binding, DispatchBinding):
            object.__setattr__(self, "binding", DispatchBinding.from_mapping(self.binding))
        expected = dispatch_id_for(
            self.mission_id,
            self.plan_id,
            self.plan_revision_id,
            self.task_id,
            self.capability_id,
            self.capability_version,
            self.dispatch_binding_digest,
        )
        object.__setattr__(self, "dispatch_id", expected)
        object.__setattr__(self, "activation_command_id", f"r2.4:{expected}:ACTIVATE_TASK")

    def activation_payload(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "target_state": "ACTIVE",
        }

    @property
    def command_id(self) -> str:
        return self.activation_command_id

    @property
    def command_type(self) -> str:
        return self.activation_command_type

    @property
    def payload(self) -> dict[str, Any]:
        return self.activation_payload()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "dispatch_binding_digest": self.dispatch_binding_digest,
            "binding": self.binding.to_dict(),
            "dispatch_id": self.dispatch_id,
            "activation_command_id": self.activation_command_id,
            "activation_command_type": self.activation_command_type,
            "activation_payload": self.activation_payload(),
        }


@dataclass(frozen=True)
class DispatchResult:
    dispatch_id: str
    status: str
    receipt: Mapping[str, Any] | None = None
    reason_code: str | None = None
    reason: str | None = None
    attempt_count: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _text(self.dispatch_id, "dispatch_id"))
        status = self.status.value if isinstance(self.status, Enum) else str(self.status).upper()
        if status not in {ACCEPTED, REJECTED, UNKNOWN}:
            raise R2_4Error("R2_4_SCHEMA_INVALID", f"unsupported dispatch status: {status}")
        object.__setattr__(self, "status", status)
        if self.receipt is not None:
            object.__setattr__(self, "receipt", _mapping(self.receipt, "receipt"))
        object.__setattr__(self, "reason_code", _optional_text(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))
        object.__setattr__(self, "attempt_count", _non_negative_int(self.attempt_count, "attempt_count"))

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED

    @property
    def outcome(self) -> str:
        return self.status

    @property
    def receipt_status(self) -> str:
        return self.status

    @property
    def rejected(self) -> bool:
        return self.status == REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "status": self.status,
            "receipt": dict(self.receipt) if self.receipt is not None else None,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "attempt_count": self.attempt_count,
        }


@dataclass(frozen=True)
class NextProgressCandidate:
    """A non-durable candidate returned to the caller for acknowledgement."""

    loop_id: str
    budget_id: str
    cycle: int
    dispatches_used: int
    budget_used: int | float
    observed_at: str
    progress_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "loop_id", _text(self.loop_id, "loop_id"))
        object.__setattr__(self, "budget_id", _text(self.budget_id, "budget_id"))
        object.__setattr__(self, "cycle", _non_negative_int(self.cycle, "cycle"))
        object.__setattr__(self, "dispatches_used", _non_negative_int(self.dispatches_used, "dispatches_used"))
        object.__setattr__(self, "budget_used", _number(self.budget_used, "budget_used"))
        object.__setattr__(self, "observed_at", _text(self.observed_at, "observed_at"))
        object.__setattr__(self, "progress_digest", _digest(self.progress_digest, "progress_digest"))

    @classmethod
    def build(
        cls,
        *,
        loop_id: str,
        budget_id: str,
        cycle: int,
        dispatches_used: int,
        budget_used: int | float,
        observed_at: str,
    ) -> "NextProgressCandidate":
        payload = {
            "loop_id": loop_id,
            "budget_id": budget_id,
            "cycle": cycle,
            "dispatches_used": dispatches_used,
            "budget_used": budget_used,
            "observed_at": observed_at,
        }
        return cls(**payload, progress_digest=canonical_sha256(payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "budget_id": self.budget_id,
            "cycle": self.cycle,
            "dispatches_used": self.dispatches_used,
            "budget_used": self.budget_used,
            "observed_at": self.observed_at,
            "progress_digest": self.progress_digest,
        }


@dataclass(frozen=True)
class LoopIdentity:
    loop_id: str
    mission_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "loop_id", _text(self.loop_id, "loop_id"))
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))

    def to_dict(self) -> dict[str, str]:
        return {"loop_id": self.loop_id, "mission_id": self.mission_id}


@dataclass(frozen=True)
class LoopDecision:
    state: str
    next_state: str
    mission_id: str
    plan_id: str | None = None
    plan_revision_id: str | None = None
    loop_id: str | None = None
    budget_id: str | None = None
    observed_seq: int | None = None
    selected_task_ids: tuple[str, ...] = ()
    readiness: tuple[TaskReadiness, ...] = ()
    dispatch_results: tuple[DispatchResult, ...] = ()
    command_results: tuple[Any, ...] = ()
    reason_code: str | None = None
    reason: str | None = None
    wait_condition: WaitCondition | None = None
    block_reason: BlockReason | None = None
    replan_request: ReplanRequest | None = None
    next_progress_candidate: NextProgressCandidate | None = None
    dispatch_attempt_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name in ("state", "next_state"):
            value = getattr(self, name)
            normalized = value.value if isinstance(value, Enum) else str(value).upper()
            if normalized not in LOOP_STATES:
                raise R2_4Error("R2_4_SCHEMA_INVALID", f"unsupported loop state: {normalized}")
            object.__setattr__(self, name, normalized)
        object.__setattr__(self, "plan_id", _optional_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_revision_id", _optional_text(self.plan_revision_id, "plan_revision_id"))
        object.__setattr__(self, "loop_id", _optional_text(self.loop_id, "loop_id"))
        object.__setattr__(self, "budget_id", _optional_text(self.budget_id, "budget_id"))
        if self.observed_seq is not None:
            object.__setattr__(self, "observed_seq", _non_negative_int(self.observed_seq, "observed_seq"))
        object.__setattr__(self, "selected_task_ids", tuple(_text(item, "selected_task_ids[]") for item in self.selected_task_ids))
        object.__setattr__(self, "readiness", tuple(item if isinstance(item, TaskReadiness) else TaskReadiness(**item) for item in self.readiness))
        object.__setattr__(self, "dispatch_results", tuple(item if isinstance(item, DispatchResult) else DispatchResult(**item) for item in self.dispatch_results))
        object.__setattr__(self, "reason_code", _optional_text(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))
        if self.wait_condition is not None and not isinstance(self.wait_condition, WaitCondition):
            object.__setattr__(self, "wait_condition", WaitCondition(**self.wait_condition))
        if self.block_reason is not None and not isinstance(self.block_reason, BlockReason):
            object.__setattr__(self, "block_reason", BlockReason(**self.block_reason))
        if self.replan_request is not None and not isinstance(self.replan_request, ReplanRequest):
            object.__setattr__(self, "replan_request", ReplanRequest(**self.replan_request))
        if self.next_progress_candidate is not None and not isinstance(self.next_progress_candidate, NextProgressCandidate):
            object.__setattr__(self, "next_progress_candidate", NextProgressCandidate(**self.next_progress_candidate))
        object.__setattr__(self, "dispatch_attempt_count", _non_negative_int(self.dispatch_attempt_count, "dispatch_attempt_count"))

    @property
    def outcome(self) -> str:
        return self.next_state

    @property
    def status(self) -> str:
        return self.next_state

    @property
    def error_code(self) -> str | None:
        return self.reason_code

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(getattr(item, "command_id", "") for item in self.command_results if getattr(item, "command_id", None))

    @property
    def ok(self) -> bool:
        return self.next_state in {DISPATCH, PLAN_COMPLETE, WAIT}

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "next_state": self.next_state,
            "outcome": self.next_state,
            "status": self.next_state,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "loop_id": self.loop_id,
            "budget_id": self.budget_id,
            "observed_seq": self.observed_seq,
            "selected_task_ids": list(self.selected_task_ids),
            "readiness": [item.to_dict() for item in self.readiness],
            "dispatch_results": [item.to_dict() for item in self.dispatch_results],
            "command_results": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.command_results],
            "reason_code": self.reason_code,
            "reason": self.reason,
            "wait_condition": self.wait_condition.to_dict() if self.wait_condition else None,
            "block_reason": self.block_reason.to_dict() if self.block_reason else None,
            "replan_request": self.replan_request.to_dict() if self.replan_request else None,
            "next_progress_candidate": self.next_progress_candidate.to_dict() if self.next_progress_candidate else None,
            "dispatch_attempt_count": self.dispatch_attempt_count,
        }


@dataclass(frozen=True)
class LoopRequest:
    mission_id: str
    plan_id: str
    plan_revision_id: str
    observed_seq: int
    loop_id: str
    scheduling_policy: SchedulingPolicy
    loop_budget: LoopBudget
    loop_progress: LoopProgress
    loop_accounting: LoopAccounting
    resolution: Mapping[str, Any]
    dispatch_bindings: tuple[DispatchBinding, ...]
    observed_at: str
    actor: Mapping[str, str] = field(default_factory=lambda: {"type": "SYSTEM", "id": "r2.4-orchestrator"})

    def __post_init__(self) -> None:
        for name in ("mission_id", "plan_id", "plan_revision_id", "loop_id", "observed_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "observed_seq", _non_negative_int(self.observed_seq, "observed_seq"))
        object.__setattr__(self, "scheduling_policy", SchedulingPolicy.from_mapping(self.scheduling_policy))
        object.__setattr__(self, "loop_budget", LoopBudget.from_mapping(self.loop_budget))
        object.__setattr__(self, "loop_progress", LoopProgress.from_mapping(self.loop_progress))
        object.__setattr__(self, "loop_accounting", LoopAccounting.from_mapping(self.loop_accounting))
        object.__setattr__(self, "resolution", _mapping(self.resolution, "resolution"))
        bindings = _sequence(self.dispatch_bindings, "dispatch_bindings")
        object.__setattr__(self, "dispatch_bindings", tuple(DispatchBinding.from_mapping(item) for item in bindings))
        actor = _mapping(self.actor, "actor")
        object.__setattr__(self, "actor", {"type": _text(actor.get("type"), "actor.type"), "id": _text(actor.get("id"), "actor.id")})

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "LoopRequest") -> "LoopRequest":
        if isinstance(value, cls):
            return value
        raw = _mapping(value, "loop_request")
        return cls(
            mission_id=raw.get("mission_id"),
            plan_id=raw.get("plan_id"),
            plan_revision_id=raw.get("plan_revision_id", raw.get("plan_revision")),
            observed_seq=raw.get("observed_seq", raw.get("as_of_seq")),
            loop_id=raw.get("loop_id"),
            scheduling_policy=raw.get("scheduling_policy", raw.get("policy")),
            loop_budget=raw.get("loop_budget", raw.get("budget")),
            loop_progress=raw.get("loop_progress", raw.get("progress")),
            loop_accounting=raw.get("loop_accounting", raw.get("accounting")),
            resolution=raw.get("resolution"),
            dispatch_bindings=raw.get("dispatch_bindings", raw.get("bindings", ())),
            observed_at=raw.get("observed_at"),
            actor=raw.get("actor", {"type": "SYSTEM", "id": "r2.4-orchestrator"}),
        )


# Compatibility names used by the detailed design vocabulary.
ReadinessObservation = LoopRequest
ExecutionLoopRequest = LoopRequest
SchedulerInput = LoopRequest
AutonomousLoopInput = LoopRequest
LoopProgressCandidate = NextProgressCandidate
deterministic_dispatch_id = dispatch_id_for
compute_dispatch_id = dispatch_id_for


__all__ = [
    "ACCEPTED",
    "ACTIVE",
    "AutonomousLoopInput",
    "BLOCKED",
    "CONTRACT_VERSION",
    "DISPATCH",
    "DispatchBinding",
    "DispatchReceiptStatus",
    "DispatchRequest",
    "DispatchResult",
    "EVALUATE",
    "ExecutionLoopRequest",
    "LoopAccounting",
    "LoopBudget",
    "LoopDecision",
    "LoopIdentity",
    "LoopProgress",
    "LoopProgressCandidate",
    "LoopRequest",
    "LoopState",
    "LOOP_BUDGET_LIMIT_EXHAUSTED",
    "LOOP_DEADLINE_EXCEEDED",
    "LOOP_MAX_CYCLES_EXHAUSTED",
    "LOOP_MAX_DISPATCHES_EXHAUSTED",
    "LOOP_PROGRESS_REQUIRED",
    "NOT_ELIGIBLE",
    "NextProgressCandidate",
    "OBSERVE",
    "ObservationCursor",
    "PLAN_COMPLETE",
    "READY",
    "REJECTED",
    "REPLAN_REQUEST",
    "R2_4_CONTRACT_VERSION",
    "R2_4Error",
    "ReadinessObservation",
    "SCHEDULE",
    "SCHEMA_VERSION",
    "SchedulerInput",
    "SchedulingPolicy",
    "TaskReadiness",
    "TaskReadinessStatus",
    "UNKNOWN",
    "WAIT",
    "BlockReason",
    "ReplanRequest",
    "WaitCondition",
    "dispatch_id_for",
    "deterministic_dispatch_id",
    "compute_dispatch_id",
]
