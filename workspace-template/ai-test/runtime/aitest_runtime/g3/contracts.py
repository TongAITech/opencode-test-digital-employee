from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256

EXTENSION_ID = "g3_testing_intelligence_product_integration"
EXTENSION_VERSION = "1.0.0"
RECORD_FACT = "G3_RECORD_FACT.v1"
FACT_RECORDED = "g3.fact_recorded.v1"
COMMAND_TYPES = frozenset({RECORD_FACT})
EVENT_TYPES = frozenset({FACT_RECORDED})

TEST_INTENTS = frozenset({
    "FULL_RELEASE_TEST", "FULL_REQUIREMENT_TEST", "RECOMMEND_NEXT_TEST_WORK",
    "REQUIREMENT_ANALYSIS", "CHANGE_IMPACT_ANALYSIS", "TEST_STRATEGY_DESIGN",
    "TEST_CASE_DESIGN", "COVERAGE_GAP_ANALYSIS", "API_TEST_REQUEST",
    "UI_TEST_REQUEST", "API_SECURITY_TEST_REQUEST", "API_PERFORMANCE_TEST_REQUEST",
    "CASE_EXECUTION_REQUEST", "DEFECT_DIAGNOSIS_REQUEST",
})
HOLD_INTENTS = {
    "CASE_EXECUTION_REQUEST": "HOLD_G4",
    "DEFECT_DIAGNOSIS_REQUEST": "HOLD_G5",
}
FACT_KINDS = frozenset({
    "TEST_INTENT", "REQUIREMENT_SEMANTIC_MODEL", "KNOWLEDGE_GAP", "HUMAN_TASK",
    "MULTI_REPO_CHANGE_ANALYSIS", "CODE_COVERAGE_OBJECTIVE", "COVERAGE_PLATFORM_PROFILE",
    "INCREMENTAL_COVERAGE_SNAPSHOT", "COVERAGE_RECONCILIATION", "COVERAGE_GAP",
    "RISK_VECTOR", "DEFECT_HYPOTHESIS", "TEST_STRATEGY_PORTFOLIO", "CASE_SPECIFICATION",
    "CASE_VALUE_LINK", "TEST_PROFILE", "DESIGN_EVALUATION", "HUMAN_REVIEW_REQUEST",
})

