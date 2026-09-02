from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeService, canonical_json, canonical_sha256
from aitest_runtime.durable_core.schema import connect

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    DEFAULT_RETRIEVAL_STATUSES,
    KnowledgeConflict,
    KnowledgeFact,
    KnowledgeFreshness,
    KnowledgeRelation,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
    R3E1Error,
)
from .projections import scope_rows


HARD_MAX_ITEMS = 24
HARD_MAX_BYTES = 12288
STATUS_RANK = {"USER_VERIFIED": 0, "RUNTIME_VERIFIED": 1, "SOURCE_VERIFIED": 2}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def anchor_digest_for(anchor: Mapping[str, Any]) -> str:
    value = dict(anchor)
    value.pop("anchor_digest", None)
    return canonical_sha256(value)


def build_r31_anchor(snapshot: Any, obligation: Any) -> dict[str, Any]:
    if getattr(snapshot, "snapshot_id", None) is None or getattr(obligation, "obligation_id", None) is None:
        raise R3E1Error("R3_E1_ANCHOR_DIGEST_MISMATCH", "R3.1 snapshot and obligation are required")
    provenance = [item.to_dict() for item in obligation.source_provenance]
    body = {
        "snapshot_id": snapshot.snapshot_id,
        "derivation_version_id": snapshot.derivation_version_id,
        "obligation_id": obligation.obligation_id,
        "source_bundle_digest": snapshot.identity.source_bundle_digest,
        "derivation_fingerprint": snapshot.identity.fingerprint,
        "source_provenance": provenance,
    }
    return {**body, "anchor_digest": anchor_digest_for(body)}


