from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    CONFLICT_RECORDED,
    FRESHNESS_RECORDED,
    LIFECYCLE_TRANSITIONED,
    RELATION_RECORDED,
    R3E1Error,
    R3E1State,
    VERSION_REGISTERED,
    KnowledgeConflict,
    KnowledgeFact,
    KnowledgeFreshness,
    KnowledgeRelation,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
    _proof_for_status,
    validate_transition,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R3E1Error("R3_E1_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    expected_digest = canonical_sha256({key: value for key, value in payload.items() if key != "payload_digest"})
    if payload.get("payload_digest") != expected_digest:
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "event payload digest does not match its immutable payload")
    return payload


def _origin(payload: Mapping[str, Any], mission_id: str) -> Mapping[str, Any]:
    value = payload.get("origin_lineage")
    if not isinstance(value, Mapping) or value.get("mission_id") != mission_id:
        raise R3E1Error("R3_E1_SCOPE_MISMATCH", "origin_lineage must identify the command Mission")
    return dict(value)


def _scope(payload: Mapping[str, Any]) -> KnowledgeScopeIdentity:
    return KnowledgeScopeIdentity.from_dict(payload["knowledge_scope_identity"])


def _append_unique(values: tuple[Any, ...], value: Any, identity: str, error_code: str = "R3_E1_VERSION_IMMUTABLE") -> tuple[Any, ...]:
    existing = {getattr(item, identity) for item in values}
    current = getattr(value, identity)
    if current in existing:
        raise R3E1Error(error_code, f"{identity} is not immutable: {current}")
    return values + (value,)


def _validate_source_scope(scope: KnowledgeScopeIdentity, source_refs: tuple[KnowledgeSourceRef, ...]) -> None:
    if any(item.scope_identity != scope for item in source_refs):
        raise R3E1Error("R3_E1_SCOPE_MISMATCH", "source ref scope does not match KnowledgeScopeIdentity")


def _merge_sources(
    existing: tuple[KnowledgeSourceRef, ...], incoming: tuple[KnowledgeSourceRef, ...]
) -> tuple[KnowledgeSourceRef, ...]:
    by_id = {item.source_ref_id: item for item in existing}
    for item in incoming:
        prior = by_id.get(item.source_ref_id)
        if prior is not None and prior.to_dict() != item.to_dict():
            raise R3E1Error("R3_E1_SOURCE_REF_INVALID", f"source ref identity conflicts: {item.source_ref_id}")
        by_id[item.source_ref_id] = item
    ordered: list[KnowledgeSourceRef] = []
    seen: set[str] = set()
    for item in (*existing, *incoming):
        if item.source_ref_id not in seen:
            ordered.append(by_id[item.source_ref_id])
            seen.add(item.source_ref_id)
    return tuple(ordered)


def initial_state(mission_id: str) -> R3E1State:
    return R3E1State(mission_id)


