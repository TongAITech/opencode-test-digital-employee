from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc8_node.autonomous_claim_client import AutonomousClaimClient
from rc8_node.autonomous_dispatcher import AutonomousWorkerDispatcher
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


class _Dispatcher:
    supported_stages = ("SCOPE_INTAKE",)

    def run_once(self, *, test_run_id):
        return SimpleNamespace(
            status="EXECUTED", stage="SCOPE_INTAKE", work_item_id="wi-1",
            result={"status": "COMPLETED", "attempt_id": "att-1", "artifact_ref": "artifact:art-1"},
        )


class _Worker:
    def execute(self, claimed):
        return {"status": "COMPLETED"}


class _Truth:
    def __init__(self, *, stale=False):
        self.stale = stale

    def get_work_item(self, work_item_id):
        return {"test_run_id": "other" if self.stale else "run-1", "stage": "SCOPE_INTAKE", "status": "COMPLETED"}

    def get_attempt(self, attempt_id):
        return {"test_run_id": "run-1", "work_item_id": "wi-1", "status": "COMPLETED"}

    def get_artifact(self, artifact_id):
        return {"test_run_id": "run-1", "work_item_id": "wi-1", "attempt_id": "att-1", "status": "COMPLETED"}

    def find_r1_attempt_completed(self, *, test_run_id, work_item_id, attempt_id):
        return {"event_id": "evt-1", "event_type": "ATTEMPT_COMPLETED", "test_run_id": test_run_id,
                "work_item_id": work_item_id, "attempt_id": attempt_id}


def _boundary_double_runner(*, stale=False):
    return SingleNodeDurableIntegrationProofRunner(
        dispatcher=_Dispatcher(), truth_reader=_Truth(stale=stale),
        required_stages=("SCOPE_INTAKE",), require_production_components=False,
    )


def test_dispatcher_observation_and_durable_truth_are_one_fail_closed_gate():
    proof = _boundary_double_runner().run(test_run_id="run-1")
    assert proof.status == "DURABLE_INTEGRATION_VERIFIED_NOT_AUTHORIZED"
    assert proof.observed.work_item_ids == ("wi-1",)
    assert proof.durable_truth.verified_attempts == ("att-1",)
    assert proof.bank_reality_verified is False
    assert proof.release_status == "HOLD"


def test_stale_center_truth_cannot_promote_dispatcher_observation():
    with pytest.raises(RuntimeError, match="CENTER_WORK_ITEM_IDENTITY_MISMATCH"):
        _boundary_double_runner(stale=True).run(test_run_id="run-1")


def test_boundary_double_cannot_enter_production_full_loop_gate_by_default():
    with pytest.raises(RuntimeError, match="FULL_LOOP_PRODUCTION_DISPATCHER_REQUIRED"):
        SingleNodeDurableIntegrationProofRunner(
            dispatcher=_Dispatcher(), truth_reader=_Truth(), required_stages=("SCOPE_INTAKE",)
        )


def test_partial_production_dispatcher_cannot_enter_full_loop_gate():
    dispatcher = AutonomousWorkerDispatcher(
        claimant=AutonomousClaimClient("http://127.0.0.1:4098", "node-1"),
        workers={"SCOPE_INTAKE": _Worker()},
    )
    with pytest.raises(RuntimeError, match="FULL_LOOP_PRODUCTION_STAGE_TOPOLOGY_MISMATCH"):
        SingleNodeDurableIntegrationProofRunner(dispatcher=dispatcher, truth_reader=object())


def test_full_stage_labels_with_double_workers_cannot_enter_production_gate():
    dispatcher = AutonomousWorkerDispatcher(
        claimant=AutonomousClaimClient("http://127.0.0.1:4098", "node-1"),
        workers={stage: _Worker() for stage in FROZEN_N1_N10_STAGES},
    )
    with pytest.raises(RuntimeError, match="FULL_LOOP_PRODUCTION_WORKER_IDENTITY_MISMATCH:SCOPE_INTAKE"):
        SingleNodeDurableIntegrationProofRunner(dispatcher=dispatcher, truth_reader=object())
