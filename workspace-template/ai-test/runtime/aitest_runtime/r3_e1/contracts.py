from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r3_e1_durable_knowledge_substrate"
EXTENSION_VERSION = "1"
R3E1_SCHEMA_VERSION = 1
ARCHITECTURE_BASELINE_REF = "v5"

REGISTER_VERSION = "R3_E1_REGISTER_KNOWLEDGE_VERSION"
RECORD_RELATION = "R3_E1_RECORD_KNOWLEDGE_RELATION"
RECORD_FRESHNESS = "R3_E1_RECORD_KNOWLEDGE_FRESHNESS"
RECORD_CONFLICT = "R3_E1_RECORD_KNOWLEDGE_CONFLICT"
TRANSITION_LIFECYCLE = "R3_E1_TRANSITION_KNOWLEDGE_LIFECYCLE"

VERSION_REGISTERED = "r3.e1.knowledge_version_registered.v1"
RELATION_RECORDED = "r3.e1.knowledge_relation_recorded.v1"
FRESHNESS_RECORDED = "r3.e1.knowledge_freshness_recorded.v1"
CONFLICT_RECORDED = "r3.e1.knowledge_conflict_recorded.v1"
LIFECYCLE_TRANSITIONED = "r3.e1.knowledge_lifecycle_transitioned.v1"

COMMAND_TYPES = frozenset({
    REGISTER_VERSION,
    RECORD_RELATION,
    RECORD_FRESHNESS,
    RECORD_CONFLICT,
    TRANSITION_LIFECYCLE,
})
EVENT_TYPES = frozenset({
    VERSION_REGISTERED,
    RELATION_RECORDED,
    FRESHNESS_RECORDED,
    CONFLICT_RECORDED,
    LIFECYCLE_TRANSITIONED,
})

KNOWLEDGE_STATUSES = frozenset({
    "DISCOVERED",
    "CANDIDATE",
    "SOURCE_VERIFIED",
    "RUNTIME_VERIFIED",
    "USER_VERIFIED",
    "STALE",
    "CONFLICTED",
    "SUPERSEDED",
    "RETIRED",
})

DEFAULT_RETRIEVAL_STATUSES = frozenset({"SOURCE_VERIFIED", "RUNTIME_VERIFIED", "USER_VERIFIED"})
TERMINAL_STATUSES = frozenset({"RETIRED"})
FRESHNESS_RESULTS = frozenset({"FRESH", "STALE", "UNKNOWN"})
CONFLICT_STATUSES = frozenset({"OPEN", "RESOLVED"})

ENDPOINT_TYPES = frozenset({
    "FRONTEND_PAGE",
    "API_DEPENDENCY",
    "BACKEND_CODE",
    "DATABASE_DATA",
    "SYSTEM_TOPOLOGY",
    "JOURNEY_STATE",
})

SOURCE_CATEGORIES = frozenset({
    "FRONTEND_CODE",
    "BACKEND_CODE",
    "API",
    "DATABASE",
    "TOPOLOGY",
    "REQUIREMENT",
    "DESIGN",
    "BUSINESS",
    "JOURNEY",
    "RUNTIME",
    "HISTORICAL_DEFECT",
})

RELATION_SEMANTICS = frozenset({
    "ROUTES_TO",
    "CALLS",
    "IMPLEMENTS",
    "READS",
    "WRITES",
    "DEPENDS_ON",
    "LOCATED_IN",
    "SERVES",
    "TRANSITIONS_TO",
})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset({"CANDIDATE", "RETIRED"}),
    "CANDIDATE": frozenset({"SOURCE_VERIFIED", "CONFLICTED", "STALE", "RETIRED"}),
    "SOURCE_VERIFIED": frozenset({"RUNTIME_VERIFIED", "CONFLICTED", "STALE", "SUPERSEDED", "RETIRED"}),
    "RUNTIME_VERIFIED": frozenset({"USER_VERIFIED", "CONFLICTED", "STALE", "SUPERSEDED", "RETIRED"}),
    "USER_VERIFIED": frozenset({"CONFLICTED", "STALE", "SUPERSEDED", "RETIRED"}),
    "STALE": frozenset({"CANDIDATE", "SUPERSEDED", "RETIRED"}),
    "CONFLICTED": frozenset({"CANDIDATE", "SOURCE_VERIFIED", "RETIRED"}),
    "SUPERSEDED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}


