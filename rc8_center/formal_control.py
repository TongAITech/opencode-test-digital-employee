"""Formal RC8 Center control plane.

PostgreSQL owns durable Node/Capability/WorkItem state. Redis owns the active
lease token. Runtime writes require both stores to agree, then persist to R1
before any governance projection runs.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Callable, Dict, List, Optional

from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    NodeIdentity,
    RuntimeEventEnvelope,
    WorkItemIdentity,
)

from .control_plane import CenterControlError, NodeRecord, NodeStatus, WorkItemRecord, WorkItemState
from .governance_event_projector import GovernanceEventProjector
from .infrastructure.postgres_control import PostgresCenterRepository
from .infrastructure.redis_coordination import RedisCoordination


class FormalCenterControlPlane:
    def __init__(
        self,
        repository: PostgresCenterRepository,
        coordination: RedisCoordination,
        runtime_ledger: CentralR1RuntimeLedger,
        projector: GovernanceEventProjector,
        *,
        now_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.repository = repository
        self.coordination = coordination
        self.runtime_ledger = runtime_ledger
        self.projector = projector
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
        record = NodeRecord(identity=identity, status=NodeStatus.ONLINE, first_registered_at=now, last_heartbeat_at=now)
        self.repository.upsert_node(record)
        return record

    def heartbeat(self, node_id: str, *, status: Optional[NodeStatus] = None) -> NodeRecord:
        node = self._require_node(node_id)
        target = status or (NodeStatus.IDLE if node.status == NodeStatus.ONLINE else node.status)
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
        if work.state in {WorkItemState.COMPLETED, WorkItemState.FAILED}:
            raise CenterControlError("WORK_ITEM_TERMINAL")
        self._require_capabilities(node_id, work.identity.required_capabilities)
        now = self._now()
        active = self.coordination.lease_info("work-item", work_item_id)
        if active is not None:
            active_owner = str(active.get("owner_id") or "")
            active_token = str(active.get("lease_id") or "")
            if active_owner != node_id:
                raise CenterControlError("WORK_ITEM_LEASE_HELD")
            if not work.lease_id or active_token != work.lease_id:
                raise CenterControlError("WORK_ITEM_LEASE_TOKEN_DIVERGED")
            if not self.coordination.renew_lease("work-item", work_item_id, node_id, ttl_seconds, lease_id=work.lease_id):
                raise CenterControlError("WORK_ITEM_LEASE_RENEW_FAILED")
            renewed = replace(work, state=WorkItemState.LEASED if work.state != WorkItemState.RUNNING else WorkItemState.RUNNING, lease_expires_at=now + ttl_seconds)
            self.repository.upsert_work_item(renewed)
            return renewed

        if work.lease_id is not None or work.state in {WorkItemState.LEASED, WorkItemState.RUNNING}:
            # Redis loss/expiry while durable state still says leased is a recovery
            # condition. Blind reacquire could duplicate a non-idempotent action.
            raise CenterControlError("WORK_ITEM_LEASE_RECOVERY_REQUIRED")

        lease_id = str(uuid.uuid4())
        if not self.coordination.acquire_lease("work-item", work_item_id, node_id, ttl_seconds, lease_id=lease_id):
            raise CenterControlError("WORK_ITEM_LEASE_HELD")
        leased = replace(work, state=WorkItemState.LEASED, lease_id=lease_id, lease_owner_node_id=node_id, lease_expires_at=now + ttl_seconds)
        self.repository.upsert_work_item(leased)
        self.repository.upsert_node(replace(node, status=NodeStatus.EXECUTING, last_heartbeat_at=now))
        return leased

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str) -> WorkItemRecord:
        work = self._require_active_lease(work_item_id, node_id, lease_id)
        updated = replace(work, state=WorkItemState.RUNNING)
        self.repository.upsert_work_item(updated)
        return updated

    def authorize_work_item_write(self, *, test_run_id: str, work_item_id: str, node_id: str, lease_id: str) -> WorkItemRecord:
        self._require_node(node_id)
        work = self._require_active_lease(work_item_id, node_id, lease_id)
        if work.identity.test_run_id != test_run_id:
            raise CenterControlError("WORK_ITEM_TEST_RUN_MISMATCH")
        return work

    def append_runtime_event(self, event: RuntimeEventEnvelope, *, lease_id: str) -> Dict[str, object]:
        self.authorize_work_item_write(test_run_id=event.test_run_id, work_item_id=event.work_item_id, node_id=event.node_id, lease_id=lease_id)
        self.runtime_ledger.assert_next_node_sequence(event)
        receipt = self.runtime_ledger.append_runtime(event)
        # Projection failure/pending never rolls back R1 truth.
        projection = self.projector.ingest({"event_id": event.event_id})
        return {"receipt": receipt, "projection": projection, "truth_note": "R1_PERSISTED_BEFORE_PROJECTION"}

    def complete_work_item(self, work_item_id: str, node_id: str, lease_id: str) -> WorkItemRecord:
        work = self._require_active_lease(work_item_id, node_id, lease_id)
        updated = replace(work, state=WorkItemState.COMPLETED, lease_id=None, lease_owner_node_id=None, lease_expires_at=None)
        # Durable terminal state first: if Redis cleanup fails, terminal PG state
        # still prevents further writes or leasing; stale Redis key will expire.
        self.repository.upsert_work_item(updated)
        try:
            self.coordination.release_lease("work-item", work_item_id, node_id, lease_id=lease_id)
        finally:
            node = self._require_node(node_id)
            self.repository.upsert_node(replace(node, status=NodeStatus.IDLE, last_heartbeat_at=self._now()))
        return updated

    def _require_node(self, node_id: str) -> NodeRecord:
        node = self.repository.get_node(str(node_id).strip())
        if node is None:
            raise CenterControlError("NODE_NOT_REGISTERED")
        return node

    def _require_work_item(self, work_item_id: str) -> WorkItemRecord:
        work = self.repository.get_work_item(str(work_item_id).strip())
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

    def _require_active_lease(self, work_item_id: str, node_id: str, lease_id: str) -> WorkItemRecord:
        work = self._require_work_item(work_item_id)
        if work.state not in {WorkItemState.LEASED, WorkItemState.RUNNING}:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        if work.lease_owner_node_id != node_id or work.lease_id != lease_id:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        active = self.coordination.lease_info("work-item", work_item_id)
        if active is None:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        if str(active.get("owner_id") or "") != node_id or str(active.get("lease_id") or "") != lease_id:
            raise CenterControlError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        return work
