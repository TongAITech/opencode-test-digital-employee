"""RC8 two-level orchestration policy.

Center is a non-AI control plane. AI Director is a runtime role placed on an
AI-capable dsh-node. Domain work is always executed by node-local team runtime,
never by the Director role itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Set

from rc8_runtime import CapabilityState
from .control_plane import CenterControlError, CenterRepository, NodeRecord, NodeStatus, WorkItemRecord


class ExecutionMode(str, Enum):
    SINGLE_NODE = "SINGLE_NODE"
    DISTRIBUTED = "DISTRIBUTED"


class ActorRole(str, Enum):
    CENTER = "CENTER"
    DIRECTOR = "DIRECTOR"
    DSH_NODE = "DSH_NODE"
    TEAM_WORKER = "TEAM_WORKER"


DOMAIN_EXECUTION_ACTIONS: Set[str] = {
    "BROWSER_EXECUTION",
    "CODEGRAPH_EXECUTION",
    "SQL_EXECUTION",
    "PYTEST_EXECUTION",
    "JUNIT_EXECUTION",
    "API_EXECUTION",
    "UI_EXECUTION",
    "E2E_EXECUTION",
}


@dataclass(frozen=True)
class PlacementPolicy:
    mode: ExecutionMode
    target_node_id: Optional[str] = None
    director_node_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode == ExecutionMode.SINGLE_NODE and not (self.target_node_id or "").strip():
            raise CenterControlError("SINGLE_NODE_TARGET_REQUIRED")


@dataclass(frozen=True)
class PlacementDecision:
    work_item_id: str
    node_id: str
    mode: ExecutionMode
    reason: str


class DirectorExecutionFence:
    """Fail closed when the AI Director attempts domain execution."""

    @staticmethod
    def authorize(actor_role: ActorRole, action: str) -> None:
        normalized = (action or "").strip().upper()
        if not normalized:
            raise CenterControlError("ACTION_REQUIRED")
        if actor_role == ActorRole.DIRECTOR and normalized in DOMAIN_EXECUTION_ACTIONS:
            raise CenterControlError("DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN:%s" % normalized)

    @staticmethod
    def evidence_counts_for_sufficiency(actor_role: ActorRole, evidence_type: str) -> bool:
        normalized = (evidence_type or "").strip().upper()
        if actor_role == ActorRole.DIRECTOR and normalized in DOMAIN_EXECUTION_ACTIONS:
            return False
        return True


class NodePlacementScheduler:
    """Capability-aware placement for SINGLE_NODE and DISTRIBUTED modes.

    The scheduler never calls a model. It only reads Center node/capability truth.
    """

    def __init__(self, repository: CenterRepository) -> None:
        self.repository = repository

    def place(self, work: WorkItemRecord, policy: PlacementPolicy) -> PlacementDecision:
        if policy.mode == ExecutionMode.SINGLE_NODE:
            node_id = (policy.target_node_id or "").strip()
            node = self._eligible_node(node_id, work.identity.required_capabilities)
            return PlacementDecision(work.identity.work_item_id, node.identity.node_id, policy.mode, "SINGLE_NODE_PIN")

        candidates = self._eligible_nodes(work.identity.required_capabilities)
        if not candidates:
            raise CenterControlError("NO_CAPABLE_NODE_AVAILABLE")

        # Prefer an idle worker and avoid the Director host when another capable
        # node exists. The Director host may still execute via a node-local team;
        # the Director role itself remains fenced from domain execution.
        director_id = (policy.director_node_id or "").strip()
        candidates.sort(
            key=lambda node: (
                node.identity.node_id == director_id,
                node.status != NodeStatus.IDLE,
                node.identity.node_id,
            )
        )
        chosen = candidates[0]
        return PlacementDecision(work.identity.work_item_id, chosen.identity.node_id, policy.mode, "CAPABILITY_AWARE")

    def select_director_node(self, preferred_node_id: Optional[str] = None) -> NodeRecord:
        required = ["ai_model", "dsh", "director_runtime"]
        if preferred_node_id:
            return self._eligible_node(preferred_node_id, required)
        candidates = self._eligible_nodes(required)
        if not candidates:
            raise CenterControlError("NO_DIRECTOR_CAPABLE_NODE_AVAILABLE")
        candidates.sort(key=lambda node: (node.status != NodeStatus.IDLE, node.identity.node_id))
        return candidates[0]

    def _eligible_nodes(self, required: Sequence[str]) -> List[NodeRecord]:
        result: List[NodeRecord] = []
        for node in self.repository.list_nodes():
            if node.status in {NodeStatus.MAINTENANCE, NodeStatus.OFFLINE, NodeStatus.ERROR}:
                continue
            if self._has_verified_capabilities(node.identity.node_id, required):
                result.append(node)
        return result

    def _eligible_node(self, node_id: str, required: Sequence[str]) -> NodeRecord:
        node = self.repository.get_node(node_id)
        if node is None:
            raise CenterControlError("NODE_NOT_REGISTERED")
        if node.status in {NodeStatus.MAINTENANCE, NodeStatus.OFFLINE, NodeStatus.ERROR}:
            raise CenterControlError("NODE_NOT_PLACEMENT_ELIGIBLE")
        if not self._has_verified_capabilities(node_id, required):
            raise CenterControlError("NODE_REQUIRED_CAPABILITY_NOT_VERIFIED")
        return node

    def _has_verified_capabilities(self, node_id: str, required: Iterable[str]) -> bool:
        for capability_id in required:
            value = self.repository.get_capability(node_id, capability_id)
            if value is None or value.state != CapabilityState.VERIFIED:
                return False
        return True
