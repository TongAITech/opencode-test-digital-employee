"""RC8 coverage observations with execution/snapshot provenance."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .contracts import RC8ContractError
from .governance import CoverageMetric


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values, name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


@dataclass(frozen=True)
class CoverageObservation:
    observation_id: str
    test_run_id: str
    stage_instance_id: str
    subject_ref: str
    source_snapshot_ref: str
    metric: CoverageMetric
    attempt_id: Optional[str] = None
    case_id: Optional[str] = None
    source_tool: Optional[str] = None
    artifact_refs: Tuple[str, ...] = field(default_factory=tuple)
    observed_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "test_run_id",
            "stage_instance_id",
            "subject_ref",
            "source_snapshot_ref",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.metric, CoverageMetric):
            raise RC8ContractError("COVERAGE_OBSERVATION_METRIC_REQUIRED")
        for name in ("attempt_id", "case_id", "source_tool"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        object.__setattr__(self, "artifact_refs", _refs(self.artifact_refs, "artifact_refs"))
        if not self.artifact_refs:
            raise RC8ContractError("COVERAGE_OBSERVATION_REQUIRES_ARTIFACT")
        # Zero denominator is UNKNOWN, never 100%. Runtime observations reject
        # it so legacy CoverageMetric.ratio cannot fabricate sufficiency.
        if self.metric.total <= 0:
            raise RC8ContractError("COVERAGE_OBSERVATION_ZERO_DENOMINATOR_FORBIDDEN")
        # The metric itself must point to evidence and the observation must bind
        # the same fact to a concrete run/snapshot/attempt scope.
        if not self.metric.evidence_refs:
            raise RC8ContractError("COVERAGE_OBSERVATION_METRIC_EVIDENCE_REQUIRED")
