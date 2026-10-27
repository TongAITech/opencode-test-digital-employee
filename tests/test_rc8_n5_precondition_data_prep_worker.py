from __future__ import annotations

import pytest

from rc8_node.precondition_data_prep_worker import PreconditionDataPrepWorker, PreconditionDataPrepWorkerError


def _candidate():
    return {
        "precondition_obligations": ["data:customer", "state:eligible"],
        "prepared_items": [
            {"obligation_id": "data:customer", "state": "READY", "locator": "customer:C001", "evidence_refs": ["artifact:data-1"]},
            {"obligation_id": "state:eligible", "state": "READY", "locator": "customer:C001#eligible", "evidence_refs": ["artifact:state-1"]},
        ],
        "evidence_refs": ["artifact:data-1", "artifact:state-1"],
    }


def test_candidate_requires_full_precondition_denominator():
    value = _candidate()
    assert PreconditionDataPrepWorker.validate_candidate(value)["precondition_obligations"] == ["data:customer", "state:eligible"]


def test_candidate_fails_closed_when_denominator_is_silently_shrunk():
    value = _candidate()
    value["prepared_items"] = value["prepared_items"][:1]
    with pytest.raises(PreconditionDataPrepWorkerError, match="PRECONDITION_DENOMINATOR_NOT_FULLY_PREPARED"):
        PreconditionDataPrepWorker.validate_candidate(value)


def test_candidate_rejects_unknown_obligation_mapping():
    value = _candidate()
    value["prepared_items"][0]["obligation_id"] = "data:invented"
    with pytest.raises(PreconditionDataPrepWorkerError, match="PREPARED_ITEM_UNKNOWN_OBLIGATION"):
        PreconditionDataPrepWorker.validate_candidate(value)


def test_candidate_requires_item_and_top_level_evidence():
    value = _candidate()
    value["prepared_items"][0]["evidence_refs"] = []
    with pytest.raises(PreconditionDataPrepWorkerError, match="PREPARED_ITEM_EVIDENCE_REQUIRED"):
        PreconditionDataPrepWorker.validate_candidate(value)
    value = _candidate()
    value["evidence_refs"] = []
    with pytest.raises(PreconditionDataPrepWorkerError, match="PRECONDITION_DATA_EVIDENCE_REFS_NONEMPTY_REQUIRED"):
        PreconditionDataPrepWorker.validate_candidate(value)


def test_worker_contract_keeps_prepared_attempt_authority_at_center():
    assert PreconditionDataPrepWorker.producer_ref == "RC8_PRECONDITION_DATA_PREP_WORKER"
