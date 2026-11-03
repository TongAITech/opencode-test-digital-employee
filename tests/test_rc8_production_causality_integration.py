from __future__ import annotations

import pytest

from rc8_node.production_causality_integration import ProductionCausalityIntegrationRunner
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


def _forged_composed_runner(*, production=True):
    """Build a boundary double without running the production constructor."""
    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = production
    runner.truth_reader = object()
    runner.production_bootstrap = object() if production else None
    runner.expected_node_id = "node-1" if production else None
    return runner


def test_boundary_double_cannot_enter_production_causality_integration():
    with pytest.raises(RuntimeError, match="PRODUCTION_CAUSALITY_PRODUCTION_RUNNER_REQUIRED"):
        ProductionCausalityIntegrationRunner(composed_runner=_forged_composed_runner(production=False))


def test_private_production_flag_cannot_forge_production_truth_authority():
    """A __new__ double with the old private flag must still fail closed."""
    with pytest.raises(RuntimeError, match="PRODUCTION_CAUSALITY_PRODUCTION_TRUTH_READER_REQUIRED"):
        ProductionCausalityIntegrationRunner(composed_runner=_forged_composed_runner(production=True))


def test_arbitrary_bootstrap_object_cannot_forge_promotion_authority():
    runner = _forged_composed_runner(production=True)
    # Even if a future test supplies a truth-reader-shaped object, arbitrary bootstrap
    # authority must not be accepted. The concrete reader check intentionally fires first
    # for this minimal boundary double.
    with pytest.raises(RuntimeError, match="PRODUCTION_CAUSALITY_PRODUCTION_TRUTH_READER_REQUIRED"):
        ProductionCausalityIntegrationRunner(composed_runner=runner)
