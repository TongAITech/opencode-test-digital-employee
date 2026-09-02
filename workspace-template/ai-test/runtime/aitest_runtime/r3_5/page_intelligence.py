from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.r3_e1 import KnowledgeRetrievalResult, KnowledgeScopeIdentity

from .contracts import (
    BACKEND_SURFACES,
    FRONTEND_SURFACES,
    CodeSymbolRef,
    PageGraph,
    PageNode,
    SourceRef,
    UserActionBinding,
)
from .errors import R35Error
from .workset import WorkSetResult


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _scope(value: Any) -> KnowledgeScopeIdentity:
    if isinstance(value, KnowledgeScopeIdentity):
        return value
    if isinstance(value, Mapping):
        return KnowledgeScopeIdentity.from_dict(value)
    raise R35Error("R3_5_SCOPE_MISMATCH", "scope must be KnowledgeScopeIdentity")


def _symbol(fact: Mapping[str, Any], *, fallback_kind: str) -> CodeSymbolRef:
    path = fact.get("path") or fact.get("file_path")
    symbol_id = fact.get("symbol_id") or fact.get("symbol") or fact.get("id")
    if not path or not symbol_id:
        raise R35Error("R3_5_SOURCE_REVISION_REQUIRED", "code fact requires path and symbol_id")
    line = fact.get("line") or fact.get("line_number")
    return CodeSymbolRef(
        symbol_id=str(symbol_id),
        path=str(path),
        kind=str(fact.get("symbol_kind") or fact.get("kind") or fallback_kind),
        line=int(line) if line is not None else None,
        source_ref_id=fact.get("source_ref_id"),
    )


def _source_refs_for(fact: Mapping[str, Any], known: Mapping[str, SourceRef]) -> tuple[SourceRef, ...]:
    values = fact.get("source_refs")
    if values is None and fact.get("source_ref") is not None:
        values = [fact.get("source_ref")]
    if values is None and fact.get("source_ref_id") is not None:
        ref = known.get(str(fact["source_ref_id"]))
        values = [ref] if ref is not None else []
    refs: list[SourceRef] = []
    for value in values or ():
        if isinstance(value, str):
            ref = known.get(value)
            if ref is None:
                raise R35Error("R3_5_KNOWLEDGE_REF_MISSING", f"unknown source ref: {value}")
        else:
            ref = value if isinstance(value, SourceRef) else SourceRef.from_dict(value)
        refs.append(ref)
    if not refs:
        raise R35Error("R3_5_PAGE_MODEL_REQUIRES_SOURCE", "code fact is not source-backed")
    return tuple(refs)


@dataclass(frozen=True)
class PageGraphBuildRequest:
    graph_id: str
    graph_version: int
    scope: KnowledgeScopeIdentity
    source_revision: str
    build_profile_ref: str
    code_facts: tuple[Mapping[str, Any], ...]
    source_refs: tuple[SourceRef, ...] = ()
    knowledge_refs: tuple[str, ...] = ()
    expected_surfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_id", _text(self.graph_id, "graph_id"))
        if not isinstance(self.graph_version, int) or self.graph_version < 1:
            raise R35Error("R3_5_SCHEMA_INVALID", "graph_version must be positive")
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "build_profile_ref", _text(self.build_profile_ref, "build_profile_ref"))
        if not isinstance(self.code_facts, (list, tuple)):
            raise R35Error("R3_5_SCHEMA_INVALID", "code_facts must be an array")
        if not self.code_facts:
            raise R35Error("R3_5_DOM_ONLY_PAGE_MODEL_FORBIDDEN", "PageGraph cannot be built from runtime/DOM observations only")
        if any(not isinstance(item, Mapping) for item in self.code_facts):
            raise R35Error("R3_5_SCHEMA_INVALID", "code_facts must contain objects")
        object.__setattr__(self, "code_facts", tuple(dict(item) for item in self.code_facts))
        object.__setattr__(self, "source_refs", tuple(item if isinstance(item, SourceRef) else SourceRef.from_dict(item) for item in self.source_refs))
        object.__setattr__(self, "knowledge_refs", tuple(str(item) for item in self.knowledge_refs))
        object.__setattr__(self, "expected_surfaces", tuple(str(item) for item in self.expected_surfaces))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PageGraphBuildRequest":
        raw = dict(value)
        return cls(
            graph_id=raw["graph_id"],
            graph_version=raw.get("graph_version", 1),
            scope=_scope(raw["scope"]),
            source_revision=raw["source_revision"],
            build_profile_ref=raw.get("build_profile_ref", "r3_5-code-first-v1"),
            code_facts=tuple(raw.get("code_facts") or ()),
            source_refs=tuple(raw.get("source_refs") or ()),
            knowledge_refs=tuple(raw.get("knowledge_refs") or ()),
            expected_surfaces=tuple(raw.get("expected_surfaces") or ()),
        )


