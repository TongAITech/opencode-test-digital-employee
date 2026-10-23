from __future__ import annotations

from rc7_runtime.test_design_loop import TestDesignClosedLoop, TestObligation
from rc7_runtime.test_obligation_inventory import ParentDerivedTestObligationInventory


def test_requirement_preconditions_and_dependencies_are_mandatory_sources():
    sources = ParentDerivedTestObligationInventory._requirement_sources(
        {
            "atomic_statements": [{"id": "A-1"}],
            "business_rules": [{"id": "BR-1"}],
            "preconditions": [{"id": "PRE-1"}],
            "normal_paths": [],
            "negative_paths": [],
            "boundaries": [],
            "states": [],
            "roles": [],
            "data_constraints": [],
            "dependencies": [{"id": "DEP-1"}],
            "side_effects": [],
        },
        "ART-REQ",
    )
    identities = {(item.kind, item.source_id) for item in sources}

    assert ("PRECONDITION", "PRE-1") in identities
    assert ("DEPENDENCY", "DEP-1") in identities
    assert ("REQUIREMENT_ASSERTION", "A-1") in identities
    assert ("BUSINESS_RULE", "BR-1") in identities


def test_code_files_requirement_mappings_and_graph_surfaces_expand_denominator():
    sources = ParentDerivedTestObligationInventory._code_sources(
        {
            "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
            "changed_files": ["src/RateService.java"],
            "reverse_requirement_mappings": [
                {"requirement_id": "REQ-1", "symbol_id": "SYM-1"},
                {"requirement_id": "REQ-2", "symbol_id": "SYM-1"},
            ],
            "impact_surfaces": [
                {"id": "API-rate-adjust", "kind": "API"},
                {"id": "DB-rate-table", "kind": "DATABASE"},
            ],
        },
        "ART-CODE",
    )
    identities = {(item.kind, item.source_id) for item in sources}

    assert ("CODE_IMPACT", "SYM-1") in identities
    assert ("CODE_IMPACT", "FILE:src/RateService.java") in identities
    assert ("REGRESSION", "REQMAP:REQ-1:SYM-1") in identities
    assert ("REGRESSION", "REQMAP:REQ-2:SYM-1") in identities
    assert ("CODE_IMPACT", "SURFACE:API-rate-adjust") in identities
    assert ("CODE_IMPACT", "SURFACE:DB-rate-table") in identities


def _case(tc_id, subject_id):
    return {
        "tc_id": tc_id,
        "layer": "L3",
        "risk": "MEDIUM",
        "status": "CANDIDATE",
        "coverage_links": [{"subject_id": subject_id, "evidence_ref": "EVD-%s" % tc_id}],
        "action_semantics": {
            "state_changing": False,
            "negative": False,
            "authorization_sensitive": False,
        },
        "oracle": {
            "checks": [
                {"type": "API_RESPONSE", "evidence_ref": "EVD-%s-API" % tc_id},
                {"type": "BUSINESS_RULE", "evidence_ref": "EVD-%s-BR" % tc_id},
            ]
        },
    }


def test_new_precondition_and_dependency_kinds_participate_in_semantic_closure():
    obligations = [
        TestObligation(
            obligation_id="OBL-PRE",
            kind="PRECONDITION",
            layer="L3",
            risk="MEDIUM",
            evidence_refs=("EVD-PRE",),
        ),
        TestObligation(
            obligation_id="OBL-DEP",
            kind="DEPENDENCY",
            layer="L3",
            risk="MEDIUM",
            evidence_refs=("EVD-DEP",),
        ),
    ]
    result = TestDesignClosedLoop().evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-DESIGN",
        obligations=obligations,
        cases=[_case("TC-PRE", "OBL-PRE"), _case("TC-DEP", "OBL-DEP")],
    )

    assert result.evaluation.result.value == "PASS"
    assert result.semantic_coverage == 1.0
    assert result.gaps == ()
