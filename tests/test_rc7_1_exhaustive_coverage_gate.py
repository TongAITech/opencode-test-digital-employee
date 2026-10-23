from __future__ import annotations

import pytest

from rc7_runtime.exhaustive_coverage_gate import (
    ExhaustiveCoverageError,
    ExhaustiveCoverageGate,
    ExhaustiveCoverageSnapshot,
)


def _snapshot(**overrides):
    values = dict(
        mission_id="MISSION-BLOAN-PF1.2.1-R3",
        snapshot_ref="R1-SEQ-13",
        evidence_refs=("EVD-R1",),
        designed_cases_total=452,
        terminal_cases_accounted=452,
        unaccounted_case_refs=(),
        changed_executable_lines_total=100,
        changed_executable_lines_covered=100,
        uncovered_changed_line_refs=(),
        changed_branches_total=40,
        changed_branches_covered=40,
        uncovered_changed_branch_refs=(),
        critical_conditions_total=20,
        critical_conditions_covered=20,
        uncovered_critical_condition_refs=(),
        l4_ui_cases_requiring_evidence=80,
        l4_ui_cases_with_complete_evidence=80,
        l4_missing_evidence_case_refs=(),
        l5_critical_high_e2e_total=38,
        l5_critical_high_e2e_executed=38,
        l5_unexecuted_e2e_refs=(),
        l6_professional_cases_total=6,
        l6_k6_verified=6,
        l6_missing_k6_refs=(),
        l7_professional_cases_total=16,
        l7_zap_verified=16,
        l7_missing_zap_refs=(),
        open_critical_gap_refs=(),
        open_high_gap_refs=(),
    )
    values.update(overrides)
    return ExhaustiveCoverageSnapshot(**values)


def test_full_contract_passes_only_when_every_gate_is_closed() -> None:
    result = ExhaustiveCoverageGate().evaluate(_snapshot())
    assert result.passed is True
    assert result.state == "EXHAUSTIVE_COVERAGE_PASS"
    assert result.gaps == ()
    assert result.metrics["execution_accounting"] == 1.0
    assert result.metrics["changed_line_coverage"] == 1.0
    assert result.metrics["changed_branch_coverage"] == 1.0
    assert result.metrics["l5_critical_high_e2e"] == 1.0
    assert result.metrics["l6_k6_verified"] == 1.0
    assert result.metrics["l7_zap_verified"] == 1.0


def test_bloan_r3_field_shape_is_not_allowed_to_pass() -> None:
    # Mirrors the field defects seen in BLOAN-PF1.2.1 R3: only a subset of the
    # designed cases is actually accounted, changed-code coverage is partial,
    # L5 is sampled, and professional/UI evidence is incomplete.
    missing_cases = tuple("CASE-%03d" % i for i in range(300, 452))
    missing_lines = tuple("cfg-scd:line:%d" % i for i in range(75, 101))
    missing_branches = tuple("cfg-scd:branch:%d" % i for i in range(11, 41))
    missing_l4 = tuple("L4-%03d" % i for i in range(1, 11))
    missing_l5 = tuple("L5-%03d" % i for i in range(7, 39))
    missing_l6 = tuple("L6-%02d" % i for i in range(1, 7))
    missing_l7 = tuple("L7-%02d" % i for i in range(1, 17))

    result = ExhaustiveCoverageGate().evaluate(
        _snapshot(
            terminal_cases_accounted=300,
            unaccounted_case_refs=missing_cases,
            changed_executable_lines_covered=74,
            uncovered_changed_line_refs=missing_lines,
            changed_branches_covered=10,
            uncovered_changed_branch_refs=missing_branches,
            l4_ui_cases_with_complete_evidence=70,
            l4_missing_evidence_case_refs=missing_l4,
            l5_critical_high_e2e_executed=6,
            l5_unexecuted_e2e_refs=missing_l5,
            l6_k6_verified=0,
            l6_missing_k6_refs=missing_l6,
            l7_zap_verified=0,
            l7_missing_zap_refs=missing_l7,
            open_high_gap_refs=("G1-BR-TRACE", "G2-BRANCH-COVERAGE"),
        )
    )

    assert result.passed is False
    categories = {gap.category for gap in result.gaps}
    assert "EXECUTION_ACCOUNTING_INCOMPLETE" in categories
    assert "CHANGED_LINE_COVERAGE_INCOMPLETE" in categories
    assert "CHANGED_BRANCH_COVERAGE_INCOMPLETE" in categories
    assert "L4_UI_EVIDENCE_INCOMPLETE" in categories
    assert "L5_E2E_NOT_EXECUTED" in categories
    assert "L6_K6_EVIDENCE_MISSING" in categories
    assert "L7_ZAP_EVIDENCE_MISSING" in categories
    assert "OPEN_HIGH_COVERAGE_GAP" in categories


def test_defect_creation_does_not_allow_case_to_disappear_from_accounting() -> None:
    result = ExhaustiveCoverageGate().evaluate(
        _snapshot(
            terminal_cases_accounted=451,
            unaccounted_case_refs=("CASE-L4-334-FAIL-PRODUCT",),
        )
    )
    assert result.passed is False
    assert any(g.category == "EXECUTION_ACCOUNTING_INCOMPLETE" for g in result.gaps)


def test_l5_sampling_cannot_be_called_e2e_complete() -> None:
    missing = tuple("L5-%02d" % i for i in range(7, 39))
    result = ExhaustiveCoverageGate().evaluate(
        _snapshot(l5_critical_high_e2e_executed=6, l5_unexecuted_e2e_refs=missing)
    )
    assert result.passed is False
    assert result.metrics["l5_critical_high_e2e"] < 1.0
    assert all(g.category == "L5_E2E_NOT_EXECUTED" for g in result.gaps)


def test_missing_k6_or_zap_is_not_degraded_pass() -> None:
    result = ExhaustiveCoverageGate().evaluate(
        _snapshot(
            l6_k6_verified=5,
            l6_missing_k6_refs=("L6-PERF-6",),
            l7_zap_verified=15,
            l7_missing_zap_refs=("L7-SEC-16",),
        )
    )
    assert result.passed is False
    assert {g.category for g in result.gaps} == {
        "L6_K6_EVIDENCE_MISSING",
        "L7_ZAP_EVIDENCE_MISSING",
    }


def test_snapshot_rejects_hidden_missing_refs() -> None:
    with pytest.raises(ExhaustiveCoverageError, match="CHANGED_LINES_MISSING_REF_COUNT_MISMATCH"):
        _snapshot(changed_executable_lines_covered=99, uncovered_changed_line_refs=())