@dataclass(frozen=True)
class PageGraphBuildResult:
    graph: PageGraph
    engineering_evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"graph": self.graph.to_dict(), "engineering_evidence": dict(self.engineering_evidence)}


def _knowledge_values(value: Any) -> tuple[tuple[str, ...], tuple[SourceRef, ...], tuple[Mapping[str, Any], ...]]:
    if value is None:
        return (), (), ()
    source = value.retrieval if isinstance(value, WorkSetResult) else value
    if not isinstance(source, KnowledgeRetrievalResult):
        raise R35Error("R3_5_SCHEMA_INVALID", "knowledge_result must be an R3.E1 retrieval result")
    relation_ids = tuple(item.relation_id for item in source.relations)
    refs = tuple(SourceRef.from_dict(item.to_dict()) for item in source.source_refs)
    gaps: list[Mapping[str, Any]] = []
    for item in source.excluded_refs:
        gaps.append({
            "kind": "KNOWLEDGE_RETRIEVAL_GAP",
            "ref": item.get("ref") or item.get("id") or item.get("version_id"),
            "reason": item.get("reason") or "EXCLUDED",
        })
    for item in source.conflicts:
        gaps.append({
            "kind": "R3_5_KNOWLEDGE_RELATION_STALE_OR_CONFLICTED",
            "ref": item.conflict_id,
            "reason": "CONFLICTED",
            "source_ref_ids": list(item.source_ref_ids),
        })
    for item in source.freshness:
        if item.result != "FRESH":
            gaps.append({
                "kind": "R3_5_KNOWLEDGE_RELATION_STALE_OR_CONFLICTED",
                "ref": item.target_version_id,
                "reason": item.result,
                "source_ref_ids": list(item.source_ref_ids),
            })
    return relation_ids, refs, tuple(gaps)


def _relation_for_fact(fact: Mapping[str, Any]) -> str | None:
    value = fact.get("knowledge_ref") or fact.get("relation_id") or fact.get("knowledge_id")
    return str(value) if value is not None else None


