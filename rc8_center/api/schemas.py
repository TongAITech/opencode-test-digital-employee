"""Pydantic schemas for the formal RC8 Center HTTP adapter."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeRegistrationRequest(StrictModel):
    node_id: str = Field(min_length=1, max_length=200)
    operator_ref: str = Field(min_length=1, max_length=240)
    os_family: str = Field(min_length=1, max_length=32)
    architecture: str = Field(min_length=1, max_length=64)
    shell: str = Field(min_length=1, max_length=64)
    registered_at: int = Field(ge=0)


class NodeHeartbeatRequest(StrictModel):
    status: Optional[str] = Field(default=None, max_length=64)


class CapabilityRequest(StrictModel):
    capability_id: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=64)
    probe_ref: Optional[str] = Field(default=None, max_length=400)
    evidence_refs: List[str] = Field(default_factory=list)
    verified_at: Optional[int] = Field(default=None, ge=0)


class WorkItemRegistrationRequest(StrictModel):
    work_item_id: str = Field(min_length=1, max_length=200)
    test_run_id: str = Field(min_length=1, max_length=160)
    stage: str = Field(min_length=1, max_length=100)
    scope_refs: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)


class LeaseRequest(StrictModel):
    node_id: str = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(default=60, gt=0, le=3600)


class LeasedActionRequest(StrictModel):
    node_id: str = Field(min_length=1, max_length=200)
    lease_id: str = Field(min_length=1, max_length=200)


class RuntimeEventRequest(StrictModel):
    lease_id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    test_run_id: str = Field(min_length=1, max_length=160)
    work_item_id: str = Field(min_length=1, max_length=200)
    node_id: str = Field(min_length=1, max_length=200)
    producer_kind: str = Field(min_length=1, max_length=64)
    producer_ref: str = Field(min_length=1, max_length=240)
    event_type: str = Field(min_length=1, max_length=120)
    sequence: int = Field(ge=0)
    case_id: Optional[str] = Field(default=None, max_length=200)
    attempt_id: Optional[str] = Field(default=None, max_length=200)
    step_id: Optional[str] = Field(default=None, max_length=200)
    refs: List[str] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: int = Field(ge=0)
