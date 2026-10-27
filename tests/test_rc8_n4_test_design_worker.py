import pytest

from rc8_node.test_design_worker import TestDesignWorker, TestDesignWorkerError


def _candidate():
    return {
        "risk_denominator": ["risk-1", "risk-2"],
        "evidence_refs": ["artifact:risk-model"],
        "test_cases": [
            {"case_id": "case-normal", "risk_ids": ["risk-1"], "preconditions": ["ready"], "steps": ["submit"], "expected_results": ["accepted"]},
            {"case_id": "case-negative", "risk_ids": ["risk-2"], "preconditions": ["ready"], "steps": ["submit invalid"], "expected_results": ["rejected"]},
        ],
    }


def test_design_candidate_requires_full_risk_denominator_coverage():
    candidate = _candidate()
    assert TestDesignWorker.validate_candidate(candidate) == candidate


def test_design_candidate_rejects_silent_risk_denominator_shrink():
    candidate = _candidate()
    candidate["test_cases"] = candidate["test_cases"][:1]
    with pytest.raises(TestDesignWorkerError, match="RISK_DENOMINATOR_NOT_FULLY_COVERED"):
        TestDesignWorker.validate_candidate(candidate)


def test_design_candidate_requires_executable_case_shape():
    candidate = _candidate()
    candidate["test_cases"][0]["expected_results"] = []
    with pytest.raises(TestDesignWorkerError, match="TEST_CASE_EXPECTED_RESULTS_NONEMPTY_REQUIRED"):
        TestDesignWorker.validate_candidate(candidate)


def test_design_candidate_rejects_unknown_risk_mapping():
    candidate = _candidate()
    candidate["test_cases"][0]["risk_ids"] = ["risk-unknown"]
    with pytest.raises(TestDesignWorkerError, match="TEST_CASE_RISK_MAPPING_INVALID"):
        TestDesignWorker.validate_candidate(candidate)
