from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r3_2_change_impact_reconciliation"
EXTENSION_VERSION = "1"
R32_SCHEMA_VERSION = 1

DERIVE_CHANGE_IMPACT_RECONCILIATION = "R32_DERIVE_CHANGE_IMPACT_RECONCILIATION"
CHANGE_IMPACT_DERIVED = "r3.2.change_impact_derived.v1"
RECONCILIATION_CREATED = "r3.2.reconciliation_created.v1"
RECONCILIATION_REUSED = "r3.2.reconciliation_reused.v1"
EVENT_TYPES = frozenset({CHANGE_IMPACT_DERIVED, RECONCILIATION_CREATED, RECONCILIATION_REUSED})
COMMAND_TYPES = frozenset({DERIVE_CHANGE_IMPACT_RECONCILIATION})

COMPARE_MODES = frozenset({"BASE_HEAD", "BRANCH", "COMMIT_RANGE", "WORKING_TREE"})
UNTRACKED_POLICIES = frozenset({"INCLUDE", "EXCLUDE", "EXPLICIT_LIST"})
CODE_INTELLIGENCE_STATUSES = frozenset({"COMPLETE", "PARTIAL", "UNAVAILABLE"})
IMPACT_RESOLUTIONS = frozenset({"RESOLVED", "PARTIAL", "UNMAPPED"})
SURFACE_KINDS = frozenset({"PAGE", "API", "DB", "SERVICE", "JOURNEY", "DOWNSTREAM", "SYSTEM"})
CHANGE_KINDS = frozenset({"ADDED", "MODIFIED", "DELETED", "RENAMED", "COPIED", "TYPE_CHANGED"})
RECONCILIATION_SEMANTICS = frozenset({
    "OVERLAP",
    "REQUIREMENT_ONLY",
    "CHANGE_ONLY",
    "REQUIREMENT_CODE_GAP",
})
RECONCILIATION_GAPS = frozenset({"REQUIREMENT_CODE_GAP", "UNMAPPED"})


