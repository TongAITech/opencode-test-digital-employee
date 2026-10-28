import pytest

from rc8_node.defect_closure_observation_worker import (
    DefectClosureObservationWorker,
    DefectClosureObservationWorkerError,
)


def _candidate():
    return {
        "route_decision_ref": "route:n8-product-1",
        "source_observation_ref": "observation:n8-1",
        "source_attempt_ref": "attempt:n7-2",
        "classification": "PRODUCT",
        "evidence_refs": ["artifact:failure", "artifact:network"],
        "observations": [
            {"observation_id": "repro-1", "kind": "REPRODUCTION", "evidence_refs": ["artifact:repro"]},
            {"observation_id": "rca-1", "kind": "RCA", "evidence_refs": ["artifact:rca"]},
        ],
    }


def test_n9_observation_is_candidate_only_and_center_authoritative():
    result = DefectClosureObservationWorker.validate_candidate(_candidate())
    assert result["authority"] == "NODE_OBSERVATION_ONLY"
    assert result["defect_lifecycle_authority"] == "CENTER_ONLY"
    assert result["may_file_defect"] is False
    assert result["may_close_defect"] is False


@pytest.mark.parametrize("classification", ["TEST", "ENVIRONMENT", "UNKNOWN", ""])
def test_n9_rejects_non_product_classification(classification):
    value = _candidate()
    value["classification"] = classification
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_REQUIRES_PRODUCT_CLASSIFICATION"):
        DefectClosureObservationWorker.validate_candidate(value)


def test_n9_requires_canonical_n8_route_and_source_attempt():
    value = _candidate()
    value["route_decision_ref"] = ""
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_CANONICAL_N8_ROUTE_REF_REQUIRED"):
        DefectClosureObservationWorker.validate_candidate(value)
    value = _candidate()
    value["source_attempt_ref"] = ""
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_SOURCE_OBSERVATION_AND_ATTEMPT_REQUIRED"):
        DefectClosureObservationWorker.validate_candidate(value)


def test_n9_requires_nonempty_unique_evidence_denominator():
    value = _candidate()
    value["evidence_refs"] = []
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_EVIDENCE_REFS_NONEMPTY_REQUIRED"):
        DefectClosureObservationWorker.validate_candidate(value)
    value = _candidate()
    value["evidence_refs"] = ["artifact:x", "artifact:x"]
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_EVIDENCE_REFS_UNIQUE_REQUIRED"):
        DefectClosureObservationWorker.validate_candidate(value)


def test_n9_rejects_unknown_observation_kind_and_missing_item_evidence():
    value = _candidate()
    value["observations"][0]["kind"] = "FILE_DEFECT"
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_OBSERVATION_KIND_INVALID"):
        DefectClosureObservationWorker.validate_candidate(value)
    value = _candidate()
    value["observations"][0]["evidence_refs"] = []
    with pytest.raises(DefectClosureObservationWorkerError, match="N9_OBSERVATION_EVIDENCE_REQUIRED"):
        DefectClosureObservationWorker.validate_candidate(value)
