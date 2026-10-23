"""RC8 deterministic, fail-closed sufficiency evaluation.

The Center freezes the denominator before a Worker can assess it. Workers may
supply candidate assessments and evidence, but they cannot shrink the required
set or decide the final SUFFICIENT result.

Python 3.8 compatible for the target bank runtime.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

from .contracts import RC8ContractError
from .governance import CoverageDimension, StatusScope, SufficiencyEvaluation, SufficiencyResult


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


class DimensionState(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class RequiredDimension:
    dimension_id: str
    dimension: CoverageDimension
    source_ref: str
    critical: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension_id", _required(self.dimension_id, "dimension_id"))
        object.__setattr__(self, "source_ref", _required(self.source_ref, "source_ref"))
        if not isinstance(self.dimension, CoverageDimension):
            raise RC8ContractError("REQUIRED_DIMENSION_TYPE_INVALID")
        if not isinstance(self.critical, bool):
            raise RC8ContractError("REQUIRED_DIMENSION_CRITICAL_INVALID")


@dataclass(frozen=True)
class FrozenSufficiencyLedger:
    ledger_id: str
    test_run_id: str
    subject_id: str
    policy_version: str
    source_refs: Tuple[str, ...]
    required_dimensions: Tuple[RequiredDimension, ...]
    frozen_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("ledger_id", "test_run_id", "subject_id", "policy_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))
        if not self.source_refs:
            raise RC8ContractError("SUFFICIENCY_LEDGER_REQUIRES_SOURCE_TRUTH")
        if not isinstance(self.required_dimensions, (tuple, list)) or not self.required_dimensions:
            raise RC8ContractError("SUFFICIENCY_LEDGER_EMPTY_DENOMINATOR_FORBIDDEN")
        dimensions = tuple(self.required_dimensions)
        ids = []
        for item in dimensions:
            if not isinstance(item, RequiredDimension):
                raise RC8ContractError("SUFFICIENCY_LEDGER_DIMENSION_INVALID")
            ids.append(item.dimension_id)
        if len(set(ids)) != len(ids):
            raise RC8ContractError("SUFFICIENCY_LEDGER_DUPLICATE_DIMENSION")
        object.__setattr__(self, "required_dimensions", dimensions)


@dataclass(frozen=True)
class DimensionAssessment:
    dimension_id: str
    state: DimensionState
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension_id", _required(self.dimension_id, "dimension_id"))
        if not isinstance(self.state, DimensionState):
            raise RC8ContractError("DIMENSION_ASSESSMENT_STATE_INVALID")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        reason = self.reason.strip() if isinstance(self.reason, str) else ""
        object.__setattr__(self, "reason", reason)
        if self.state == DimensionState.SATISFIED and not self.evidence_refs:
            raise RC8ContractError("SATISFIED_DIMENSION_REQUIRES_EVIDENCE")
        if self.state == DimensionState.NOT_APPLICABLE:
            if not self.evidence_refs or not reason:
                raise RC8ContractError("NOT_APPLICABLE_REQUIRES_REASON_AND_EVIDENCE")


@dataclass(frozen=True)
class CenterSufficiencyDecision:
    ledger_id: str
    test_run_id: str
    subject_id: str
    evaluator_id: str
    policy_version: str
    result: SufficiencyResult
    assessments: Tuple[DimensionAssessment, ...]
    active_gap_ids: Tuple[str, ...]
    worker_claimed_sufficient: Optional[bool]
    evaluated_at: int = field(default_factory=_now)

    @property
    def required_total(self) -> int:
        return len(self.assessments)

    @property
    def satisfied_total(self) -> int:
        return sum(1 for item in self.assessments if item.state == DimensionState.SATISFIED)

    @property
    def not_applicable_total(self) -> int:
        return sum(1 for item in self.assessments if item.state == DimensionState.NOT_APPLICABLE)

    @property
    def unknown_total(self) -> int:
        return sum(1 for item in self.assessments if item.state == DimensionState.UNKNOWN)

    @property
    def unsatisfied_total(self) -> int:
        return sum(1 for item in self.assessments if item.state == DimensionState.UNSATISFIED)

    @property
    def effective_ratio(self) -> float:
        # A frozen ledger can never be empty. Keep fail-closed semantics anyway.
        if self.required_total <= 0:
            return 0.0
        return float(self.satisfied_total + self.not_applicable_total) / float(self.required_total)

    def to_evaluation(self, evaluation_id: str) -> SufficiencyEvaluation:
        evidence = []
        satisfied = []
        unsatisfied = []
        for item in self.assessments:
            evidence.extend(item.evidence_refs)
            if item.state in {DimensionState.SATISFIED, DimensionState.NOT_APPLICABLE}:
                satisfied.append(item.dimension_id)
            else:
                unsatisfied.append(item.dimension_id)
        # UNKNOWN still needs a durable audit reference even when the Worker
        # supplied no evidence. The ledger is the Center-owned proof of the
        # frozen denominator and missing assessment.
        evidence.append("ledger:%s" % self.ledger_id)
        return SufficiencyEvaluation(
            evaluation_id=_required(evaluation_id, "evaluation_id"),
            test_run_id=self.test_run_id,
            scope=StatusScope.STAGE,
            subject_id=self.subject_id,
            evaluator_id=self.evaluator_id,
            policy_version="center-ledger:%s" % self.policy_version,
            result=self.result,
            dimension_refs=tuple(item.dimension_id for item in self.assessments),
            evidence_refs=tuple(dict.fromkeys(evidence)),
            satisfied_requirement_refs=tuple(satisfied),
            unsatisfied_requirement_refs=tuple(unsatisfied),
            unresolved_gap_ids=self.active_gap_ids,
            explanation=(
                "center deterministic ledger=%s satisfied=%s not_applicable=%s "
                "unknown=%s unsatisfied=%s active_gaps=%s worker_claim_ignored=%s"
                % (
                    self.ledger_id,
                    self.satisfied_total,
                    self.not_applicable_total,
                    self.unknown_total,
                    self.unsatisfied_total,
                    len(self.active_gap_ids),
                    self.worker_claimed_sufficient,
                )
            ),
        )


def evaluate_frozen_ledger(
    ledger: FrozenSufficiencyLedger,
    assessments: Sequence[DimensionAssessment],
    *,
    evaluator_id: str,
    active_gap_ids: Sequence[str] = (),
    worker_claimed_sufficient: Optional[bool] = None,
) -> CenterSufficiencyDecision:
    """Recompute sufficiency from the frozen Center-owned denominator.

    Missing Worker assessments are materialized as UNKNOWN. Extra or duplicate
    dimension IDs are rejected rather than silently changing the denominator.
    The optional Worker claim is retained only for audit and never influences
    the result.
    """
    if not isinstance(ledger, FrozenSufficiencyLedger):
        raise RC8ContractError("FROZEN_SUFFICIENCY_LEDGER_REQUIRED")
    evaluator = _required(evaluator_id, "evaluator_id")
    gaps = _refs(active_gap_ids, "active_gap_ids")
    if worker_claimed_sufficient is not None and not isinstance(worker_claimed_sufficient, bool):
        raise RC8ContractError("WORKER_SUFFICIENT_CLAIM_INVALID")

    by_id: Dict[str, DimensionAssessment] = {}
    for assessment in assessments:
        if not isinstance(assessment, DimensionAssessment):
            raise RC8ContractError("DIMENSION_ASSESSMENT_INVALID")
        if assessment.dimension_id in by_id:
            raise RC8ContractError("DUPLICATE_DIMENSION_ASSESSMENT")
        by_id[assessment.dimension_id] = assessment

    required_ids = {item.dimension_id for item in ledger.required_dimensions}
    extras = sorted(set(by_id) - required_ids)
    if extras:
        raise RC8ContractError("ASSESSMENT_OUTSIDE_FROZEN_LEDGER:%s" % ",".join(extras))

    normalized = []
    for required in ledger.required_dimensions:
        assessment = by_id.get(required.dimension_id)
        if assessment is None:
            assessment = DimensionAssessment(
                dimension_id=required.dimension_id,
                state=DimensionState.UNKNOWN,
                reason="missing assessment from worker",
            )
        normalized.append(assessment)

    blocking_dimension = any(
        item.state in {DimensionState.UNKNOWN, DimensionState.UNSATISFIED}
        for item in normalized
    )
    result = SufficiencyResult.SUFFICIENT
    if blocking_dimension or gaps:
        result = SufficiencyResult.INSUFFICIENT

    return CenterSufficiencyDecision(
        ledger_id=ledger.ledger_id,
        test_run_id=ledger.test_run_id,
        subject_id=ledger.subject_id,
        evaluator_id=evaluator,
        policy_version=ledger.policy_version,
        result=result,
        assessments=tuple(normalized),
        active_gap_ids=gaps,
        worker_claimed_sufficient=worker_claimed_sufficient,
    )