class R3E1ReducerContribution:
    def reduce(self, state: R3E1State, event: EventEnvelope, core_state: RuntimeState) -> R3E1State:
        if not isinstance(state, R3E1State):
            raise R3E1Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E1 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R3E1Error("R3_E1_EVENT_INVALID", "R3.E1 Event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R3E1Error("R3_E1_EVENT_INVALID", "R3.E1 Event does not share the Core sequence")

        if event.event_type == VERSION_REGISTERED:
            payload = _payload(event, {
                "knowledge_scope_identity", "fact", "version", "source_refs",
                "origin_lineage", "payload_digest",
            })
            scope = _scope(payload)
            _origin(payload, event.mission_id)
            fact = KnowledgeFact.from_dict(payload["fact"])
            version = KnowledgeVersion.from_dict(payload["version"])
            sources = tuple(KnowledgeSourceRef.from_dict(item) for item in payload["source_refs"])
            if fact.scope_identity != scope or version.scope_identity != scope:
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", "fact/version scope differs from event scope")
            if fact.fact_id != version.fact_id or fact.current_version_id != version.version_id:
                raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "fact current version does not match registered version")
            if tuple(item.source_ref_id for item in sources) != version.source_ref_ids:
                raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "version source refs do not match event source refs")
            _validate_source_scope(scope, sources)
            existing_fact = state.fact(fact.fact_id)
            if existing_fact is not None:
                immutable_fact = fact.to_dict()
                immutable_fact.pop("current_version_id", None)
                prior_fact = existing_fact.to_dict()
                prior_fact.pop("current_version_id", None)
                if canonical_sha256(immutable_fact) != canonical_sha256(prior_fact):
                    raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "fact identity conflicts across Knowledge versions")
                prior_version = state.version(existing_fact.current_version_id)
                if prior_version is not None and version.version_number <= prior_version.version_number:
                    raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "Knowledge version number must increase monotonically")
                facts = tuple(
                    replace(item, current_version_id=fact.current_version_id)
                    if item.fact_id == fact.fact_id else item
                    for item in state.facts
                )
            else:
                facts = state.facts + (fact,)
            return replace(
                state,
                facts=facts,
                versions=_append_unique(state.versions, version, "version_id"),
                source_refs=_merge_sources(state.source_refs, sources),
            )

        if event.event_type == RELATION_RECORDED:
            payload = _payload(event, {
                "knowledge_scope_identity", "relation", "source_refs",
                "origin_lineage", "payload_digest",
            })
            scope = _scope(payload)
            _origin(payload, event.mission_id)
            relation = KnowledgeRelation.from_dict(payload["relation"])
            sources = tuple(KnowledgeSourceRef.from_dict(item) for item in payload["source_refs"])
            if relation.scope_identity != scope:
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", "relation scope differs from event scope")
            if tuple(item.source_ref_id for item in sources) != tuple(
                item for item in relation.source_ref_ids if item in {source.source_ref_id for source in sources}
            ) and sources:
                source_ids = {item.source_ref_id for item in sources}
                if not set(relation.source_ref_ids).issubset(source_ids | {item.source_ref_id for item in state.source_refs}):
                    raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "relation source refs are unresolved in event/state")
            _validate_source_scope(scope, sources)
            return replace(
                state,
                relations=_append_unique(state.relations, relation, "relation_id"),
                source_refs=state.source_refs + tuple(
                    source for source in sources if source.source_ref_id not in {item.source_ref_id for item in state.source_refs}
                ),
            )

        if event.event_type == FRESHNESS_RECORDED:
            payload = _payload(event, {
                "knowledge_scope_identity", "freshness", "source_refs",
                "origin_lineage", "payload_digest",
            })
            scope = _scope(payload)
            _origin(payload, event.mission_id)
            freshness = KnowledgeFreshness.from_dict(payload["freshness"])
            sources = tuple(KnowledgeSourceRef.from_dict(item) for item in payload["source_refs"])
            if freshness.scope_identity != scope:
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", "freshness scope differs from event scope")
            _validate_source_scope(scope, sources)
            return replace(
                state,
                freshness=_append_unique(state.freshness, freshness, "freshness_id"),
                source_refs=state.source_refs + tuple(
                    source for source in sources if source.source_ref_id not in {item.source_ref_id for item in state.source_refs}
                ),
            )

        if event.event_type == CONFLICT_RECORDED:
            payload = _payload(event, {
                "knowledge_scope_identity", "conflict", "source_refs",
                "origin_lineage", "payload_digest",
            })
            scope = _scope(payload)
            _origin(payload, event.mission_id)
            conflict = KnowledgeConflict.from_dict(payload["conflict"])
            sources = tuple(KnowledgeSourceRef.from_dict(item) for item in payload["source_refs"])
            if conflict.scope_identity != scope:
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", "conflict scope differs from event scope")
            _validate_source_scope(scope, sources)
            return replace(
                state,
                conflicts=_append_unique(state.conflicts, conflict, "conflict_id"),
                source_refs=state.source_refs + tuple(
                    source for source in sources if source.source_ref_id not in {item.source_ref_id for item in state.source_refs}
                ),
            )

        if event.event_type == LIFECYCLE_TRANSITIONED:
            payload = _payload(event, {
                "knowledge_scope_identity", "version_id", "from_status", "to_status",
                "proof", "source_refs", "origin_lineage", "payload_digest",
            })
            scope = _scope(payload)
            _origin(payload, event.mission_id)
            validate_transition(payload["from_status"], payload["to_status"])
            source_refs = tuple(KnowledgeSourceRef.from_dict(item) for item in payload["source_refs"])
            _validate_source_scope(scope, source_refs)
            lifecycle = {
                "version_id": payload["version_id"],
                "scope_identity": scope.to_dict(),
                "from_status": payload["from_status"],
                "to_status": payload["to_status"],
                "proof": dict(payload["proof"]),
                "source_ref_ids": [item.source_ref_id for item in source_refs],
                "origin_lineage": dict(payload["origin_lineage"]),
                "event_seq": event.seq,
            }
            existing = state.version(payload["version_id"])
            versions = state.versions
            if existing is not None:
                if existing.scope_identity != scope:
                    raise R3E1Error("R3_E1_SCOPE_MISMATCH", "lifecycle version scope mismatch")
                if existing.status != payload["from_status"]:
                    raise R3E1Error("R3_E1_STATUS_TRANSITION_INVALID", "lifecycle from_status does not match replay state")
                _proof_for_status(payload["to_status"], existing.source_ref_ids, payload["proof"])
                updated = replace(
                    existing,
                    status=payload["to_status"],
                    verification_proof=dict(payload["proof"]),
                )
                versions = tuple(updated if item.version_id == updated.version_id else item for item in versions)
            return replace(
                state,
                versions=versions,
                source_refs=state.source_refs + tuple(
                    source for source in source_refs if source.source_ref_id not in {item.source_ref_id for item in state.source_refs}
                ),
                lifecycle_events=state.lifecycle_events + (lifecycle,),
            )

        raise R3E1Error("R3_E1_EVENT_NOT_OWNED", f"unsupported R3.E1 event: {event.event_type}")


class R3E1StateContribution:
    def initial_state(self, mission_id: str) -> R3E1State:
        return initial_state(mission_id)

    def encode(self, state: R3E1State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: Mapping[str, Any]) -> R3E1State:
        return R3E1State.from_dict(value)

    def hash(self, state: R3E1State) -> str:
        return canonical_sha256(self.encode(state))