def _validate_anchor(anchor: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(anchor, "anchor")
    required = {
        "snapshot_id",
        "derivation_version_id",
        "obligation_id",
        "source_bundle_digest",
        "derivation_fingerprint",
        "source_provenance",
        "anchor_digest",
    }
    if set(value) != required:
        raise R3E1Error("R3_E1_ANCHOR_DIGEST_MISMATCH", "anchor contains unknown or missing fields")
    for key in ("snapshot_id", "derivation_version_id", "obligation_id", "source_bundle_digest", "derivation_fingerprint", "anchor_digest"):
        _text(value[key], f"anchor.{key}")
    if not isinstance(value["source_provenance"], (list, tuple)) or not value["source_provenance"]:
        raise R3E1Error("R3_E1_ANCHOR_DIGEST_MISMATCH", "anchor source provenance is required")
    if value["anchor_digest"] != anchor_digest_for(value):
        raise R3E1Error("R3_E1_ANCHOR_DIGEST_MISMATCH", "anchor digest does not match exact R3.1 identity/provenance")
    return value


@dataclass(frozen=True)
class KnowledgeRetrievalRequest:
    scope_identity: KnowledgeScopeIdentity
    anchor: Mapping[str, Any]
    architecture_baseline_ref: str = ARCHITECTURE_BASELINE_REF
    refs: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    allowed_statuses: tuple[str, ...] = ()
    freshness_policy_version: str = "r3.e1.freshness.v1"
    max_hops: int = 5
    max_items: int = HARD_MAX_ITEMS
    max_bytes: int = HARD_MAX_BYTES
    include_bounded_excerpts: bool = False
    session_ref: str | None = None
    correlation_id: str = "r3.e1-retrieval"
    allow_qualified_cross_scope: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "retrieval requires KnowledgeScopeIdentity")
        object.__setattr__(self, "architecture_baseline_ref", _text(self.architecture_baseline_ref, "architecture_baseline_ref"))
        if self.architecture_baseline_ref != ARCHITECTURE_BASELINE_REF:
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", f"retrieval must use ArchitectureBaseline {ARCHITECTURE_BASELINE_REF}")
        object.__setattr__(self, "anchor", _validate_anchor(self.anchor))
        for name, value in (("refs", self.refs), ("relation_types", self.relation_types), ("allowed_statuses", self.allowed_statuses)):
            if not isinstance(value, (list, tuple)):
                raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an array")
            object.__setattr__(self, name, tuple(_text(item, f"{name}[]") for item in value))
        statuses = tuple(self.allowed_statuses) or tuple(sorted(DEFAULT_RETRIEVAL_STATUSES))
        if any(status not in DEFAULT_RETRIEVAL_STATUSES for status in statuses):
            raise R3E1Error("R3_E1_RETRIEVAL_STATUS_INVALID", "testing retrieval cannot widen into stale/conflicted/superseded/retired data")
        object.__setattr__(self, "allowed_statuses", statuses)
        object.__setattr__(self, "freshness_policy_version", _text(self.freshness_policy_version, "freshness_policy_version"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.session_ref is not None:
            object.__setattr__(self, "session_ref", _text(self.session_ref, "session_ref"))
        if not isinstance(self.max_hops, int) or isinstance(self.max_hops, bool) or self.max_hops < 0:
            raise R3E1Error("R3_E1_RETRIEVAL_BUDGET_EXCEEDED", "max_hops must be non-negative")
        if not isinstance(self.max_items, int) or isinstance(self.max_items, bool) or self.max_items < 1 or self.max_items > HARD_MAX_ITEMS:
            raise R3E1Error("R3_E1_RETRIEVAL_BUDGET_EXCEEDED", f"max_items must be between 1 and {HARD_MAX_ITEMS}")
        if not isinstance(self.max_bytes, int) or isinstance(self.max_bytes, bool) or self.max_bytes < 1 or self.max_bytes > HARD_MAX_BYTES:
            raise R3E1Error("R3_E1_RETRIEVAL_BUDGET_EXCEEDED", f"max_bytes must be between 1 and {HARD_MAX_BYTES}")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeRetrievalRequest":
        raw = _mapping(value, "retrieval_request")
        return cls(
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            anchor=raw["anchor"],
            architecture_baseline_ref=raw.get("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF),
            refs=tuple(raw.get("refs") or ()),
            relation_types=tuple(raw.get("relation_types") or ()),
            allowed_statuses=tuple(raw.get("allowed_statuses") or ()),
            freshness_policy_version=raw.get("freshness_policy_version", "r3.e1.freshness.v1"),
            max_hops=raw.get("max_hops", 5),
            max_items=raw.get("max_items", HARD_MAX_ITEMS),
            max_bytes=raw.get("max_bytes", HARD_MAX_BYTES),
            include_bounded_excerpts=bool(raw.get("include_bounded_excerpts", False)),
            session_ref=raw.get("session_ref"),
            correlation_id=raw.get("correlation_id", "r3.e1-retrieval"),
            allow_qualified_cross_scope=bool(raw.get("allow_qualified_cross_scope", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_identity": self.scope_identity.to_dict(),
            "anchor": dict(self.anchor),
            "architecture_baseline_ref": self.architecture_baseline_ref,
            "refs": list(self.refs),
            "relation_types": list(self.relation_types),
            "allowed_statuses": list(self.allowed_statuses),
            "freshness_policy_version": self.freshness_policy_version,
            "max_hops": self.max_hops,
            "max_items": self.max_items,
            "max_bytes": self.max_bytes,
            "include_bounded_excerpts": self.include_bounded_excerpts,
            "session_ref": self.session_ref,
            "correlation_id": self.correlation_id,
            "allow_qualified_cross_scope": self.allow_qualified_cross_scope,
        }


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    scope_identity: KnowledgeScopeIdentity
    anchor_digest: str
    facts: tuple[KnowledgeFact, ...]
    versions: tuple[KnowledgeVersion, ...]
    relations: tuple[KnowledgeRelation, ...]
    source_refs: tuple[KnowledgeSourceRef, ...]
    freshness: tuple[KnowledgeFreshness, ...]
    conflicts: tuple[KnowledgeConflict, ...]
    excluded_refs: tuple[Mapping[str, Any], ...]
    bounded_excerpts: tuple[Mapping[str, Any], ...]
    truncation: str
    retrieval_receipt: Mapping[str, Any]
    result_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "result requires KnowledgeScopeIdentity")
        object.__setattr__(self, "excluded_refs", tuple(dict(item) for item in self.excluded_refs))
        object.__setattr__(self, "bounded_excerpts", tuple(dict(item) for item in self.bounded_excerpts))
        object.__setattr__(self, "retrieval_receipt", dict(self.retrieval_receipt))

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "scope_identity": self.scope_identity.to_dict(),
            "anchor_digest": self.anchor_digest,
            "facts": [item.to_dict() for item in self.facts],
            "versions": [item.to_dict() for item in self.versions],
            "relations": [item.to_dict() for item in self.relations],
            "source_refs": [item.to_dict() for item in self.source_refs],
            "freshness": [item.to_dict() for item in self.freshness],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "excluded_refs": list(self.excluded_refs),
            "bounded_excerpts": list(self.bounded_excerpts),
            "truncation": self.truncation,
            "retrieval_receipt": dict(self.retrieval_receipt),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.semantic_dict(), "result_digest": self.result_digest}


@dataclass(frozen=True)
class _Candidate:
    depth: int
    fact: KnowledgeFact
    version: KnowledgeVersion


class KnowledgeRetrievalAdapter:
    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        self._runtime = runtime_service

    @staticmethod
    def _rows(conn: Any, request: KnowledgeRetrievalRequest, table: str, *, all_scopes: bool = False) -> list[dict[str, Any]]:
        if all_scopes:
            return [json.loads(row["state_json"]) for row in conn.execute(f"SELECT state_json FROM {table} ORDER BY state_json")]
        return [
            json.loads(row["state_json"])
            for row in conn.execute(f"SELECT state_json FROM {table} WHERE scope_key=? ORDER BY state_json", (request.scope_identity.key,))
        ]

    @staticmethod
    def _matches_refs(fact: KnowledgeFact, version: KnowledgeVersion, refs: set[str], anchor: Mapping[str, Any]) -> bool:
        if not refs:
            return True
        known = {fact.fact_id, version.version_id, *version.source_ref_ids, *fact.anchor_refs}
        known.update({anchor["snapshot_id"], anchor["derivation_version_id"], anchor["obligation_id"], anchor["anchor_digest"]})
        return bool(known & refs)

    @staticmethod
    def _endpoint_fact_id(endpoint: Any) -> str:
        return endpoint.endpoint_id

    def retrieve(self, request: KnowledgeRetrievalRequest | Mapping[str, Any]) -> KnowledgeRetrievalResult:
        if isinstance(request, Mapping):
            request = KnowledgeRetrievalRequest.from_dict(request)
        if not isinstance(request, KnowledgeRetrievalRequest):
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "retrieval request has invalid type")
        conn = connect(self._runtime.db_path)
        try:
            return self._retrieve(conn, request)
        finally:
            conn.close()

    def _retrieve(self, conn: Any, request: KnowledgeRetrievalRequest) -> KnowledgeRetrievalResult:
        anchor = request.anchor
        all_scopes = request.allow_qualified_cross_scope
        fact_rows = self._rows(conn, request, "r3e1_facts", all_scopes=all_scopes)
        version_rows = self._rows(conn, request, "r3e1_versions", all_scopes=all_scopes)
        source_rows = self._rows(conn, request, "r3e1_source_refs", all_scopes=all_scopes)
        freshness_rows = self._rows(conn, request, "r3e1_freshness", all_scopes=all_scopes)
        conflict_rows = self._rows(conn, request, "r3e1_conflicts", all_scopes=all_scopes)
        relation_rows = self._rows(conn, request, "r3e1_relations", all_scopes=False)
        facts = [KnowledgeFact.from_dict(item) for item in fact_rows]
        versions = [KnowledgeVersion.from_dict(item) for item in version_rows]
        sources = [KnowledgeSourceRef.from_dict(item) for item in source_rows]
        freshness = [KnowledgeFreshness.from_dict(item) for item in freshness_rows]
        conflicts = [KnowledgeConflict.from_dict(item) for item in conflict_rows]
        relations = [KnowledgeRelation.from_dict(item) for item in relation_rows]
        fact_by_id = {item.fact_id: item for item in facts}
        version_by_id = {item.version_id: item for item in versions}
        source_by_id = {item.source_ref_id: item for item in sources}
        freshness_by_id = {item.freshness_id: item for item in freshness}
        conflicts_by_fact: dict[str, list[KnowledgeConflict]] = {}
        for item in conflicts:
            conflicts_by_fact.setdefault(item.fact_id, []).append(item)
        excluded: list[dict[str, Any]] = []

        def exclude(identity: str, reason: str, **extra: Any) -> None:
            excluded.append({"ref": identity, "reason": reason, **extra})

        def eligible(fact: KnowledgeFact, version: KnowledgeVersion) -> bool:
            if fact.scope_identity != request.scope_identity and not request.allow_qualified_cross_scope:
                exclude(fact.fact_id, "SCOPE_MISMATCH")
                return False
            if version.status not in request.allowed_statuses:
                exclude(version.version_id, "STATUS_INELIGIBLE", status=version.status)
                return False
            if not self._matches_refs(fact, version, set(request.refs), anchor):
                exclude(fact.fact_id, "REF_NOT_REQUESTED")
                return False
            if any(source_by_id.get(source_id) is None for source_id in version.source_ref_ids):
                exclude(version.version_id, "SOURCE_UNAVAILABLE")
                return False
            if any(source_by_id[source_id].scope_identity != version.scope_identity for source_id in version.source_ref_ids):
                exclude(version.version_id, "SCOPE_MISMATCH")
                return False
            if any(item.status == "OPEN" for item in conflicts_by_fact.get(fact.fact_id, [])):
                exclude(fact.fact_id, "CONFLICT")
                return False
            if version.freshness_id is None or freshness_by_id.get(version.freshness_id) is None:
                exclude(version.version_id, "FRESHNESS_UNAVAILABLE")
                return False
            fresh = freshness_by_id[version.freshness_id]
            if fresh.policy_version != request.freshness_policy_version or fresh.result != "FRESH":
                exclude(version.version_id, "STALE_OR_UNKNOWN")
                return False
            return True

        current_versions = {
            fact.fact_id: version_by_id.get(fact.current_version_id)
            for fact in facts
        }
        queue: deque[tuple[KnowledgeFact, KnowledgeVersion, int]] = deque()
        page_candidates: list[_Candidate] = []
        anchor_ids = {anchor["snapshot_id"], anchor["derivation_version_id"], anchor["obligation_id"], anchor["anchor_digest"]}
        for fact in sorted(facts, key=lambda item: item.fact_id):
            version = current_versions.get(fact.fact_id)
            endpoint_type = (fact.metadata or {}).get("endpoint_type")
            if endpoint_type != "FRONTEND_PAGE" or not (set(fact.anchor_refs) & anchor_ids):
                continue
            if version is not None and eligible(fact, version):
                page_candidates.append(_Candidate(0, fact, version))
        if not page_candidates:
            exclude(anchor["obligation_id"], "ANCHOR_PAGE_NOT_FOUND")

        relation_by_from: dict[str, list[KnowledgeRelation]] = {}
        for relation in relations:
            relation_by_from.setdefault(relation.from_ref.endpoint_id, []).append(relation)
        for value in relation_by_from.values():
            value.sort(key=lambda item: (item.relation_id, item.relation_version))

        selected: dict[str, _Candidate] = {}
        selected_relations: dict[str, tuple[KnowledgeRelation, int]] = {}
        for candidate in page_candidates:
            selected[candidate.fact.fact_id] = candidate
            queue.append((candidate.fact, candidate.version, 0))

        while queue:
            current_fact, current_version, depth = queue.popleft()
            if depth >= request.max_hops:
                continue
            for relation in relation_by_from.get(current_fact.fact_id, []):
                if request.relation_types and relation.semantic not in request.relation_types:
                    exclude(relation.relation_id, "RELATION_TYPE_NOT_REQUESTED")
                    continue
                if relation.status not in request.allowed_statuses:
                    exclude(relation.relation_id, "STATUS_INELIGIBLE", status=relation.status)
                    continue
                if relation.from_ref.version_id != current_version.version_id:
                    exclude(relation.relation_id, "ENDPOINT_VERSION_MISMATCH")
                    continue
                cross_scope = relation.from_ref.scope_identity != relation.to_ref.scope_identity
                if cross_scope and (not request.allow_qualified_cross_scope or not relation.cross_scope_provenance):
                    exclude(relation.relation_id, "CROSS_SCOPE_PROVENANCE_REQUIRED")
                    continue
                target_fact = fact_by_id.get(self._endpoint_fact_id(relation.to_ref))
                target_version = version_by_id.get(relation.to_ref.version_id)
                if target_fact is None or target_version is None:
                    exclude(relation.relation_id, "ENDPOINT_UNAVAILABLE")
                    continue
                if target_version.fact_id != target_fact.fact_id or target_version.scope_identity != relation.to_ref.scope_identity:
                    exclude(relation.relation_id, "RELATION_ENDPOINT_INVALID")
                    continue
                if not eligible(target_fact, target_version):
                    exclude(relation.relation_id, "TARGET_INELIGIBLE")
                    continue
                target = _Candidate(depth + 1, target_fact, target_version)
                previous = selected.get(target_fact.fact_id)
                if previous is None or target.depth < previous.depth:
                    selected[target_fact.fact_id] = target
                    queue.append((target.fact, target.version, target.depth))
                selected_relations[relation.relation_id] = (relation, depth + 1)

        ordered_candidates = sorted(selected.values(), key=lambda item: (
            item.depth,
            STATUS_RANK.get(item.version.status, 99),
            item.version.confidence,
            item.version.source_ref_ids[0] if item.version.source_ref_ids else "",
            item.fact.fact_id,
        ))
        ordered_relations = sorted(selected_relations.values(), key=lambda item: (item[1], item[0].relation_id))
        chosen_facts: list[KnowledgeFact] = []
        chosen_versions: list[KnowledgeVersion] = []
        chosen_relations: list[KnowledgeRelation] = []
        chosen_ids: set[str] = set()
        budget_bytes = 0
        truncation = "NONE"
        for candidate in ordered_candidates:
            item_bytes = len(canonical_json({"fact": candidate.fact.to_dict(), "version": candidate.version.to_dict()}).encode("utf-8"))
            if len(chosen_ids) >= request.max_items or budget_bytes + item_bytes > request.max_bytes:
                exclude(candidate.fact.fact_id, "RETRIEVAL_BUDGET")
                truncation = "BUDGET"
                continue
            chosen_facts.append(candidate.fact)
            chosen_versions.append(candidate.version)
            chosen_ids.add(candidate.fact.fact_id)
            budget_bytes += item_bytes
        for relation, depth in ordered_relations:
            item_bytes = len(canonical_json({"relation": relation.to_dict(), "depth": depth}).encode("utf-8"))
            if len(chosen_ids) >= request.max_items or budget_bytes + item_bytes > request.max_bytes:
                exclude(relation.relation_id, "RETRIEVAL_BUDGET")
                truncation = "BUDGET"
                continue
            chosen_relations.append(relation)
            chosen_ids.add(f"relation:{relation.relation_id}")
            budget_bytes += item_bytes

        chosen_version_ids = {item.version_id for item in chosen_versions}
        chosen_source_ids = {
            source_id
            for item in chosen_versions
            for source_id in item.source_ref_ids
        }
        chosen_source_ids |= {
            source_id
            for item in chosen_relations
            for source_id in item.source_ref_ids
        }
        chosen_sources = tuple(source_by_id[item] for item in sorted(chosen_source_ids) if item in source_by_id)
        chosen_freshness = tuple(
            item for item in freshness if item.freshness_id in {version.freshness_id for version in chosen_versions if version.freshness_id}
        )
        chosen_conflicts = tuple(
            item for item in conflicts if item.fact_id in {fact.fact_id for fact in chosen_facts} and item.status == "OPEN"
        )
        excerpts: list[Mapping[str, Any]] = []
        if request.include_bounded_excerpts:
            for source in chosen_sources:
                excerpts.append({
                    "source_ref_id": source.source_ref_id,
                    "locator": source.locator,
                    "source_revision": source.source_revision,
                    "source_digest": source.source_digest,
                    "excerpt_digest": canonical_sha256({"source_ref_id": source.source_ref_id, "bounded": True}),
                    "bytes": 0,
                    "content": None,
                })
        receipt = {
            "scope_identity": request.scope_identity.to_dict(),
            "architecture_baseline_ref": request.architecture_baseline_ref,
            "anchor_digest": anchor["anchor_digest"],
            "request_digest": canonical_sha256(request.to_dict()),
            "correlation_id": request.correlation_id,
            "session_ref": request.session_ref,
            "max_hops": request.max_hops,
            "max_items": request.max_items,
            "max_bytes": request.max_bytes,
            "selected_item_count": len(chosen_facts) + len(chosen_relations),
            "selected_bytes": budget_bytes,
            "omission_count": len(excluded),
        }
        semantic = {
            "scope_identity": request.scope_identity.to_dict(),
            "anchor_digest": anchor["anchor_digest"],
            "facts": [item.to_dict() for item in chosen_facts],
            "versions": [item.to_dict() for item in chosen_versions],
            "relations": [item.to_dict() for item in chosen_relations],
            "source_refs": [item.to_dict() for item in chosen_sources],
            "freshness": [item.to_dict() for item in chosen_freshness],
            "conflicts": [item.to_dict() for item in chosen_conflicts],
            "excluded_refs": excluded,
            "bounded_excerpts": excerpts,
            "truncation": truncation,
            "retrieval_receipt": receipt,
        }
        return KnowledgeRetrievalResult(
            scope_identity=request.scope_identity,
            anchor_digest=anchor["anchor_digest"],
            facts=tuple(chosen_facts),
            versions=tuple(chosen_versions),
            relations=tuple(chosen_relations),
            source_refs=chosen_sources,
            freshness=chosen_freshness,
            conflicts=chosen_conflicts,
            excluded_refs=tuple(excluded),
            bounded_excerpts=tuple(excerpts),
            truncation=truncation,
            retrieval_receipt=receipt,
            result_digest=canonical_sha256(semantic),
        )

    @staticmethod
    def to_knowledge_set(result: KnowledgeRetrievalResult) -> Any:
        from aitest_runtime.execution_context import KnowledgeRecordInput, KnowledgeSetInput

        relation_by_fact: dict[str, list[dict[str, Any]]] = {}
        for relation in result.relations:
            relation_by_fact.setdefault(relation.from_ref.endpoint_id, []).append(relation.to_dict())
        records = []
        omissions: list[dict[str, Any]] = []
        for fact, version in zip(result.facts, result.versions):
            content = {
                "fact": fact.to_dict(),
                "version": version.to_dict(),
                "relations": relation_by_fact.get(fact.fact_id, []),
            }
            record = KnowledgeRecordInput(
                knowledge_id=fact.fact_id,
                version=version.version_number,
                status="VERIFIED",
                scope={
                    **result.scope_identity.to_dict(),
                    "architecture_baseline_ref": result.retrieval_receipt.get("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF),
                },
                content=content,
                metadata={
                    "canonical_status": version.status,
                    "knowledge_version_id": version.version_id,
                    "knowledge_scope_identity": result.scope_identity.to_dict(),
                    "architecture_baseline_ref": result.retrieval_receipt.get("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF),
                    "source_ref_ids": list(version.source_ref_ids),
                    "retrieval_receipt": dict(result.retrieval_receipt),
                },
                confidence=version.confidence,
                subject=fact.subject,
                predicate=fact.predicate,
                source_type="R3_E1",
                source_ref=version.source_ref_ids[0] if version.source_ref_ids else None,
            )
            size = len(canonical_json(record.to_dict()).encode("utf-8"))
            if len(records) >= HARD_MAX_ITEMS or sum(len(canonical_json(item.to_dict()).encode("utf-8")) for item in records) + size > HARD_MAX_BYTES:
                omissions.append({"fact_id": fact.fact_id, "reason": "CONTEXT_BUDGET"})
                continue
            records.append(record)
        return KnowledgeSetInput(records), omissions
