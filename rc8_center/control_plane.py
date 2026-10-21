"""RC8 Center control-plane domain service.

This is the W1 transport-neutral core. It deliberately separates durable
Center state from DSH Session state and requires verified capabilities before
a node may lease work. A persistence adapter is injected; the memory adapter
exists only for deterministic unit tests and is not the production database.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol

from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    NodeIdentity,
    RuntimeEventEnvelope,
    WorkItemIdentity,
)


class CenterControlError(ValueError):
    pass


class NodeStatus(str, Enum):
    ONLINE = "ONLINE"
    IDLE = "IDLE"
    EXECUTING = "EXECUTING"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


class WorkItemState(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class NodeRecord:
    identity: NodeIdentity
    status: NodeStatus
    first_registered_at: int
    last_heartbeat_at: int


@dataclass(frozen=True)
class WorkItemRecord:
    identity: WorkItemIdentity
    state: WorkItemState = WorkItemState.REGISTERED
    lease_id: Optional[str] = None
    lease_owner_node_id: Optional[str] = None
    lease_expires_at: Optional[int] = None


class CenterRepository(Protocol):
    def get_node(self, node_id: str) -> Optional[NodeRecord]: ...
    def upsert_node(self, node: NodeRecord) -> None: ...
    def list_nodes(self) -> List[NodeRecord]: ...
    def get_capability(self, node_id: str, capability_id: str) -> Optional[CapabilityQualification]: ...
    def upsert_capability(self, value: CapabilityQualification) -> None: ...
    def list_capabilities(self, node_id: str) -> List[CapabilityQualification]: ...
    def get_work_item(self, work_item_id: str) -> Optional[WorkItemRecord]: ...
    def upsert_work_item(self, value: WorkItemRecord) -> None: ...
    def list_work_items(self) -> List[WorkItemRecord]: ...


class MemoryCenterRepository:
    """Unit-test adapter only. Production W1 will use the Center DB adapter."""

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeRecord] = {}
        self._capabilities: Dict[str, CapabilityQualification] = {}
        self._work_items: Dict[str, WorkItemRecord] = {}

    @staticmethod
    def _cap_key(node_id: str, capability_id: str) -> str:
        return "%s::%s" % (node_id, capability_id)

    def get_node(self, node_id: str) -> Optional[NodeRecord]:
        return self._nodes.get(node_id)

    def upsert_node(self, node: NodeRecord) -> None:
        self._nodes[node.identity.node_id] = node

    def list_nodes(self) -> List[NodeRecord]:
        return [self._nodes[key] for key in sorted(self._nodes)]

    def get_capability(self, node_id: str, capability_id: str) -> Optional[CapabilityQualification]:
        return self._capabilities.get(self._cap_key(node_id, capability_id))

    def upsert_capability(self, value: CapabilityQualification) -> None:
        self._capabilities[self._cap_key(value.node_id, value.capability_id)] = value

    def list_capabilities(self, node_id: str) -> List[CapabilityQualification]:
        return [
            self._capabilities[key]
            for key in sorted(self._capabilities)
            if key.startswith(node_id + "::")
        ]

    def get_work_item(self, work_item_id: str) -> Optional[WorkItemRecord]:
        return self._work_items.get(work_item_id)

    def upsert_work_item(self, value: WorkItemRecord) -> None:
        self._work_items[value.identity.work_item_id] = value

    def list_work_items(self) -> List[WorkItemRecord]:
        return [self._work_items[key] for key in sorted(self._work_items)]


class CenterControlPlane:
    def __init__(
        self,
        repository: CenterRepository,
        runtime_ledger: CentralR1RuntimeLedger,
        *,
        now_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.repository = repository
        self.runtime_ledger = runtime_ledger
        self._now = now_fn or (lambda: int(time.time()))

    def register_node(self, identity: NodeIdentity) -> NodeRecord:
        if not isinstance(identity, NodeIdentity):
            raise CenterControlError("NODE_IDENTITY_REQUIRED")
        now = self._now()
        current = self.repository.get_node(identity.node_id)
        if current is not None:
            if current.identity != identity:
                raise CenterControlError("NODE_IDENTITY_CONFLICT")
            updated = replace(current, status=NodeStatus.ONLINE, last_heartbeat_at=now)
            self.repository.upsert_node(updated)
            return updated
        record = NodeRecord(
            identity=identity,
            status=NodeStatus.ONLINE,
            first_registered_at=now,
            last_heartbeat_at=now,
        )
        self.repository.upsert_node(record)
        return record

    def heartbeat(self, node_id: str, *, status: Optional[NodeStatus] = None) -> NodeRecord:
        node = self._require_node(node_id)
        target = status or (NodeStatus.IDLE if node.status == NodeStatus.ONLINE else node.status)
        if not isinstance(target, NodeStatus):
            raise CenterControlError("NODE_STATUS_INVALID")
        updated = replace(node, status=target, last_heartbeat_at=self._now())
        self.repository.upsert_node(updated)
        return updated

    def qualify_capability(self, value: CapabilityQualification) -> CapabilityQualification:
        if not isinstance(value, CapabilityQualification):
            raise CenterControlError("CAPABILITY_QUALIFICATION_REQUIRED")
        self._require_node(value.node_id)
        self.repository.upsert_capability(value)
        return value

    def register_work_item(self, identity: WorkItemIdentity) -> WorkItemRecord:
        if not isinstance(identity, WorkItemIdentity):
            raise CenterControlError("WORK_ITEM_IDENTITY_REQUIRED")
        existing = self.repository.get_work_item(identity.work_item_id)
        if existing is not None:
            if existing.identity != identity:
                raise CenterControlError("WORK_ITEM_IDENTITY_CONFLICT")
            return existing
        record = WorkItemRecord(identity=identity, state=WorkItemState.READY)
        self.repository.upsert_work_item(record)
        return record

    def lease_work_item(self, work_item_id: str, node_id: str, *, ttl_seconds: int = 60) -> WorkItemRecord:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise CenterControlError("LEASE_TTL_INVALID")
        node = self._require_node(node_id)
        if node.status in {NodeStatus.MAINTENANCE, NodeStatus.OFFLINE, NodeStatus.ERROR}:
            raise CenterControlError("NODE_NOT_LEASE_ELIGIBLE")
        work = self._require_work_item(work_item_id)
        now = self._now()

        if work.lease_owner_node_id is not None and work.lease_expires_at is not None and work.lease_expires_at > now:
            if work.lease_owner_node_id != node_id:
                raise CenterControlError("WORK_ITEM_LEASE_HELD")
            renewed = replace(work, state=WorkItemState.LEASED, lease_expires_at=now + ttl_seconds)
            self.repository.upsert_work_item(renewed)
            return renewed

        if work.state in {WorkItemState.COMPLETED, WorkItemState.FAILED}:
            raise CenterControlError("WORK_ITEM_TERMINAL")
        self._require_capabilities(node_id, work.identity.required_capabilities)
        leased = replace(
            work,
            state=WorkItemState.LEASED,
            lease_id=str(uuid.uuid4()),
            lease_owner_node_id=node_id,
            lease_expires_at=now + ttl_seconds,
        )
        self.repository.upsert_work_item(leased)
        self.repository.upsert_node(replace(node, status=NodeStatus.EXECUTING, last_heartbeat_at=now))
        return leased

    def start_work_item(self, work_item_id: str, node_id: str) -> WorkItemRecord:
        work = self._require_active_lease(work_item_id, node_id)
        updated = replace(work, state=WorkItemState.RUNNING)
        self.repository.upsert_work_item(updated)
        return updated

    def authorize_work_item_write(self, *, test_run_id: str, work_item_id: str, node_id: str) -> WorkItemRecord:
        """Authorize a runtime/event/artifact write against the active node lease."""
        self._require_node(node_id)
        work = self._require_active_lease(work_item_id, node_id)
        if work.identity.test_run_id != test_run_id:
            raise CenterControlError("WORK_ITEM_TEST_RUN_MISMATCH")
        return work

    def append_runtime_event(self, event: RuntimeEventEnvelope) -> Dict[str, object]:
        self.authorize_work_item_write(
            test_run_id=event.test_run_id,
            work_item_id=event.work_item_id,
            node_id=event.node_id,
        )
        self.runtime_ledger.assert_next_node_sequence(event)
        return self.runtime_ledger.append_runtime(event)

    def complete_work_item(self, work_item_id: str, node_id: str) -> WorkItemRecord:
        work = self._require_active_lease(work_item_id, node_id)
        updated = replace(
            work,
            state=WorkItemState.COMPLETED,
            lease_id=None,
            lease_owner_node_id=None,
            lease_expires_at=None,
        )
        self.repository.upsert_work_item(updated)
        node = self._require_node(node_id)
        self.repository.upsert_node(replace(node, status=NodeStatus.IDLE, last_heartbeat_at=self._now()))
        return updated

    def _require_node(self, node_id: str) -> NodeRecord:
        if not isinstance(node_id, str) or not node_id.strip():
            raise CenterControlError("NODE_ID_REQUIRED")
        node = self.repository.get_node(node_id.strip())
        if node is None:
            raise CenterControlError("NODE_NOT_REGISTERED")
        return node

    def _require_work_item(self, work_item_id: str) -> WorkItemRecord:
        if not isinstance(work_item_id, str) or not work_item_id.strip():
            raise CenterControlError("WORK_ITEM_ID_REQUIRED")
        work = self.repository.get_work_item(work_item_id.strip())
        if work is None:
            raise CenterControlError("WORK_ITEM_NOT_FOUND")
        return work

    def _require_capabilities(self, node_id: str, required: List[str]) -> None:
        missing: List[str] = []
        for capability_id in required:
            value = self.repository.get_capability(node_id, capability_id)
            if value is None or value.state != CapabilityState.VERIFIED:
                missing.append(capability_id)
        if missing:
            raise CenterControlError("NODE_REQUIRED_CAPABILITY_NOT_VERIFIED:%s" % ",".join(sorted(missing)))

    def _require_active_lease(self, work_item_id: str, node_id: str) -> WorkItemRecord:
        work = self._require_work_item(work_item_id)
        now = self._now()
        if work.lease_owner_node_id != node_id or work.lease_expires_at is None or work.lease_expires_at <= now:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        return work
