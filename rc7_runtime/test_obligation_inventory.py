"""Derive mandatory Test Design obligation sources from accepted parent artifacts.

RC7.1 expands the denominator beyond the original Requirement fields and
changed-symbol list. Preconditions/dependencies, changed files, reverse
requirement mappings and optional CodeGraph-derived impact surfaces now become
mandatory Test Design sources. The Test Designer cannot make them disappear by
self-authoring a smaller obligation set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadError, CandidatePayloadReader


class TestObligationInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MandatoryObligationSource:
    kind: str
    source_id: str
    parent_artifact_id: str


_REQUIREMENT_SOURCE_KINDS = (
    ("atomic_statements", "REQUIREMENT_ASSERTION"),
    ("business_rules", "BUSINESS_RULE"),
    ("preconditions", "PRECONDITION"),
    ("normal_paths", "POSITIVE_PATH"),
    ("negative_paths", "NEGATIVE_PATH"),
    ("boundaries", "BOUNDARY"),
    ("states", "STATE_TRANSITION"),
    ("roles", "ROLE_PERMISSION"),
    ("data_constraints", "DATA_CONDITION"),
    ("dependencies", "DEPENDENCY"),
    ("side_effects", "SIDE_EFFECT"),
)


class ParentDerivedTestObligationInventory:
    def __init__(self) -> None:
        self.reader = CandidatePayloadReader()

    def derive(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
        parent_artifact_refs: Sequence[str],
    ) -> Tuple[MandatoryObligationSource, ...]:
        sources: List[MandatoryObligationSource] = []
        seen = set()
        for artifact_id in parent_artifact_refs:
            rows = truth.query("rc7_artifact", artifact_id=artifact_id)
            if not rows:
                # External non-RC7 inputs may coexist with canonical parent refs.
                continue
            if len(rows) != 1:
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_ARTIFACT_NOT_UNIQUE:%s" % artifact_id)
            row = rows[0]
            if row.get("mission_id") != mission_id:
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_MISSION_MISMATCH:%s" % artifact_id)
            artifact_type = str(row.get("artifact_type_name") or "")
            if artifact_type not in {"REQUIREMENT_MODEL", "CODE_IMPACT_MODEL"}:
                continue
            try:
                candidate = self.reader.load(
                    truth,
                    artifact_id,
                    expected_mission_id=mission_id,
                )
            except CandidatePayloadError as exc:
                raise TestObligationInventoryError(
                    "TEST_DESIGN_PARENT_CANDIDATE_INVALID:%s:%s" % (artifact_id, exc)
                ) from exc
            payload = candidate.semantic_payload
            if artifact_type == "REQUIREMENT_MODEL":
                pairs = self._requirement_sources(payload, artifact_id)
            else:
                pairs = self._code_sources(payload, artifact_id)
            for item in pairs:
                identity = (item.kind, item.source_id, item.parent_artifact_id)
                if identity in seen:
                    continue
                seen.add(identity)
                sources.append(item)
        return tuple(sources)

    @staticmethod
    def missing_reasons(
        sources: Sequence[MandatoryObligationSource],
        raw_obligations: object,
    ) -> Tuple[str, ...]:
        if not sources:
            return ()
        if not isinstance(raw_obligations, list):
            return tuple(
                "SOURCE_OBLIGATION_MISSING:%s:%s" % (source.kind, source.source_id)
                for source in sources
            )
        represented = set()
        for raw in raw_obligations:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "").strip().upper()
            refs = raw.get("source_refs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, str) and ref.strip():
                    represented.add((kind, ref.strip()))
        missing = []
        for source in sources:
            if (source.kind, source.source_id) not in represented:
                missing.append("SOURCE_OBLIGATION_MISSING:%s:%s" % (source.kind, source.source_id))
        return tuple(missing)

    @staticmethod
    def _requirement_sources(
        payload: Mapping[str, object],
        artifact_id: str,
    ) -> Tuple[MandatoryObligationSource, ...]:
        result = []
        for field, kind in _REQUIREMENT_SOURCE_KINDS:
            values = payload.get(field, [])
            if values is None:
                values = []
            if not isinstance(values, list):
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_REQUIREMENT_FIELD_INVALID:%s" % field)
            for item in values:
                if not isinstance(item, dict):
                    raise TestObligationInventoryError("TEST_DESIGN_PARENT_REQUIREMENT_ITEM_INVALID:%s" % field)
                source_id = item.get("id")
                if not isinstance(source_id, str) or not source_id.strip():
                    raise TestObligationInventoryError("TEST_DESIGN_PARENT_REQUIREMENT_SOURCE_ID_REQUIRED:%s" % field)
                result.append(MandatoryObligationSource(kind, source_id.strip(), artifact_id))
        return tuple(result)

    @staticmethod
    def _code_sources(
        payload: Mapping[str, object],
        artifact_id: str,
    ) -> Tuple[MandatoryObligationSource, ...]:
        result: List[MandatoryObligationSource] = []

        changed = payload.get("changed_symbols", [])
        if changed is None:
            changed = []
        if not isinstance(changed, list):
            raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOLS_INVALID")
        for item in changed:
            if not isinstance(item, dict):
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOL_INVALID")
            source_id = item.get("id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOL_ID_REQUIRED")
            result.append(MandatoryObligationSource("CODE_IMPACT", source_id.strip(), artifact_id))

        # File-level changes are a separate regression surface. A changed file
        # may contain configuration/static/initializer effects not represented by
        # a method-level symbol inventory.
        changed_files = payload.get("changed_files", [])
        if changed_files is None:
            changed_files = []
        if not isinstance(changed_files, list):
            raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_FILES_INVALID")
        for path in changed_files:
            if not isinstance(path, str) or not path.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_FILE_INVALID")
            result.append(MandatoryObligationSource("CODE_IMPACT", "FILE:%s" % path.strip(), artifact_id))

        # Every requirement-to-symbol mapping creates an explicit regression
        # obligation. This stops one generic CODE_IMPACT case from claiming all
        # requirement regressions are covered.
        reverse = payload.get("reverse_requirement_mappings", [])
        if reverse is None:
            reverse = []
        if not isinstance(reverse, list):
            raise TestObligationInventoryError("TEST_DESIGN_PARENT_REVERSE_MAPPINGS_INVALID")
        for item in reverse:
            if not isinstance(item, dict):
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_REVERSE_MAPPING_INVALID")
            requirement_id = item.get("requirement_id")
            symbol_id = item.get("symbol_id")
            if not isinstance(requirement_id, str) or not requirement_id.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_REVERSE_REQUIREMENT_ID_REQUIRED")
            if not isinstance(symbol_id, str) or not symbol_id.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_REVERSE_SYMBOL_ID_REQUIRED")
            source_id = "REQMAP:%s:%s" % (requirement_id.strip(), symbol_id.strip())
            result.append(MandatoryObligationSource("REGRESSION", source_id, artifact_id))

        # RC7.1 Code workers may emit CodeGraph-expanded surfaces. They are
        # optional at schema level for backward compatibility, but once present
        # they become mandatory downstream coverage facts.
        surfaces = payload.get("impact_surfaces", [])
        if surfaces is None:
            surfaces = []
        if not isinstance(surfaces, list):
            raise TestObligationInventoryError("TEST_DESIGN_PARENT_IMPACT_SURFACES_INVALID")
        for item in surfaces:
            if not isinstance(item, dict):
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_IMPACT_SURFACE_INVALID")
            source_id = item.get("id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_IMPACT_SURFACE_ID_REQUIRED")
            result.append(MandatoryObligationSource("CODE_IMPACT", "SURFACE:%s" % source_id.strip(), artifact_id))

        return tuple(result)