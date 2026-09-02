from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


CONTRACT_VERSION = "R2.1_RUNTIME_FACTS_CAPABILITY_RESOLUTION_V1"
SNAPSHOT_KIND = "R2_1_RUNTIME_FACTS_RESOLUTION"

SCOPE_PROJECT = "PROJECT"
SCOPE_ENVIRONMENT = "ENVIRONMENT"
SCOPE_REPOSITORY = "REPOSITORY"
SCOPE_TYPES = {SCOPE_PROJECT, SCOPE_ENVIRONMENT, SCOPE_REPOSITORY}


class ScopeType:
    PROJECT = SCOPE_PROJECT
    ENVIRONMENT = SCOPE_ENVIRONMENT
    REPOSITORY = SCOPE_REPOSITORY

RESOLUTION_RESOLVED = "RESOLVED"
RESOLUTION_UNAVAILABLE = "UNAVAILABLE"
RESOLUTION_BLOCKED = "BLOCKED"
RESOLUTION_INVALID = "INVALID"
RESOLUTION_STATUSES = {
    RESOLUTION_RESOLVED,
    RESOLUTION_UNAVAILABLE,
    RESOLUTION_BLOCKED,
    RESOLUTION_INVALID,
}


class ResolutionStatus:
    RESOLVED = RESOLUTION_RESOLVED
    UNAVAILABLE = RESOLUTION_UNAVAILABLE
    BLOCKED = RESOLUTION_BLOCKED
    INVALID = RESOLUTION_INVALID

FACT_KNOWN = "KNOWN"
FACT_UNKNOWN = "UNKNOWN"
FACT_STALE = "STALE"
FACT_CONFLICT = "CONFLICT"
FACT_NOT_CONFIGURED = "NOT_CONFIGURED"
FACT_DENIED = "DENIED"
FACT_ERROR = "ERROR"
FACT_STATUSES = {
    FACT_KNOWN,
    FACT_UNKNOWN,
    FACT_STALE,
    FACT_CONFLICT,
    FACT_NOT_CONFIGURED,
    FACT_DENIED,
    FACT_ERROR,
}


class FactStatus:
    KNOWN = FACT_KNOWN
    UNKNOWN = FACT_UNKNOWN
    STALE = FACT_STALE
    CONFLICT = FACT_CONFLICT
    NOT_CONFIGURED = FACT_NOT_CONFIGURED
    DENIED = FACT_DENIED
    ERROR = FACT_ERROR

CAPABILITY_AVAILABLE = "AVAILABLE"
CAPABILITY_UNAVAILABLE = "UNAVAILABLE"
CAPABILITY_BLOCKED = "BLOCKED"
CAPABILITY_INVALID = "INVALID"
CAPABILITY_STATUSES = {
    CAPABILITY_AVAILABLE,
    CAPABILITY_UNAVAILABLE,
    CAPABILITY_BLOCKED,
    CAPABILITY_INVALID,
}


class CapabilityStatus:
    AVAILABLE = CAPABILITY_AVAILABLE
    UNAVAILABLE = CAPABILITY_UNAVAILABLE
    BLOCKED = CAPABILITY_BLOCKED
    INVALID = CAPABILITY_INVALID

OPTIONAL_CONTEXT_REFS = (
    "mission_id",
    "plan_revision_id",
    "task_id",
    "runtime_session_id",
    "attempt_id",
    "context_cursor",
)
REFERENCE_PREFIXES = ("secret://", "env://", "profile://")
SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|authorization|cookie|secret|client[_-]?secret|access[_-]?key|private[_-]?key|otp|mfa)"
)
INLINE_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+\S+|basic\s+\S+|(?:password|passwd|pwd|token|secret|otp|mfa)\s*[:=]\s*\S+)"
)


