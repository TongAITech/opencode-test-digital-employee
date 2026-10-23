from __future__ import annotations

from rc7_runtime.code_sufficiency_v2 import CodeSufficiencyV2, REQUIRED_IMPACT_DIMENSIONS


def _analysis():
    return {
        "changed_files": ["src/RateService.java"],
        "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
        "evidence_refs": ["EVD-SOURCE", "EVD-CODE-TOOL-REAL"],
        "symbol_explanations": [
            {"symbol_id": "SYM-1", "evidence_refs": ["EVD-SOURCE"]}
        ],
        "tool_calls": [
            {
                "tool_id": "codegraph",
                "call_ref": "dsh-event://codegraph/callers/RateService.adjustRate",
                "evidence_ref": "EVD-CODE-TOOL-REAL",
                "target_id": "cfg-data",
            }
        ],
    }


def test_real_codegraph_call_without_structured_impact_surface_is_not_sufficient():
    result = CodeSufficiencyV2().evaluate(_analysis())

    assert result.passed is False
    assert result.metrics["runtime_proven"] is True
    assert "CODE_IMPACT_SYMBOL_UNACCOUNTED:SYM-1" in result.reasons
    assert "CODE_IMPACT_FILE_UNACCOUNTED:src/RateService.java" in result.reasons
    assert "CODE_IMPACT_DIMENSION_UNACCOUNTED:CALL_GRAPH" in result.reasons


def test_complete_surface_plus_evidence_backed_not_applicable_dimensions_passes():
    analysis = _analysis()
    analysis["impact_surfaces"] = [
        {
            "id": "SURF-CALLER-1",
            "kind": "CALLER",
            "source_symbol_id": "SYM-1",
            "source_file": "src/RateService.java",
            "target_ref": "RateController.adjustRate",
        },
        {
            "id": "SURF-API-1",
            "kind": "API",
            "source_symbol_id": "SYM-1",
            "source_file": "src/RateService.java",
            "target_ref": "POST /rate/adjust",
        },
        {
            "id": "SURF-DB-1",
            "kind": "DATABASE",
            "source_symbol_id": "SYM-1",
            "source_file": "src/RateService.java",
            "target_ref": "loan_rate.rate",
        },
    ]
    populated = {"CALL_GRAPH", "INTERFACE", "DATA"}
    analysis["impact_dimension_exclusions"] = [
        {
            "dimension": dimension,
            "reason": "CodeGraph/source evidence shows no %s impact for this change" % dimension,
            "basis_symbol_ids": ["SYM-1"],
        }
        for dimension in REQUIRED_IMPACT_DIMENSIONS
        if dimension not in populated
    ]

    result = CodeSufficiencyV2().evaluate(analysis)

    assert result.passed is True
    assert result.reasons == ()
    assert result.metrics["impact_surface_count"] == 3
    assert result.metrics["uncovered_symbol_ids"] == []
    assert result.metrics["uncovered_files"] == []
    assert set(result.metrics["populated_dimensions"]) == populated


def test_dimension_exclusion_without_durable_symbol_basis_is_rejected():
    analysis = _analysis()
    analysis["impact_surfaces"] = [
        {
            "id": "SURF-CALLER-1",
            "kind": "CALLER",
            "source_symbol_id": "SYM-1",
            "source_file": "src/RateService.java",
        }
    ]
    analysis["impact_dimension_exclusions"] = [
        {
            "dimension": "INTERFACE",
            "reason": "claimed not applicable",
            "basis_symbol_ids": ["SYM-NOT-REAL"],
        }
    ]

    result = CodeSufficiencyV2().evaluate(analysis)

    assert result.passed is False
    assert "CODE_IMPACT_DIMENSION_EXCLUSION_INVALID:INTERFACE" in result.reasons
    assert "CODE_IMPACT_DIMENSION_UNACCOUNTED:INTERFACE" in result.reasons


def test_symbol_exclusion_must_be_anchored_to_durably_explained_symbol():
    analysis = _analysis()
    analysis["symbol_explanations"] = [
        {"symbol_id": "SYM-1", "evidence_refs": ["NOT-CANONICAL"]}
    ]
    analysis["impact_exclusions"] = [
        {
            "target_type": "SYMBOL",
            "target_ref": "SYM-1",
            "reason": "no downstream impact",
        }
    ]

    result = CodeSufficiencyV2().evaluate(analysis)

    assert result.passed is False
    assert "CODE_IMPACT_EXCLUSION_INVALID:SYM-1" in result.reasons
    assert "CODE_IMPACT_SYMBOL_UNACCOUNTED:SYM-1" in result.reasons


def test_small_direct_fixture_without_real_r1_tool_proof_remains_compatible():
    analysis = _analysis()
    analysis["tool_calls"] = [
        {
            "tool_id": "codegraph",
            "call_ref": "fixture://codegraph",
            "evidence_ref": "fixture-evidence",
            "target_id": "cfg-data",
        }
    ]
    result = CodeSufficiencyV2().evaluate(analysis, force=False)

    assert result.passed is True
    assert result.metrics["active"] is False
