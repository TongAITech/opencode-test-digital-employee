import pytest

from rc8_node.mission_sufficiency_observation_worker import (
    MissionSufficiencyObservationWorker,
    MissionSufficiencyObservationWorkerError,
)


def _candidate():
    return {
        "evidence_refs": ["artifact:coverage", "artifact:defects", "artifact:risk", "artifact:release"],
        "dimensions": {
            "test_sufficiency": {"state": "CANDIDATE_SUFFICIENT", "evidence_refs": ["artifact:coverage"]},
            "product_quality": {"state": "CANDIDATE_ACCEPTABLE", "evidence_refs": ["artifact:defects"]},
            "release_recommendation": {"state": "CANDIDATE_HOLD", "evidence_refs": ["artifact:release"]},
            "residual_risk": {"state": "PRESENT", "evidence_refs": ["artifact:risk"]},
        },
        "active_blocking_gaps": ["gap:n8-1"],
    }


def test_n10_observation_keeps_all_final_authority_in_center():
    result = MissionSufficiencyObservationWorker.validate_candidate(_candidate())
    assert result["authority"] == "NODE_OBSERVATION_ONLY"
    assert result["convergence_authority"] == "CENTER_ONLY"
    assert result["may_declare_mission_converged"] is False
    assert result["may_recommend_release"] is False


def test_n10_requires_nonempty_unique_evidence_denominator():
    value = _candidate(); value["evidence_refs"] = []
    with pytest.raises(MissionSufficiencyObservationWorkerError, match="N10_EVIDENCE_DENOMINATOR_NONEMPTY_REQUIRED"):
        MissionSufficiencyObservationWorker.validate_candidate(value)
    value = _candidate(); value["evidence_refs"] = ["artifact:x", "artifact:x"]
    with pytest.raises(MissionSufficiencyObservationWorkerError, match="N10_EVIDENCE_DENOMINATOR_UNIQUE_REQUIRED"):
        MissionSufficiencyObservationWorker.validate_candidate(value)


def test_n10_requires_four_independent_dimensions():
    value = _candidate(); del value["dimensions"]["product_quality"]
    with pytest.raises(MissionSufficiencyObservationWorkerError, match="N10_REQUIRED_DIMENSIONS_MISSING"):
        MissionSufficiencyObservationWorker.validate_candidate(value)


def test_n10_dimension_evidence_must_be_inside_frozen_denominator():
    value = _candidate(); value["dimensions"]["residual_risk"]["evidence_refs"] = ["artifact:unknown"]
    with pytest.raises(MissionSufficiencyObservationWorkerError, match="N10_DIMENSION_EVIDENCE_OUTSIDE_DENOMINATOR:residual_risk"):
        MissionSufficiencyObservationWorker.validate_candidate(value)


def test_n10_requires_explicit_active_blocking_gap_denominator():
    value = _candidate(); value["active_blocking_gaps"] = None
    with pytest.raises(MissionSufficiencyObservationWorkerError, match="N10_ACTIVE_BLOCKING_GAPS_LIST_REQUIRED"):
        MissionSufficiencyObservationWorker.validate_candidate(value)