class R2_1Error(RuntimeError):
    """A typed, fail-closed R2.1 contract error."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        detail = message or code
        super().__init__(detail if detail.startswith(code) else f"{code}: {detail}")


class IdempotencyConflict(R2_1Error):
    def __init__(self, resolution_id: str):
        super().__init__("IDEMPOTENCY_CONFLICT", f"resolution_id already exists with a different request digest: {resolution_id}")


def is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REFERENCE_PREFIXES)


def validate_secret_boundary(value: Any, key: str = "") -> None:
    """Reject raw secret material before it can enter a digest or snapshot."""
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            child_name = str(child_key)
            if SENSITIVE_KEY_RE.search(child_name):
                if child_value is not None and not is_reference(child_value):
                    raise R2_1Error("SECRET_VALUE_NOT_ALLOWED", f"raw secret value is not allowed for {child_name}")
            validate_secret_boundary(child_value, child_name)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            validate_secret_boundary(child, key)
        return
    if isinstance(value, str) and not is_reference(value) and INLINE_SECRET_RE.search(value):
        raise R2_1Error("SECRET_VALUE_NOT_ALLOWED", "raw secret material is not allowed")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass(frozen=True)
class ResolutionRequest:
    resolution_id: str
    scope: dict[str, Any]
    context_refs: dict[str, Any]
    facts: tuple[dict[str, Any], ...]
    capabilities: tuple[dict[str, Any], ...]
    source_precedence: Any
    declared_inputs: dict[str, Any]
    request_digest: str | None = None
    valid_until: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "ResolutionRequest") -> "ResolutionRequest":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise R2_1Error("INVALID_REQUEST", "resolution request must be a mapping")

        raw = dict(value)
        declared = raw.get("declared_inputs")
        declared_inputs = dict(declared) if isinstance(declared, Mapping) else {}

        raw_scope = raw.get("scope")
        scope = dict(raw_scope) if isinstance(raw_scope, Mapping) else {}
        if not scope and isinstance(raw.get("scope_type"), str):
            scope["type"] = raw["scope_type"]
        for field in ("type", "scope_type", "project_id", "environment_id", "repository_id"):
            if field not in scope and field in raw:
                scope[field] = raw[field]
        if "scope_type" in scope and "type" not in scope:
            scope["type"] = scope["scope_type"]

        raw_context = raw.get("context_refs")
        context_refs = dict(raw_context) if isinstance(raw_context, Mapping) else {}
        for field in OPTIONAL_CONTEXT_REFS:
            if field in raw and field not in context_refs and raw[field] is not None:
                context_refs[field] = raw[field]
        context_refs = {key: context_refs[key] for key in OPTIONAL_CONTEXT_REFS if key in context_refs and context_refs[key] is not None}

        facts = raw.get("facts", raw.get("runtime_facts", declared_inputs.get("facts", [])))
        capabilities = raw.get("capabilities", raw.get("capability_declarations", declared_inputs.get("capabilities", [])))
        precedence = raw.get("source_precedence", declared_inputs.get("source_precedence"))
        resolution_id = str(raw.get("resolution_id") or "").strip()
        request_digest = raw.get("request_digest")
        if request_digest is not None:
            request_digest = str(request_digest)

        return cls(
            resolution_id=resolution_id,
            scope=scope,
            context_refs=context_refs,
            facts=tuple(dict(item) for item in _as_list(facts) if isinstance(item, Mapping)),
            capabilities=tuple(dict(item) for item in _as_list(capabilities) if isinstance(item, Mapping)),
            source_precedence=precedence,
            declared_inputs=declared_inputs,
            request_digest=request_digest,
            valid_until=str(raw["valid_until"]) if raw.get("valid_until") is not None else None,
        )

    def declared_mapping(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "context_refs": self.context_refs,
            "facts": list(self.facts),
            "capabilities": list(self.capabilities),
            "source_precedence": self.source_precedence,
            "declared_inputs": self.declared_inputs,
            "valid_until": self.valid_until,
        }


def normalize_status(value: Any, allowed: set[str], default: str) -> str:
    status = str(value or default).upper()
    if status not in allowed:
        raise R2_1Error("INVALID_STATUS", f"unsupported status: {status}")
    return status
