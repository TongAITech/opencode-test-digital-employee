from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from aitest_runtime.durable_core import RuntimeError


EXECUTION_CONTEXT_SCHEMA_VERSION = 1
BUILDER_VERSION = 1
CANONICALIZATION_VERSION = 1


def _error(message: str) -> RuntimeError:
    return RuntimeError("EXECUTION_CONTEXT_SCHEMA_INVALID", message)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized.strip():
        raise _error(f"{name} must be a non-empty string")
    if normalized != normalized.strip():
        raise _error(f"{name} cannot contain leading or trailing whitespace")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _error(f"{name} must be valid Unicode") from exc
    return normalized


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _error(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _error(f"{name} must be a non-negative integer")
    return value


def freeze_json(value: Any, name: str = "value") -> Any:
    """Validate a JSON-like value, NFC-normalize it and make it deeply immutable."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        try:
            normalized.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _error(f"{name} contains invalid Unicode") from exc
        return normalized
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise _error(f"{name} contains a non-string object key")
            key = unicodedata.normalize("NFC", raw_key)
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise _error(f"{name} contains an invalid Unicode object key") from exc
            if key in frozen:
                raise _error(f"{name} contains duplicate keys after NFC normalization")
            frozen[key] = freeze_json(item, f"{name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item, f"{name}[{index}]") for index, item in enumerate(value))
    raise _error(f"{name} contains a non-JSON value of type {type(value).__name__}")


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        thaw_json(freeze_json(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class ContextTargetType(str, Enum):
    MISSION = "MISSION"
    PLAN = "PLAN"
    TASK = "TASK"


# Frozen contract terminology aliases.  The concrete implementation keeps
# the original R1.3A names as compatibility aliases for existing callers.
ContextScope = ContextTargetType
ContextSourceRef = Mapping[str, Any]
MaterializationProvenance = Mapping[str, Any]
ExecutionContextProvenance = Mapping[str, Any]


@dataclass(frozen=True, init=False)
class EventCursor:
    """Immutable, mission-bound Event stream cursor.

    ``EventCursor(seq)`` remains accepted as a compatibility shorthand for
    callers written against the first R1.3A draft.  New callers should pass
    ``mission_id`` and ``through_seq`` explicitly.
    """

    mission_id: str | None
    through_seq: int
    stream_schema_version: int

    def __init__(
        self,
        mission_id: str | int | None = None,
        through_seq: int | None = None,
        stream_schema_version: int = 1,
        *,
        seq: int | None = None,
    ) -> None:
        if seq is not None:
            if mission_id is not None or through_seq is not None:
                raise _error("cursor cannot combine seq with mission_id or through_seq")
            mission_id = None
            through_seq = seq
        elif isinstance(mission_id, int) and through_seq is None:
            # Legacy positional form: EventCursor(seq).
            through_seq = mission_id
            mission_id = None
        if mission_id is not None and not isinstance(mission_id, str):
            raise _error("cursor.mission_id must be a string when provided")
        if mission_id is not None:
            mission_id = _text(mission_id, "cursor.mission_id")
        if through_seq is None:
            raise _error("cursor.through_seq is required")
        through_seq = _non_negative_int(through_seq, "cursor.through_seq")
        stream_schema_version = _positive_int(stream_schema_version, "cursor.stream_schema_version")
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "through_seq", through_seq)
        object.__setattr__(self, "stream_schema_version", stream_schema_version)

    @property
    def seq(self) -> int:
        """Compatibility alias for the cursor's inclusive upper bound."""
        return self.through_seq

    def to_dict(self) -> dict[str, Any]:
        if self.mission_id is None and self.stream_schema_version == 1:
            return {"seq": self.through_seq}
        return {
            "mission_id": self.mission_id,
            "through_seq": self.through_seq,
            "stream_schema_version": self.stream_schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EventCursor:
        if not isinstance(value, Mapping):
            raise _error("cursor must be an object")
        if set(value) == {"seq"}:
            return cls(seq=value["seq"])
        if set(value) != {"mission_id", "through_seq", "stream_schema_version"}:
            raise _error("cursor must contain seq or mission_id, through_seq and stream_schema_version")
        return cls(
            mission_id=value["mission_id"],
            through_seq=value["through_seq"],
            stream_schema_version=value["stream_schema_version"],
        )


@dataclass(frozen=True, init=False)
class ContextTarget:
    target_type: ContextTargetType | str
    plan_id: str | None = None
    plan_revision_id: str | None = None
    task_id: str | None = None

    def __init__(
        self,
        target_type: ContextTargetType | str | None = None,
        plan_id: str | None = None,
        plan_revision_id: str | None = None,
        task_id: str | None = None,
        *,
        scope: ContextTargetType | str | None = None,
    ) -> None:
        if target_type is None:
            target_type = scope
        elif scope is not None:
            try:
                if ContextTargetType(target_type) != ContextTargetType(scope):
                    raise _error("target cannot specify conflicting target_type and scope")
            except ValueError as exc:
                raise _error("target.target_type must be MISSION, PLAN or TASK") from exc
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "plan_revision_id", plan_revision_id)
        object.__setattr__(self, "task_id", task_id)
        self.__post_init__()

    def __post_init__(self) -> None:
        try:
            target_type = ContextTargetType(self.target_type)
        except (TypeError, ValueError) as exc:
            raise _error("target.target_type must be MISSION, PLAN or TASK") from exc
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "plan_id", _optional_text(self.plan_id, "target.plan_id"))
        object.__setattr__(
            self,
            "plan_revision_id",
            _optional_text(self.plan_revision_id, "target.plan_revision_id"),
        )
        object.__setattr__(self, "task_id", _optional_text(self.task_id, "target.task_id"))
        if target_type == ContextTargetType.MISSION and any(
            item is not None for item in (self.plan_id, self.plan_revision_id, self.task_id)
        ):
            raise _error("MISSION target cannot contain Plan, Revision or Task identifiers")
        if target_type == ContextTargetType.PLAN:
            if self.plan_id is None:
                raise _error("PLAN target requires plan_id")
            if self.task_id is not None:
                raise _error("PLAN target cannot contain task_id")
        if target_type == ContextTargetType.TASK and self.task_id is None:
            raise _error("TASK target requires task_id")

    @property
    def kind(self) -> ContextTargetType:
        return self.target_type

    @property
    def scope(self) -> ContextTargetType:
        return self.target_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type.value,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextTarget:
        if not isinstance(value, Mapping):
            raise _error("target must be an object")
        allowed = {"target_type", "scope", "plan_id", "plan_revision_id", "task_id"}
        if set(value) - allowed or ("target_type" not in value and "scope" not in value):
            raise _error("target contains unknown or missing fields")
        return cls(
            value.get("target_type"),
            value.get("plan_id"),
            value.get("plan_revision_id"),
            value.get("task_id"),
            scope=value.get("scope"),
        )


