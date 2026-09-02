from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .errors import R37Error


EXTENSION_ID = "r3_7_test_sufficiency_operations_reporting"
EXTENSION_VERSION = "1"
ARCHITECTURE_BASELINE_REF = "v5"

R37_EVALUATE_TEST_SUFFICIENCY = "R37_EVALUATE_TEST_SUFFICIENCY"
R37_SEMANTIC_REUSE = "R37_SEMANTIC_REUSE"

REMAINING_RISK_RECORDED = "r3.7.remaining_risk_item_recorded.v1"
TEST_SUFFICIENCY_DECIDED = "r3.7.test_sufficiency_decided.v1"
SEMANTIC_REUSE_RECORDED = "r3.7.semantic_reuse.v1"

COMMAND_TYPES = frozenset({R37_EVALUATE_TEST_SUFFICIENCY, R37_SEMANTIC_REUSE})
EVENT_TYPES = frozenset({REMAINING_RISK_RECORDED, TEST_SUFFICIENCY_DECIDED, SEMANTIC_REUSE_RECORDED})

DECISION_STATES = frozenset({"SUFFICIENT", "NOT_SUFFICIENT", "BLOCKED", "RISK_ACCEPTED"})
DECISION_SCOPE_KINDS = frozenset({"ENGINEERING", "FIELD", "MIXED"})
EVIDENCE_CONFIDENCE_STATES = frozenset({
    "SUFFICIENT", "PARTIAL", "INSUFFICIENT", "CONFLICTED", "BLOCKED", "UNAVAILABLE", "NOT_EVALUATED",
})
EVIDENCE_CLASSES = frozenset({"ENGINEERING_EVIDENCE", "FIELD_EVIDENCE"})
COVERAGE_DIMENSIONS = ("requirement", "change", "risk", "journey")
RISK_STATUSES = frozenset({"OPEN", "BLOCKED", "ACCEPTED", "PENDING_FIELD_VALIDATION"})
RISK_CATEGORIES = frozenset({
    "REQUIREMENT_UNCOVERED", "REQUIREMENT_UNMAPPED", "CHANGE_ONLY_UNCOVERED", "CHANGE_UNMAPPED",
    "CRITICAL_RISK_UNTESTED", "JOURNEY_GAP", "EVIDENCE_INSUFFICIENT", "EVIDENCE_CONFLICTED",
    "BLOCKED_CRITICAL_WORK", "CONFIRMED_DEFECT", "INCONCLUSIVE_DEFECT", "ORACLE_OR_RESULT_GAP",
    "FIELD_VALIDATION_PENDING", "SOURCE_UNAVAILABLE",
})
WORKSET_TRUNCATION = frozenset({"NONE", "ITEMS", "BYTES"})
SOURCE_STATUSES = frozenset({"COLLECTED", "UNAVAILABLE", "NOT_CONFIGURED", "BLOCKED", "INVALID", "REDACTED"})
PROJECTION_TYPES = frozenset({
    "COVERAGE_CENTER", "TEST_CASE_CENTER", "TEST_RUNS", "EVIDENCE_LINKAGE", "DEFECT_LINKAGE", "TESTING_REPORT",
})

HARD_MAX_ITEMS = 24
HARD_MAX_BYTES = 12288
HARD_MAX_HOPS = 8

