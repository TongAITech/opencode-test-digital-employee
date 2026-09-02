from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlparse

from aitest_runtime.common import new_id, now_iso, redact
from aitest_runtime.durable_core import canonical_sha256


READY = "READY"
UNKNOWN = "UNKNOWN"
NOT_CONFIGURED = "NOT_CONFIGURED"
UNAVAILABLE = "UNAVAILABLE"
BLOCKED = "BLOCKED"
CAPABILITY_STATUSES = frozenset({READY, UNKNOWN, NOT_CONFIGURED, UNAVAILABLE, BLOCKED})


class R3E3Error(RuntimeError):
    """Typed fail-closed error for the controlled Browser runtime seam."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(f"{self.code}: {message}")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E3Error("R3_E3_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E3Error("R3_E3_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _status(value: Any, name: str) -> str:
    status = _text(value, name).upper()
    if status not in CAPABILITY_STATUSES:
        raise R3E3Error("R3_E3_SCHEMA_INVALID", f"{name} has unsupported status: {status}")
    return status


def _allowed_hosts(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set)):
        raise R3E3Error("R3_E3_SUT_ENDPOINT_NOT_CONFIGURED", "allowed_hosts must be a list")
    hosts = []
    for item in value:
        host = _text(item, "allowed_hosts").lower()
        if "://" in host:
            host = urlparse(host).hostname or ""
        host = host.rstrip(".")
        if host:
            hosts.append(host)
    return tuple(dict.fromkeys(hosts))


@dataclass(frozen=True)
class EnvironmentBinding:
    environment_id: str
    allowed_hosts: tuple[str, ...] = ()
    sut_base_url: str | None = None
    protected_probe_url: str | None = None
    verifier_policy: Mapping[str, Any] = field(default_factory=dict)
    service_endpoints: Mapping[str, Any] = field(default_factory=dict)
    page_urls: Mapping[str, Any] = field(default_factory=dict)
    configuration_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment_id", _text(self.environment_id, "environment_id"))
        object.__setattr__(self, "allowed_hosts", _allowed_hosts(self.allowed_hosts))
        object.__setattr__(self, "sut_base_url", _optional_text(self.sut_base_url, "sut_base_url"))
        object.__setattr__(self, "protected_probe_url", _optional_text(self.protected_probe_url, "protected_probe_url"))
        object.__setattr__(self, "verifier_policy", _mapping(self.verifier_policy, "verifier_policy"))
        object.__setattr__(self, "service_endpoints", _mapping(self.service_endpoints, "service_endpoints"))
        object.__setattr__(self, "page_urls", _mapping(self.page_urls, "page_urls"))
        digest = self.configuration_digest or canonical_sha256(self.to_dict(include_digest=False))
        object.__setattr__(self, "configuration_digest", digest)

    @classmethod
    def from_mapping(cls, environment_id: str, config: Mapping[str, Any] | None = None) -> "EnvironmentBinding":
        raw = dict(config or {})
        nested = raw.get("config") if isinstance(raw.get("config"), Mapping) else raw
        nested = dict(nested)
        service_endpoints = dict(nested.get("service_endpoints") or {})
        page_urls = dict(nested.get("page_urls") or {})
        base = nested.get("sut_base_url") or page_urls.get("sut") or page_urls.get("sut_base") or service_endpoints.get("sut")
        probe = (
            nested.get("protected_probe_url")
            or service_endpoints.get("auth_probe")
            or service_endpoints.get("protected_probe")
            or service_endpoints.get("sut_auth_probe")
            or service_endpoints.get("verifier")
        )
        verifier_policy = nested.get("verifier_policy") or nested.get("sut_verifier") or {}
        return cls(
            environment_id=environment_id,
            allowed_hosts=nested.get("allowed_hosts") or nested.get("allowed_domains") or (),
            sut_base_url=base,
            protected_probe_url=probe,
            verifier_policy=verifier_policy,
            service_endpoints=service_endpoints,
            page_urls=page_urls,
            configuration_digest=str(nested.get("configuration_digest") or ""),
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "environment_id": self.environment_id,
            "allowed_hosts": list(self.allowed_hosts),
            "sut_base_url": self.sut_base_url,
            "protected_probe_url": self.protected_probe_url,
            "verifier_policy": redact(dict(self.verifier_policy)),
            "service_endpoints": redact(dict(self.service_endpoints)),
            "page_urls": redact(dict(self.page_urls)),
        }
        if include_digest:
            result["configuration_digest"] = self.configuration_digest
        return result

    def require_endpoint(self, *, probe: bool = False) -> str:
        value = self.protected_probe_url if probe else self.sut_base_url
        if not value:
            raise R3E3Error(
                "R3_E3_SUT_ENDPOINT_NOT_CONFIGURED",
                "authoritative SUT endpoint/protected probe is not configured",
                details={"environment_id": self.environment_id, "configuration_digest": self.configuration_digest},
            )
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise R3E3Error("R3_E3_SUT_ENDPOINT_NOT_CONFIGURED", "SUT endpoint must be an absolute HTTP(S) URL")
        if self.allowed_hosts and parsed.hostname.lower() not in self.allowed_hosts and not any(
            item.startswith(".") and parsed.hostname.lower().endswith(item) for item in self.allowed_hosts
        ):
            raise R3E3Error("R3_E3_BROWSER_DOMAIN_NOT_ALLOWED", f"SUT endpoint host is outside allowed_hosts: {parsed.hostname}")
        return value


@dataclass(frozen=True)
class RuntimeBootstrapReceipt:
    client_bootstrap_status: str
    browser_selection_status: str
    backend_reachable: str
    setup_completed_before_selection: bool
    backend_kind: str
    source_ref: str
    observed_at: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_bootstrap_status": self.client_bootstrap_status,
            "browser_selection_status": self.browser_selection_status,
            "backend_reachable": self.backend_reachable,
            "setup_completed_before_selection": self.setup_completed_before_selection,
            "backend_kind": self.backend_kind,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class CapabilityReport:
    report_id: str
    observed_at: str
    backend_kind: str
    client_bootstrap_status: str
    browser_reachable: str
    session_create_lookup_status: str
    context_identity_status: str
    lease_handoff_status: str
    navigation_status: str
    action_status: str
    human_gate_bridge_status: str
    sut_endpoint_status: str
    non_mock_verifier_status: str
    reuse_status: str
    reason_codes: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    report_digest: str = ""

    def __post_init__(self) -> None:
        for name in (
            "client_bootstrap_status", "browser_reachable", "session_create_lookup_status",
            "context_identity_status", "lease_handoff_status", "navigation_status", "action_status",
            "human_gate_bridge_status", "sut_endpoint_status", "non_mock_verifier_status", "reuse_status",
        ):
            object.__setattr__(self, name, _status(getattr(self, name), name))
        digest = self.report_digest or canonical_sha256(self.to_dict(include_digest=False))
        object.__setattr__(self, "report_digest", digest)

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "report_id": self.report_id,
            "observed_at": self.observed_at,
            "backend_kind": self.backend_kind,
            "client_bootstrap_status": self.client_bootstrap_status,
            "browser_reachable": self.browser_reachable,
            "session_create_lookup_status": self.session_create_lookup_status,
            "context_identity_status": self.context_identity_status,
            "lease_handoff_status": self.lease_handoff_status,
            "navigation_status": self.navigation_status,
            "action_status": self.action_status,
            "human_gate_bridge_status": self.human_gate_bridge_status,
            "sut_endpoint_status": self.sut_endpoint_status,
            "non_mock_verifier_status": self.non_mock_verifier_status,
            "reuse_status": self.reuse_status,
            "reason_codes": list(self.reason_codes),
            "source_refs": list(self.source_refs),
        }
        if include_digest:
            result["report_digest"] = self.report_digest
        return result


@dataclass(frozen=True)
class BrowserContextObservation:
    browser_session_id: str
    context_id_or_epoch: str
    context_binding_digest: str
    lease_owner: str
    process_alive: bool
    context_alive: bool
    current_origin: str | None
    state_digest: str
    observed_at: str
    backend_kind: str
    source_ref: str

    @property
    def live(self) -> bool:
        return self.process_alive and self.context_alive

    def to_dict(self) -> dict[str, Any]:
        return redact({
            "browser_session_id": self.browser_session_id,
            "context_id_or_epoch": self.context_id_or_epoch,
            "context_binding_digest": self.context_binding_digest,
            "lease_owner": self.lease_owner,
            "process_alive": self.process_alive,
            "context_alive": self.context_alive,
            "current_origin": self.current_origin,
            "state_digest": self.state_digest,
            "observed_at": self.observed_at,
            "backend_kind": self.backend_kind,
            "source_ref": self.source_ref,
        })


@dataclass(frozen=True)
class RuntimeStateObservation:
    browser_session_id: str
    process_status: str
    context_status: str
    context_id_or_epoch: str | None
    lease_owner: str | None
    observed_at: str
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return redact(self.__dict__.copy())


@dataclass(frozen=True)
class BrowserActionRequest:
    request_id: str
    action_kind: str
    target: str
    input_digest: str | None
    expected_lease_owner: str
    idempotency_key: str
    expected_scope: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "action_kind", "target", "expected_lease_owner", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "action_kind", self.action_kind.upper())
        object.__setattr__(self, "expected_lease_owner", self.expected_lease_owner.upper())
        object.__setattr__(self, "input_digest", _optional_text(self.input_digest, "input_digest"))
        object.__setattr__(self, "expected_scope", _mapping(self.expected_scope, "expected_scope"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BrowserActionRequest":
        raw = dict(value)
        return cls(
            request_id=str(raw.get("request_id") or new_id("BA")),
            action_kind=raw.get("action_kind") or raw.get("kind") or "READ_STATE",
            target=raw.get("target") or raw.get("selector") or raw.get("url") or "about:blank",
            input_digest=raw.get("input_digest"),
            expected_lease_owner=raw.get("expected_lease_owner") or "AI",
            idempotency_key=str(raw.get("idempotency_key") or raw.get("request_id") or new_id("BA-IDEMP")),
            expected_scope=raw.get("expected_scope") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return redact({
            "request_id": self.request_id,
            "action_kind": self.action_kind,
            "target": self.target,
            "input_digest": self.input_digest,
            "expected_lease_owner": self.expected_lease_owner,
            "idempotency_key": self.idempotency_key,
            "expected_scope": dict(self.expected_scope),
        })


@dataclass(frozen=True)
class BrowserActionReceipt:
    request_id: str
    action_id: str
    real_runtime: bool
    adapter_kind: str
    browser_context_ref: Any
    observed_url_or_origin: str | None
    outcome: str
    state_digest: str
    source_ref: str
    observed_at: str
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        ref = self.browser_context_ref.to_dict() if hasattr(self.browser_context_ref, "to_dict") else self.browser_context_ref
        return redact({
            "request_id": self.request_id,
            "action_id": self.action_id,
            "real_runtime": self.real_runtime,
            "adapter_kind": self.adapter_kind,
            "browser_context_ref": ref,
            "observed_url_or_origin": self.observed_url_or_origin,
            "outcome": self.outcome,
            "state_digest": self.state_digest,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "reason_code": self.reason_code,
        })


@dataclass(frozen=True)
class LeaseHandoffReceipt:
    handoff_id: str
    browser_session_id: str
    from_owner: str
    to_owner: str
    before_context_id_or_epoch: str
    after_context_id_or_epoch: str
    before_binding_digest: str
    after_binding_digest: str
    observed_at: str
    same_context: bool
    source_ref: str

    def to_dict(self) -> dict[str, Any]:
        return redact(self.__dict__.copy())


@dataclass(frozen=True)
class RuntimeSession:
    browser_session: Mapping[str, Any]
    browser_context_ref: Any
    capability_report: CapabilityReport
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        ref = self.browser_context_ref.to_dict() if hasattr(self.browser_context_ref, "to_dict") else self.browser_context_ref
        return redact({
            "browser_session": dict(self.browser_session),
            "browser_context_ref": ref,
            "capability_report": self.capability_report.to_dict(),
            "observed_at": self.observed_at,
        })


def redacted_digest(value: Any) -> str:
    return canonical_sha256(redact(value))


def now_or(value: str | None) -> str:
    return value or now_iso()