class R3E1Error(RuntimeError):
    """R3.E1 schema, lifecycle, provenance, and retrieval error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _tuple_text(value: Any, name: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(value))
    if required and not result:
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _tuple_mapping(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[{index}]") for index, item in enumerate(value))


def _scope_key(scope: "KnowledgeScopeIdentity") -> str:
    return f"{scope.project_id}|{scope.environment_id}|{scope.version_scope}"


def _status(value: Any, name: str = "status") -> str:
    value = _text(value, name)
    if value not in KNOWLEDGE_STATUSES:
        raise R3E1Error("R3_E1_STATUS_INVALID", f"unsupported Knowledge status: {value}")
    return value


def _proof_for_status(status: str, source_ref_ids: tuple[str, ...], proof: Mapping[str, Any]) -> None:
    if status in {"SOURCE_VERIFIED", "RUNTIME_VERIFIED", "USER_VERIFIED"} and not source_ref_ids:
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", f"{status} requires durable source refs")
    if status == "RUNTIME_VERIFIED" and not _optional_text(proof.get("runtime_evidence_ref"), "runtime_evidence_ref"):
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "RUNTIME_VERIFIED requires runtime_evidence_ref")
    if status == "USER_VERIFIED" and not _optional_text(proof.get("user_verification_ref"), "user_verification_ref"):
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", "USER_VERIFIED requires user_verification_ref")
    if status in {"STALE", "CONFLICTED", "SUPERSEDED", "RETIRED"} and not proof:
        raise R3E1Error("R3_E1_PROVENANCE_REQUIRED", f"{status} requires explicit transition proof")


def validate_transition(from_status: str, to_status: str) -> None:
    from_status = _status(from_status, "from_status")
    to_status = _status(to_status, "to_status")
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise R3E1Error(
            "R3_E1_STATUS_TRANSITION_INVALID",
            f"{from_status} cannot transition to {to_status}",
            {"from_status": from_status, "to_status": to_status},
        )


@dataclass(frozen=True)
class KnowledgeScopeIdentity:
    project_id: str
    environment_id: str
    version_scope: str

    def __post_init__(self) -> None:
        for name in ("project_id", "environment_id", "version_scope"):
            value = _text(getattr(self, name), name)
            if value == "*":
                raise R3E1Error("R3_E1_SCOPE_MISMATCH", f"{name} cannot be a wildcard")
            object.__setattr__(self, name, value)

    @property
    def key(self) -> str:
        return _scope_key(self)

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "environment_id": self.environment_id,
            "version_scope": self.version_scope,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeScopeIdentity":
        raw = _mapping(value, "knowledge_scope_identity")
        required = {"project_id", "environment_id", "version_scope"}
        if set(raw) != required:
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "KnowledgeScopeIdentity must contain exactly project/environment/version")
        return cls(raw["project_id"], raw["environment_id"], raw["version_scope"])


@dataclass(frozen=True)
class KnowledgeSourceRef:
    source_ref_id: str
    source_category: str
    locator: str
    source_revision: str
    source_digest: str
    scope_identity: KnowledgeScopeIdentity
    captured_at: str
    observed_at: str
    retrieval_policy: str
    raw_content_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_ref_id", "source_category", "locator", "source_revision", "source_digest", "captured_at", "observed_at", "retrieval_policy"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_category not in SOURCE_CATEGORIES:
            raise R3E1Error("R3_E1_SOURCE_REF_INVALID", f"unsupported source category: {self.source_category}")
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "source ref requires KnowledgeScopeIdentity")
        object.__setattr__(self, "raw_content_ref", _optional_text(self.raw_content_ref, "raw_content_ref"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref_id": self.source_ref_id,
            "source_category": self.source_category,
            "locator": self.locator,
            "source_revision": self.source_revision,
            "source_digest": self.source_digest,
            "scope_identity": self.scope_identity.to_dict(),
            "captured_at": self.captured_at,
            "observed_at": self.observed_at,
            "retrieval_policy": self.retrieval_policy,
            "raw_content_ref": self.raw_content_ref,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeSourceRef":
        raw = _mapping(value, "source_ref")
        return cls(
            source_ref_id=raw["source_ref_id"],
            source_category=raw["source_category"],
            locator=raw["locator"],
            source_revision=raw["source_revision"],
            source_digest=raw["source_digest"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            captured_at=raw["captured_at"],
            observed_at=raw["observed_at"],
            retrieval_policy=raw["retrieval_policy"],
            raw_content_ref=raw.get("raw_content_ref"),
            metadata=raw.get("metadata") or {},
        )


@dataclass(frozen=True)
class KnowledgeFact:
    fact_id: str
    scope_identity: KnowledgeScopeIdentity
    subject: str
    predicate: str
    value: Any
    current_version_id: str
    anchor_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _text(self.fact_id, "fact_id"))
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(self, "predicate", _text(self.predicate, "predicate"))
        object.__setattr__(self, "current_version_id", _text(self.current_version_id, "current_version_id"))
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "fact requires KnowledgeScopeIdentity")
        object.__setattr__(self, "anchor_refs", _tuple_text(self.anchor_refs, "anchor_refs"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "scope_identity": self.scope_identity.to_dict(),
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "current_version_id": self.current_version_id,
            "anchor_refs": list(self.anchor_refs),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeFact":
        raw = _mapping(value, "fact")
        return cls(
            fact_id=raw["fact_id"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            subject=raw["subject"],
            predicate=raw["predicate"],
            value=raw.get("value"),
            current_version_id=raw["current_version_id"],
            anchor_refs=tuple(raw.get("anchor_refs") or ()),
            metadata=raw.get("metadata") or {},
        )


@dataclass(frozen=True)
class KnowledgeVersion:
    version_id: str
    fact_id: str
    version_number: int
    payload: Mapping[str, Any]
    scope_identity: KnowledgeScopeIdentity
    status: str
    confidence: str
    source_ref_ids: tuple[str, ...]
    freshness_id: str | None = None
    supersedes_version_id: str | None = None
    effective_at: str | None = None
    observed_at: str | None = None
    verification_proof: Mapping[str, Any] = field(default_factory=dict)
    payload_digest: str | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name in ("version_id", "fact_id", "confidence"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.version_number, int) or isinstance(self.version_number, bool) or self.version_number < 1:
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "version_number must be positive")
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "version requires KnowledgeScopeIdentity")
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(self, "source_ref_ids", _tuple_text(self.source_ref_ids, "source_ref_ids"))
        object.__setattr__(self, "freshness_id", _optional_text(self.freshness_id, "freshness_id"))
        object.__setattr__(self, "supersedes_version_id", _optional_text(self.supersedes_version_id, "supersedes_version_id"))
        object.__setattr__(self, "effective_at", _optional_text(self.effective_at, "effective_at"))
        object.__setattr__(self, "observed_at", _optional_text(self.observed_at, "observed_at"))
        object.__setattr__(self, "verification_proof", _mapping(self.verification_proof, "verification_proof"))
        expected_payload_digest = canonical_sha256(self.payload)
        if self.payload_digest is not None and self.payload_digest != expected_payload_digest:
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "payload_digest does not match version payload")
        object.__setattr__(self, "payload_digest", expected_payload_digest)
        expected_fingerprint = canonical_sha256({
            "version_id": self.version_id,
            "fact_id": self.fact_id,
            "version_number": self.version_number,
            "scope_identity": self.scope_identity.to_dict(),
            "payload_digest": expected_payload_digest,
            "source_ref_ids": list(self.source_ref_ids),
        })
        if self.fingerprint is not None and self.fingerprint != expected_fingerprint:
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "version fingerprint does not match immutable identity")
        object.__setattr__(self, "fingerprint", expected_fingerprint)
        _proof_for_status(self.status, self.source_ref_ids, self.verification_proof)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "fact_id": self.fact_id,
            "version_number": self.version_number,
            "payload": dict(self.payload),
            "scope_identity": self.scope_identity.to_dict(),
            "status": self.status,
            "confidence": self.confidence,
            "source_ref_ids": list(self.source_ref_ids),
            "freshness_id": self.freshness_id,
            "supersedes_version_id": self.supersedes_version_id,
            "effective_at": self.effective_at,
            "observed_at": self.observed_at,
            "verification_proof": dict(self.verification_proof),
            "payload_digest": self.payload_digest,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeVersion":
        raw = _mapping(value, "version")
        return cls(
            version_id=raw["version_id"],
            fact_id=raw["fact_id"],
            version_number=raw["version_number"],
            payload=raw.get("payload") or {},
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            status=raw["status"],
            confidence=raw.get("confidence", "UNKNOWN"),
            source_ref_ids=tuple(raw.get("source_ref_ids") or ()),
            freshness_id=raw.get("freshness_id"),
            supersedes_version_id=raw.get("supersedes_version_id"),
            effective_at=raw.get("effective_at"),
            observed_at=raw.get("observed_at"),
            verification_proof=raw.get("verification_proof") or {},
            payload_digest=raw.get("payload_digest"),
            fingerprint=raw.get("fingerprint"),
        )


@dataclass(frozen=True)
class KnowledgeEndpointRef:
    endpoint_id: str
    endpoint_type: str
    version_id: str
    scope_identity: KnowledgeScopeIdentity
    source_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("endpoint_id", "endpoint_type", "version_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.endpoint_type not in ENDPOINT_TYPES:
            raise R3E1Error("R3_E1_RELATION_ENDPOINT_INVALID", f"unsupported endpoint type: {self.endpoint_type}")
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "relation endpoint requires KnowledgeScopeIdentity")
        object.__setattr__(self, "source_ref_ids", _tuple_text(self.source_ref_ids, "endpoint.source_ref_ids", required=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "endpoint_type": self.endpoint_type,
            "version_id": self.version_id,
            "scope_identity": self.scope_identity.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeEndpointRef":
        raw = _mapping(value, "relation endpoint")
        return cls(
            endpoint_id=raw["endpoint_id"],
            endpoint_type=raw["endpoint_type"],
            version_id=raw["version_id"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            source_ref_ids=tuple(raw.get("source_ref_ids") or ()),
        )


def _validate_relation_semantics(from_type: str, to_type: str, semantic: str) -> None:
    semantic = _text(semantic, "semantic")
    if semantic not in RELATION_SEMANTICS:
        raise R3E1Error("R3_E1_RELATION_ENDPOINT_INVALID", f"unsupported relation semantic: {semantic}")
    exact = {
        "ROUTES_TO": {("FRONTEND_PAGE", "API_DEPENDENCY")},
        "CALLS": {("API_DEPENDENCY", "BACKEND_CODE")},
        "IMPLEMENTS": {("BACKEND_CODE", "DATABASE_DATA")},
        "READS": {("BACKEND_CODE", "DATABASE_DATA")},
        "WRITES": {("BACKEND_CODE", "DATABASE_DATA")},
        "TRANSITIONS_TO": {("DATABASE_DATA", "JOURNEY_STATE"), ("JOURNEY_STATE", "JOURNEY_STATE")},
    }
    if semantic in exact and (from_type, to_type) not in exact[semantic]:
        raise R3E1Error(
            "R3_E1_RELATION_ENDPOINT_INVALID",
            f"{semantic} is incompatible with {from_type}->{to_type}",
        )


@dataclass(frozen=True)
class KnowledgeRelation:
    relation_id: str
    from_ref: KnowledgeEndpointRef
    to_ref: KnowledgeEndpointRef
    semantic: str
    scope_identity: KnowledgeScopeIdentity
    status: str
    source_ref_ids: tuple[str, ...]
    relation_version: int = 1
    freshness_id: str | None = None
    conflict_id: str | None = None
    cross_scope_provenance: tuple[Mapping[str, Any], ...] = ()
    relation_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "relation_id", _text(self.relation_id, "relation_id"))
        if not isinstance(self.from_ref, KnowledgeEndpointRef) or not isinstance(self.to_ref, KnowledgeEndpointRef):
            raise R3E1Error("R3_E1_RELATION_ENDPOINT_INVALID", "relation endpoints must be typed")
        object.__setattr__(self, "semantic", _text(self.semantic, "semantic"))
        _validate_relation_semantics(self.from_ref.endpoint_type, self.to_ref.endpoint_type, self.semantic)
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "relation requires KnowledgeScopeIdentity")
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "source_ref_ids", _tuple_text(self.source_ref_ids, "source_ref_ids", required=True))
        if not isinstance(self.relation_version, int) or isinstance(self.relation_version, bool) or self.relation_version < 1:
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "relation_version must be positive")
        object.__setattr__(self, "freshness_id", _optional_text(self.freshness_id, "freshness_id"))
        object.__setattr__(self, "conflict_id", _optional_text(self.conflict_id, "conflict_id"))
        provenance = _tuple_mapping(self.cross_scope_provenance, "cross_scope_provenance")
        scopes_differ = self.from_ref.scope_identity != self.to_ref.scope_identity
        if scopes_differ and not provenance:
            raise R3E1Error("R3_E1_RELATION_SCOPE_MISMATCH", "cross-scope relation requires explicit provenance")
        if self.scope_identity != self.from_ref.scope_identity:
            raise R3E1Error("R3_E1_RELATION_SCOPE_MISMATCH", "relation owner scope must qualify the from endpoint scope")
        if scopes_differ:
            required = {"from_scope", "to_scope", "reason"}
            if not required.issubset(provenance[0]):
                raise R3E1Error("R3_E1_RELATION_SCOPE_MISMATCH", "cross-scope provenance must qualify both endpoint scopes")
        object.__setattr__(self, "cross_scope_provenance", provenance)
        digest_input = {
            "relation_id": self.relation_id,
            "from_ref": self.from_ref.to_dict(),
            "to_ref": self.to_ref.to_dict(),
            "semantic": self.semantic,
            "scope_identity": self.scope_identity.to_dict(),
            "status": self.status,
            "source_ref_ids": list(self.source_ref_ids),
            "relation_version": self.relation_version,
            "freshness_id": self.freshness_id,
            "conflict_id": self.conflict_id,
            "cross_scope_provenance": [dict(item) for item in provenance],
        }
        expected = canonical_sha256(digest_input)
        if self.relation_digest is not None and self.relation_digest != expected:
            raise R3E1Error("R3_E1_VERSION_IMMUTABLE", "relation_digest does not match relation")
        object.__setattr__(self, "relation_digest", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "from_ref": self.from_ref.to_dict(),
            "to_ref": self.to_ref.to_dict(),
            "semantic": self.semantic,
            "scope_identity": self.scope_identity.to_dict(),
            "status": self.status,
            "source_ref_ids": list(self.source_ref_ids),
            "relation_version": self.relation_version,
            "freshness_id": self.freshness_id,
            "conflict_id": self.conflict_id,
            "cross_scope_provenance": [dict(item) for item in self.cross_scope_provenance],
            "relation_digest": self.relation_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeRelation":
        raw = _mapping(value, "relation")
        return cls(
            relation_id=raw["relation_id"],
            from_ref=KnowledgeEndpointRef.from_dict(raw["from_ref"]),
            to_ref=KnowledgeEndpointRef.from_dict(raw["to_ref"]),
            semantic=raw["semantic"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            status=raw["status"],
            source_ref_ids=tuple(raw.get("source_ref_ids") or ()),
            relation_version=raw.get("relation_version", 1),
            freshness_id=raw.get("freshness_id"),
            conflict_id=raw.get("conflict_id"),
            cross_scope_provenance=tuple(raw.get("cross_scope_provenance") or ()),
            relation_digest=raw.get("relation_digest"),
        )


@dataclass(frozen=True)
class KnowledgeConflict:
    conflict_id: str
    fact_id: str
    scope_identity: KnowledgeScopeIdentity
    competing_version_ids: tuple[str, ...]
    conflict_kind: str
    reason: str
    detected_at: str
    source_ref_ids: tuple[str, ...]
    status: str = "OPEN"
    resolution_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("conflict_id", "fact_id", "conflict_kind", "reason", "detected_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "conflict requires KnowledgeScopeIdentity")
        object.__setattr__(self, "competing_version_ids", _tuple_text(self.competing_version_ids, "competing_version_ids", required=True))
        if len(self.competing_version_ids) < 2:
            raise R3E1Error("R3_E1_CONFLICT_UNRESOLVED", "conflict requires at least two competing versions")
        object.__setattr__(self, "source_ref_ids", _tuple_text(self.source_ref_ids, "source_ref_ids", required=True))
        object.__setattr__(self, "status", _text(self.status, "conflict.status"))
        if self.status not in CONFLICT_STATUSES:
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "conflict status must be OPEN or RESOLVED")
        object.__setattr__(self, "resolution_ref", _optional_text(self.resolution_ref, "resolution_ref"))
        if self.status == "RESOLVED" and self.resolution_ref is None:
            raise R3E1Error("R3_E1_CONFLICT_UNRESOLVED", "resolved conflict requires resolution_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "fact_id": self.fact_id,
            "scope_identity": self.scope_identity.to_dict(),
            "competing_version_ids": list(self.competing_version_ids),
            "conflict_kind": self.conflict_kind,
            "reason": self.reason,
            "detected_at": self.detected_at,
            "source_ref_ids": list(self.source_ref_ids),
            "status": self.status,
            "resolution_ref": self.resolution_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeConflict":
        raw = _mapping(value, "conflict")
        return cls(
            conflict_id=raw["conflict_id"],
            fact_id=raw["fact_id"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            competing_version_ids=tuple(raw.get("competing_version_ids") or ()),
            conflict_kind=raw["conflict_kind"],
            reason=raw["reason"],
            detected_at=raw["detected_at"],
            source_ref_ids=tuple(raw.get("source_ref_ids") or ()),
            status=raw.get("status", "OPEN"),
            resolution_ref=raw.get("resolution_ref"),
        )


@dataclass(frozen=True)
class KnowledgeFreshness:
    freshness_id: str
    target_version_id: str
    scope_identity: KnowledgeScopeIdentity
    policy_version: str
    observed_at: str
    expires_at: str | None
    next_check_at: str | None
    result: str
    source_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("freshness_id", "target_version_id", "policy_version", "observed_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.scope_identity, KnowledgeScopeIdentity):
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "freshness requires KnowledgeScopeIdentity")
        object.__setattr__(self, "expires_at", _optional_text(self.expires_at, "expires_at"))
        object.__setattr__(self, "next_check_at", _optional_text(self.next_check_at, "next_check_at"))
        object.__setattr__(self, "result", _text(self.result, "freshness.result"))
        if self.result not in FRESHNESS_RESULTS:
            raise R3E1Error("R3_E1_SCHEMA_INVALID", f"unsupported freshness result: {self.result}")
        object.__setattr__(self, "source_ref_ids", _tuple_text(self.source_ref_ids, "source_ref_ids", required=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness_id": self.freshness_id,
            "target_version_id": self.target_version_id,
            "scope_identity": self.scope_identity.to_dict(),
            "policy_version": self.policy_version,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "next_check_at": self.next_check_at,
            "result": self.result,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeFreshness":
        raw = _mapping(value, "freshness")
        return cls(
            freshness_id=raw["freshness_id"],
            target_version_id=raw["target_version_id"],
            scope_identity=KnowledgeScopeIdentity.from_dict(raw["scope_identity"]),
            policy_version=raw["policy_version"],
            observed_at=raw["observed_at"],
            expires_at=raw.get("expires_at"),
            next_check_at=raw.get("next_check_at"),
            result=raw["result"],
            source_ref_ids=tuple(raw.get("source_ref_ids") or ()),
        )


@dataclass(frozen=True)
class R3E1State:
    mission_id: str
    facts: tuple[KnowledgeFact, ...] = ()
    versions: tuple[KnowledgeVersion, ...] = ()
    source_refs: tuple[KnowledgeSourceRef, ...] = ()
    conflicts: tuple[KnowledgeConflict, ...] = ()
    freshness: tuple[KnowledgeFreshness, ...] = ()
    relations: tuple[KnowledgeRelation, ...] = ()
    lifecycle_events: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (
            ("facts", KnowledgeFact),
            ("versions", KnowledgeVersion),
            ("source_refs", KnowledgeSourceRef),
            ("conflicts", KnowledgeConflict),
            ("freshness", KnowledgeFreshness),
            ("relations", KnowledgeRelation),
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, cls) for item in value):
                raise R3E1Error("R3_E1_SCHEMA_INVALID", f"{name} must contain typed immutable values")
        object.__setattr__(self, "lifecycle_events", _tuple_mapping(self.lifecycle_events, "lifecycle_events"))

    def fact(self, fact_id: str) -> KnowledgeFact | None:
        return next((item for item in self.facts if item.fact_id == fact_id), None)

    def version(self, version_id: str) -> KnowledgeVersion | None:
        return next((item for item in self.versions if item.version_id == version_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "facts": [item.to_dict() for item in sorted(self.facts, key=lambda value: value.fact_id)],
            "versions": [item.to_dict() for item in sorted(self.versions, key=lambda value: value.version_id)],
            "source_refs": [item.to_dict() for item in sorted(self.source_refs, key=lambda value: value.source_ref_id)],
            "conflicts": [item.to_dict() for item in sorted(self.conflicts, key=lambda value: value.conflict_id)],
            "freshness": [item.to_dict() for item in sorted(self.freshness, key=lambda value: value.freshness_id)],
            "relations": [item.to_dict() for item in sorted(self.relations, key=lambda value: value.relation_id)],
            "lifecycle_events": [dict(item) for item in self.lifecycle_events],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R3E1State":
        return cls(
            mission_id=value["mission_id"],
            facts=tuple(KnowledgeFact.from_dict(item) for item in value.get("facts") or ()),
            versions=tuple(KnowledgeVersion.from_dict(item) for item in value.get("versions") or ()),
            source_refs=tuple(KnowledgeSourceRef.from_dict(item) for item in value.get("source_refs") or ()),
            conflicts=tuple(KnowledgeConflict.from_dict(item) for item in value.get("conflicts") or ()),
            freshness=tuple(KnowledgeFreshness.from_dict(item) for item in value.get("freshness") or ()),
            relations=tuple(KnowledgeRelation.from_dict(item) for item in value.get("relations") or ()),
            lifecycle_events=tuple(value.get("lifecycle_events") or ()),
        )