@dataclass(frozen=True)
class KnowledgeRecordInput:
    knowledge_id: str
    version: str | int = 1
    status: str = "VERIFIED"
    scope: Mapping[str, Any] = field(default_factory=dict)
    content: Any = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    confidence: str | None = None
    subject: str | None = None
    predicate: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_id", _text(self.knowledge_id, "knowledge.knowledge_id"))
        version: str | int
        if isinstance(self.version, bool) or not isinstance(self.version, (str, int)):
            raise _error("knowledge.version must be a non-empty string or non-negative integer")
        if isinstance(self.version, int):
            version = _positive_int(self.version, "knowledge.version")
        else:
            version = _text(self.version, "knowledge.version")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "status", _text(self.status, "knowledge.status"))
        frozen_scope = freeze_json(self.scope, "knowledge.scope")
        if not isinstance(frozen_scope, Mapping):
            raise _error("knowledge.scope must be an object")
        for key, item in frozen_scope.items():
            if not isinstance(item, str) or not item.strip():
                raise _error(f"knowledge.scope.{key} must be a non-empty string")
        object.__setattr__(self, "scope", frozen_scope)
        object.__setattr__(self, "content", freeze_json(self.content, "knowledge.content"))
        frozen_metadata = freeze_json(self.metadata, "knowledge.metadata")
        if not isinstance(frozen_metadata, Mapping):
            raise _error("knowledge.metadata must be an object")
        object.__setattr__(self, "metadata", frozen_metadata)
        for name in (
            "confidence",
            "subject",
            "predicate",
            "source_type",
            "source_ref",
            "valid_from",
            "valid_to",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name), f"knowledge.{name}"))

    @property
    def record_id(self) -> str:
        return self.knowledge_id

    @property
    def provenance(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "confidence": self.confidence,
                "source_type": self.source_type,
                "source_ref": self.source_ref,
                "valid_from": self.valid_from,
                "valid_to": self.valid_to,
            }
        )

    def identity_key(self) -> str:
        return self.knowledge_id

    def sort_key(self) -> tuple[str, str]:
        return self.knowledge_id, canonical_json(self.version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "version": self.version,
            "status": self.status,
            "scope": thaw_json(self.scope),
            "content": thaw_json(self.content),
            "metadata": thaw_json(self.metadata),
            "confidence": self.confidence,
            "subject": self.subject,
            "predicate": self.predicate,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KnowledgeRecordInput:
        if not isinstance(value, Mapping):
            raise _error("knowledge record must be an object")
        allowed = {
            "knowledge_id",
            "version",
            "status",
            "scope",
            "content",
            "metadata",
            "confidence",
            "subject",
            "predicate",
            "source_type",
            "source_ref",
            "valid_from",
            "valid_to",
        }
        if set(value) - allowed or "knowledge_id" not in value or "content" not in value:
            raise _error("knowledge record contains unknown or missing fields")
        return cls(
            knowledge_id=value["knowledge_id"],
            version=value.get("version", 1),
            status=value.get("status", "VERIFIED"),
            scope=value["scope"] if "scope" in value else {},
            content=value["content"],
            metadata=value["metadata"] if "metadata" in value else {},
            confidence=value.get("confidence"),
            subject=value.get("subject"),
            predicate=value.get("predicate"),
            source_type=value.get("source_type"),
            source_ref=value.get("source_ref"),
            valid_from=value.get("valid_from"),
            valid_to=value.get("valid_to"),
        )


KnowledgeItemInput = KnowledgeRecordInput


@dataclass(frozen=True, init=False)
class KnowledgeSetInput:
    records: tuple[KnowledgeRecordInput, ...]

    def __init__(
        self,
        records: Sequence[KnowledgeRecordInput | Mapping[str, Any]] = (),
        *,
        items: Sequence[KnowledgeRecordInput | Mapping[str, Any]] | None = None,
        set_digest: str | None = None,
    ) -> None:
        if items is not None:
            if records not in ((), []) and tuple(records) != tuple(items):
                raise _error("knowledge_set cannot specify conflicting records and items")
            records = items
        if isinstance(records, (str, bytes, bytearray)) or not isinstance(records, Sequence):
            raise _error("knowledge_set.records must be an array")
        normalized = tuple(
            item if isinstance(item, KnowledgeRecordInput) else KnowledgeRecordInput.from_dict(item)
            for item in records
        )
        ordered = tuple(sorted(normalized, key=lambda item: item.sort_key()))
        identities = [item.identity_key() for item in ordered]
        if len(set(identities)) != len(identities):
            raise RuntimeError("KNOWLEDGE_DUPLICATE", "Knowledge records must have unique knowledge_id")
        if set_digest is not None:
            set_digest = _text(set_digest, "knowledge_set.set_digest")
            if len(set_digest) != 64 or any(character not in "0123456789abcdef" for character in set_digest):
                raise _error("knowledge_set.set_digest must be a lowercase SHA-256 digest")
        if set_digest is not None:
            calculated = canonical_sha256({"records": [item.to_dict() for item in ordered]})
            if set_digest != calculated:
                raise RuntimeError("KNOWLEDGE_DIGEST_MISMATCH", "Knowledge set digest does not match its records")
        object.__setattr__(self, "records", ordered)


    @property
    def items(self) -> tuple[KnowledgeRecordInput, ...]:
        return tuple(self.records)

    @property
    def digest(self) -> str:
        return canonical_sha256({"records": [item.to_dict() for item in self.records]})

    @property
    def set_digest(self) -> str:
        return self.digest

    def to_dict(self) -> dict[str, Any]:
        return {"records": [item.to_dict() for item in self.records], "set_digest": self.digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KnowledgeSetInput:
        if not isinstance(value, Mapping):
            raise _error("knowledge_set must be an object")
        allowed = {"records", "items", "set_digest"}
        if set(value) - allowed or ("records" not in value and "items" not in value):
            raise _error("knowledge_set must contain records or items")
        return cls(
            value.get("records", ()),
            items=value.get("items"),
            set_digest=value.get("set_digest"),
        )


@dataclass(frozen=True)
class BuildExecutionContextRequest:
    execution_attempt_id: str
    mission_id: str
    cursor: EventCursor
    target: ContextTarget
    knowledge_set: KnowledgeSetInput
    policy_id: str
    policy_version: int
    knowledge_scope: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_attempt_id",
            _text(self.execution_attempt_id, "execution_attempt_id"),
        )
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor):
            raise _error("cursor must be an EventCursor")
        if not isinstance(self.target, ContextTarget):
            raise _error("target must be a ContextTarget")
        if not isinstance(self.knowledge_set, KnowledgeSetInput):
            raise _error("knowledge_set must be a KnowledgeSetInput")
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "policy_version", _positive_int(self.policy_version, "policy_version"))
        frozen_scope = freeze_json(self.knowledge_scope, "knowledge_scope")
        if not isinstance(frozen_scope, Mapping):
            raise _error("knowledge_scope must be an object")
        object.__setattr__(self, "knowledge_scope", frozen_scope)

    @property
    def event_cursor(self) -> EventCursor:
        return self.cursor

    @property
    def attempt_id(self) -> str:
        return self.execution_attempt_id

    @property
    def mission(self) -> str:
        return self.mission_id

    @property
    def frozen_knowledge_set(self) -> KnowledgeSetInput:
        return self.knowledge_set

    @property
    def context_target(self) -> ContextTarget:
        return self.target

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_attempt_id": self.execution_attempt_id,
            "mission_id": self.mission_id,
            "cursor": self.cursor.to_dict(),
            "target": self.target.to_dict(),
            "knowledge_set": self.knowledge_set.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "knowledge_scope": thaw_json(self.knowledge_scope),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BuildExecutionContextRequest:
        if not isinstance(value, Mapping):
            raise _error("build request must be an object")
        required = {
            "execution_attempt_id",
            "mission_id",
            "cursor",
            "target",
            "knowledge_set",
            "policy_id",
            "policy_version",
        }
        allowed = required | {"knowledge_scope"}
        if set(value) - allowed or not required.issubset(value):
            raise _error("build request contains unknown or missing fields")
        return cls(
            execution_attempt_id=value["execution_attempt_id"],
            mission_id=value["mission_id"],
            cursor=EventCursor.from_dict(value["cursor"]),
            target=ContextTarget.from_dict(value["target"]),
            knowledge_set=KnowledgeSetInput.from_dict(value["knowledge_set"]),
            policy_id=value["policy_id"],
            policy_version=value["policy_version"],
            knowledge_scope=value.get("knowledge_scope", {}),
        )