def build_page_graph(
    request: PageGraphBuildRequest | Mapping[str, Any],
    *,
    knowledge_result: WorkSetResult | KnowledgeRetrievalResult | None = None,
) -> PageGraphBuildResult:
    if isinstance(request, Mapping):
        request = PageGraphBuildRequest.from_mapping(request)
    if not isinstance(request, PageGraphBuildRequest):
        raise R35Error("R3_5_SCHEMA_INVALID", "build_page_graph requires PageGraphBuildRequest")

    known_sources = {item.ref_id: item for item in request.source_refs}
    relation_ids, knowledge_sources, knowledge_gaps = _knowledge_values(knowledge_result)
    graph_sources: dict[str, SourceRef] = {item.ref_id: item for item in (*request.source_refs, *knowledge_sources)}
    graph_knowledge = set(request.knowledge_refs)
    graph_knowledge.update(relation_ids)
    grouped: dict[str, list[dict[str, Any]]] = {}
    gaps: list[dict[str, Any]] = [dict(item) for item in knowledge_gaps]
    for index, raw in enumerate(request.code_facts):
        fact = dict(raw)
        surface = str(fact.get("surface") or fact.get("layer") or fact.get("kind") or "").lower()
        if surface in {"dom", "runtime", "browser_runtime", "runtime_observation"} or str(fact.get("origin") or "").lower() in {"dom", "runtime"}:
            gaps.append({
                "kind": "DOM_SCAN_IS_NOT_PAGE_MODEL",
                "index": index,
                "surface": surface or "DOM",
                "reason": "runtime observation is reconciliation input only",
            })
            continue
        page_key = fact.get("page_key") or fact.get("page") or fact.get("route")
        try:
            refs = _source_refs_for(fact, known_sources)
        except R35Error:
            raise
        for ref in refs:
            graph_sources[ref.ref_id] = ref
        if not page_key:
            gaps.append({"kind": "UNRESOLVED_SOURCE_MAPPING", "index": index, "surface": surface or "UNKNOWN", "reason": "page_key_missing"})
            continue
        fact["surface"] = surface
        fact["_source_refs"] = refs
        relation_id = _relation_for_fact(fact)
        if relation_id:
            graph_knowledge.add(relation_id)
        if fact.get("unresolved"):
            gaps.append({
                "kind": "UNRESOLVED_SOURCE_MAPPING",
                "page_key": str(page_key),
                "surface": surface or "UNKNOWN",
                "reason": str(fact.get("reason") or "source_mapping_unresolved"),
            })
        grouped.setdefault(str(page_key), []).append(fact)

    if not grouped:
        raise R35Error("R3_5_PAGE_MODEL_REQUIRES_SOURCE", "no code-backed PageNode could be admitted")

    nodes: list[PageNode] = []
    bindings: list[UserActionBinding] = []
    for page_key, facts in sorted(grouped.items()):
        node_id = f"{request.graph_id}:v{request.graph_version}:{page_key}"
        routes: list[str] = []
        router_refs: list[CodeSymbolRef] = []
        menu_refs: list[CodeSymbolRef] = []
        permission_refs: list[Mapping[str, Any]] = []
        component_refs: list[CodeSymbolRef] = []
        form_refs: list[CodeSymbolRef] = []
        table_refs: list[CodeSymbolRef] = []
        action_refs: list[str] = []
        api_refs: list[str] = []
        backend_refs: list[str] = []
        node_sources: dict[str, SourceRef] = {}
        node_knowledge: set[str] = set()
        protection = "PUBLIC"
        dynamic_markers: list[str] = []
        for fact in facts:
            surface = fact["surface"]
            refs = tuple(fact["_source_refs"])
            node_sources.update({item.ref_id: item for item in refs})
            relation_id = _relation_for_fact(fact)
            if relation_id:
                node_knowledge.add(relation_id)
            route = fact.get("route") or fact.get("route_pattern")
            if route:
                routes.append(str(route))
            symbol = _symbol(fact, fallback_kind=surface.upper())
            if surface == "router":
                router_refs.append(symbol)
            elif surface == "menu":
                menu_refs.append(symbol)
            elif surface == "permission":
                permission_refs.append({
                    "permission": fact.get("permission") or fact.get("name") or symbol.symbol_id,
                    "symbol_ref": symbol.to_dict(),
                    "source_ref_ids": [item.ref_id for item in refs],
                })
                protection = "PERMISSION_REQUIRED"
            elif surface == "component":
                component_refs.append(symbol)
            elif surface == "form":
                form_refs.append(symbol)
            elif surface == "table":
                table_refs.append(symbol)
            elif surface in {"api_binding", "api"}:
                api_refs.append(str(fact.get("api_binding_id") or fact.get("binding_id") or relation_id or symbol.symbol_id))
            elif surface in {"controller", "service", "repository", "db", "external_client"}:
                backend_refs.append(str(fact.get("relation_id") or fact.get("knowledge_ref") or symbol.symbol_id))
            elif surface in {"action", "handler"}:
                binding_id = str(fact.get("binding_id") or f"{node_id}:action:{len(bindings) + 1}")
                action_kind = str(fact.get("action_kind") or ("CLICK" if surface == "action" else "CUSTOM")).upper()
                binding = UserActionBinding(
                    binding_id=binding_id,
                    page_node_ref=node_id,
                    action_kind=action_kind,
                    semantic_target=str(fact.get("semantic_target") or fact.get("target") or symbol.symbol_id),
                    selector_hint=fact.get("selector_hint") or fact.get("selector"),
                    component_ref=symbol if surface == "action" else None,
                    handler_refs=(symbol,) if surface == "handler" else (),
                    form_ref=form_refs[-1] if form_refs and fact.get("form_ref") else None,
                    table_ref=table_refs[-1] if table_refs and fact.get("table_ref") else None,
                    api_binding_refs=tuple(str(item) for item in fact.get("api_binding_refs") or (())),
                    precondition_refs=tuple(dict(item) for item in fact.get("precondition_refs") or ()),
                    input_schema_ref=fact.get("input_schema_ref"),
                    output_oracle_ref=fact.get("output_oracle_ref"),
                    auth_context_requirement=str(fact.get("auth_context_requirement") or ("PERMISSION_REQUIRED" if protection == "PERMISSION_REQUIRED" else "PUBLIC")),
                    source_refs=refs,
                )
                bindings.append(binding)
                action_refs.append(binding_id)
            else:
                gaps.append({"kind": "UNRESOLVED_SOURCE_MAPPING", "page_key": page_key, "surface": surface or "UNKNOWN", "reason": "unsupported_surface"})
            if fact.get("auth_required"):
                protection = "AUTH_REQUIRED"
            if fact.get("dynamic_marker"):
                dynamic_markers.append(str(fact["dynamic_marker"]))
        missing_expected = set(request.expected_surfaces) - {item["surface"] for item in facts}
        for surface in sorted(missing_expected):
            gaps.append({"kind": "UNRESOLVED_SOURCE_MAPPING", "page_key": page_key, "surface": surface, "reason": "expected_surface_missing"})
        nodes.append(PageNode(
            page_node_id=node_id,
            page_key=page_key,
            graph_version=request.graph_version,
            scope=request.scope,
            route_patterns=tuple(dict.fromkeys(routes)),
            router_refs=tuple(router_refs),
            menu_refs=tuple(menu_refs),
            permission_refs=tuple(permission_refs),
            component_refs=tuple(component_refs),
            form_refs=tuple(form_refs),
            table_refs=tuple(table_refs),
            action_binding_refs=tuple(action_refs),
            api_binding_refs=tuple(dict.fromkeys(api_refs)),
            backend_relation_refs=tuple(dict.fromkeys(backend_refs)),
            source_refs=tuple(node_sources.values()),
            knowledge_refs=tuple(sorted(node_knowledge)),
            code_defined_state="CODE_PARTIAL" if missing_expected or dynamic_markers else "CODE_DEFINED",
            protection=protection,
            dynamic_markers=tuple(dynamic_markers),
        ))

    graph = PageGraph(
        graph_id=request.graph_id,
        graph_version=request.graph_version,
        scope=request.scope,
        source_revision=request.source_revision,
        build_profile_ref=request.build_profile_ref,
        nodes=tuple(nodes),
        bindings=tuple(bindings),
        knowledge_refs=tuple(sorted(graph_knowledge)),
        source_refs=tuple(graph_sources.values()),
        unresolved_gaps=tuple(gaps),
        status="SOURCE_MAPPED",
    )
    return PageGraphBuildResult(
        graph=graph,
        engineering_evidence={
            "evidence_class": "ENGINEERING_EVIDENCE",
            "source_revision": request.source_revision,
            "graph_digest": graph.graph_digest,
            "node_count": len(graph.nodes),
            "binding_count": len(graph.bindings),
            "unresolved_gap_count": len(graph.unresolved_gaps),
            "knowledge_relation_refs": list(graph.knowledge_refs),
            "dom_scan_used": False,
        },
    )
