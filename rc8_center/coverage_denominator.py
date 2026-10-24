"""RC8 N7 versioned coverage denominator and closure engine.

Coverage is obligation-driven, not case-count driven. A denominator snapshot is
immutable and versioned. Expansion creates a new denominator and reopens the
layer; receipts against an old snapshot never satisfy the new snapshot.
COVERED_FAIL still means the obligation was tested; product quality is decided
later and is not conflated with test sufficiency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple


class CoverageDenominatorError(ValueError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoverageDenominatorError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise CoverageDenominatorError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CoverageDenominatorError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


class CoverageObligationState(str, Enum):
    UNEXECUTED = "UNEXECUTED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COVERED_PASS = "COVERED_PASS"
    COVERED_FAIL = "COVERED_FAIL"
    BLOCKED = "BLOCKED"
    EXCLUDED_WITH_EVIDENCE = "EXCLUDED_WITH_EVIDENCE"


_RECEIPT_STATES = {
    CoverageObligationState.COVERED_PASS,
    CoverageObligationState.COVERED_FAIL,
    CoverageObligationState.BLOCKED,
    CoverageObligationState.EXCLUDED_WITH_EVIDENCE,
}
_CLOSURE_STATES = {
    CoverageObligationState.COVERED_PASS,
    CoverageObligationState.COVERED_FAIL,
    CoverageObligationState.EXCLUDED_WITH_EVIDENCE,
}


@dataclass(frozen=True)
class CoverageObligation:
    obligation_id: str
    layer: str
    subject_ref: str
    source_refs: Tuple[str, ...]
    critical: bool = False

    def __post_init__(self) -> None:
        for name in ("obligation_id", "layer", "subject_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))
        if not self.source_refs:
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_REQUIRES_SOURCE")
        if not isinstance(self.critical, bool):
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_CRITICAL_INVALID")


@dataclass(frozen=True)
class CoverageDenominatorSnapshot:
    snapshot_id: str
    test_run_id: str
    mission_node_id: str
    layer: str
    version: int
    source_revision: str
    obligations: Tuple[CoverageObligation, ...]
    created_at: int
    supersedes_snapshot_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "test_run_id", "mission_node_id", "layer", "source_revision"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.version, int) or self.version < 1:
            raise CoverageDenominatorError("COVERAGE_DENOMINATOR_VERSION_INVALID")
        if not isinstance(self.created_at, int) or self.created_at < 0:
            raise CoverageDenominatorError("COVERAGE_DENOMINATOR_TIME_INVALID")
        if not isinstance(self.obligations, (tuple, list)) or not self.obligations:
            raise CoverageDenominatorError("COVERAGE_DENOMINATOR_ZERO_FORBIDDEN")
        obligations = tuple(self.obligations)
        if any(not isinstance(value, CoverageObligation) for value in obligations):
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_INVALID")
        ids = [value.obligation_id for value in obligations]
        if len(ids) != len(set(ids)):
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_DUPLICATE")
        if any(value.layer != self.layer for value in obligations):
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_LAYER_MISMATCH")
        object.__setattr__(self, "obligations", obligations)
        if self.supersedes_snapshot_id is not None:
            object.__setattr__(self, "supersedes_snapshot_id", _required(self.supersedes_snapshot_id, "supersedes_snapshot_id"))


@dataclass(frozen=True)
class CoverageReceipt:
    receipt_id: str
    snapshot_id: str
    obligation_id: str
    state: CoverageObligationState
    evidence_refs: Tuple[str, ...]
    observed_at: int
    attempt_id: Optional[str] = None
    case_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("receipt_id", "snapshot_id", "obligation_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.state not in _RECEIPT_STATES:
            raise CoverageDenominatorError("COVERAGE_RECEIPT_STATE_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise CoverageDenominatorError("COVERAGE_RECEIPT_REQUIRES_EVIDENCE")
        if not isinstance(self.observed_at, int) or self.observed_at < 0:
            raise CoverageDenominatorError("COVERAGE_RECEIPT_TIME_INVALID")
        for name in ("attempt_id", "case_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        if self.state in {CoverageObligationState.COVERED_PASS, CoverageObligationState.COVERED_FAIL} and (not self.attempt_id or not self.case_id):
            raise CoverageDenominatorError("EXECUTED_COVERAGE_REQUIRES_CASE_ATTEMPT")


@dataclass(frozen=True)
class LayerReopen:
    reopen_id: str
    test_run_id: str
    layer: str
    previous_snapshot_id: str
    new_snapshot_id: str
    invalidated_receipt_ids: Tuple[str, ...]
    added_obligation_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    created_at: int

    def __post_init__(self) -> None:
        for name in ("reopen_id", "test_run_id", "layer", "previous_snapshot_id", "new_snapshot_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        for name in ("invalidated_receipt_ids", "added_obligation_ids", "evidence_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if not self.added_obligation_ids or not self.evidence_refs:
            raise CoverageDenominatorError("LAYER_REOPEN_REQUIRES_EXPANSION_EVIDENCE")


@dataclass(frozen=True)
class CoverageClosure:
    snapshot_id: str
    total: int
    covered_pass: int
    covered_fail: int
    excluded: int
    blocked: int
    unresolved: int
    complete: bool


class CoverageDenominatorRepository(Protocol):
    def get_snapshot(self, snapshot_id: str) -> Optional[CoverageDenominatorSnapshot]: ...
    def current_snapshot(self, test_run_id: str, layer: str) -> Optional[CoverageDenominatorSnapshot]: ...
    def save_snapshot(self, value: CoverageDenominatorSnapshot) -> None: ...
    def receipts(self, snapshot_id: str) -> Tuple[CoverageReceipt, ...]: ...
    def save_receipt(self, value: CoverageReceipt) -> None: ...
    def save_reopen(self, value: LayerReopen) -> None: ...


class MemoryCoverageDenominatorRepository:
    def __init__(self) -> None:
        self.snapshots: Dict[str, CoverageDenominatorSnapshot] = {}
        self._receipts: Dict[str, CoverageReceipt] = {}
        self.reopens: Dict[str, LayerReopen] = {}

    def get_snapshot(self, snapshot_id: str) -> Optional[CoverageDenominatorSnapshot]:
        return self.snapshots.get(snapshot_id)

    def current_snapshot(self, test_run_id: str, layer: str) -> Optional[CoverageDenominatorSnapshot]:
        values = [value for value in self.snapshots.values() if value.test_run_id == test_run_id and value.layer == layer]
        return max(values, key=lambda item: item.version) if values else None

    def save_snapshot(self, value: CoverageDenominatorSnapshot) -> None:
        existing = self.snapshots.get(value.snapshot_id)
        if existing is not None and existing != value:
            raise CoverageDenominatorError("COVERAGE_SNAPSHOT_ID_CONFLICT")
        current = self.current_snapshot(value.test_run_id, value.layer)
        if existing is None:
            expected = 1 if current is None else current.version + 1
            if value.version != expected:
                raise CoverageDenominatorError("COVERAGE_SNAPSHOT_VERSION_NON_MONOTONIC")
        self.snapshots[value.snapshot_id] = value

    def receipts(self, snapshot_id: str) -> Tuple[CoverageReceipt, ...]:
        return tuple(value for value in self._receipts.values() if value.snapshot_id == snapshot_id)

    def save_receipt(self, value: CoverageReceipt) -> None:
        existing = self._receipts.get(value.receipt_id)
        if existing is not None and existing != value:
            raise CoverageDenominatorError("COVERAGE_RECEIPT_ID_CONFLICT")
        for receipt in self.receipts(value.snapshot_id):
            if receipt.obligation_id == value.obligation_id and receipt.receipt_id != value.receipt_id:
                raise CoverageDenominatorError("COVERAGE_OBLIGATION_ALREADY_RECEIPTED")
        self._receipts[value.receipt_id] = value

    def save_reopen(self, value: LayerReopen) -> None:
        existing = self.reopens.get(value.reopen_id)
        if existing is not None and existing != value:
            raise CoverageDenominatorError("LAYER_REOPEN_ID_CONFLICT")
        self.reopens[value.reopen_id] = value


class CenterCoverageDenominatorService:
    def __init__(self, repository: CoverageDenominatorRepository, *, now_fn: Optional[Callable[[], int]] = None) -> None:
        self.repository = repository
        self.now_fn = now_fn or (lambda: int(time.time()))

    def freeze(self, *, snapshot_id: str, test_run_id: str, mission_node_id: str, layer: str, source_revision: str, obligations: Sequence[CoverageObligation]) -> CoverageDenominatorSnapshot:
        current = self.repository.current_snapshot(test_run_id, layer)
        version = 1 if current is None else current.version + 1
        value = CoverageDenominatorSnapshot(snapshot_id=snapshot_id, test_run_id=test_run_id, mission_node_id=mission_node_id, layer=layer, version=version, source_revision=source_revision, obligations=tuple(obligations), created_at=int(self.now_fn()), supersedes_snapshot_id=current.snapshot_id if current else None)
        self.repository.save_snapshot(value)
        return value

    def record(self, *, receipt_id: str, snapshot_id: str, obligation_id: str, state: CoverageObligationState, evidence_refs: Sequence[str], attempt_id: Optional[str] = None, case_id: Optional[str] = None) -> CoverageReceipt:
        snapshot = self._require_current(snapshot_id)
        if obligation_id not in {value.obligation_id for value in snapshot.obligations}:
            raise CoverageDenominatorError("COVERAGE_OBLIGATION_NOT_IN_DENOMINATOR")
        value = CoverageReceipt(receipt_id=receipt_id, snapshot_id=snapshot_id, obligation_id=obligation_id, state=state, evidence_refs=tuple(evidence_refs), observed_at=int(self.now_fn()), attempt_id=attempt_id, case_id=case_id)
        self.repository.save_receipt(value)
        return value

    def closure(self, snapshot_id: str) -> CoverageClosure:
        snapshot = self._require_current(snapshot_id)
        receipts = {value.obligation_id: value for value in self.repository.receipts(snapshot_id)}
        states = [receipts.get(item.obligation_id).state if item.obligation_id in receipts else CoverageObligationState.UNEXECUTED for item in snapshot.obligations]
        covered_pass = sum(1 for value in states if value == CoverageObligationState.COVERED_PASS)
        covered_fail = sum(1 for value in states if value == CoverageObligationState.COVERED_FAIL)
        excluded = sum(1 for value in states if value == CoverageObligationState.EXCLUDED_WITH_EVIDENCE)
        blocked = sum(1 for value in states if value == CoverageObligationState.BLOCKED)
        unresolved = sum(1 for value in states if value not in _CLOSURE_STATES and value != CoverageObligationState.BLOCKED)
        complete = all(value in _CLOSURE_STATES for value in states)
        return CoverageClosure(snapshot_id=snapshot_id, total=len(states), covered_pass=covered_pass, covered_fail=covered_fail, excluded=excluded, blocked=blocked, unresolved=unresolved, complete=complete)

    def expand(self, *, new_snapshot_id: str, previous_snapshot_id: str, added_obligations: Sequence[CoverageObligation], reopen_id: str, evidence_refs: Sequence[str]) -> Tuple[CoverageDenominatorSnapshot, LayerReopen]:
        previous = self._require_current(previous_snapshot_id)
        added = tuple(added_obligations)
        if not added:
            raise CoverageDenominatorError("COVERAGE_EXPANSION_REQUIRES_OBLIGATIONS")
        existing_ids = {value.obligation_id for value in previous.obligations}
        if any(value.obligation_id in existing_ids for value in added):
            raise CoverageDenominatorError("COVERAGE_EXPANSION_DUPLICATES_EXISTING_OBLIGATION")
        new_snapshot = self.freeze(snapshot_id=new_snapshot_id, test_run_id=previous.test_run_id, mission_node_id=previous.mission_node_id, layer=previous.layer, source_revision=previous.source_revision, obligations=previous.obligations + added)
        old_receipts = self.repository.receipts(previous.snapshot_id)
        reopen = LayerReopen(reopen_id=reopen_id, test_run_id=previous.test_run_id, layer=previous.layer, previous_snapshot_id=previous.snapshot_id, new_snapshot_id=new_snapshot.snapshot_id, invalidated_receipt_ids=tuple(value.receipt_id for value in old_receipts), added_obligation_ids=tuple(value.obligation_id for value in added), evidence_refs=tuple(evidence_refs), created_at=int(self.now_fn()))
        self.repository.save_reopen(reopen)
        return new_snapshot, reopen

    def _require_current(self, snapshot_id: str) -> CoverageDenominatorSnapshot:
        snapshot = self.repository.get_snapshot(_required(snapshot_id, "snapshot_id"))
        if snapshot is None:
            raise CoverageDenominatorError("COVERAGE_SNAPSHOT_NOT_FOUND")
        current = self.repository.current_snapshot(snapshot.test_run_id, snapshot.layer)
        if current is None or current.snapshot_id != snapshot.snapshot_id:
            raise CoverageDenominatorError("STALE_COVERAGE_DENOMINATOR_FORBIDDEN")
        return snapshot
