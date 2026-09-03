from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256

EXTENSION_ID = "g4_real_execution_goal_convergence"
EXTENSION_VERSION = "1.0.0"
RECORD_FACT = "G4_RECORD_FACT.v1"
FACT_RECORDED = "g4.fact_recorded.v1"
COMMAND_TYPES = frozenset({RECORD_FACT})
EVENT_TYPES = frozenset({FACT_RECORDED})

FACT_KINDS = frozenset({
    "TESTING_GOAL", "STEP_CURSOR", "CAPABILITY_STATUS", "BROWSER_LEASE",
    "HUMAN_TAKEOVER_REQUEST", "HUMAN_GATE_USER_TURN_RESUME_REQUEST",
    "EXECUTION_STEP_RESULT", "EVIDENCE_BUNDLE",
    "EXECUTION_BATCH", "COVERAGE_MEASUREMENT", "GOAL_EVALUATION",
    "TEST_LOOP_ITERATION", "BLOCKER_GAP", "REPLAN_REQUEST", "RISK_ACCEPTANCE",
    "UNEXPECTED_OBSERVATION", "TESTING_GOAL_STATUS", "HUMAN_GATE_BINDING",
    "BROWSER_TAKEOVER_RECONCILIATION",
})

GOAL_STATUSES = frozenset({
    "PROPOSED", "ACTIVE", "EXECUTING", "MEASURING", "REPLANNING",
    "WAITING_HUMAN", "WAITING_COVERAGE_REFRESH", "WAITING_ENVIRONMENT",
    "WAITING_APPROVAL", "SATISFIED", "COMPLETED_WITH_ACCEPTED_GAP",
    "BLOCKED", "CANCELLED", "STOPPED",
})
CAPABILITY_STATUSES = frozenset({"AVAILABLE", "PARTIAL", "UNAVAILABLE", "AUTH_REQUIRED", "APPROVAL_REQUIRED"})
ORACLE_STATUSES = frozenset({"PASS", "FAIL", "INCONCLUSIVE", "BLOCKED", "ERROR"})
COVERAGE_STATES = frozenset({"REQUESTED", "AUTH_REQUIRED", "WAITING_REFRESH", "AVAILABLE", "STALE", "SOURCE_UNAVAILABLE", "SOURCE_IDENTITY_MISMATCH", "FAILED"})
LEASE_STATES = frozenset({"AI_CONTROLLED", "TAKEOVER_REQUESTED", "HUMAN_CONTROLLED", "HUMAN_COMPLETED_PENDING_VERIFY", "AI_RECLAIMING", "CONTEXT_EXPIRED", "BLOCKED", "CANCELLED"})
ITERATION_STATUSES = frozenset({"PROGRESSING", "PLATEAU", "BLOCKED", "TARGET_REACHED", "WAITING_MEASUREMENT"})
GAP_KINDS = frozenset({
    "TEST_DESIGN_GAP", "TEST_DATA_GAP", "AUTH_GAP", "PERMISSION_GAP",
    "ENVIRONMENT_GAP", "SOURCE_DATA_GAP", "DEPLOYMENT_GAP", "MANUAL_ACTION_REQUIRED",
    "POSSIBLY_UNREACHABLE", "COVERAGE_SOURCE_STALE", "SOURCE_IDENTITY_MISMATCH", "UNKNOWN",
})
SENSITIVE_KEY_FRAGMENTS = (
    "password", "passwd", "pwd", "secret", "otp", "captcha", "face_image",
    "access_token", "refresh_token", "authorization", "cookie_value", "private_key", "credential",
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|pwd|otp|captcha|access[_-]?token|refresh[_-]?token|authorization|secret|cookie)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)^Bearer\s+[A-Za-z0-9._~+/-]+=*$"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
)
REDACTED_SENSITIVE_VALUE = "[REDACTED:SENSITIVE]"


