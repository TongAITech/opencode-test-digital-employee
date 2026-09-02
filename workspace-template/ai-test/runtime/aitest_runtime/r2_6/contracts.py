from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r2_6_human_gate"
EXTENSION_VERSION = "1"
R26_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
CANONICALIZATION_VERSION = 1

OPEN_HUMAN_GATE = "R26_OPEN_HUMAN_GATE"
RECORD_HUMAN_DECISION = "R26_RECORD_HUMAN_DECISION"
ESCALATE_HUMAN_GATE = "R26_ESCALATE_HUMAN_GATE"
CANCEL_HUMAN_GATE = "R26_CANCEL_HUMAN_GATE"
EXPIRE_HUMAN_GATE = "R26_EXPIRE_HUMAN_GATE"
RECORD_CONTINUATION = "R26_RECORD_CONTINUATION"

HUMAN_GATE_OPENED = "r2_6.human_gate_opened.v1"
HUMAN_GATE_DECISION_RECORDED = "r2_6.human_gate_decision_recorded.v1"
HUMAN_GATE_ESCALATED = "r2_6.human_gate_escalated.v1"
HUMAN_GATE_CANCELLED = "r2_6.human_gate_cancelled.v1"
HUMAN_GATE_EXPIRED = "r2_6.human_gate_expired.v1"
HUMAN_GATE_CONTINUATION_RECORDED = "r2_6.human_gate_continuation_recorded.v1"

COMMAND_TYPES = frozenset(
    {
        OPEN_HUMAN_GATE,
        RECORD_HUMAN_DECISION,
        ESCALATE_HUMAN_GATE,
        CANCEL_HUMAN_GATE,
        EXPIRE_HUMAN_GATE,
        RECORD_CONTINUATION,
    }
)
EVENT_TYPES = frozenset(
    {
        HUMAN_GATE_OPENED,
        HUMAN_GATE_DECISION_RECORDED,
        HUMAN_GATE_ESCALATED,
        HUMAN_GATE_CANCELLED,
        HUMAN_GATE_EXPIRED,
        HUMAN_GATE_CONTINUATION_RECORDED,
    }
)

PENDING = "PENDING"
RESOLVED = "RESOLVED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"

NOT_REQUIRED = "NOT_REQUIRED"
CONTINUATION_PENDING = "PENDING"
APPLIED = "APPLIED"

INLINE_NON_SECRET = "INLINE_NON_SECRET"
REFERENCE = "REFERENCE"

APPROVED = "APPROVED"
REJECTED = "REJECTED"
CHOICE_SELECTED = "CHOICE_SELECTED"
INFORMATION_PROVIDED = "INFORMATION_PROVIDED"
EXTERNAL_ACTION_COMPLETED = "EXTERNAL_ACTION_COMPLETED"
OUTCOMES = frozenset(
    {APPROVED, REJECTED, CHOICE_SELECTED, INFORMATION_PROVIDED, EXTERNAL_ACTION_COMPLETED}
)

NONE = "NONE"
RESUME_EXECUTION = "RESUME_EXECUTION"
GOAL_REVISION = "GOAL_REVISION"
PLAN_REVISION = "PLAN_REVISION"
BLOCK = "BLOCK"
ROUTES = frozenset({NONE, RESUME_EXECUTION, GOAL_REVISION, PLAN_REVISION, BLOCK})

APPROVED_ROUTES = frozenset({NONE, RESUME_EXECUTION})
REJECTED_ROUTES = frozenset({BLOCK})

GATE_KINDS = frozenset({"APPROVAL", "CHOICE", "ADDITIONAL_INFORMATION", "EXTERNAL_ACTION"})
PAYLOAD_MODES = frozenset({INLINE_NON_SECRET, REFERENCE})
TERMINAL_STATUSES = frozenset({RESOLVED, CANCELLED, EXPIRED})

