from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import canonical_json, canonical_sha256
from aitest_runtime.r3_e1 import (
    ARCHITECTURE_BASELINE_REF,
    DEFAULT_RETRIEVAL_STATUSES,
    HARD_MAX_BYTES,
    HARD_MAX_ITEMS,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResult,
    KnowledgeScopeIdentity,
)

from .errors import R35Error


class KnowledgeRetrievalPort(Protocol):
    def retrieve(self, request: KnowledgeRetrievalRequest | Mapping[str, Any]) -> KnowledgeRetrievalResult:
        ...


@dataclass(frozen=True)
class WorkSetRequest:
    scope: KnowledgeScopeIdentity
    anchor: Mapping[str, Any]
    refs: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    allowed_statuses: tuple[str, ...] = ()
    max_hops: int = 5
    max_items: int = HARD_MAX_ITEMS
    max_bytes: int = HARD_MAX_BYTES
    semantic_batch_key: str = "r3_5-default"
    context_policy_ref: str = "runtime-capability-fact"
    continuation_cursor: str | None = None
    exclude_digests: tuple[str, ...] = ()
    session_ref: str | None = None
    correlation_id: str = "r3.5-workset"

    def __post_init__(self) -> None:
        if not isinstance(self.scope, KnowledgeScopeIdentity):
            raise R35Error("R3_5_SCOPE_MISMATCH", "WorkSet requires KnowledgeScopeIdentity")
        if not isinstance(self.anchor, Mapping):
            raise R35Error("R3_5_KNOWLEDGE_REF_MISSING", "WorkSet requires a source-backed R3.E1 anchor")
        for name in ("refs", "relation_types", "allowed_statuses"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be an array")
            object.__setattr__(self, name, tuple(str(item) for item in value))
        if not isinstance(self.exclude_digests, (list, tuple)):
            raise R35Error("R3_5_SCHEMA_INVALID", "exclude_digests must be an array")
        object.__setattr__(self, "exclude_digests", tuple(str(item) for item in self.exclude_digests))
        if not isinstance(self.max_hops, int) or isinstance(self.max_hops, bool) or self.max_hops < 0:
            raise R35Error("R3_5_WORKSET_BOUND_EXCEEDED", "max_hops must be non-negative")
        if not isinstance(self.max_items, int) or isinstance(self.max_items, bool) or not 1 <= self.max_items <= HARD_MAX_ITEMS:
            raise R35Error("R3_5_WORKSET_BOUND_EXCEEDED", f"max_items must be between 1 and {HARD_MAX_ITEMS}")
        if not isinstance(self.max_bytes, int) or isinstance(self.max_bytes, bool) or not 1 <= self.max_bytes <= HARD_MAX_BYTES:
            raise R35Error("R3_5_WORKSET_BOUND_EXCEEDED", f"max_bytes must be between 1 and {HARD_MAX_BYTES}")
        if not isinstance(self.semantic_batch_key, str) or not self.semantic_batch_key.strip():
            raise R35Error("R3_5_SCHEMA_INVALID", "semantic_batch_key is required")
        if not isinstance(self.context_policy_ref, str) or not self.context_policy_ref.strip():
            raise R35Error("R3_5_SCHEMA_INVALID", "context_policy_ref is required")
        if self.continuation_cursor is not None:
            object.__setattr__(self, "continuation_cursor", str(self.continuation_cursor))
        if self.session_ref is not None:
            object.__setattr__(self, "session_ref", str(self.session_ref))

    def to_retrieval_request(self) -> KnowledgeRetrievalRequest:
        statuses = self.allowed_statuses or tuple(sorted(DEFAULT_RETRIEVAL_STATUSES))
        return KnowledgeRetrievalRequest(
            scope_identity=self.scope,
            anchor=self.anchor,
            architecture_baseline_ref=ARCHITECTURE_BASELINE_REF,
            refs=self.refs,
            relation_types=self.relation_types,
            allowed_statuses=statuses,
            max_hops=self.max_hops,
            max_items=self.max_items,
            max_bytes=self.max_bytes,
            include_bounded_excerpts=False,
            session_ref=self.session_ref,
            correlation_id=self.correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "anchor": dict(self.anchor),
            "refs": list(self.refs),
            "relation_types": list(self.relation_types),
            "allowed_statuses": list(self.allowed_statuses),
            "max_hops": self.max_hops,
            "max_items": self.max_items,
            "max_bytes": self.max_bytes,
            "semantic_batch_key": self.semantic_batch_key,
            "context_policy_ref": self.context_policy_ref,
            "continuation_cursor": self.continuation_cursor,
            "exclude_digests": list(self.exclude_digests),
            "session_ref": self.session_ref,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class WorkSetResult:
    request: WorkSetRequest
    retrieval: KnowledgeRetrievalResult
    items: tuple[Mapping[str, Any], ...]
    included_digests: tuple[str, ...]
    excluded_refs: tuple[Mapping[str, Any], ...]
    unresolved_refs: tuple[str, ...]
    truncated: bool
    next_cursor: str | None
    workset_digest: str
    stale_or_conflicted_refs: tuple[str, ...] = ()
    retrieval_receipt_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "items": [dict(item) for item in self.items],
            "included_digests": list(self.included_digests),
            "excluded_refs": [dict(item) for item in self.excluded_refs],
            "unresolved_refs": list(self.unresolved_refs),
            "truncated": self.truncated,
            "next_cursor": self.next_cursor,
            "workset_digest": self.workset_digest,
            "stale_or_conflicted_refs": list(self.stale_or_conflicted_refs),
            "retrieval_receipt_ref": self.retrieval_receipt_ref,
            "retrieval": self.retrieval.to_dict(),
        }


def _items(result: KnowledgeRetrievalResult) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = []
    for fact in result.facts:
        values.append({"kind": "KNOWLEDGE_FACT", "id": fact.fact_id, "value": fact.to_dict()})
    for relation in result.relations:
        values.append({"kind": "KNOWLEDGE_RELATION", "id": relation.relation_id, "value": relation.to_dict()})
    return tuple(values)


def retrieve_workset(request: WorkSetRequest, retriever: KnowledgeRetrievalPort) -> WorkSetResult:
    if not isinstance(request, WorkSetRequest):
        raise R35Error("R3_5_SCHEMA_INVALID", "retrieve_workset requires WorkSetRequest")
    if retriever is None or not callable(getattr(retriever, "retrieve", None)):
        raise R35Error("R3_5_KNOWLEDGE_REF_MISSING", "R3.E1 retrieval seam is unavailable")
    retrieval = retriever.retrieve(request.to_retrieval_request())
    if not isinstance(retrieval, KnowledgeRetrievalResult):
        raise R35Error("R3_5_SCHEMA_INVALID", "R3.E1 retrieval seam returned an invalid result")
    if retrieval.scope_identity != request.scope:
        raise R35Error("R3_5_SCOPE_MISMATCH", "R3.E1 result scope differs from requested WorkSet")
    candidate_items = _items(retrieval)
    excluded = [dict(item) for item in retrieval.excluded_refs]
    items: list[Mapping[str, Any]] = []
    for item in candidate_items:
        digest = canonical_sha256(item)
        if digest in request.exclude_digests:
            excluded.append({"id": item.get("id"), "reason": "EXCLUDED_DIGEST", "digest": digest})
            continue
        items.append(item)
    items = tuple(items)
    included = tuple(canonical_sha256(item) for item in items)
    excluded = tuple(excluded)
    unresolved_values = [item.get("ref") or item.get("id") or item.get("relation_id") for item in excluded if item.get("reason") not in {"CONTEXT_BUDGET", "RETRIEVAL_BUDGET"}]
    unresolved = tuple(str(item) for item in unresolved_values if item is not None)
    stale_values = [
        str(item.get("ref") or item.get("id") or item.get("version_id"))
        for item in excluded
        if str(item.get("reason") or "").upper() in {"STALE", "CONFLICTED", "STALE_OR_UNKNOWN", "FRESHNESS_UNAVAILABLE"}
    ]
    stale_values.extend(item.conflict_id for item in retrieval.conflicts)
    stale_values.extend(item.target_version_id for item in retrieval.freshness if item.result != "FRESH")
    stale_or_conflicted = tuple(dict.fromkeys(stale_values))
    truncated = bool(retrieval.truncation and retrieval.truncation not in {"NONE", "NOT_TRUNCATED", "COMPLETE"})
    next_cursor = request.continuation_cursor
    if truncated:
        next_cursor = canonical_sha256({
            "semantic_batch_key": request.semantic_batch_key,
            "result_digest": retrieval.result_digest,
            "excluded": list(excluded),
        })
    body = {
        "request": request.to_dict(),
        "items": [dict(item) for item in items],
        "included_digests": list(included),
        "excluded_refs": list(excluded),
        "unresolved_refs": list(unresolved),
        "truncated": truncated,
        "next_cursor": next_cursor,
    }
    return WorkSetResult(
        request=request,
        retrieval=retrieval,
        items=items,
        included_digests=included,
        excluded_refs=excluded,
        unresolved_refs=unresolved,
        truncated=truncated,
        next_cursor=next_cursor,
        workset_digest=canonical_sha256(body),
        stale_or_conflicted_refs=stale_or_conflicted,
        retrieval_receipt_ref=str(
            retrieval.retrieval_receipt.get("source_ref_id")
            or retrieval.retrieval_receipt.get("ref_id")
            or "r3.e1:retrieval:" + retrieval.result_digest
        ),
    )


def checkpoint_workset(result: WorkSetResult, *, session_ref: str | None = None) -> dict[str, Any]:
    if session_ref is not None and not str(session_ref).strip():
        raise R35Error("R3_5_SCHEMA_INVALID", "session_ref must be non-empty when supplied")
    return {
        "workset_digest": result.workset_digest,
        "retrieval_cursor_ref": result.next_cursor,
        "semantic_batch_key": result.request.semantic_batch_key,
        "session_ref": session_ref or result.request.session_ref,
        "source_refs": [item.to_dict() for item in result.retrieval.source_refs],
        "knowledge_refs": [item.fact_id for item in result.retrieval.facts],
    }
