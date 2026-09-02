from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef

from .contracts import (
    ActiveWriterState,
    ContentRelation,
    LegacySourceObservationInput,
    LegacySourceAdapter,
    SourceAvailability,
    SourceFamily,
    SourceFreshness,
    SourceSelector,
    SourceValueState,
)
from .errors import R47_SCHEMA_INVALID, R47Error


def _read(reader: Any, selector: SourceSelector) -> Mapping[str, Any]:
    """Read one bounded object through an injected, read-only surface."""
    if reader is None:
        return {}
    if isinstance(reader, Mapping):
        value = reader.get(selector.source_object_identity or selector.native_id or selector.source_system_id, {})
        return dict(value) if isinstance(value, Mapping) else {"value": value}
    method = getattr(reader, "read", None)
    if callable(method):
        value = method(selector)
        if isinstance(value, Mapping):
            return dict(value)
    raise R47Error(R47_SCHEMA_INVALID, "legacy adapter reader must expose a bounded read surface")


class _BaseLegacyAdapter:
    adapter_id = "r4.7.legacy.base"
    source_families = frozenset({SourceFamily.UNKNOWN})

    def __init__(self, reader: Any = None) -> None:
        self.reader = reader

    def can_read(self, selector: SourceSelector) -> bool:
        return selector.source_family in self.source_families

    def observe(self, selector: SourceSelector, *, owner_mission_id: str, actor: ActorRef, correlation_id: str, causation_id: str) -> LegacySourceObservationInput:
        if not self.can_read(selector):
            raise R47Error(R47_SCHEMA_INVALID, "adapter cannot read the selected source family")
        raw = dict(_read(self.reader, selector))
        normalized = raw.get("normalized_observation", raw.get("normalized", raw))
        if not isinstance(normalized, Mapping):
            normalized = {"value": normalized}
        source_scope = raw.get("source_scope", selector.source_scope)
        return LegacySourceObservationInput(
            source_family=selector.source_family,
            source_system_id=selector.source_system_id,
            adapter_id=self.adapter_id,
            source_object_identity=selector.source_object_identity,
            source_location=selector.source_location,
            native_id=selector.native_id,
            native_revision=raw.get("native_revision", selector.native_revision),
            native_revision_state=raw.get("native_revision_state", SourceValueState.KNOWN if raw.get("native_revision") else SourceValueState.UNKNOWN),
            native_source_digest=raw.get("native_source_digest"),
            native_source_digest_state=raw.get("native_source_digest_state", SourceValueState.KNOWN if raw.get("native_source_digest") else SourceValueState.UNKNOWN),
            native_content_relation=raw.get("native_content_relation", ContentRelation.UNKNOWN),
            source_scope=source_scope if isinstance(source_scope, Mapping) else {},
            observed_at=str(raw.get("observed_at", "adapter-observation")),
            source_cursor=raw.get("source_cursor", selector.source_cursor),
            source_cursor_state=raw.get("source_cursor_state", SourceValueState.KNOWN if raw.get("source_cursor", selector.source_cursor) is not None else SourceValueState.UNKNOWN),
            availability=raw.get("availability", SourceAvailability.AVAILABLE),
            freshness=raw.get("freshness", SourceFreshness.UNKNOWN),
            active_writer_state=raw.get("active_writer_state", ActiveWriterState.UNKNOWN),
            writer_authority=raw.get("writer_authority"),
            raw_status=raw.get("raw_status", raw.get("status")),
            raw_version=raw.get("raw_version", raw.get("version")),
            raw_provenance={"adapter_id": self.adapter_id, "actor": actor.to_dict(), "correlation_id": correlation_id, "causation_id": causation_id, "reader": "injected_read_only_surface"},
            normalized_observation=dict(normalized),
            bounded_payload_ref=raw.get("bounded_payload_ref"),
            observation_schema_version=int(raw.get("observation_schema_version", 1)),
            previous_observation_ref=raw.get("previous_observation_ref"),
            supersedes_observation_ref=raw.get("supersedes_observation_ref"),
        )


class LegacyKnowledgeTeachingAdapter(_BaseLegacyAdapter):
    adapter_id = "r4.7.legacy.knowledge-teaching"
    source_families = frozenset({SourceFamily.LEGACY_KNOWLEDGE, SourceFamily.LEGACY_TEACHING})


class LegacySkillMetadataAdapter(_BaseLegacyAdapter):
    adapter_id = "r4.7.legacy.skill-metadata"
    source_families = frozenset({SourceFamily.LEGACY_SKILL_METADATA})


class LegacyProjectTruthAdapter(_BaseLegacyAdapter):
    adapter_id = "r4.7.legacy.project-truth"
    source_families = frozenset({SourceFamily.LEGACY_PROJECT_TRUTH})


class LegacyRuntimeQualityAdapter(_BaseLegacyAdapter):
    adapter_id = "r4.7.legacy.runtime-quality"
    source_families = frozenset({SourceFamily.LEGACY_RUNTIME_STATE, SourceFamily.LEGACY_DEFECT, SourceFamily.LEGACY_TEST_STATE, SourceFamily.LEGACY_CAMPAIGN_OR_SCHEDULER})


class LegacyArtifactReferenceAdapter(_BaseLegacyAdapter):
    adapter_id = "r4.7.legacy.artifact-reference"
    source_families = frozenset({SourceFamily.LEGACY_ARTIFACT, SourceFamily.LEGACY_MIGRATION_REPORT, SourceFamily.LEGACY_LOCAL_CACHE, SourceFamily.LEGACY_BROWSER_OR_TRACE, SourceFamily.LEGACY_REFERENCE_FILE})


__all__ = [
    "LegacySourceAdapter",
    "LegacyKnowledgeTeachingAdapter",
    "LegacySkillMetadataAdapter",
    "LegacyProjectTruthAdapter",
    "LegacyRuntimeQualityAdapter",
    "LegacyArtifactReferenceAdapter",
]
