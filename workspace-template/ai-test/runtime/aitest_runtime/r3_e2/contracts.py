from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256


EXTENSION_ID = "r3_e2_sut_auth_context"
EXTENSION_VERSION = "1"
ARCHITECTURE_BASELINE_REF = "v5"

REQUEST_AUTH_CONTEXT = "R3E2_REQUEST_AUTH_CONTEXT"
LINK_HUMAN_GATE = "R3E2_LINK_HUMAN_GATE"
ARM_RUNTIME_VERIFICATION = "R3E2_ARM_RUNTIME_VERIFICATION"
VERIFY_RUNTIME_AUTH = "R3E2_VERIFY_RUNTIME_AUTH"
AUTHORIZE_RESUME = "R3E2_AUTHORIZE_RESUME"
EXPIRE_AUTH_CONTEXT = "R3E2_EXPIRE_AUTH_CONTEXT"
REVOKE_AUTH_CONTEXT = "R3E2_REVOKE_AUTH_CONTEXT"
CLOSE_AUTH_CONTEXT = "R3E2_CLOSE_AUTH_CONTEXT"

AUTH_REQUIRED = "r3.e2.sut_auth_context.auth_required.v1"
HUMAN_GATE_LINKED = "r3.e2.sut_auth_context.human_gate_linked.v1"
VERIFICATION_PENDING = "r3.e2.sut_auth_context.verification_pending.v1"
RUNTIME_VERIFIED = "r3.e2.sut_auth_context.runtime_verified.v1"
RESUME_AUTHORIZED = "r3.e2.sut_auth_context.resume_authorized.v1"
CONTEXT_EXPIRED = "r3.e2.sut_auth_context.expired.v1"
CONTEXT_REVOKED = "r3.e2.sut_auth_context.revoked.v1"
CONTEXT_CLOSED = "r3.e2.sut_auth_context.closed.v1"

COMMAND_TYPES = frozenset({
    REQUEST_AUTH_CONTEXT,
    LINK_HUMAN_GATE,
    ARM_RUNTIME_VERIFICATION,
    VERIFY_RUNTIME_AUTH,
    AUTHORIZE_RESUME,
    EXPIRE_AUTH_CONTEXT,
    REVOKE_AUTH_CONTEXT,
    CLOSE_AUTH_CONTEXT,
})
EVENT_TYPES = frozenset({
    AUTH_REQUIRED,
    HUMAN_GATE_LINKED,
    VERIFICATION_PENDING,
    RUNTIME_VERIFIED,
    RESUME_AUTHORIZED,
    CONTEXT_EXPIRED,
    CONTEXT_REVOKED,
    CONTEXT_CLOSED,
})

