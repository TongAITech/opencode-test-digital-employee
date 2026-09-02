from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r3_1_requirement_coverage_traceability"
EXTENSION_VERSION = "1"
R31_SCHEMA_VERSION = 1

DERIVE_REQUIREMENT_COVERAGE = "R31_DERIVE_REQUIREMENT_COVERAGE"
DERIVATION_CREATED = "r3.1.derivation_created.v1"
DERIVATION_REUSED = "r3.1.derivation_reused.v1"
EVENT_TYPES = frozenset({DERIVATION_CREATED, DERIVATION_REUSED})
COMMAND_TYPES = frozenset({DERIVE_REQUIREMENT_COVERAGE})

MAPPING_STATES = frozenset({"MAPPED", "PARTIAL", "UNMAPPED"})
COVERAGE_GAP_KINDS = frozenset({
    "UNCOVERED",
    "REQUIREMENT_CODE_GAP",
    "SOURCE_INCOMPLETE",
    "TRACEABILITY_CONFLICT",
    "SOURCE_UNAVAILABLE",
})
GAP_UNCOVERED = "UNCOVERED"
ACCEPTED_SOURCE_KINDS = frozenset({"REQUIREMENT", "SST", "DESIGN"})
ACCEPTED_OBLIGATION_TYPES = frozenset({
    "REQUIREMENT",
    "BUSINESS_RULE",
    "ACCEPTANCE_CRITERION",
    "BUSINESS_OPERATION",
    "STATE_TRANSITION",
})


