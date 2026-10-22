"""First-class requirement and delivery-scope revision identities for RC8.

A Requirement is the long-lived business identity. RequirementRevision is one
immutable business iteration of that requirement. ScopeRevision is the
immutable delivery-scope snapshot attached to a RequirementRevision. Technical
system versions remain fields of RequirementDeliveryScope and must never be
used as requirement versions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _required(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("%s_REQUIRED" % name.upper())
    return normalized


@dataclass(frozen=True)
class RequirementRevision:
    requirement_revision_id: str
    requirement_id: str
    revision_label: str
    parent_requirement_revision_id: Optional[str] = None
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_revision_id", _required(self.requirement_revision_id, "requirement_revision_id"))
        object.__setattr__(self, "requirement_id", _required(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "revision_label", _required(self.revision_label, "revision_label"))
        if self.parent_requirement_revision_id is not None:
            object.__setattr__(
                self,
                "parent_requirement_revision_id",
                _required(self.parent_requirement_revision_id, "parent_requirement_revision_id"),
            )


@dataclass(frozen=True)
class ScopeRevision:
    scope_revision_id: str
    requirement_revision_id: str
    revision_label: str
    parent_scope_revision_id: Optional[str] = None
    created_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_revision_id", _required(self.scope_revision_id, "scope_revision_id"))
        object.__setattr__(self, "requirement_revision_id", _required(self.requirement_revision_id, "requirement_revision_id"))
        object.__setattr__(self, "revision_label", _required(self.revision_label, "revision_label"))
        if self.parent_scope_revision_id is not None:
            object.__setattr__(self, "parent_scope_revision_id", _required(self.parent_scope_revision_id, "parent_scope_revision_id"))


@dataclass(frozen=True)
class DeliveryRevisionBinding:
    delivery_id: str
    requirement_revision_id: str
    scope_revision_id: str
    created_at: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "delivery_id", _required(self.delivery_id, "delivery_id"))
        object.__setattr__(self, "requirement_revision_id", _required(self.requirement_revision_id, "requirement_revision_id"))
        object.__setattr__(self, "scope_revision_id", _required(self.scope_revision_id, "scope_revision_id"))

    @property
    def immutable_scope_ref(self) -> str:
        return "requirement-revision:%s|scope-revision:%s" % (
            self.requirement_revision_id,
            self.scope_revision_id,
        )
