from types import SimpleNamespace

import pytest

from rc8_center.control_plane import WorkItemState
from rc8_node.single_node_production_bootstrap import (
    ProductionSingleNodeBootstrap,
    ProductionSingleNodeBootstrapError,
)


class _ControlRepository:
    def __init__(self):
        self.items = []
        self.links = {}

    def list_work_items(self):
        return list(self.items)

    def get_stage_link_for_work_item(self, work_item_id):
        return self.links.get(work_item_id)


class _GovernanceRepository:
    def __init__(self):
        self.stages = {}

    def get_stage(self, stage_instance_id):
        return self.stages.get(stage_instance_id)


class _Progressor:
    def __init__(self, control, governance):
        self.control_repository = control
        self.governance_repository = governance

    def materialize_ready_work(self, test_run_id):
        work = SimpleNamespace(
            identity=SimpleNamespace(
                work_item_id="work-scope-1",
                test_run_id=test_run_id,
                stage="SCOPE_INTAKE",
            ),
            state=WorkItemState.READY,
        )
        self.control_repository.items.append(work)
        self.control_repository.links[work.identity.work_item_id] = SimpleNamespace(
            test_run_id=test_run_id,
            stage_instance_id="stage-scope-1",
        )
        self.governance_repository.stages["stage-scope-1"] = SimpleNamespace(
            test_run_id=test_run_id,
            stage_instance_id="stage-scope-1",
            stage_type="SCOPE_INTAKE",
        )
        return (("stage-scope-1",), (work.identity.work_item_id,))


def _bootstrap(progressor, control):
    # Constructor type checks intentionally protect production wiring. These unit
    # tests isolate the post-preflight materialization invariant itself.
    bootstrap = object.__new__(ProductionSingleNodeBootstrap)
    bootstrap.progressor = progressor
    bootstrap.truth_reader = SimpleNamespace(center_repository=control)
    return bootstrap


def test_materializes_exactly_one_initial_scope_intake_work_item():
    control = _ControlRepository()
    governance = _GovernanceRepository()
    progressor = _Progressor(control, governance)
    proof = _bootstrap(progressor, control).materialize_initial_ready_work(test_run_id="run-1")

    assert proof.test_run_id == "run-1"
    assert proof.work_item_id == "work-scope-1"
    assert proof.stage_instance_id == "stage-scope-1"
    assert proof.stage == "SCOPE_INTAKE"


def test_rejects_preseeded_work_before_center_materialization():
    control = _ControlRepository()
    control.items.append(
        SimpleNamespace(
            identity=SimpleNamespace(
                work_item_id="fixture-work",
                test_run_id="run-1",
                stage="SCOPE_INTAKE",
            ),
            state=WorkItemState.READY,
        )
    )
    progressor = _Progressor(control, _GovernanceRepository())

    with pytest.raises(ProductionSingleNodeBootstrapError, match="PRODUCTION_INITIAL_WORK_PREEXISTS"):
        _bootstrap(progressor, control).materialize_initial_ready_work(test_run_id="run-1")


def test_rejects_multiple_initial_materializations():
    control = _ControlRepository()
    governance = _GovernanceRepository()
    progressor = _Progressor(control, governance)

    def _multiple(test_run_id):
        return (("stage-1", "stage-2"), ("work-1", "work-2"))

    progressor.materialize_ready_work = _multiple

    with pytest.raises(ProductionSingleNodeBootstrapError, match="PRODUCTION_INITIAL_WORK_CARDINALITY_MISMATCH:2"):
        _bootstrap(progressor, control).materialize_initial_ready_work(test_run_id="run-1")
