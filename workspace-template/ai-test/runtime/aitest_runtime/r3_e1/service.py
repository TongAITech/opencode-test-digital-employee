from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandEnvelope, CommandResult, RuntimeService, canonical_sha256

from .contracts import (
    RECORD_CONFLICT,
    RECORD_FRESHNESS,
    RECORD_RELATION,
    REGISTER_VERSION,
    TRANSITION_LIFECYCLE,
    KnowledgeConflict,
    KnowledgeFreshness,
    KnowledgeRelation,
    KnowledgeScopeIdentity,
    KnowledgeSourceRef,
    KnowledgeVersion,
    R3E1Error,
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _actor(value: ActorRef | Mapping[str, Any]) -> ActorRef:
    if isinstance(value, ActorRef):
        return value
    if not isinstance(value, Mapping):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", "actor must be an object")
    return ActorRef(_text(value.get("type"), "actor.type"), _text(value.get("id"), "actor.id"))


@dataclass(frozen=True)
class R3E1OperationResult:
    command_result: CommandResult
    value: Any = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def error(self) -> Any:
        return self.command_result.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_result": self.command_result.to_dict(),
            "value": self.value.to_dict() if hasattr(self.value, "to_dict") else self.value,
        }


class R3E1ApplicationService:
    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest("r3_e1_durable_knowledge_substrate")
        self._runtime = runtime_service

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime

    def _run(
        self,
        *,
        command_type: str,
        entity_id: str,
        mission_id: str,
        scope: KnowledgeScopeIdentity,
        payload: Mapping[str, Any],
        actor: ActorRef | Mapping[str, Any],
        idempotency_key: str | None,
        correlation_id: str | None,
        command_id: str | None,
        session_id: str | None,
    ) -> CommandResult:
        mission_id = _text(mission_id, "mission_id")
        actor_ref = _actor(actor)
        origin = dict(payload.get("origin_lineage") or {})
        origin["mission_id"] = mission_id
        if session_id is not None:
            origin["session_id"] = session_id
        raw = dict(payload)
        raw["knowledge_scope_identity"] = scope.to_dict()
        raw["origin_lineage"] = origin
        raw["payload_digest"] = canonical_sha256(raw)
        if command_id is None:
            if command_type == TRANSITION_LIFECYCLE:
                transition_key = f"{raw.get('from_status')}->{raw.get('to_status')}"
                command_id = f"r3.e1:{command_type}:{entity_id}:{idempotency_key or transition_key}"
            else:
                command_id = f"r3.e1:{command_type}:{entity_id}:{idempotency_key or 'once'}"
        return self._runtime.execute(
            CommandEnvelope(
                command_id=_text(command_id, "command_id"),
                type=command_type,
                mission_id=mission_id,
                session_id=session_id,
                expected_seq=self._runtime.get_head_seq(mission_id),
                actor=actor_ref,
                payload=raw,
                idempotency_key=idempotency_key or command_id,
                correlation_id=correlation_id or command_id,
                schema_version=1,
            )
        )

    def register_version(
        self,
        *,
        mission_id: str,
        fact: Any,
        version: KnowledgeVersion,
        source_refs: tuple[KnowledgeSourceRef, ...] | list[KnowledgeSourceRef],
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e1"},
        origin_lineage: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E1OperationResult:
        from .contracts import KnowledgeFact

        if not isinstance(fact, KnowledgeFact):
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "fact must be KnowledgeFact")
        if not isinstance(version, KnowledgeVersion):
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "version must be KnowledgeVersion")
        sources = tuple(source_refs)
        scope = fact.scope_identity
        if version.scope_identity != scope or tuple(item.scope_identity for item in sources) != (scope,) * len(sources):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "registration values must share KnowledgeScopeIdentity")
        result = self._run(
            command_type=REGISTER_VERSION,
            entity_id=version.version_id,
            mission_id=mission_id,
            scope=scope,
            payload={
                "fact": fact.to_dict(),
                "version": version.to_dict(),
                "source_refs": [item.to_dict() for item in sources],
                "origin_lineage": dict(origin_lineage or {}),
            },
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            command_id=command_id,
            session_id=(origin_lineage or {}).get("session_id"),
        )
        return R3E1OperationResult(result, version if result.ok else None)

    def record_relation(
        self,
        *,
        mission_id: str,
        relation: KnowledgeRelation,
        source_refs: tuple[KnowledgeSourceRef, ...] | list[KnowledgeSourceRef],
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e1"},
        origin_lineage: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E1OperationResult:
        sources = tuple(source_refs)
        if any(item.scope_identity != relation.scope_identity for item in sources):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "relation source refs must match relation scope")
        result = self._run(
            command_type=RECORD_RELATION,
            entity_id=relation.relation_id,
            mission_id=mission_id,
            scope=relation.scope_identity,
            payload={
                "relation": relation.to_dict(),
                "source_refs": [item.to_dict() for item in sources],
                "origin_lineage": dict(origin_lineage or {}),
            },
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            command_id=command_id,
            session_id=(origin_lineage or {}).get("session_id"),
        )
        return R3E1OperationResult(result, relation if result.ok else None)

    def record_freshness(
        self,
        *,
        mission_id: str,
        freshness: KnowledgeFreshness,
        source_refs: tuple[KnowledgeSourceRef, ...] | list[KnowledgeSourceRef],
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e1"},
        origin_lineage: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E1OperationResult:
        sources = tuple(source_refs)
        if any(item.scope_identity != freshness.scope_identity for item in sources):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "freshness source refs must match freshness scope")
        result = self._run(
            command_type=RECORD_FRESHNESS,
            entity_id=freshness.freshness_id,
            mission_id=mission_id,
            scope=freshness.scope_identity,
            payload={
                "freshness": freshness.to_dict(),
                "source_refs": [item.to_dict() for item in sources],
                "origin_lineage": dict(origin_lineage or {}),
            },
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            command_id=command_id,
            session_id=(origin_lineage or {}).get("session_id"),
        )
        return R3E1OperationResult(result, freshness if result.ok else None)

    def record_conflict(
        self,
        *,
        mission_id: str,
        conflict: KnowledgeConflict,
        source_refs: tuple[KnowledgeSourceRef, ...] | list[KnowledgeSourceRef],
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e1"},
        origin_lineage: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E1OperationResult:
        sources = tuple(source_refs)
        if any(item.scope_identity != conflict.scope_identity for item in sources):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "conflict source refs must match conflict scope")
        result = self._run(
            command_type=RECORD_CONFLICT,
            entity_id=conflict.conflict_id,
            mission_id=mission_id,
            scope=conflict.scope_identity,
            payload={
                "conflict": conflict.to_dict(),
                "source_refs": [item.to_dict() for item in sources],
                "origin_lineage": dict(origin_lineage or {}),
            },
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            command_id=command_id,
            session_id=(origin_lineage or {}).get("session_id"),
        )
        return R3E1OperationResult(result, conflict if result.ok else None)

    def transition_lifecycle(
        self,
        *,
        mission_id: str,
        scope_identity: KnowledgeScopeIdentity,
        version_id: str,
        from_status: str,
        to_status: str,
        proof: Mapping[str, Any],
        source_refs: tuple[KnowledgeSourceRef, ...] | list[KnowledgeSourceRef],
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e1"},
        origin_lineage: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E1OperationResult:
        sources = tuple(source_refs)
        if any(item.scope_identity != scope_identity for item in sources):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "lifecycle source refs must match scope")
        result = self._run(
            command_type=TRANSITION_LIFECYCLE,
            entity_id=version_id,
            mission_id=mission_id,
            scope=scope_identity,
            payload={
                "version_id": _text(version_id, "version_id"),
                "from_status": _text(from_status, "from_status"),
                "to_status": _text(to_status, "to_status"),
                "proof": dict(proof),
                "source_refs": [item.to_dict() for item in sources],
                "origin_lineage": dict(origin_lineage or {}),
            },
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            command_id=command_id,
            session_id=(origin_lineage or {}).get("session_id"),
        )
        return R3E1OperationResult(result)

    def retrieve(self, request: Any) -> Any:
        from .retrieval import KnowledgeRetrievalAdapter

        return KnowledgeRetrievalAdapter(self._runtime).retrieve(request)