def _sanitize_text(value: str, path: str) -> str:
    if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
        return REDACTED_SENSITIVE_VALUE
    # OTP/captcha values are frequently passed through generic fields such as
    # actual/body/metadata. In evidence-bearing paths, a bare 4-8 digit value
    # is treated as sensitive rather than risking durable credential leakage.
    low_path = path.lower()
    if re.fullmatch(r"\d{4,8}", value.strip()) and any(token in low_path for token in ("actual", "body", "metadata", "evidence", "credential")):
        return REDACTED_SENSITIVE_VALUE
    return value


def sanitize_durable_payload(value: Any, path: str = "payload") -> Any:
    return _json(value, path)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("G4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _json(value: Any, path: str = "payload") -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return _sanitize_text(value, path)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeError("G4_SCHEMA_INVALID", f"{path} contains non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeError("G4_SCHEMA_INVALID", f"{path} object keys must be strings")
            lowered = key.lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise RuntimeError("G4_SECRET_FORBIDDEN", f"durable G4 fact cannot contain sensitive field: {path}.{key}")
            result[key] = _json(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item, f"{path}[]") for item in value]
    if isinstance(value, Enum):
        return value.value
    raise RuntimeError("G4_SCHEMA_INVALID", f"{path} must contain canonical JSON values")


@dataclass(frozen=True)
class G4Fact:
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
            raise RuntimeError("G4_FACT_KIND_UNSUPPORTED", kind)
        object.__setattr__(self, "fact_kind", kind)
        object.__setattr__(self, "payload", _json(dict(self.payload)))
        object.__setattr__(self, "provenance_refs", tuple(_text(v, "provenance_ref") for v in self.provenance_refs))
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if not isinstance(self.created_seq, int) or self.created_seq < 1:
            raise RuntimeError("G4_SCHEMA_INVALID", "created_seq must be positive")
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))

    @property
    def digest(self) -> str:
        return canonical_sha256({
            "fact_id": self.fact_id, "fact_kind": self.fact_kind, "mission_id": self.mission_id,
            "payload": dict(self.payload), "provenance_refs": list(self.provenance_refs),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id, "fact_kind": self.fact_kind, "mission_id": self.mission_id,
            "payload": dict(self.payload), "provenance_refs": list(self.provenance_refs),
            "idempotency_key": self.idempotency_key, "correlation_id": self.correlation_id,
            "created_seq": self.created_seq, "created_at": self.created_at, "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G4Fact":
        return cls(
            fact_id=value["fact_id"], fact_kind=value["fact_kind"], mission_id=value["mission_id"],
            payload=value.get("payload") or {}, provenance_refs=tuple(value.get("provenance_refs") or ()),
            idempotency_key=value["idempotency_key"], correlation_id=value["correlation_id"],
            created_seq=int(value["created_seq"]), created_at=value["created_at"],
        )


@dataclass(frozen=True)
class G4State:
    mission_id: str
    facts: tuple[G4Fact, ...] = ()

    def by_id(self, fact_id: str) -> G4Fact | None:
        return next((item for item in self.facts if item.fact_id == fact_id), None)

    def by_kind(self, fact_kind: str) -> tuple[G4Fact, ...]:
        key = str(fact_kind).upper()
        return tuple(item for item in self.facts if item.fact_kind == key)

    def latest(self, fact_kind: str, predicate: Any | None = None) -> G4Fact | None:
        items = self.by_kind(fact_kind)
        if predicate is not None:
            items = tuple(item for item in items if predicate(item))
        return items[-1] if items else None

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "facts": [item.to_dict() for item in self.facts]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "G4State":
        return cls(str(value["mission_id"]), tuple(G4Fact.from_dict(item) for item in value.get("facts") or ()))


def require_percentage(value: Any, name: str = "target_pct") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 100:
        raise RuntimeError("G4_COVERAGE_PERCENT_INVALID", f"{name} must be 0..100")
    return float(value)


def same_browser_context(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = ("browser_session_id", "browser_context_id_or_epoch", "context_binding_digest")
    return all(str(left.get(key) or "") == str(right.get(key) or "") and bool(left.get(key)) for key in keys)