@dataclass(frozen=True)
class ExecutionContextItem:
    item_type: str
    item_id: str
    required: bool
    value: Any
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_type", _text(self.item_type, "item.item_type"))
        object.__setattr__(self, "item_id", _text(self.item_id, "item.item_id"))
        if not isinstance(self.required, bool):
            raise _error("item.required must be a boolean")
        object.__setattr__(self, "value", freeze_json(self.value, "item.value"))
        object.__setattr__(self, "size_bytes", _non_negative_int(self.size_bytes, "item.size_bytes"))
        if len(canonical_bytes(self.semantic_dict())) != self.size_bytes:
            raise _error("item.size_bytes does not match canonical item size")

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "item_type": self.item_type,
            "item_id": self.item_id,
            "required": self.required,
            "value": thaw_json(self.value),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.semantic_dict(), "size_bytes": self.size_bytes}


@dataclass(frozen=True)
class ExecutionContextSection:
    name: str
    items: tuple[ExecutionContextItem, ...]
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "section.name"))
        if not isinstance(self.items, tuple) or any(not isinstance(item, ExecutionContextItem) for item in self.items):
            raise _error("section.items must be an immutable tuple of ExecutionContextItem values")
        object.__setattr__(self, "size_bytes", _non_negative_int(self.size_bytes, "section.size_bytes"))
        if sum(item.size_bytes for item in self.items) != self.size_bytes:
            raise _error("section.size_bytes must equal the sum of item sizes")

    def semantic_dict(self) -> dict[str, Any]:
        return {"name": self.name, "items": [item.semantic_dict() for item in self.items]}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "items": [item.to_dict() for item in self.items],
            "item_count": len(self.items),
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class OmissionSummary:
    total_count: int
    counts_by_reason: Mapping[str, int]
    samples: tuple[Mapping[str, Any], ...]
    digest: str
    counts_by_section: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_count", _non_negative_int(self.total_count, "omissions.total_count"))
        frozen_counts = freeze_json(self.counts_by_reason, "omissions.counts_by_reason")
        if not isinstance(frozen_counts, Mapping) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in frozen_counts.values()
        ):
            raise _error("omission counts must be non-negative integers")
        object.__setattr__(self, "counts_by_reason", frozen_counts)
        frozen_sections = freeze_json(self.counts_by_section, "omissions.counts_by_section")
        if not isinstance(frozen_sections, Mapping) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in frozen_sections.values()
        ):
            raise _error("omission section counts must be non-negative integers")
        object.__setattr__(self, "counts_by_section", frozen_sections)
        frozen_samples = freeze_json(self.samples, "omissions.samples")
        if not isinstance(frozen_samples, tuple) or any(not isinstance(item, Mapping) for item in frozen_samples):
            raise _error("omission samples must be an array of objects")
        object.__setattr__(self, "samples", frozen_samples)
        digest = _text(self.digest, "omissions.digest")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise _error("omissions.digest must be a lowercase SHA-256 digest")
        object.__setattr__(self, "digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "counts_by_reason": thaw_json(self.counts_by_reason),
            "counts_by_section": thaw_json(self.counts_by_section),
            "samples": thaw_json(self.samples),
            "digest": self.digest,
        }


