"""RC7.1 exhaustive coverage hard gate.

This gate encodes the field acceptance contract that execution activity is not
sufficient by itself.  Mission completion requires every designed case to be
accounted for, exhaustive changed-code coverage, real E2E execution for
critical/high paths, and professional-tool/UI evidence where the layer
requires it.

The gate is intentionally deterministic and contains no model judgement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Gap, GapSeverity


class ExhaustiveCoverageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExhaustiveCoverageSnapshot:
    mission_id: str
    snapshot_ref: str
    evidence_refs: Tuple[str, ...]

    designed_cases_total: int = 0
    terminal_cases_accounted: int = 0
    unaccounted_case_refs: Tuple[str, ...] = ()

    changed_executable_lines_total: int = 0
    changed_executable_lines_covered: int = 0
    uncovered_changed_line_refs: Tuple[str, ...] = ()

    changed_branches_total: int = 0
    changed_branches_covered: int = 0
    uncovered_changed_branch_refs: Tuple[str, ...] = ()

    critical_conditions_total: int = 0
    critical_conditions_covered: int = 0
    uncovered_critical_condition_refs: Tuple[str, ...] = ()

    l4_ui_cases_requiring_evidence: int = 0
    l4_ui_cases_with_complete_evidence: int = 0
    l4_missing_evidence_case_refs: Tuple[str, ...] = ()

    l5_critical_high_e2e_total: int = 0
    l5_critical_high_e2e_executed: int = 0
    l5_unexecuted_e2e_refs: Tuple[str, ...] = ()

    l6_professional_cases_total: int = 0
    l6_k6_verified: int = 0
    l6_missing_k6_refs: Tuple[str, ...] = ()

    l7_professional_cases_total: int = 0
    l7_zap_verified: int = 0
    l7_missing_zap_refs: Tuple[str, ...] = ()

    open_critical_gap_refs: Tuple[str, ...] = ()
    open_high_gap_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.mission_id or not self.snapshot_ref or not self.evidence_refs:
            raise ExhaustiveCoverageError("MISSION_SNAPSHOT_AND_EVIDENCE_REQUIRED")
        self._validate_counter("DESIGNED_CASES", self.designed_cases_total, self.terminal_cases_accounted, self.unaccounted_case_refs)
        self._validate_counter("CHANGED_LINES", self.changed_executable_lines_total, self.changed_executable_lines_covered, self.uncovered_changed_line_refs)
        self._validate_counter("CHANGED_BRANCHES", self.changed_branches_total, self.changed_branches_covered, self.uncovered_changed_branch_refs)
        self._validate_counter("CRITICAL_CONDITIONS", self.critical_conditions_total, self.critical_conditions_covered, self.uncovered_critical_condition_refs)
        self._validate_counter("L4_UI_EVIDENCE", self.l4_ui_cases_requiring_evidence, self.l4_ui_cases_with_complete_evidence, self.l4_missing_evidence_case_refs)
        self._validate_counter("L5_E2E", self.l5_critical_high_e2e_total, self.l5_critical_high_e2e_executed, self.l5_unexecuted_e2e_refs)
        self._validate_counter("L6_K6", self.l6_professional_cases_total, self.l6_k6_verified, self.l6_missing_k6_refs)
        self._validate_counter("L7_ZAP", self.l7_professional_cases_total, self.l7_zap_verified, self.l7_missing_zap_refs)

    @staticmethod
    def _validate_counter(name: str, total: int, complete: int, missing_refs: Tuple[str, ...]) -> None:
        if not isinstance(total, int) or not isinstance(complete, int) or total < 0 or complete < 0 or complete > total:
            raise ExhaustiveCoverageError("%s_COUNTER_INVALID" % name)
        if len(missing_refs) != total - complete:
            raise ExhaustiveCoverageError("%s_MISSING_REF_COUNT_MISMATCH" % name)


@dataclass(frozen=True)
class ExhaustiveCoverageResult:
    passed: bool
    state: str
    gaps: Tuple[Gap, ...]
    metrics: Dict[str, float]


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class ExhaustiveCoverageGate:
    """Fail closed unless the exhaustive acceptance contract is satisfied."""

    def evaluate(self, snapshot: ExhaustiveCoverageSnapshot) -> ExhaustiveCoverageResult:
        gaps: List[Gap] = []

        self._append_many(gaps, snapshot, "EXECUTION_ACCOUNTING_INCOMPLETE", "EXECUTION", GapSeverity.CRITICAL, snapshot.unaccounted_case_refs)
        self._append_many(gaps, snapshot, "CHANGED_LINE_COVERAGE_INCOMPLETE", "EXECUTION", GapSeverity.CRITICAL, snapshot.uncovered_changed_line_refs)
        self._append_many(gaps, snapshot, "CHANGED_BRANCH_COVERAGE_INCOMPLETE", "EXECUTION", GapSeverity.CRITICAL, snapshot.uncovered_changed_branch_refs)
        self._append_many(gaps, snapshot, "CRITICAL_CONDITION_COVERAGE_INCOMPLETE", "EXECUTION", GapSeverity.CRITICAL, snapshot.uncovered_critical_condition_refs)
        self._append_many(gaps, snapshot, "L4_UI_EVIDENCE_INCOMPLETE", "EXECUTION", GapSeverity.HIGH, snapshot.l4_missing_evidence_case_refs)
        self._append_many(gaps, snapshot, "L5_E2E_NOT_EXECUTED", "EXECUTION", GapSeverity.CRITICAL, snapshot.l5_unexecuted_e2e_refs)
        self._append_many(gaps, snapshot, "L6_K6_EVIDENCE_MISSING", "EXECUTION", GapSeverity.HIGH, snapshot.l6_missing_k6_refs)
        self._append_many(gaps, snapshot, "L7_ZAP_EVIDENCE_MISSING", "EXECUTION", GapSeverity.HIGH, snapshot.l7_missing_zap_refs)
        self._append_many(gaps, snapshot, "OPEN_CRITICAL_COVERAGE_GAP", "TEST_DESIGN", GapSeverity.CRITICAL, snapshot.open_critical_gap_refs)
        self._append_many(gaps, snapshot, "OPEN_HIGH_COVERAGE_GAP", "TEST_DESIGN", GapSeverity.HIGH, snapshot.open_high_gap_refs)

        metrics = {
            "execution_accounting": self._ratio(snapshot.terminal_cases_accounted, snapshot.designed_cases_total),
            "changed_line_coverage": self._ratio(snapshot.changed_executable_lines_covered, snapshot.changed_executable_lines_total),
            "changed_branch_coverage": self._ratio(snapshot.changed_branches_covered, snapshot.changed_branches_total),
            "critical_condition_coverage": self._ratio(snapshot.critical_conditions_covered, snapshot.critical_conditions_total),
            "l4_complete_evidence": self._ratio(snapshot.l4_ui_cases_with_complete_evidence, snapshot.l4_ui_cases_requiring_evidence),
            "l5_critical_high_e2e": self._ratio(snapshot.l5_critical_high_e2e_executed, snapshot.l5_critical_high_e2e_total),
            "l6_k6_verified": self._ratio(snapshot.l6_k6_verified, snapshot.l6_professional_cases_total),
            "l7_zap_verified": self._ratio(snapshot.l7_zap_verified, snapshot.l7_professional_cases_total),
            "open_critical_gaps": float(len(snapshot.open_critical_gap_refs)),
            "open_high_gaps": float(len(snapshot.open_high_gap_refs)),
        }
        return ExhaustiveCoverageResult(
            passed=not gaps,
            state="EXHAUSTIVE_COVERAGE_PASS" if not gaps else "EXHAUSTIVE_COVERAGE_NOT_PASS",
            gaps=tuple(gaps),
            metrics=metrics,
        )

    @staticmethod
    def _ratio(value: int, total: int) -> float:
        return 1.0 if total == 0 else float(value) / float(total)

    @staticmethod
    def _append_many(
        gaps: List[Gap],
        snapshot: ExhaustiveCoverageSnapshot,
        category: str,
        target_node: str,
        severity: GapSeverity,
        refs: Tuple[str, ...],
    ) -> None:
        for subject_ref in refs:
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-EXHAUSTIVE", snapshot.mission_id, category, subject_ref),
                    mission_id=snapshot.mission_id,
                    source_node="MISSION_EVALUATION",
                    category=category,
                    severity=severity,
                    target_node=target_node,
                    description="%s:%s" % (category, subject_ref),
                    subject_refs=[subject_ref, snapshot.snapshot_ref],
                    evidence_refs=list(snapshot.evidence_refs),
                    acceptance_criteria=["exhaustive coverage hard gate no longer reports %s" % category],
                )
            )
