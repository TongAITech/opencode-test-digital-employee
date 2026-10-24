from __future__ import annotations

from rc7_runtime.defect_evidence_policy import (
    DefectEvidencePolicy,
    RCAEvidenceChain,
    SeverityFactors,
)


def _signature(**overrides):
    data = {
        "product_area": "loan-version-management",
        "requirement_refs": ["STBB19-320"],
        "affected_application": "cfg-data",
        "surface_ref": "POST /loan/version/publish",
        "failure_signature_id": "FSIG-ABC",
        "business_error_code": "BIZ-409",
        "root_stack_frame": "LoanVersionService.publish",
        "suspected_symbols": ["LoanVersionService.publish", "VersionRepository.save"],
        "codegraph_root": "LoanVersionService.publish",
        "business_symptom": "version state remains DRAFT after publish",
        "final_state_mismatch": "expected=PUBLISHED actual=DRAFT",
        "root_cause_statement": "publish transaction does not advance state",
        "evidence_refs": ["EVD-EXEC-1", "EVD-CAT-1", "EVD-GRAPH-1"],
    }
    data.update(overrides)
    return DefectEvidencePolicy.build_signature(**data)


def test_duplicate_requires_multi_evidence_and_same_business_outcome():
    candidate = _signature()
    existing = _signature()
    decision = DefectEvidencePolicy.compare(candidate, "DEFECT-OLD", existing)
    assert decision.disposition == "DUPLICATE"
    assert decision.auto_merge_allowed is True
    assert decision.confidence >= 0.9
    assert "failure_signature_id" in decision.matched_fields
    assert "codegraph_root" in decision.matched_fields


def test_same_symbol_but_different_business_failure_cannot_auto_merge():
    candidate = _signature(
        business_symptom="version publish succeeds but effective date is wrong",
        final_state_mismatch="expected=2026-10-24 actual=2026-10-23",
    )
    existing = _signature()
    decision = DefectEvidencePolicy.compare(candidate, "DEFECT-OLD", existing)
    assert decision.disposition == "POSSIBLE_DUPLICATE"
    assert decision.auto_merge_allowed is False


def test_distinct_failure_without_root_cause_compatibility_stays_distinct():
    candidate = _signature(
        affected_application="cfg-center",
        surface_ref="GET /loan/version/query",
        failure_signature_id="FSIG-DIFFERENT",
        business_error_code="BIZ-500",
        root_stack_frame="VersionQueryController.query",
        suspected_symbols=["VersionQueryController.query"],
        codegraph_root="VersionQueryController.query",
        business_symptom="query returns empty list",
        final_state_mismatch="expected=1-row actual=0-row",
    )
    decision = DefectEvidencePolicy.compare(candidate, "DEFECT-OLD", _signature())
    assert decision.disposition == "DISTINCT"
    assert decision.matched_defect_id is None


def test_severity_is_policy_derived_not_default_high():
    critical = DefectEvidencePolicy.derive_severity(
        SeverityFactors(
            business_impact=3,
            blast_radius=3,
            data_integrity=1,
            security_compliance=4,
            transaction_criticality=3,
            workaround_unavailable=3,
            reproducibility=4,
            evidence_refs=("EVD-SEV-1",),
        )
    )
    assert critical.severity == "CRITICAL"
    assert "CRITICAL_SECURITY_OR_COMPLIANCE" in critical.reasons

    medium = DefectEvidencePolicy.derive_severity(
        SeverityFactors(
            business_impact=2,
            blast_radius=2,
            data_integrity=1,
            security_compliance=0,
            transaction_criticality=2,
            workaround_unavailable=2,
            reproducibility=3,
            evidence_refs=("EVD-SEV-2",),
        )
    )
    assert medium.severity == "MEDIUM"

    low = DefectEvidencePolicy.derive_severity(
        SeverityFactors(
            business_impact=1,
            blast_radius=1,
            data_integrity=0,
            security_compliance=0,
            transaction_criticality=1,
            workaround_unavailable=1,
            reproducibility=1,
            evidence_refs=("EVD-SEV-3",),
        )
    )
    assert low.severity == "LOW"


def test_rca_level_allows_filing_at_service_level_but_tracks_deeper_evidence():
    l0 = DefectEvidencePolicy.assess_rca(
        RCAEvidenceChain(symptom_evidence_refs=("EVD-SYMPTOM",))
    )
    assert l0.level == "RCA-L0"
    assert l0.filing_minimum_met is False

    l2 = DefectEvidencePolicy.assess_rca(
        RCAEvidenceChain(
            symptom_evidence_refs=("EVD-SYMPTOM",),
            affected_application="cfg-data",
            service_or_endpoint="POST /loan/version/publish",
            evidence_refs=("EVD-CAT",),
        )
    )
    assert l2.level == "RCA-L2"
    assert l2.filing_minimum_met is True

    l4 = DefectEvidencePolicy.assess_rca(
        RCAEvidenceChain(
            symptom_evidence_refs=("EVD-SYMPTOM",),
            affected_application="cfg-data",
            service_or_endpoint="POST /loan/version/publish",
            module_or_symbol="LoanVersionService.publish",
            code_change_refs=("git-change://abc123",),
            codegraph_refs=("codegraph://LoanVersionService.publish",),
            git_refs=("git://abc123",),
            requirement_refs=("STBB19-320",),
            evidence_refs=("EVD-CAT", "EVD-GRAPH", "EVD-GIT"),
        )
    )
    assert l4.level == "RCA-L4"
    assert l4.filing_minimum_met is True
