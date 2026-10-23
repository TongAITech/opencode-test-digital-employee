"""Deterministic, non-LLM provider failover for durable RC8 work.

Failover changes only provider/model routing. It never creates a replacement
Mission, Stage, WorkItem, Attempt, or input snapshot. UNKNOWN external side
effects fail closed and must be reconciled before any provider switch/replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .contracts import RC8ContractError
from .provider_recovery import RecoveryCheckpoint, SideEffectState


@dataclass(frozen=True)
class ProviderRoute:
    provider_id: str
    model_id: str
    priority: int
    available: bool = True

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise RC8ContractError("PROVIDER_ROUTE_ID_REQUIRED")
        if self.priority < 0:
            raise RC8ContractError("PROVIDER_ROUTE_PRIORITY_INVALID")


@dataclass(frozen=True)
class FailoverDispatch:
    checkpoint: RecoveryCheckpoint
    provider_id: str
    model_id: str
    r1_event_type: str = "PROVIDER_FAILOVER_RESUME_SCHEDULED"


class DeterministicFailoverSupervisor:
    """Select the next healthy configured route without consulting an LLM."""

    def __init__(self, routes: Iterable[ProviderRoute]) -> None:
        ordered = tuple(sorted(routes, key=lambda item: (item.priority, item.provider_id, item.model_id)))
        if not ordered:
            raise RC8ContractError("PROVIDER_FAILOVER_ROUTES_REQUIRED")
        identities = [(item.provider_id, item.model_id) for item in ordered]
        if len(identities) != len(set(identities)):
            raise RC8ContractError("PROVIDER_FAILOVER_ROUTE_DUPLICATE")
        self.routes: Tuple[ProviderRoute, ...] = ordered

    def select(
        self,
        checkpoint: RecoveryCheckpoint,
        *,
        failed_provider_id: str,
        failed_model_id: Optional[str] = None,
    ) -> FailoverDispatch:
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise RC8ContractError("RECOVERY_CHECKPOINT_REQUIRED")
        if checkpoint.side_effect_state == SideEffectState.UNKNOWN:
            raise RC8ContractError("SIDE_EFFECT_RECONCILIATION_REQUIRED_BEFORE_FAILOVER")
        failed_provider_id = failed_provider_id.strip()
        if not failed_provider_id:
            raise RC8ContractError("FAILED_PROVIDER_ID_REQUIRED")
        for route in self.routes:
            if not route.available:
                continue
            if route.provider_id == failed_provider_id and (failed_model_id is None or route.model_id == failed_model_id):
                continue
            return FailoverDispatch(checkpoint=checkpoint, provider_id=route.provider_id, model_id=route.model_id)
        raise RC8ContractError("NO_HEALTHY_PROVIDER_FAILOVER_ROUTE")
