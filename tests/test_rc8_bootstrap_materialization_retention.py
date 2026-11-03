from types import SimpleNamespace

from rc8_node.production_causality_integration import ProductionCausalityIntegrationRunner
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES


def _proof(*, production=True, stages=FROZEN_N1_N10_STAGES, work_items=("wi-1",), stage_instances=("si-1",)):
    return SimpleNamespace(
        production_components_verified=production,
        observed=SimpleNamespace(
            stages=tuple(stages),
            work_item_ids=tuple(work_items),
            stage_instance_ids=tuple(stage_instances),
        ),
    )


def test_bootstrap_materialization_is_retained_from_composed_proof_surface():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof()) is True


def test_bootstrap_materialization_fails_closed_without_production_authority():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(production=False)) is False


def test_bootstrap_materialization_fails_closed_without_first_claim_identity():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(work_items=())) is False
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(_proof(stage_instances=())) is False


def test_bootstrap_materialization_fails_closed_on_denominator_drift():
    assert ProductionCausalityIntegrationRunner._bootstrap_materialization_retained(
        _proof(stages=FROZEN_N1_N10_STAGES[1:])
    ) is False
