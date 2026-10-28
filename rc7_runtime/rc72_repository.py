"""Canonical RC7.2 repository with cross-entity lineage enforcement.

The low-level R1 adapter validates entity shape. This repository validates
relationships before append so autonomous workers cannot create orphan
coverage-driven obligations/ETUs outside the ReleaseBatch business tree.
"""
from __future__ import annotations

from typing import Any, Dict, List

from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import (
    BackEdge,
    ExecutionTaskUnit,
    MissionNodeRecord,
    NodeDelivery,
    NodeGate,
    ReleaseBatch,
    TestObligation,
)
from .rc72_truth import append_rc72_entity


class RC72LineageError(ContractError):
    pass


class CanonicalRC72Repository:
    """Persist RC7.2 entities into R1 only after canonical lineage checks."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        if not isinstance(release_id, str) or not release_id.strip():
            raise RC72LineageError("RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def persist(self, entity: Any, *, artifact_version: int = 1):
        self._validate_lineage(entity)
        return append_rc72_entity(
            self.truth,
            entity,
            release_id=self.release_id,
            artifact_version=artifact_version,
        )

    def query(self, artifact_type: str, **filters: Any) -> List[Dict[str, Any]]:
        return self.truth.query(artifact_type, **filters)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            identity = ",".join("%s=%s" % (key, value) for key, value in sorted(filters.items()))
            raise RC72LineageError(
                "RC72_PARENT_NOT_UNIQUE:%s:%s:%s" % (artifact_type, identity, len(rows))
            )
        return rows[0]

    def _batch_for_mission(self, mission_id: str) -> Dict[str, Any]:
        return self._one("rc72_release_batch", mission_id=mission_id)

    def _validate_lineage(self, entity: Any) -> None:
        if isinstance(entity, ReleaseBatch):
            return

        if isinstance(entity, MissionNodeRecord):
            self._batch_for_mission(entity.mission_id)
            return

        if isinstance(entity, NodeDelivery):
            self._batch_for_mission(entity.mission_id)
            node = self._one("rc72_mission_node", mission_node_id=entity.mission_node_id)
            if node.get("mission_id") != entity.mission_id:
                raise RC72LineageError("NODE_DELIVERY_MISSION_NODE_MISSION_MISMATCH")
            if node.get("node_type") != entity.node_type.value:
                raise RC72LineageError("NODE_DELIVERY_MISSION_NODE_TYPE_MISMATCH")
            return

        if isinstance(entity, NodeGate):
            node = self._one("rc72_mission_node", mission_node_id=entity.mission_node_id)
            if node.get("mission_id") != entity.mission_id:
                raise RC72LineageError("NODE_GATE_MISSION_NODE_MISSION_MISMATCH")
            if node.get("node_type") != entity.node_type.value:
                raise RC72LineageError("NODE_GATE_MISSION_NODE_TYPE_MISMATCH")
            delivery = self._one("rc72_node_delivery", delivery_id=entity.delivery_id)
            if delivery.get("mission_id") != entity.mission_id:
                raise RC72LineageError("NODE_GATE_DELIVERY_MISSION_MISMATCH")
            if delivery.get("mission_node_id") != entity.mission_node_id:
                raise RC72LineageError("NODE_GATE_DELIVERY_MISSION_NODE_MISMATCH")
            if delivery.get("node_type") != entity.node_type.value:
                raise RC72LineageError("NODE_GATE_DELIVERY_NODE_TYPE_MISMATCH")
            return

        if isinstance(entity, TestObligation):
            batch = self._one("rc72_release_batch", release_batch_id=entity.release_batch_id)
            if batch.get("mission_id") != entity.mission_id:
                raise RC72LineageError("TEST_OBLIGATION_RELEASE_BATCH_MISSION_MISMATCH")
            requirement_ids = batch.get("requirement_ids") or []
            application_ids = batch.get("application_ids") or []
            if requirement_ids and entity.requirement_id not in requirement_ids:
                raise RC72LineageError("TEST_OBLIGATION_REQUIREMENT_OUTSIDE_RELEASE_BATCH")
            if application_ids and entity.application_id not in application_ids:
                raise RC72LineageError("TEST_OBLIGATION_APPLICATION_OUTSIDE_RELEASE_BATCH")
            return

        if isinstance(entity, ExecutionTaskUnit):
            obligation = self._one("rc72_test_obligation", obligation_id=entity.obligation_id)
            if obligation.get("mission_id") != entity.mission_id:
                raise RC72LineageError("ETU_OBLIGATION_MISSION_MISMATCH")
            if obligation.get("release_batch_id") != entity.release_batch_id:
                raise RC72LineageError("ETU_OBLIGATION_RELEASE_BATCH_MISMATCH")
            return

        if isinstance(entity, BackEdge):
            gap = self._one("rc7_gap", gap_id=entity.gap_id)
            if gap.get("mission_id") != entity.mission_id:
                raise RC72LineageError("BACK_EDGE_GAP_MISSION_MISMATCH")
            delivery = self._one("rc72_node_delivery", delivery_id=entity.from_delivery_id)
            if delivery.get("mission_id") != entity.mission_id:
                raise RC72LineageError("BACK_EDGE_DELIVERY_MISSION_MISMATCH")
            if delivery.get("node_type") != entity.from_node.value:
                raise RC72LineageError("BACK_EDGE_FROM_NODE_DELIVERY_MISMATCH")
            if entity.resolved_by_delivery_id:
                resolved = self._one("rc72_node_delivery", delivery_id=entity.resolved_by_delivery_id)
                if resolved.get("mission_id") != entity.mission_id:
                    raise RC72LineageError("BACK_EDGE_RESOLUTION_DELIVERY_MISSION_MISMATCH")
                if resolved.get("node_type") != entity.return_node.value:
                    raise RC72LineageError("BACK_EDGE_RESOLUTION_DELIVERY_NODE_MISMATCH")
            return

        raise TypeError("UNSUPPORTED_RC72_ENTITY")
