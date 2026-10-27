import pytest

from rc8_node.design_sufficiency_worker import DesignSufficiencyWorker, DesignSufficiencyWorkerError


def _design():
    return {
        "schema_version": "rc8.test-design.v1",
        "authority": "NODE_OBSERVATION_ONLY",
        "candidate": {
            "risk_denominator": ["risk-1", "risk-2"],
            "evidence_refs": ["artifact:risk-model"],
            "test_cases": [
                {"case_id": "case-1", "risk_ids": ["risk-1"], "preconditions": ["ready"], "steps": ["submit"], "expected_results": ["accepted"]},
                {"case_id": "case-2", "risk_ids": ["risk-2"], "preconditions": ["ready"], "steps": ["submit invalid"], "expected_results": ["rejected"]},
            ],
        },
    }


def test_design_sufficiency_accepts_complete_frozen_denominator():
    result = DesignSufficiencyWorker.evaluate("artifact-test-design", _design())
    assert result == {"candidate_sufficient": True, "missing": []}


def test_design_sufficiency_rejects_uncovered_risk():
    design = _design()
    design["candidate"]["test_cases"] = design["candidate"]["test_cases"][:1]
    result = DesignSufficiencyWorker.evaluate("artifact-test-design", design)
    assert result["candidate_sufficient"] is False
    assert "risk_denominator:fully_covered" in result["missing"]


def test_design_sufficiency_rejects_missing_evidence():
    design = _design()
    design["candidate"]["evidence_refs"] = []
    result = DesignSufficiencyWorker.evaluate("artifact-test-design", design)
    assert result["candidate_sufficient"] is False
    assert "evidence_refs:non-empty" in result["missing"]


def test_design_sufficiency_rejects_wrong_artifact_schema():
    design = _design()
    design["schema_version"] = "wrong"
    with pytest.raises(DesignSufficiencyWorkerError, match="TEST_DESIGN_ARTIFACT_REQUIRED"):
        DesignSufficiencyWorker.evaluate("artifact-test-design", design)
