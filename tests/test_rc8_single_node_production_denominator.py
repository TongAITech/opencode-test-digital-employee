from __future__ import annotations

import pytest

from rc8_node.autonomous_claim_client import AutonomousClaimClient
from rc8_node.autonomous_dispatcher import AutonomousWorkerDispatcher
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


class _Worker:
    def execute(self, claimed):
        return {"status": "COMPLETED"}


def test_production_proof_cannot_shrink_frozen_n1_n10_denominator_via_constructor_override():
    dispatcher = AutonomousWorkerDispatcher(
        claimant=AutonomousClaimClient("http://127.0.0.1:4098", "node-1"),
        workers={"SCOPE_INTAKE": _Worker()},
    )

    with pytest.raises(RuntimeError, match="FULL_LOOP_PRODUCTION_DENOMINATOR_OVERRIDE_FORBIDDEN"):
        SingleNodeDurableIntegrationProofRunner(
            dispatcher=dispatcher,
            truth_reader=object(),
            required_stages=("SCOPE_INTAKE",),
            require_production_components=True,
        )


def test_boundary_double_may_keep_small_denominator_for_contract_testing():
    class _Dispatcher:
        supported_stages = ("SCOPE_INTAKE",)

        def run_once(self, *, test_run_id):
            return type("Result", (), {"status": "IDLE"})()

    class _Truth:
        # Boundary-double construction still obeys the existing durable truth-reader
        # interface contract.  The denominator test is not allowed to bypass that
        # independent fail-closed gate with an intentionally incomplete stub.
        def get_work_item(self, work_item_id):
            return None

        def get_attempt(self, attempt_id):
            return None

        def get_artifact(self, artifact_ref):
            return None

        def find_r1_attempt_completed(self, **kwargs):
            return None

    runner = SingleNodeDurableIntegrationProofRunner(
        dispatcher=_Dispatcher(),
        truth_reader=_Truth(),
        required_stages=("SCOPE_INTAKE",),
        require_production_components=False,
    )
    assert runner.production_components_verified is False