_FORBIDDEN_KEYS = frozenset({
    "raw", "raw_content", "raw_payload", "content", "body", "secret", "password", "passwd", "token",
    "cookie", "credential", "otp", "mfa", "authorization", "storage_state", "access_token", "refresh_token",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an integer >= {minimum}")
    return value


def _mapping(value: Any, name: str, *, required: bool = True) -> dict[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an object")
    result = {str(key): child for key, child in value.items()}
    _reject_forbidden(result, name)
    return result


def _reject_forbidden(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise R37Error("R3_7_SCHEMA_INVALID", f"{name} contains forbidden raw or secret field: {key}")
            _reject_forbidden(child, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{name}[{index}]")


def _tuple_text(value: Any, name: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if required and not result:
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _mapping_tuple(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[]") for item in value)


def _scope(value: Any) -> dict[str, Any]:
    scope = _mapping(value, "scope")
    for key in ("project_id", "environment_id", "version_scope"):
        _text(scope.get(key), f"scope.{key}")
    return scope


def _ref(value: Any, name: str, *, required: bool = True) -> dict[str, Any]:
    if value is None and not required:
        return {}
    ref = _mapping(value, name)
    identifier = ref.get("ref_id") or ref.get("id") or next(
        (item for key, item in ref.items() if str(key).endswith("_id")), None
    )
    if not isinstance(identifier, str) or not identifier.strip():
        raise R37Error("R3_7_UPSTREAM_REF_MISSING", f"{name} requires a stable ref ID")
    if not any("digest" in str(key).lower() or "fingerprint" in str(key).lower() for key in ref):
        raise R37Error("R3_7_UPSTREAM_REF_MISSING", f"{name} requires an exact digest or fingerprint")
    return ref


def _refs(value: Any, name: str, *, required: bool = False) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_ref(item, f"{name}[]") for item in value)
    if required and not result:
        raise R37Error("R3_7_UPSTREAM_REF_MISSING", f"{name} must not be empty")
    return result


def _ref_values(value: Any, name: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{name} must be an array")
    result: list[Any] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(_mapping(item, f"{name}[]"))
        else:
            result.append(_text(item, f"{name}[]"))
    return tuple(result)


def _digest(body: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(body))


def _finish(obj: Any, field_name: str, body: Mapping[str, Any], supplied: str | None) -> None:
    expected = _digest(body)
    if supplied is not None and supplied != expected:
        raise R37Error("R3_7_SCHEMA_INVALID", f"{field_name} does not match immutable object body")
    object.__setattr__(obj, field_name, expected)


def _field_status(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "OPEN", "mandatory": True}
    if isinstance(value, str):
        return {"status": _text(value, "field_validation_state"), "mandatory": True}
    return _mapping(value, "field_validation_state")


@dataclass(frozen=True)
class EvidenceConfidence:
    confidence_id: str
    status: str
    evidence_class: str
    evidence_refs: tuple[Any, ...] = ()
    verification_state: str = "NOT_EVALUATED"
    freshness: str = "UNKNOWN"
    conflict_refs: tuple[str, ...] = ()
    basis_codes: tuple[str, ...] = ()
    confidence_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence_id", _text(self.confidence_id, "confidence_id"))
        status = _text(self.status, "status")
        if status not in EVIDENCE_CONFIDENCE_STATES:
            raise R37Error("R3_7_EVIDENCE_CONFIDENCE_INVALID", f"invalid evidence confidence: {status}")
        object.__setattr__(self, "status", status)
        evidence_class = _text(self.evidence_class, "evidence_class")
        if evidence_class not in EVIDENCE_CLASSES:
            raise R37Error("R3_7_EVIDENCE_CONFIDENCE_INVALID", f"invalid evidence class: {evidence_class}")
        object.__setattr__(self, "evidence_class", evidence_class)
        object.__setattr__(self, "evidence_refs", _ref_values(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "verification_state", _text(self.verification_state, "verification_state"))
        object.__setattr__(self, "freshness", _text(self.freshness, "freshness"))
        object.__setattr__(self, "conflict_refs", _tuple_text(self.conflict_refs, "conflict_refs"))
        object.__setattr__(self, "basis_codes", _tuple_text(self.basis_codes, "basis_codes"))
        body = {
            "confidence_id": self.confidence_id, "status": self.status, "evidence_class": self.evidence_class,
            "evidence_refs": list(self.evidence_refs), "verification_state": self.verification_state,
            "freshness": self.freshness, "conflict_refs": list(self.conflict_refs), "basis_codes": list(self.basis_codes),
        }
        _finish(self, "confidence_digest", body, self.confidence_digest)

    def to_reference(self) -> dict[str, str]:
        return {"ref_id": self.confidence_id, "kind": "R3_7_EVIDENCE_CONFIDENCE", "digest": self.confidence_digest or ""}

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence_id": self.confidence_id, "status": self.status, "evidence_class": self.evidence_class,
            "evidence_refs": list(self.evidence_refs), "verification_state": self.verification_state,
            "freshness": self.freshness, "conflict_refs": list(self.conflict_refs), "basis_codes": list(self.basis_codes),
            "confidence_digest": self.confidence_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceConfidence":
        raw = _mapping(value, "evidence_confidence")
        return cls(
            raw["confidence_id"], raw["status"], raw.get("evidence_class", "ENGINEERING_EVIDENCE"),
            tuple(raw.get("evidence_refs") or ()), raw.get("verification_state", "NOT_EVALUATED"),
            raw.get("freshness", "UNKNOWN"), tuple(raw.get("conflict_refs") or ()),
            tuple(raw.get("basis_codes") or ()), raw.get("confidence_digest"),
        )


@dataclass(frozen=True)
class CoverageSummary:
    dimensions: Mapping[str, Mapping[str, Any]]
    summary_digest: str | None = None

    def __post_init__(self) -> None:
        raw = _mapping(self.dimensions, "coverage_summary")
        normalized: dict[str, dict[str, Any]] = {}
        for dimension, value in raw.items():
            if dimension not in COVERAGE_DIMENSIONS:
                raise R37Error("R3_7_SCHEMA_INVALID", f"unknown coverage dimension: {dimension}")
            item = _mapping(value, f"coverage_summary.{dimension}")
            normalized[dimension] = {
                "applicable": bool(item.get("applicable", True)),
                "denominator_count": _int(item.get("denominator_count", 0), f"{dimension}.denominator_count"),
                "covered_count": _int(item.get("covered_count", 0), f"{dimension}.covered_count"),
                "mapped_count": _int(item.get("mapped_count", 0), f"{dimension}.mapped_count"),
                "partial_count": _int(item.get("partial_count", 0), f"{dimension}.partial_count"),
                "unmapped_count": _int(item.get("unmapped_count", 0), f"{dimension}.unmapped_count"),
                "uncovered_count": _int(item.get("uncovered_count", 0), f"{dimension}.uncovered_count"),
                "blocked_count": _int(item.get("blocked_count", 0), f"{dimension}.blocked_count"),
                "covered_refs": list(_ref_values(item.get("covered_refs") or (), f"{dimension}.covered_refs")),
                "gap_refs": list(_ref_values(item.get("gap_refs") or (), f"{dimension}.gap_refs")),
                "source_refs": [dict(ref) for ref in _refs(item.get("source_refs") or (), f"{dimension}.source_refs")],
            }
        object.__setattr__(self, "dimensions", normalized)
        body = {"dimensions": normalized}
        _finish(self, "summary_digest", body, self.summary_digest)

    def to_dict(self) -> dict[str, Any]:
        return {"dimensions": {key: dict(value) for key, value in sorted(self.dimensions.items())}, "summary_digest": self.summary_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "CoverageSummary":
        raw = _mapping(value or {}, "coverage_summary")
        dimensions = raw.get("dimensions", raw)
        return cls(dimensions, raw.get("summary_digest"))


@dataclass(frozen=True)
class WorkSetRequest:
    workset_id: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    typed_channels: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    max_items: int = HARD_MAX_ITEMS
    max_bytes: int = HARD_MAX_BYTES
    max_hops: int = HARD_MAX_HOPS
    cursor: str | None = None
    session_ref: str | None = None
    as_of_seq: int = 0
    source_cursors: Mapping[str, Any] = field(default_factory=dict)
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workset_id", _text(self.workset_id, "workset_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "typed_channels", _tuple_text(self.typed_channels, "typed_channels"))
        object.__setattr__(self, "relation_types", _tuple_text(self.relation_types, "relation_types"))
        if self.max_items < 1 or self.max_items > HARD_MAX_ITEMS:
            raise R37Error("R3_7_WORKSET_BOUND_EXCEEDED", f"max_items must be between 1 and {HARD_MAX_ITEMS}")
        if self.max_bytes < 1 or self.max_bytes > HARD_MAX_BYTES:
            raise R37Error("R3_7_WORKSET_BOUND_EXCEEDED", f"max_bytes must be between 1 and {HARD_MAX_BYTES}")
        if self.max_hops < 0 or self.max_hops > HARD_MAX_HOPS:
            raise R37Error("R3_7_WORKSET_BOUND_EXCEEDED", f"max_hops must be between 0 and {HARD_MAX_HOPS}")
        object.__setattr__(self, "cursor", _optional_text(self.cursor, "cursor"))
        object.__setattr__(self, "session_ref", _optional_text(self.session_ref, "session_ref"))
        object.__setattr__(self, "as_of_seq", _int(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "source_cursors", _mapping(self.source_cursors, "source_cursors", required=False))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage", required=False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workset_id": self.workset_id, "scope": dict(self.scope), "typed_channels": list(self.typed_channels),
            "relation_types": list(self.relation_types), "max_items": self.max_items, "max_bytes": self.max_bytes,
            "max_hops": self.max_hops, "cursor": self.cursor, "session_ref": self.session_ref,
            "as_of_seq": self.as_of_seq, "source_cursors": dict(self.source_cursors), "origin_lineage": dict(self.origin_lineage),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkSetRequest":
        raw = _mapping(value, "workset_request")
        return cls(
            raw.get("workset_id", ""), raw.get("scope") or {}, tuple(raw.get("typed_channels") or ()),
            tuple(raw.get("relation_types") or ()), raw.get("max_items", HARD_MAX_ITEMS), raw.get("max_bytes", HARD_MAX_BYTES),
            raw.get("max_hops", HARD_MAX_HOPS), raw.get("cursor"), raw.get("session_ref"), raw.get("as_of_seq", 0),
            raw.get("source_cursors") or {}, raw.get("origin_lineage") or {},
        )


@dataclass(frozen=True)
class WorkSetReceipt:
    workset_id: str
    selected_items: tuple[Mapping[str, Any], ...]
    omitted_refs: tuple[str, ...]
    truncation: str
    source_statuses: Mapping[str, str]
    next_cursor: str | None
    session_ref: str | None
    context_usage_telemetry: str = "UNAVAILABLE"
    result_digest: str | None = None
    receipt_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workset_id", _text(self.workset_id, "workset_id"))
        object.__setattr__(self, "selected_items", _mapping_tuple(self.selected_items, "selected_items"))
        object.__setattr__(self, "omitted_refs", _tuple_text(self.omitted_refs, "omitted_refs"))
        if self.truncation not in WORKSET_TRUNCATION:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid workset truncation: {self.truncation}")
        statuses = _mapping(self.source_statuses, "source_statuses", required=False)
        if any(value not in SOURCE_STATUSES for value in statuses.values()):
            raise R37Error("R3_7_SCHEMA_INVALID", "invalid workset source status")
        object.__setattr__(self, "source_statuses", {str(key): str(value) for key, value in statuses.items()})
        object.__setattr__(self, "next_cursor", _optional_text(self.next_cursor, "next_cursor"))
        object.__setattr__(self, "session_ref", _optional_text(self.session_ref, "session_ref"))
        if self.context_usage_telemetry != "UNAVAILABLE":
            raise R37Error("R3_7_CONTEXT_TELEMETRY_UNAVAILABLE", "Context Usage Telemetry must remain UNAVAILABLE")
        body = {
            "workset_id": self.workset_id, "selected_items": [dict(item) for item in self.selected_items],
            "omitted_refs": list(self.omitted_refs), "truncation": self.truncation,
            "source_statuses": dict(self.source_statuses), "next_cursor": self.next_cursor, "session_ref": self.session_ref,
            "context_usage_telemetry": self.context_usage_telemetry, "result_digest": self.result_digest,
        }
        if self.result_digest is None:
            object.__setattr__(self, "result_digest", _digest(body))
        _finish(self, "receipt_digest", {**body, "result_digest": self.result_digest}, self.receipt_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workset_id": self.workset_id, "selected_items": [dict(item) for item in self.selected_items],
            "omitted_refs": list(self.omitted_refs), "truncation": self.truncation, "source_statuses": dict(self.source_statuses),
            "next_cursor": self.next_cursor, "session_ref": self.session_ref,
            "context_usage_telemetry": self.context_usage_telemetry, "result_digest": self.result_digest,
            "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkSetReceipt":
        raw = _mapping(value, "workset_receipt")
        return cls(
            raw["workset_id"], tuple(raw.get("selected_items") or ()), tuple(raw.get("omitted_refs") or ()),
            raw.get("truncation", "NONE"), raw.get("source_statuses") or {}, raw.get("next_cursor"), raw.get("session_ref"),
            raw.get("context_usage_telemetry", "UNAVAILABLE"), raw.get("result_digest"), raw.get("receipt_digest"),
        )


@dataclass(frozen=True)
class RemainingRiskItem:
    risk_item_id: str
    scope: Mapping[str, Any]
    category: str
    severity_or_risk_band: str
    status: str
    critical: bool
    reason_code: str
    risk_summary: str
    source_refs: tuple[Mapping[str, Any], ...] = ()
    coverage_gap_refs: tuple[Any, ...] = ()
    evidence_refs: tuple[Any, ...] = ()
    defect_refs: tuple[Any, ...] = ()
    acceptance_ref: Mapping[str, Any] | None = None
    field_validation_required: bool = False
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)
    risk_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_item_id", _text(self.risk_item_id, "risk_item_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "category", _text(self.category, "category"))
        if self.category not in RISK_CATEGORIES:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid remaining risk category: {self.category}")
        object.__setattr__(self, "severity_or_risk_band", _text(self.severity_or_risk_band, "severity_or_risk_band"))
        status = _text(self.status, "status")
        if status not in RISK_STATUSES:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid remaining risk status: {status}")
        object.__setattr__(self, "status", status)
        if not isinstance(self.critical, bool):
            raise R37Error("R3_7_SCHEMA_INVALID", "critical must be boolean")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "risk_summary", _text(self.risk_summary, "risk_summary"))
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))
        object.__setattr__(self, "coverage_gap_refs", _ref_values(self.coverage_gap_refs, "coverage_gap_refs"))
        object.__setattr__(self, "evidence_refs", _ref_values(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "defect_refs", _ref_values(self.defect_refs, "defect_refs"))
        if self.acceptance_ref is not None:
            object.__setattr__(self, "acceptance_ref", _ref(self.acceptance_ref, "acceptance_ref"))
        if self.status == "ACCEPTED" and self.acceptance_ref is None:
            raise R37Error("R3_7_RISK_ACCEPTANCE_REF_REQUIRED", "accepted remaining risk requires acceptance_ref")
        if self.status == "PENDING_FIELD_VALIDATION" and not self.field_validation_required:
            raise R37Error("R3_7_FIELD_VALIDATION_PENDING", "field-pending risk must require field validation")
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage", required=False))
        body = {
            "risk_item_id": self.risk_item_id, "scope": dict(self.scope), "category": self.category,
            "severity_or_risk_band": self.severity_or_risk_band, "status": self.status, "critical": self.critical,
            "reason_code": self.reason_code, "risk_summary": self.risk_summary,
            "source_refs": [dict(item) for item in self.source_refs], "coverage_gap_refs": list(self.coverage_gap_refs),
            "evidence_refs": list(self.evidence_refs), "defect_refs": list(self.defect_refs),
            "acceptance_ref": dict(self.acceptance_ref) if self.acceptance_ref else None,
            "field_validation_required": self.field_validation_required, "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "risk_digest", body, self.risk_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_item_id": self.risk_item_id, "scope": dict(self.scope), "category": self.category,
            "severity_or_risk_band": self.severity_or_risk_band, "status": self.status, "critical": self.critical,
            "reason_code": self.reason_code, "risk_summary": self.risk_summary,
            "source_refs": [dict(item) for item in self.source_refs], "coverage_gap_refs": list(self.coverage_gap_refs),
            "evidence_refs": list(self.evidence_refs), "defect_refs": list(self.defect_refs),
            "acceptance_ref": dict(self.acceptance_ref) if self.acceptance_ref else None,
            "field_validation_required": self.field_validation_required, "origin_lineage": dict(self.origin_lineage),
            "risk_digest": self.risk_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RemainingRiskItem":
        raw = _mapping(value, "remaining_risk_item")
        return cls(
            raw["risk_item_id"], raw["scope"], raw["category"], raw.get("severity_or_risk_band", "MEDIUM"),
            raw.get("status", "OPEN"), bool(raw.get("critical", False)), raw["reason_code"], raw["risk_summary"],
            tuple(raw.get("source_refs") or ()), tuple(raw.get("coverage_gap_refs") or ()),
            tuple(raw.get("evidence_refs") or ()), tuple(raw.get("defect_refs") or ()), raw.get("acceptance_ref"),
            bool(raw.get("field_validation_required", False)), raw.get("origin_lineage") or {}, raw.get("risk_digest"),
        )


@dataclass(frozen=True)
class TestSufficiencyDecision:
    decision_id: str
    scope: Mapping[str, Any]
    decision_scope_kind: str
    decision: str
    basis: Mapping[str, Any]
    coverage_snapshot: Mapping[str, Any]
    coverage_summary: Mapping[str, Any]
    evidence_confidence_refs: tuple[Mapping[str, Any], ...]
    remaining_risk: Mapping[str, Any]
    evidence_refs: tuple[Any, ...]
    defect_assessment_refs: tuple[Any, ...]
    rca_refs: tuple[Any, ...]
    journey_verification_refs: tuple[Any, ...]
    r1_r2_projection_ref: Mapping[str, Any] | None
    evaluation_receipt_ref: Mapping[str, Any]
    session_ref: str
    field_validation_state: Mapping[str, Any]
    risk_acceptance_ref: Mapping[str, Any] | None
    decision_summary: str
    source_provenance: tuple[Mapping[str, Any], ...]
    origin_lineage: Mapping[str, Any]
    decision_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _text(self.decision_id, "decision_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        if self.decision_scope_kind not in DECISION_SCOPE_KINDS:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid decision_scope_kind: {self.decision_scope_kind}")
        if self.decision not in DECISION_STATES:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid decision: {self.decision}")
        object.__setattr__(self, "basis", _mapping(self.basis, "basis"))
        object.__setattr__(self, "coverage_snapshot", _ref(self.coverage_snapshot, "coverage_snapshot"))
        object.__setattr__(self, "coverage_summary", _mapping(self.coverage_summary, "coverage_summary"))
        object.__setattr__(self, "evidence_confidence_refs", _refs(self.evidence_confidence_refs, "evidence_confidence_refs"))
        object.__setattr__(self, "remaining_risk", _mapping(self.remaining_risk, "remaining_risk"))
        object.__setattr__(self, "evidence_refs", _ref_values(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "defect_assessment_refs", _ref_values(self.defect_assessment_refs, "defect_assessment_refs"))
        object.__setattr__(self, "rca_refs", _ref_values(self.rca_refs, "rca_refs"))
        object.__setattr__(self, "journey_verification_refs", _ref_values(self.journey_verification_refs, "journey_verification_refs"))
        if self.r1_r2_projection_ref is not None:
            object.__setattr__(self, "r1_r2_projection_ref", _ref(self.r1_r2_projection_ref, "r1_r2_projection_ref"))
        object.__setattr__(self, "evaluation_receipt_ref", _ref(self.evaluation_receipt_ref, "evaluation_receipt_ref"))
        object.__setattr__(self, "session_ref", _text(self.session_ref, "session_ref"))
        object.__setattr__(self, "field_validation_state", _field_status(self.field_validation_state))
        if self.risk_acceptance_ref is not None:
            object.__setattr__(self, "risk_acceptance_ref", _ref(self.risk_acceptance_ref, "risk_acceptance_ref"))
        object.__setattr__(self, "decision_summary", _text(self.decision_summary, "decision_summary"))
        object.__setattr__(self, "source_provenance", _refs(self.source_provenance, "source_provenance"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage", required=False))
        body = {
            "decision_id": self.decision_id, "scope": dict(self.scope), "decision_scope_kind": self.decision_scope_kind,
            "decision": self.decision, "basis": dict(self.basis), "coverage_snapshot": dict(self.coverage_snapshot),
            "coverage_summary": dict(self.coverage_summary), "evidence_confidence_refs": [dict(item) for item in self.evidence_confidence_refs],
            "remaining_risk": dict(self.remaining_risk), "evidence_refs": list(self.evidence_refs),
            "defect_assessment_refs": list(self.defect_assessment_refs), "rca_refs": list(self.rca_refs),
            "journey_verification_refs": list(self.journey_verification_refs),
            "r1_r2_projection_ref": dict(self.r1_r2_projection_ref) if self.r1_r2_projection_ref else None,
            "evaluation_receipt_ref": dict(self.evaluation_receipt_ref), "session_ref": self.session_ref,
            "field_validation_state": dict(self.field_validation_state),
            "risk_acceptance_ref": dict(self.risk_acceptance_ref) if self.risk_acceptance_ref else None,
            "decision_summary": self.decision_summary, "source_provenance": [dict(item) for item in self.source_provenance],
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "decision_digest", body, self.decision_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "scope": dict(self.scope), "decision_scope_kind": self.decision_scope_kind,
            "decision": self.decision, "basis": dict(self.basis), "coverage_snapshot": dict(self.coverage_snapshot),
            "coverage_summary": dict(self.coverage_summary), "evidence_confidence_refs": [dict(item) for item in self.evidence_confidence_refs],
            "remaining_risk": dict(self.remaining_risk), "evidence_refs": list(self.evidence_refs),
            "defect_assessment_refs": list(self.defect_assessment_refs), "rca_refs": list(self.rca_refs),
            "journey_verification_refs": list(self.journey_verification_refs),
            "r1_r2_projection_ref": dict(self.r1_r2_projection_ref) if self.r1_r2_projection_ref else None,
            "evaluation_receipt_ref": dict(self.evaluation_receipt_ref), "session_ref": self.session_ref,
            "field_validation_state": dict(self.field_validation_state),
            "risk_acceptance_ref": dict(self.risk_acceptance_ref) if self.risk_acceptance_ref else None,
            "decision_summary": self.decision_summary, "source_provenance": [dict(item) for item in self.source_provenance],
            "origin_lineage": dict(self.origin_lineage), "decision_digest": self.decision_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestSufficiencyDecision":
        raw = _mapping(value, "test_sufficiency_decision")
        return cls(
            raw["decision_id"], raw["scope"], raw["decision_scope_kind"], raw["decision"], raw["basis"],
            raw["coverage_snapshot"], raw["coverage_summary"], tuple(raw.get("evidence_confidence_refs") or ()),
            raw["remaining_risk"], tuple(raw.get("evidence_refs") or ()), tuple(raw.get("defect_assessment_refs") or ()),
            tuple(raw.get("rca_refs") or ()), tuple(raw.get("journey_verification_refs") or ()),
            raw.get("r1_r2_projection_ref"), raw["evaluation_receipt_ref"], raw["session_ref"],
            raw.get("field_validation_state") or {}, raw.get("risk_acceptance_ref"), raw["decision_summary"],
            tuple(raw.get("source_provenance") or ()), raw.get("origin_lineage") or {}, raw.get("decision_digest"),
        )


@dataclass(frozen=True)
class SemanticReuse:
    reuse_id: str
    entity_kind: str
    entity_id: str
    entity_digest: str
    original_command_id: str
    origin_lineage: Mapping[str, Any]
    reuse_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("reuse_id", "entity_kind", "entity_id", "entity_digest", "original_command_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage", required=False))
        body = {
            "reuse_id": self.reuse_id, "entity_kind": self.entity_kind, "entity_id": self.entity_id,
            "entity_digest": self.entity_digest, "original_command_id": self.original_command_id,
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "reuse_digest", body, self.reuse_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reuse_id": self.reuse_id, "entity_kind": self.entity_kind, "entity_id": self.entity_id,
            "entity_digest": self.entity_digest, "original_command_id": self.original_command_id,
            "origin_lineage": dict(self.origin_lineage), "reuse_digest": self.reuse_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticReuse":
        raw = _mapping(value, "semantic_reuse")
        return cls(
            raw["reuse_id"], raw["entity_kind"], raw["entity_id"], raw["entity_digest"],
            raw["original_command_id"], raw.get("origin_lineage") or {}, raw.get("reuse_digest"),
        )


@dataclass(frozen=True)
class R37EvaluationInput:
    mission_id: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    decision_scope_kind: str = "ENGINEERING"
    as_of_seq: int = 0
    source_cursors: Mapping[str, Any] = field(default_factory=dict)
    coverage_snapshot_ref: Mapping[str, Any] = field(default_factory=dict)
    reconciliation_ref: Mapping[str, Any] = field(default_factory=dict)
    strategy_ref: Mapping[str, Any] = field(default_factory=dict)
    risk_vector_refs: tuple[Mapping[str, Any], ...] = ()
    standard_case_refs: tuple[Mapping[str, Any], ...] = ()
    case_review_refs: tuple[Mapping[str, Any], ...] = ()
    readiness_refs: tuple[Mapping[str, Any], ...] = ()
    attempt_refs: tuple[Mapping[str, Any], ...] = ()
    result_refs: tuple[Mapping[str, Any], ...] = ()
    journey_refs: tuple[Mapping[str, Any], ...] = ()
    defect_assessment_refs: tuple[Any, ...] = ()
    rca_refs: tuple[Any, ...] = ()
    r1_evidence_refs: tuple[Any, ...] = ()
    r2_runtime_projection_ref: Mapping[str, Any] | None = None
    coverage_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_confidences: tuple[EvidenceConfidence, ...] = ()
    uncovered_obligations: tuple[Mapping[str, Any], ...] = ()
    blocked_critical_work: tuple[Mapping[str, Any], ...] = ()
    defect_truth: tuple[Mapping[str, Any], ...] = ()
    remaining_risk: tuple[Mapping[str, Any], ...] = ()
    risk_acceptance_ref: Mapping[str, Any] | None = None
    workset_request: WorkSetRequest | None = None
    workset_receipt: WorkSetReceipt | None = None
    session_ref: str | None = None
    field_validation_state: Mapping[str, Any] = field(default_factory=lambda: {"status": "OPEN", "mandatory": True})
    operational_metrics: Mapping[str, Any] = field(default_factory=dict)
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)
    policy_version: str = "r3.7.sufficiency.v1"
    actor_ref: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        if self.decision_scope_kind not in DECISION_SCOPE_KINDS:
            raise R37Error("R3_7_SCHEMA_INVALID", f"invalid decision_scope_kind: {self.decision_scope_kind}")
        object.__setattr__(self, "as_of_seq", _int(self.as_of_seq, "as_of_seq"))
        object.__setattr__(self, "source_cursors", _mapping(self.source_cursors, "source_cursors", required=False))
        object.__setattr__(self, "coverage_snapshot_ref", _ref(self.coverage_snapshot_ref, "coverage_snapshot_ref"))
        object.__setattr__(self, "reconciliation_ref", _ref(self.reconciliation_ref, "reconciliation_ref"))
        if self.strategy_ref:
            object.__setattr__(self, "strategy_ref", _ref(self.strategy_ref, "strategy_ref"))
        else:
            object.__setattr__(self, "strategy_ref", {})
        for name in ("risk_vector_refs", "standard_case_refs", "case_review_refs", "readiness_refs", "attempt_refs", "result_refs", "journey_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        for name in ("defect_assessment_refs", "rca_refs", "r1_evidence_refs"):
            object.__setattr__(self, name, _ref_values(getattr(self, name), name))
        if self.r2_runtime_projection_ref is not None:
            object.__setattr__(self, "r2_runtime_projection_ref", _ref(self.r2_runtime_projection_ref, "r2_runtime_projection_ref"))
        object.__setattr__(self, "coverage_summary", CoverageSummary.from_dict(self.coverage_summary).to_dict())
        object.__setattr__(self, "evidence_confidences", tuple(
            item if isinstance(item, EvidenceConfidence) else EvidenceConfidence.from_dict(item)
            for item in self.evidence_confidences
        ))
        object.__setattr__(self, "uncovered_obligations", _mapping_tuple(self.uncovered_obligations, "uncovered_obligations"))
        object.__setattr__(self, "blocked_critical_work", _mapping_tuple(self.blocked_critical_work, "blocked_critical_work"))
        object.__setattr__(self, "defect_truth", _mapping_tuple(self.defect_truth, "defect_truth"))
        object.__setattr__(self, "remaining_risk", _mapping_tuple(self.remaining_risk, "remaining_risk"))
        if self.risk_acceptance_ref is not None:
            object.__setattr__(self, "risk_acceptance_ref", _ref(self.risk_acceptance_ref, "risk_acceptance_ref"))
        if self.workset_request is not None and not isinstance(self.workset_request, WorkSetRequest):
            object.__setattr__(self, "workset_request", WorkSetRequest.from_dict(self.workset_request))
        if self.workset_receipt is not None and not isinstance(self.workset_receipt, WorkSetReceipt):
            object.__setattr__(self, "workset_receipt", WorkSetReceipt.from_dict(self.workset_receipt))
        object.__setattr__(self, "session_ref", _optional_text(self.session_ref, "session_ref"))
        object.__setattr__(self, "field_validation_state", _field_status(self.field_validation_state))
        object.__setattr__(self, "operational_metrics", _mapping(self.operational_metrics, "operational_metrics", required=False))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage", required=False))
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        object.__setattr__(self, "actor_ref", _mapping(self.actor_ref, "actor_ref", required=False))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, mission_id: str | None = None) -> "R37EvaluationInput":
        raw = _mapping(value, "evaluation_request")
        scope = raw.get("scope") or {
            "project_id": raw.get("project_id"), "environment_id": raw.get("environment_id", "engineering"),
            "version_scope": raw.get("version_scope", "unknown"),
        }
        selected_mission = mission_id or raw.get("mission_id") or raw.get("origin_lineage", {}).get("mission_id")
        return cls(
            mission_id=selected_mission or "", scope=scope, decision_scope_kind=raw.get("decision_scope_kind", "ENGINEERING"),
            as_of_seq=raw.get("as_of_seq", 0), source_cursors=raw.get("source_cursors") or {},
            coverage_snapshot_ref=raw.get("coverage_snapshot_ref") or raw.get("coverage_snapshot") or {},
            reconciliation_ref=raw.get("reconciliation_ref") or raw.get("reconciliation") or {},
            strategy_ref=raw.get("strategy_ref") or raw.get("strategy") or {},
            risk_vector_refs=tuple(raw.get("risk_vector_refs") or ()), standard_case_refs=tuple(raw.get("standard_case_refs") or ()),
            case_review_refs=tuple(raw.get("case_review_refs") or ()), readiness_refs=tuple(raw.get("readiness_refs") or ()),
            attempt_refs=tuple(raw.get("attempt_refs") or ()), result_refs=tuple(raw.get("result_refs") or ()),
            journey_refs=tuple(raw.get("journey_refs") or raw.get("journey_verification_refs") or ()),
            defect_assessment_refs=tuple(raw.get("defect_assessment_refs") or ()), rca_refs=tuple(raw.get("rca_refs") or ()),
            r1_evidence_refs=tuple(raw.get("r1_evidence_refs") or ()), r2_runtime_projection_ref=raw.get("r2_runtime_projection_ref"),
            coverage_summary=raw.get("coverage_summary") or raw.get("coverage") or {},
            evidence_confidences=tuple(raw.get("evidence_confidences") or raw.get("evidence_confidence") or ()),
            uncovered_obligations=tuple(raw.get("uncovered_obligations") or raw.get("unmapped_obligations") or ()),
            blocked_critical_work=tuple(raw.get("blocked_critical_work") or ()), defect_truth=tuple(raw.get("defect_truth") or ()),
            remaining_risk=tuple(raw.get("remaining_risk") or ()), risk_acceptance_ref=raw.get("risk_acceptance_ref"),
            workset_request=raw.get("workset_request"), workset_receipt=raw.get("workset_receipt"),
            session_ref=raw.get("session_ref"), field_validation_state=raw.get("field_validation_state") or {"status": "OPEN", "mandatory": True},
            operational_metrics=raw.get("operational_metrics") or {}, origin_lineage=raw.get("origin_lineage") or {},
            policy_version=raw.get("policy_version", "r3.7.sufficiency.v1"), actor_ref=raw.get("actor_ref") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "scope": dict(self.scope), "decision_scope_kind": self.decision_scope_kind,
            "as_of_seq": self.as_of_seq, "source_cursors": dict(self.source_cursors),
            "coverage_snapshot_ref": dict(self.coverage_snapshot_ref), "reconciliation_ref": dict(self.reconciliation_ref),
            "strategy_ref": dict(self.strategy_ref), "risk_vector_refs": [dict(item) for item in self.risk_vector_refs],
            "standard_case_refs": [dict(item) for item in self.standard_case_refs], "case_review_refs": [dict(item) for item in self.case_review_refs],
            "readiness_refs": [dict(item) for item in self.readiness_refs], "attempt_refs": [dict(item) for item in self.attempt_refs],
            "result_refs": [dict(item) for item in self.result_refs], "journey_refs": [dict(item) for item in self.journey_refs],
            "defect_assessment_refs": list(self.defect_assessment_refs), "rca_refs": list(self.rca_refs), "r1_evidence_refs": list(self.r1_evidence_refs),
            "r2_runtime_projection_ref": dict(self.r2_runtime_projection_ref) if self.r2_runtime_projection_ref else None,
            "coverage_summary": dict(self.coverage_summary), "evidence_confidences": [item.to_dict() for item in self.evidence_confidences],
            "uncovered_obligations": [dict(item) for item in self.uncovered_obligations],
            "blocked_critical_work": [dict(item) for item in self.blocked_critical_work], "defect_truth": [dict(item) for item in self.defect_truth],
            "remaining_risk": [dict(item) for item in self.remaining_risk],
            "risk_acceptance_ref": dict(self.risk_acceptance_ref) if self.risk_acceptance_ref else None,
            "workset_request": self.workset_request.to_dict() if self.workset_request else None,
            "workset_receipt": self.workset_receipt.to_dict() if self.workset_receipt else None,
            "session_ref": self.session_ref, "field_validation_state": dict(self.field_validation_state),
            "operational_metrics": dict(self.operational_metrics), "origin_lineage": dict(self.origin_lineage),
            "policy_version": self.policy_version, "actor_ref": dict(self.actor_ref),
        }


@dataclass(frozen=True)
class R37State:
    mission_id: str
    decisions: tuple[TestSufficiencyDecision, ...] = ()
    remaining_risks: tuple[RemainingRiskItem, ...] = ()
    reuses: tuple[SemanticReuse, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))

    def decision(self, value: str) -> TestSufficiencyDecision | None:
        return next((item for item in self.decisions if item.decision_id == value), None)

    def risk(self, value: str) -> RemainingRiskItem | None:
        return next((item for item in self.remaining_risks if item.risk_item_id == value), None)

    def reuse(self, value: str) -> SemanticReuse | None:
        return next((item for item in self.reuses if item.reuse_id == value), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "decisions": [item.to_dict() for item in self.decisions],
            "remaining_risks": [item.to_dict() for item in self.remaining_risks],
            "reuses": [item.to_dict() for item in self.reuses],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R37State":
        raw = _mapping(value, "r37_state")
        return cls(
            raw["mission_id"],
            tuple(TestSufficiencyDecision.from_dict(item) for item in raw.get("decisions") or ()),
            tuple(RemainingRiskItem.from_dict(item) for item in raw.get("remaining_risks") or ()),
            tuple(SemanticReuse.from_dict(item) for item in raw.get("reuses") or ()),
        )
