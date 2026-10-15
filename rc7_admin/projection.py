"""R1-backed read/write projection for the RC7 administration platform."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

install_rc7_truth_overlay()


class AdminProjectionError(RuntimeError):
    pass


RESOURCE_TYPES = {
    "missions": "rc7_mission", "tasks": "rc7_task", "gaps": "rc7_gap",
    "evidence": "rc7_evidence", "defects": "rc7_defect", "evaluations": "rc7_evaluation",
    "artifacts": "rc7_artifact", "requirements": "requirement_analysis",
    "code-impacts": "code_analysis", "test-cases": "test_case",
    "executions": "execution_attempt", "reports": "report",
}
IDENTITY_FIELDS = {
    "missions": "mission_id", "tasks": "task_id", "gaps": "gap_id",
    "evidence": "evidence_id", "defects": "defect_id", "evaluations": "evaluation_id",
    "artifacts": "artifact_id", "requirements": "id", "code-impacts": "id",
    "test-cases": "tc_id", "executions": "attempt_id", "reports": "id",
}
FILTER_ALIASES = {
    "version": ("release_id", "version", "release"),
    "requirement": ("requirement_id", "requirement", "requirement_ref", "requirement_refs"),
    "sst": ("sst_id", "sst", "sst_ids", "source_sst", "source_ssts"),
    "status": ("state", "status", "result", "test_result", "sufficiency_state"),
    "node": ("node", "source_node", "target_node"),
    "risk": ("risk", "severity"),
    "source_revision": ("source_revision", "source_revision_set", "revision_ref", "revision_refs", "fix_revision"),
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
    return (not target) or target in _text(value).casefold() or any(
        target in _text(item).casefold() for item in _walk_values(value)
    )


def _parse_time(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError as exc:
        raise AdminProjectionError("INVALID_TIME_FILTER") from exc


def _row_time(row: Mapping[str, Any]) -> int:
    for key in ("updated_at", "created_at", "captured_at"):
        value = row.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


class AdminProjection:
    """Live projection. UI state is never a second business truth store."""
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

    def list_resource(self, resource: str, *, page: int = 1, page_size: int = 20,
                      filters: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        self.refresh()
        return self.paginate_rows(resource, self.truth.query(self._artifact_type(resource)),
                                  page=page, page_size=page_size, filters=filters)

    def paginate_rows(self, resource: str, rows: Sequence[Mapping[str, Any]], *, page: int = 1,
                      page_size: int = 20, filters: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        if page < 1:
            raise AdminProjectionError("PAGE_MUST_BE_POSITIVE")
        if page_size < 1 or page_size > 200:
            raise AdminProjectionError("PAGE_SIZE_OUT_OF_RANGE")
        active = {k: v for k, v in dict(filters or {}).items() if v not in (None, "")}
        matched = [dict(row) for row in rows if self._matches(row, active)]
        matched.sort(key=self._sort_key, reverse=True)
        total = len(matched)
        start = (page - 1) * page_size
        return {"items": deepcopy(matched[start:start + page_size]), "total": total,
                "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size if total else 0,
                "resource": resource}

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
        rows = self.truth.query("rc7_mission", mission_id=mission_id)
        if not rows:
            raise AdminProjectionError("MISSION_NOT_FOUND")
        related = {}
        for name, artifact_type in RESOURCE_TYPES.items():
            try:
                related[name] = self.truth.query(artifact_type, mission_id=mission_id)
            except Exception:
                related[name] = []
        return {"mission": deepcopy(rows[0]), "related": deepcopy(related)}

    def create_test_case(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        candidate = deepcopy(dict(payload))
        tc_id = str(candidate.get("tc_id") or "")
        if not tc_id:
            raise AdminProjectionError("TEST_CASE_ID_REQUIRED")
        self.refresh()
        if self.truth.query("test_case", tc_id=tc_id):
            raise AdminProjectionError("TEST_CASE_ALREADY_EXISTS")
        if candidate.get("case_version") != 1:
            raise AdminProjectionError("NEW_TEST_CASE_VERSION_MUST_BE_ONE")
        receipt = self.truth.append_atomic("TEST_CASE_UPSERTED", candidate)
        self.refresh()
        return {"status": "CREATED", "event_id": receipt.event_id, "seq": receipt.seq,
                "case": deepcopy(self.truth.query("test_case", tc_id=tc_id)[0])}

    def append_test_case_revision(self, tc_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        self.refresh()
        existing = self.truth.query("test_case", tc_id=tc_id)
        if not existing:
            raise AdminProjectionError("TEST_CASE_NOT_FOUND")
        current = existing[0]
        candidate = deepcopy(dict(payload))
        if candidate.get("tc_id") != tc_id:
            raise AdminProjectionError("TEST_CASE_ID_IMMUTABLE")
        if candidate.get("case_version") != int(current.get("case_version", 0)) + 1:
            raise AdminProjectionError("TEST_CASE_VERSION_MUST_INCREMENT_BY_ONE")
        if current.get("release_id") is not None and candidate.get("release_id") != current.get("release_id"):
            raise AdminProjectionError("TEST_CASE_RELEASE_ID_IMMUTABLE")
        receipt = self.truth.append_atomic("TEST_CASE_UPSERTED", candidate)
        self.refresh()
        return {"status": "REVISION_APPENDED", "event_id": receipt.event_id, "seq": receipt.seq,
                "case": deepcopy(self.truth.query("test_case", tc_id=tc_id)[0])}

    def quarantine_test_case(self, tc_id: str, reason: str) -> Dict[str, Any]:
        self.refresh()
        rows = self.truth.query("test_case", tc_id=tc_id)
        if not rows:
            raise AdminProjectionError("TEST_CASE_NOT_FOUND")
        if not isinstance(reason, str) or not reason.strip():
            raise AdminProjectionError("QUARANTINE_REASON_REQUIRED")
        candidate = deepcopy(rows[0])
        candidate.pop("artifact_type", None)
        candidate["case_version"] = int(candidate.get("case_version", 0)) + 1
        candidate["status"] = "QUARANTINED"
        candidate["quarantine_reason"] = reason.strip()
        receipt = self.truth.append_atomic("TEST_CASE_UPSERTED", candidate)
        self.refresh()
        return {"status": "QUARANTINED", "event_id": receipt.event_id, "seq": receipt.seq,
                "case": deepcopy(self.truth.query("test_case", tc_id=tc_id)[0])}

    def _artifact_type(self, resource: str) -> str:
        try:
            return RESOURCE_TYPES[resource]
        except KeyError as exc:
            raise AdminProjectionError("UNKNOWN_RESOURCE") from exc

    @staticmethod
    def _sort_key(row: Mapping[str, Any]) -> Any:
        return (_row_time(row), int(row.get("artifact_version") or row.get("case_version") or row.get("version") or 0), _text(row))

    @staticmethod
    def _matches(row: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
        for key, value in filters.items():
            needle = str(value).strip()
            if not needle:
                continue
            if key in {"q", "search"}:
                if not _contains(row, needle): return False
                continue
            if key == "date_from":
                if _row_time(row) < _parse_time(needle): return False
                continue
            if key == "date_to":
                end = _parse_time(needle)
                if len(needle) == 10 and "T" not in needle: end += 86399
                if _row_time(row) > end: return False
                continue
            aliases = FILTER_ALIASES.get(key, (key,))
            values = [row.get(alias) for alias in aliases if alias in row]
            if values and not any(_contains(item, needle) for item in values): return False
            if not values and not _contains(row, needle): return False
        return True
