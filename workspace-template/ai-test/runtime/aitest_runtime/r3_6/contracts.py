from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .errors import R36Error


EXTENSION_ID = "r3_6_defect_investigation_rca"
EXTENSION_VERSION = "1"
ARCHITECTURE_BASELINE_REF = "v5"

RECORD_TEST_ANOMALY = "R36_RECORD_TEST_ANOMALY"
CREATE_DEFECT_CANDIDATE = "R36_CREATE_DEFECT_CANDIDATE"
REQUEST_EVIDENCE_DEEPENING = "R36_REQUEST_EVIDENCE_DEEPENING"
RECORD_EVIDENCE_ASSESSMENT = "R36_RECORD_EVIDENCE_ASSESSMENT"
RECORD_CROSS_SOURCE_CORRELATION = "R36_RECORD_CROSS_SOURCE_CORRELATION"
EVALUATE_REPRODUCIBILITY = "R36_EVALUATE_REPRODUCIBILITY"
ASSESS_FALSE_POSITIVE = "R36_ASSESS_FALSE_POSITIVE"
ASSESS_DEFECT_TRUTH = "R36_ASSESS_DEFECT_TRUTH"
RECORD_RCA = "R36_RECORD_RCA"
RECORD_INVESTIGATION_CHECKPOINT = "R36_RECORD_INVESTIGATION_CHECKPOINT"
SEMANTIC_REUSE = "R36_SEMANTIC_REUSE"

ANOMALY_RECORDED = "r3.6.test_anomaly_recorded.v1"
CANDIDATE_CREATED = "r3.6.defect_candidate_created.v1"
EVIDENCE_DEEPENING_REQUESTED = "r3.6.evidence_deepening_requested.v1"
EVIDENCE_ASSESSED = "r3.6.evidence_assessed.v1"
CROSS_SOURCE_CORRELATED = "r3.6.cross_source_correlated.v1"
REPRODUCIBILITY_EVALUATED = "r3.6.reproducibility_evaluated.v1"
FALSE_POSITIVE_ASSESSED = "r3.6.false_positive_assessed.v1"
DEFECT_TRUTH_ASSESSED = "r3.6.defect_truth_assessed.v1"
RCA_RECORDED = "r3.6.rca_recorded.v1"
CHECKPOINT_RECORDED = "r3.6.investigation_checkpoint_recorded.v1"
SEMANTIC_REUSE_RECORDED = "r3.6.semantic_reuse.v1"

COMMAND_TYPES = frozenset({
    RECORD_TEST_ANOMALY, CREATE_DEFECT_CANDIDATE, REQUEST_EVIDENCE_DEEPENING,
    RECORD_EVIDENCE_ASSESSMENT, RECORD_CROSS_SOURCE_CORRELATION,
    EVALUATE_REPRODUCIBILITY, ASSESS_FALSE_POSITIVE, ASSESS_DEFECT_TRUTH,
    RECORD_RCA, RECORD_INVESTIGATION_CHECKPOINT, SEMANTIC_REUSE,
})
EVENT_TYPES = frozenset({
    ANOMALY_RECORDED, CANDIDATE_CREATED, EVIDENCE_DEEPENING_REQUESTED,
    EVIDENCE_ASSESSED, CROSS_SOURCE_CORRELATED, REPRODUCIBILITY_EVALUATED,
    FALSE_POSITIVE_ASSESSED, DEFECT_TRUTH_ASSESSED, RCA_RECORDED,
    CHECKPOINT_RECORDED, SEMANTIC_REUSE_RECORDED,
})

FAILURE_CLASSIFICATIONS = frozenset({
    "PRODUCT_DEFECT_CANDIDATE",
    "ENVIRONMENT_PROBLEM",
    "TEST_DATA_PROBLEM",
    "AUTOMATION_DEFECT",
    "CASE_SPEC_DEFECT",
    "KNOWLEDGE_FACT_ERROR",
    "UNKNOWN_INCONCLUSIVE",
})
FINAL_CLASSIFICATIONS = frozenset({
    "PRODUCT_DEFECT",
    "ENVIRONMENT_PROBLEM",
    "TEST_DATA_PROBLEM",
    "AUTOMATION_DEFECT",
    "CASE_SPEC_DEFECT",
    "KNOWLEDGE_FACT_ERROR",
    "UNKNOWN_INCONCLUSIVE",
})
ANOMALY_TRIGGERS = frozenset({
    "FAIL", "ERROR", "BLOCKED", "INCONCLUSIVE", "EVIDENCE_INSUFFICIENT",
    "ORACLE_CONTRADICTION", "PAGE_RUNTIME_CONFLICT", "JOURNEY_ANOMALY",
})
EVIDENCE_SUFFICIENCY = frozenset({"SUFFICIENT", "INSUFFICIENT", "CONFLICTED"})
EVIDENCE_CLASSES = frozenset({"ENGINEERING_EVIDENCE", "FIELD_EVIDENCE"})
SOURCE_STATUSES = frozenset({"COLLECTED", "UNAVAILABLE", "NOT_CONFIGURED", "BLOCKED", "INVALID", "REDACTED"})
REPRODUCIBILITY_STATES = frozenset({
    "REPRODUCED", "NOT_REPRODUCED", "NON_DETERMINISTIC", "BLOCKED", "INCONCLUSIVE", "NOT_ATTEMPTED",
})
FALSE_POSITIVE_STATES = frozenset({"NOT_FALSE_POSITIVE", "REJECTED_FALSE_POSITIVE", "UNRESOLVED", "BLOCKED"})
DEFECT_ASSESSMENT_OUTCOMES = frozenset({
    "CONFIRMED_DEFECT", "CLASSIFIED_NON_PRODUCT", "REJECTED_FALSE_POSITIVE", "INCONCLUSIVE", "BLOCKED",
})
RCA_CAUSES = frozenset({
    "CODE_LOGIC", "API_CONTRACT", "DATA_PERSISTENCE", "ENV_DEPLOYMENT",
    "AUTH_PERMISSION", "INTEGRATION_DEPENDENCY", "JOURNEY_STATE",
    "AUTOMATION", "CASE_SPEC", "KNOWLEDGE_FACT", "UNKNOWN",
})
RCA_STATES = frozenset({"ESTABLISHED", "PARTIAL", "UNRESOLVED", "NOT_APPLICABLE"})
WORKSET_TRUNCATION = frozenset({"NONE", "ITEMS", "BYTES"})

