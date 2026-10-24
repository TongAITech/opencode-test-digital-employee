from __future__ import annotations

import pytest

from rc7_runtime.autonomous_contract import (
    AutonomousContractError,
    CoverageDenominatorSnapshot,
    CoverageLedger,
    CoverageObligation,
)


def _denominator(*, excluded=()):
    return CoverageDenominatorSnapshot(
        mission_id="MISSION-COVERAGE",
        layer="L1",
        source_revision="git:abc123",
        target_id="PFC",
        denominator_version="v1",
        denominator_hash="sha256:denominator",
        obligation_ids=("LINE-1", "BRANCH-TRUE", "BRANCH-FALSE"),
        evidence_refs=("EVD-GIT", "EVD-CODEGRAPH"),
        excluded_obligation_ids=tuple(excluded),
    )


def test_covered_fail_closes_coverage_without_turning_quality_into_pass() -> None:
    ledger = CoverageLedger(
        denominator=_denominator(excluded=("BRANCH-FALSE",)),
        obligations=(
            CoverageObligation("LINE-1", "COVERED_PASS", evidence_refs=("EVD-LINE",)),
            CoverageObligation("BRANCH-TRUE", "COVERED_FAIL", evidence_refs=("EVD-FAIL",)),
            CoverageObligation(
                "BRANCH-FALSE",
                "EXCLUDED_WITH_EVIDENCE",
                evidence_refs=("EVD-UNREACHABLE",),
                exclusion_reason="proven unreachable generated branch",
            ),
        ),
    )
    receipt = ledger.receipt()
    assert receipt.status == "READY"
    assert receipt.covered == 3
    assert receipt.covered_pass == 1
    assert receipt.covered_fail == 1
    assert receipt.excluded_with_evidence == 1
    assert receipt.percent == 1.0


def test_exclusion_cannot_exist_without_evidence_and_reason() -> None:
    with pytest.raises(AutonomousContractError, match="COVERAGE_TERMINAL_EVIDENCE_REQUIRED"):
        CoverageObligation("BRANCH-FALSE", "EXCLUDED_WITH_EVIDENCE")
    with pytest.raises(AutonomousContractError, match="COVERAGE_EXCLUSION_REASON_REQUIRED"):
        CoverageObligation("BRANCH-FALSE", "EXCLUDED_WITH_EVIDENCE", evidence_refs=("EVD",))


def test_ledger_must_exactly_match_frozen_denominator() -> None:
    with pytest.raises(AutonomousContractError, match="COVERAGE_LEDGER_DENOMINATOR_MISMATCH"):
        CoverageLedger(
            denominator=_denominator(),
            obligations=(
                CoverageObligation("LINE-1", "COVERED_PASS", evidence_refs=("EVD-LINE",)),
                CoverageObligation("BRANCH-TRUE", "COVERED_PASS", evidence_refs=("EVD-BRANCH",)),
            ),
        )


def test_blocked_obligation_never_produces_ready_receipt() -> None:
    ledger = CoverageLedger(
        denominator=_denominator(),
        obligations=(
            CoverageObligation("LINE-1", "COVERED_PASS", evidence_refs=("EVD-LINE",)),
            CoverageObligation("BRANCH-TRUE", "BLOCKED", gap_ids=("GAP-DATA",)),
            CoverageObligation("BRANCH-FALSE", "READY", gap_ids=("GAP-CASE",)),
        ),
    )
    receipt = ledger.receipt()
    assert receipt.status == "BLOCKED"
    assert receipt.blocked_obligation_ids == ("BRANCH-TRUE",)
    assert set(receipt.open_gap_ids) == {"GAP-DATA", "GAP-CASE"}
    assert receipt.percent < 1.0
