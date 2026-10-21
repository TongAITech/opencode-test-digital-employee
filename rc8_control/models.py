"""Canonical RC8 shared-control domain models.

The models are intentionally Python 3.8 compatible because bank-side nodes may
run older Python runtimes.  Durable business/task identities are kept separate
from disposable DSH session/provider identities.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RC8ContractError(ValueError):
    """Raised when an RC8 canonical contract is invalid."""


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(values: List[str], name: str) -> List[str]:
    if not isinstance(values, list):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
    return values


class NodeStatus(str, Enum):
    ONLINE = "ONLINE"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class CapabilityState(str, Enum):
    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    EXECUTED = "EXECUTED"
    ASSERTED = "ASSERTED"
    EVIDENCE_PERSISTED = "EVIDENCE_PERSISTED"
    VERIFIED = "VERIFIED"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class LeaseState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class RequirementDeliveryScope:
    """One requirement implementation scope inside one production batch.

    A requirement can therefore naturally span many system versions,
    applications and SSTs without flattening them into one version_id/sst_id.
    """

    scope_id: str
    production_batch_id: str
    requirement_id: str
    system_version_id: str
    application_id: str
    sst_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _required(self.scope_id, "scope_id"))
        object.__setattr__(
            self,
            "production_batch_id",
            _required(self.production_batch_id, "production_batch_id"),
        )
        object.__setattr__(self, "requirement_id", _required(self.requirement_id, "requirement_id"))
        object.__setattr__(
            self,
            "system_version_id",
            _required(self.system_version_id, "system_version_id"),
        )
        object.__setattr__(self, "application_id", _required(self.application_id, "application_id"))
        object.__setattr__(self, "sst_id", _required(self.sst_id, "sst_id"))


@dataclass
class NodeCapability:
    capability: str
    state: CapabilityState = CapabilityState.DISCOVERED
    evidence_refs: List[str] = field(default_factory=list)
    last_verified_at: Optional[int] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        self.capability = _required(self.capability, "capability")
        _string_list(self.evidence_refs, "evidence_refs")
        if self.state == CapabilityState.VERIFIED and not self.evidence_refs:
            raise RC8ContractError("VERIFIED_CAPABILITY_REQUIRES_EVIDENCE")

    @property
    def is_verified(self) -> bool:
        return self.state == CapabilityState.VERIFIED


@dataclass
class ExecutionNode:
    node_id: str
    display_name: str
    platform: str
    architecture: str
    operator: str = ""
    package_version: str = ""
    status: NodeStatus = NodeStatus.ONLINE
    capabilities: Dict[str, NodeCapability] = field(default_factory=dict)
    registered_at: int = field(default_factory=_now)
    heartbeat_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.node_id = _required(self.node_id, "node_id")
        self.display_name = _required(self.display_name, "display_name")
        self.platform = _required(self.platform, "platform")
        self.architecture = _required(self.architecture, "architecture")
        if self.operator:
            self.operator = self.operator.strip()
        if self.package_version:
            self.package_version = self.package_version.strip()
        if not isinstance(self.capabilities, dict):
            raise RC8ContractError("CAPABILITIES_MUST_BE_OBJECT")

    def has_verified_capabilities(self, required: List[str]) -> bool:
        _string_list(required, "required_capabilities")
        for name in required:
            capability = self.capabilities.get(name)
            if capability is None or not capability.is_verified:
                return False
        return True


@dataclass
class WorkItemLease:
    lease_id: str
    work_item_id: str
    node_id: str
    required_capabilities: List[str]
    issued_at: int
    expires_at: int
    state: LeaseState = LeaseState.ACTIVE

    def __post_init__(self) -> None:
        self.lease_id = _required(self.lease_id, "lease_id")
        self.work_item_id = _required(self.work_item_id, "work_item_id")
        self.node_id = _required(self.node_id, "node_id")
        _string_list(self.required_capabilities, "required_capabilities")
        if not isinstance(self.issued_at, int) or not isinstance(self.expires_at, int):
            raise RC8ContractError("LEASE_TIMESTAMPS_MUST_BE_INT")
        if self.expires_at <= self.issued_at:
            raise RC8ContractError("LEASE_EXPIRY_MUST_FOLLOW_ISSUE")

    def is_active_at(self, now: int) -> bool:
        return self.state == LeaseState.ACTIVE and now < self.expires_at
