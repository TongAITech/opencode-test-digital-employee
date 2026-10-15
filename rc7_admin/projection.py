"""Read-model/query layer for the RC7 administration platform.

The administration UI never owns business truth. Every read is rebuilt from the
append-only R1 event stream, and controlled test-case edits append a new
TEST_CASE_UPSERTED version instead of mutating projection state.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

install_rc7_truth_overlay()


class AdminProjectionError(RuntimeError):
    pass


RESOURCE_TYPES = {
    "missions": "rc7_mission",
    "tasks": "rc7_task",
    "gaps": "rc7_gap",
    "evidence": "rc7_evidence",
    "defects": "rc7_defect",
    "evaluations": "rc7_evaluation",
    "artifacts": "rc7_artifact",
    "requirements": "requirement_analysis",
    "code-impacts": "code_analysis",
    "test-cases": "test_case",
    "executions": "execution_attempt",
    "reports": "report",
}

IDENTITY_FIELDS = {
    "missions": "mission_id",
    "tasks": "task_id",
    "gaps": "gap_id",
    "evidence": "evidence_id",
    "defects": "defect_id",
    "evaluations": "evaluation_id",
    "artifacts": "artifact_id",
    "requirements": "id",
    "code-impacts": "id",
    "test-cases": "tc_id",
    "executions": "attempt_id",
    "reports": "id",
}

FILTER_ALIASES = {
    "version": ("release_id", "version", "source_revision", "release"),
    "requirement": ("requirement_id", "requirement", "requirement_ref", "requirement_refs"),
    "sst": ("sst_id", "sst", "sst_ids", "source_sst", "source_ssts"),
    "status": ("state", "status", "result", "test_result", "sufficiency_state"),
    "node": ("node", "source_node", "target_node"),
    "risk": ("risk", "severity"),
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _walk_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield child
            for nested in _walk_values(child):
                yield nested
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield child
            for nested in _walk_values(child):
                yield nested


def _contains(value: Any, needle: str) -> bool:
    target = needle.casefold().strip()
    if not target:
        return True
    if target in _text(value).casefold():
        return True
    return any(target in _text(item).casefold() for item in _walk_values(value))


def _field_values(row: Mapping[str, Any], keys: Iterable[str]) -> List[Any]:
    found = []
    for key in keys:
        if key in row:
            found.append(row.get(key))
    return found


class AdminProjection:
    """Live paginated projection over R1. No shadow database is permitted."""

    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def refresh(self) -> None:
        self.truth.rebuild_projection()

    def inventory(self) -> Dict[str, int]:
        self.refresh()
        result = {}
        for resource, artifact_type in RESOURCE_TYPES.items():
            try:
                result[resource] = len(self.truth.query(artifact_type))
            except Exception:
                result[resource] = 0
        return result

    def list_resource(
        self,
        resource: str,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        artifact_type = self._artifact_type(resource)
        if page < 1:
            raise AdminProjectionError("PAGE_MUST_BE_POSITIVE")
        if page_size < 1 or page_size > 200:
            raise AdminProjectionError("PAGE_SIZE_OUT_OF_RANGE")
        self.refresh()
        rows = self.truth.query(artifact_type)
        active = {key: value for key, value in dict(filters or {}).items() if value not in (None, "")}
        matched = [row for row in rows if self._matches(row, active)]
        matched.sort(key=self._sort_key, reverse=True)
        total = len(matched)
        start = (page - 1) * page_size
        return {
            "items": deepcopy(matched[start:start + page_size]),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
            "resource": resource,
        }

    def get_resource(self, resource: str, entity_id: str) -> Dict[str, Any]:
        self.refresh()
        identity = IDENTITY_FIELDS.get(resource)
        if identity is None:
            raise AdminProjectionError("UNKNOWN_RESOURCE")
        rows = self.truth.query(self._artifact_type(resource), **{identity: entity_id})
        if not rows:
            raise AdminProjectionError("ENTITY_NOT_FOUND")
        return deepcopy(rows[0])

    def mission_overview(self, mission_id: str) -> Dict[str, Any]:
        self.refresh()
        mission_rows = self.truth.query("rc7_mission", mission_id=mission_id)
        if not mission_rows:
            raise AdminProjectionError("MISSION_NOT_FOUND")
        related = {}
        for name, artifact_type in RESOURCE_TYPES.items():
            if name in {"requirements", "code-impacts", "test-cases", "executions", "reports"}:
                continue
            try:
                related[name] = self.truth.query(artifact_type, mission_id=mission_id)
            except Exception:
                related[name] = []
        return {"mission": deepcopy(mission_rows[0]), "related": deepcopy(related)}

    def append_test_case_revision(self, tc_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Append a new canonical test-case version; never mutate the current row."""
        self.refresh()
        existing = self.truth.query("test_case", tc_id=tc_id)
        if not existing:
            raise AdminProjectionError("TEST_CASE_NOT_FOUND")
        current = existing[0]
        candidate = deepcopy(dict(payload))
        if candidate.get("tc_id") != tc_id:
            raise AdminProjectionError("TEST_CASE_ID_IMMUTABLE")
        current_version = int(current.get("case_version", 0))
        if candidate.get("case_version") != current_version + 1:
            raise AdminProjectionError("TEST_CASE_VERSION_MUST_INCREMENT_BY_ONE")
        if current.get("release_id") is not None and candidate.get("release_id") != current.get("release_id"):
            raise AdminProjectionError("TEST_CASE_RELEASE_ID_IMMUTABLE")
        receipt = self.truth.append_atomic("TEST_CASE_UPSERTED", candidate)
        self.refresh()
        row = self.truth.query("test_case", tc_id=tc_id)[0]
        return {
            "status": "REVISION_APPENDED",
            "event_id": receipt.event_id,
            "seq": receipt.seq,
            "case": deepcopy(row),
        }

    def _artifact_type(self, resource: str) -> str:
        try:
            return RESOURCE_TYPES[resource]
        except KeyError as exc:
            raise AdminProjectionError("UNKNOWN_RESOURCE") from exc

    @staticmethod
    def _sort_key(row: Mapping[str, Any]) -> Any:
        return (
            int(row.get("updated_at") or row.get("created_at") or 0),
            int(row.get("artifact_version") or row.get("case_version") or 0),
            _text(row),
        )

    @staticmethod
    def _matches(row: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
        for key, value in filters.items():
            needle = str(value).strip()
            if not needle:
                continue
            if key in {"q", "search"}:
                if not _contains(row, needle):
                    return False
                continue
            aliases = FILTER_ALIASES.get(key, (key,))
            values = _field_values(row, aliases)
            if values:
                if not any(_contains(item, needle) for item in values):
                    return False
            elif not _contains(row, needle):
                return False
        return True
