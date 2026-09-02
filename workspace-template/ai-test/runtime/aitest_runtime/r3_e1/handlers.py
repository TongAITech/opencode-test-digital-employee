from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeError, canonical_sha256

from .contracts import (
    CONFLICT_RECORDED,
    FRESHNESS_RECORDED,
    LIFECYCLE_TRANSITIONED,
    RECORD_CONFLICT,
    RECORD_FRESHNESS,
    RECORD_RELATION,
    REGISTER_VERSION,
    RELATION_RECORDED,
    R3E1Error,
    TRANSITION_LIFECYCLE,
    VERSION_REGISTERED,
    KnowledgeConflict,
    KnowledgeFact,
    KnowledgeFreshness,
    KnowledgeRelation,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
    R3E1State,
    _proof_for_status,
    validate_transition,
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _scope(value: Any) -> KnowledgeScopeIdentity:
    return KnowledgeScopeIdentity.from_dict(value)


def _origin(payload: Mapping[str, Any], mission_id: str) -> dict[str, Any]:
    origin = _mapping(payload.get("origin_lineage"), "origin_lineage")
    if origin.get("mission_id") != mission_id:
        raise R3E1Error("R3_E1_SCOPE_MISMATCH", "origin_lineage.mission_id must match command mission_id")
    for key in ("task_id", "session_id", "plan_revision_id"):
        if key in origin and origin[key] is not None:
            _text(origin[key], f"origin_lineage.{key}")
    return origin


def _sources(payload: Mapping[str, Any], scope: KnowledgeScopeIdentity) -> tuple[KnowledgeSourceRef, ...]:
    raw = payload.get("source_refs")
    if not isinstance(raw, (list, tuple)):
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "source_refs must be an array")
    sources = tuple(KnowledgeSourceRef.from_dict(item) for item in raw)
    if any(item.scope_identity != scope for item in sources):
        raise R3E1Error("R3_E1_SCOPE_MISMATCH", "source ref scope does not match event scope")
    if len({item.source_ref_id for item in sources}) != len(sources):
        raise R3E1Error("R3_E1_SOURCE_REF_INVALID", "source refs must have unique identities")
    return sources


def _digest(payload: Mapping[str, Any]) -> str:
    value = payload.get("payload_digest")
    expected = canonical_sha256({key: item for key, item in payload.items() if key != "payload_digest"})
    if value != expected:
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "command payload digest does not match its immutable payload")
    return expected


def _pending(event_type: str, entity_type: str, entity_id: str, payload: Mapping[str, Any], session_id: str | None) -> list[PendingEvent]:
    return [PendingEvent(event_type, entity_type, entity_id, dict(payload), session_id=session_id)]