class R31Error(RuntimeError):
    """R3.1 schema, derivation, and traceability error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be an array")
    return list(value)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be a boolean")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class SourceProvenance:
    source_id: str
    source_kind: str
    revision: str
    locator: str
    item_id: str
    source_digest: str
    source_bundle_digest: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_id", "source_kind", "revision", "locator", "item_id", "source_digest", "source_bundle_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_kind not in ACCEPTED_SOURCE_KINDS:
            raise R31Error("R3_1_SOURCE_KIND_UNSUPPORTED", f"unsupported source kind: {self.source_kind}")
        object.__setattr__(self, "metadata", _freeze(_mapping(self.metadata, "metadata")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "revision": self.revision,
            "locator": self.locator,
            "item_id": self.item_id,
            "source_digest": self.source_digest,
            "source_bundle_digest": self.source_bundle_digest,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceProvenance":
        return cls(
            source_id=value["source_id"], source_kind=value["source_kind"], revision=value["revision"],
            locator=value["locator"], item_id=value["item_id"], source_digest=value["source_digest"],
            source_bundle_digest=value["source_bundle_digest"], metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class CoverageRelation:
    relation_id: str
    obligation_id: str
    asset_id: str
    relation_type: str
    mapping_state: str
    source_provenance: tuple[SourceProvenance, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("relation_id", "obligation_id", "asset_id", "relation_type"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.mapping_state not in MAPPING_STATES:
            raise R31Error("R3_1_MAPPING_STATE_INVALID", f"invalid mapping_state: {self.mapping_state}")
        if not isinstance(self.source_provenance, tuple) or any(not isinstance(item, SourceProvenance) for item in self.source_provenance):
            raise R31Error("R3_1_SCHEMA_INVALID", "source_provenance must be an immutable tuple")
        object.__setattr__(self, "metadata", _freeze(_mapping(self.metadata, "metadata")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "obligation_id": self.obligation_id,
            "asset_id": self.asset_id,
            "relation_type": self.relation_type,
            "mapping_state": self.mapping_state,
            "source_provenance": [item.to_dict() for item in self.source_provenance],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageRelation":
        return cls(
            relation_id=value["relation_id"], obligation_id=value["obligation_id"], asset_id=value["asset_id"],
            relation_type=value["relation_type"], mapping_state=value["mapping_state"],
            source_provenance=tuple(SourceProvenance.from_dict(item) for item in value.get("source_provenance") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class CoverageGap:
    gap_id: str
    obligation_id: str
    kind: str
    reason: str
    source_provenance: tuple[SourceProvenance, ...] = ()

    def __post_init__(self) -> None:
        for name in ("gap_id", "obligation_id", "reason"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.kind not in COVERAGE_GAP_KINDS:
            raise R31Error("R3_1_COVERAGE_GAP_INVALID", f"invalid CoverageGap kind: {self.kind}")
        if not isinstance(self.source_provenance, tuple) or any(not isinstance(item, SourceProvenance) for item in self.source_provenance):
            raise R31Error("R3_1_SCHEMA_INVALID", "source_provenance must be an immutable tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "reason": self.reason,
            "source_provenance": [item.to_dict() for item in self.source_provenance],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        return cls(
            gap_id=value["gap_id"], obligation_id=value["obligation_id"], kind=value["kind"], reason=value["reason"],
            source_provenance=tuple(SourceProvenance.from_dict(item) for item in value.get("source_provenance") or ()),
        )


@dataclass(frozen=True)
class TestCoverageObligation:
    obligation_id: str
    obligation_type: str
    text: str
    source_provenance: tuple[SourceProvenance, ...]
    mapping_state: str
    coverage_gaps: tuple[CoverageGap, ...] = ()
    coverage_relations: tuple[CoverageRelation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("obligation_id", "obligation_type", "text"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.obligation_type not in ACCEPTED_OBLIGATION_TYPES:
            raise R31Error("R3_1_OBLIGATION_TYPE_UNSUPPORTED", f"unsupported obligation type: {self.obligation_type}")
        if self.mapping_state not in MAPPING_STATES:
            raise R31Error("R3_1_MAPPING_STATE_INVALID", f"invalid mapping_state: {self.mapping_state}")
        if not isinstance(self.source_provenance, tuple) or not self.source_provenance:
            raise R31Error("R3_1_PROVENANCE_MISSING", f"obligation has no source provenance: {self.obligation_id}")
        if any(not isinstance(item, SourceProvenance) for item in self.source_provenance):
            raise R31Error("R3_1_SCHEMA_INVALID", "source_provenance must contain SourceProvenance values")
        for name, cls in (("coverage_gaps", CoverageGap), ("coverage_relations", CoverageRelation)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be immutable typed tuples")
        object.__setattr__(self, "metadata", _freeze(_mapping(self.metadata, "metadata")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "obligation_type": self.obligation_type,
            "text": self.text,
            "source_provenance": [item.to_dict() for item in self.source_provenance],
            "mapping_state": self.mapping_state,
            "coverage_gaps": [item.to_dict() for item in self.coverage_gaps],
            "coverage_relations": [item.to_dict() for item in self.coverage_relations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestCoverageObligation":
        return cls(
            obligation_id=value["obligation_id"], obligation_type=value["obligation_type"], text=value["text"],
            source_provenance=tuple(SourceProvenance.from_dict(item) for item in value.get("source_provenance") or ()),
            mapping_state=value["mapping_state"],
            coverage_gaps=tuple(CoverageGap.from_dict(item) for item in value.get("coverage_gaps") or ()),
            coverage_relations=tuple(CoverageRelation.from_dict(item) for item in value.get("coverage_relations") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class DerivationIdentity:
    mission_id: str
    scope_identity: str
    source_bundle_digest: str
    derivation_policy_version: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "scope_identity", "source_bundle_digest", "derivation_policy_version"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "mission_id": self.mission_id,
            "scope_identity": self.scope_identity,
            "source_bundle_digest": self.source_bundle_digest,
            "derivation_policy_version": self.derivation_policy_version,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DerivationIdentity":
        return cls(
            mission_id=value["mission_id"], scope_identity=value["scope_identity"],
            source_bundle_digest=value["source_bundle_digest"],
            derivation_policy_version=value["derivation_policy_version"],
        )


@dataclass(frozen=True)
class CoverageSnapshot:
    snapshot_id: str
    derivation_version_id: str
    identity: DerivationIdentity
    denominator_count: int
    obligations: tuple[TestCoverageObligation, ...]
    created_seq: int
    created_at: str

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "derivation_version_id", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.denominator_count, int) or isinstance(self.denominator_count, bool) or self.denominator_count < 1:
            raise R31Error("R3_1_SCHEMA_INVALID", "denominator_count must be a positive integer")
        if self.denominator_count != len(self.obligations):
            raise R31Error("R3_1_DENOMINATOR_MISMATCH", "snapshot denominator does not match obligation count")
        if not isinstance(self.created_seq, int) or isinstance(self.created_seq, bool) or self.created_seq < 1:
            raise R31Error("R3_1_SCHEMA_INVALID", "created_seq must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "derivation_version_id": self.derivation_version_id,
            "identity": self.identity.to_dict(),
            "derivation_fingerprint": self.identity.fingerprint,
            "denominator_count": self.denominator_count,
            "obligations": [item.to_dict() for item in self.obligations],
            "created_seq": self.created_seq,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageSnapshot":
        identity = DerivationIdentity.from_dict(value["identity"])
        if value.get("derivation_fingerprint") not in (None, identity.fingerprint):
            raise R31Error("R3_1_FINGERPRINT_MISMATCH", "snapshot fingerprint does not match identity")
        return cls(
            snapshot_id=value["snapshot_id"], derivation_version_id=value["derivation_version_id"], identity=identity,
            denominator_count=value["denominator_count"],
            obligations=tuple(TestCoverageObligation.from_dict(item) for item in value.get("obligations") or ()),
            created_seq=value["created_seq"], created_at=value["created_at"],
        )


@dataclass(frozen=True)
class DerivationVersion:
    derivation_version_id: str
    identity: DerivationIdentity
    obligation_denominator_count: int
    obligations: tuple[TestCoverageObligation, ...]
    coverage_snapshot_id: str
    evidence_references: tuple[str, ...]
    created_seq: int
    created_at: str
    correlation_id: str
    idempotency_key: str
    requested_by: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in ("derivation_version_id", "coverage_snapshot_id", "created_at", "correlation_id", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.obligation_denominator_count != len(self.obligations) or self.obligation_denominator_count < 1:
            raise R31Error("R3_1_DENOMINATOR_MISMATCH", "derivation denominator does not match obligations")
        if not isinstance(self.created_seq, int) or isinstance(self.created_seq, bool) or self.created_seq < 1:
            raise R31Error("R3_1_SCHEMA_INVALID", "created_seq must be positive")
        if not isinstance(self.evidence_references, tuple) or not self.evidence_references or any(not isinstance(item, str) or not item.strip() for item in self.evidence_references):
            raise R31Error("R3_1_EVIDENCE_REFERENCE_MISSING", "derivation evidence references must be non-empty")
        actor = _mapping(self.requested_by, "requested_by")
        if not _text(actor.get("type"), "requested_by.type") or not _text(actor.get("id"), "requested_by.id"):
            raise R31Error("R3_1_SCHEMA_INVALID", "requested_by must contain type and id")
        object.__setattr__(self, "requested_by", {"type": actor["type"], "id": actor["id"]})

    @property
    def derivation_fingerprint(self) -> str:
        return self.identity.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "derivation_version_id": self.derivation_version_id,
            "identity": self.identity.to_dict(),
            "derivation_fingerprint": self.derivation_fingerprint,
            "obligation_denominator_count": self.obligation_denominator_count,
            "obligations": [item.to_dict() for item in self.obligations],
            "coverage_snapshot_id": self.coverage_snapshot_id,
            "evidence_references": list(self.evidence_references),
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "requested_by": dict(self.requested_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DerivationVersion":
        identity = DerivationIdentity.from_dict(value["identity"])
        if value.get("derivation_fingerprint") not in (None, identity.fingerprint):
            raise R31Error("R3_1_FINGERPRINT_MISMATCH", "derivation fingerprint does not match identity")
        return cls(
            derivation_version_id=value["derivation_version_id"], identity=identity,
            obligation_denominator_count=value["obligation_denominator_count"],
            obligations=tuple(TestCoverageObligation.from_dict(item) for item in value.get("obligations") or ()),
            coverage_snapshot_id=value["coverage_snapshot_id"],
            evidence_references=tuple(value.get("evidence_references") or ()),
            created_seq=value["created_seq"], created_at=value["created_at"],
            correlation_id=value["correlation_id"], idempotency_key=value["idempotency_key"],
            requested_by=value["requested_by"],
        )


@dataclass(frozen=True)
class ReuseReference:
    reuse_id: str
    derivation_version_id: str
    derivation_fingerprint: str
    idempotency_key: str
    created_seq: int
    created_at: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("reuse_id", "derivation_version_id", "derivation_fingerprint", "idempotency_key", "created_at", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.created_seq, int) or isinstance(self.created_seq, bool) or self.created_seq < 1:
            raise R31Error("R3_1_SCHEMA_INVALID", "reuse created_seq must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reuse_id": self.reuse_id,
            "derivation_version_id": self.derivation_version_id,
            "derivation_fingerprint": self.derivation_fingerprint,
            "idempotency_key": self.idempotency_key,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReuseReference":
        return cls(
            reuse_id=value["reuse_id"], derivation_version_id=value["derivation_version_id"],
            derivation_fingerprint=value["derivation_fingerprint"], idempotency_key=value["idempotency_key"],
            created_seq=value["created_seq"], created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class R31State:
    mission_id: str
    derivations: tuple[DerivationVersion, ...] = ()
    snapshots: tuple[CoverageSnapshot, ...] = ()
    reuses: tuple[ReuseReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (("derivations", DerivationVersion), ("snapshots", CoverageSnapshot), ("reuses", ReuseReference)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R31Error("R3_1_SCHEMA_INVALID", f"{name} must be immutable typed tuples")
            ids = [getattr(item, next(iter(item.__dataclass_fields__))) for item in values]
            if len(ids) != len(set(ids)):
                raise R31Error("R3_1_IDENTITY_CONFLICT", f"{name} identities must be unique")

    def derivation(self, fingerprint: str) -> DerivationVersion | None:
        return next((item for item in self.derivations if item.derivation_fingerprint == fingerprint), None)

    def snapshot(self, snapshot_id: str) -> CoverageSnapshot | None:
        return next((item for item in self.snapshots if item.snapshot_id == snapshot_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "derivations": [item.to_dict() for item in sorted(self.derivations, key=lambda value: value.derivation_version_id)],
            "snapshots": [item.to_dict() for item in sorted(self.snapshots, key=lambda value: value.snapshot_id)],
            "reuses": [item.to_dict() for item in sorted(self.reuses, key=lambda value: value.reuse_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R31State":
        return cls(
            mission_id=value["mission_id"],
            derivations=tuple(DerivationVersion.from_dict(item) for item in value.get("derivations") or ()),
            snapshots=tuple(CoverageSnapshot.from_dict(item) for item in value.get("snapshots") or ()),
            reuses=tuple(ReuseReference.from_dict(item) for item in value.get("reuses") or ()),
        )


@dataclass(frozen=True)
class DerivationRequest:
    mission_id: str
    scope_identity: str
    source_bundle_digest: str
    source_bundle: Mapping[str, Any]
    derivation_policy_version: str
    idempotency_key: str
    requested_by: Mapping[str, str]
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "scope_identity", "source_bundle_digest", "derivation_policy_version", "idempotency_key", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "source_bundle", _mapping(self.source_bundle, "source_bundle"))
        actor = _mapping(self.requested_by, "requested_by")
        object.__setattr__(self, "requested_by", {"type": _text(actor.get("type"), "requested_by.type"), "id": _text(actor.get("id"), "requested_by.id")})

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, command_mission_id: str | None = None, correlation_id: str | None = None) -> "DerivationRequest":
        payload = _mapping(payload, "payload")
        required = {
            "mission_id", "scope_identity", "source_bundle_digest", "source_bundle",
            "derivation_policy_version", "idempotency_key", "requested_by",
        }
        if set(payload) != required:
            raise R31Error("R3_1_SCHEMA_INVALID", "derivation payload contains unknown or missing fields")
        request = cls(
            mission_id=payload["mission_id"], scope_identity=payload["scope_identity"],
            source_bundle_digest=payload["source_bundle_digest"], source_bundle=payload["source_bundle"],
            derivation_policy_version=payload["derivation_policy_version"], idempotency_key=payload["idempotency_key"],
            requested_by=payload["requested_by"], correlation_id=correlation_id or request_correlation(payload),
        )
        if command_mission_id is not None and request.mission_id != command_mission_id:
            raise R31Error("R3_1_MISSION_IDENTITY_MISMATCH", "payload mission_id differs from command mission_id")
        return request

    def identity(self) -> DerivationIdentity:
        return DerivationIdentity(
            mission_id=self.mission_id, scope_identity=self.scope_identity,
            source_bundle_digest=self.source_bundle_digest,
            derivation_policy_version=self.derivation_policy_version,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "scope_identity": self.scope_identity,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle": dict(self.source_bundle),
            "derivation_policy_version": self.derivation_policy_version,
            "idempotency_key": self.idempotency_key,
            "requested_by": dict(self.requested_by),
        }


def request_correlation(payload: Mapping[str, Any]) -> str:
    # Payload callers may provide this only for pure contract inspection; runtime commands use the envelope correlation.
    return _text(payload.get("correlation_id") or payload.get("idempotency_key"), "correlation_id")