R26_ERROR_CODES = frozenset(
    {
        "R2_6_GATE_NOT_FOUND",
        "R2_6_GATE_NOT_PENDING",
        "R2_6_ACTIVE_GATE_CONFLICT",
        "R2_6_GATE_REVISION_CONFLICT",
        "R2_6_CONTINUATION_REVISION_CONFLICT",
        "R2_6_DECISION_ALREADY_RECORDED",
        "R2_6_DECISION_POLICY_VIOLATION",
        "R2_6_CONTINUATION_SOURCE_CONFLICT",
        "R2_6_EXPIRY_NOT_REACHED",
        "R2_6_PAYLOAD_SECURITY_VIOLATION",
        "R2_6_CANONICAL_BINDING_CONFLICT",
    }
)


class R26Error(RuntimeError):
    """Fail-closed R2.6 contract and runtime error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _non_negative(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name).lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _plain(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise R26Error("R2_6_SCHEMA_INVALID", f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item, f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, f"{name}[{index}]") for index, item in enumerate(value)]
    raise R26Error("R2_6_SCHEMA_INVALID", f"{name} contains an unsupported value")


def _provenance(value: Any, name: str) -> dict[str, Any]:
    raw = _mapping(value, name)
    if not isinstance(raw.get("source_ref"), str) or not raw["source_ref"].strip():
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name}.source_ref is required")
    if not isinstance(raw.get("source_digest"), str):
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name}.source_digest is required")
    _digest(raw["source_digest"], f"{name}.source_digest")
    if not isinstance(raw.get("observed_at"), str) or not raw["observed_at"].strip():
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name}.observed_at is required")
    return _plain(raw, name)


_SENSITIVE_KEY_PARTS = ("secret", "token", "credential", "password", "cookie", "private_key", "api_key")


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def validate_payload(mode: Any, payload: Any, digest: Any, name: str) -> tuple[str, Any, str]:
    mode = _text(mode, f"{name}.mode")
    if mode not in PAYLOAD_MODES:
        raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"unsupported {name} mode")
    normalized = _plain(payload, f"{name}.payload")
    expected_digest = _digest(digest, f"{name}.digest")
    if mode == INLINE_NON_SECRET:
        if _contains_sensitive_key(normalized):
            raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"{name} contains sensitive inline data")
        if canonical_sha256(normalized) != expected_digest:
            raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"{name} digest mismatch")
    else:
        if not isinstance(normalized, Mapping) or not normalized.get("reference"):
            raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"{name} reference is required")
        if _contains_sensitive_key(normalized) or set(normalized) != {"reference", "digest"}:
            raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"{name} reference must contain only reference and digest")
        _text(normalized["reference"], f"{name}.payload.reference")
        reference_digest = normalized.get("digest")
        if not isinstance(reference_digest, str) or _digest(reference_digest, f"{name}.payload.digest") != expected_digest:
            raise R26Error("R2_6_PAYLOAD_SECURITY_VIOLATION", f"{name} reference digest mismatch")
    return mode, normalized, expected_digest


def _timestamp(value: Any, name: str) -> str | None:
    if value is None:
        return None
    value = _text(value, name)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise R26Error("R2_6_SCHEMA_INVALID", f"{name} must be ISO-8601") from exc
    return value


def _allowed_routes(value: Any) -> dict[str, tuple[str, ...]]:
    raw = _mapping(value, "allowed_routes_by_outcome")
    if set(raw) != set(OUTCOMES):
        raise R26Error("R2_6_DECISION_POLICY_VIOLATION", "policy must define every outcome")
    result: dict[str, tuple[str, ...]] = {}
    for outcome in OUTCOMES:
        routes = raw[outcome]
        if not isinstance(routes, (list, tuple)) or not routes:
            raise R26Error("R2_6_DECISION_POLICY_VIOLATION", f"policy routes missing for {outcome}")
        normalized = tuple(_text(route, f"allowed_routes_by_outcome.{outcome}") for route in routes)
        if any(route not in ROUTES for route in normalized):
            raise R26Error("R2_6_DECISION_POLICY_VIOLATION", f"unsupported route for {outcome}")
        result[outcome] = normalized
    return result


def policy_digest(
    policy_id: str,
    policy_version: int,
    allowed_outcomes: tuple[str, ...],
    allowed_routes_by_outcome: Mapping[str, tuple[str, ...]],
) -> str:
    return canonical_sha256(
        {
            "decision_policy_id": policy_id,
            "decision_policy_version": policy_version,
            "allowed_outcomes": list(allowed_outcomes),
            "allowed_routes_by_outcome": {
                key: list(value) for key, value in sorted(allowed_routes_by_outcome.items())
            },
            "policy_snapshot_schema_version": 1,
        }
    )


@dataclass(frozen=True)
class HumanGateRecord:
    gate_id: str
    mission_id: str
    plan_id: str
    plan_revision_id: str
    task_id: str
    root_attempt_id: str
    origin_attempt_id: str
    origin_session_id: str
    gate_kind: str
    status: str
    request_payload_mode: str
    request_payload: Any
    request_digest: str
    response_schema: Mapping[str, Any]
    expires_at: str | None
    expiry_policy: str
    decision_policy_id: str
    decision_policy_version: int
    decision_policy_digest: str
    allowed_outcomes: tuple[str, ...]
    allowed_routes_by_outcome: Mapping[str, tuple[str, ...]]
    gate_revision: int
    continuation_revision: int
    continuation_state: str
    continuation_route: str | None = None
    decision_id: str | None = None
    decision_outcome: str | None = None
    decision_payload_mode: str | None = None
    decision_payload: Any = None
    decision_digest: str | None = None
    decision_provenance: Mapping[str, Any] | None = None
    continuation_reference: Mapping[str, Any] | None = None
    created_seq: int = 0
    created_at: str = ""
    created_by: Mapping[str, str] = None  # type: ignore[assignment]

    @property
    def binding(self) -> tuple[str, str, str]:
        return self.mission_id, self.task_id, self.root_attempt_id

    @property
    def is_unfinished(self) -> bool:
        return self.status == PENDING or (self.status == RESOLVED and self.continuation_state == CONTINUATION_PENDING)

    @property
    def is_blocking(self) -> bool:
        return self.is_unfinished or self.status in {CANCELLED, EXPIRED} or self.continuation_route == BLOCK or self.decision_outcome == REJECTED

    @property
    def is_allowing(self) -> bool:
        return self.status == RESOLVED and (
            self.continuation_state == NOT_REQUIRED
            or (self.continuation_state == APPLIED and self.continuation_route in {RESUME_EXECUTION, GOAL_REVISION, PLAN_REVISION})
        ) and self.continuation_route != BLOCK and self.decision_outcome != REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "task_id": self.task_id,
            "root_attempt_id": self.root_attempt_id,
            "origin_attempt_id": self.origin_attempt_id,
            "origin_session_id": self.origin_session_id,
            "gate_kind": self.gate_kind,
            "status": self.status,
            "request_payload_mode": self.request_payload_mode,
            "request_payload": self.request_payload,
            "request_digest": self.request_digest,
            "response_schema": dict(self.response_schema),
            "expires_at": self.expires_at,
            "expiry_policy": self.expiry_policy,
            "decision_policy_id": self.decision_policy_id,
            "decision_policy_version": self.decision_policy_version,
            "decision_policy_digest": self.decision_policy_digest,
            "allowed_outcomes": list(self.allowed_outcomes),
            "allowed_routes_by_outcome": {key: list(value) for key, value in sorted(self.allowed_routes_by_outcome.items())},
            "gate_revision": self.gate_revision,
            "continuation_revision": self.continuation_revision,
            "continuation_state": self.continuation_state,
            "continuation_route": self.continuation_route,
            "decision_id": self.decision_id,
            "decision_outcome": self.decision_outcome,
            "decision_payload_mode": self.decision_payload_mode,
            "decision_payload": self.decision_payload,
            "decision_digest": self.decision_digest,
            "decision_provenance": dict(self.decision_provenance) if self.decision_provenance else None,
            "continuation_reference": dict(self.continuation_reference) if self.continuation_reference else None,
            "created_seq": self.created_seq,
            "created_at": self.created_at,
            "created_by": dict(self.created_by or {}),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanGateRecord":
        required = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != required:
            raise R26Error("R2_6_SCHEMA_INVALID", "Human Gate state contains unknown or missing fields")
        return cls(
            gate_id=_text(value["gate_id"], "gate_id"), mission_id=_text(value["mission_id"], "mission_id"),
            plan_id=_text(value["plan_id"], "plan_id"), plan_revision_id=_text(value["plan_revision_id"], "plan_revision_id"),
            task_id=_text(value["task_id"], "task_id"), root_attempt_id=_text(value["root_attempt_id"], "root_attempt_id"),
            origin_attempt_id=_text(value["origin_attempt_id"], "origin_attempt_id"), origin_session_id=_text(value["origin_session_id"], "origin_session_id"),
            gate_kind=_text(value["gate_kind"], "gate_kind"), status=_text(value["status"], "status"),
            request_payload_mode=_text(value["request_payload_mode"], "request_payload_mode"), request_payload=value["request_payload"],
            request_digest=_digest(value["request_digest"], "request_digest"), response_schema=_mapping(value["response_schema"], "response_schema"),
            expires_at=_timestamp(value["expires_at"], "expires_at"), expiry_policy=_text(value["expiry_policy"], "expiry_policy"),
            decision_policy_id=_text(value["decision_policy_id"], "decision_policy_id"), decision_policy_version=_positive(value["decision_policy_version"], "decision_policy_version"),
            decision_policy_digest=_digest(value["decision_policy_digest"], "decision_policy_digest"),
            allowed_outcomes=tuple(_text(item, "allowed_outcomes") for item in value["allowed_outcomes"]),
            allowed_routes_by_outcome={key: tuple(item) for key, item in value["allowed_routes_by_outcome"].items()},
            gate_revision=_positive(value["gate_revision"], "gate_revision"), continuation_revision=_non_negative(value["continuation_revision"], "continuation_revision"),
            continuation_state=_text(value["continuation_state"], "continuation_state"), continuation_route=_optional_text(value["continuation_route"], "continuation_route"),
            decision_id=_optional_text(value["decision_id"], "decision_id"), decision_outcome=_optional_text(value["decision_outcome"], "decision_outcome"),
            decision_payload_mode=_optional_text(value["decision_payload_mode"], "decision_payload_mode"), decision_payload=value["decision_payload"],
            decision_digest=_digest(value["decision_digest"], "decision_digest") if value["decision_digest"] else None,
            decision_provenance=value["decision_provenance"], continuation_reference=value["continuation_reference"],
            created_seq=_non_negative(value["created_seq"], "created_seq"), created_at=_text(value["created_at"], "created_at"),
            created_by=_mapping(value["created_by"], "created_by"),
        )


@dataclass(frozen=True)
class HumanGateState:
    mission_id: str
    gates: tuple[HumanGateRecord, ...] = ()

    def gate(self, gate_id: str) -> HumanGateRecord | None:
        return next((item for item in self.gates if item.gate_id == gate_id), None)

    def for_binding(self, mission_id: str, task_id: str, root_attempt_id: str) -> tuple[HumanGateRecord, ...]:
        binding = (mission_id, task_id, root_attempt_id)
        return tuple(item for item in self.gates if item.binding == binding and item.is_blocking)

    def current_cycle(self, mission_id: str, task_id: str, root_attempt_id: str) -> HumanGateRecord | None:
        candidates = self.for_binding(mission_id, task_id, root_attempt_id)
        if len(candidates) > 1:
            raise R26Error("R2_6_ACTIVE_GATE_CONFLICT", "multiple blocking Human Gates exist for one execution lineage")
        return candidates[0] if candidates else None

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "gates": {item.gate_id: item.to_dict() for item in sorted(self.gates, key=lambda item: item.gate_id)}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanGateState":
        if set(value) != {"mission_id", "gates"} or not isinstance(value["gates"], Mapping):
            raise R26Error("R2_6_SCHEMA_INVALID", "Human Gate extension state is invalid")
        return cls(_text(value["mission_id"], "mission_id"), tuple(HumanGateRecord.from_dict(item) for item in value["gates"].values()))


def replace_gate(state: HumanGateState, record: HumanGateRecord) -> HumanGateState:
    return replace(state, gates=tuple(record if item.gate_id == record.gate_id else item for item in state.gates))
