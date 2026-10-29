"""Composition gate for RC8 SINGLE_NODE full-loop integration proof.

This module deliberately owns no PASS/release authority. It composes the production
AutonomousWorkerDispatcher traversal proof with the durable Center/R1 truth verifier
so an observed worker result cannot be promoted unless the same TestRun/WorkItem/
Attempt/Artifact identities exist in durable truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader

from .autonomous_claim_client import AutonomousClaimClient
from .autonomous_dispatcher import AutonomousWorkerDispatcher
from .single_node_full_loop_proof import (
    FROZEN_N1_N10_STAGES,
    SingleNodeFullLoopProof,
    SingleNodeFullLoopProofRunner,
)
from .single_node_truth import SingleNodeCenterTruthVerifier, SingleNodeTruthProof


@dataclass(frozen=True)
class SingleNodeDurableIntegrationProof:
    observed: SingleNodeFullLoopProof
    durable_truth: SingleNodeTruthProof
    status: str = "DURABLE_INTEGRATION_VERIFIED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


def assert_production_dispatcher_topology(
    dispatcher: AutonomousWorkerDispatcher,
    *,
    required_stages: Sequence[str] = FROZEN_N1_N10_STAGES,
) -> None:
    """Reject a production-shaped dispatcher that cannot execute the frozen denominator.

    isinstance checks alone are insufficient: an AutonomousWorkerDispatcher can be
    constructed with a subset of workers.  Such a dispatcher must never enter the
    SINGLE_NODE production proof because Center would simply never lease the missing
    stages and a partial traversal could be mistaken for a production topology.
    """
    expected = tuple(sorted(str(stage).strip() for stage in required_stages))
    actual = tuple(sorted(dispatcher.supported_stages))
    if actual != expected:
        missing = tuple(stage for stage in expected if stage not in actual)
        extra = tuple(stage for stage in actual if stage not in expected)
        raise RuntimeError(
            "FULL_LOOP_PRODUCTION_STAGE_TOPOLOGY_MISMATCH:missing=%s:extra=%s"
            % (",".join(missing), ",".join(extra))
        )


class SingleNodeDurableIntegrationProofRunner:
    """Run dispatcher traversal, then verify the exact traversal in durable truth.

    Production-driven proof is the default.  Boundary-double tests must opt out
    explicitly; they can exercise verifier contracts but can never be promoted as
    the SINGLE_NODE production full-loop checkpoint.
    """

    def __init__(
        self,
        *,
        dispatcher: Any,
        truth_reader: Any,
        required_stages: Sequence[str] = FROZEN_N1_N10_STAGES,
        require_production_components: bool = True,
    ) -> None:
        if require_production_components:
            if not isinstance(dispatcher, AutonomousWorkerDispatcher):
                raise RuntimeError("FULL_LOOP_PRODUCTION_DISPATCHER_REQUIRED")
            if not isinstance(getattr(dispatcher, "claimant", None), AutonomousClaimClient):
                raise RuntimeError("FULL_LOOP_PRODUCTION_CLAIM_CLIENT_REQUIRED")
            assert_production_dispatcher_topology(dispatcher, required_stages=required_stages)
            if not isinstance(truth_reader, ProductionCenterR1TruthReader):
                raise RuntimeError("FULL_LOOP_PRODUCTION_TRUTH_READER_REQUIRED")
        self.production_components_verified = bool(require_production_components)
        self.observer = SingleNodeFullLoopProofRunner(
            dispatcher=dispatcher,
            required_stages=required_stages,
        )
        self.verifier = SingleNodeCenterTruthVerifier(truth_reader=truth_reader)

    def run(self, *, test_run_id: str) -> SingleNodeDurableIntegrationProof:
        observed = self.observer.run(test_run_id=test_run_id)
        durable = self.verifier.verify(observed)
        # Keep this composition fail-closed even if verifier contracts evolve.
        if durable.verified_work_items != observed.work_item_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_WORK_ITEM_IDENTITY_MISMATCH")
        if durable.verified_attempts != observed.attempt_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_ATTEMPT_IDENTITY_MISMATCH")
        if durable.bank_reality_verified:
            raise RuntimeError("CLOUD_INTEGRATION_MUST_NOT_ASSERT_BANK_REALITY")
        if durable.release_status != "HOLD":
            raise RuntimeError("INTEGRATION_PROOF_MUST_NOT_AUTHORIZE_RELEASE")
        return SingleNodeDurableIntegrationProof(observed=observed, durable_truth=durable)
