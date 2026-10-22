"""Production-batch-first task organization for RC8.

Business truth:
- a production batch is selected first;
- Requirement is the long-lived business identity;
- RequirementRevision/Iteration is a first-class immutable business version;
- ScopeRevision is a first-class immutable delivery-scope version;
- RequirementDelivery binds one effective RequirementRevision + ScopeRevision
  into a production batch;
- system version/application/SST are technical delivery scopes and must never be
  used as the requirement revision identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProductionBatchState(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RequirementDeliveryState(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TERMINAL_DELIVERY_STATES = {
    RequirementDeliveryState.COMPLETED,
    RequirementDeliveryState.CANCELLED,
}


_ALLOWED_DELIVERY_TRANSITIONS = {
    RequirementDeliveryState.PLANNED: {
        RequirementDeliveryState.IN_PROGRESS,
        RequirementDeliveryState.PARTIAL,
        RequirementDeliveryState.COMPLETED,
        RequirementDeliveryState.CANCELLED,
    },
    RequirementDeliveryState.IN_PROGRESS: {
        RequirementDeliveryState.PARTIAL,
        RequirementDeliveryState.COMPLETED,
        RequirementDeliveryState.CANCELLED,
    },
    RequirementDeliveryState.PARTIAL: {
        RequirementDeliveryState.IN_PROGRESS,
        RequirementDeliveryState.COMPLETED,
        RequirementDeliveryState.CANCELLED,
    },
    RequirementDeliveryState.COMPLETED: set(),
    RequirementDeliveryState.CANCELLED: set(),
}


@dataclass(frozen=True)
class ProductionBatch:
    production_batch_id: str
    production_date: str
    name: str
    state: ProductionBatchState = ProductionBatchState.PLANNED
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    title: str
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequirementDelivery:
    delivery_id: str
    production_batch_id: str
    requirement_id: str
    state: RequirementDeliveryState = RequirementDeliveryState.PLANNED
    continuation_of_delivery_id: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    requirement_revision_id: Optional[str] = None
    scope_revision_id: Optional[str] = None

    def transition_to(self, target: RequirementDeliveryState) -> "RequirementDelivery":
        target = RequirementDeliveryState(target)
        if target == self.state:
            return self
        if target not in _ALLOWED_DELIVERY_TRANSITIONS[self.state]:
            raise ValueError(
                "REQUIREMENT_DELIVERY_TERMINAL_STATE_IMMUTABLE"
                if self.state in TERMINAL_DELIVERY_STATES
                else "REQUIREMENT_DELIVERY_STATE_TRANSITION_INVALID"
            )
        return RequirementDelivery(
            delivery_id=self.delivery_id,
            production_batch_id=self.production_batch_id,
            requirement_id=self.requirement_id,
            state=target,
            continuation_of_delivery_id=self.continuation_of_delivery_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            payload=dict(self.payload),
            requirement_revision_id=self.requirement_revision_id,
            scope_revision_id=self.scope_revision_id,
        )


@dataclass(frozen=True)
class RequirementDeliveryScope:
    scope_id: str
    delivery_id: str
    system_id: str
    system_version: str
    sst_id: str
    application_id: Optional[str] = None
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def scope_identity(self) -> str:
        """Stable compact identity for delivery/system-version/application/SST."""
        canonical = "\x1f".join(
            [
                self.delivery_id.strip(),
                self.system_id.strip(),
                self.system_version.strip(),
                (self.application_id or "").strip(),
                self.sst_id.strip(),
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RequirementDeliveryHistory:
    requirement: Requirement
    deliveries: List[RequirementDelivery]
    scopes_by_delivery: Dict[str, List[RequirementDeliveryScope]]

    @property
    def current_delivery_state(self) -> Optional[RequirementDeliveryState]:
        if not self.deliveries:
            return None
        return self.deliveries[-1].state

    @property
    def completed_in_single_batch(self) -> bool:
        return len(self.deliveries) == 1 and self.deliveries[0].state == RequirementDeliveryState.COMPLETED

    @property
    def spans_multiple_batches(self) -> bool:
        return len({item.production_batch_id for item in self.deliveries}) > 1
