from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, RuntimeState, canonical_sha256
from aitest_runtime.r3_e1 import KnowledgeScopeIdentity

from .errors import R35Error


EXTENSION_ID = "r3_5_page_journey_e2e_intelligence"
EXTENSION_VERSION = "1"
ARCHITECTURE_BASELINE_REF = "v5"

BUILD_PAGE_GRAPH = "R3_5_BUILD_PAGE_GRAPH"
DEFINE_JOURNEY = "R3_5_DEFINE_JOURNEY"
RECORD_TRANSITION = "R3_5_RECORD_JOURNEY_TRANSITION"
CHECKPOINT_JOURNEY = "R3_5_CHECKPOINT_JOURNEY"
RECORD_VERIFICATION = "R3_5_RECORD_JOURNEY_VERIFICATION"

PAGE_GRAPH_RECORDED = "r3.5.page_graph_recorded.v1"
JOURNEY_RECORDED = "r3.5.journey_recorded.v1"
TRANSITION_RECORDED = "r3.5.journey_transition_recorded.v1"
CHECKPOINT_RECORDED = "r3.5.journey_checkpoint_recorded.v1"
VERIFICATION_RECORDED = "r3.5.journey_verification_recorded.v1"

COMMAND_TYPES = frozenset({
    BUILD_PAGE_GRAPH,
    DEFINE_JOURNEY,
    RECORD_TRANSITION,
    CHECKPOINT_JOURNEY,
    RECORD_VERIFICATION,
})
EVENT_TYPES = frozenset({
    PAGE_GRAPH_RECORDED,
    JOURNEY_RECORDED,
    TRANSITION_RECORDED,
    CHECKPOINT_RECORDED,
    VERIFICATION_RECORDED,
})

