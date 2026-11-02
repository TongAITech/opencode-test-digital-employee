from types import SimpleNamespace

import pytest

from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


def test_preseeded_work_item_fails_before_first_production_claim():
    reader = ProductionCenterR1TruthReader.__new__(ProductionCenterR1TruthReader)
    reader.center_repository = SimpleNamespace(
        list_work_items=lambda: [
            SimpleNamespace(identity=SimpleNamespace(work_item_id="wi-preseeded", test_run_id="run-dirty")),
            SimpleNamespace(identity=SimpleNamespace(work_item_id="wi-other-run", test_run_id="run-other")),
        ]
    )

    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner.truth_reader = reader

    with pytest.raises(
        RuntimeError,
        match="PRODUCTION_CAUSALITY_PREFLIGHT_WORK_ITEM_ALREADY_EXISTS:wi-preseeded",
    ):
        runner._assert_clean_production_preflight("run-dirty")
