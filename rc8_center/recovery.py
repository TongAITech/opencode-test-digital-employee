"""Durable lease-recovery contracts for RC8 Center."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RecoveryIncidentState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RecoveryReason(str, Enum):
    REDIS_LEASE_MISSING = "REDIS_LEASE_MISSING"
    REDIS_LEASE_DIVERGED = "REDIS_LEASE_DIVERGED"
    STALE_REDIS_LEASE_AFTER_TERMINAL = "STALE_REDIS_LEASE_AFTER_TERMINAL"


class RecoveryResolution(str, Enum):
    RESET_READY_NO_RUNTIME = "RESET_READY_NO_RUNTIME"
    AUTHORIZE_REQUEUE = "AUTHORIZE_REQUEUE"
    ABORT_WORK_ITEM = "ABORT_WORK_ITEM"
    CLEAN_STALE_REDIS_LEASE = "CLEAN_STALE_REDIS_LEASE"


@dataclass(frozen=True)
class RecoveryIncident:
    incident_id: str
    work_item_id: str
    test_run_id: str
    node_id: Optional[str]
    lease_id: Optional[str]
    work_item_state: str
    reason: RecoveryReason
    runtime_event_count: int
    state: RecoveryIncidentState
    opened_at: int
    resolution: Optional[RecoveryResolution] = None
    decision_ref: Optional[str] = None
    evidence_ref: Optional[str] = None
    explanation: Optional[str] = None
    resolved_at: Optional[int] = None
