"""Deterministic RC8 model-provider governance and durable-resume semantics.

This module deliberately contains no LLM decision making. It classifies provider
faults, applies a shared request budget, and tells a Supervisor how the same
Mission/WorkItem/Attempt must be resumed after transient provider failures.
Persistence of RecoveryCheckpoint belongs to Center/PostgreSQL; Redis may only
coordinate leases/capacity.

Python 3.8 compatible for the target bank runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from .contracts import RC8ContractError


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


class ProviderFaultKind(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_SERVER = "TRANSIENT_SERVER"
    SSE_INCOMPLETE = "SSE_INCOMPLETE"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    AUTH_CONFIGURATION = "AUTH_CONFIGURATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN = "UNKNOWN"


class ProviderHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class RecoveryAction(str, Enum):
    CONTINUE = "CONTINUE"
    WAITING_PROVIDER_CAPACITY = "WAITING_PROVIDER_CAPACITY"
    RETRY_BACKOFF = "RETRY_BACKOFF"
    WAITING_PROVIDER_RECOVERY = "WAITING_PROVIDER_RECOVERY"
    RECONCILE_SIDE_EFFECT = "RECONCILE_SIDE_EFFECT"
    BLOCKED_PROVIDER_CONFIGURATION = "BLOCKED_PROVIDER_CONFIGURATION"


class SideEffectState(str, Enum):
    NONE = "NONE"
    CONFIRMED_NOT_APPLIED = "CONFIRMED_NOT_APPLIED"
    CONFIRMED_APPLIED = "CONFIRMED_APPLIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderFault:
    kind: ProviderFaultKind
    code: str
    message: str
    retry_after_seconds: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProviderFaultKind):
            raise RC8ContractError("PROVIDER_FAULT_KIND_INVALID")
        object.__setattr__(self, "code", _required(self.code, "code"))
        object.__setattr__(self, "message", _required(self.message, "message"))
        if self.retry_after_seconds is not None:
            if not isinstance(self.retry_after_seconds, int) or self.retry_after_seconds < 0:
                raise RC8ContractError("PROVIDER_RETRY_AFTER_INVALID")


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    remaining: int
    next_allowed_at: Optional[int]


class RequestGovernor:
    """Shared rolling-window request budget.

    One instance is intended to be shared by Director and all Workers for one
    provider/account. Limits are configuration, never hard-coded bank facts.
    """

    def __init__(self, *, max_requests: int, window_seconds: int, safety_ratio: float = 0.90) -> None:
        if not isinstance(max_requests, int) or max_requests <= 0:
            raise RC8ContractError("REQUEST_GOVERNOR_MAX_REQUESTS_INVALID")
        if not isinstance(window_seconds, int) or window_seconds <= 0:
            raise RC8ContractError("REQUEST_GOVERNOR_WINDOW_INVALID")
        if not isinstance(safety_ratio, (int, float)) or safety_ratio <= 0.0 or safety_ratio > 1.0:
            raise RC8ContractError("REQUEST_GOVERNOR_SAFETY_RATIO_INVALID")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.safety_ratio = float(safety_ratio)
        self.safe_limit = max(1, min(max_requests, int(max_requests * self.safety_ratio)))
        self._request_times: List[int] = []

    def _prune(self, now: int) -> None:
        cutoff = now - self.window_seconds
        self._request_times = [stamp for stamp in self._request_times if stamp > cutoff]

    def reserve(self, now: int) -> BudgetDecision:
        if not isinstance(now, int) or now < 0:
            raise RC8ContractError("REQUEST_GOVERNOR_NOW_INVALID")
        self._prune(now)
        if len(self._request_times) >= self.safe_limit:
            earliest = min(self._request_times)
            return BudgetDecision(
                allowed=False,
                remaining=0,
                next_allowed_at=earliest + self.window_seconds + 1,
            )
        self._request_times.append(now)
        return BudgetDecision(
            allowed=True,
            remaining=max(0, self.safe_limit - len(self._request_times)),
            next_allowed_at=None,
        )


@dataclass
class ProviderHealthState:
    state: ProviderHealth = ProviderHealth.HEALTHY
    consecutive_transient_failures: int = 0
    last_fault: Optional[ProviderFaultKind] = None

    def record_success(self) -> None:
        self.state = ProviderHealth.HEALTHY
        self.consecutive_transient_failures = 0
        self.last_fault = None

    def record_fault(self, fault: ProviderFault, *, unavailable_after: int = 3) -> None:
        if not isinstance(fault, ProviderFault):
            raise RC8ContractError("PROVIDER_FAULT_REQUIRED")
        self.last_fault = fault.kind
        if fault.kind in {
            ProviderFaultKind.RATE_LIMIT,
            ProviderFaultKind.TRANSIENT_SERVER,
            ProviderFaultKind.SSE_INCOMPLETE,
            ProviderFaultKind.CONNECT_TIMEOUT,
            ProviderFaultKind.READ_TIMEOUT,
        }:
            self.consecutive_transient_failures += 1
            self.state = (
                ProviderHealth.UNAVAILABLE
                if self.consecutive_transient_failures >= unavailable_after
                else ProviderHealth.DEGRADED
            )
        elif fault.kind in {ProviderFaultKind.AUTH_CONFIGURATION, ProviderFaultKind.INVALID_REQUEST}:
            self.state = ProviderHealth.UNAVAILABLE
        else:
            self.state = ProviderHealth.DEGRADED


@dataclass(frozen=True)
class RecoveryCheckpoint:
    checkpoint_id: str
    mission_id: str
    test_run_id: str
    stage_instance_id: str
    work_item_id: str
    attempt_id: str
    input_snapshot_ref: str
    cursor: str
    side_effect_state: SideEffectState = SideEffectState.NONE
    completed_effect_refs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in (
            "checkpoint_id",
            "mission_id",
            "test_run_id",
            "stage_instance_id",
            "work_item_id",
            "attempt_id",
            "input_snapshot_ref",
            "cursor",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.side_effect_state, SideEffectState):
            raise RC8ContractError("SIDE_EFFECT_STATE_INVALID")
        refs = []
        for item in self.completed_effect_refs:
            refs.append(_required(item, "completed_effect_ref"))
        object.__setattr__(self, "completed_effect_refs", tuple(refs))

    @property
    def resume_key(self) -> str:
        # Same checkpoint always produces the same resume identity. Supervisor
        # must reclaim this WorkItem rather than creating a duplicate mission.
        return "%s:%s:%s:%s" % (
            self.mission_id,
            self.stage_instance_id,
            self.work_item_id,
            self.checkpoint_id,
        )


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    resume_key: str
    mission_id: str
    work_item_id: str
    attempt_id: str
    resume_at: Optional[int]
    provider_health: ProviderHealth
    reason: str
    r1_event_type: str


@dataclass(frozen=True)
class RetryPolicy:
    base_delay_seconds: int = 2
    max_delay_seconds: int = 120
    unavailable_after: int = 3

    def __post_init__(self) -> None:
        if self.base_delay_seconds <= 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise RC8ContractError("RETRY_POLICY_DELAY_INVALID")
        if self.unavailable_after <= 0:
            raise RC8ContractError("RETRY_POLICY_UNAVAILABLE_AFTER_INVALID")

    def delay(self, failure_number: int) -> int:
        if not isinstance(failure_number, int) or failure_number <= 0:
            raise RC8ContractError("RETRY_FAILURE_NUMBER_INVALID")
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (failure_number - 1)))


def classify_provider_fault(*, status_code: Optional[int] = None, message: str = "", retry_after_seconds: Optional[int] = None) -> ProviderFault:
    text = (message or "").strip()
    lowered = text.lower()
    if status_code == 429:
        kind = ProviderFaultKind.RATE_LIMIT
        code = "HTTP_429"
    elif status_code in {502, 503, 504}:
        kind = ProviderFaultKind.TRANSIENT_SERVER
        code = "HTTP_%s" % status_code
    elif status_code in {401, 403}:
        kind = ProviderFaultKind.AUTH_CONFIGURATION
        code = "HTTP_%s" % status_code
    elif status_code is not None and 400 <= status_code < 500:
        kind = ProviderFaultKind.INVALID_REQUEST
        code = "HTTP_%s" % status_code
    elif "sse" in lowered and ("done" in lowered or "closed" in lowered or "ended" in lowered):
        kind = ProviderFaultKind.SSE_INCOMPLETE
        code = "SSE_INCOMPLETE"
    elif "connect timeout" in lowered or "connection timeout" in lowered:
        kind = ProviderFaultKind.CONNECT_TIMEOUT
        code = "CONNECT_TIMEOUT"
    elif "read timeout" in lowered or "timed out while reading" in lowered:
        kind = ProviderFaultKind.READ_TIMEOUT
        code = "READ_TIMEOUT"
    else:
        kind = ProviderFaultKind.UNKNOWN
        code = "UNKNOWN_PROVIDER_FAULT"
    return ProviderFault(
        kind=kind,
        code=code,
        message=text or code,
        retry_after_seconds=retry_after_seconds,
    )


class RecoverySupervisor:
    """Non-LLM recovery policy for provider faults."""

    def __init__(self, policy: Optional[RetryPolicy] = None) -> None:
        self.policy = policy or RetryPolicy()
        self.health = ProviderHealthState()

    def recovered(self) -> None:
        self.health.record_success()

    def decide(
        self,
        checkpoint: RecoveryCheckpoint,
        fault: ProviderFault,
        *,
        now: int,
        next_capacity_at: Optional[int] = None,
    ) -> RecoveryDecision:
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise RC8ContractError("RECOVERY_CHECKPOINT_REQUIRED")
        if not isinstance(fault, ProviderFault):
            raise RC8ContractError("PROVIDER_FAULT_REQUIRED")
        if not isinstance(now, int) or now < 0:
            raise RC8ContractError("RECOVERY_NOW_INVALID")

        self.health.record_fault(fault, unavailable_after=self.policy.unavailable_after)

        # Never blindly replay an operation whose external side effect may have
        # happened before the provider/transport response disappeared.
        if checkpoint.side_effect_state == SideEffectState.UNKNOWN:
            return RecoveryDecision(
                action=RecoveryAction.RECONCILE_SIDE_EFFECT,
                resume_key=checkpoint.resume_key,
                mission_id=checkpoint.mission_id,
                work_item_id=checkpoint.work_item_id,
                attempt_id=checkpoint.attempt_id,
                resume_at=None,
                provider_health=self.health.state,
                reason="external side effect outcome is unknown; reconcile before replay",
                r1_event_type="PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED",
            )

        if fault.kind == ProviderFaultKind.RATE_LIMIT:
            candidates = [value for value in (next_capacity_at, now + (fault.retry_after_seconds or 0)) if value is not None]
            resume_at = max(candidates) if candidates else now + self.policy.base_delay_seconds
            return self._decision(
                checkpoint,
                RecoveryAction.WAITING_PROVIDER_CAPACITY,
                resume_at,
                "provider request budget exhausted; preserve task and resume after capacity",
                "PROVIDER_CAPACITY_WAITING",
            )

        if fault.kind in {
            ProviderFaultKind.TRANSIENT_SERVER,
            ProviderFaultKind.SSE_INCOMPLETE,
            ProviderFaultKind.CONNECT_TIMEOUT,
            ProviderFaultKind.READ_TIMEOUT,
        }:
            failures = self.health.consecutive_transient_failures
            delay = self.policy.delay(failures)
            if self.health.state == ProviderHealth.UNAVAILABLE:
                return self._decision(
                    checkpoint,
                    RecoveryAction.WAITING_PROVIDER_RECOVERY,
                    now + delay,
                    "provider unavailable after repeated transient failures; mission remains durable",
                    "PROVIDER_RECOVERY_WAITING",
                )
            return self._decision(
                checkpoint,
                RecoveryAction.RETRY_BACKOFF,
                now + delay,
                "transient provider fault; resume same work item from checkpoint after backoff",
                "PROVIDER_RETRY_SCHEDULED",
            )

        if fault.kind in {ProviderFaultKind.AUTH_CONFIGURATION, ProviderFaultKind.INVALID_REQUEST}:
            return self._decision(
                checkpoint,
                RecoveryAction.BLOCKED_PROVIDER_CONFIGURATION,
                None,
                "non-transient provider/configuration fault requires correction; do not mark test task failed",
                "PROVIDER_CONFIGURATION_BLOCKED",
            )

        return self._decision(
            checkpoint,
            RecoveryAction.WAITING_PROVIDER_RECOVERY,
            now + self.policy.base_delay_seconds,
            "unknown provider fault; fail closed and preserve durable mission",
            "PROVIDER_RECOVERY_WAITING",
        )

    def _decision(self, checkpoint, action, resume_at, reason, event_type):
        return RecoveryDecision(
            action=action,
            resume_key=checkpoint.resume_key,
            mission_id=checkpoint.mission_id,
            work_item_id=checkpoint.work_item_id,
            attempt_id=checkpoint.attempt_id,
            resume_at=resume_at,
            provider_health=self.health.state,
            reason=reason,
            r1_event_type=event_type,
        )
