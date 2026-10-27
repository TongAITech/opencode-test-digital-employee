"""Repository contract for Center-owned MissionNode current truth."""
from __future__ import annotations

from typing import Dict, Optional, Protocol, Tuple

from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeInstance


class MissionNodeRepositoryError(RuntimeError):
    pass


class MissionNodeRepository(Protocol):
    def save(self, node: MissionNodeInstance) -> None:
        ...

    def get(self, mission_node_id: str) -> Optional[MissionNodeInstance]:
        ...

    def list_for_test_run(self, test_run_id: str) -> Tuple[MissionNodeInstance, ...]:
        ...


class MemoryMissionNodeRepository:
    """Test adapter with the same identity guards as the PostgreSQL adapter."""

    def __init__(self) -> None:
        self._nodes: Dict[str, MissionNodeInstance] = {}

    def save(self, node: MissionNodeInstance) -> None:
        if not isinstance(node, MissionNodeInstance):
            raise MissionNodeRepositoryError("MISSION_NODE_INSTANCE_REQUIRED")
        existing = self._nodes.get(node.mission_node_id)
        if existing is not None:
            self._require_same_identity(existing, node)
        for other in self._nodes.values():
            if (
                other.mission_node_id != node.mission_node_id
                and other.test_run_id == node.test_run_id
                and other.node_type == node.node_type
            ):
                raise MissionNodeRepositoryError("MISSION_NODE_TYPE_ALREADY_EXISTS_FOR_TEST_RUN")
        self._nodes[node.mission_node_id] = node

    def get(self, mission_node_id: str) -> Optional[MissionNodeInstance]:
        return self._nodes.get(mission_node_id)

    def list_for_test_run(self, test_run_id: str) -> Tuple[MissionNodeInstance, ...]:
        order = {node_type: index for index, node_type in enumerate(MISSION_NODE_SEQUENCE)}
        nodes = [node for node in self._nodes.values() if node.test_run_id == test_run_id]
        nodes.sort(key=lambda node: order[node.node_type])
        return tuple(nodes)

    @staticmethod
    def _require_same_identity(existing: MissionNodeInstance, candidate: MissionNodeInstance) -> None:
        if existing.test_run_id != candidate.test_run_id:
            raise MissionNodeRepositoryError("MISSION_NODE_TEST_RUN_IMMUTABLE")
        if existing.node_type != candidate.node_type:
            raise MissionNodeRepositoryError("MISSION_NODE_TYPE_IMMUTABLE")
        if existing.scope_version != candidate.scope_version:
            raise MissionNodeRepositoryError("MISSION_NODE_SCOPE_VERSION_IMMUTABLE")
        if existing.predecessor_node_ids != candidate.predecessor_node_ids:
            raise MissionNodeRepositoryError("MISSION_NODE_PREDECESSORS_IMMUTABLE")
