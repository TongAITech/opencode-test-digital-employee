from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import canonical_json, canonical_sha256

from .contracts import (
    SOURCE_STATUSES,
    WorkSetReceipt,
    WorkSetRequest,
    _reject_forbidden,
)
from .errors import R37Error


class TypedRetrievalProvider(Protocol):
    def retrieve(self, request: WorkSetRequest) -> Iterable[Mapping[str, Any]]:
        ...


def _provider_items(
    provider: TypedRetrievalProvider | Callable[[WorkSetRequest], Iterable[Mapping[str, Any]]],
    request: WorkSetRequest,
) -> Iterable[Mapping[str, Any]]:
    try:
        if hasattr(provider, "retrieve"):
            return provider.retrieve(request)  # type: ignore[union-attr]
        if callable(provider):
            return provider(request)
    except Exception as exc:
        raise R37Error("R3_7_RUNTIME_SOURCE_UNAVAILABLE", "typed retrieval provider is unavailable") from exc
    raise R37Error("R3_7_RUNTIME_SOURCE_UNAVAILABLE", "typed retrieval provider is not callable")


def retrieve_workset(
    request: WorkSetRequest | Mapping[str, Any],
    provider: TypedRetrievalProvider | Callable[[WorkSetRequest], Iterable[Mapping[str, Any]]],
) -> WorkSetReceipt:
    if isinstance(request, Mapping):
        request = WorkSetRequest.from_dict(request)
    if not isinstance(request, WorkSetRequest):
        raise R37Error("R3_7_SCHEMA_INVALID", "workset request has invalid type")
    selected: list[dict[str, Any]] = []
    omitted: list[str] = []
    statuses: dict[str, str] = {}
    total_bytes = 0
    truncation = "NONE"
    try:
        items = _provider_items(provider, request)
        for raw in items:
            if not isinstance(raw, Mapping):
                raise R37Error("R3_7_SCHEMA_INVALID", "retrieval item must be a typed mapping")
            item = dict(raw)
            _reject_forbidden(item, "retrieval_item")
            ref_id = item.get("ref_id") or item.get("id")
            digest = item.get("digest") or item.get("content_digest") or item.get("source_digest")
            kind = item.get("kind") or item.get("source_kind")
            status = item.get("status", "COLLECTED")
            if not isinstance(ref_id, str) or not ref_id.strip() or not isinstance(digest, str) or not digest.strip():
                raise R37Error("R3_7_UPSTREAM_REF_MISSING", "retrieval item requires ref_id and digest")
            if not isinstance(kind, str) or not kind.strip():
                raise R37Error("R3_7_SCHEMA_INVALID", "retrieval item requires typed kind")
            if status not in SOURCE_STATUSES:
                raise R37Error("R3_7_SCHEMA_INVALID", f"invalid retrieval source status: {status}")
            item.update({"ref_id": ref_id, "kind": kind, "digest": digest, "status": status})
            statuses[ref_id] = status
            encoded_size = len(canonical_json(item).encode("utf-8"))
            if status != "COLLECTED":
                omitted.append(ref_id)
                continue
            if len(selected) >= request.max_items:
                omitted.append(ref_id)
                truncation = "ITEMS"
                continue
            if total_bytes + encoded_size > request.max_bytes:
                omitted.append(ref_id)
                truncation = "BYTES"
                continue
            selected.append(item)
            total_bytes += encoded_size
    except R37Error:
        raise
    except Exception as exc:
        raise R37Error("R3_7_RUNTIME_SOURCE_UNAVAILABLE", "typed retrieval provider failed") from exc
    body = {
        "workset_id": request.workset_id, "selected_items": selected, "omitted_refs": omitted,
        "truncation": truncation, "source_statuses": statuses, "next_cursor": request.cursor,
        "session_ref": request.session_ref, "context_usage_telemetry": "UNAVAILABLE",
    }
    return WorkSetReceipt(
        workset_id=request.workset_id, selected_items=tuple(selected), omitted_refs=tuple(omitted),
        truncation=truncation, source_statuses=statuses, next_cursor=request.cursor, session_ref=request.session_ref,
        context_usage_telemetry="UNAVAILABLE", result_digest=canonical_sha256(body),
    )