class R3E1CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        if not isinstance(composed, ComposedRuntimeState):
            raise R3E1Error("EXTENSION_SCHEMA_MISMATCH", "R3.E1 requires composed runtime state")
        if composed.core_state.mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
        payload = _mapping(command.payload, "command.payload")
        if command.type == REGISTER_VERSION:
            return self._register_version(command, composed, payload)
        if command.type == RECORD_RELATION:
            return self._record_relation(command, composed, payload)
        if command.type == RECORD_FRESHNESS:
            return self._record_freshness(command, composed, payload)
        if command.type == RECORD_CONFLICT:
            return self._record_conflict(command, composed, payload)
        if command.type == TRANSITION_LIFECYCLE:
            return self._transition(command, composed, payload)
        raise R3E1Error("R3_E1_COMMAND_NOT_OWNED", f"unsupported R3.E1 command: {command.type}")

    def _base(self, command: Any, payload: Mapping[str, Any], scope: KnowledgeScopeIdentity) -> dict[str, Any]:
        _origin(payload, command.mission_id)
        if command.session_id is not None:
            origin = dict(payload["origin_lineage"])
            if origin.get("session_id") not in (None, command.session_id):
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", "origin session differs from R1 command session")
        base = dict(payload)
        base["knowledge_scope_identity"] = scope.to_dict()
        _digest(base)
        return base

    def _register_version(self, command: Any, composed: ComposedRuntimeState, payload: dict[str, Any]) -> list[PendingEvent]:
        fact = KnowledgeFact.from_dict(payload.get("fact") or {})
        version = KnowledgeVersion.from_dict(payload.get("version") or {})
        scope = fact.scope_identity
        if version.scope_identity != scope:
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "fact and version scope mismatch")
        if fact.fact_id != version.fact_id or fact.current_version_id != version.version_id:
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "fact/version identity mismatch")
        source_refs = _sources(payload, scope)
        if tuple(item.source_ref_id for item in source_refs) != version.source_ref_ids:
            raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "version source refs must be carried by the registration payload")
        _proof_for_status(version.status, version.source_ref_ids, version.verification_proof)
        state = composed.extension_state("r3_e1_durable_knowledge_substrate")
        if isinstance(state, R3E1State):
            if state.version(version.version_id) is not None:
                raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "version identity already exists in origin state")
            existing_fact = state.fact(fact.fact_id)
            if existing_fact is not None:
                immutable_fact = fact.to_dict()
                immutable_fact.pop("current_version_id", None)
                prior_fact = existing_fact.to_dict()
                prior_fact.pop("current_version_id", None)
                if canonical_sha256(immutable_fact) != canonical_sha256(prior_fact):
                    raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "fact identity conflicts across versions")
                prior_version = state.version(existing_fact.current_version_id)
                if prior_version is not None and version.version_number <= prior_version.version_number:
                    raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "Knowledge version number must increase monotonically")
        event_payload = self._base(command, payload, scope)
        return _pending(VERSION_REGISTERED, "KNOWLEDGE_VERSION", version.version_id, event_payload, command.session_id)

    def _record_relation(self, command: Any, composed: ComposedRuntimeState, payload: dict[str, Any]) -> list[PendingEvent]:
        relation = KnowledgeRelation.from_dict(payload.get("relation") or {})
        scope = relation.scope_identity
        source_refs = _sources(payload, scope)
        known_source_ids = {item.source_ref_id for item in source_refs}
        state = composed.extension_state("r3_e1_durable_knowledge_substrate")
        if isinstance(state, R3E1State):
            known_source_ids |= {item.source_ref_id for item in state.source_refs}
            if any(item.relation_id == relation.relation_id for item in state.relations):
                raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "relation identity already exists in origin state")
            for endpoint in (relation.from_ref, relation.to_ref):
                endpoint_fact = state.fact(endpoint.endpoint_id)
                endpoint_version = state.version(endpoint.version_id)
                if endpoint_fact is None or endpoint_version is None or endpoint_fact.current_version_id != endpoint.version_id:
                    raise R3E1Error("R3_E1_RELATION_ENDPOINT_INVALID", "relation endpoint is dangling or not current")
                if endpoint_version.fact_id != endpoint.endpoint_id or endpoint_version.scope_identity != endpoint.scope_identity:
                    raise R3E1Error("R3_E1_RELATION_ENDPOINT_INVALID", "relation endpoint version does not match fact scope")
                if not set(endpoint.source_ref_ids).issubset(known_source_ids):
                    raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "relation endpoint source refs are unresolved")
        if not set(relation.source_ref_ids).issubset(known_source_ids):
            raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "relation source refs are not available in event/origin state")
        event_payload = self._base(command, payload, scope)
        return _pending(RELATION_RECORDED, "KNOWLEDGE_RELATION", relation.relation_id, event_payload, command.session_id)

    def _record_freshness(self, command: Any, composed: ComposedRuntimeState, payload: dict[str, Any]) -> list[PendingEvent]:
        freshness = KnowledgeFreshness.from_dict(payload.get("freshness") or {})
        scope = freshness.scope_identity
        source_refs = _sources(payload, scope)
        state = composed.extension_state("r3_e1_durable_knowledge_substrate")
        if isinstance(state, R3E1State) and any(item.freshness_id == freshness.freshness_id for item in state.freshness):
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "freshness identity already exists in origin state")
        if isinstance(state, R3E1State):
            target = state.version(freshness.target_version_id)
            if target is None or target.scope_identity != scope:
                raise R3E1Error("R3_E1_FRESHNESS_REQUIRED", "freshness target version is unresolved")
        if not set(freshness.source_ref_ids).issubset({item.source_ref_id for item in source_refs} | {
            item.source_ref_id for item in state.source_refs
        } if isinstance(state, R3E1State) else {item.source_ref_id for item in source_refs}):
            raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "freshness source refs are unresolved")
        event_payload = self._base(command, payload, scope)
        return _pending(FRESHNESS_RECORDED, "KNOWLEDGE_FRESHNESS", freshness.freshness_id, event_payload, command.session_id)

    def _record_conflict(self, command: Any, composed: ComposedRuntimeState, payload: dict[str, Any]) -> list[PendingEvent]:
        conflict = KnowledgeConflict.from_dict(payload.get("conflict") or {})
        scope = conflict.scope_identity
        source_refs = _sources(payload, scope)
        state = composed.extension_state("r3_e1_durable_knowledge_substrate")
        if isinstance(state, R3E1State) and any(item.conflict_id == conflict.conflict_id for item in state.conflicts):
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "conflict identity already exists in origin state")
        if isinstance(state, R3E1State):
            if any(state.version(item) is None for item in conflict.competing_version_ids):
                raise R3E1Error("R3_E1_CONFLICT_UNRESOLVED", "conflict competing version is unresolved")
        if not set(conflict.source_ref_ids).issubset({item.source_ref_id for item in source_refs} | {
            item.source_ref_id for item in state.source_refs
        } if isinstance(state, R3E1State) else {item.source_ref_id for item in source_refs}):
            raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "conflict source refs are unresolved")
        event_payload = self._base(command, payload, scope)
        return _pending(CONFLICT_RECORDED, "KNOWLEDGE_CONFLICT", conflict.conflict_id, event_payload, command.session_id)

    def _transition(self, command: Any, composed: ComposedRuntimeState, payload: dict[str, Any]) -> list[PendingEvent]:
        scope = _scope(payload.get("knowledge_scope_identity") or {})
        version_id = _text(payload.get("version_id"), "version_id")
        from_status = _text(payload.get("from_status"), "from_status")
        to_status = _text(payload.get("to_status"), "to_status")
        validate_transition(from_status, to_status)
        proof = _mapping(payload.get("proof"), "proof")
        source_refs = _sources(payload, scope)
        _proof_for_status(to_status, tuple(item.source_ref_id for item in source_refs), proof)
        state = composed.extension_state("r3_e1_durable_knowledge_substrate")
        if isinstance(state, R3E1State):
            existing = state.version(version_id)
            if existing is not None and (existing.scope_identity != scope or existing.status != from_status):
                raise R3E1Error("R3_E1_STATUS_TRANSITION_INVALID", "lifecycle request does not match origin state")
        event_payload = self._base(command, payload, scope)
        return _pending(LIFECYCLE_TRANSITIONED, "KNOWLEDGE_VERSION", version_id, event_payload, command.session_id)
