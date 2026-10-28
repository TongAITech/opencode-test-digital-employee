import pytest

from rc8_node.failure_coverage_evaluation_worker import (
    FailureCoverageEvaluationWorker,
    FailureCoverageEvaluationWorkerError,
)


def _candidate():
    return {
        "coverage_denominator_refs": ["coverage:L3", "coverage:L4"],
        "evidence_refs": ["artifact:run-evidence"],
        "gaps": [
            {
                "gap_id": "gap-l4",
                "denominator_ref": "coverage:L4",
                "reason": "missing negative-path evidence",
                "suggested_route": "TEST_DESIGN",
            }
        ],
    }


def test_candidate_is_node_observation_and_center_keeps_gap_router_authority():
    value = FailureCoverageEvaluationWorker.validate_candidate(_candidate())
    assert value["authority"] == "NODE_OBSERVATION_ONLY"
    assert value["gap_router_authority"] == "CENTER_ONLY"


def test_empty_coverage_denominator_fails_closed():
    value = _candidate()
    value["coverage_denominator_refs"] = []
    with pytest.raises(FailureCoverageEvaluationWorkerError, match="COVERAGE_DENOMINATOR_REFS_NONEMPTY_REQUIRED"):
        FailureCoverageEvaluationWorker.validate_candidate(value)


def test_gap_cannot_escape_frozen_coverage_denominator():
    value = _candidate()
    value["gaps"][0]["denominator_ref"] = "coverage:UNKNOWN"
    with pytest.raises(FailureCoverageEvaluationWorkerError, match="GAP_DENOMINATOR_REF_UNKNOWN"):
        FailureCoverageEvaluationWorker.validate_candidate(value)


def test_duplicate_evidence_denominator_fails_closed():
    value = _candidate()
    value["evidence_refs"] = ["artifact:same", "artifact:same"]
    with pytest.raises(FailureCoverageEvaluationWorkerError, match="EVIDENCE_REFS_UNIQUE_REQUIRED"):
        FailureCoverageEvaluationWorker.validate_candidate(value)
