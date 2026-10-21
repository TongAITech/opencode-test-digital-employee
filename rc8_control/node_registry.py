"""Deterministic RC8 node registry and lease rules for W1.

This first slice is storage-agnostic on purpose.  PostgreSQL/Redis adapters can
persist/coordinate these contracts later without changing qualification rules.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Iterable, List, Optional

from .models import (
    CapabilityState,
    ExecutionNode,
    LeaseState,
    NodeCapability,
    NodeStatus,
    WorkItemLease,
)


class NodeRegistryError(RuntimeError):
    """Raised for invalid RC8 node-control operations."""


_ALLOWED_CAPABILITY_TRANSITIONS = {
    CapabilityState.DISCOVERED: {
        CapabilityState.REGISTERED,
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.REGISTERED: {
        CapabilityState.EXECUTED,
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.EXECUTED: {
        CapabilityState.ASSERTED,
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.ASSERTED: {
        CapabilityState.EVIDENCE_PERSISTED,
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.EVIDENCE_PERSISTED: {
        CapabilityState.VERIFIED,
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.VERIFIED: {
        CapabilityState.ERROR,
        CapabilityState.UNAVAILABLE,
        CapabilityState.REGISTERED,
    },
    CapabilityState.ERROR: {
        CapabilityState.REGISTERED,
        CapabilityState.UNAVAILABLE,
    },
    CapabilityState.UNAVAILABLE: {
        CapabilityState.REGISTERED,
        CapabilityState.DISCOVERED,
    },
}


class NodeRegistry:
    """In-memory W1 domain service for node qualification and task leasing."""

    def __init__(self, offline_after_seconds: int = 60) -> None:
        if not isinstance(offline_after_seconds, int) or offline_after_seconds <= 0:
            raise ValueError("OFFLINE_AFTER_SECONDS_INVALID")
        self.offline_after_seconds = offline_after_seconds
        self._nodes: Dict[str, ExecutionNode] = {}
        self._leases_by_work_item: Dict[str, WorkItemLease] = {}

    @staticmethod
    def _now() -> int:
        return int(time.time())

    def register(self, node: ExecutionNode, now: Optional[int] = None) -> ExecutionNode:
        timestamp = self._now() if now is None else int(now)
        existing = self._nodes.get(node.node_id)
        if existing is not None:
            # Durable node identity is stable; a re-registration updates runtime
            # metadata but never silently carries a VERIFIED capability that the
            # new registration did not report/qualify.
            existing.display_name = node.display_name
            existing.platform = node.platform
            existing.architecture = node.architecture
            existing.operator = node.operator
            existing.package_version = node.package_version
            existing.status = NodeStatus.ONLINE
            existing.heartbeat_at = timestamp
            return existing
        node.registered_at = timestamp
        node.heartbeat_at = timestamp
        node.status = NodeStatus.ONLINE
        self._nodes[node.node_id] = node
        return node

    def get(self, node_id: str) -> ExecutionNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise NodeRegistryError("NODE_NOT_REGISTERED:%s" % node_id)

    def heartbeat(self, node_id: str, now: Optional[int] = None) -> ExecutionNode:
        node = self.get(node_id)
        timestamp = self._now() if now is None else int(now)
        node.heartbeat_at = timestamp
        if node.status == NodeStatus.OFFLINE:
            node.status = NodeStatus.ONLINE
        return node

    def refresh_liveness(self, now: Optional[int] = None) -> List[str]:
        timestamp = self._now() if now is None else int(now)
        offlined: List[str] = []
        for node in self._nodes.values():
            if node.status == NodeStatus.MAINTENANCE:
                continue
            if timestamp - node.heartbeat_at >= self.offline_after_seconds:
                if node.status != NodeStatus.OFFLINE:
                    node.status = NodeStatus.OFFLINE
                    offlined.append(node.node_id)
        return offlined

    def set_status(self, node_id: str, status: NodeStatus) -> ExecutionNode:
        node = self.get(node_id)
        node.status = status
        return node

    def report_capability(
        self,
        node_id: str,
        capability_name: str,
        state: CapabilityState,
        evidence_refs: Optional[List[str]] = None,
        detail: Optional[str] = None,
        now: Optional[int] = None,
    ) -> NodeCapability:
        node = self.get(node_id)
        timestamp = self._now() if now is None else int(now)
        evidence = list(evidence_refs or [])
        current = node.capabilities.get(capability_name)
        if current is None:
            current = NodeCapability(capability=capability_name)
            node.capabilities[capability_name] = current

        if state != current.state:
            allowed = _ALLOWED_CAPABILITY_TRANSITIONS[current.state]
            if state not in allowed:
                raise NodeRegistryError(
                    "CAPABILITY_TRANSITION_FORBIDDEN:%s:%s->%s"
                    % (capability_name, current.state.value, state.value)
                )

        if state == CapabilityState.VERIFIED and not evidence:
            # A node cannot become scheduler-eligible from self-report alone.
            raise NodeRegistryError("VERIFIED_CAPABILITY_REQUIRES_EVIDENCE:%s" % capability_name)

        current.state = state
        current.evidence_refs = evidence
        current.detail = detail
        if state == CapabilityState.VERIFIED:
            current.last_verified_at = timestamp
        return current

    def eligible_nodes(self, required_capabilities: Iterable[str], now: Optional[int] = None) -> List[ExecutionNode]:
        required = list(required_capabilities)
        self.refresh_liveness(now=now)
        eligible: List[ExecutionNode] = []
        for node in self._nodes.values():
            if node.status not in (NodeStatus.ONLINE, NodeStatus.IDLE):
                continue
            if node.has_verified_capabilities(required):
                eligible.append(node)
        eligible.sort(key=lambda item: item.node_id)
        return eligible

    def _active_lease(self, work_item_id: str, now: int) -> Optional[WorkItemLease]:
        lease = self._leases_by_work_item.get(work_item_id)
        if lease is None:
            return None
        if lease.state == LeaseState.ACTIVE and now >= lease.expires_at:
            lease.state = LeaseState.EXPIRED
            return None
        if lease.state == LeaseState.ACTIVE:
            return lease
        return None

    def lease_work_item(
        self,
        work_item_id: str,
        node_id: str,
        required_capabilities: List[str],
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> WorkItemLease:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise NodeRegistryError("LEASE_TTL_INVALID")
        timestamp = self._now() if now is None else int(now)
        node = self.get(node_id)
        self.refresh_liveness(now=timestamp)
        if node.status not in (NodeStatus.ONLINE, NodeStatus.IDLE):
            raise NodeRegistryError("NODE_NOT_LEASE_ELIGIBLE:%s:%s" % (node_id, node.status.value))
        if not node.has_verified_capabilities(required_capabilities):
            raise NodeRegistryError("NODE_CAPABILITY_REQUIREMENTS_NOT_MET:%s" % node_id)
        active = self._active_lease(work_item_id, timestamp)
        if active is not None:
            raise NodeRegistryError("WORK_ITEM_ALREADY_LEASED:%s:%s" % (work_item_id, active.node_id))

        lease = WorkItemLease(
            lease_id="LEASE-%s" % uuid.uuid4().hex,
            work_item_id=work_item_id,
            node_id=node_id,
            required_capabilities=list(required_capabilities),
            issued_at=timestamp,
            expires_at=timestamp + ttl_seconds,
        )
        self._leases_by_work_item[work_item_id] = lease
        node.status = NodeStatus.RUNNING
        return lease

    def renew_lease(
        self,
        work_item_id: str,
        node_id: str,
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> WorkItemLease:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise NodeRegistryError("LEASE_TTL_INVALID")
        timestamp = self._now() if now is None else int(now)
        lease = self._active_lease(work_item_id, timestamp)
        if lease is None:
            raise NodeRegistryError("ACTIVE_LEASE_NOT_FOUND:%s" % work_item_id)
        if lease.node_id != node_id:
            raise NodeRegistryError("LEASE_OWNER_MISMATCH:%s" % work_item_id)
        lease.expires_at = timestamp + ttl_seconds
        self.heartbeat(node_id, now=timestamp)
        return lease

    def release_lease(self, work_item_id: str, node_id: str) -> WorkItemLease:
        lease = self._leases_by_work_item.get(work_item_id)
        if lease is None or lease.state != LeaseState.ACTIVE:
            raise NodeRegistryError("ACTIVE_LEASE_NOT_FOUND:%s" % work_item_id)
        if lease.node_id != node_id:
            raise NodeRegistryError("LEASE_OWNER_MISMATCH:%s" % work_item_id)
        lease.state = LeaseState.RELEASED
        node = self.get(node_id)
        if node.status == NodeStatus.RUNNING:
            node.status = NodeStatus.IDLE
        return lease

    def lease_for(self, work_item_id: str, now: Optional[int] = None) -> Optional[WorkItemLease]:
        timestamp = self._now() if now is None else int(now)
        return self._active_lease(work_item_id, timestamp)
