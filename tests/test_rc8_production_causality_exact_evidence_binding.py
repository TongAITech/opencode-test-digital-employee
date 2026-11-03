from dataclasses import replace

from rc8_node.production_causality_integration import ProductionCausalityIntegrationRunner
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES, SingleNodeFullLoopProof
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProof
from rc8_node.single_node_truth import SingleNodeTruthProof


def _proof():
    n = len(FROZEN_N1_N10_STAGES)
    observed = SingleNodeFullLoopProof(
        test_run_id="tr-exact-evidence",
        stages=FROZEN_N1_N10_STAGES,
        work_item_ids=tuple(f"wi-{i}" for i in range(n)),
        lease_ids=tuple(f"attempt-{i}" for i in range(n)),
        stage_instance_ids=tuple(f"si-{i}" for i in range(n)),
        attempt_ids=tuple(f"attempt-{i}" for i in range(n)),
        evidence_refs=tuple(f"artifact:ev-{i}" for i in range(n)),
        terminal_center_idle=True,
    )
    durable = SingleNodeTruthProof(
        test_run_id=observed.test_run_id,
        verified_work_items=observed.work_item_ids,
        verified_attempts=observed.attempt_ids,
        verified_artifacts=observed.evidence_refs,
        verified_r1_start_events=tuple(f"start-{i}" for i in range(n)),
        verified_r1_events=tuple(f"done-{i}" for i in range(n)),
    )
    return SingleNodeDurableIntegrationProof(
        observed=observed,
        durable_truth=durable,
        production_components_verified=True,
        production_causality_verified=False,
        status="DURABLE_MATCHED_NOT_PROMOTED",
    )


def test_exact_durable_evidence_identity_denominator_is_accepted():
    assert ProductionCausalityIntegrationRunner._durable_truth_verified(_proof()) is True


def test_same_cardinality_stale_artifact_identity_fails_closed():
    proof = _proof()
    stale = replace(
        proof.durable_truth,
        verified_artifacts=tuple(f"artifact:stale-{i}" for i in range(len(FROZEN_N1_N10_STAGES))),
    )
    forged = replace(proof, durable_truth=stale)
    assert ProductionCausalityIntegrationRunner._durable_truth_verified(forged) is False
