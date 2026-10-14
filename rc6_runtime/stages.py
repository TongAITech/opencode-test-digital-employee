from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


class StageViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class StageRule:
    name: str
    required_gates: tuple


class StageMachine:
    """Fail-closed mission stage machine."""

    RULES: List[StageRule] = [
        StageRule("REGISTERED", ()),
        StageRule("REQUIREMENT_ANALYSIS", ("MISSION_REGISTERED",)),
        StageRule("CODE_ANALYSIS", ("REQUIREMENT_SUFFICIENT",)),
        StageRule("FUSION", ("REQUIREMENT_SUFFICIENT", "CODE_SUFFICIENT")),
        StageRule("TEST_DESIGN", ("FUSION_COMPLETE",)),
        StageRule("PREPARATION", ("DESIGN_SUFFICIENT", "ORACLE_SUFFICIENT", "PROJECTION_INTEGRITY", "TARGET_IDENTITY_READY")),
        StageRule("EXECUTION", ("PREPARATION_READY",)),
        StageRule("COVERAGE_CLOSURE", ("EXECUTION_INTEGRITY",)),
        StageRule("REPORTING", ("COVERAGE_SUFFICIENT",)),
        StageRule("COMPLETE", ("REPORT_COMPLETE",)),
    ]

    def __init__(self):
        self._index = {rule.name: i for i, rule in enumerate(self.RULES)}

    def can_enter(self, stage: str, passed_gates: Iterable[str]) -> bool:
        if stage not in self._index:
            return False
        required = set(self.RULES[self._index[stage]].required_gates)
        return required.issubset(set(passed_gates))

    def enter(self, current_stage: str, target_stage: str, passed_gates: Iterable[str]) -> str:
        if current_stage not in self._index or target_stage not in self._index:
            raise StageViolation("UNKNOWN_STAGE")
        if self._index[target_stage] != self._index[current_stage] + 1:
            raise StageViolation("NON_SEQUENTIAL_STAGE_TRANSITION")
        if not self.can_enter(target_stage, passed_gates):
            raise StageViolation("REQUIRED_GATE_NOT_PASSED")
        return target_stage
