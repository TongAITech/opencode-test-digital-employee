"""Lease recovery coordinator driven by PostgreSQL + Redis + last R1 truth.

Rules are deliberately conservative:
- lost LEASED work with zero R1 runtime facts can be reset READY safely;
- RUNNING or any work with runtime facts is never blindly replayed;
- requeue/abort of uncertain work requires an explicit decision/evidence ref;
- terminal PG truth can clean only the matching stale Redis owner+token.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from typing import List, Optional

from rc8_center.control_plane import NodeStatus, WorkItemState
from rc8_center.infrastructure.postgres_control import PostgresCenterRepository
from rc8_center.infrastructure.postgres_recovery import PostgresRecoveryRepository
from rc8_center.infrastructure.redis_coordination import RedisCoordination
from rc8_center.recovery import (
    RecoveryIncident,
    RecoveryIncidentState,
    RecoveryReason,
    RecoveryResolution,
)
from rc8_runtime import CentralR1RuntimeLedger


class RecoveryError(RuntimeError):
    pass


class LeaseRecoveryCoordinator:
    def __init__(
        self,
        control_repository: PostgresCenterRepository,
        recovery_repository: PostgresRecoveryRepository,
        coordination: RedisCoordination,
        runtime_ledger: CentralR1RuntimeLedger,
        *,
        now_fn=None,
    ) -> None:
        self.control_repository = control_repository
        self.recovery_repository = recovery_repository
        self.coordination = coordination
        self.runtime_ledger = runtime_ledger
        self._now = now_fn or (lambda: int(time.time()))

    def reconcile(self) -> List[RecoveryIncident]:
        opened: List[RecoveryIncident] = []
        for work in self.control_repository.list_work_items():
            active = self.coordination.lease_info("work-item", work.identity.work_item_id)
            reason: Optional[RecoveryReason] = None
            if work.state in {WorkItemState.LEASED, WorkItemState.RUNNING}:
                if active is None:
                    reason = RecoveryReason.REDIS_LEASE_MISSING
                elif (
                    str(active.get("owner_id") or "") != str(work.lease_owner_node_id or "")
                    or str(active.get("lease_id") or "") != str(work.lease_id or "")
                ):
                    reason = RecoveryReason.REDIS_LEASE_DIVERGED
            elif work.state in {WorkItemState.COMPLETED, WorkItemState.FAILED} and active is not None:
                reason = RecoveryReason.STALE_REDIS_LEASE_AFTER_TERMINAL
            elif work.state in {WorkItemState.PENDING, WorkItemState.READY} and active is not None:
                reason = RecoveryReason.REDIS_LEASE_DIVERGED

            if reason is None:
                continue
            incident_id = self._incident_id(work.identity.work_item_id, work.lease_id, reason)
            existing = self.recovery_repository.get(incident_id)
            opened_at = existing.opened_at if existing is not None else self._now()
            incident = RecoveryIncident(
                incident_id=incident_id,
                work_item_id=work.identity.work_item_id,
                test_run_id=work.identity.test_run_id,
                node_id=work.lease_owner_node_id,
                lease_id=work.lease_id,
                work_item_state=work.state.value,
                reason=reason,
                runtime_event_count=self._runtime_event_count(work.identity.work_item_id),
                state=RecoveryIncidentState.OPEN,
                opened_at=opened_at,
            )
            stored = self.recovery_repository.upsert_open(incident)
            if stored.state == RecoveryIncidentState.OPEN:
                opened.append(stored)
        return opened

    def resolve(
        self,
        incident_id: str,
        resolution: RecoveryResolution,
        *,
        decision_ref: Optional[str] = None,
        evidence_ref: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> RecoveryIncident:
        incident = self.recovery_repository.get(incident_id)
        if incident is None:
            raise RecoveryError("RECOVERY_INCIDENT_NOT_FOUND")
        if incident.state == RecoveryIncidentState.RESOLVED:
            return incident
        work = self.control_repository.get_work_item(incident.work_item_id)
        if work is None:
            raise RecoveryError("RECOVERY_WORK_ITEM_NOT_FOUND")
        active = self.coordination.lease_info("work-item", incident.work_item_id)
        runtime_count = self._runtime_event_count(incident.work_item_id)

        if resolution == RecoveryResolution.RESET_READY_NO_RUNTIME:
            if work.state != WorkItemState.LEASED:
                raise RecoveryError("RESET_READY_REQUIRES_LEASED_NOT_RUNNING")
            if runtime_count != 0:
                raise RecoveryError("RESET_READY_REQUIRES_ZERO_RUNTIME_EVENTS")
            if active is not None:
                raise RecoveryError("RESET_READY_REQUIRES_MISSING_ACTIVE_REDIS_LEASE")
            self._reset_ready(work)

        elif resolution == RecoveryResolution.AUTHORIZE_REQUEUE:
            self._require_governed_decision(decision_ref, evidence_ref, explanation)
            if work.state not in {WorkItemState.LEASED, WorkItemState.RUNNING}:
                raise RecoveryError("REQUEUE_REQUIRES_INFLIGHT_WORK_ITEM")
            if active is not None:
                raise RecoveryError("REQUEUE_REQUIRES_NO_ACTIVE_REDIS_LEASE")
            self._reset_ready(work)

        elif resolution == RecoveryResolution.ABORT_WORK_ITEM:
            self._require_governed_decision(decision_ref, evidence_ref, explanation)
            if work.state in {WorkItemState.COMPLETED, WorkItemState.FAILED}:
                raise RecoveryError("ABORT_REQUIRES_NONTERMINAL_WORK_ITEM")
            if active is not None and self._active_matches(work, active):
                self.coordination.release_lease(
                    "work-item",
                    work.identity.work_item_id,
                    str(work.lease_owner_node_id or ""),
                    lease_id=work.lease_id,
                )
            failed = replace(work, state=WorkItemState.FAILED, lease_id=None, lease_owner_node_id=None, lease_expires_at=None)
            self.control_repository.upsert_work_item(failed)
            self._mark_node_idle(work.lease_owner_node_id)

        elif resolution == RecoveryResolution.CLEAN_STALE_REDIS_LEASE:
            if work.state not in {WorkItemState.COMPLETED, WorkItemState.FAILED}:
                raise RecoveryError("STALE_LEASE_CLEAN_REQUIRES_TERMINAL_WORK_ITEM")
            if active is None:
                raise RecoveryError("STALE_LEASE_ALREADY_ABSENT")
            if not self._active_matches(work, active):
                raise RecoveryError("STALE_LEASE_OWNER_OR_TOKEN_DIVERGED")
            self.coordination.release_lease(
                "work-item",
                work.identity.work_item_id,
                str(work.lease_owner_node_id or ""),
                lease_id=work.lease_id,
            )

        else:
            raise RecoveryError("RECOVERY_RESOLUTION_UNSUPPORTED")

        resolved = replace(
            incident,
            work_item_state=(self.control_repository.get_work_item(incident.work_item_id) or work).state.value,
            runtime_event_count=runtime_count,
            state=RecoveryIncidentState.RESOLVED,
            resolution=resolution,
            decision_ref=decision_ref,
            evidence_ref=evidence_ref,
            explanation=explanation,
            resolved_at=self._now(),
        )
        return self.recovery_repository.resolve(resolved)

    def list_open(self) -> List[RecoveryIncident]:
        return self.recovery_repository.list_open()

    def _reset_ready(self, work) -> None:
        ready = replace(work, state=WorkItemState.READY, lease_id=None, lease_owner_node_id=None, lease_expires_at=None)
        self.control_repository.upsert_work_item(ready)
        self._mark_node_idle(work.lease_owner_node_id)

    def _mark_node_idle(self, node_id: Optional[str]) -> None:
        if not node_id:
            return
        node = self.control_repository.get_node(node_id)
        if node is not None and node.status == NodeStatus.EXECUTING:
            self.control_repository.upsert_node(replace(node, status=NodeStatus.IDLE, last_heartbeat_at=self._now()))

    def _runtime_event_count(self, work_item_id: str) -> int:
        return sum(1 for event in self.runtime_ledger.runtime_events() if event.work_item_id == work_item_id)

    @staticmethod
    def _active_matches(work, active) -> bool:
        return (
            str(active.get("owner_id") or "") == str(work.lease_owner_node_id or "")
            and str(active.get("lease_id") or "") == str(work.lease_id or "")
        )

    @staticmethod
    def _require_governed_decision(decision_ref: Optional[str], evidence_ref: Optional[str], explanation: Optional[str]) -> None:
        if not decision_ref or not str(decision_ref).strip():
            raise RecoveryError("RECOVERY_DECISION_REF_REQUIRED")
        if not evidence_ref or not str(evidence_ref).strip():
            raise RecoveryError("RECOVERY_EVIDENCE_REF_REQUIRED")
        if not explanation or not str(explanation).strip():
            raise RecoveryError("RECOVERY_EXPLANATION_REQUIRED")

    @staticmethod
    def _incident_id(work_item_id: str, lease_id: Optional[str], reason: RecoveryReason) -> str:
        material = "%s|%s|%s" % (work_item_id, lease_id or "NONE", reason.value)
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        return "recovery-%s" % digest
