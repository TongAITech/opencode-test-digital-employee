"""Center-owned AI Director runtime election and failover.

The Center remains non-AI. It elects a Director host only from verified nodes and
never grants the Director role domain-execution authority. A lost Director is
re-elected in DISTRIBUTED mode; SINGLE_NODE fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .control_plane import CenterControlError, CenterRepository, NodeStatus
from .distributed_orchestration import ExecutionMode, NodePlacementScheduler


@dataclass(frozen=True)
class DirectorRuntimeState:
    node_id: str
    generation: int
    reason: str


class DirectorRuntimeLifecycle:
    """Deterministic Center-side Director election without model calls."""

    def __init__(self, repository: CenterRepository) -> None:
        self.repository = repository
        self.scheduler = NodePlacementScheduler(repository)
        self._state: Optional[DirectorRuntimeState] = None

    @property
    def state(self) -> Optional[DirectorRuntimeState]:
        return self._state

    def elect(self, preferred_node_id: Optional[str] = None) -> DirectorRuntimeState:
        node = self.scheduler.select_director_node(preferred_node_id)
        generation = 1 if self._state is None else self._state.generation + 1
        reason = "INITIAL_ELECTION" if self._state is None else "DIRECTOR_REELECTED"
        self._state = DirectorRuntimeState(node.identity.node_id, generation, reason)
        return self._state

    def reconcile(
        self,
        mode: ExecutionMode,
        *,
        single_node_id: Optional[str] = None,
    ) -> DirectorRuntimeState:
        if self._state is None:
            preferred = single_node_id if mode == ExecutionMode.SINGLE_NODE else None
            return self.elect(preferred)

        current = self.repository.get_node(self._state.node_id)
        if current is not None and current.status not in {
            NodeStatus.MAINTENANCE,
            NodeStatus.OFFLINE,
            NodeStatus.ERROR,
        }:
            # Re-validate Director capabilities on every reconciliation so a
            # qualification downgrade cannot leave a stale Director active.
            try:
                self.scheduler.select_director_node(self._state.node_id)
                return self._state
            except CenterControlError:
                pass

        if mode == ExecutionMode.SINGLE_NODE:
            target = (single_node_id or self._state.node_id).strip()
            # Fail closed: never move a SINGLE_NODE mission to another PC.
            self.scheduler.select_director_node(target)
            raise CenterControlError("SINGLE_NODE_DIRECTOR_RECOVERY_FORBIDDEN")

        old_node_id = self._state.node_id
        replacement = self.scheduler.select_director_node()
        if replacement.identity.node_id == old_node_id:
            raise CenterControlError("DIRECTOR_REPLACEMENT_REQUIRED")
        self._state = DirectorRuntimeState(
            replacement.identity.node_id,
            self._state.generation + 1,
            "DIRECTOR_FAILOVER",
        )
        return self._state