FRONTEND_SURFACES = frozenset({
    "router",
    "menu",
    "permission",
    "component",
    "form",
    "table",
    "action",
    "handler",
    "api_binding",
})
BACKEND_SURFACES = frozenset({
    "api",
    "controller",
    "service",
    "repository",
    "db",
    "external_client",
})
EXECUTION_TYPES = frozenset({"UI", "API", "DB", "MQ", "LOG", "MANUAL", "OTHER_TOOL"})
JOURNEY_STEP_STATUSES = frozenset({"PLANNED", "READY", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED", "INCONCLUSIVE"})
PAGE_RECONCILIATION_STATES = frozenset({
    "CODE_DEFINED_RUNTIME_VISIBLE",
    "CODE_DEFINED_RUNTIME_HIDDEN",
    "PERMISSION_HIDDEN",
    "DYNAMIC_RUNTIME_ONLY",
    "CODE_RUNTIME_CONFLICT",
    "UNRESOLVED",
})
PAGE_GRAPH_STATUSES = frozenset({"DRAFT", "SOURCE_MAPPED", "RECONCILED", "SUPERSEDED"})
RUNTIME_EXECUTIONS = frozenset({"REAL", "STRUCTURAL_ONLY", "MOCK", "FAKE", "TEXT_ONLY", "NOT_EXECUTED"})
VERIFICATION_RESULTS = frozenset({"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "INVALID"})
EVIDENCE_CLASSES = frozenset({"ENGINEERING_EVIDENCE", "FIELD_EVIDENCE"})
_SECRET_KEY_MARKERS = frozenset({
    "password", "passwd", "cookie", "secret", "otp", "mfa", "credential",
    "storage_state", "access_token", "refresh_token", "authorization",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _mapping(value: Any, name: str, *, required: bool = True) -> dict[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an object")
    result = dict(value)
    _reject_secrets(result, name)
    return result


def _reject_secrets(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SECRET_KEY_MARKERS or any(marker in normalized for marker in _SECRET_KEY_MARKERS):
                raise R35Error("R3_5_SCHEMA_INVALID", f"{name} contains a forbidden secret field: {key}")
            _reject_secrets(child, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{name}[{index}]")


def _tuple_text(value: Any, name: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if required and not result:
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _tuple_mapping(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[]") for item in value)


def _scope(value: Any, name: str = "scope") -> KnowledgeScopeIdentity:
    if isinstance(value, KnowledgeScopeIdentity):
        return value
    if not isinstance(value, Mapping):
        raise R35Error("R3_5_SCOPE_MISMATCH", f"{name} must be KnowledgeScopeIdentity")
    return KnowledgeScopeIdentity.from_dict(value)


def _source_ref(value: Any, name: str = "source_ref") -> "SourceRef":
    if isinstance(value, SourceRef):
        return value
    if isinstance(value, Mapping):
        return SourceRef.from_dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return SourceRef.from_dict(value.to_dict())
    raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be a source-backed ref")


def _source_refs(value: Any, name: str = "source_refs") -> tuple["SourceRef", ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an array")
    refs = tuple(_source_ref(item, f"{name}[]") for item in value)
    ids = [item.ref_id for item in refs]
    if len(ids) != len(set(ids)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must contain unique refs")
    return refs


def _symbol_refs(value: Any, name: str) -> tuple["CodeSymbolRef", ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(item if isinstance(item, CodeSymbolRef) else CodeSymbolRef.from_dict(item) for item in value)


def _digest(body: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(body))


@dataclass(frozen=True)
class SourceRef:
    ref_id: str
    source_kind: str
    locator: str
    revision: str
    source_digest: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("ref_id", "source_kind", "locator", "revision", "source_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata", required=False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "source_kind": self.source_kind,
            "locator": self.locator,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceRef":
        raw = _mapping(value, "source_ref")
        return cls(
            ref_id=raw.get("ref_id") or raw.get("source_ref_id"),
            source_kind=raw.get("source_kind") or raw.get("source_category") or "SOURCE",
            locator=raw.get("locator") or raw.get("raw_content_ref") or "opaque://source",
            revision=raw.get("revision") or raw.get("source_revision") or "unknown",
            source_digest=raw.get("source_digest") or raw.get("digest") or _digest(raw),
            metadata=raw.get("metadata") or {},
        )


@dataclass(frozen=True)
class CodeSymbolRef:
    symbol_id: str
    path: str
    kind: str
    line: int | None = None
    source_ref_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_id", _text(self.symbol_id, "symbol_id"))
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        if self.line is not None and (not isinstance(self.line, int) or self.line < 1):
            raise R35Error("R3_5_SCHEMA_INVALID", "line must be a positive integer")
        object.__setattr__(self, "source_ref_id", _optional_text(self.source_ref_id, "source_ref_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "path": self.path,
            "kind": self.kind,
            "line": self.line,
            "source_ref_id": self.source_ref_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeSymbolRef":
        raw = _mapping(value, "symbol_ref")
        return cls(raw["symbol_id"], raw["path"], raw["kind"], raw.get("line"), raw.get("source_ref_id"))


@dataclass(frozen=True)
class PageNode:
    page_node_id: str
    page_key: str
    graph_version: int
    scope: KnowledgeScopeIdentity
    route_patterns: tuple[str, ...] = ()
    router_refs: tuple[CodeSymbolRef, ...] = ()
    menu_refs: tuple[CodeSymbolRef, ...] = ()
    permission_refs: tuple[Mapping[str, Any], ...] = ()
    component_refs: tuple[CodeSymbolRef, ...] = ()
    form_refs: tuple[CodeSymbolRef, ...] = ()
    table_refs: tuple[CodeSymbolRef, ...] = ()
    action_binding_refs: tuple[str, ...] = ()
    api_binding_refs: tuple[str, ...] = ()
    backend_relation_refs: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    knowledge_refs: tuple[str, ...] = ()
    code_defined_state: str = "CODE_DEFINED"
    protection: str = "UNKNOWN"
    dynamic_markers: tuple[str, ...] = ()
    node_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "page_node_id", _text(self.page_node_id, "page_node_id"))
        object.__setattr__(self, "page_key", _text(self.page_key, "page_key"))
        if not isinstance(self.graph_version, int) or self.graph_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "graph_version must be positive")
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "route_patterns", _tuple_text(self.route_patterns, "route_patterns"))
        object.__setattr__(self, "router_refs", _symbol_refs(self.router_refs, "router_refs"))
        object.__setattr__(self, "menu_refs", _symbol_refs(self.menu_refs, "menu_refs"))
        object.__setattr__(self, "permission_refs", _tuple_mapping(self.permission_refs, "permission_refs"))
        object.__setattr__(self, "form_refs", _symbol_refs(self.form_refs, "form_refs"))
        object.__setattr__(self, "table_refs", _symbol_refs(self.table_refs, "table_refs"))
        object.__setattr__(self, "action_binding_refs", _tuple_text(self.action_binding_refs, "action_binding_refs"))
        object.__setattr__(self, "api_binding_refs", _tuple_text(self.api_binding_refs, "api_binding_refs"))
        object.__setattr__(self, "backend_relation_refs", _tuple_text(self.backend_relation_refs, "backend_relation_refs"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        object.__setattr__(self, "knowledge_refs", _tuple_text(self.knowledge_refs, "knowledge_refs"))
        object.__setattr__(self, "code_defined_state", _text(self.code_defined_state, "code_defined_state"))
        object.__setattr__(self, "protection", _text(self.protection, "protection"))
        object.__setattr__(self, "dynamic_markers", _tuple_text(self.dynamic_markers, "dynamic_markers"))
        body = self._body()
        expected = _digest(body)
        if self.node_digest and self.node_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "node_digest does not match immutable node fields")
        object.__setattr__(self, "node_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "page_node_id": self.page_node_id,
            "page_key": self.page_key,
            "graph_version": self.graph_version,
            "scope": self.scope.to_dict(),
            "route_patterns": list(self.route_patterns),
            "router_refs": [item.to_dict() for item in self.router_refs],
            "menu_refs": [item.to_dict() for item in self.menu_refs],
            "permission_refs": [dict(item) for item in self.permission_refs],
            "component_refs": [item.to_dict() for item in self.component_refs],
            "form_refs": [item.to_dict() for item in self.form_refs],
            "table_refs": [item.to_dict() for item in self.table_refs],
            "action_binding_refs": list(self.action_binding_refs),
            "api_binding_refs": list(self.api_binding_refs),
            "backend_relation_refs": list(self.backend_relation_refs),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "knowledge_refs": list(self.knowledge_refs),
            "code_defined_state": self.code_defined_state,
            "protection": self.protection,
            "dynamic_markers": list(self.dynamic_markers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "node_digest": self.node_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageNode":
        raw = _mapping(value, "page_node")
        return cls(
            raw["page_node_id"], raw["page_key"], raw["graph_version"], _scope(raw["scope"]),
            tuple(raw.get("route_patterns") or ()),
            _symbol_refs(raw.get("router_refs"), "router_refs"),
            _symbol_refs(raw.get("menu_refs"), "menu_refs"),
            _tuple_mapping(raw.get("permission_refs"), "permission_refs"),
            _symbol_refs(raw.get("component_refs"), "component_refs"),
            _symbol_refs(raw.get("form_refs"), "form_refs"),
            _symbol_refs(raw.get("table_refs"), "table_refs"),
            tuple(raw.get("action_binding_refs") or ()),
            tuple(raw.get("api_binding_refs") or ()),
            tuple(raw.get("backend_relation_refs") or ()),
            _source_refs(raw.get("source_refs")),
            tuple(raw.get("knowledge_refs") or ()),
            raw.get("code_defined_state", "CODE_DEFINED"),
            raw.get("protection", "UNKNOWN"),
            tuple(raw.get("dynamic_markers") or ()),
            raw.get("node_digest", ""),
        )


@dataclass(frozen=True)
class UserActionBinding:
    binding_id: str
    page_node_ref: str
    action_kind: str
    semantic_target: str
    selector_hint: str | None = None
    component_ref: CodeSymbolRef | None = None
    handler_refs: tuple[CodeSymbolRef, ...] = ()
    form_ref: CodeSymbolRef | None = None
    table_ref: CodeSymbolRef | None = None
    api_binding_refs: tuple[str, ...] = ()
    precondition_refs: tuple[Mapping[str, Any], ...] = ()
    input_schema_ref: str | None = None
    output_oracle_ref: str | None = None
    auth_context_requirement: str = "UNKNOWN"
    source_refs: tuple[SourceRef, ...] = ()
    binding_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("binding_id", "page_node_ref", "action_kind", "semantic_target"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "selector_hint", _optional_text(self.selector_hint, "selector_hint"))
        if self.component_ref is not None and not isinstance(self.component_ref, CodeSymbolRef):
            object.__setattr__(self, "component_ref", CodeSymbolRef.from_dict(self.component_ref))
        object.__setattr__(self, "handler_refs", _symbol_refs(self.handler_refs, "handler_refs"))
        if self.form_ref is not None and not isinstance(self.form_ref, CodeSymbolRef):
            object.__setattr__(self, "form_ref", CodeSymbolRef.from_dict(self.form_ref))
        if self.table_ref is not None and not isinstance(self.table_ref, CodeSymbolRef):
            object.__setattr__(self, "table_ref", CodeSymbolRef.from_dict(self.table_ref))
        object.__setattr__(self, "api_binding_refs", _tuple_text(self.api_binding_refs, "api_binding_refs"))
        object.__setattr__(self, "precondition_refs", _tuple_mapping(self.precondition_refs, "precondition_refs"))
        object.__setattr__(self, "input_schema_ref", _optional_text(self.input_schema_ref, "input_schema_ref"))
        object.__setattr__(self, "output_oracle_ref", _optional_text(self.output_oracle_ref, "output_oracle_ref"))
        object.__setattr__(self, "auth_context_requirement", _text(self.auth_context_requirement, "auth_context_requirement"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        expected = _digest(self._body())
        if self.binding_digest and self.binding_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "binding_digest does not match immutable binding fields")
        object.__setattr__(self, "binding_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "page_node_ref": self.page_node_ref,
            "action_kind": self.action_kind,
            "semantic_target": self.semantic_target,
            "selector_hint": self.selector_hint,
            "component_ref": self.component_ref.to_dict() if self.component_ref else None,
            "handler_refs": [item.to_dict() for item in self.handler_refs],
            "form_ref": self.form_ref.to_dict() if self.form_ref else None,
            "table_ref": self.table_ref.to_dict() if self.table_ref else None,
            "api_binding_refs": list(self.api_binding_refs),
            "precondition_refs": [dict(item) for item in self.precondition_refs],
            "input_schema_ref": self.input_schema_ref,
            "output_oracle_ref": self.output_oracle_ref,
            "auth_context_requirement": self.auth_context_requirement,
            "source_refs": [item.to_dict() for item in self.source_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "binding_digest": self.binding_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UserActionBinding":
        raw = _mapping(value, "user_action_binding")
        return cls(
            raw["binding_id"], raw["page_node_ref"], raw["action_kind"], raw["semantic_target"],
            raw.get("selector_hint"),
            CodeSymbolRef.from_dict(raw["component_ref"]) if raw.get("component_ref") else None,
            _symbol_refs(raw.get("handler_refs"), "handler_refs"),
            CodeSymbolRef.from_dict(raw["form_ref"]) if raw.get("form_ref") else None,
            CodeSymbolRef.from_dict(raw["table_ref"]) if raw.get("table_ref") else None,
            tuple(raw.get("api_binding_refs") or ()),
            _tuple_mapping(raw.get("precondition_refs"), "precondition_refs"),
            raw.get("input_schema_ref"), raw.get("output_oracle_ref"),
            raw.get("auth_context_requirement", "UNKNOWN"),
            _source_refs(raw.get("source_refs")),
            raw.get("binding_digest", ""),
        )


@dataclass(frozen=True)
class PageGraph:
    graph_id: str
    graph_version: int
    scope: KnowledgeScopeIdentity
    source_revision: str
    build_profile_ref: str
    nodes: tuple[PageNode, ...]
    bindings: tuple[UserActionBinding, ...]
    knowledge_refs: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    unresolved_gaps: tuple[Mapping[str, Any], ...] = ()
    status: str = "DRAFT"
    graph_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_id", _text(self.graph_id, "graph_id"))
        if not isinstance(self.graph_version, int) or self.graph_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "graph_version must be positive")
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "build_profile_ref", _text(self.build_profile_ref, "build_profile_ref"))
        if not isinstance(self.nodes, (list, tuple)) or not self.nodes:
            raise R35Error("R3_5_PAGE_MODEL_REQUIRES_SOURCE", "PageGraph requires at least one source-backed PageNode")
        object.__setattr__(self, "nodes", tuple(item if isinstance(item, PageNode) else PageNode.from_dict(item) for item in self.nodes))
        object.__setattr__(self, "bindings", tuple(item if isinstance(item, UserActionBinding) else UserActionBinding.from_dict(item) for item in self.bindings))
        if any(item.scope != self.scope for item in self.nodes):
            raise R35Error("R3_5_SCOPE_MISMATCH", "PageNode scope differs from PageGraph scope")
        if any(item.page_node_ref not in {node.page_node_id for node in self.nodes} for item in self.bindings):
            raise R35Error("R3_5_SCHEMA_INVALID", "UserActionBinding references unknown PageNode")
        object.__setattr__(self, "knowledge_refs", _tuple_text(self.knowledge_refs, "knowledge_refs"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        object.__setattr__(self, "unresolved_gaps", _tuple_mapping(self.unresolved_gaps, "unresolved_gaps"))
        object.__setattr__(self, "status", _text(self.status, "status"))
        if self.status not in PAGE_GRAPH_STATUSES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported PageGraph status: {self.status}")
        expected = _digest(self._body())
        if self.graph_digest and self.graph_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "graph_digest does not match immutable graph fields")
        object.__setattr__(self, "graph_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "scope": self.scope.to_dict(),
            "source_revision": self.source_revision,
            "build_profile_ref": self.build_profile_ref,
            "nodes": [item.to_dict() for item in self.nodes],
            "bindings": [item.to_dict() for item in self.bindings],
            "knowledge_refs": list(self.knowledge_refs),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "unresolved_gaps": [dict(item) for item in self.unresolved_gaps],
            "status": self.status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "graph_digest": self.graph_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageGraph":
        raw = _mapping(value, "page_graph")
        return cls(
            raw["graph_id"], raw["graph_version"], _scope(raw["scope"]),
            raw["source_revision"], raw["build_profile_ref"],
            tuple(PageNode.from_dict(item) for item in raw.get("nodes") or ()),
            tuple(UserActionBinding.from_dict(item) for item in raw.get("bindings") or ()),
            tuple(raw.get("knowledge_refs") or ()),
            _source_refs(raw.get("source_refs")),
            _tuple_mapping(raw.get("unresolved_gaps"), "unresolved_gaps"),
            raw.get("status", "DRAFT"),
            raw.get("graph_digest", ""),
        )


@dataclass(frozen=True)
class PageRuntimeReconciliation:
    graph_ref: str
    page_node_ref: str | None
    browser_context_ref: Mapping[str, Any]
    observation_ref: SourceRef
    observed_route: str | None
    observed_origin: str | None
    observed_state_digest: str
    state: str
    relation_checks: tuple[Mapping[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()
    reconciled_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_ref", _text(self.graph_ref, "graph_ref"))
        object.__setattr__(self, "page_node_ref", _optional_text(self.page_node_ref, "page_node_ref"))
        object.__setattr__(self, "browser_context_ref", _mapping(self.browser_context_ref, "browser_context_ref"))
        object.__setattr__(self, "observation_ref", _source_ref(self.observation_ref, "observation_ref"))
        object.__setattr__(self, "observed_route", _optional_text(self.observed_route, "observed_route"))
        object.__setattr__(self, "observed_origin", _optional_text(self.observed_origin, "observed_origin"))
        object.__setattr__(self, "observed_state_digest", _text(self.observed_state_digest, "observed_state_digest"))
        object.__setattr__(self, "state", _text(self.state, "state"))
        if self.state not in PAGE_RECONCILIATION_STATES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported reconciliation state: {self.state}")
        object.__setattr__(self, "relation_checks", _tuple_mapping(self.relation_checks, "relation_checks"))
        object.__setattr__(self, "reasons", _tuple_text(self.reasons, "reasons"))
        object.__setattr__(self, "reconciled_at", _text(self.reconciled_at, "reconciled_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_ref": self.graph_ref,
            "page_node_ref": self.page_node_ref,
            "browser_context_ref": dict(self.browser_context_ref),
            "observation_ref": self.observation_ref.to_dict(),
            "observed_route": self.observed_route,
            "observed_origin": self.observed_origin,
            "observed_state_digest": self.observed_state_digest,
            "state": self.state,
            "relation_checks": [dict(item) for item in self.relation_checks],
            "reasons": list(self.reasons),
            "reconciled_at": self.reconciled_at,
        }


def _validate_states(value: Any, name: str) -> dict[str, Any]:
    state = _mapping(value, name)
    if not state:
        raise R35Error("R3_5_JOURNEY_START_END_REQUIRED", f"{name} must not be empty")
    return state


@dataclass(frozen=True)
class JourneyStep:
    step_id: str
    journey_id: str
    ordinal: int
    actor: str
    system_ref: str
    execution_type: str
    pre_state: Mapping[str, Any]
    action_ref: Any
    input_ref: Any
    expected_transition_ref: str
    auth_context_ref: Mapping[str, Any] | None = None
    browser_context_ref: Mapping[str, Any] | None = None
    oracle_refs: tuple[str, ...] = ()
    result_ref: str | None = None
    status: str = "PLANNED"
    source_refs: tuple[SourceRef, ...] = ()
    step_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("step_id", "journey_id", "actor", "system_ref", "expected_transition_ref", "status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "step ordinal must be positive")
        object.__setattr__(self, "execution_type", _text(self.execution_type, "execution_type").upper())
        if self.execution_type not in EXECUTION_TYPES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported execution_type: {self.execution_type}")
        if self.status not in JOURNEY_STEP_STATUSES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported JourneyStep status: {self.status}")
        object.__setattr__(self, "pre_state", _validate_states(self.pre_state, "pre_state"))
        _reject_secrets(self.action_ref, "action_ref")
        _reject_secrets(self.input_ref, "input_ref")
        if self.auth_context_ref is not None:
            object.__setattr__(self, "auth_context_ref", _mapping(self.auth_context_ref, "auth_context_ref"))
        if self.browser_context_ref is not None:
            object.__setattr__(self, "browser_context_ref", _mapping(self.browser_context_ref, "browser_context_ref"))
        object.__setattr__(self, "oracle_refs", _tuple_text(self.oracle_refs, "oracle_refs"))
        object.__setattr__(self, "result_ref", _optional_text(self.result_ref, "result_ref"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        expected = _digest(self._body())
        if self.step_digest and self.step_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "step_digest does not match immutable step fields")
        object.__setattr__(self, "step_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id, "journey_id": self.journey_id, "ordinal": self.ordinal,
            "actor": self.actor, "system_ref": self.system_ref, "execution_type": self.execution_type,
            "pre_state": dict(self.pre_state), "action_ref": self.action_ref, "input_ref": self.input_ref,
            "expected_transition_ref": self.expected_transition_ref,
            "auth_context_ref": dict(self.auth_context_ref) if self.auth_context_ref else None,
            "browser_context_ref": dict(self.browser_context_ref) if self.browser_context_ref else None,
            "oracle_refs": list(self.oracle_refs), "result_ref": self.result_ref, "status": self.status,
            "source_refs": [item.to_dict() for item in self.source_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "step_digest": self.step_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JourneyStep":
        raw = _mapping(value, "journey_step")
        return cls(
            raw["step_id"], raw["journey_id"], raw["ordinal"], raw["actor"], raw["system_ref"],
            raw["execution_type"], raw["pre_state"], raw.get("action_ref"), raw.get("input_ref"),
            raw["expected_transition_ref"], raw.get("auth_context_ref"), raw.get("browser_context_ref"),
            tuple(raw.get("oracle_refs") or ()), raw.get("result_ref"), raw.get("status", "PLANNED"),
            _source_refs(raw.get("source_refs")), raw.get("step_digest", ""),
        )


@dataclass(frozen=True)
class JourneyTransition:
    transition_id: str
    journey_id: str
    ordinal: int
    from_state: Mapping[str, Any]
    to_state: Mapping[str, Any]
    trigger_step_ref: str
    cross_system_boundary: Mapping[str, Any] | None = None
    expected_data_refs: tuple[str, ...] = ()
    expected_event_refs: tuple[str, ...] = ()
    expected_log_refs: tuple[str, ...] = ()
    oracle_refs: tuple[str, ...] = ()
    observed_evidence_refs: tuple[str, ...] = ()
    status: str = "PLANNED"
    observed_at: str | None = None
    source_refs: tuple[SourceRef, ...] = ()
    transition_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("transition_id", "journey_id", "trigger_step_ref", "status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "transition ordinal must be positive")
        object.__setattr__(self, "from_state", _validate_states(self.from_state, "from_state"))
        object.__setattr__(self, "to_state", _validate_states(self.to_state, "to_state"))
        if self.cross_system_boundary is not None:
            object.__setattr__(self, "cross_system_boundary", _mapping(self.cross_system_boundary, "cross_system_boundary"))
        for name in ("expected_data_refs", "expected_event_refs", "expected_log_refs", "oracle_refs", "observed_evidence_refs"):
            object.__setattr__(self, name, _tuple_text(getattr(self, name), name))
        object.__setattr__(self, "observed_at", _optional_text(self.observed_at, "observed_at"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        expected = _digest(self._body())
        if self.transition_digest and self.transition_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "transition_digest does not match immutable transition fields")
        object.__setattr__(self, "transition_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id, "journey_id": self.journey_id, "ordinal": self.ordinal,
            "from_state": dict(self.from_state), "to_state": dict(self.to_state),
            "trigger_step_ref": self.trigger_step_ref,
            "cross_system_boundary": dict(self.cross_system_boundary) if self.cross_system_boundary else None,
            "expected_data_refs": list(self.expected_data_refs), "expected_event_refs": list(self.expected_event_refs),
            "expected_log_refs": list(self.expected_log_refs), "oracle_refs": list(self.oracle_refs),
            "observed_evidence_refs": list(self.observed_evidence_refs), "status": self.status,
            "observed_at": self.observed_at, "source_refs": [item.to_dict() for item in self.source_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "transition_digest": self.transition_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JourneyTransition":
        raw = _mapping(value, "journey_transition")
        return cls(
            raw["transition_id"], raw["journey_id"], raw["ordinal"], raw["from_state"], raw["to_state"],
            raw["trigger_step_ref"], raw.get("cross_system_boundary"),
            tuple(raw.get("expected_data_refs") or ()), tuple(raw.get("expected_event_refs") or ()),
            tuple(raw.get("expected_log_refs") or ()), tuple(raw.get("oracle_refs") or ()),
            tuple(raw.get("observed_evidence_refs") or ()), raw.get("status", "PLANNED"),
            raw.get("observed_at"), _source_refs(raw.get("source_refs")), raw.get("transition_digest", ""),
        )


@dataclass(frozen=True)
class BusinessJourney:
    journey_id: str
    journey_version: int
    scope: KnowledgeScopeIdentity
    business_start_state: Mapping[str, Any]
    steps: tuple[JourneyStep, ...]
    ordered_transition_refs: tuple[str, ...]
    business_end_state: Mapping[str, Any]
    participating_system_refs: tuple[str, ...]
    page_graph_refs: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    knowledge_refs: tuple[str, ...] = ()
    oracle_refs: tuple[str, ...] = ()
    lifecycle: str = "DRAFT"
    journey_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "journey_id", _text(self.journey_id, "journey_id"))
        if not isinstance(self.journey_version, int) or self.journey_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "journey_version must be positive")
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "business_start_state", _validate_states(self.business_start_state, "business_start_state"))
        object.__setattr__(self, "steps", tuple(item if isinstance(item, JourneyStep) else JourneyStep.from_dict(item) for item in self.steps))
        if not self.steps:
            raise R35Error("R3_5_JOURNEY_START_END_REQUIRED", "BusinessJourney requires ordered steps")
        ordinals = [item.ordinal for item in self.steps]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "JourneyStep ordinals must be contiguous and ordered")
        if any(item.journey_id != self.journey_id for item in self.steps):
            raise R35Error("R3_5_SCOPE_MISMATCH", "JourneyStep belongs to another Journey")
        object.__setattr__(self, "ordered_transition_refs", _tuple_text(self.ordered_transition_refs, "ordered_transition_refs", required=True))
        object.__setattr__(self, "business_end_state", _validate_states(self.business_end_state, "business_end_state"))
        object.__setattr__(self, "participating_system_refs", _tuple_text(self.participating_system_refs, "participating_system_refs", required=True))
        step_systems = {item.system_ref for item in self.steps}
        if len(set(self.participating_system_refs) | step_systems) < 2:
            raise R35Error("R3_5_CROSS_SYSTEM_RELATION_MISSING", "BusinessJourney requires at least two participating systems")
        object.__setattr__(self, "page_graph_refs", _tuple_text(self.page_graph_refs, "page_graph_refs"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        object.__setattr__(self, "knowledge_refs", _tuple_text(self.knowledge_refs, "knowledge_refs"))
        object.__setattr__(self, "oracle_refs", _tuple_text(self.oracle_refs, "oracle_refs"))
        if not self.source_refs and not self.knowledge_refs:
            raise R35Error("R3_5_KNOWLEDGE_REF_MISSING", "BusinessJourney requires source or Knowledge refs")
        object.__setattr__(self, "lifecycle", _text(self.lifecycle, "lifecycle"))
        expected = _digest(self._body())
        if self.journey_digest and self.journey_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "journey_digest does not match immutable journey fields")
        object.__setattr__(self, "journey_digest", expected)

    @property
    def ordered_step_refs(self) -> tuple[str, ...]:
        return tuple(item.step_id for item in self.steps)

    def _body(self) -> dict[str, Any]:
        return {
            "journey_id": self.journey_id, "journey_version": self.journey_version,
            "scope": self.scope.to_dict(), "business_start_state": dict(self.business_start_state),
            "steps": [item.to_dict() for item in self.steps],
            "ordered_step_refs": list(self.ordered_step_refs),
            "ordered_transition_refs": list(self.ordered_transition_refs),
            "business_end_state": dict(self.business_end_state),
            "participating_system_refs": list(self.participating_system_refs),
            "page_graph_refs": list(self.page_graph_refs),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "knowledge_refs": list(self.knowledge_refs), "oracle_refs": list(self.oracle_refs),
            "lifecycle": self.lifecycle,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "journey_digest": self.journey_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BusinessJourney":
        raw = _mapping(value, "business_journey")
        return cls(
            raw["journey_id"], raw["journey_version"], _scope(raw["scope"]),
            raw["business_start_state"],
            tuple(JourneyStep.from_dict(item) for item in raw.get("steps") or ()),
            tuple(raw.get("ordered_transition_refs") or ()),
            raw["business_end_state"], tuple(raw.get("participating_system_refs") or ()),
            tuple(raw.get("page_graph_refs") or ()), _source_refs(raw.get("source_refs")),
            tuple(raw.get("knowledge_refs") or ()), tuple(raw.get("oracle_refs") or ()),
            raw.get("lifecycle", "DRAFT"), raw.get("journey_digest", ""),
        )


@dataclass(frozen=True)
class JourneyCheckpoint:
    checkpoint_id: str
    journey_id: str
    journey_version: int
    next_step_ordinal: int
    last_transition_ref: str | None
    r1_cursor_ref: str | None
    attempt_ref: str | None
    session_ref: str | None
    auth_context_ref: Mapping[str, Any] | None
    browser_context_ref: Mapping[str, Any] | None
    workset_digest: str
    retrieval_cursor_ref: str | None
    checkpoint_reason: str
    checkpoint_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("checkpoint_id", "journey_id", "workset_digest", "checkpoint_reason"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.journey_version, int) or self.journey_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "journey_version must be positive")
        if not isinstance(self.next_step_ordinal, int) or self.next_step_ordinal < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "next_step_ordinal must be positive")
        for name in ("last_transition_ref", "r1_cursor_ref", "attempt_ref", "session_ref", "retrieval_cursor_ref"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.auth_context_ref is not None:
            object.__setattr__(self, "auth_context_ref", _mapping(self.auth_context_ref, "auth_context_ref"))
        if self.browser_context_ref is not None:
            object.__setattr__(self, "browser_context_ref", _mapping(self.browser_context_ref, "browser_context_ref"))
        expected = _digest(self._body())
        if self.checkpoint_digest and self.checkpoint_digest != expected:
            raise R35Error("R3_5_CHECKPOINT_DIGEST_MISMATCH", "checkpoint_digest does not match checkpoint")
        object.__setattr__(self, "checkpoint_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "journey_id": self.journey_id,
            "journey_version": self.journey_version, "next_step_ordinal": self.next_step_ordinal,
            "last_transition_ref": self.last_transition_ref, "r1_cursor_ref": self.r1_cursor_ref,
            "attempt_ref": self.attempt_ref, "session_ref": self.session_ref,
            "auth_context_ref": dict(self.auth_context_ref) if self.auth_context_ref else None,
            "browser_context_ref": dict(self.browser_context_ref) if self.browser_context_ref else None,
            "workset_digest": self.workset_digest, "retrieval_cursor_ref": self.retrieval_cursor_ref,
            "checkpoint_reason": self.checkpoint_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "checkpoint_digest": self.checkpoint_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JourneyCheckpoint":
        raw = _mapping(value, "journey_checkpoint")
        return cls(
            raw["checkpoint_id"], raw["journey_id"], raw["journey_version"], raw["next_step_ordinal"],
            raw.get("last_transition_ref"), raw.get("r1_cursor_ref"), raw.get("attempt_ref"),
            raw.get("session_ref"), raw.get("auth_context_ref"), raw.get("browser_context_ref"),
            raw["workset_digest"], raw.get("retrieval_cursor_ref"), raw["checkpoint_reason"],
            raw.get("checkpoint_digest", ""),
        )


@dataclass(frozen=True)
class JourneyVerification:
    verification_id: str
    journey_id: str
    journey_version: int
    execution_id: str
    executed_step_refs: tuple[str, ...]
    observed_transition_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_refs: tuple[SourceRef, ...]
    auth_receipt_refs: tuple[str, ...]
    browser_receipt_refs: tuple[str, ...]
    oracle_evaluations: tuple[Mapping[str, Any], ...]
    runtime_execution: str
    result: str
    evidence_class: str = "ENGINEERING_EVIDENCE"
    verified_status: str = "NOT_VERIFIED"
    verification_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("verification_id", "journey_id", "execution_id", "runtime_execution", "result", "evidence_class", "verified_status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.journey_version, int) or self.journey_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "journey_version must be positive")
        for name in ("executed_step_refs", "observed_transition_refs", "evidence_refs", "auth_receipt_refs", "browser_receipt_refs"):
            object.__setattr__(self, name, _tuple_text(getattr(self, name), name))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        object.__setattr__(self, "oracle_evaluations", _tuple_mapping(self.oracle_evaluations, "oracle_evaluations"))
        if self.runtime_execution not in RUNTIME_EXECUTIONS:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported runtime_execution: {self.runtime_execution}")
        if self.result not in VERIFICATION_RESULTS:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported verification result: {self.result}")
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported evidence_class: {self.evidence_class}")
        if self.verified_status not in {"VERIFIED", "NOT_VERIFIED"}:
            raise R35Error("R3_5_SCHEMA_INVALID", "verified_status must be VERIFIED or NOT_VERIFIED")
        if self.verified_status == "VERIFIED":
            if self.runtime_execution != "REAL" or self.evidence_class != "FIELD_EVIDENCE" or self.result != "PASS":
                raise R35Error("R3_5_VERIFIED_INELIGIBLE", "VERIFIED requires REAL FIELD_EVIDENCE and PASS")
            if not self.evidence_refs or not self.executed_step_refs or not self.observed_transition_refs:
                raise R35Error("R3_5_VERIFIED_INELIGIBLE", "VERIFIED requires complete execution and evidence refs")
            if any(item.get("result") not in {"PASS", "PASSED", True} for item in self.oracle_evaluations):
                raise R35Error("R3_5_VERIFIED_INELIGIBLE", "VERIFIED requires passing business oracles")
        expected = _digest(self._body())
        if self.verification_digest and self.verification_digest != expected:
            raise R35Error("R3_5_SCHEMA_INVALID", "verification_digest does not match verification")
        object.__setattr__(self, "verification_digest", expected)

    def _body(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id, "journey_id": self.journey_id,
            "journey_version": self.journey_version, "execution_id": self.execution_id,
            "executed_step_refs": list(self.executed_step_refs),
            "observed_transition_refs": list(self.observed_transition_refs),
            "evidence_refs": list(self.evidence_refs),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "auth_receipt_refs": list(self.auth_receipt_refs),
            "browser_receipt_refs": list(self.browser_receipt_refs),
            "oracle_evaluations": [dict(item) for item in self.oracle_evaluations],
            "runtime_execution": self.runtime_execution, "result": self.result,
            "evidence_class": self.evidence_class, "verified_status": self.verified_status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "verification_digest": self.verification_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JourneyVerification":
        raw = _mapping(value, "journey_verification")
        return cls(
            raw["verification_id"], raw["journey_id"], raw["journey_version"], raw["execution_id"],
            tuple(raw.get("executed_step_refs") or ()), tuple(raw.get("observed_transition_refs") or ()),
            tuple(raw.get("evidence_refs") or ()), _source_refs(raw.get("source_refs")),
            tuple(raw.get("auth_receipt_refs") or ()), tuple(raw.get("browser_receipt_refs") or ()),
            _tuple_mapping(raw.get("oracle_evaluations"), "oracle_evaluations"),
            raw["runtime_execution"], raw["result"], raw.get("evidence_class", "ENGINEERING_EVIDENCE"),
            raw.get("verified_status", "NOT_VERIFIED"), raw.get("verification_digest", ""),
        )


@dataclass(frozen=True)
class R35State:
    mission_id: str
    page_graphs: tuple[PageGraph, ...] = ()
    journeys: tuple[BusinessJourney, ...] = ()
    transitions: tuple[JourneyTransition, ...] = ()
    checkpoints: tuple[JourneyCheckpoint, ...] = ()
    verifications: tuple[JourneyVerification, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))

    def page_graph(self, graph_id: str, graph_version: int | None = None) -> PageGraph | None:
        return next((item for item in self.page_graphs if item.graph_id == graph_id and (graph_version is None or item.graph_version == graph_version)), None)

    def journey(self, journey_id: str, journey_version: int | None = None) -> BusinessJourney | None:
        return next((item for item in self.journeys if item.journey_id == journey_id and (journey_version is None or item.journey_version == journey_version)), None)

    def transition(self, transition_id: str) -> JourneyTransition | None:
        return next((item for item in self.transitions if item.transition_id == transition_id), None)

    def checkpoint(self, checkpoint_id: str) -> JourneyCheckpoint | None:
        return next((item for item in self.checkpoints if item.checkpoint_id == checkpoint_id), None)

    def verification(self, verification_id: str) -> JourneyVerification | None:
        return next((item for item in self.verifications if item.verification_id == verification_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "page_graphs": [item.to_dict() for item in sorted(self.page_graphs, key=lambda x: (x.graph_id, x.graph_version))],
            "journeys": [item.to_dict() for item in sorted(self.journeys, key=lambda x: (x.journey_id, x.journey_version))],
            "transitions": [item.to_dict() for item in sorted(self.transitions, key=lambda x: x.transition_id)],
            "checkpoints": [item.to_dict() for item in sorted(self.checkpoints, key=lambda x: x.checkpoint_id)],
            "verifications": [item.to_dict() for item in sorted(self.verifications, key=lambda x: x.verification_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R35State":
        raw = _mapping(value, "r3_5_state")
        return cls(
            raw["mission_id"],
            tuple(PageGraph.from_dict(item) for item in raw.get("page_graphs") or ()),
            tuple(BusinessJourney.from_dict(item) for item in raw.get("journeys") or ()),
            tuple(JourneyTransition.from_dict(item) for item in raw.get("transitions") or ()),
            tuple(JourneyCheckpoint.from_dict(item) for item in raw.get("checkpoints") or ()),
            tuple(JourneyVerification.from_dict(item) for item in raw.get("verifications") or ()),
        )