@dataclass(frozen=True)
class ExecutionContext:
    execution_attempt_id: str
    mission_id: str
    cursor: EventCursor
    resolved_target: ContextTarget
    policy_id: str
    policy_version: int
    knowledge_set_digest: str
    sections: tuple[ExecutionContextSection, ...]
    omissions: OmissionSummary
    semantic_provenance: tuple[Mapping[str, Any], ...]
    materialization_provenance: Mapping[str, Any]
    semantic_digest: str
    metadata_bytes: int
    total_bytes: int
    knowledge_scope: Mapping[str, Any] = field(default_factory=dict)
    execution_context_schema_version: int = EXECUTION_CONTEXT_SCHEMA_VERSION
    builder_version: int = BUILDER_VERSION
    canonicalization_version: int = CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_attempt_id", _text(self.execution_attempt_id, "execution_attempt_id"))
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.cursor, EventCursor) or not isinstance(self.resolved_target, ContextTarget):
            raise _error("ExecutionContext cursor and resolved_target have invalid types")
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "policy_version", _positive_int(self.policy_version, "policy_version"))
        for name in (
            "execution_context_schema_version",
            "builder_version",
            "canonicalization_version",
        ):
            if getattr(self, name) != 1:
                raise _error(f"{name} must be 1")
        digest = _text(self.knowledge_set_digest, "knowledge_set_digest")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise _error("knowledge_set_digest must be a lowercase SHA-256 digest")
        object.__setattr__(self, "knowledge_set_digest", digest)
        if not isinstance(self.sections, tuple) or any(
            not isinstance(item, ExecutionContextSection) for item in self.sections
        ):
            raise _error("sections must be an immutable tuple")
        if tuple(item.name for item in self.sections) != ("execution", "runtime", "work_graph", "knowledge"):
            raise _error("sections must use the frozen R1.3A order")
        if not isinstance(self.omissions, OmissionSummary):
            raise _error("omissions must be an OmissionSummary")
        provenance = freeze_json(self.semantic_provenance, "semantic_provenance")
        if not isinstance(provenance, tuple) or any(not isinstance(item, Mapping) for item in provenance):
            raise _error("semantic_provenance must be an array of objects")
        object.__setattr__(self, "semantic_provenance", provenance)
        materialization = freeze_json(self.materialization_provenance, "materialization_provenance")
        if not isinstance(materialization, Mapping):
            raise _error("materialization_provenance must be an object")
        object.__setattr__(self, "materialization_provenance", materialization)
        semantic_digest = _text(self.semantic_digest, "semantic_digest")
        if len(semantic_digest) != 64 or any(character not in "0123456789abcdef" for character in semantic_digest):
            raise _error("semantic_digest must be a lowercase SHA-256 digest")
        object.__setattr__(self, "semantic_digest", semantic_digest)
        object.__setattr__(self, "metadata_bytes", _non_negative_int(self.metadata_bytes, "metadata_bytes"))
        object.__setattr__(self, "total_bytes", _non_negative_int(self.total_bytes, "total_bytes"))
        frozen_scope = freeze_json(self.knowledge_scope, "knowledge_scope")
        if not isinstance(frozen_scope, Mapping):
            raise _error("knowledge_scope must be an object")
        object.__setattr__(self, "knowledge_scope", frozen_scope)
        if self.total_bytes != self.metadata_bytes + sum(section.size_bytes for section in self.sections):
            raise _error("total_bytes must equal metadata bytes plus section item bytes")
        if canonical_sha256(self.semantic_dict()) != self.semantic_digest:
            raise _error("semantic_digest does not match the semantic Context")
        if len(canonical_bytes(self.metadata_dict())) != self.metadata_bytes:
            raise _error("metadata_bytes does not match canonical metadata size")

    @property
    def target(self) -> ContextTarget:
        return self.resolved_target

    @property
    def digest(self) -> str:
        return self.semantic_digest

    def section(self, name: str) -> ExecutionContextSection | None:
        return next((item for item in self.sections if item.name == name), None)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "execution_context_schema_version": self.execution_context_schema_version,
            "builder_version": self.builder_version,
            "canonicalization_version": self.canonicalization_version,
            "execution_attempt_id": self.execution_attempt_id,
            "mission_id": self.mission_id,
            "cursor": self.cursor.to_dict(),
            "resolved_target": self.resolved_target.to_dict(),
            "policy": {"policy_id": self.policy_id, "policy_version": self.policy_version},
            "knowledge_set_digest": self.knowledge_set_digest,
            "knowledge_scope": thaw_json(self.knowledge_scope),
            "sections": [section.semantic_dict() for section in self.sections],
            "semantic_provenance": thaw_json(self.semantic_provenance),
            "omissions": self.omissions.to_dict(),
        }

    def metadata_dict(self) -> dict[str, Any]:
        value = self.semantic_dict()
        value.pop("sections")
        value["materialization_provenance"] = thaw_json(self.materialization_provenance)
        value["semantic_digest"] = self.semantic_digest
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_context_schema_version": self.execution_context_schema_version,
            "builder_version": self.builder_version,
            "canonicalization_version": self.canonicalization_version,
            "execution_attempt_id": self.execution_attempt_id,
            "mission_id": self.mission_id,
            "cursor": self.cursor.to_dict(),
            "resolved_target": self.resolved_target.to_dict(),
            "policy": {"policy_id": self.policy_id, "policy_version": self.policy_version},
            "knowledge_set_digest": self.knowledge_set_digest,
            "knowledge_scope": thaw_json(self.knowledge_scope),
            "sections": [section.to_dict() for section in self.sections],
            "omissions": self.omissions.to_dict(),
            "provenance": {
                "semantic": thaw_json(self.semantic_provenance),
                "materialization": thaw_json(self.materialization_provenance),
            },
            "semantic_digest": self.semantic_digest,
            "metadata_bytes": self.metadata_bytes,
            "total_bytes": self.total_bytes,
        }


# Public contract names; aliases keep the serialized schema and implementation
# identity stable while exposing the frozen vocabulary.
ContextItem = ExecutionContextItem
ContextSection = ExecutionContextSection
OmissionSample = Mapping[str, Any]
OmissionReport = OmissionSummary