_FORBIDDEN_KEYS = frozenset({
    "raw", "raw_content", "raw_payload", "content", "body", "secret",
    "password", "passwd", "token", "cookie", "credential", "otp", "mfa",
    "authorization", "storage_state", "access_token", "refresh_token",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _reject_forbidden(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise R36Error("R3_6_SCHEMA_INVALID", f"{name} contains forbidden raw or secret field: {key}")
            _reject_forbidden(child, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{name}[{index}]")


def _mapping(value: Any, name: str, *, required: bool = True) -> dict[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must be an object")
    result = dict(value)
    _reject_forbidden(result, name)
    return result


def _tuple_text(value: Any, name: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if required and not result:
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _tuple_mapping(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise R36Error("R3_6_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[]") for item in value)


def _scope(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    scope = _mapping(value, "scope")
    for key in ("project_id", "environment_id", "version_scope"):
        _text(scope.get(key), f"scope.{key}")
    return scope


def _ref(value: Any, name: str) -> dict[str, Any]:
    ref = _mapping(value, name)
    identifier = ref.get("ref_id") or ref.get("id") or next((v for k, v in ref.items() if k.endswith("_id")), None)
    if not isinstance(identifier, str) or not identifier.strip():
        raise R36Error("R3_6_UPSTREAM_REF_MISSING", f"{name} requires a stable ref ID")
    if not any("digest" in str(key).lower() or "fingerprint" in str(key).lower() for key in ref):
        raise R36Error("R3_6_UPSTREAM_REF_MISSING", f"{name} requires an exact digest or fingerprint")
    return ref


def _refs(value: Any, name: str, *, required: bool = False) -> tuple[dict[str, Any], ...]:
    result = _tuple_mapping(value, name)
    refs = tuple(_ref(item, f"{name}[]") for item in result)
    if required and not refs:
        raise R36Error("R3_6_UPSTREAM_REF_MISSING", f"{name} must not be empty")
    return refs


def _digest(body: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(body))


def _finish(obj: Any, field_name: str, body: Mapping[str, Any], supplied: str | None) -> None:
    expected = _digest(body)
    if supplied is not None and supplied != expected:
        raise R36Error("R3_6_SCHEMA_INVALID", f"{field_name} does not match immutable object body")
    object.__setattr__(obj, field_name, expected)


def _common_body(obj: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in names}


@dataclass(frozen=True)
class TestAnomaly:
    anomaly_id: str
    scope: Mapping[str, Any]
    trigger: str
    upstream_refs: Mapping[str, Mapping[str, Any]]
    source_refs: tuple[Mapping[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()
    observed_digests: Mapping[str, Any] = field(default_factory=dict)
    candidate_signal: str = ""
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)
    anomaly_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "anomaly_id", _text(self.anomaly_id, "anomaly_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        trigger = _text(self.trigger, "trigger")
        if trigger not in ANOMALY_TRIGGERS:
            raise R36Error("R3_6_ANOMALY_NOT_ELIGIBLE", f"unsupported anomaly trigger: {trigger}")
        object.__setattr__(self, "trigger", trigger)
        refs = {str(key): _ref(value, f"upstream_refs.{key}") for key, value in _mapping(self.upstream_refs, "upstream_refs").items()}
        if not refs:
            raise R36Error("R3_6_UPSTREAM_REF_MISSING", "anomaly requires exact upstream refs")
        object.__setattr__(self, "upstream_refs", refs)
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))
        object.__setattr__(self, "evidence_refs", _tuple_text(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "observed_digests", _mapping(self.observed_digests, "observed_digests", required=False))
        object.__setattr__(self, "candidate_signal", _text(self.candidate_signal or trigger, "candidate_signal"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "anomaly_id": self.anomaly_id, "scope": dict(self.scope), "trigger": self.trigger,
            "upstream_refs": {key: dict(value) for key, value in self.upstream_refs.items()},
            "source_refs": [dict(value) for value in self.source_refs], "evidence_refs": list(self.evidence_refs),
            "observed_digests": dict(self.observed_digests), "candidate_signal": self.candidate_signal,
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "anomaly_digest", body, self.anomaly_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id, "scope": dict(self.scope), "trigger": self.trigger,
            "upstream_refs": {key: dict(value) for key, value in self.upstream_refs.items()},
            "source_refs": [dict(value) for value in self.source_refs], "evidence_refs": list(self.evidence_refs),
            "observed_digests": dict(self.observed_digests), "candidate_signal": self.candidate_signal,
            "origin_lineage": dict(self.origin_lineage), "anomaly_digest": self.anomaly_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TestAnomaly":
        raw = _mapping(value, "anomaly")
        return cls(
            raw["anomaly_id"], raw["scope"], raw["trigger"], raw["upstream_refs"],
            tuple(raw.get("source_refs") or ()), tuple(raw.get("evidence_refs") or ()),
            raw.get("observed_digests") or {}, raw.get("candidate_signal") or "",
            raw.get("origin_lineage") or {}, raw.get("anomaly_digest"),
        )


@dataclass(frozen=True)
class DefectCandidate:
    candidate_id: str
    scope: Mapping[str, Any]
    anomaly_refs: tuple[str, ...]
    classification: str
    alternative_classifications: tuple[str, ...]
    hypothesis: str
    affected_scope: Mapping[str, Any]
    supporting_evidence_refs: tuple[str, ...]
    contradicting_evidence_refs: tuple[str, ...]
    origin_lineage: Mapping[str, Any]
    candidate_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "anomaly_refs", _tuple_text(self.anomaly_refs, "anomaly_refs", required=True))
        classification = _text(self.classification, "classification")
        if classification not in FAILURE_CLASSIFICATIONS:
            raise R36Error("R3_6_SCHEMA_INVALID", f"invalid candidate classification: {classification}")
        object.__setattr__(self, "classification", classification)
        alternatives = _tuple_text(self.alternative_classifications, "alternative_classifications")
        if any(item not in FAILURE_CLASSIFICATIONS for item in alternatives):
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid alternative candidate classification")
        object.__setattr__(self, "alternative_classifications", alternatives)
        object.__setattr__(self, "hypothesis", _text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "affected_scope", _mapping(self.affected_scope, "affected_scope", required=False))
        object.__setattr__(self, "supporting_evidence_refs", _tuple_text(self.supporting_evidence_refs, "supporting_evidence_refs"))
        object.__setattr__(self, "contradicting_evidence_refs", _tuple_text(self.contradicting_evidence_refs, "contradicting_evidence_refs"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "candidate_id": self.candidate_id, "scope": dict(self.scope), "anomaly_refs": list(self.anomaly_refs),
            "classification": self.classification, "alternative_classifications": list(self.alternative_classifications),
            "hypothesis": self.hypothesis, "affected_scope": dict(self.affected_scope),
            "supporting_evidence_refs": list(self.supporting_evidence_refs),
            "contradicting_evidence_refs": list(self.contradicting_evidence_refs),
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "candidate_digest", body, self.candidate_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "scope": dict(self.scope), "anomaly_refs": list(self.anomaly_refs),
            "classification": self.classification, "alternative_classifications": list(self.alternative_classifications),
            "hypothesis": self.hypothesis, "affected_scope": dict(self.affected_scope),
            "supporting_evidence_refs": list(self.supporting_evidence_refs),
            "contradicting_evidence_refs": list(self.contradicting_evidence_refs),
            "origin_lineage": dict(self.origin_lineage), "candidate_digest": self.candidate_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DefectCandidate":
        raw = _mapping(value, "candidate")
        return cls(
            raw["candidate_id"], raw["scope"], tuple(raw.get("anomaly_refs") or ()), raw["classification"],
            tuple(raw.get("alternative_classifications") or ()), raw["hypothesis"], raw.get("affected_scope") or {},
            tuple(raw.get("supporting_evidence_refs") or ()), tuple(raw.get("contradicting_evidence_refs") or ()),
            raw.get("origin_lineage") or {}, raw.get("candidate_digest"),
        )


@dataclass(frozen=True)
class InvestigationWorkSetRequest:
    workset_id: str
    candidate_id: str
    scope: Mapping[str, Any]
    channels: tuple[str, ...]
    relation_types: tuple[str, ...] = ()
    max_items: int = 24
    max_bytes: int = 12288
    max_hops: int = 2
    cursor: str | None = None
    session_ref: str | None = None
    origin_lineage: Mapping[str, Any] = field(default_factory=dict)
    request_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workset_id", _text(self.workset_id, "workset_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "channels", _tuple_text(self.channels, "channels", required=True))
        object.__setattr__(self, "relation_types", _tuple_text(self.relation_types, "relation_types"))
        if isinstance(self.max_items, bool) or not isinstance(self.max_items, int) or not 1 <= self.max_items <= 24:
            raise R36Error("R3_6_WORKSET_BOUND_EXCEEDED", "max_items must be between 1 and 24")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or not 1 <= self.max_bytes <= 12288:
            raise R36Error("R3_6_WORKSET_BOUND_EXCEEDED", "max_bytes must be between 1 and 12288")
        if isinstance(self.max_hops, bool) or not isinstance(self.max_hops, int) or not 0 <= self.max_hops <= 8:
            raise R36Error("R3_6_WORKSET_BOUND_EXCEEDED", "max_hops must be between 0 and 8")
        object.__setattr__(self, "cursor", _optional_text(self.cursor, "cursor"))
        object.__setattr__(self, "session_ref", _optional_text(self.session_ref, "session_ref"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "workset_id": self.workset_id, "candidate_id": self.candidate_id, "scope": dict(self.scope),
            "channels": list(self.channels), "relation_types": list(self.relation_types),
            "max_items": self.max_items, "max_bytes": self.max_bytes, "max_hops": self.max_hops,
            "cursor": self.cursor, "session_ref": self.session_ref, "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "request_digest", body, self.request_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workset_id": self.workset_id, "candidate_id": self.candidate_id, "scope": dict(self.scope),
            "channels": list(self.channels), "relation_types": list(self.relation_types),
            "max_items": self.max_items, "max_bytes": self.max_bytes, "max_hops": self.max_hops,
            "cursor": self.cursor, "session_ref": self.session_ref, "origin_lineage": dict(self.origin_lineage),
            "request_digest": self.request_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestigationWorkSetRequest":
        raw = _mapping(value, "workset_request")
        return cls(
            raw["workset_id"], raw["candidate_id"], raw["scope"], tuple(raw.get("channels") or ()),
            tuple(raw.get("relation_types") or ()), int(raw.get("max_items", 24)), int(raw.get("max_bytes", 12288)),
            int(raw.get("max_hops", 2)), raw.get("cursor"), raw.get("session_ref"),
            raw.get("origin_lineage") or {}, raw.get("request_digest"),
        )


@dataclass(frozen=True)
class InvestigationWorkSetReceipt:
    workset_id: str
    selected_items: tuple[Mapping[str, Any], ...]
    omitted_refs: tuple[str, ...]
    truncation: str
    source_statuses: Mapping[str, str]
    next_cursor: str | None
    result_digest: str
    receipt_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workset_id", _text(self.workset_id, "workset_id"))
        items = _tuple_mapping(self.selected_items, "selected_items")
        for item in items:
            _ref(item, "selected_items[]")
        object.__setattr__(self, "selected_items", items)
        object.__setattr__(self, "omitted_refs", _tuple_text(self.omitted_refs, "omitted_refs"))
        truncation = _text(self.truncation, "truncation")
        if truncation not in WORKSET_TRUNCATION:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid WorkSet truncation state")
        object.__setattr__(self, "truncation", truncation)
        statuses = _mapping(self.source_statuses, "source_statuses", required=False)
        if any(str(value) not in SOURCE_STATUSES for value in statuses.values()):
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid WorkSet source status")
        object.__setattr__(self, "source_statuses", {str(k): str(v) for k, v in statuses.items()})
        object.__setattr__(self, "next_cursor", _optional_text(self.next_cursor, "next_cursor"))
        object.__setattr__(self, "result_digest", _text(self.result_digest, "result_digest"))
        body = {
            "workset_id": self.workset_id, "selected_items": [dict(item) for item in self.selected_items],
            "omitted_refs": list(self.omitted_refs), "truncation": self.truncation,
            "source_statuses": dict(self.source_statuses), "next_cursor": self.next_cursor,
            "result_digest": self.result_digest,
        }
        _finish(self, "receipt_digest", body, self.receipt_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workset_id": self.workset_id, "selected_items": [dict(item) for item in self.selected_items],
            "omitted_refs": list(self.omitted_refs), "truncation": self.truncation,
            "source_statuses": dict(self.source_statuses), "next_cursor": self.next_cursor,
            "result_digest": self.result_digest, "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestigationWorkSetReceipt":
        raw = _mapping(value, "workset_receipt")
        return cls(
            raw["workset_id"], tuple(raw.get("selected_items") or ()), tuple(raw.get("omitted_refs") or ()),
            raw.get("truncation", "NONE"), raw.get("source_statuses") or {}, raw.get("next_cursor"),
            raw["result_digest"], raw.get("receipt_digest"),
        )


@dataclass(frozen=True)
class EvidenceDeepeningReceipt:
    deepening_id: str
    candidate_id: str
    workset_request: InvestigationWorkSetRequest
    workset_receipt: InvestigationWorkSetReceipt
    channel_statuses: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    origin_lineage: Mapping[str, Any]
    deepening_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "deepening_id", _text(self.deepening_id, "deepening_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        if self.workset_request.candidate_id != self.candidate_id or self.workset_receipt.workset_id != self.workset_request.workset_id:
            raise R36Error("R3_6_SCOPE_MISMATCH", "WorkSet and evidence deepening candidate/identity mismatch")
        statuses = _mapping(self.channel_statuses, "channel_statuses", required=True)
        if any(str(value) not in SOURCE_STATUSES for value in statuses.values()):
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid evidence deepening channel status")
        object.__setattr__(self, "channel_statuses", {str(k): str(v) for k, v in statuses.items()})
        object.__setattr__(self, "evidence_refs", _tuple_text(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "deepening_id": self.deepening_id, "candidate_id": self.candidate_id,
            "workset_request": self.workset_request.to_dict(), "workset_receipt": self.workset_receipt.to_dict(),
            "channel_statuses": dict(self.channel_statuses), "evidence_refs": list(self.evidence_refs),
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "deepening_digest", body, self.deepening_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deepening_id": self.deepening_id, "candidate_id": self.candidate_id,
            "workset_request": self.workset_request.to_dict(), "workset_receipt": self.workset_receipt.to_dict(),
            "channel_statuses": dict(self.channel_statuses), "evidence_refs": list(self.evidence_refs),
            "origin_lineage": dict(self.origin_lineage), "deepening_digest": self.deepening_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceDeepeningReceipt":
        raw = _mapping(value, "evidence_deepening")
        return cls(
            raw["deepening_id"], raw["candidate_id"],
            InvestigationWorkSetRequest.from_dict(raw["workset_request"]),
            InvestigationWorkSetReceipt.from_dict(raw["workset_receipt"]),
            raw["channel_statuses"], tuple(raw.get("evidence_refs") or ()),
            raw.get("origin_lineage") or {}, raw.get("deepening_digest"),
        )


@dataclass(frozen=True)
class EvidenceAssessment:
    assessment_id: str
    candidate_id: str
    evidence_refs: tuple[str, ...]
    evidence_role: str
    evidence_sufficiency: str
    relevance: str
    verification_method: str
    freshness: str
    scope_match: str
    conflict_refs: tuple[str, ...]
    evidence_class: str
    origin_lineage: Mapping[str, Any]
    assessment_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "evidence_refs", _tuple_text(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "evidence_role", _text(self.evidence_role, "evidence_role"))
        sufficiency = _text(self.evidence_sufficiency, "evidence_sufficiency")
        if sufficiency not in EVIDENCE_SUFFICIENCY:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid evidence sufficiency")
        object.__setattr__(self, "evidence_sufficiency", sufficiency)
        for name in ("relevance", "verification_method", "freshness", "scope_match"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "conflict_refs", _tuple_text(self.conflict_refs, "conflict_refs"))
        evidence_class = _text(self.evidence_class, "evidence_class")
        if evidence_class not in EVIDENCE_CLASSES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid evidence class")
        object.__setattr__(self, "evidence_class", evidence_class)
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "assessment_id": self.assessment_id, "candidate_id": self.candidate_id,
            "evidence_refs": list(self.evidence_refs), "evidence_role": self.evidence_role,
            "evidence_sufficiency": self.evidence_sufficiency, "relevance": self.relevance,
            "verification_method": self.verification_method, "freshness": self.freshness,
            "scope_match": self.scope_match, "conflict_refs": list(self.conflict_refs),
            "evidence_class": self.evidence_class, "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "assessment_digest", body, self.assessment_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id, "candidate_id": self.candidate_id,
            "evidence_refs": list(self.evidence_refs), "evidence_role": self.evidence_role,
            "evidence_sufficiency": self.evidence_sufficiency, "relevance": self.relevance,
            "verification_method": self.verification_method, "freshness": self.freshness,
            "scope_match": self.scope_match, "conflict_refs": list(self.conflict_refs),
            "evidence_class": self.evidence_class, "origin_lineage": dict(self.origin_lineage),
            "assessment_digest": self.assessment_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceAssessment":
        raw = _mapping(value, "evidence_assessment")
        return cls(
            raw["assessment_id"], raw["candidate_id"], tuple(raw.get("evidence_refs") or ()),
            raw["evidence_role"], raw["evidence_sufficiency"], raw["relevance"],
            raw["verification_method"], raw["freshness"], raw["scope_match"],
            tuple(raw.get("conflict_refs") or ()), raw.get("evidence_class", "ENGINEERING_EVIDENCE"),
            raw.get("origin_lineage") or {}, raw.get("assessment_digest"),
        )


@dataclass(frozen=True)
class CrossSourceCorrelation:
    correlation_id: str
    candidate_id: str
    source_refs: tuple[Mapping[str, Any], ...]
    correlation_keys: Mapping[str, Any]
    method: str
    match_quality: str
    confidence: float
    time_window: Mapping[str, Any]
    conflict_refs: tuple[str, ...]
    origin_lineage: Mapping[str, Any]
    correlation_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs", required=True))
        object.__setattr__(self, "correlation_keys", _mapping(self.correlation_keys, "correlation_keys", required=True))
        object.__setattr__(self, "method", _text(self.method, "method"))
        object.__setattr__(self, "match_quality", _text(self.match_quality, "match_quality"))
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
            raise R36Error("R3_6_SCHEMA_INVALID", "correlation confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "time_window", _mapping(self.time_window, "time_window", required=False))
        object.__setattr__(self, "conflict_refs", _tuple_text(self.conflict_refs, "conflict_refs"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "correlation_id": self.correlation_id, "candidate_id": self.candidate_id,
            "source_refs": [dict(value) for value in self.source_refs], "correlation_keys": dict(self.correlation_keys),
            "method": self.method, "match_quality": self.match_quality, "confidence": self.confidence,
            "time_window": dict(self.time_window), "conflict_refs": list(self.conflict_refs),
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "correlation_digest", body, self.correlation_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id, "candidate_id": self.candidate_id,
            "source_refs": [dict(value) for value in self.source_refs], "correlation_keys": dict(self.correlation_keys),
            "method": self.method, "match_quality": self.match_quality, "confidence": self.confidence,
            "time_window": dict(self.time_window), "conflict_refs": list(self.conflict_refs),
            "origin_lineage": dict(self.origin_lineage), "correlation_digest": self.correlation_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CrossSourceCorrelation":
        raw = _mapping(value, "correlation")
        return cls(
            raw["correlation_id"], raw["candidate_id"], tuple(raw.get("source_refs") or ()),
            raw["correlation_keys"], raw["method"], raw["match_quality"], raw["confidence"],
            raw.get("time_window") or {}, tuple(raw.get("conflict_refs") or ()),
            raw.get("origin_lineage") or {}, raw.get("correlation_digest"),
        )


@dataclass(frozen=True)
class ReproducibilityAssessment:
    reproducibility_id: str
    candidate_id: str
    status: str
    attempt_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    controlled_variables: Mapping[str, Any]
    signature: str
    comparison: str
    blocking_basis: str | None
    origin_lineage: Mapping[str, Any]
    reproducibility_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reproducibility_id", _text(self.reproducibility_id, "reproducibility_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        status = _text(self.status, "status")
        if status not in REPRODUCIBILITY_STATES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid reproducibility state")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "attempt_refs", _tuple_text(self.attempt_refs, "attempt_refs"))
        object.__setattr__(self, "evidence_refs", _tuple_text(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "controlled_variables", _mapping(self.controlled_variables, "controlled_variables", required=False))
        object.__setattr__(self, "signature", _text(self.signature, "signature"))
        object.__setattr__(self, "comparison", _text(self.comparison, "comparison"))
        object.__setattr__(self, "blocking_basis", _optional_text(self.blocking_basis, "blocking_basis"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "reproducibility_id": self.reproducibility_id, "candidate_id": self.candidate_id,
            "status": self.status, "attempt_refs": list(self.attempt_refs),
            "evidence_refs": list(self.evidence_refs), "controlled_variables": dict(self.controlled_variables),
            "signature": self.signature, "comparison": self.comparison, "blocking_basis": self.blocking_basis,
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "reproducibility_digest", body, self.reproducibility_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reproducibility_id": self.reproducibility_id, "candidate_id": self.candidate_id,
            "status": self.status, "attempt_refs": list(self.attempt_refs), "evidence_refs": list(self.evidence_refs),
            "controlled_variables": dict(self.controlled_variables), "signature": self.signature,
            "comparison": self.comparison, "blocking_basis": self.blocking_basis,
            "origin_lineage": dict(self.origin_lineage), "reproducibility_digest": self.reproducibility_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReproducibilityAssessment":
        raw = _mapping(value, "reproducibility")
        return cls(
            raw["reproducibility_id"], raw["candidate_id"], raw["status"],
            tuple(raw.get("attempt_refs") or ()), tuple(raw.get("evidence_refs") or ()),
            raw.get("controlled_variables") or {}, raw["signature"], raw["comparison"],
            raw.get("blocking_basis"), raw.get("origin_lineage") or {}, raw.get("reproducibility_digest"),
        )


@dataclass(frozen=True)
class FalsePositiveAssessment:
    false_positive_id: str
    candidate_id: str
    status: str
    alternatives_considered: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    decision_basis: str
    origin_lineage: Mapping[str, Any]
    false_positive_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "false_positive_id", _text(self.false_positive_id, "false_positive_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        status = _text(self.status, "status")
        if status not in FALSE_POSITIVE_STATES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid false-positive state")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "alternatives_considered", _tuple_text(self.alternatives_considered, "alternatives_considered", required=True))
        object.__setattr__(self, "evidence_refs", _tuple_text(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "unresolved_refs", _tuple_text(self.unresolved_refs, "unresolved_refs"))
        object.__setattr__(self, "decision_basis", _text(self.decision_basis, "decision_basis"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "false_positive_id": self.false_positive_id, "candidate_id": self.candidate_id,
            "status": self.status, "alternatives_considered": list(self.alternatives_considered),
            "evidence_refs": list(self.evidence_refs), "unresolved_refs": list(self.unresolved_refs),
            "decision_basis": self.decision_basis, "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "false_positive_digest", body, self.false_positive_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "false_positive_id": self.false_positive_id, "candidate_id": self.candidate_id,
            "status": self.status, "alternatives_considered": list(self.alternatives_considered),
            "evidence_refs": list(self.evidence_refs), "unresolved_refs": list(self.unresolved_refs),
            "decision_basis": self.decision_basis, "origin_lineage": dict(self.origin_lineage),
            "false_positive_digest": self.false_positive_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FalsePositiveAssessment":
        raw = _mapping(value, "false_positive")
        return cls(
            raw["false_positive_id"], raw["candidate_id"], raw["status"],
            tuple(raw.get("alternatives_considered") or ()), tuple(raw.get("evidence_refs") or ()),
            tuple(raw.get("unresolved_refs") or ()), raw["decision_basis"],
            raw.get("origin_lineage") or {}, raw.get("false_positive_digest"),
        )


@dataclass(frozen=True)
class DefectAssessment:
    assessment_id: str
    candidate_id: str
    outcome: str
    final_classification: str
    evidence_assessment_refs: tuple[str, ...]
    reproducibility_ref: str
    false_positive_ref: str
    causal_basis_refs: tuple[str, ...]
    unresolved_contradiction_refs: tuple[str, ...]
    evidence_class: str
    decision_basis: str
    origin_lineage: Mapping[str, Any]
    defect_assessment_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        outcome = _text(self.outcome, "outcome")
        if outcome not in DEFECT_ASSESSMENT_OUTCOMES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid defect assessment outcome")
        object.__setattr__(self, "outcome", outcome)
        classification = _text(self.final_classification, "final_classification")
        if classification not in FINAL_CLASSIFICATIONS:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid final classification")
        object.__setattr__(self, "final_classification", classification)
        object.__setattr__(self, "evidence_assessment_refs", _tuple_text(self.evidence_assessment_refs, "evidence_assessment_refs", required=True))
        object.__setattr__(self, "reproducibility_ref", _text(self.reproducibility_ref, "reproducibility_ref"))
        object.__setattr__(self, "false_positive_ref", _text(self.false_positive_ref, "false_positive_ref"))
        object.__setattr__(self, "causal_basis_refs", _tuple_text(self.causal_basis_refs, "causal_basis_refs"))
        object.__setattr__(self, "unresolved_contradiction_refs", _tuple_text(self.unresolved_contradiction_refs, "unresolved_contradiction_refs"))
        evidence_class = _text(self.evidence_class, "evidence_class")
        if evidence_class not in EVIDENCE_CLASSES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid assessment evidence class")
        object.__setattr__(self, "evidence_class", evidence_class)
        object.__setattr__(self, "decision_basis", _text(self.decision_basis, "decision_basis"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "assessment_id": self.assessment_id, "candidate_id": self.candidate_id, "outcome": self.outcome,
            "final_classification": self.final_classification, "evidence_assessment_refs": list(self.evidence_assessment_refs),
            "reproducibility_ref": self.reproducibility_ref, "false_positive_ref": self.false_positive_ref,
            "causal_basis_refs": list(self.causal_basis_refs),
            "unresolved_contradiction_refs": list(self.unresolved_contradiction_refs),
            "evidence_class": self.evidence_class, "decision_basis": self.decision_basis,
            "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "defect_assessment_digest", body, self.defect_assessment_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id, "candidate_id": self.candidate_id, "outcome": self.outcome,
            "final_classification": self.final_classification, "evidence_assessment_refs": list(self.evidence_assessment_refs),
            "reproducibility_ref": self.reproducibility_ref, "false_positive_ref": self.false_positive_ref,
            "causal_basis_refs": list(self.causal_basis_refs),
            "unresolved_contradiction_refs": list(self.unresolved_contradiction_refs),
            "evidence_class": self.evidence_class, "decision_basis": self.decision_basis,
            "origin_lineage": dict(self.origin_lineage), "defect_assessment_digest": self.defect_assessment_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DefectAssessment":
        raw = _mapping(value, "defect_assessment")
        return cls(
            raw["assessment_id"], raw["candidate_id"], raw["outcome"], raw["final_classification"],
            tuple(raw.get("evidence_assessment_refs") or ()), raw["reproducibility_ref"], raw["false_positive_ref"],
            tuple(raw.get("causal_basis_refs") or ()), tuple(raw.get("unresolved_contradiction_refs") or ()),
            raw.get("evidence_class", "ENGINEERING_EVIDENCE"), raw["decision_basis"],
            raw.get("origin_lineage") or {}, raw.get("defect_assessment_digest"),
        )


@dataclass(frozen=True)
class RCARecord:
    rca_id: str
    candidate_id: str
    cause_class: str
    status: str
    causal_chain_refs: tuple[Mapping[str, Any], ...]
    root_component: str | None
    contradiction_refs: tuple[str, ...]
    decision_basis: str
    origin_lineage: Mapping[str, Any]
    rca_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rca_id", _text(self.rca_id, "rca_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        cause = _text(self.cause_class, "cause_class")
        if cause not in RCA_CAUSES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid RCA cause class")
        object.__setattr__(self, "cause_class", cause)
        status = _text(self.status, "status")
        if status not in RCA_STATES:
            raise R36Error("R3_6_SCHEMA_INVALID", "invalid RCA status")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "causal_chain_refs", _refs(self.causal_chain_refs, "causal_chain_refs", required=status == "ESTABLISHED"))
        object.__setattr__(self, "root_component", _optional_text(self.root_component, "root_component"))
        object.__setattr__(self, "contradiction_refs", _tuple_text(self.contradiction_refs, "contradiction_refs"))
        object.__setattr__(self, "decision_basis", _text(self.decision_basis, "decision_basis"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "rca_id": self.rca_id, "candidate_id": self.candidate_id, "cause_class": self.cause_class,
            "status": self.status, "causal_chain_refs": [dict(item) for item in self.causal_chain_refs],
            "root_component": self.root_component, "contradiction_refs": list(self.contradiction_refs),
            "decision_basis": self.decision_basis, "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "rca_digest", body, self.rca_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rca_id": self.rca_id, "candidate_id": self.candidate_id, "cause_class": self.cause_class,
            "status": self.status, "causal_chain_refs": [dict(item) for item in self.causal_chain_refs],
            "root_component": self.root_component, "contradiction_refs": list(self.contradiction_refs),
            "decision_basis": self.decision_basis, "origin_lineage": dict(self.origin_lineage),
            "rca_digest": self.rca_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RCARecord":
        raw = _mapping(value, "rca")
        return cls(
            raw["rca_id"], raw["candidate_id"], raw["cause_class"], raw["status"],
            tuple(raw.get("causal_chain_refs") or ()), raw.get("root_component"),
            tuple(raw.get("contradiction_refs") or ()), raw["decision_basis"],
            raw.get("origin_lineage") or {}, raw.get("rca_digest"),
        )


@dataclass(frozen=True)
class InvestigationCheckpoint:
    checkpoint_id: str
    candidate_id: str
    cursor: str | None
    workset_digest: str
    session_ref: str | None
    omitted_refs: tuple[str, ...]
    origin_lineage: Mapping[str, Any]
    checkpoint_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "checkpoint_id", _text(self.checkpoint_id, "checkpoint_id"))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "cursor", _optional_text(self.cursor, "cursor"))
        object.__setattr__(self, "workset_digest", _text(self.workset_digest, "workset_digest"))
        object.__setattr__(self, "session_ref", _optional_text(self.session_ref, "session_ref"))
        object.__setattr__(self, "omitted_refs", _tuple_text(self.omitted_refs, "omitted_refs"))
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
        body = {
            "checkpoint_id": self.checkpoint_id, "candidate_id": self.candidate_id, "cursor": self.cursor,
            "workset_digest": self.workset_digest, "session_ref": self.session_ref,
            "omitted_refs": list(self.omitted_refs), "origin_lineage": dict(self.origin_lineage),
        }
        _finish(self, "checkpoint_digest", body, self.checkpoint_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "candidate_id": self.candidate_id, "cursor": self.cursor,
            "workset_digest": self.workset_digest, "session_ref": self.session_ref,
            "omitted_refs": list(self.omitted_refs), "origin_lineage": dict(self.origin_lineage),
            "checkpoint_digest": self.checkpoint_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestigationCheckpoint":
        raw = _mapping(value, "checkpoint")
        return cls(
            raw["checkpoint_id"], raw["candidate_id"], raw.get("cursor"), raw["workset_digest"],
            raw.get("session_ref"), tuple(raw.get("omitted_refs") or ()),
            raw.get("origin_lineage") or {}, raw.get("checkpoint_digest"),
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
        object.__setattr__(self, "origin_lineage", _mapping(self.origin_lineage, "origin_lineage"))
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
        raw = _mapping(value, "reuse")
        return cls(
            raw["reuse_id"], raw["entity_kind"], raw["entity_id"], raw["entity_digest"],
            raw["original_command_id"], raw.get("origin_lineage") or {}, raw.get("reuse_digest"),
        )


@dataclass(frozen=True)
class R36State:
    mission_id: str
    anomalies: tuple[TestAnomaly, ...] = ()
    candidates: tuple[DefectCandidate, ...] = ()
    deepenings: tuple[EvidenceDeepeningReceipt, ...] = ()
    evidence_assessments: tuple[EvidenceAssessment, ...] = ()
    correlations: tuple[CrossSourceCorrelation, ...] = ()
    reproducibility_assessments: tuple[ReproducibilityAssessment, ...] = ()
    false_positive_assessments: tuple[FalsePositiveAssessment, ...] = ()
    defect_assessments: tuple[DefectAssessment, ...] = ()
    rca_records: tuple[RCARecord, ...] = ()
    checkpoints: tuple[InvestigationCheckpoint, ...] = ()
    reuses: tuple[SemanticReuse, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))

    def _find(self, values: tuple[Any, ...], name: str, value: str) -> Any | None:
        return next((item for item in values if getattr(item, name) == value), None)

    def anomaly(self, value: str) -> TestAnomaly | None:
        return self._find(self.anomalies, "anomaly_id", value)

    def candidate(self, value: str) -> DefectCandidate | None:
        return self._find(self.candidates, "candidate_id", value)

    def deepening(self, value: str) -> EvidenceDeepeningReceipt | None:
        return self._find(self.deepenings, "deepening_id", value)

    def evidence_assessment(self, value: str) -> EvidenceAssessment | None:
        return self._find(self.evidence_assessments, "assessment_id", value)

    def correlation(self, value: str) -> CrossSourceCorrelation | None:
        return self._find(self.correlations, "correlation_id", value)

    def reproducibility(self, value: str) -> ReproducibilityAssessment | None:
        return self._find(self.reproducibility_assessments, "reproducibility_id", value)

    def false_positive(self, value: str) -> FalsePositiveAssessment | None:
        return self._find(self.false_positive_assessments, "false_positive_id", value)

    def defect_assessment(self, value: str) -> DefectAssessment | None:
        return self._find(self.defect_assessments, "assessment_id", value)

    def rca(self, value: str) -> RCARecord | None:
        return self._find(self.rca_records, "rca_id", value)

    def checkpoint(self, value: str) -> InvestigationCheckpoint | None:
        return self._find(self.checkpoints, "checkpoint_id", value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "anomalies": [item.to_dict() for item in self.anomalies],
            "candidates": [item.to_dict() for item in self.candidates],
            "deepenings": [item.to_dict() for item in self.deepenings],
            "evidence_assessments": [item.to_dict() for item in self.evidence_assessments],
            "correlations": [item.to_dict() for item in self.correlations],
            "reproducibility_assessments": [item.to_dict() for item in self.reproducibility_assessments],
            "false_positive_assessments": [item.to_dict() for item in self.false_positive_assessments],
            "defect_assessments": [item.to_dict() for item in self.defect_assessments],
            "rca_records": [item.to_dict() for item in self.rca_records],
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "reuses": [item.to_dict() for item in self.reuses],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R36State":
        raw = _mapping(value, "r36_state")
        return cls(
            raw["mission_id"],
            tuple(TestAnomaly.from_dict(item) for item in raw.get("anomalies") or ()),
            tuple(DefectCandidate.from_dict(item) for item in raw.get("candidates") or ()),
            tuple(EvidenceDeepeningReceipt.from_dict(item) for item in raw.get("deepenings") or ()),
            tuple(EvidenceAssessment.from_dict(item) for item in raw.get("evidence_assessments") or ()),
            tuple(CrossSourceCorrelation.from_dict(item) for item in raw.get("correlations") or ()),
            tuple(ReproducibilityAssessment.from_dict(item) for item in raw.get("reproducibility_assessments") or ()),
            tuple(FalsePositiveAssessment.from_dict(item) for item in raw.get("false_positive_assessments") or ()),
            tuple(DefectAssessment.from_dict(item) for item in raw.get("defect_assessments") or ()),
            tuple(RCARecord.from_dict(item) for item in raw.get("rca_records") or ()),
            tuple(InvestigationCheckpoint.from_dict(item) for item in raw.get("checkpoints") or ()),
            tuple(SemanticReuse.from_dict(item) for item in raw.get("reuses") or ()),
        )
