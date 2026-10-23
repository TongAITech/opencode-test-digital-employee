"""RC8 requirement-to-runtime traceability domain.

The graph is a durable product/control-domain projection built from evidence.
Model output may create CANDIDATE relations only; verification is performed by
Center policy over persisted evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TraceabilityError(ValueError):
    """Raised when a traceability invariant would be violated."""


class TraceNodeType(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    BUSINESS_CAPABILITY = "BUSINESS_CAPABILITY"
    PAGE = "PAGE"
    PAGE_ACTION = "PAGE_ACTION"
    API = "API"
    CONTROLLER = "CONTROLLER"
    METHOD = "METHOD"
    SERVICE = "SERVICE"
    REPOSITORY = "REPOSITORY"
    MAPPER = "MAPPER"
    SQL = "SQL"
    DATABASE = "DATABASE"
    TABLE = "TABLE"
    TEST_CASE = "TEST_CASE"


class TraceRelationType(str, Enum):
    REQUIREMENT_AFFECTS = "REQUIREMENT_AFFECTS"
    CAPABILITY_PRESENTED_ON = "CAPABILITY_PRESENTED_ON"
    PAGE_HAS_ACTION = "PAGE_HAS_ACTION"
    PAGE_CALLS_API = "PAGE_CALLS_API"
    API_IMPLEMENTED_BY = "API_IMPLEMENTED_BY"
    CALLS = "CALLS"
    READS_TABLE = "READS_TABLE"
    WRITES_TABLE = "WRITES_TABLE"
    EXECUTES_SQL = "EXECUTES_SQL"
    TEST_COVERS = "TEST_COVERS"
    TEST_VERIFIES = "TEST_VERIFIES"


class TraceVerificationState(str, Enum):
    CANDIDATE = "CANDIDATE"
    STATIC_VERIFIED = "STATIC_VERIFIED"
    RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
    MULTI_SOURCE_VERIFIED = "MULTI_SOURCE_VERIFIED"
    CONFLICTED = "CONFLICTED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class TraceabilityGraph:
    graph_id: str
    test_run_id: str
    test_round_id: str
    scope_revision_id: str
    code_source_snapshot_id: str
    created_at: int
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TraceabilityGraph":
        values = {
            "TRACE_GRAPH_ID_REQUIRED": self.graph_id,
            "TRACE_TEST_RUN_ID_REQUIRED": self.test_run_id,
            "TRACE_TEST_ROUND_ID_REQUIRED": self.test_round_id,
            "TRACE_SCOPE_REVISION_ID_REQUIRED": self.scope_revision_id,
            "TRACE_CODE_SOURCE_SNAPSHOT_ID_REQUIRED": self.code_source_snapshot_id,
        }
        for error, value in values.items():
            if not str(value or "").strip():
                raise TraceabilityError(error)
        if int(self.created_at) <= 0:
            raise TraceabilityError("TRACE_GRAPH_CREATED_AT_REQUIRED")
        return self


@dataclass(frozen=True)
class TraceNode:
    node_id: str
    graph_id: str
    node_type: TraceNodeType
    business_key: str
    display_name: str
    created_at: int
    source_snapshot_id: Optional[str] = None
    scope_revision_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TraceNode":
        if not self.node_id.strip():
            raise TraceabilityError("TRACE_NODE_ID_REQUIRED")
        if not self.graph_id.strip():
            raise TraceabilityError("TRACE_NODE_GRAPH_ID_REQUIRED")
        if not self.business_key.strip():
            raise TraceabilityError("TRACE_NODE_BUSINESS_KEY_REQUIRED")
        if not self.display_name.strip():
            raise TraceabilityError("TRACE_NODE_DISPLAY_NAME_REQUIRED")
        TraceNodeType(self.node_type)
        return self


@dataclass(frozen=True)
class TraceEdge:
    edge_id: str
    graph_id: str
    from_node_id: str
    to_node_id: str
    relation_type: TraceRelationType
    created_at: int
    verification_state: TraceVerificationState = TraceVerificationState.CANDIDATE
    confidence: float = 0.0
    evidence_count: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TraceEdge":
        if not self.edge_id.strip():
            raise TraceabilityError("TRACE_EDGE_ID_REQUIRED")
        if not self.graph_id.strip():
            raise TraceabilityError("TRACE_EDGE_GRAPH_ID_REQUIRED")
        if not self.from_node_id.strip() or not self.to_node_id.strip():
            raise TraceabilityError("TRACE_EDGE_ENDPOINT_REQUIRED")
        if self.from_node_id == self.to_node_id:
            raise TraceabilityError("TRACE_EDGE_SELF_LOOP_NOT_ALLOWED")
        TraceRelationType(self.relation_type)
        TraceVerificationState(self.verification_state)
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise TraceabilityError("TRACE_EDGE_CONFIDENCE_INVALID")
        if int(self.evidence_count) < 0:
            raise TraceabilityError("TRACE_EDGE_EVIDENCE_COUNT_INVALID")
        return self


@dataclass(frozen=True)
class TraceEvidence:
    evidence_id: str
    graph_id: str
    edge_id: str
    evidence_type: str
    source: str
    test_run_id: str
    code_source_snapshot_id: str
    captured_at: int
    integrity_hash: str
    artifact_id: Optional[str] = None
    stage_id: Optional[str] = None
    work_item_id: Optional[str] = None
    attempt_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TraceEvidence":
        values = {
            "TRACE_EVIDENCE_ID_REQUIRED": self.evidence_id,
            "TRACE_EVIDENCE_GRAPH_ID_REQUIRED": self.graph_id,
            "TRACE_EVIDENCE_EDGE_ID_REQUIRED": self.edge_id,
            "TRACE_EVIDENCE_TYPE_REQUIRED": self.evidence_type,
            "TRACE_EVIDENCE_SOURCE_REQUIRED": self.source,
            "TRACE_EVIDENCE_TEST_RUN_ID_REQUIRED": self.test_run_id,
            "TRACE_EVIDENCE_CODE_SOURCE_REQUIRED": self.code_source_snapshot_id,
            "TRACE_EVIDENCE_INTEGRITY_HASH_REQUIRED": self.integrity_hash,
        }
        for error, value in values.items():
            if not str(value or "").strip():
                raise TraceabilityError(error)
        if int(self.captured_at) <= 0:
            raise TraceabilityError("TRACE_EVIDENCE_CAPTURED_AT_REQUIRED")
        return self