class R32Error(RuntimeError):
    """R3.2 schema, provider, derivation, and reconciliation error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be an array")
    return list(value)


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be a number between 0 and 1")
    return float(value)


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{name}[]") for item in _array(value, name))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class RepositoryCompareRequest:
    repository_id: str
    compare_mode: str
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    commit_range: str | None = None
    working_tree_status_digest: str | None = None
    untracked_policy: str = "EXCLUDE"
    untracked_paths: tuple[str, ...] = ()
    repository_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        object.__setattr__(self, "compare_mode", _text(self.compare_mode, "compare_mode"))
        if self.compare_mode not in COMPARE_MODES:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", f"unsupported compare_mode: {self.compare_mode}")
        object.__setattr__(self, "untracked_policy", _text(self.untracked_policy, "untracked_policy"))
        if self.untracked_policy not in UNTRACKED_POLICIES:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", f"unsupported untracked_policy: {self.untracked_policy}")
        for name in ("base_ref", "base_sha", "head_ref", "head_sha", "commit_range", "working_tree_status_digest", "repository_path"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "untracked_paths", _text_tuple(self.untracked_paths, "untracked_paths"))
        if self.compare_mode in {"BASE_HEAD", "BRANCH"} and not (self.base_ref or self.base_sha) or self.compare_mode in {"BASE_HEAD", "BRANCH"} and not (self.head_ref or self.head_sha):
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "BASE_HEAD/BRANCH requires explicit base and head identity")
        if self.compare_mode == "COMMIT_RANGE" and not self.commit_range:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "COMMIT_RANGE requires an explicit commit_range")
        if self.compare_mode == "WORKING_TREE":
            if not (self.base_ref or self.base_sha):
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "WORKING_TREE requires an explicit base ref or sha")
            if not self.working_tree_status_digest:
                raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "WORKING_TREE requires working_tree_status_digest")
        if self.untracked_policy == "EXPLICIT_LIST" and not self.untracked_paths:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "EXPLICIT_LIST requires untracked_paths")

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "compare_mode": self.compare_mode,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "commit_range": self.commit_range,
            "working_tree_status_digest": self.working_tree_status_digest,
            "untracked_policy": self.untracked_policy,
            "untracked_paths": list(self.untracked_paths),
            "repository_path": self.repository_path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryCompareRequest":
        return cls(
            repository_id=value["repository_id"], compare_mode=value["compare_mode"],
            base_ref=value.get("base_ref"), base_sha=value.get("base_sha"),
            head_ref=value.get("head_ref"), head_sha=value.get("head_sha"),
            commit_range=value.get("commit_range"), working_tree_status_digest=value.get("working_tree_status_digest"),
            untracked_policy=value.get("untracked_policy", "EXCLUDE"),
            untracked_paths=tuple(value.get("untracked_paths") or ()), repository_path=value.get("repository_path"),
        )


@dataclass(frozen=True)
class CompareIdentity:
    repository_id: str
    compare_mode: str
    base_ref: str | None
    base_sha: str | None
    head_ref: str | None
    head_sha: str | None
    commit_range: str | None
    working_tree_status_digest: str | None
    untracked_policy: str
    diff_digest: str
    policy_version: str
    provider_id: str
    provider_version: str
    code_graph_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        object.__setattr__(self, "compare_mode", _text(self.compare_mode, "compare_mode"))
        if self.compare_mode not in COMPARE_MODES:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", f"unsupported compare_mode: {self.compare_mode}")
        for name in ("base_ref", "base_sha", "head_ref", "head_sha", "commit_range", "working_tree_status_digest", "code_graph_digest"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        for name in ("untracked_policy", "diff_digest", "policy_version", "provider_id", "provider_version"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.untracked_policy not in UNTRACKED_POLICIES:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", f"unsupported untracked_policy: {self.untracked_policy}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "compare_mode": self.compare_mode,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "commit_range": self.commit_range,
            "working_tree_status_digest": self.working_tree_status_digest,
            "untracked_policy": self.untracked_policy,
            "diff_digest": self.diff_digest,
            "policy_version": self.policy_version,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "code_graph_digest": self.code_graph_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompareIdentity":
        return cls(
            repository_id=value["repository_id"], compare_mode=value["compare_mode"],
            base_ref=value.get("base_ref"), base_sha=value.get("base_sha"),
            head_ref=value.get("head_ref"), head_sha=value.get("head_sha"),
            commit_range=value.get("commit_range"), working_tree_status_digest=value.get("working_tree_status_digest"),
            untracked_policy=value["untracked_policy"], diff_digest=value["diff_digest"],
            policy_version=value["policy_version"], provider_id=value["provider_id"],
            provider_version=value["provider_version"], code_graph_digest=value.get("code_graph_digest"),
        )


@dataclass(frozen=True)
class R31Reference:
    derivation_version_id: str
    snapshot_id: str
    derivation_fingerprint: str
    source_bundle_digest: str
    provenance_bundle_digest: str

    def __post_init__(self) -> None:
        for name in ("derivation_version_id", "snapshot_id", "derivation_fingerprint", "source_bundle_digest", "provenance_bundle_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "derivation_version_id": self.derivation_version_id,
            "snapshot_id": self.snapshot_id,
            "derivation_fingerprint": self.derivation_fingerprint,
            "source_bundle_digest": self.source_bundle_digest,
            "provenance_bundle_digest": self.provenance_bundle_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R31Reference":
        return cls(
            derivation_version_id=value["derivation_version_id"], snapshot_id=value["snapshot_id"],
            derivation_fingerprint=value["derivation_fingerprint"], source_bundle_digest=value["source_bundle_digest"],
            provenance_bundle_digest=value["provenance_bundle_digest"],
        )


@dataclass(frozen=True)
class ChangedFileFact:
    file_path: str
    change_kind: str
    old_path: str | None
    new_path: str | None
    old_sha: str | None
    new_sha: str | None
    lines_added: int
    lines_deleted: int
    diff_hunk_refs: tuple[str, ...]
    source_provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_path", _text(self.file_path, "file_path"))
        object.__setattr__(self, "change_kind", _text(self.change_kind, "change_kind"))
        if self.change_kind not in CHANGE_KINDS:
            raise R32Error("R3_2_CHANGE_FACT_INVALID", f"unsupported change_kind: {self.change_kind}")
        for name in ("old_path", "new_path", "old_sha", "new_sha"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "lines_added", _int(self.lines_added, "lines_added"))
        object.__setattr__(self, "lines_deleted", _int(self.lines_deleted, "lines_deleted"))
        object.__setattr__(self, "diff_hunk_refs", _text_tuple(self.diff_hunk_refs, "diff_hunk_refs"))
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path, "change_kind": self.change_kind, "old_path": self.old_path,
            "new_path": self.new_path, "old_sha": self.old_sha, "new_sha": self.new_sha,
            "lines_added": self.lines_added, "lines_deleted": self.lines_deleted,
            "diff_hunk_refs": list(self.diff_hunk_refs), "source_provenance": list(self.source_provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangedFileFact":
        return cls(
            file_path=value["file_path"], change_kind=value["change_kind"], old_path=value.get("old_path"),
            new_path=value.get("new_path"), old_sha=value.get("old_sha"), new_sha=value.get("new_sha"),
            lines_added=value.get("lines_added", 0), lines_deleted=value.get("lines_deleted", 0),
            diff_hunk_refs=tuple(value.get("diff_hunk_refs") or ()), source_provenance=tuple(value.get("source_provenance") or ()),
        )


@dataclass(frozen=True)
class ChangedSymbolFact:
    symbol_id: str
    file_path: str
    symbol_kind: str
    change_kind: str
    old_signature: str | None
    new_signature: str | None
    line_refs: tuple[int, ...]
    source_provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("symbol_id", "file_path", "symbol_kind", "change_kind"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.change_kind not in CHANGE_KINDS:
            raise R32Error("R3_2_CHANGE_FACT_INVALID", f"unsupported symbol change_kind: {self.change_kind}")
        object.__setattr__(self, "old_signature", _optional_text(self.old_signature, "old_signature"))
        object.__setattr__(self, "new_signature", _optional_text(self.new_signature, "new_signature"))
        object.__setattr__(self, "line_refs", tuple(_int(item, "line_refs[]", minimum=1) for item in _array(self.line_refs, "line_refs")))
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id, "file_path": self.file_path, "symbol_kind": self.symbol_kind,
            "change_kind": self.change_kind, "old_signature": self.old_signature, "new_signature": self.new_signature,
            "line_refs": list(self.line_refs), "source_provenance": list(self.source_provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangedSymbolFact":
        return cls(
            symbol_id=value["symbol_id"], file_path=value["file_path"], symbol_kind=value["symbol_kind"],
            change_kind=value["change_kind"], old_signature=value.get("old_signature"), new_signature=value.get("new_signature"),
            line_refs=tuple(value.get("line_refs") or ()), source_provenance=tuple(value.get("source_provenance") or ()),
        )


@dataclass(frozen=True)
class ImpactEdge:
    from_node: str
    to_node: str
    edge_kind: str
    direction: str
    depth: int
    confidence: float
    provider_ref: str
    source_provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("from_node", "to_node", "edge_kind", "direction", "provider_ref"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "depth", _int(self.depth, "depth"))
        object.__setattr__(self, "confidence", _number(self.confidence, "confidence"))
        object.__setattr__(self, "source_provenance", _text_tuple(self.source_provenance, "source_provenance"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_node": self.from_node, "to_node": self.to_node, "edge_kind": self.edge_kind,
            "direction": self.direction, "depth": self.depth, "confidence": self.confidence,
            "provider_ref": self.provider_ref, "source_provenance": list(self.source_provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImpactEdge":
        return cls(
            from_node=value["from_node"], to_node=value["to_node"], edge_kind=value["edge_kind"],
            direction=value["direction"], depth=value.get("depth", 0), confidence=value.get("confidence", 0),
            provider_ref=value["provider_ref"], source_provenance=tuple(value.get("source_provenance") or ()),
        )


@dataclass(frozen=True)
class ImpactedSurface:
    surface_kind: str
    stable_surface_id: str
    relation: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface_kind", _text(self.surface_kind, "surface_kind"))
        if self.surface_kind not in SURFACE_KINDS:
            raise R32Error("R3_2_SURFACE_INVALID", f"unsupported surface_kind: {self.surface_kind}")
        object.__setattr__(self, "stable_surface_id", _text(self.stable_surface_id, "stable_surface_id"))
        object.__setattr__(self, "relation", _text(self.relation, "relation"))
        object.__setattr__(self, "confidence", _number(self.confidence, "confidence"))
        object.__setattr__(self, "evidence_refs", _text_tuple(self.evidence_refs, "evidence_refs"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_kind": self.surface_kind, "stable_surface_id": self.stable_surface_id,
            "relation": self.relation, "confidence": self.confidence, "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImpactedSurface":
        return cls(
            surface_kind=value["surface_kind"], stable_surface_id=value["stable_surface_id"],
            relation=value["relation"], confidence=value.get("confidence", 0), evidence_refs=tuple(value.get("evidence_refs") or ()),
        )


@dataclass(frozen=True)
class CodeIntelligenceEnvelope:
    compare_identity: CompareIdentity
    provider_id: str
    provider_version: str
    requested_capabilities: tuple[str, ...]
    resolved_capabilities: tuple[str, ...]
    code_intelligence_status: str
    provider_input_digest: str
    code_graph_digest: str | None
    changed_files: tuple[ChangedFileFact, ...]
    changed_symbols: tuple[ChangedSymbolFact, ...]
    impact_edges: tuple[ImpactEdge, ...]
    impacted_surfaces: tuple[ImpactedSurface, ...]
    warnings: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("provider_id", "provider_version", "provider_input_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "code_graph_digest", _optional_text(self.code_graph_digest, "code_graph_digest"))
        object.__setattr__(self, "requested_capabilities", _text_tuple(self.requested_capabilities, "requested_capabilities"))
        object.__setattr__(self, "resolved_capabilities", _text_tuple(self.resolved_capabilities, "resolved_capabilities"))
        object.__setattr__(self, "code_intelligence_status", _text(self.code_intelligence_status, "code_intelligence_status"))
        if self.code_intelligence_status not in CODE_INTELLIGENCE_STATUSES:
            raise R32Error("R3_2_PROVIDER_STATUS_INVALID", f"unsupported code_intelligence_status: {self.code_intelligence_status}")
        for name, cls in (("changed_files", ChangedFileFact), ("changed_symbols", ChangedSymbolFact), ("impact_edges", ImpactEdge), ("impacted_surfaces", ImpactedSurface)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must contain typed immutable values")
        object.__setattr__(self, "warnings", _text_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "source_refs", _text_tuple(self.source_refs, "source_refs"))
        if self.code_intelligence_status == "COMPLETE" and not set(self.resolved_capabilities).issuperset(self.requested_capabilities):
            raise R32Error("R3_2_PROVIDER_STATUS_INVALID", "COMPLETE provider must resolve every requested capability")
        if self.code_intelligence_status == "UNAVAILABLE" and self.resolved_capabilities:
            raise R32Error("R3_2_PROVIDER_STATUS_INVALID", "UNAVAILABLE provider cannot claim resolved capabilities")

    def to_dict(self) -> dict[str, Any]:
        return {
            "compare_identity": self.compare_identity.to_dict(), "provider_id": self.provider_id,
            "provider_version": self.provider_version, "requested_capabilities": list(self.requested_capabilities),
            "resolved_capabilities": list(self.resolved_capabilities), "code_intelligence_status": self.code_intelligence_status,
            "provider_input_digest": self.provider_input_digest, "code_graph_digest": self.code_graph_digest,
            "changed_files": [item.to_dict() for item in self.changed_files],
            "changed_symbols": [item.to_dict() for item in self.changed_symbols],
            "impact_edges": [item.to_dict() for item in self.impact_edges],
            "impacted_surfaces": [item.to_dict() for item in self.impacted_surfaces],
            "warnings": list(self.warnings), "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeIntelligenceEnvelope":
        return cls(
            compare_identity=CompareIdentity.from_dict(value["compare_identity"]),
            provider_id=value["provider_id"], provider_version=value["provider_version"],
            requested_capabilities=tuple(value.get("requested_capabilities") or ()),
            resolved_capabilities=tuple(value.get("resolved_capabilities") or ()),
            code_intelligence_status=value["code_intelligence_status"], provider_input_digest=value["provider_input_digest"],
            code_graph_digest=value.get("code_graph_digest"),
            changed_files=tuple(ChangedFileFact.from_dict(item) for item in value.get("changed_files") or ()),
            changed_symbols=tuple(ChangedSymbolFact.from_dict(item) for item in value.get("changed_symbols") or ()),
            impact_edges=tuple(ImpactEdge.from_dict(item) for item in value.get("impact_edges") or ()),
            impacted_surfaces=tuple(ImpactedSurface.from_dict(item) for item in value.get("impacted_surfaces") or ()),
            warnings=tuple(value.get("warnings") or ()), source_refs=tuple(value.get("source_refs") or ()),
        )


@dataclass(frozen=True)
class ChangeImpactIdentity:
    mission_id: str
    scope_identity: str
    compare_identity: CompareIdentity
    provider_id: str
    provider_version: str
    provider_input_digest: str
    code_graph_digest: str | None
    r3_1_reference: R31Reference
    policy_version: str
    untracked_policy: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "scope_identity", "provider_id", "provider_version", "provider_input_digest", "policy_version", "untracked_policy"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "code_graph_digest", _optional_text(self.code_graph_digest, "code_graph_digest"))
        if self.untracked_policy not in UNTRACKED_POLICIES:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", f"unsupported untracked_policy: {self.untracked_policy}")

    def to_identity_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "scope_identity": self.scope_identity,
            "compare_identity": self.compare_identity.to_dict(), "provider_id": self.provider_id,
            "provider_version": self.provider_version, "provider_input_digest": self.provider_input_digest,
            "code_graph_digest": self.code_graph_digest, "r3_1_reference": self.r3_1_reference.to_dict(),
            "policy_version": self.policy_version, "untracked_policy": self.untracked_policy,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_identity_dict(), "derivation_fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangeImpactIdentity":
        identity = cls(
            mission_id=value["mission_id"], scope_identity=value["scope_identity"],
            compare_identity=CompareIdentity.from_dict(value["compare_identity"]),
            provider_id=value["provider_id"], provider_version=value["provider_version"],
            provider_input_digest=value["provider_input_digest"], code_graph_digest=value.get("code_graph_digest"),
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]),
            policy_version=value["policy_version"], untracked_policy=value["untracked_policy"],
        )
        if value.get("derivation_fingerprint") not in (None, identity.fingerprint):
            raise R32Error("R3_2_FINGERPRINT_MISMATCH", "change-impact derivation fingerprint does not match identity")
        return identity


@dataclass(frozen=True)
class ChangeImpactObligation:
    change_obligation_id: str
    compare_identity: CompareIdentity
    trigger_fact_refs: tuple[str, ...]
    impacted_surface_refs: tuple[str, ...]
    affected_behavior: str
    risk_hint: str | None
    impact_resolution: str
    correlation_keys: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    obligation_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_obligation_id", _text(self.change_obligation_id, "change_obligation_id"))
        object.__setattr__(self, "trigger_fact_refs", _text_tuple(self.trigger_fact_refs, "trigger_fact_refs"))
        object.__setattr__(self, "impacted_surface_refs", _text_tuple(self.impacted_surface_refs, "impacted_surface_refs"))
        object.__setattr__(self, "affected_behavior", _text(self.affected_behavior, "affected_behavior"))
        object.__setattr__(self, "risk_hint", _optional_text(self.risk_hint, "risk_hint"))
        object.__setattr__(self, "impact_resolution", _text(self.impact_resolution, "impact_resolution"))
        if self.impact_resolution not in IMPACT_RESOLUTIONS:
            raise R32Error("R3_2_IMPACT_RESOLUTION_INVALID", f"unsupported impact_resolution: {self.impact_resolution}")
        object.__setattr__(self, "correlation_keys", _text_tuple(self.correlation_keys, "correlation_keys"))
        object.__setattr__(self, "provenance_refs", _text_tuple(self.provenance_refs, "provenance_refs"))
        object.__setattr__(self, "obligation_fingerprint", _text(self.obligation_fingerprint, "obligation_fingerprint"))

    def to_identity_dict(self) -> dict[str, Any]:
        return {
            "change_obligation_id": self.change_obligation_id,
            "compare_identity": self.compare_identity.to_dict(),
            "trigger_fact_refs": list(self.trigger_fact_refs),
            "impacted_surface_refs": list(self.impacted_surface_refs),
            "affected_behavior": self.affected_behavior,
            "risk_hint": self.risk_hint,
            "impact_resolution": self.impact_resolution,
            "correlation_keys": list(self.correlation_keys),
            "provenance_refs": list(self.provenance_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_identity_dict(), "obligation_fingerprint": self.obligation_fingerprint}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangeImpactObligation":
        return cls(
            change_obligation_id=value["change_obligation_id"], compare_identity=CompareIdentity.from_dict(value["compare_identity"]),
            trigger_fact_refs=tuple(value.get("trigger_fact_refs") or ()), impacted_surface_refs=tuple(value.get("impacted_surface_refs") or ()),
            affected_behavior=value["affected_behavior"], risk_hint=value.get("risk_hint"),
            impact_resolution=value["impact_resolution"], correlation_keys=tuple(value.get("correlation_keys") or ()),
            provenance_refs=tuple(value.get("provenance_refs") or ()), obligation_fingerprint=value["obligation_fingerprint"],
        )


@dataclass(frozen=True)
class ReconciliationItem:
    reconciliation_item_id: str
    semantic: str
    requirement_obligation_id: str | None
    change_obligation_id: str | None
    gap_kinds: tuple[str, ...]
    correlation_evidence: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "reconciliation_item_id", _text(self.reconciliation_item_id, "reconciliation_item_id"))
        object.__setattr__(self, "semantic", _text(self.semantic, "semantic"))
        if self.semantic not in RECONCILIATION_SEMANTICS:
            raise R32Error("R3_2_RECONCILIATION_INVALID", f"unsupported semantic: {self.semantic}")
        object.__setattr__(self, "requirement_obligation_id", _optional_text(self.requirement_obligation_id, "requirement_obligation_id"))
        object.__setattr__(self, "change_obligation_id", _optional_text(self.change_obligation_id, "change_obligation_id"))
        object.__setattr__(self, "gap_kinds", _text_tuple(self.gap_kinds, "gap_kinds"))
        if any(item not in RECONCILIATION_GAPS for item in self.gap_kinds):
            raise R32Error("R3_2_RECONCILIATION_INVALID", "unsupported reconciliation gap kind")
        object.__setattr__(self, "correlation_evidence", _text_tuple(self.correlation_evidence, "correlation_evidence"))
        object.__setattr__(self, "provenance_refs", _text_tuple(self.provenance_refs, "provenance_refs"))
        if self.semantic in {"OVERLAP", "REQUIREMENT_CODE_GAP"} and not self.requirement_obligation_id:
            raise R32Error("R3_2_RECONCILIATION_INVALID", "requirement-bearing semantic requires requirement identity")
        if self.semantic == "OVERLAP" and not self.change_obligation_id:
            raise R32Error("R3_2_RECONCILIATION_INVALID", "OVERLAP requires change identity")
        if self.semantic == "CHANGE_ONLY" and not self.change_obligation_id:
            raise R32Error("R3_2_RECONCILIATION_INVALID", "CHANGE_ONLY requires change identity")
        if self.semantic == "REQUIREMENT_ONLY" and not self.requirement_obligation_id:
            raise R32Error("R3_2_RECONCILIATION_INVALID", "REQUIREMENT_ONLY requires requirement identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_item_id": self.reconciliation_item_id, "semantic": self.semantic,
            "requirement_obligation_id": self.requirement_obligation_id, "change_obligation_id": self.change_obligation_id,
            "gap_kinds": list(self.gap_kinds), "correlation_evidence": list(self.correlation_evidence),
            "provenance_refs": list(self.provenance_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationItem":
        return cls(
            reconciliation_item_id=value["reconciliation_item_id"], semantic=value["semantic"],
            requirement_obligation_id=value.get("requirement_obligation_id"), change_obligation_id=value.get("change_obligation_id"),
            gap_kinds=tuple(value.get("gap_kinds") or ()), correlation_evidence=tuple(value.get("correlation_evidence") or ()),
            provenance_refs=tuple(value.get("provenance_refs") or ()),
        )


@dataclass(frozen=True)
class ReconciliationSnapshot:
    reconciliation_id: str
    derivation_fingerprint: str
    r3_1_reference: R31Reference
    items: tuple[ReconciliationItem, ...]
    counts_by_source: Mapping[str, int]
    counts_by_semantic: Mapping[str, int]
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("reconciliation_id", "derivation_fingerprint"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.items, tuple) or any(not isinstance(item, ReconciliationItem) for item in self.items):
            raise R32Error("R3_2_SCHEMA_INVALID", "reconciliation items must be an immutable typed tuple")
        object.__setattr__(self, "counts_by_source", {str(key): _int(value, f"counts_by_source.{key}") for key, value in _mapping(self.counts_by_source, "counts_by_source").items()})
        object.__setattr__(self, "counts_by_semantic", {str(key): _int(value, f"counts_by_semantic.{key}") for key, value in _mapping(self.counts_by_semantic, "counts_by_semantic").items()})
        object.__setattr__(self, "created_seq", _int(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", str(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_id": self.reconciliation_id, "derivation_fingerprint": self.derivation_fingerprint,
            "r3_1_reference": self.r3_1_reference.to_dict(), "items": [item.to_dict() for item in self.items],
            "counts_by_source": dict(self.counts_by_source), "counts_by_semantic": dict(self.counts_by_semantic),
            "created_seq": self.created_seq, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciliationSnapshot":
        return cls(
            reconciliation_id=value["reconciliation_id"], derivation_fingerprint=value["derivation_fingerprint"],
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]),
            items=tuple(ReconciliationItem.from_dict(item) for item in value.get("items") or ()),
            counts_by_source=value.get("counts_by_source") or {}, counts_by_semantic=value.get("counts_by_semantic") or {},
            created_seq=value.get("created_seq", 0), created_at=value.get("created_at", ""),
        )


@dataclass(frozen=True)
class ChangeImpactDerivation:
    derivation_version_id: str
    identity: ChangeImpactIdentity
    code_intelligence: CodeIntelligenceEnvelope
    change_obligations: tuple[ChangeImpactObligation, ...]
    r3_1_reference: R31Reference
    evidence_references: tuple[str, ...]
    correlation_id: str
    idempotency_key: str
    requested_by: Mapping[str, str]
    created_seq: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("derivation_version_id", "correlation_id", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.change_obligations, tuple) or any(not isinstance(item, ChangeImpactObligation) for item in self.change_obligations):
            raise R32Error("R3_2_SCHEMA_INVALID", "change_obligations must be an immutable typed tuple")
        object.__setattr__(self, "evidence_references", _text_tuple(self.evidence_references, "evidence_references"))
        if not self.evidence_references:
            raise R32Error("R3_2_EVIDENCE_REFERENCE_MISSING", "derivation evidence references must be non-empty")
        actor = _mapping(self.requested_by, "requested_by")
        object.__setattr__(self, "requested_by", {"type": _text(actor.get("type"), "requested_by.type"), "id": _text(actor.get("id"), "requested_by.id")})
        object.__setattr__(self, "created_seq", _int(self.created_seq, "created_seq"))
        object.__setattr__(self, "created_at", str(self.created_at))
        if self.identity.r3_1_reference != self.r3_1_reference:
            raise R32Error("R3_2_R31_REFERENCE_INVALID", "derivation identity and result R3.1 reference differ")
        if self.identity.compare_identity != self.code_intelligence.compare_identity:
            raise R32Error("R3_2_COMPARE_IDENTITY_INVALID", "derivation and provider compare identities differ")
        if self.identity.provider_id != self.code_intelligence.provider_id or self.identity.provider_version != self.code_intelligence.provider_version:
            raise R32Error("R3_2_PROVIDER_STATUS_INVALID", "derivation and provider identities differ")

    @property
    def derivation_fingerprint(self) -> str:
        return self.identity.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "derivation_version_id": self.derivation_version_id, "identity": self.identity.to_dict(),
            "derivation_fingerprint": self.derivation_fingerprint, "code_intelligence": self.code_intelligence.to_dict(),
            "change_obligations": [item.to_dict() for item in self.change_obligations],
            "r3_1_reference": self.r3_1_reference.to_dict(), "evidence_references": list(self.evidence_references),
            "correlation_id": self.correlation_id, "idempotency_key": self.idempotency_key,
            "requested_by": dict(self.requested_by), "created_seq": self.created_seq, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangeImpactDerivation":
        identity = ChangeImpactIdentity.from_dict(value["identity"])
        if value.get("derivation_fingerprint") not in (None, identity.fingerprint):
            raise R32Error("R3_2_FINGERPRINT_MISMATCH", "derivation fingerprint does not match identity")
        return cls(
            derivation_version_id=value["derivation_version_id"], identity=identity,
            code_intelligence=CodeIntelligenceEnvelope.from_dict(value["code_intelligence"]),
            change_obligations=tuple(ChangeImpactObligation.from_dict(item) for item in value.get("change_obligations") or ()),
            r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]),
            evidence_references=tuple(value.get("evidence_references") or ()), correlation_id=value["correlation_id"],
            idempotency_key=value["idempotency_key"], requested_by=value["requested_by"],
            created_seq=value.get("created_seq", 0), created_at=value.get("created_at", ""),
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
        object.__setattr__(self, "created_seq", _int(self.created_seq, "created_seq", minimum=1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reuse_id": self.reuse_id, "derivation_version_id": self.derivation_version_id,
            "derivation_fingerprint": self.derivation_fingerprint, "idempotency_key": self.idempotency_key,
            "created_seq": self.created_seq, "created_at": self.created_at, "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReuseReference":
        return cls(
            reuse_id=value["reuse_id"], derivation_version_id=value["derivation_version_id"],
            derivation_fingerprint=value["derivation_fingerprint"], idempotency_key=value["idempotency_key"],
            created_seq=value["created_seq"], created_at=value["created_at"], correlation_id=value["correlation_id"],
        )


@dataclass(frozen=True)
class R32State:
    mission_id: str
    derivations: tuple[ChangeImpactDerivation, ...] = ()
    reconciliations: tuple[ReconciliationSnapshot, ...] = ()
    reuses: tuple[ReuseReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        for name, cls in (("derivations", ChangeImpactDerivation), ("reconciliations", ReconciliationSnapshot), ("reuses", ReuseReference)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise R32Error("R3_2_SCHEMA_INVALID", f"{name} must be immutable typed tuples")
            ids = [getattr(item, next(iter(item.__dataclass_fields__))) for item in values]
            if len(ids) != len(set(ids)):
                raise R32Error("R3_2_IDENTITY_CONFLICT", f"{name} identities must be unique")

    def derivation(self, fingerprint: str) -> ChangeImpactDerivation | None:
        return next((item for item in self.derivations if item.derivation_fingerprint == fingerprint), None)

    def reconciliation(self, reconciliation_id: str) -> ReconciliationSnapshot | None:
        return next((item for item in self.reconciliations if item.reconciliation_id == reconciliation_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "derivations": [item.to_dict() for item in sorted(self.derivations, key=lambda value: value.derivation_version_id)],
            "reconciliations": [item.to_dict() for item in sorted(self.reconciliations, key=lambda value: value.reconciliation_id)],
            "reuses": [item.to_dict() for item in sorted(self.reuses, key=lambda value: value.reuse_id)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R32State":
        return cls(
            mission_id=value["mission_id"],
            derivations=tuple(ChangeImpactDerivation.from_dict(item) for item in value.get("derivations") or ()),
            reconciliations=tuple(ReconciliationSnapshot.from_dict(item) for item in value.get("reconciliations") or ()),
            reuses=tuple(ReuseReference.from_dict(item) for item in value.get("reuses") or ()),
        )


@dataclass(frozen=True)
class ChangeImpactRequest:
    mission_id: str
    scope_identity: str
    repository: RepositoryCompareRequest
    code_intelligence: Mapping[str, Any]
    r3_1_reference: R31Reference
    policy_version: str
    idempotency_key: str
    requested_by: Mapping[str, str]
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("mission_id", "scope_identity", "policy_version", "idempotency_key", "correlation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        intelligence = _mapping(self.code_intelligence, "code_intelligence")
        required = {"provider_id", "provider_version", "requested_capabilities", "provider_input_digest"}
        if set(intelligence) != required:
            raise R32Error("R3_2_SCHEMA_INVALID", "code_intelligence request contains unknown or missing fields")
        for name in ("provider_id", "provider_version", "provider_input_digest"):
            intelligence[name] = _text(intelligence[name], f"code_intelligence.{name}")
        intelligence["requested_capabilities"] = list(_text_tuple(intelligence["requested_capabilities"], "code_intelligence.requested_capabilities"))
        object.__setattr__(self, "code_intelligence", _freeze(intelligence))
        actor = _mapping(self.requested_by, "requested_by")
        object.__setattr__(self, "requested_by", {"type": _text(actor.get("type"), "requested_by.type"), "id": _text(actor.get("id"), "requested_by.id")})

    def to_payload(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "scope_identity": self.scope_identity,
            "repository": self.repository.to_dict(), "code_intelligence": dict(self.code_intelligence),
            "r3_1_reference": self.r3_1_reference.to_dict(), "policy_version": self.policy_version,
            "idempotency_key": self.idempotency_key, "requested_by": dict(self.requested_by),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, command_mission_id: str | None = None, correlation_id: str | None = None) -> "ChangeImpactRequest":
        value = _mapping(payload, "payload")
        required = {"mission_id", "scope_identity", "repository", "code_intelligence", "r3_1_reference", "policy_version", "idempotency_key", "requested_by"}
        if set(value) != required:
            raise R32Error("R3_2_SCHEMA_INVALID", "change-impact request contains unknown or missing fields")
        request = cls(
            mission_id=value["mission_id"], scope_identity=value["scope_identity"], repository=RepositoryCompareRequest.from_dict(value["repository"]),
            code_intelligence=value["code_intelligence"], r3_1_reference=R31Reference.from_dict(value["r3_1_reference"]),
            policy_version=value["policy_version"], idempotency_key=value["idempotency_key"], requested_by=value["requested_by"],
            correlation_id=correlation_id or value.get("idempotency_key"),
        )
        if command_mission_id is not None and request.mission_id != command_mission_id:
            raise R32Error("R3_2_MISSION_IDENTITY_MISMATCH", "payload mission_id differs from command mission_id")
        return request
