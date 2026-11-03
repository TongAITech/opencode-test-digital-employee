from types import SimpleNamespace
from rc8_node.production_causality_integration import ProductionCausalityIntegrationRunner


def _proof(*, production=True, materialized=True, proof_wi="wi-1", proof_si="si-1", work_items=("wi-1",), stage_instances=("si-1",)):
    return SimpleNamespace(production_components_verified=production, bootstrap_materialized=materialized, bootstrap_work_item_id=proof_wi, bootstrap_stage_instance_id=proof_si, observed=SimpleNamespace(work_item_ids=tuple(work_items), stage_instance_ids=tuple(stage_instances)))


def test_bootstrap_materialization_is_retained_from_explicit_composed_proof_surface():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof()) is True


def test_bootstrap_materialization_fails_closed_without_explicit_materialization_fact():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(materialized=False)) is False


def test_bootstrap_materialization_fails_closed_without_production_authority():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(production=False)) is False


def test_bootstrap_materialization_fails_closed_when_retained_identity_differs_from_first_claim():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(proof_wi="stale-wi")) is False
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(proof_si="stale-si")) is False


def test_bootstrap_materialization_fails_closed_without_first_claim_identity():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(work_items=())) is False
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(stage_instances=())) is False
