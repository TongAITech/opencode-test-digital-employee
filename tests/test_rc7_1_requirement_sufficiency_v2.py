from __future__ import annotations

from rc7_runtime.requirement_sufficiency_v2 import RequirementSufficiencyV2


DIMENSIONS = (
    "business_rules",
    "roles",
    "preconditions",
    "normal_paths",
    "negative_paths",
    "boundaries",
    "states",
    "data_constraints",
    "dependencies",
    "side_effects",
)


def _analysis():
    row = {
        "source_assertions": [{"id": "SRC-1"}],
        "atomic_statements": [{"id": "A-1"}],
        "evidence_refs": ["EVD-1"],
    }
    for index, name in enumerate(DIMENSIONS, 1):
        row[name] = [{"id": "%s-%d" % (name.upper(), index)}]
    return row


def test_forced_real_analysis_rejects_unaccounted_empty_dimension():
    analysis = _analysis()
    analysis["negative_paths"] = []
    result = RequirementSufficiencyV2().evaluate(analysis, force=True)

    assert result.passed is False
    assert "REQ_DIMENSION_UNACCOUNTED:negative_paths" in result.reasons
    assert result.metrics["unaccounted_dimensions"] == ["negative_paths"]


def test_evidence_backed_not_applicable_exclusion_accounts_for_empty_dimension():
    analysis = _analysis()
    analysis["roles"] = []
    analysis["dependencies"] = []
    analysis["dimension_exclusions"] = [
        {"dimension": "roles", "reason": "no role-dependent behavior in source", "evidence_ref": "EVD-1"},
        {"dimension": "dependencies", "reason": "no external dependency in source", "evidence_ref": "EVD-1"},
    ]
    result = RequirementSufficiencyV2().evaluate(analysis, force=True)

    assert result.passed is True
    assert result.metrics["excluded_dimensions"] == ["dependencies", "roles"]
    assert result.reasons == ()


def test_exclusion_without_durable_evidence_is_rejected():
    analysis = _analysis()
    analysis["states"] = []
    analysis["dimension_exclusions"] = [
        {"dimension": "states", "reason": "claimed not applicable", "evidence_ref": "EVD-NOT-CANONICAL"},
    ]
    result = RequirementSufficiencyV2().evaluate(analysis, force=True)

    assert result.passed is False
    assert "REQ_DIMENSION_EXCLUSION_INVALID:states" in result.reasons
    assert "REQ_DIMENSION_UNACCOUNTED:states" in result.reasons


def test_populated_dimension_requires_unique_identified_facts():
    analysis = _analysis()
    analysis["business_rules"] = [{"id": "BR-1"}, {"id": "BR-1"}]
    result = RequirementSufficiencyV2().evaluate(analysis, force=True)

    assert result.passed is False
    assert "REQ_DIMENSION_ITEM_INVALID:business_rules" in result.reasons


def test_small_direct_fixture_remains_backward_compatible_without_force():
    analysis = _analysis()
    for name in DIMENSIONS:
        if name != "boundaries":
            analysis[name] = []
    result = RequirementSufficiencyV2().evaluate(analysis, force=False)

    assert result.passed is True
    assert result.metrics["active"] is False
    assert result.metrics["status"] == "NOT_REQUIRED_FOR_SMALL_ANALYSIS"
