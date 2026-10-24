"""Center-owned distributed WorkItem lifecycle and failover audit.

The Center remains a non-AI control plane.  This coordinator combines the
existing capability-aware placement scheduler with Center lease state and the
canonical R1 runtime ledger.  It owns only control decisions: it never calls a
model, dsh-agent-teams or a domain execution tool.

It makes the control-side lifecycle first-class and auditable:
PLACED -> LEASED -> ...node-local runtime...; and on failure
NODE_LOST / LEASE_EXPIRED -> re-placement.  Late writes from an old attempt
remain rejected by CenterControlPlane and can be recorded as
STALE_ATTEMPT_REJECTED without granting the stale attempt a write lease.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional

from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind

from .control_plane import (
    CenterControlError,
    CenterControlPlane,
    NodeStatus,
    WorkItemRecord,
    WorkItemState,
)
from .distributed_orchestration import (
    ActorRole,
    NodePlacementScheduler,
    PlacementDecision,
    PlacementPolicy,
)


class DistributedLifecycleError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchRecord:
    decision: PlacementDecision
    lease: WorkItemRecord

    @property
    def attempt_id(self) -> str:
        if not self.lease.lease_id:
            raise DistributedLifecycleError("DISPATCH_LEASE_ID_REQUIRED")
        return self.lease.lease_id


class DistributedLifecycleCoordinator:
    """Center-side placement, lease expiry and node-loss reconciliation."""

    def __init__(
        self,
        control_plane: CenterControlPlane,
        *,
        heartbeat_timeout_seconds: int = 90,
        now_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        if not isinstance(control_plane, CenterControlPlane):
            raise DistributedLifecycleError("CENTER_CONTROL_PLANE_REQUIRED")
        if not isinstance(heartbeat_timeout_seconds, int) or heartbeat_timeout_seconds <= 0:
            raise DistributedLifecycleError("HEARTBEAT_TIMEOUT_INVALID")
        self.control_plane = control_plane
        self.scheduler = NodePlacementScheduler(control_plane.repository)
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._now = now_fn or (lambda: int(time.time()))

    def dispatch(
        self,
        work_item_id: str,
        policy: PlacementPolicy,
        *,
        ttl_seconds: int = 60,
    ) -> DispatchRecord:
        work = self._require_work(work_item_id)
        if work.lease_id is not None:
            raise DistributedLifecycleError("WORK_ITEM_ALREADY_LEASED")
        decision = self.scheduler.place(work, policy)
        self._emit_center_event(
            work,
            decision.node_id,
            "PLACED",
            data={
                "placement_mode": decision.mode.value,
                "placement_reason": decision.reason,
            },
        )
        lease = self.control_plane.lease_work_item(
            work.identity.work_item_id,
            decision.node_id,
            ttl_seconds=ttl_seconds,
        )
        if not lease.lease_id:
            raise DistributedLifecycleError("LEASE_ID_REQUIRED")
        self._emit_center_event(
            lease,
            decision.node_id,
            "LEASED",
            attempt_id=lease.lease_id,
            data={
                "placement_mode": decision.mode.value,
                "lease_expires_at": lease.lease_expires_at,
            },
        )
        return DispatchRecord(decision=decision, lease=lease)

    def reconcile(
        self,
        work_item_id: str,
        policy: PlacementPolicy,
        *,
        ttl_seconds: int = 60,
    ) -> Optional[DispatchRecord]:
        """Requeue expired/lost work; return None while the current lease is valid."""
        work = self._require_work(work_item_id)
        if work.lease_id is None or work.lease_owner_node_id is None or work.lease_expires_at is None:
            if work.state in {WorkItemState.COMPLETED, WorkItemState.FAILED}:
                return None
            return self.dispatch(work_item_id, policy, ttl_seconds=ttl_seconds)

        now = self._now()
        node = self.control_plane.repository.get_node(work.lease_owner_node_id)
        node_lost = node is None or (now - node.last_heartbeat_at) >= self.heartbeat_timeout_seconds
        lease_expired = work.lease_expires_at <= now
        if not node_lost and not lease_expired:
            return None

        old_node_id = work.lease_owner_node_id
        old_attempt_id = work.lease_id
        if node_lost:
            self._emit_center_event(
                work,
                old_node_id,
                "NODE_LOST",
                attempt_id=old_attempt_id,
                data={"last_heartbeat_at": node.last_heartbeat_at if node is not None else None},
            )
            if node is not None:
                self.control_plane.repository.upsert_node(replace(node, status=NodeStatus.OFFLINE))

        self._emit_center_event(
            work,
            old_node_id,
            "LEASE_EXPIRED",
            attempt_id=old_attempt_id,
            data={"reason": "NODE_LOST" if node_lost else "TTL_EXPIRED"},
        )
        self._clear_stale_lease(work, preserve_offline=node_lost)
        return self.dispatch(work_item_id, policy, ttl_seconds=ttl_seconds)

    def record_stale_attempt_rejected(
        self,
        *,
        work_item_id: str,
        node_id: str,
        attempt_id: str,
        reason: str,
    ) -> Dict[str, object]:
        work = self._require_work(work_item_id)
        node_id = self._required(node_id, "node_id")
        attempt_id = self._required(attempt_id, "attempt_id")
        reason = self._required(reason, "reason")
        now = self._now()
        if (
            work.lease_owner_node_id == node_id
            and work.lease_id == attempt_id
            and work.lease_expires_at is not None
            and work.lease_expires_at > now
        ):
            raise DistributedLifecycleError("ATTEMPT_IS_STILL_ACTIVE")
        return self._emit_center_event(
            work,
            node_id,
            "STALE_ATTEMPT_REJECTED",
            attempt_id=attempt_id,
            data={
                "reason": reason,
                "current_attempt_id": work.lease_id,
                "current_node_id": work.lease_owner_node_id,
            },
        )

    def _clear_stale_lease(self, work: WorkItemRecord, *, preserve_offline: bool) -> None:
        old_node_id = work.lease_owner_node_id
        cleared = replace(
            work,
            state=WorkItemState.READY,
            lease_id=None,
            lease_owner_node_id=None,
            lease_expires_at=None,
        )
        self.control_plane.repository.upsert_work_item(cleared)
        if not old_node_id or preserve_offline:
            return
        node = self.control_plane.repository.get_node(old_node_id)
        if node is not None and node.status == NodeStatus.EXECUTING:
            self.control_plane.repository.upsert_node(replace(node, status=NodeStatus.IDLE))

    def _require_work(self, work_item_id: str) -> WorkItemRecord:
        value = self._required(work_item_id, "work_item_id")
        work = self.control_plane.repository.get_work_item(value)
        if work is None:
            raise DistributedLifecycleError("WORK_ITEM_NOT_FOUND")
        return work

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DistributedLifecycleError("%s_REQUIRED" % name.upper())
        return value.strip()

    def _emit_center_event(
        self,
        work: WorkItemRecord,
        node_id: str,
        event_type: str,
        *,
        attempt_id: Optional[str] = None,
        data: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        node_id = self._required(node_id, "node_id")
        payload = {
            "actor_role": ActorRole.CENTER.value,
            "stage_id": work.identity.stage,
            "work_item_id": work.identity.work_item_id,
            "node_id": node_id,
        }
        if attempt_id is not None:
            payload["attempt_id"] = attempt_id
        payload.update(dict(data or {}))
        sequence = self.control_plane.runtime_ledger.latest_node_sequence(
            test_run_id=work.identity.test_run_id,
            node_id=node_id,
        ) + 1
        event = RuntimeEventEnvelope(
            event_id=str(uuid.uuid4()),
            test_run_id=work.identity.test_run_id,
            work_item_id=work.identity.work_item_id,
            node_id=node_id,
            producer_kind=RuntimeProducerKind.NODE_AGENT,
            producer_ref="rc8-center",
            event_type=event_type,
            sequence=sequence,
            attempt_id=attempt_id,
            data=payload,
        )
        # Center control events intentionally bypass active-node lease
        # authorization: lease expiry/loss/stale-rejection are exactly the
        # events that must remain writable after the old lease becomes invalid.
        return self.control_plane.runtime_ledger.append_runtime(event)
