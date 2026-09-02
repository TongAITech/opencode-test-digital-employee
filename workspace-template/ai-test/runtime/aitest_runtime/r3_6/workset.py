from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import canonical_json, canonical_sha256

from .contracts import (
    InvestigationWorkSetReceipt,
    InvestigationWorkSetRequest,
    SOURCE_STATUSES,
    _reject_forbidden,
)
from .errors import R36Error


class TypedRetrievalProvider(Protocol):
    def retrieve(self, request: InvestigationWorkSetRequest) -> Iterable[Mapping[str, Any]]:
        ...


def _provider_items(provider: TypedRetrievalProvider | Callable[[InvestigationWorkSetRequest], Iterable[Mapping[str, Any]]], request: InvestigationWorkSetRequest) -> Iterable[Mapping[str, Any]]:
    if hasattr(provider, "retrieve"):
        return provider.retrieve(request)  # type: ignore[union-attr]
    if callable(provider):
        return provider(request)
    raise R36Error("R3_6_SOURCE_UNAVAILABLE", "typed retrieval provider is not callable")


def retrieve_workset(
    request: InvestigationWorkSetRequest,
    provider: TypedRetrievalProvider | Callable[[InvestigationWorkSetRequest], Iterable[Mapping[str, Any]]],
) -> InvestigationWorkSetReceipt:
    """Retrieve only typed, digest-addressed refs within the bounded WorkSet."""

    selected: list[dict[str, Any]] = []
    omitted: list[str] = []
    statuses: dict[str, str] = {}
    total_bytes = 0
    truncated = "NONE"
    for raw in _provider_items(provider, request):
        if not isinstance(raw, Mapping):
            raise R36Error("R3_6_SCHEMA_INVALID", "retrieval item must be a typed mapping")
        item = dict(raw)
        _reject_forbidden(item, "retrieval_item")
        ref_id = item.get("ref_id") or item.get("id")
        digest = item.get("digest") or item.get("content_digest") or item.get("source_digest")
        kind = item.get("kind") or item.get("source_kind")
        status = item.get("status", "COLLECTED")
        if not isinstance(ref_id, str) or not ref_id.strip() or not isinstance(digest, str) or not digest.strip():
            raise R36Error("R3_6_UPSTREAM_REF_MISSING", "retrieval item requires ref_id and digest")
        if not isinstance(kind, str) or not kind.strip():
            raise R36Error("R3_6_SCHEMA_INVALID", "retrieval item requires typed kind")
        if status not in SOURCE_STATUSES:
            raise R36Error("R3_6_SCHEMA_INVALID", f"invalid retrieval source status: {status}")
        statuses[ref_id] = status
        item["ref_id"] = ref_id
        item["kind"] = kind
        item["digest"] = digest
        encoded_size = len(canonical_json(item).encode("utf-8"))
        if status != "COLLECTED":
            omitted.append(ref_id)
            continue
        if len(selected) >= request.max_items:
            omitted.append(ref_id)
            truncated = "ITEMS"
            continue
        if total_bytes + encoded_size > request.max_bytes:
            omitted.append(ref_id)
            truncated = "BYTES"
            continue
        selected.append(item)
        total_bytes += encoded_size
    result_body = {
        "workset_id": request.workset_id,
        "selected_items": selected,
        "omitted_refs": omitted,
        "truncation": truncated,
        "source_statuses": statuses,
        "next_cursor": request.cursor,
    }
    result_digest = canonical_sha256(result_body)
    return InvestigationWorkSetReceipt(
        workset_id=request.workset_id,
        selected_items=tuple(selected),
        omitted_refs=tuple(omitted),
        truncation=truncated,
        source_statuses=statuses,
        next_cursor=request.cursor,
        result_digest=result_digest,
    )


def checkpoint_payload(
    request: InvestigationWorkSetRequest,
    receipt: InvestigationWorkSetReceipt,
) -> dict[str, Any]:
    if request.workset_id != receipt.workset_id:
        raise R36Error("R3_6_SCOPE_MISMATCH", "WorkSet request and receipt identity mismatch")
    return {
        "workset_digest": receipt.receipt_digest,
        "cursor": receipt.next_cursor,
        "omitted_refs": list(receipt.omitted_refs),
        "session_ref": request.session_ref,
    }
