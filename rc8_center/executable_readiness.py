"""RC8 N6 Executable Readiness contract.

N6 consumes a frozen case plus the exact current N5 PreparedAttempt and produces
an executable specification: driver/script, fixture bindings, business
assertions and evidence collectors. Technical build/readiness never means a
business test PASS.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple

from .prepared_attempt import CenterPreparedAttemptService, PreparedAttemptError


class ExecutableReadinessError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutableReadinessError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ExecutableReadinessError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ExecutableReadinessError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class ExecutableReadinessState(str, Enum):
    BUILT = "BUILT"
    VERIFIED = "VERIFIED"
    READY = "READY"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ExecutableSpec:
    executable_spec_id: str
    test_run_id: str
    mission_node_id: str
    case_id: str
    attempt_id: str
    prepared_attempt_id: str
    frozen_case_ref: str
    driver_ref: str
    script_artifact_ref: str
    fixture_binding_refs: Tuple[str, ...]
    assertion_refs: Tuple[str, ...]
    evidence_collector_refs: Tuple[str, ...]
    build_evidence_refs: Tuple[str, ...]
    semantic_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    state: ExecutableReadinessState = ExecutableReadinessState.BUILT
    created_at: int = 0
    updated_at: int = 0
    invalidation_reason: Optional[str] = None
    invalidation_evidence_refs: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("executable_spec_id", "test_run_id", "mission_node_id", "case_id", "attempt_id", "prepared_attempt_id", "frozen_case_ref", "driver_ref", "script_artifact_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.state, ExecutableReadinessState):
            raise ExecutableReadinessError("EXECUTABLE_READINESS_STATE_INVALID")
        for name in ("fixture_binding_refs", "assertion_refs", "evidence_collector_refs", "build_evidence_refs", "semantic_evidence_refs", "invalidation_evidence_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if not self.fixture_binding_refs:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRES_FIXTURE_BINDINGS")
        if not self.assertion_refs:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRES_ASSERTIONS")
        if not self.evidence_collector_refs:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRES_EVIDENCE_COLLECTORS")
        if not self.build_evidence_refs:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRES_BUILD_EVIDENCE")
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ExecutableReadinessError("%s_INVALID" % name.upper())
        if self.updated_at < self.created_at:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_TIME_REGRESSION")


class ExecutableSpecRepository(Protocol):
    def get_executable_spec(self, executable_spec_id: str) -> Optional[ExecutableSpec]:
        ...

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[ExecutableSpec]:
        ...

    def save_executable_spec(self, value: ExecutableSpec) -> None:
        ...


class MemoryExecutableSpecRepository:
    def __init__(self) -> None:
        self._values: Dict[str, ExecutableSpec] = {}

    def get_executable_spec(self, executable_spec_id: str) -> Optional[ExecutableSpec]:
        return self._values.get(executable_spec_id)

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[ExecutableSpec]:
        values = [value for value in self._values.values() if value.test_run_id == test_run_id and value.case_id == case_id and value.attempt_id == attempt_id and value.state != ExecutableReadinessState.INVALIDATED]
        if len(values) > 1:
            raise ExecutableReadinessError("MULTIPLE_CURRENT_EXECUTABLE_SPECS")
        return values[0] if values else None

    def save_executable_spec(self, value: ExecutableSpec) -> None:
        if not isinstance(value, ExecutableSpec):
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRED")
        current = self.current_for_attempt(value.test_run_id, value.case_id, value.attempt_id)
        if current is not None and current.executable_spec_id != value.executable_spec_id and value.state != ExecutableReadinessState.INVALIDATED:
            raise ExecutableReadinessError("CURRENT_EXECUTABLE_SPEC_ALREADY_EXISTS")
        self._values[value.executable_spec_id] = value


class CenterExecutableReadinessService:
    def __init__(self, repository: ExecutableSpecRepository, prepared_attempts: CenterPreparedAttemptService, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.prepared_attempts = prepared_attempts
        self.now_fn = now_fn or (lambda: int(time.time()))

    def build(self, *, executable_spec_id: str, test_run_id: str, mission_node_id: str, case_id: str, attempt_id: str, prepared_attempt_id: str, frozen_case_ref: str, driver_ref: str, script_artifact_ref: str, fixture_binding_refs: Sequence[str], assertion_refs: Sequence[str], evidence_collector_refs: Sequence[str], build_evidence_refs: Sequence[str]) -> ExecutableSpec:
        self._require_prepared(prepared_attempt_id, test_run_id, case_id, attempt_id)
        existing = self.repository.get_executable_spec(executable_spec_id)
        if existing is not None:
            return existing
        if self.repository.current_for_attempt(test_run_id, case_id, attempt_id) is not None:
            raise ExecutableReadinessError("CURRENT_EXECUTABLE_SPEC_ALREADY_EXISTS")
        now = int(self.now_fn())
        value = ExecutableSpec(executable_spec_id=executable_spec_id, test_run_id=test_run_id, mission_node_id=mission_node_id, case_id=case_id, attempt_id=attempt_id, prepared_attempt_id=prepared_attempt_id, frozen_case_ref=frozen_case_ref, driver_ref=driver_ref, script_artifact_ref=script_artifact_ref, fixture_binding_refs=tuple(fixture_binding_refs), assertion_refs=tuple(assertion_refs), evidence_collector_refs=tuple(evidence_collector_refs), build_evidence_refs=tuple(build_evidence_refs), created_at=now, updated_at=now)
        self.repository.save_executable_spec(value)
        return value

    def verify(self, executable_spec_id: str, *, semantic_evidence_refs: Sequence[str]) -> ExecutableSpec:
        current = self._require_state(executable_spec_id, ExecutableReadinessState.BUILT)
        self._require_prepared(current.prepared_attempt_id, current.test_run_id, current.case_id, current.attempt_id)
        evidence = _refs(semantic_evidence_refs, "semantic_evidence_refs")
        if not evidence:
            raise ExecutableReadinessError("EXECUTABLE_SEMANTIC_VERIFICATION_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=ExecutableReadinessState.VERIFIED, semantic_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def mark_ready(self, executable_spec_id: str) -> ExecutableSpec:
        current = self._require_state(executable_spec_id, ExecutableReadinessState.VERIFIED)
        self._require_prepared(current.prepared_attempt_id, current.test_run_id, current.case_id, current.attempt_id)
        return self._save(replace(current, state=ExecutableReadinessState.READY, updated_at=int(self.now_fn())))

    def require_ready_for_execution(self, *, executable_spec_id: str, prepared_attempt_id: str, test_run_id: str, case_id: str, attempt_id: str) -> ExecutableSpec:
        current = self.repository.current_for_attempt(test_run_id, case_id, attempt_id)
        if current is None or current.executable_spec_id != executable_spec_id:
            raise ExecutableReadinessError("TEST_EXECUTION_REQUIRES_CURRENT_EXECUTABLE_SPEC")
        if current.state != ExecutableReadinessState.READY:
            raise ExecutableReadinessError("TEST_EXECUTION_REQUIRES_EXECUTABLE_READY")
        if current.prepared_attempt_id != prepared_attempt_id:
            raise ExecutableReadinessError("EXECUTABLE_PREPARED_ATTEMPT_MISMATCH")
        self._require_prepared(prepared_attempt_id, test_run_id, case_id, attempt_id)
        return current

    def invalidate(self, executable_spec_id: str, *, reason: str, evidence_refs: Sequence[str]) -> ExecutableSpec:
        current = self._get(executable_spec_id)
        evidence = _refs(evidence_refs, "invalidation_evidence_refs")
        if not evidence:
            raise ExecutableReadinessError("EXECUTABLE_INVALIDATION_REQUIRES_EVIDENCE")
        return self._save(replace(current, state=ExecutableReadinessState.INVALIDATED, invalidation_reason=_required(reason, "invalidation_reason"), invalidation_evidence_refs=evidence, updated_at=int(self.now_fn())))

    def _require_prepared(self, prepared_attempt_id: str, test_run_id: str, case_id: str, attempt_id: str) -> None:
        try:
            self.prepared_attempts.require_current_for_execution(prepared_attempt_id=prepared_attempt_id, test_run_id=test_run_id, case_id=case_id, attempt_id=attempt_id)
        except PreparedAttemptError as exc:
            raise ExecutableReadinessError("N6_REQUIRES_N5_PREPARED_ATTEMPT:%s" % exc) from exc

    def _get(self, executable_spec_id: str) -> ExecutableSpec:
        value = self.repository.get_executable_spec(_required(executable_spec_id, "executable_spec_id"))
        if value is None:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_NOT_FOUND")
        return value

    def _require_state(self, executable_spec_id: str, expected: ExecutableReadinessState) -> ExecutableSpec:
        value = self._get(executable_spec_id)
        if value.state != expected:
            raise ExecutableReadinessError("EXECUTABLE_SPEC_STATE_REQUIRED:%s" % expected.value)
        return value

    def _save(self, value: ExecutableSpec) -> ExecutableSpec:
        self.repository.save_executable_spec(value)
        return value
