"""Production-only bootstrap gate for RC8 SINGLE_NODE causality proof.

This bridge is intentionally narrow: after the durable preflight proves that a
fresh TestRun has no WorkItem/Attempt/Artifact/R1 attempt-lifecycle truth, it asks
the production Center AutonomousMissionProgressor to materialize the first READY
work item. Tests must not pre-seed this record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from rc8_center.autonomous_progression import AutonomousMissionProgressor
from rc8_center.control_plane import WorkItemState
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader


class ProductionSingleNodeBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionSingleNodeBootstrapProof:
    test_run_id: str
    work_item_id: str
    stage_instance_id: str
    stage: str
    truth_note: str = "CENTER_AUTONOMOUS_PROGRESSION_MATERIALIZED_INITIAL_WORK"


class ProductionSingleNodeBootstrap:
    """Materialize and verify the first WorkItem through production Center services."""

    def __init__(
        self,
        *,
        progressor: AutonomousMissionProgressor,
        truth_reader: ProductionCenterR1TruthReader,
    ) -> None:
        if not isinstance(progressor, AutonomousMissionProgressor):
            raise ProductionSingleNodeBootstrapError("PRODUCTION_PROGRESSOR_REQUIRED")
        if not isinstance(truth_reader, ProductionCenterR1TruthReader):
            raise ProductionSingleNodeBootstrapError("PRODUCTION_TRUTH_READER_REQUIRED")
        if progressor.control_repository is not truth_reader.center_repository:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_CENTER_REPOSITORY_IDENTITY_MISMATCH")
        self.progressor = progressor
        self.truth_reader = truth_reader

    def materialize_initial_ready_work(self, *, test_run_id: str) -> ProductionSingleNodeBootstrapProof:
        run_id = str(test_run_id or "").strip()
        if not run_id:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_TEST_RUN_ID_REQUIRED")

        # Called only after the composed runner's clean production preflight.
        # Re-check here so a race or fixture cannot insert a WorkItem between
        # preflight and Center materialization.
        before = self._work_items_for_run(run_id)
        if before:
            raise ProductionSingleNodeBootstrapError(
                "PRODUCTION_INITIAL_WORK_PREEXISTS:%s"
                % ",".join(sorted(item.identity.work_item_id for item in before))
            )

        _newly_ready, materialized = self.progressor.materialize_ready_work(run_id)
        materialized_ids = tuple(str(value).strip() for value in materialized if str(value).strip())
        if len(materialized_ids) != 1:
            raise ProductionSingleNodeBootstrapError(
                "PRODUCTION_INITIAL_WORK_CARDINALITY_MISMATCH:%s" % len(materialized_ids)
            )

        after = self._work_items_for_run(run_id)
        if len(after) != 1:
            raise ProductionSingleNodeBootstrapError(
                "PRODUCTION_INITIAL_DURABLE_WORK_CARDINALITY_MISMATCH:%s" % len(after)
            )
        work = after[0]
        if work.identity.work_item_id != materialized_ids[0]:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_INITIAL_WORK_IDENTITY_MISMATCH")
        if work.identity.stage != "SCOPE_INTAKE":
            raise ProductionSingleNodeBootstrapError(
                "PRODUCTION_INITIAL_STAGE_NOT_SCOPE_INTAKE:%s" % work.identity.stage
            )
        if work.state != WorkItemState.READY:
            raise ProductionSingleNodeBootstrapError(
                "PRODUCTION_INITIAL_WORK_NOT_READY:%s" % work.state.value
            )

        link = self.progressor.control_repository.get_stage_link_for_work_item(work.identity.work_item_id)
        if link is None:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_INITIAL_STAGE_LINK_MISSING")
        if str(link.test_run_id) != run_id:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_INITIAL_STAGE_LINK_TEST_RUN_MISMATCH")
        stage = self.progressor.governance_repository.get_stage(str(link.stage_instance_id))
        if stage is None:
            raise ProductionSingleNodeBootstrapError("PRODUCTION_INITIAL_STAGE_NOT_FOUND")
        if stage.test_run_id != run_id or stage.stage_type != "SCOPE_INTAKE":
            raise ProductionSingleNodeBootstrapError("PRODUCTION_INITIAL_STAGE_IDENTITY_MISMATCH")

        return ProductionSingleNodeBootstrapProof(
            test_run_id=run_id,
            work_item_id=work.identity.work_item_id,
            stage_instance_id=stage.stage_instance_id,
            stage=stage.stage_type,
        )

    def _work_items_for_run(self, test_run_id: str) -> Tuple[object, ...]:
        return tuple(
            item
            for item in self.truth_reader.center_repository.list_work_items()
            if item.identity.test_run_id == test_run_id
        )
