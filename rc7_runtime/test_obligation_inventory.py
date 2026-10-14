"""Derive mandatory Test Design obligation sources from accepted parent artifacts.

A Test Designer is not allowed to choose its own coverage denominator. For a
normal RC7 Mission, TEST_DESIGN receives the accepted REQUIREMENT_MODEL and
CODE_IMPACT_MODEL as durable parent inputs. This module reloads those
runtime-hashed candidates and derives the source facts that must be represented
by Test Obligations before semantic coverage can be considered sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

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
    ("normal_paths", "POSITIVE_PATH"),
    ("negative_paths", "NEGATIVE_PATH"),
    ("boundaries", "BOUNDARY"),
    ("states", "STATE_TRANSITION"),
    ("roles", "ROLE_PERMISSION"),
    ("data_constraints", "DATA_CONDITION"),
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
        changed = payload.get("changed_symbols", [])
        if changed is None:
            changed = []
        if not isinstance(changed, list):
            raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOLS_INVALID")
        result = []
        for item in changed:
            if not isinstance(item, dict):
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOL_INVALID")
            source_id = item.get("id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise TestObligationInventoryError("TEST_DESIGN_PARENT_CHANGED_SYMBOL_ID_REQUIRED")
            result.append(MandatoryObligationSource("CODE_IMPACT", source_id.strip(), artifact_id))
        return tuple(result)
