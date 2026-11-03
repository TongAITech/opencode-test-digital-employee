"""Production-only promotion wrapper for the RC8 SINGLE_NODE composed proof."""
from __future__ import annotations
from dataclasses import replace
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader
from .production_causality_gate import ProductionCausalityGate
from .single_node_integration_proof import SingleNodeDurableIntegrationProof, SingleNodeDurableIntegrationProofRunner, assert_production_dispatcher_topology
from .single_node_production_bootstrap import ProductionSingleNodeBootstrap

class ProductionCausalityIntegrationRunner:
    def __init__(self, *, composed_runner: SingleNodeDurableIntegrationProofRunner) -> None:
        if not isinstance(composed_runner, SingleNodeDurableIntegrationProofRunner): raise RuntimeError("PRODUCTION_CAUSALITY_COMPOSED_RUNNER_REQUIRED")
        if not composed_runner.production_components_verified: raise RuntimeError("PRODUCTION_CAUSALITY_PRODUCTION_RUNNER_REQUIRED")
        truth_reader = getattr(composed_runner, "truth_reader", None)
        if not isinstance(truth_reader, ProductionCenterR1TruthReader): raise RuntimeError("PRODUCTION_CAUSALITY_PRODUCTION_TRUTH_READER_REQUIRED")
        production_bootstrap = getattr(composed_runner, "production_bootstrap", None)
        if not isinstance(production_bootstrap, ProductionSingleNodeBootstrap): raise RuntimeError("PRODUCTION_CAUSALITY_BOOTSTRAP_AUTHORITY_REQUIRED")
        if production_bootstrap.truth_reader is not truth_reader: raise RuntimeError("PRODUCTION_CAUSALITY_BOOTSTRAP_TRUTH_READER_MISMATCH")
        observer = getattr(composed_runner, "observer", None); dispatcher = getattr(observer, "dispatcher", None)
        if dispatcher is None: raise RuntimeError("PRODUCTION_CAUSALITY_DISPATCHER_AUTHORITY_REQUIRED")
        assert_production_dispatcher_topology(dispatcher)
        expected_node_id = str(getattr(composed_runner, "expected_node_id", "") or "").strip()
        claimant_node_id = str(getattr(getattr(dispatcher, "claimant", None), "node_id", "") or "").strip()
        if not expected_node_id or expected_node_id != claimant_node_id: raise RuntimeError("PRODUCTION_CAUSALITY_NODE_AUTHORITY_MISMATCH")
        self.composed_runner = composed_runner
        self.gate = ProductionCausalityGate(production_constructor_verified=True)

    @staticmethod
    def _bootstrap_materialization_retained(proof: SingleNodeDurableIntegrationProof) -> bool:
        observed = proof.observed
        return bool(proof.production_components_verified and proof.bootstrap_materialized and proof.bootstrap_work_item_id and proof.bootstrap_stage_instance_id and observed.work_item_ids and observed.stage_instance_ids and proof.bootstrap_work_item_id == observed.work_item_ids[0] and proof.bootstrap_stage_instance_id == observed.stage_instance_ids[0])

    @staticmethod
    def _durable_truth_verified(proof: SingleNodeDurableIntegrationProof) -> bool:
        durable, observed = proof.durable_truth, proof.observed
        start_events, completion_events = tuple(durable.verified_r1_start_events), tuple(durable.verified_r1_events)
        attempt_count = len(observed.attempt_ids)
        return bool(durable.verified_work_items == observed.work_item_ids and durable.verified_attempts == observed.attempt_ids and durable.verified_artifacts == observed.evidence_refs and len(start_events) == attempt_count and len(completion_events) == attempt_count and len(set(start_events)) == len(start_events) and len(set(completion_events)) == len(completion_events) and not set(start_events).intersection(completion_events))

    def run(self, *, test_run_id: str) -> SingleNodeDurableIntegrationProof:
        proof = self.composed_runner.run(test_run_id=test_run_id)
        durable = proof.durable_truth
        promotion = self.gate.evaluate(bootstrap_materialized=self._bootstrap_materialization_retained(proof), observed_stages=proof.observed.stages, work_item_ids=proof.observed.work_item_ids, lease_ids=proof.observed.lease_ids, attempt_ids=proof.observed.attempt_ids, evidence_refs=proof.observed.evidence_refs, durable_truth_verified=self._durable_truth_verified(proof), terminal_center_idle=bool(getattr(proof.observed, "terminal_center_idle", False)))
        if not promotion.verified: raise RuntimeError("PRODUCTION_CAUSALITY_PROMOTION_REJECTED:%s" % promotion.status)
        if proof.bank_reality_verified or durable.bank_reality_verified: raise RuntimeError("CLOUD_INTEGRATION_MUST_NOT_ASSERT_BANK_REALITY")
        if proof.release_status != "HOLD" or durable.release_status != "HOLD": raise RuntimeError("PRODUCTION_CAUSALITY_MUST_NOT_AUTHORIZE_RELEASE")
        return replace(proof, production_causality_verified=True, status=promotion.status, bank_reality_verified=False, release_status="HOLD")
