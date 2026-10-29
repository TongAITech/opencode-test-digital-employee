"""Composition gate for RC8 SINGLE_NODE full-loop integration proof.

This module deliberately owns no PASS/release authority. It composes the production
AutonomousWorkerDispatcher traversal proof with the durable Center/R1 truth verifier
so an observed worker result cannot be promoted unless the same TestRun/WorkItem/
Attempt/Artifact identities exist in durable truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .single_node_full_loop_proof import (
    FROZEN_N1_N10_STAGES,
    SingleNodeFullLoopProof,
    SingleNodeFullLoopProofRunner,
)
from .single_node_truth import SingleNodeCenterTruth, SingleNodeCenterTruthVerifier


@dataclass(frozen=True)
class SingleNodeDurableIntegrationProof:
    observed: SingleNodeFullLoopProof
    durable_truth: SingleNodeCenterTruth
    status: str = "DURABLE_INTEGRATION_VERIFIED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


class SingleNodeDurableIntegrationProofRunner:
    """Run real dispatcher traversal, then verify the exact traversal in durable truth."""

    def __init__(
        self,
        *,
        dispatcher: Any,
        truth_reader: Any,
        required_stages: Sequence[str] = FROZEN_N1_N10_STAGES,
    ) -> None:
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