SENSITIVE_KEY_FRAGMENTS = (
    "password", "passwd", "pwd", "secret", "access_token", "refresh_token", "authorization",
    "cookie_value", "private_key", "credential",
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("G3_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _json(value: Any, path: str = "payload") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeError("G3_SCHEMA_INVALID", f"{path} contains non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeError("G3_SCHEMA_INVALID", f"{path} object keys must be strings")
            lowered = key.lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise RuntimeError("G3_SECRET_FORBIDDEN", f"durable G3 fact cannot contain sensitive field: {path}.{key}")
            result[key] = _json(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item, f"{path}[]") for item in value]
    if isinstance(value, Enum):
        return value.value
    raise RuntimeError("G3_SCHEMA_INVALID", f"{path} must contain canonical JSON values")


@dataclass(frozen=True)
class G3Fact:
    fact_id: str
    fact_kind: str
    mission_id: str
    payload: Mapping[str, Any]
    provenance_refs: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    created_seq: int
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _text(self.fact_id, "fact_id"))
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        kind = _text(self.fact_kind, "fact_kind").upper()
        if kind not in FACT_KINDS:
            raise RuntimeError("G3_FACT_KIND_UNSUPPORTED", kind)
        object.__setattr__(self, "fact_kind", kind)
        object.__setattr__(self, "payload", _json(dict(self.payload)))
        object.__setattr__(self, "provenance_refs", tuple(_text(v, "provenance_ref") for v in self.provenance_refs))
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if not isinstance(self.created_seq, int) or self.created_seq < 1:
            raise RuntimeError("G3_SCHEMA_INVALID", "created_seq must be positive")
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))

    @property
    def digest(self) -> str:
        return canonical_sha256({
            "fact_id": self.fact_id,
            "fact_kind": self.fact_kind,
            "mission_id": self.mission_id,
            "payload": dict(self.payload),
            "provenance_refs": list(self.provenance_refs),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "fact_kind": self.fact_kind,
            "mission_id": self.mission_id,
            "payload": dict(self.payload),
            "provenance_refs": list(self.provenance_refs),
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G3Fact":
        return cls(
            fact_id=value["fact_id"], fact_kind=value["fact_kind"], mission_id=value["mission_id"],
            payload=value.get("payload") or {}, provenance_refs=tuple(value.get("provenance_refs") or ()),
            idempotency_key=value["idempotency_key"], correlation_id=value["correlation_id"],
            created_seq=int(value["created_seq"]), created_at=value["created_at"],
        )


@dataclass(frozen=True)
class G3State:
    mission_id: str
    facts: tuple[G3Fact, ...] = ()

    def by_id(self, fact_id: str) -> G3Fact | None:
        return next((item for item in self.facts if item.fact_id == fact_id), None)

    def by_kind(self, fact_kind: str) -> tuple[G3Fact, ...]:
        key = str(fact_kind).upper()
        return tuple(item for item in self.facts if item.fact_kind == key)

    def latest(self, fact_kind: str, predicate: Any | None = None) -> G3Fact | None:
        """Return the latest fact in canonical Event Stream order."""
        items = self.by_kind(fact_kind)
        if predicate is not None:
            items = tuple(item for item in items if predicate(item))
        return items[-1] if items else None

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "facts": [item.to_dict() for item in self.facts]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G3State":
        return cls(str(value["mission_id"]), tuple(G3Fact.from_dict(item) for item in value.get("facts") or ()))


def validate_test_intent(intent_type: str, scope: Mapping[str, Any], constraints: Mapping[str, Any] | None = None) -> dict[str, Any]:
    intent = _text(intent_type, "intent_type").upper()
    if intent not in TEST_INTENTS:
        raise RuntimeError("G3_TEST_INTENT_UNSUPPORTED", intent)
    payload = {"intent_type": intent, "scope": _json(dict(scope), "scope"), "constraints": _json(dict(constraints or {}), "constraints")}
    if intent in HOLD_INTENTS:
        payload["hold_code"] = HOLD_INTENTS[intent]
        payload["gate"] = "G4_REAL_EXECUTION" if intent == "CASE_EXECUTION_REQUEST" else "G5_DEFECT_TRUTH"
        payload["status"] = "HOLD"
    else:
        payload["status"] = "ACCEPTED"
    return payload


def validate_requirement_semantics(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _json(dict(value), "requirement_semantics")
    required_arrays = (
        "business_rules", "field_data_rules", "state_transitions", "positive_paths", "negative_paths",
        "exception_paths", "boundary_rules", "permission_rules", "cross_system_flows", "acceptance_criteria",
        "non_functional_risks", "unknowns",
    )
    for name in required_arrays:
        if name not in data or not isinstance(data[name], list):
            raise RuntimeError("G3_REQUIREMENT_SEMANTICS_INCOMPLETE", f"{name} must be an array")
    if not data.get("source_refs") or not isinstance(data["source_refs"], list):
        raise RuntimeError("G3_REQUIREMENT_PROVENANCE_REQUIRED", "source_refs are required")
    return data


def validate_coverage_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _json(dict(value), "coverage_snapshot")
    for name in ("snapshot_id", "application_id", "target_version", "baseline_label", "observed_at", "coverage_semantics", "source_identity"):
        _text(data.get(name), name)
    if data["baseline_label"] != "master":
        raise RuntimeError("G3_COVERAGE_BASELINE_INVALID", "baseline_label must be master")
    if data["coverage_semantics"] != "BANK_EFFECTIVE_INCREMENTAL":
        raise RuntimeError("G3_COVERAGE_SEMANTICS_INVALID", "actual coverage must use BANK_EFFECTIVE_INCREMENTAL")
    pct = data.get("effective_incremental_coverage_pct")
    if pct is not None and (isinstance(pct, bool) or not isinstance(pct, (int, float)) or pct < 0 or pct > 100):
        raise RuntimeError("G3_COVERAGE_PERCENT_INVALID", "coverage percentage must be null or 0..100")
    details = data.get("details") or []
    if not isinstance(details, list):
        raise RuntimeError("G3_COVERAGE_DETAILS_INVALID", "details must be an array")
    allowed = {"APPLICATION", "FILE", "CLASS", "LINE"}
    for item in details:
        if not isinstance(item, Mapping) or str(item.get("level") or "").upper() not in allowed:
            raise RuntimeError("G3_COVERAGE_DETAILS_INVALID", "detail level must be APPLICATION/FILE/CLASS/LINE")
    baseline_commit = data.get("baseline_commit")
    data["baseline_identity_status"] = "COMMIT_PINNED" if isinstance(baseline_commit, str) and baseline_commit.strip() and baseline_commit != "UNKNOWN" else "MASTER_ALIAS_ONLY"
    return data


_PLACEHOLDER_PATTERNS = (
    "执行正向数据", "符合预期", "exercise governed boundary", "exercise boundary", "normal data", "expected result",
)


def validate_detailed_case(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _json(dict(value), "case_spec")
    required = ("objective", "preconditions", "test_data", "ordered_steps", "expected_results", "oracle", "evidence_requirements", "postcondition")
    for name in required:
        if name not in data or data[name] in (None, "", [], {}):
            raise RuntimeError("G3_CASE_DETAIL_REQUIRED", f"{name} is required")
    if not isinstance(data["preconditions"], list) or not isinstance(data["ordered_steps"], list) or not isinstance(data["expected_results"], list) or not isinstance(data["evidence_requirements"], list):
        raise RuntimeError("G3_CASE_DETAIL_REQUIRED", "preconditions/ordered_steps/expected_results/evidence_requirements must be arrays")
    if len(data["ordered_steps"]) != len(data["expected_results"]):
        raise RuntimeError("G3_CASE_STEP_EXPECTED_MISMATCH", "each ordered step requires an expected result")
    searchable = str(data).lower()
    for phrase in _PLACEHOLDER_PATTERNS:
        if phrase.lower() in searchable:
            raise RuntimeError("G3_LOW_INFORMATION_CASE_REJECTED", phrase)
    return data


def validate_defect_hypothesis(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _json(dict(value), "defect_hypothesis")
    required = ("hypothesis_id", "trigger", "expected_invariant", "suspected_surface", "evidence_requirement", "discriminating_test", "defect_class", "severity", "confidence_basis")
    for name in required:
        if data.get(name) in (None, "", [], {}):
            raise RuntimeError("G3_HYPOTHESIS_INCOMPLETE", f"{name} is required")
    status = str(data.get("status") or "PROPOSED").upper()
    if status not in {"PROPOSED", "READY_TO_TEST", "REJECTED"}:
        raise RuntimeError("G3_DEFECT_TRUTH_BOUNDARY", "G3 hypothesis cannot become a confirmed defect")
    data["status"] = status
    return data
