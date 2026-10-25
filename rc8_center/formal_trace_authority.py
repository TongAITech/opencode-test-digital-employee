"""Formal PostgreSQL/Redis authority bridge for N3 runtime trace ingestion.

The generic ingestion service deliberately accepts a small control-plane surface
so unit tests do not need infrastructure.  This bridge binds that surface to the
formal Center truth: PostgreSQL WorkItem/Attempt state plus the Redis lease
validated by FormalCenterControlPlane.  Worker payload never supplies a lease
identity or chooses the current Attempt.
"""
from __future__ import annotations

from typing import Optional

from rc8_runtime.governance import AttemptStatus

from .runtime_attempt_authority import RuntimeAttemptAuthoritySnapshot
from .traceability import TraceabilityError


class FormalTraceRuntimeAuthority:
    """Resolve the current runtime Attempt and active lease from Center truth."""

    def __init__(self, formal_control, governance_repository) -> None:
        self.formal_control = formal_control
        self.governance_repository = governance_repository

    def _now(self) -> int:
        return int(self.formal_control._now())

    def authorize_work_item_write(self, *, test_run_id: str, work_item_id: str, node_id: str):
        # The lease token is read from Center-owned durable state, never accepted
        # from an observation. FormalCenterControlPlane then cross-checks that
        # token against Redis before authorizing the write.
        work = self.formal_control.repository.get_work_item(work_item_id)
        if work is None:
            raise TraceabilityError("WORK_ITEM_NOT_FOUND")
        lease_id = str(work.lease_id or "").strip()
        if not lease_id:
            raise TraceabilityError("ACTIVE_WORK_ITEM_LEASE_REQUIRED")
        try:
            return self.formal_control.authorize_work_item_write(
                test_run_id=test_run_id,
                work_item_id=work_item_id,
                node_id=node_id,
                lease_id=lease_id,
            )
        except Exception as exc:
            raise TraceabilityError(str(exc)) from exc

    def resolve_current_attempt(self, work_item_id: str) -> Optional[RuntimeAttemptAuthoritySnapshot]:
        work = self.formal_control.repository.get_work_item(work_item_id)
        if work is None:
            return None
        lease_owner = str(work.lease_owner_node_id or "").strip()
        if not lease_owner or work.lease_expires_at is None:
            return None

        attempts = [
            item
            for item in self.governance_repository.list_attempts(work.identity.test_run_id)
            if item.work_item_id == work_item_id
        ]
        if not attempts:
            return None

        # Current means the newest non-terminal STARTED attempt. A completed,
        # failed or blocked attempt cannot authorize new runtime evidence. If a
        # newer attempt exists, older attempts are therefore naturally stale.
        attempts.sort(key=lambda item: (int(item.started_at), item.attempt_id))
        current = attempts[-1]
        if current.status != AttemptStatus.STARTED:
            return None
        return RuntimeAttemptAuthoritySnapshot(
            work_item_id=work_item_id,
            attempt_id=current.attempt_id,
            producer_node_id=current.producer_node_id,
            attempt_started_at=int(current.started_at),
            lease_owner_node_id=lease_owner,
            lease_expires_at=int(work.lease_expires_at),
            superseded=False,
        )
