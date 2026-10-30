from __future__ import annotations

from rc8_node.autonomous_claim_client import ClaimedWork
from rc8_node.autonomous_dispatcher import AutonomousWorkerDispatcher
from rc8_node.single_node_full_loop_proof import (
    CENTER_CLAIM_TRUTH_NOTE,
    CENTER_IDLE_TRUTH_NOTE,
    SingleNodeFullLoopProofError,
    SingleNodeFullLoopProofRunner,
)

import pytest


class _Claimant:
    def __init__(self, claims):
        self.claims = list(claims)

    def claim_next(self, **kwargs):
        if self.claims:
            return self.claims.pop(0)
        return ClaimedWork(False, None, None, CENTER_IDLE_TRUTH_NOTE)


class _Worker:
    def execute(self, claimed):
        return {
            "status": "COMPLETED",
            "attempt_id": claimed.lease_id,
            "artifact_ref": "artifact:%s" % claimed.work_item_id,
        }


def _claim(truth_note=CENTER_CLAIM_TRUTH_NOTE):
    return ClaimedWork(
        claimed=True,
        work_item={
            "identity": {
                "work_item_id": "wi-1",
                "test_run_id": "run-1",
                "stage": "SCOPE_INTAKE",
            },
            "lease_id": "lease-1",
        },
        stage_instance_id="stage-instance-1",
        truth_note=truth_note,
    )


def _runner(truth_note=CENTER_CLAIM_TRUTH_NOTE):
    dispatcher = AutonomousWorkerDispatcher(
        claimant=_Claimant([_claim(truth_note)]),
        workers={"SCOPE_INTAKE": _Worker()},
    )
    return SingleNodeFullLoopProofRunner(
        dispatcher=dispatcher,
        required_stages=("SCOPE_INTAKE",),
        require_center_claim_provenance=True,
    )


def test_production_proof_observes_center_claim_and_terminal_idle_provenance():
    proof = _runner().run(test_run_id="run-1")
    assert proof.work_item_ids == ("wi-1",)
    assert proof.lease_ids == ("lease-1",)
    assert proof.status == "OBSERVED_NOT_AUTHORIZED"
    assert proof.bank_reality_verified is False
    assert proof.release_status == "HOLD"


def test_production_proof_rejects_claim_without_center_lease_provenance():
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_CENTER_CLAIM_PROVENANCE_MISSING:SCOPE_INTAKE"):
        _runner("CLAIMED_BY_TEST_DOUBLE").run(test_run_id="run-1")


def test_dispatcher_preserves_center_idle_provenance():
    dispatcher = AutonomousWorkerDispatcher(
        claimant=_Claimant([]),
        workers={"SCOPE_INTAKE": _Worker()},
    )
    outcome = dispatcher.run_once(test_run_id="run-1")
    assert outcome.status == "IDLE"
    assert outcome.claim_truth_note == CENTER_IDLE_TRUTH_NOTE
