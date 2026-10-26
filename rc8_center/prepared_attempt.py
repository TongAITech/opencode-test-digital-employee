"""RC8 N5 PreparedAttempt lifecycle and execution gate.

N5 binds one concrete case execution attempt to current test data, reservation,
fresh authentication, environment, route and reality snapshot. A case may not
enter execution unless the exact PreparedAttempt is current, PREPARED and fresh.

This is Center-owned durable control state. It does not create test PASS.
Python 3.8 compatible for bank portability.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple


class PreparedAttemptError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreparedAttemptError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise PreparedAttemptError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PreparedAttemptError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class PreparedAttemptState(str, Enum):
    SELECTED = "SELECTED"
    VERIFIED = "VERIFIED"
    RESERVED = "RESERVED"
    FRESH = "FRESH"
    PREPARED = "PREPARED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class AuthBindingMode(str, Enum):
    FRESH_LOGIN = "FRESH_LOGIN"


_TERMINAL_STATES = {PreparedAttemptState.RELEASED, PreparedAttemptState.QUARANTINED}


@dataclass(frozen=True)
class PreparedAttempt:
    prepared_attempt_id: str
    test_run_id: str
    mission_node_id: str
    case_id: str
    attempt_id: str
    reality_snapshot_id: str
    data_refs: Tuple[str, ...]
    state: PreparedAttemptState = PreparedAttemptState.SELECTED
    verification_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    reservation_ref: Optional[str] = None
    reservation_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    data_freshness_ref: Optional[str] = None
    auth_session_ref: Optional[str] = None
    auth_binding_mode: Optional[AuthBindingMode] = None
    auth_acquired_at: Optional[int] = None
    auth_expires_at: Optional[int] = None
    freshness_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    environment_ref: Optional[str] = None
    route_ref: Optional[str] = None
    binding_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    created_at: int = 0
    updated_at: int = 0
    released_at: Optional[int] = None
    release_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    quarantine_reason: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("prepared_attempt_id", "test_run_id", "mission_node_id", "case_id", "attempt_id", "reality_snapshot_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.state, PreparedAttemptState):
            raise PreparedAttemptError("PREPARED_ATTEMPT_STATE_INVALID")
        object.__setattr__(self, "data_refs", _refs(self.data_refs, "data_refs"))
        if not self.data_refs:
            raise PreparedAttemptError("PREPARED_ATTEMPT_REQUIRES_DATA")
        for name in ("verification_evidence_refs", "reservation_evidence_refs", "freshness_evidence_refs", "binding_evidence_refs", "release_evidence_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise PreparedAttemptError("%s_INVALID" % name.upper())
        if self.updated_at < self.created_at:
            raise PreparedAttemptError("PREPARED_ATTEMPT_TIME_REGRESSION")
        for name in ("auth_acquired_at", "auth_expires_at", "released_at"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise PreparedAttemptError("%s_INVALID" % name.upper())
        if self.auth_binding_mode is not None and self.auth_binding_mode != AuthBindingMode.FRESH_LOGIN:
            raise PreparedAttemptError("HISTORICAL_AUTH_BINDING_FORBIDDEN")

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


class PreparedAttemptRepository(Protocol):
    def get_prepared_attempt(self, prepared_attempt_id: str) -> Optional[PreparedAttempt]:
        ...

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[PreparedAttempt]:
        ...

    def current_for_case(self, test_run_id: str, case_id: str) -> Optional[PreparedAttempt]:
        ...

    def save_prepared_attempt(self, value: PreparedAttempt) -> None:
        ...


class MemoryPreparedAttemptRepository:
    def __init__(self) -> None:
        self._values: Dict[str, PreparedAttempt] = {}

    def get_prepared_attempt(self, prepared_attempt_id: str) -> Optional[PreparedAttempt]:
        return self._values.get(prepared_attempt_id)

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[PreparedAttempt]:
        matches = [
            value for value in self._values.values()
            if value.test_run_id == test_run_id
            and value.case_id == case_id
            and value.attempt_id == attempt_id
            and not value.terminal
        ]
        if len(matches) > 1:
            raise PreparedAttemptError("MULTIPLE_CURRENT_PREPARED_ATTEMPTS")
        return matches[0] if matches else None

    def current_for_case(self, test_run_id: str, case_id: str) -> Optional[PreparedAttempt]:
        matches = [
            value for value in self._values.values()
            if value.test_run_id == test_run_id
            and value.case_id == case_id
            and not value.terminal
        ]
        if len(matches) > 1:
            raise PreparedAttemptError("MULTIPLE_CURRENT_CASE_ATTEMPTS")
        return matches[0] if matches else None

    def save_prepared_attempt(self, value: PreparedAttempt) -> None:
        if not isinstance(value, PreparedAttempt):
            raise PreparedAttemptError("PREPARED_ATTEMPT_REQUIRED")
        history = [
            item for item in self._values.values()
            if item.test_run_id == value.test_run_id
            and item.case_id == value.case_id
            and item.attempt_id == value.attempt_id
            and item.prepared_attempt_id != value.prepared_attempt_id
        ]
        if history:
            if any(not item.terminal for item in history) and not value.terminal:
                raise PreparedAttemptError("CURRENT_PREPARED_ATTEMPT_ALREADY_EXISTS")
            raise PreparedAttemptError("RETRY_REQUIRES_NEW_ATTEMPT_IDENTITY")
        current_case = self.current_for_case(value.test_run_id, value.case_id)
        if (
            current_case is not None
            and current_case.prepared_attempt_id != value.prepared_attempt_id
            and not value.terminal
        ):
            raise PreparedAttemptError("CURRENT_CASE_ATTEMPT_ALREADY_EXISTS")
        self._values[value.prepared_attempt_id] = value


class CenterPreparedAttemptService:
    """Center-owned N5 lifecycle. Workers provide evidence, not preparation truth."""

    def __init__(self, repository: PreparedAttemptRepository, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.now_fn = now_fn or (lambda: int(time.time()))

    def select(self, *, prepared_attempt_id: str, test_run_id: str, mission_node_id: str, case_id: str, attempt_id: str, reality_snapshot_id: str, data_refs: Sequence[str]) -> PreparedAttempt:
        now = int(self.now_fn())
        existing = self.repository.get_prepared_attempt(prepared_attempt_id)
        if existing is not None:
            return existing
        current_case = self.repository.current_for_case(test_run_id, case_id)
        if current_case is not None:
            if current_case.attempt_id == attempt_id:
                raise PreparedAttemptError("CURRENT_PREPARED_ATTEMPT_ALREADY_EXISTS")
            raise PreparedAttemptError("CURRENT_CASE_ATTEMPT_ALREADY_EXISTS")
        value = PreparedAttempt(prepared_attempt_id=prepared_attempt_id, test_run_id=test_run_id, mission_node_id=mission_node_id, case_id=case_id, attempt_id=attempt_id, reality_snapshot_id=reality_snapshot_id, data_refs=tuple(data_refs), created_at=now, updated_at=now)
        self.repository.save_prepared_attempt(value)
        return value

    def current_for_case(self, *, test_run_id: str, case_id: str) -> Optional[PreparedAttempt]:
        return self.repository.current_for_case(_required(test_run_id, "test_run_id"), _required(case_id, "case_id"))

    def verify(self, prepared_attempt_id: str, *, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._require_state(prepared_attempt_id, PreparedAttemptState.SELECTED)
        evidence = _refs(evidence_refs, "verification_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_VERIFY_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=PreparedAttemptState.VERIFIED, verification_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def reserve(self, prepared_attempt_id: str, *, reservation_ref: str, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._require_state(prepared_attempt_id, PreparedAttemptState.VERIFIED)
        evidence = _refs(evidence_refs, "reservation_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_RESERVE_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=PreparedAttemptState.RESERVED, reservation_ref=_required(reservation_ref, "reservation_ref"), reservation_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def freshness_check(self, prepared_attempt_id: str, *, data_freshness_ref: str, auth_session_ref: str, auth_acquired_at: int, auth_expires_at: int, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._require_state(prepared_attempt_id, PreparedAttemptState.RESERVED)
        now = int(self.now_fn())
        if not isinstance(auth_acquired_at, int) or auth_acquired_at < 0 or auth_acquired_at > now:
            raise PreparedAttemptError("FRESH_AUTH_ACQUIRED_AT_INVALID")
        if not isinstance(auth_expires_at, int) or auth_expires_at <= now:
            raise PreparedAttemptError("FRESH_AUTH_ALREADY_EXPIRED")
        evidence = _refs(evidence_refs, "freshness_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_FRESHNESS_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=PreparedAttemptState.FRESH, data_freshness_ref=_required(data_freshness_ref, "data_freshness_ref"), auth_session_ref=_required(auth_session_ref, "auth_session_ref"), auth_binding_mode=AuthBindingMode.FRESH_LOGIN, auth_acquired_at=auth_acquired_at, auth_expires_at=auth_expires_at, freshness_evidence_refs=evidence, updated_at=now))

    def bind(self, prepared_attempt_id: str, *, environment_ref: str, route_ref: str, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._require_state(prepared_attempt_id, PreparedAttemptState.FRESH)
        now = int(self.now_fn())
        if current.auth_expires_at is None or current.auth_expires_at <= now:
            raise PreparedAttemptError("FRESH_AUTH_EXPIRED_BEFORE_BIND")
        evidence = _refs(evidence_refs, "binding_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_BIND_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=PreparedAttemptState.PREPARED, environment_ref=_required(environment_ref, "environment_ref"), route_ref=_required(route_ref, "route_ref"), binding_evidence_refs=evidence, updated_at=now))

    def require_current_for_execution(self, *, prepared_attempt_id: str, test_run_id: str, case_id: str, attempt_id: str) -> PreparedAttempt:
        current = self.repository.current_for_attempt(test_run_id, case_id, attempt_id)
        if current is None:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_CURRENT_PREPARED_ATTEMPT")
        if current.prepared_attempt_id != prepared_attempt_id:
            raise PreparedAttemptError("TEST_EXECUTION_PREPARED_ATTEMPT_MISMATCH")
        if current.state != PreparedAttemptState.PREPARED:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_PREPARED_STATE")
        now = int(self.now_fn())
        if current.auth_binding_mode != AuthBindingMode.FRESH_LOGIN:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_FRESH_AUTH")
        if current.auth_expires_at is None or current.auth_expires_at <= now:
            raise PreparedAttemptError("TEST_EXECUTION_FRESH_AUTH_EXPIRED")
        if not current.reservation_ref:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_RESERVATION")
        if not current.data_freshness_ref:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_DATA_FRESHNESS")
        if not current.environment_ref or not current.route_ref:
            raise PreparedAttemptError("TEST_EXECUTION_REQUIRES_ENVIRONMENT_AND_ROUTE")
        return current

    def release(self, prepared_attempt_id: str, *, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._get(prepared_attempt_id)
        if current.terminal:
            return current
        evidence = _refs(evidence_refs, "release_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_RELEASE_REQUIRES_EVIDENCE")
        now = int(self.now_fn())
        return self._save(replace(current, state=PreparedAttemptState.RELEASED, released_at=now, release_evidence_refs=evidence, updated_at=now))

    def quarantine(self, prepared_attempt_id: str, *, reason: str, evidence_refs: Sequence[str]) -> PreparedAttempt:
        current = self._get(prepared_attempt_id)
        if current.terminal:
            return current
        evidence = _refs(evidence_refs, "release_evidence_refs")
        if not evidence:
            raise PreparedAttemptError("PREPARED_ATTEMPT_QUARANTINE_REQUIRES_EVIDENCE")
        now = int(self.now_fn())
        return self._save(replace(current, state=PreparedAttemptState.QUARANTINED, released_at=now, release_evidence_refs=evidence, quarantine_reason=_required(reason, "quarantine_reason"), updated_at=now))

    def _get(self, prepared_attempt_id: str) -> PreparedAttempt:
        value = self.repository.get_prepared_attempt(_required(prepared_attempt_id, "prepared_attempt_id"))
        if value is None:
            raise PreparedAttemptError("PREPARED_ATTEMPT_NOT_FOUND")
        return value

    def _require_state(self, prepared_attempt_id: str, expected: PreparedAttemptState) -> PreparedAttempt:
        value = self._get(prepared_attempt_id)
        if value.state != expected:
            raise PreparedAttemptError("PREPARED_ATTEMPT_STATE_REQUIRED:%s" % expected.value)
        return value

    def _save(self, value: PreparedAttempt) -> PreparedAttempt:
        self.repository.save_prepared_attempt(value)
        return value
