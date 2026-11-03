"""Production-only promotion wrapper for the RC8 SINGLE_NODE composed proof.

The durable integration runner intentionally remains a no-PASS composition boundary.
This wrapper is the only bridge that may ask ProductionCausalityGate to promote a
completed production traversal. It preserves HOLD/bank-reality separation.
"""
from __future__ import annotations

from dataclasses import replace

from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader

from .production_causality_gate import ProductionCausalityGate
from .single_node_integration_proof import (
    SingleNodeDurableIntegrationProof,
    SingleNodeDurableIntegrationProofRunner,
    assert_production_dispatcher_topology,
)
from .single_node_production_bootstrap import ProductionSingleNodeBootstrap


class ProductionCausalityIntegrationRunner:
    """Promote only a constructor-established production composed runner.

    Do not trust the composed runner's private production boolean by itself: a unit
    boundary double can be created with ``__new__`` and can mutate private fields.
    Promotion therefore re-validates the concrete production authorities that the
    normal composed-runner constructor establishes.
    """

    def __init__(self, *, composed_runner: SingleNodeDurableIntegrationProofRunner) -> None:
        if not isinstance(composed_runner, SingleNodeDurableIntegrationProofRunner):
            raise RuntimeError("PRODUCTION_CAUSALITY_COMPOSED_RUNNER_REQUIRED")
        if not composed_runner.production_components_verified:
            raise RuntimeError("PRODUCTION_CAUSALITY_PRODUCTION_RUNNER_REQUIRED")
        truth_reader = getattr(composed_runner, "truth_reader", None)
        if not isinstance(truth_reader, ProductionCenterR1TruthReader):
            raise RuntimeError("PRODUCTION_CAUSALITY_PRODUCTION_TRUTH_READER_REQUIRED")
        production_bootstrap = getattr(composed_runner, "production_bootstrap", None)
        if not isinstance(production_bootstrap, ProductionSingleNodeBootstrap):
            raise RuntimeError("PRODUCTION_CAUSALITY_BOOTSTRAP_AUTHORITY_REQUIRED")
        if production_bootstrap.truth_reader is not truth_reader:
            raise RuntimeError("PRODUCTION_CAUSALITY_BOOTSTRAP_TRUTH_READER_MISMATCH")
        observer = getattr(composed_runner, "observer", None)
        dispatcher = getattr(observer, "dispatcher", None)
        if dispatcher is None:
            raise RuntimeError("PRODUCTION_CAUSALITY_DISPATCHER_AUTHORITY_REQUIRED")
        assert_production_dispatcher_topology(dispatcher)
        expected_node_id = str(getattr(composed_runner, "expected_node_id", "") or "").strip()
        claimant_node_id = str(getattr(getattr(dispatcher, "claimant", None), "node_id", "") or "").strip()
        if not expected_node_id or expected_node_id != claimant_node_id:
            raise RuntimeError("PRODUCTION_CAUSALITY_NODE_AUTHORITY_MISMATCH")
        self.composed_runner = composed_runner
        self.gate = ProductionCausalityGate(production_constructor_verified=True)

    def run(self, *, test_run_id: str) -> SingleNodeDurableIntegrationProof:
        proof = self.composed_runner.run(test_run_id=test_run_id)
        durable = proof.durable_truth
        durable_truth_verified = (
            durable.verified_work_items == proof.observed.work_item_ids
            and durable.verified_attempts == proof.observed.attempt_ids
            and len(durable.verified_artifacts) == len(proof.observed.evidence_refs)
            and len(durable.verified_r1_start_events) == len(proof.observed.attempt_ids)
            and len(durable.verified_r1_events) == len(proof.observed.attempt_ids)
        )
        promotion = self.gate.evaluate(
            bootstrap_materialized=True,
            observed_stages=proof.observed.stages,
            work_item_ids=proof.observed.work_item_ids,
            lease_ids=proof.observed.lease_ids,
            attempt_ids=proof.observed.attempt_ids,
            evidence_refs=proof.observed.evidence_refs,
            durable_truth_verified=durable_truth_verified,
            # SingleNodeFullLoopProofRunner has already required the post-denominator
            # production Center claim to return provenance-backed IDLE.
            terminal_center_idle=True,
        )
        if not promotion.verified:
            raise RuntimeError("PRODUCTION_CAUSALITY_PROMOTION_REJECTED:%s" % promotion.status)
        if proof.bank_reality_verified or durable.bank_reality_verified:
            raise RuntimeError("CLOUD_INTEGRATION_MUST_NOT_ASSERT_BANK_REALITY")
        if proof.release_status != "HOLD" or durable.release_status != "HOLD":
            raise RuntimeError("PRODUCTION_CAUSALITY_MUST_NOT_AUTHORIZE_RELEASE")
        return replace(
            proof,
            production_causality_verified=True,
            status=promotion.status,
            bank_reality_verified=False,
            release_status="HOLD",
        )
