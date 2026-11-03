from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc8_node.production_causality_integration import ProductionCausalityIntegrationRunner
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES, SingleNodeFullLoopProof
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProof, SingleNodeDurableIntegrationProofRunner
from rc8_node.single_node_truth import SingleNodeTruthProof


def _composed_runner(*, production=True):
    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = production
    runner.production_bootstrap = object() if production else None
    denominator = len(FROZEN_N1_N10_STAGES)
    work_items = tuple("wi-%02d" % i for i in range(denominator))
    leases = tuple("lease-%02d" % i for i in range(denominator))
    evidence = tuple("artifact:art-%02d" % i for i in range(denominator))
    observed = SingleNodeFullLoopProof(
        test_run_id="run-1",
        stages=tuple(FROZEN_N1_N10_STAGES),
        work_item_ids=work_items,
        lease_ids=leases,
        stage_instance_ids=tuple("si-%02d" % i for i in range(denominator)),
        attempt_ids=leases,
        evidence_refs=evidence,
    )
    durable = SingleNodeTruthProof(
        test_run_id="run-1",
        verified_work_items=work_items,
        verified_attempts=leases,
        verified_artifacts=evidence,
        verified_r1_events=tuple("complete-%02d" % i for i in range(denominator)),
        verified_r1_start_events=tuple("start-%02d" % i for i in range(denominator)),
        verified_production_node_id="node-1",
    )
    proof = SingleNodeDurableIntegrationProof(
        observed=observed,
        durable_truth=durable,
        production_components_verified=production,
        production_causality_verified=False,
        status="PRODUCTION_COMPONENTS_DURABLE_TRUTH_MATCHED_CAUSALITY_NOT_PROVEN",
    )
    runner.run = lambda **_: proof
    return runner


def test_boundary_double_cannot_enter_production_causality_integration():
    with pytest.raises(RuntimeError, match="PRODUCTION_CAUSALITY_PRODUCTION_RUNNER_REQUIRED"):
        ProductionCausalityIntegrationRunner(composed_runner=_composed_runner(production=False))


def test_complete_production_composed_proof_promotes_causality_only():
    promoted = ProductionCausalityIntegrationRunner(composed_runner=_composed_runner()).run(test_run_id="run-1")
    assert promoted.production_causality_verified is True
    assert promoted.status == "PRODUCTION_CAUSALITY_VERIFIED"
    assert promoted.bank_reality_verified is False
    assert promoted.release_status == "HOLD"


def test_incomplete_durable_denominator_fails_closed():
    runner = _composed_runner()
    original = runner.run(test_run_id="run-1")
    bad_durable = SimpleNamespace(
        verified_work_items=original.durable_truth.verified_work_items,
        verified_attempts=original.durable_truth.verified_attempts,
        verified_artifacts=original.durable_truth.verified_artifacts[:-1],
        verified_r1_start_events=original.durable_truth.verified_r1_start_events,
        verified_r1_events=original.durable_truth.verified_r1_events,
        bank_reality_verified=False,
        release_status="HOLD",
    )
    runner.run = lambda **_: SingleNodeDurableIntegrationProof(
        observed=original.observed,
        durable_truth=bad_durable,
        production_components_verified=True,
        production_causality_verified=False,
        status=original.status,
    )
    with pytest.raises(RuntimeError, match="PRODUCTION_CAUSALITY_PROMOTION_REJECTED:PRODUCTION_DURABLE_TRUTH_NOT_VERIFIED"):
        ProductionCausalityIntegrationRunner(composed_runner=runner).run(test_run_id="run-1")
