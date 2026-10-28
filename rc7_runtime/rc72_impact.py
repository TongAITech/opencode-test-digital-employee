"""RC7.2 impact/stale-propagation domain contract.

ImpactSet is persisted before Phase 2 state-machine logic uses it. It records why
an upstream truth change invalidates downstream runtime assets. Broad fallback
invalidation is allowed only when explicitly recorded as SAFE_FALLBACK.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from .models import ContractError
from .rc72_domain import AutonomousMissionNode


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(values: List[str], name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(values, list):
        raise ContractError("%s_MUST_BE_LIST" % name.upper())
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
    if not allow_empty and not values:
        raise ContractError("%s_REQUIRED" % name.upper())
    return values


class ImpactStrategy(str, Enum):
    EXPLICIT_DEPENDENCY = "EXPLICIT_DEPENDENCY"
    SAFE_FALLBACK = "SAFE_FALLBACK"


@dataclass(frozen=True)
class ImpactSet:
    impact_set_id: str
    mission_id: str
    source_mission_node_id: str
    source_node_type: AutonomousMissionNode
    source_delivery_id: str
    changed_refs: List[str]
    affected_refs: List[str] = field(default_factory=list)
    stale_mission_node_ids: List[str] = field(default_factory=list)
    stale_obligation_ids: List[str] = field(default_factory=list)
    stale_etu_ids: List[str] = field(default_factory=list)
    strategy: ImpactStrategy = ImpactStrategy.EXPLICIT_DEPENDENCY
    reason: str = "upstream truth changed"
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "impact_set_id", "mission_id", "source_mission_node_id",
            "source_delivery_id", "reason",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.source_node_type, AutonomousMissionNode):
            try:
                object.__setattr__(
                    self,
                    "source_node_type",
                    AutonomousMissionNode(str(self.source_node_type)),
                )
            except ValueError as exc:
                raise ContractError("IMPACT_SOURCE_NODE_TYPE_INVALID") from exc
        if not isinstance(self.strategy, ImpactStrategy):
            try:
                object.__setattr__(self, "strategy", ImpactStrategy(str(self.strategy)))
            except ValueError as exc:
                raise ContractError("IMPACT_STRATEGY_INVALID") from exc
        _strings(self.changed_refs, "changed_refs", allow_empty=False)
        _strings(self.affected_refs, "affected_refs")
        _strings(self.stale_mission_node_ids, "stale_mission_node_ids")
        _strings(self.stale_obligation_ids, "stale_obligation_ids")
        _strings(self.stale_etu_ids, "stale_etu_ids")
        if not (
            self.affected_refs
            or self.stale_mission_node_ids
            or self.stale_obligation_ids
            or self.stale_etu_ids
        ):
            raise ContractError("IMPACT_SET_MUST_RECORD_AFFECTED_ASSET")
