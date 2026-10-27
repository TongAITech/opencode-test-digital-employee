import pytest

from rc8_node.risk_test_model_worker import RiskTestModelWorker, RiskTestModelWorkerError


def test_risk_candidate_requires_evidence_backed_nonzero_denominator():
    candidate = {
        "risk_obligations": [
            {"risk_id": "risk-1", "evidence_refs": ["artifact:req"]},
            {"risk_id": "risk-2", "evidence_refs": ["artifact:code"]},
        ],
        "evidence_refs": ["artifact:req", "artifact:code"],
        "denominator": {"expected_obligation_count": 2},
    }
    assert RiskTestModelWorker.validate_candidate(candidate) == candidate


def test_risk_candidate_rejects_silent_denominator_shrink():
    candidate = {
        "risk_obligations": [{"risk_id": "risk-1", "evidence_refs": ["artifact:req"]}],
        "evidence_refs": ["artifact:req"],
        "denominator": {"expected_obligation_count": 2},
    }
    with pytest.raises(RiskTestModelWorkerError, match="RISK_MODEL_DENOMINATOR_MISMATCH"):
        RiskTestModelWorker.validate_candidate(candidate)


def test_risk_candidate_rejects_unbound_evidence():
    candidate = {
        "risk_obligations": [{"risk_id": "risk-1", "evidence_refs": ["artifact:missing"]}],
        "evidence_refs": ["artifact:req"],
        "denominator": {"expected_obligation_count": 1},
    }
    with pytest.raises(RiskTestModelWorkerError, match="RISK_OBLIGATION_EVIDENCE_MISMATCH"):
        RiskTestModelWorker.validate_candidate(candidate)