CONTEXT_STATUSES = frozenset({
    "AUTH_REQUIRED",
    "HUMAN_GATE_PENDING",
    "VERIFICATION_PENDING",
    "AUTHENTICATED",
    "EXPIRED",
    "INVALID",
    "REVOKED",
    "CLOSED",
})
VALIDATION_STATUSES = frozenset({"UNKNOWN", "VALID", "INVALID"})
GATE_KINDS = frozenset({"EXTERNAL_ACTION"})
GATE_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED", "CANCELLED", "EXPIRED"})
AUTH_METHODS = frozenset({"HUMAN_4A"})
SOURCE_KINDS = frozenset({
    "AUTH_PROFILE_CONFIG",
    "HUMAN_GATE",
    "BROWSER_CONTEXT",
    "RUNTIME_VERIFICATION",
    "R1_EVIDENCE",
    "CONTINUATION_ANCHOR",
})
RESUME_ROUTES = frozenset({"RESUME_EXECUTION"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "AUTH_REQUIRED": frozenset({"HUMAN_GATE_PENDING"}),
    "HUMAN_GATE_PENDING": frozenset({"VERIFICATION_PENDING", "EXPIRED", "INVALID", "CLOSED"}),
    "VERIFICATION_PENDING": frozenset({"AUTHENTICATED", "INVALID", "EXPIRED", "CLOSED"}),
    "AUTHENTICATED": frozenset({"EXPIRED", "INVALID", "REVOKED", "CLOSED"}),
    "EXPIRED": frozenset(),
    "INVALID": frozenset(),
    "REVOKED": frozenset(),
    "CLOSED": frozenset(),
}


class R3E2Error(RuntimeError):
    """R3.E2 schema, lifecycle, provenance, and runtime-boundary error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _tuple_mapping(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[{index}]") for index, item in enumerate(value))


def _tuple_text(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must contain unique values")
    return result


def _status(value: Any) -> str:
    value = _text(value, "status")
    if value not in CONTEXT_STATUSES:
        raise R3E2Error("R3_E2_STATUS_INVALID", f"unsupported SUT auth context status: {value}")
    return value


def _validation_status(value: Any) -> str:
    value = _text(value, "validation_status")
    if value not in VALIDATION_STATUSES:
        raise R3E2Error("R3_E2_STATUS_INVALID", f"unsupported validation status: {value}")
    return value


def _require_future(expires_at: str, observed_at: str) -> None:
    if expires_at <= observed_at:
        raise R3E2Error("R3_E2_EXPIRY_INVALID", "expires_at must be after the observed verification time")


def validate_transition(from_status: str, to_status: str) -> None:
    from_status = _status(from_status)
    to_status = _status(to_status)
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise R3E2Error(
            "R3_E2_STATUS_TRANSITION_INVALID",
            f"{from_status} cannot transition to {to_status}",
            {"from_status": from_status, "to_status": to_status},
        )


@dataclass(frozen=True)
class SUTAuthContextIdentity:
    sut_auth_context_id: str
    context_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "sut_auth_context_id", _text(self.sut_auth_context_id, "sut_auth_context_id"))
        if not isinstance(self.context_epoch, int) or isinstance(self.context_epoch, bool) or self.context_epoch < 1:
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "context_epoch must be a positive integer")

    @property
    def key(self) -> str:
        return f"{self.sut_auth_context_id}:{self.context_epoch}"

    def to_dict(self) -> dict[str, Any]:
        return {"sut_auth_context_id": self.sut_auth_context_id, "context_epoch": self.context_epoch}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SUTAuthContextIdentity":
        raw = _mapping(value, "identity")
        if set(raw) != {"sut_auth_context_id", "context_epoch"}:
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "identity has unknown or missing fields")
        return cls(raw["sut_auth_context_id"], raw["context_epoch"])


@dataclass(frozen=True)
class SUTAuthContextScope:
    project_id: str
    environment_id: str
    system_id: str
    version_scope: str
    tenant_scope_ref: str
    permission_scope_digest: str

    def __post_init__(self) -> None:
        for name in ("project_id", "environment_id", "system_id", "version_scope", "tenant_scope_ref", "permission_scope_digest"):
            value = _text(getattr(self, name), name)
            if value == "*":
                raise R3E2Error("R3_E2_SCOPE_MISMATCH", f"{name} cannot be a wildcard")
            object.__setattr__(self, name, value)

    @property
    def key(self) -> str:
        return "|".join((self.project_id, self.environment_id, self.system_id, self.version_scope, self.tenant_scope_ref, self.permission_scope_digest))

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "environment_id": self.environment_id,
            "system_id": self.system_id,
            "version_scope": self.version_scope,
            "tenant_scope_ref": self.tenant_scope_ref,
            "permission_scope_digest": self.permission_scope_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SUTAuthContextScope":
        raw = _mapping(value, "scope")
        required = {"project_id", "environment_id", "system_id", "version_scope", "tenant_scope_ref", "permission_scope_digest"}
        if set(raw) != required:
            raise R3E2Error("R3_E2_SCOPE_MISMATCH", "scope has unknown or missing fields")
        return cls(*(raw[name] for name in ("project_id", "environment_id", "system_id", "version_scope", "tenant_scope_ref", "permission_scope_digest")))


@dataclass(frozen=True)
class BrowserContextRef:
    browser_session_id: str
    browser_context_id_or_epoch: str
    context_binding_digest: str
    observed_lease_owner: str
    observed_at: str

    def __post_init__(self) -> None:
        for name in ("browser_session_id", "browser_context_id_or_epoch", "context_binding_digest", "observed_lease_owner", "observed_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "browser_session_id": self.browser_session_id,
            "browser_context_id_or_epoch": self.browser_context_id_or_epoch,
            "context_binding_digest": self.context_binding_digest,
            "observed_lease_owner": self.observed_lease_owner,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BrowserContextRef":
        raw = _mapping(value, "browser_context_ref")
        return cls(*(raw[name] for name in ("browser_session_id", "browser_context_id_or_epoch", "context_binding_digest", "observed_lease_owner", "observed_at")))


@dataclass(frozen=True)
class AuthSourceRef:
    source_ref_id: str
    source_kind: str
    locator: str
    source_revision: str
    source_digest: str
    scope: SUTAuthContextScope
    observed_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_ref_id", "source_kind", "locator", "source_revision", "source_digest", "observed_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_kind not in SOURCE_KINDS:
            raise R3E2Error("R3_E2_SOURCE_INVALID", f"unsupported source kind: {self.source_kind}")
        if not isinstance(self.scope, SUTAuthContextScope):
            raise R3E2Error("R3_E2_SCOPE_MISMATCH", "source ref requires SUTAuthContextScope")
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref_id": self.source_ref_id,
            "source_kind": self.source_kind,
            "locator": self.locator,
            "source_revision": self.source_revision,
            "source_digest": self.source_digest,
            "scope": self.scope.to_dict(),
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthSourceRef":
        raw = _mapping(value, "source_ref")
        return cls(raw["source_ref_id"], raw["source_kind"], raw["locator"], raw["source_revision"], raw["source_digest"], SUTAuthContextScope.from_dict(raw["scope"]), raw["observed_at"], raw.get("metadata") or {})


@dataclass(frozen=True)
class HumanGateReference:
    gate_id: str
    gate_kind: str
    action_kind: str
    status: str
    decision_ref: str | None = None
    decision_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("gate_id", "gate_kind", "action_kind", "status"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.gate_kind not in GATE_KINDS:
            raise R3E2Error("R3_E2_GATE_INVALID", "R3.E2 requires the existing EXTERNAL_ACTION gate kind")
        if self.action_kind != "SUT_AUTHENTICATION_4A":
            raise R3E2Error("R3_E2_GATE_INVALID", "HumanGate action must be SUT_AUTHENTICATION_4A")
        if self.status not in GATE_STATUSES:
            raise R3E2Error("R3_E2_GATE_INVALID", f"unsupported HumanGate status: {self.status}")
        object.__setattr__(self, "decision_ref", _optional_text(self.decision_ref, "decision_ref"))
        object.__setattr__(self, "decision_digest", _optional_text(self.decision_digest, "decision_digest"))
        if self.status == "APPROVED" and (self.decision_ref is None or self.decision_digest is None):
            raise R3E2Error("R3_E2_GATE_INVALID", "approved HumanGate requires decision provenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_kind": self.gate_kind,
            "action_kind": self.action_kind,
            "status": self.status,
            "decision_ref": self.decision_ref,
            "decision_digest": self.decision_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanGateReference":
        raw = _mapping(value, "human_gate_ref")
        return cls(raw["gate_id"], raw["gate_kind"], raw["action_kind"], raw["status"], raw.get("decision_ref"), raw.get("decision_digest"))


@dataclass(frozen=True)
class RuntimeVerificationReceipt:
    verification_id: str
    real_runtime: bool
    verifier_kind: str
    authenticated_principal_ref: str
    scope_digest: str
    browser_context_ref: BrowserContextRef
    verified_at: str
    expires_at: str
    source_ref: AuthSourceRef
    observed_lease_owner: str
    evidence_digest: str
    checks: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("verification_id", "verifier_kind", "authenticated_principal_ref", "scope_digest", "verified_at", "expires_at", "observed_lease_owner", "evidence_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.real_runtime, bool):
            raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "real_runtime must be boolean")
        if not isinstance(self.browser_context_ref, BrowserContextRef) or not isinstance(self.source_ref, AuthSourceRef):
            raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "runtime verification requires typed Browser/source refs")
        _require_future(self.expires_at, self.verified_at)
        object.__setattr__(self, "checks", _mapping(self.checks, "checks"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "real_runtime": self.real_runtime,
            "verifier_kind": self.verifier_kind,
            "authenticated_principal_ref": self.authenticated_principal_ref,
            "scope_digest": self.scope_digest,
            "browser_context_ref": self.browser_context_ref.to_dict(),
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "source_ref": self.source_ref.to_dict(),
            "observed_lease_owner": self.observed_lease_owner,
            "evidence_digest": self.evidence_digest,
            "checks": dict(self.checks),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeVerificationReceipt":
        raw = _mapping(value, "runtime_verification")
        return cls(raw["verification_id"], raw["real_runtime"], raw["verifier_kind"], raw["authenticated_principal_ref"], raw["scope_digest"], BrowserContextRef.from_dict(raw["browser_context_ref"]), raw["verified_at"], raw["expires_at"], AuthSourceRef.from_dict(raw["source_ref"]), raw["observed_lease_owner"], raw["evidence_digest"], raw.get("checks") or {})


@dataclass(frozen=True)
class ContinuationProof:
    gate_id: str
    route: str
    canonical_reference: Mapping[str, Any]
    source_seq: int
    source_digest: str
    continuation_operation_id: str
    continuation_provenance: Mapping[str, Any]
    applied: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _text(self.gate_id, "gate_id"))
        object.__setattr__(self, "route", _text(self.route, "route"))
        if self.route not in RESUME_ROUTES:
            raise R3E2Error("R3_E2_CONTINUATION_INVALID", "R3.E2 only authorizes RESUME_EXECUTION")
        if not isinstance(self.source_seq, int) or isinstance(self.source_seq, bool) or self.source_seq < 0:
            raise R3E2Error("R3_E2_CONTINUATION_INVALID", "source_seq must be non-negative")
        for name in ("source_digest", "continuation_operation_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "canonical_reference", _mapping(self.canonical_reference, "canonical_reference"))
        object.__setattr__(self, "continuation_provenance", _mapping(self.continuation_provenance, "continuation_provenance"))
        if not isinstance(self.applied, bool) or not self.applied:
            raise R3E2Error("R3_E2_CONTINUATION_INVALID", "resume continuation must be applied by the existing R2.6 mechanism")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "route": self.route,
            "canonical_reference": dict(self.canonical_reference),
            "source_seq": self.source_seq,
            "source_digest": self.source_digest,
            "continuation_operation_id": self.continuation_operation_id,
            "continuation_provenance": dict(self.continuation_provenance),
            "applied": self.applied,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContinuationProof":
        raw = _mapping(value, "continuation_proof")
        return cls(raw["gate_id"], raw["route"], raw["canonical_reference"], raw["source_seq"], raw["source_digest"], raw["continuation_operation_id"], raw["continuation_provenance"], raw["applied"])


@dataclass(frozen=True)
class SUTAuthContext:
    identity: SUTAuthContextIdentity
    scope: SUTAuthContextScope
    auth_profile_ref: str | None
    authenticated_principal_ref: str | None
    auth_method: str
    status: str
    validation_status: str
    browser_context_ref: BrowserContextRef | None
    human_gate_ref: HumanGateReference | None
    verification_receipt: RuntimeVerificationReceipt | None
    lineage_refs: Mapping[str, Any]
    source_refs: tuple[AuthSourceRef, ...] = ()
    verified_at: str | None = None
    expires_at: str | None = None
    continuation_proof: ContinuationProof | None = None
    last_observed_at: str | None = None
    record_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SUTAuthContextIdentity) or not isinstance(self.scope, SUTAuthContextScope):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "SUTAuthContext requires typed identity and scope")
        object.__setattr__(self, "auth_profile_ref", _optional_text(self.auth_profile_ref, "auth_profile_ref"))
        object.__setattr__(self, "authenticated_principal_ref", _optional_text(self.authenticated_principal_ref, "authenticated_principal_ref"))
        object.__setattr__(self, "auth_method", _text(self.auth_method, "auth_method"))
        if self.auth_method not in AUTH_METHODS:
            raise R3E2Error("R3_E2_SCHEMA_INVALID", f"unsupported auth_method: {self.auth_method}")
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "validation_status", _validation_status(self.validation_status))
        if self.status == "AUTHENTICATED" and self.validation_status != "VALID":
            raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "AUTHENTICATED requires VALID")
        if self.validation_status == "VALID" and self.status != "AUTHENTICATED":
            raise R3E2Error("R3_E2_STATUS_INVALID", "VALID is only legal for AUTHENTICATED")
        if self.status == "AUTHENTICATED" and (self.verification_receipt is None or self.browser_context_ref is None or self.verified_at is None or self.expires_at is None):
            raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "AUTHENTICATED requires runtime receipt, Browser ref, verified_at, and expires_at")
        for name in ("verified_at", "expires_at", "last_observed_at"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.verification_receipt is not None and not isinstance(self.verification_receipt, RuntimeVerificationReceipt):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "verification_receipt must be typed")
        if self.browser_context_ref is not None and not isinstance(self.browser_context_ref, BrowserContextRef):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "browser_context_ref must be typed")
        if self.human_gate_ref is not None and not isinstance(self.human_gate_ref, HumanGateReference):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "human_gate_ref must be typed")
        if self.continuation_proof is not None and not isinstance(self.continuation_proof, ContinuationProof):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "continuation_proof must be typed")
        object.__setattr__(self, "lineage_refs", _mapping(self.lineage_refs, "lineage_refs"))
        if not isinstance(self.source_refs, tuple) or any(not isinstance(item, AuthSourceRef) for item in self.source_refs):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "source_refs must contain typed AuthSourceRef values")
        if any(item.scope != self.scope for item in self.source_refs):
            raise R3E2Error("R3_E2_SCOPE_MISMATCH", "source ref scope does not match SUTAuthContext scope")
        digest = canonical_sha256(self._digest_input())
        if self.record_digest is not None and self.record_digest != digest:
            raise R3E2Error("R3_E2_PROVENANCE_INVALID", "record_digest does not match immutable context record")
        object.__setattr__(self, "record_digest", digest)

    def _digest_input(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "scope": self.scope.to_dict(),
            "auth_profile_ref": self.auth_profile_ref,
            "authenticated_principal_ref": self.authenticated_principal_ref,
            "auth_method": self.auth_method,
            "status": self.status,
            "validation_status": self.validation_status,
            "browser_context_ref": self.browser_context_ref.to_dict() if self.browser_context_ref else None,
            "human_gate_ref": self.human_gate_ref.to_dict() if self.human_gate_ref else None,
            "verification_receipt": self.verification_receipt.to_dict() if self.verification_receipt else None,
            "lineage_refs": dict(self.lineage_refs),
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "continuation_proof": self.continuation_proof.to_dict() if self.continuation_proof else None,
            "last_observed_at": self.last_observed_at,
            "source_refs": [item.to_dict() for item in self.source_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        result = self._digest_input()
        result["record_digest"] = self.record_digest
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SUTAuthContext":
        raw = _mapping(value, "context")
        return cls(
            identity=SUTAuthContextIdentity.from_dict(raw["identity"]),
            scope=SUTAuthContextScope.from_dict(raw["scope"]),
            auth_profile_ref=raw.get("auth_profile_ref"),
            authenticated_principal_ref=raw.get("authenticated_principal_ref"),
            auth_method=raw["auth_method"],
            status=raw["status"],
            validation_status=raw["validation_status"],
            browser_context_ref=BrowserContextRef.from_dict(raw["browser_context_ref"]) if raw.get("browser_context_ref") else None,
            human_gate_ref=HumanGateReference.from_dict(raw["human_gate_ref"]) if raw.get("human_gate_ref") else None,
            verification_receipt=RuntimeVerificationReceipt.from_dict(raw["verification_receipt"]) if raw.get("verification_receipt") else None,
            lineage_refs=raw.get("lineage_refs") or {},
            source_refs=tuple(AuthSourceRef.from_dict(item) for item in raw.get("source_refs") or ()),
            verified_at=raw.get("verified_at"),
            expires_at=raw.get("expires_at"),
            continuation_proof=ContinuationProof.from_dict(raw["continuation_proof"]) if raw.get("continuation_proof") else None,
            last_observed_at=raw.get("last_observed_at"),
            record_digest=raw.get("record_digest"),
        )


@dataclass(frozen=True)
class R3E2State:
    mission_id: str
    contexts: tuple[SUTAuthContext, ...] = ()
    transition_history: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _text(self.mission_id, "mission_id"))
        if not isinstance(self.contexts, tuple) or any(not isinstance(item, SUTAuthContext) for item in self.contexts):
            raise R3E2Error("R3_E2_SCHEMA_INVALID", "contexts must contain typed SUTAuthContext values")
        object.__setattr__(self, "transition_history", _tuple_mapping(self.transition_history, "transition_history"))

    def context(self, context_id: str, epoch: int | None = None) -> SUTAuthContext | None:
        return next((item for item in self.contexts if item.identity.sut_auth_context_id == context_id and (epoch is None or item.identity.context_epoch == epoch)), None)

    def context_key(self, key: str) -> SUTAuthContext | None:
        return next((item for item in self.contexts if item.identity.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "contexts": [item.to_dict() for item in sorted(self.contexts, key=lambda value: value.identity.key)],
            "transition_history": [dict(item) for item in self.transition_history],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R3E2State":
        return cls(
            mission_id=value["mission_id"],
            contexts=tuple(SUTAuthContext.from_dict(item) for item in value.get("contexts") or ()),
            transition_history=tuple(value.get("transition_history") or ()),
        )
