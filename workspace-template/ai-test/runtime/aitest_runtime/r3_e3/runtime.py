from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from aitest_runtime import browser as browser_owner
from aitest_runtime.common import new_id, now_iso
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.storage import all_rows
from aitest_runtime.r3_e2.contracts import (
    AuthSourceRef,
    BrowserContextRef,
    RuntimeVerificationReceipt,
    SUTAuthContextScope,
)
from aitest_runtime.r3_e2.ports import ContextReuseReceipt

from .backend import BrowserBackend, PlaywrightCDPBackend
from .contracts import (
    BLOCKED,
    NOT_CONFIGURED,
    READY,
    UNKNOWN,
    UNAVAILABLE,
    BrowserActionReceipt,
    BrowserActionRequest,
    BrowserContextObservation,
    CapabilityReport,
    EnvironmentBinding,
    LeaseHandoffReceipt,
    RuntimeBootstrapReceipt,
    RuntimeSession,
    RuntimeStateObservation,
    R3E3Error,
    redacted_digest,
)


class _BrowserSelector:
    def __init__(self, backend_factory: Callable[[], BrowserBackend]) -> None:
        self._backend_factory = backend_factory

    def getDefault(self) -> BrowserBackend:  # noqa: N802 - mirrors the controlled Browser client API
        return self._backend_factory()


class _BrowserClientRuntime:
    def __init__(self, backend_factory: Callable[[], BrowserBackend]) -> None:
        self.browsers = _BrowserSelector(backend_factory)


def setupBrowserRuntime(backend_factory: Callable[[], BrowserBackend] | None = None) -> _BrowserClientRuntime:  # noqa: N802
    """Initialize the controlled Browser client before Browser selection.

    The function intentionally mirrors the Browser client bootstrap name and
    is kept as a separate callable so tests can prove that setup precedes
    `agent.browsers.getDefault()`. The default selected backend is real CDP;
    no mock backend is installed by default.
    """

    return _BrowserClientRuntime(backend_factory or PlaywrightCDPBackend)


class BrowserRuntimeEntrypoint:
    def __init__(
        self,
        *,
        setup_browser_runtime: Callable[[], Any] = setupBrowserRuntime,
        browser_selector: Callable[[Any], BrowserBackend] | None = None,
    ) -> None:
        self._setup_browser_runtime = setup_browser_runtime
        self._browser_selector = browser_selector
        self.agent: Any | None = None
        self.browser: BrowserBackend | None = None
        self.receipt: RuntimeBootstrapReceipt | None = None

    def bootstrap(self) -> BrowserBackend:
        setup_completed = False
        try:
            # This call must remain before all Browser selection access. It is
            # the fixed boundary for the observed `agent is not defined` root
            # cause and is not an OpenCode agent/session wiring concern.
            self.agent = self._setup_browser_runtime()
            setup_completed = True
            if self.agent is None or getattr(self.agent, "browsers", None) is None:
                raise R3E3Error("R3_E3_BROWSER_CLIENT_INIT_FAILED", "setupBrowserRuntime did not return initialized Browser runtime")
            self.browser = self._browser_selector(self.agent) if self._browser_selector else self.agent.browsers.getDefault()
            if self.browser is None:
                raise R3E3Error("R3_E3_BROWSER_CLIENT_INIT_FAILED", "Browser selection returned no backend")
            bootstrap = self.browser.bootstrap()
            if not bootstrap.available:
                self.receipt = RuntimeBootstrapReceipt(
                    READY, READY, UNAVAILABLE, setup_completed, bootstrap.backend_kind,
                    bootstrap.source_ref, now_iso(), (bootstrap.reason_code or "R3_E3_BROWSER_BACKEND_UNAVAILABLE",),
                )
                raise R3E3Error(bootstrap.reason_code or "R3_E3_BROWSER_BACKEND_UNAVAILABLE", "controlled Browser backend is unavailable")
            self.receipt = RuntimeBootstrapReceipt(
                READY, READY, READY, setup_completed, bootstrap.backend_kind,
                bootstrap.source_ref, now_iso(), (),
            )
            return self.browser
        except R3E3Error:
            raise
        except Exception as exc:
            code = "R3_E3_BROWSER_CLIENT_INIT_FAILED"
            self.receipt = RuntimeBootstrapReceipt(
                READY if setup_completed else UNAVAILABLE,
                BLOCKED,
                BLOCKED,
                setup_completed,
                getattr(self.browser, "backend_kind", "UNKNOWN"),
                "runtime://r3.e3/bootstrap",
                now_iso(),
                (code,),
            )
            raise R3E3Error(code, f"Browser client bootstrap failed: {type(exc).__name__}") from exc


class ControlledBrowserRuntime:
    """Additive Browser/SUT runtime seam implementing the existing E2 port."""

    def __init__(
        self,
        *,
        backend_factory: Callable[[], BrowserBackend] | None = None,
        setup_browser_runtime: Callable[[], Any] | None = None,
        browser_selector: Callable[[Any], BrowserBackend] | None = None,
        environment_config: Mapping[str, Any] | None = None,
        environment_id: str = "UNKNOWN",
        human_gate_bridge: Any | None = None,
    ) -> None:
        self._backend_factory = backend_factory or PlaywrightCDPBackend
        self._entrypoint = BrowserRuntimeEntrypoint(
            setup_browser_runtime=setup_browser_runtime or (lambda: setupBrowserRuntime(self._backend_factory)),
            browser_selector=browser_selector,
        )
        self._environment_id = environment_id
        self._binding = EnvironmentBinding.from_mapping(environment_id, environment_config or {})
        self._human_gate_bridge = human_gate_bridge
        self._session: dict[str, Any] | None = None
        self._backend: BrowserBackend | None = None
        self._bootstrap_receipt: RuntimeBootstrapReceipt | None = None
        self._reasons: list[str] = []
        self._source_refs: list[str] = []
        self._capabilities: dict[str, str] = {
            "client_bootstrap_status": UNKNOWN,
            "browser_reachable": UNKNOWN,
            "session_create_lookup_status": UNKNOWN,
            "context_identity_status": UNKNOWN,
            "lease_handoff_status": UNKNOWN,
            "navigation_status": UNKNOWN,
            "action_status": UNKNOWN,
            "human_gate_bridge_status": UNKNOWN,
            "sut_endpoint_status": NOT_CONFIGURED if not self._binding.sut_base_url else UNKNOWN,
            "non_mock_verifier_status": NOT_CONFIGURED if not self._binding.protected_probe_url else UNKNOWN,
            "reuse_status": UNKNOWN,
        }
        self._idempotent_actions: dict[str, BrowserActionReceipt] = {}

    def bind_human_gate_bridge(self, bridge: Any) -> None:
        self._human_gate_bridge = bridge
        self._mark("human_gate_bridge_status", READY)

    def open_external_action(self, *, mission_id: str, lineage_refs: Mapping[str, Any], browser_context_ref: BrowserContextRef) -> Any:
        if self._human_gate_bridge is None:
            self._mark("human_gate_bridge_status", NOT_CONFIGURED, "R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE")
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 HumanGate bridge is not configured")
        result = self._human_gate_bridge.open_external_action(
            mission_id=mission_id,
            lineage_refs=lineage_refs,
            browser_context_ref=browser_context_ref,
        )
        self._mark("human_gate_bridge_status", READY)
        return result

    def read_decision(self, gate_ref: Any) -> Any:
        if self._human_gate_bridge is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 HumanGate bridge is not configured")
        return self._human_gate_bridge.read_decision(gate_ref)

    def record_resume(self, *, mission_id: str, gate_ref: Any, auth_context_id: str, browser_context_ref: BrowserContextRef) -> Any:
        if self._human_gate_bridge is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 continuation bridge is not configured")
        return self._human_gate_bridge.record_resume(
            mission_id=mission_id,
            gate_ref=gate_ref,
            auth_context_id=auth_context_id,
            browser_context_ref=browser_context_ref,
        )

    @property
    def binding(self) -> EnvironmentBinding:
        return self._binding

    @property
    def session(self) -> Mapping[str, Any] | None:
        return dict(self._session) if self._session else None

    @property
    def backend(self) -> BrowserBackend | None:
        return self._backend

    def _mark(self, capability: str, status: str, reason: str | None = None) -> None:
        self._capabilities[capability] = status
        if reason and reason not in self._reasons:
            self._reasons.append(reason)

    def capability_report(self) -> CapabilityReport:
        receipt = self._bootstrap_receipt
        return CapabilityReport(
            report_id=new_id("E3-CAP"),
            observed_at=now_iso(),
            backend_kind=getattr(self._backend, "backend_kind", "UNKNOWN"),
            reason_codes=tuple(self._reasons),
            source_refs=tuple(self._source_refs),
            **self._capabilities,
        )

    def bootstrap(self) -> RuntimeBootstrapReceipt:
        if self._bootstrap_receipt is not None:
            if self._backend is None:
                raise R3E3Error(self._bootstrap_receipt.reason_codes[0] if self._bootstrap_receipt.reason_codes else "R3_E3_BROWSER_CLIENT_INIT_FAILED", "Browser runtime is not available")
            return self._bootstrap_receipt
        try:
            self._backend = self._entrypoint.bootstrap()
            self._bootstrap_receipt = self._entrypoint.receipt
            self._mark("client_bootstrap_status", READY)
            self._mark("browser_reachable", UNKNOWN)
            if self._bootstrap_receipt:
                self._source_refs.append(self._bootstrap_receipt.source_ref)
            return self._bootstrap_receipt  # type: ignore[return-value]
        except R3E3Error as exc:
            self._mark("client_bootstrap_status", UNAVAILABLE, exc.code)
            self._mark("browser_reachable", BLOCKED, exc.code)
            self._bootstrap_receipt = self._entrypoint.receipt
            raise

    def _load_binding(self, request: Mapping[str, Any]) -> None:
        if request.get("environment_config") is not None:
            self._environment_id = str(request.get("environment_id") or self._environment_id)
            self._binding = EnvironmentBinding.from_mapping(self._environment_id, request.get("environment_config") or {})
        self._binding.require_endpoint(probe=False)
        self._mark("sut_endpoint_status", READY)

    def _find_existing_session(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        requested_id = request.get("browser_session_id")
        if requested_id:
            try:
                return browser_owner.get_browser_session(str(requested_id))
            except KeyError as exc:
                raise R3E3Error("R3_E3_BROWSER_SESSION_NOT_FOUND", f"BrowserSession not found: {requested_id}") from exc
        project_id = str(request.get("project_id") or "")
        mission_id = request.get("mission_id")
        environment_id = request.get("environment_id") or self._environment_id
        candidates = all_rows(
            "SELECT * FROM browser_sessions WHERE project_id=? AND (? IS NULL OR mission_id=?) AND (? IS NULL OR environment_id=?) ORDER BY updated_at DESC",
            (project_id, mission_id, mission_id, environment_id, environment_id),
        )
        return browser_owner.get_browser_session(candidates[0]["browser_session_id"]) if candidates else None

    def create_or_lookup_session(self, request: Mapping[str, Any]) -> RuntimeSession:
        self._load_binding(request)
        self.bootstrap()
        raw = dict(request)
        session = self._find_existing_session(raw)
        allowed_hosts = list(self._binding.allowed_hosts)
        start_url = str(raw.get("start_url") or self._binding.sut_base_url or "")
        if session is None:
            project_id = raw.get("project_id")
            if not project_id:
                raise R3E3Error("R3_E3_BROWSER_SESSION_NOT_FOUND", "project_id is required to create BrowserSession")
            session = browser_owner.create_browser_session(
                str(project_id),
                "CONTROLLED",
                mission_id=raw.get("mission_id"),
                environment_id=raw.get("environment_id") or self._environment_id,
                auth_profile_id=raw.get("auth_profile_id"),
                lease_owner="AI",
                start_url=start_url,
                allowed_domains=allowed_hosts,
            )
        else:
            session = browser_owner.get_browser_session(session["browser_session_id"])
        if str(session.get("lease_owner", "")).upper() != "AI":
            raise R3E3Error("R3_E3_BROWSER_LEASE_CONFLICT", "controlled runtime must bind the executor AI lease before AUTH_REQUIRED")
        assert self._backend is not None
        if getattr(self._backend, "requires_browser_launch", False) and (
            str(session.get("status")) != "OPEN" or not session.get("debug_port")
        ):
            launched = browser_owner.launch_browser(
                str(session["project_id"]),
                "CONTROLLED",
                browser_session_id=session["browser_session_id"],
                mission_id=session.get("mission_id"),
                environment_id=session.get("environment_id"),
                auth_profile_id=session.get("auth_profile_id"),
                start_url=start_url,
                allowed_domains=allowed_hosts,
                dry_run=False,
            )
            session = launched["browser_session"]
            if not launched.get("launched"):
                raise R3E3Error("R3_E3_BROWSER_BACKEND_UNAVAILABLE", "existing Browser runtime could not launch controlled Browser")
        try:
            self._backend.connect(session)
            session = browser_owner.get_browser_session(session["browser_session_id"])
            observation = self._observe(session)
        except R3E3Error as exc:
            self._mark("browser_reachable", UNAVAILABLE, exc.code)
            raise
        self._session = session
        self._mark("browser_reachable", READY)
        self._mark("session_create_lookup_status", READY)
        self._mark("context_identity_status", READY if observation.live else BLOCKED)
        self._mark("lease_handoff_status", READY)
        self._source_refs.append(observation.source_ref)
        return RuntimeSession(session, self._to_context_ref(observation), self.capability_report(), observation.observed_at)

    def _require_session(self) -> dict[str, Any]:
        if self._session is None or self._backend is None:
            raise R3E3Error("R3_E3_BROWSER_SESSION_NOT_FOUND", "controlled BrowserSession has not been bound")
        return browser_owner.get_browser_session(self._session["browser_session_id"])

    def _observe(self, session: Mapping[str, Any] | None = None) -> BrowserContextObservation:
        current = session or self._require_session()
        if self._backend is None:
            raise R3E3Error("R3_E3_BROWSER_BACKEND_UNAVAILABLE", "Browser backend is not selected")
        try:
            observation = self._backend.inspect(current)
        except R3E3Error:
            raise
        except Exception as exc:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_NOT_FOUND", "live context inspection failed") from exc
        if not observation.live:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_CLOSED", "Browser process/context is not live")
        return observation

    @staticmethod
    def _to_context_ref(observation: BrowserContextObservation) -> BrowserContextRef:
        return BrowserContextRef(
            observation.browser_session_id,
            observation.context_id_or_epoch,
            observation.context_binding_digest,
            observation.lease_owner,
            observation.observed_at,
        )

    def context_observation(self, browser_context_ref: BrowserContextRef) -> BrowserContextObservation:
        session = self._require_session()
        observation = self._observe(session)
        if observation.browser_session_id != browser_context_ref.browser_session_id:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_NOT_FOUND", "BrowserSession identity does not match context reference")
        if observation.context_id_or_epoch != browser_context_ref.browser_context_id_or_epoch:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_REPLACED", "Browser context epoch differs from context reference")
        if observation.context_binding_digest != browser_context_ref.context_binding_digest:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_REPLACED", "Browser context binding differs from context reference")
        return observation

    def inspect_context(self, browser_context_ref: BrowserContextRef) -> BrowserContextRef:
        return self._to_context_ref(self.context_observation(browser_context_ref))

    def inspect_lease(self, browser_context_ref: BrowserContextRef) -> str:
        observation = self.context_observation(browser_context_ref)
        return observation.lease_owner

    def inspect_runtime(self) -> RuntimeStateObservation:
        session = self._require_session()
        try:
            observation = self._observe(session)
            return RuntimeStateObservation(session["browser_session_id"], "OPEN", "OPEN", observation.context_id_or_epoch, observation.lease_owner, observation.observed_at)
        except R3E3Error as exc:
            return RuntimeStateObservation(session["browser_session_id"], str(session.get("status")), "CLOSED", None, session.get("lease_owner"), now_iso(), exc.code)

    def _assert_expected_context(self, browser_context_ref: BrowserContextRef, expected_lease_owner: str) -> tuple[dict[str, Any], BrowserContextObservation]:
        session = self._require_session()
        observation = self.context_observation(browser_context_ref)
        expected = expected_lease_owner.upper()
        if observation.lease_owner != expected:
            self._mark("lease_handoff_status", BLOCKED, "R3_E3_BROWSER_LEASE_CONFLICT")
            raise R3E3Error("R3_E3_BROWSER_LEASE_CONFLICT", f"expected lease {expected}, observed {observation.lease_owner}")
        return session, observation

    def _allowed_url(self, target: str) -> None:
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            raise R3E3Error("R3_E3_BROWSER_DOMAIN_NOT_ALLOWED", "real SUT navigation requires an absolute HTTP(S) URL")
        if self._binding.allowed_hosts and parsed.hostname and parsed.hostname.lower() not in self._binding.allowed_hosts and not any(
            item.startswith(".") and parsed.hostname.lower().endswith(item) for item in self._binding.allowed_hosts
        ):
            raise R3E3Error("R3_E3_BROWSER_DOMAIN_NOT_ALLOWED", f"navigation host is not allowed: {parsed.hostname}")

    def navigate(self, browser_context_ref: BrowserContextRef, url: str, *, request_id: str | None = None, idempotency_key: str | None = None) -> BrowserActionReceipt:
        self._binding.require_endpoint(probe=False)
        self._allowed_url(url)
        request = BrowserActionRequest(request_id or new_id("BA"), "NAVIGATE", url, None, "AI", idempotency_key or request_id or new_id("BA-IDEMP"))
        if request.idempotency_key in self._idempotent_actions:
            return self._idempotent_actions[request.idempotency_key]
        session, _ = self._assert_expected_context(browser_context_ref, "AI")
        assert self._backend is not None
        try:
            observation = self._backend.navigate(session, url)
        except R3E3Error as exc:
            self._mark("navigation_status", BLOCKED, exc.code)
            raise
        receipt = BrowserActionReceipt(request.request_id, new_id("BACT"), True, getattr(self._backend, "backend_kind", "UNKNOWN"), browser_context_ref, observation.observed_url_or_origin, observation.outcome, observation.state_digest, observation.source_ref, now_iso())
        self._idempotent_actions[request.idempotency_key] = receipt
        self._mark("navigation_status", READY)
        return receipt

    def execute_action(self, browser_context_ref: BrowserContextRef, request: BrowserActionRequest | Mapping[str, Any], *, value: str | None = None) -> BrowserActionReceipt:
        action = request if isinstance(request, BrowserActionRequest) else BrowserActionRequest.from_mapping(request)
        if action.action_kind == "NAVIGATE":
            return self.navigate(browser_context_ref, action.target, request_id=action.request_id, idempotency_key=action.idempotency_key)
        self._binding.require_endpoint(probe=False)
        if action.action_kind == "FILL_NON_SECRET" and value is None:
            raise R3E3Error("R3_E3_REAL_ACTION_REQUIRED", "non-secret fill requires an in-memory value; manual 4A fields are not adapter inputs")
        if action.idempotency_key in self._idempotent_actions:
            return self._idempotent_actions[action.idempotency_key]
        session, _ = self._assert_expected_context(browser_context_ref, action.expected_lease_owner)
        assert self._backend is not None
        try:
            observation = self._backend.action(session, action.action_kind, action.target, value)
        except R3E3Error as exc:
            self._mark("action_status", BLOCKED, exc.code)
            raise
        receipt = BrowserActionReceipt(action.request_id, new_id("BACT"), True, getattr(self._backend, "backend_kind", "UNKNOWN"), browser_context_ref, observation.observed_url_or_origin, observation.outcome, observation.state_digest, observation.source_ref, now_iso())
        self._idempotent_actions[action.idempotency_key] = receipt
        self._mark("action_status", READY)
        return receipt

    def verify_authenticated_runtime(self, *, browser_context_ref: BrowserContextRef, requested_scope: SUTAuthContextScope, policy: Mapping[str, Any]) -> RuntimeVerificationReceipt:
        self._binding.require_endpoint(probe=True)
        session, observation = self._assert_expected_context(browser_context_ref, "AI")
        assert self._backend is not None
        effective_policy = {**dict(self._binding.verifier_policy), **dict(policy or {})}
        try:
            verifier = self._backend.verify_protected_probe(session, self._binding.protected_probe_url or "", effective_policy)
        except R3E3Error as exc:
            self._mark("non_mock_verifier_status", UNAVAILABLE, exc.code)
            raise
        if not verifier.authenticated or not verifier.principal_ref:
            self._mark("non_mock_verifier_status", BLOCKED, verifier.reason_code or "R3_E3_SUT_VERIFICATION_FAILED")
            raise R3E3Error(verifier.reason_code or "R3_E3_SUT_VERIFICATION_FAILED", "protected SUT verifier did not observe authenticated state")
        if verifier.verifier_kind.upper() in {"MOCK", "FAKE", "NOT_CONFIGURED"}:
            self._mark("non_mock_verifier_status", BLOCKED, "R3_E3_MOCK_NOT_ACCEPTED")
            raise R3E3Error("R3_E3_MOCK_NOT_ACCEPTED", "mock/fake/not-configured verifier cannot produce runtime proof")
        observed_ref = self._to_context_ref(observation)
        if observed_ref != browser_context_ref:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_REPLACED", "live verifier context differs from original E2 context")
        verified_at = verifier.observed_at or now_iso()
        try:
            parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(timezone.utc)
            verified_at = parsed.isoformat().replace("+00:00", "Z")
        ttl = int(effective_policy.get("ttl_seconds") or 300)
        ttl = max(1, min(ttl, 3600))
        expires_at = (parsed + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z")
        source = AuthSourceRef(
            f"e3-source-{verifier.source_digest[:16]}",
            "RUNTIME_VERIFICATION",
            verifier.source_locator,
            verifier.source_revision,
            verifier.source_digest,
            requested_scope,
            verified_at,
            {"backend_kind": getattr(self._backend, "backend_kind", "UNKNOWN")},
        )
        receipt = RuntimeVerificationReceipt(
            f"e3-verification-{verifier.source_digest[:16]}",
            True,
            verifier.verifier_kind,
            verifier.principal_ref,
            requested_scope.digest,
            browser_context_ref,
            verified_at,
            expires_at,
            source,
            "AI",
            redacted_digest({"source_digest": verifier.source_digest, "checks": dict(verifier.checks), "scope": requested_scope.to_dict()}),
            dict(verifier.checks),
        )
        self._mark("non_mock_verifier_status", READY)
        return receipt

    def reuse_context(self, *, browser_context_ref: BrowserContextRef, requested_scope: SUTAuthContextScope) -> ContextReuseReceipt:
        self._binding.require_endpoint(probe=False)
        _, observation = self._assert_expected_context(browser_context_ref, "AI")
        if self._to_context_ref(observation) != browser_context_ref:
            self._mark("reuse_status", BLOCKED, "R3_E3_BROWSER_CONTEXT_REPLACED")
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_REPLACED", "context identity changed before reuse")
        receipt = ContextReuseReceipt(True, browser_context_ref, requested_scope.digest, f"e3-reuse-{canonical_sha256(browser_context_ref.to_dict())[:16]}", now_iso())
        self._mark("reuse_status", READY)
        return receipt

    def transfer_lease(self, browser_context_ref: BrowserContextRef, *, from_owner: str, to_owner: str) -> LeaseHandoffReceipt:
        from_owner = from_owner.upper()
        to_owner = to_owner.upper()
        session, before = self._assert_expected_context(browser_context_ref, from_owner)
        try:
            browser_owner.transfer_lease(session["browser_session_id"], from_owner, to_owner)
            after_session = browser_owner.get_browser_session(session["browser_session_id"])
            after = self._observe(after_session)
        except PermissionError as exc:
            self._mark("lease_handoff_status", BLOCKED, "R3_E3_BROWSER_LEASE_CONFLICT")
            raise R3E3Error("R3_E3_BROWSER_LEASE_CONFLICT", "existing Browser lease transfer rejected") from exc
        if before.context_id_or_epoch != after.context_id_or_epoch or before.context_binding_digest != after.context_binding_digest:
            self._mark("lease_handoff_status", BLOCKED, "R3_E3_BROWSER_CONTEXT_REPLACED")
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_REPLACED", "lease transfer did not preserve context identity/epoch")
        self._session = after_session
        self._mark("lease_handoff_status", READY)
        return LeaseHandoffReceipt(
            new_id("E3-LEASE"),
            session["browser_session_id"],
            from_owner,
            to_owner,
            before.context_id_or_epoch,
            after.context_id_or_epoch,
            before.context_binding_digest,
            after.context_binding_digest,
            after.observed_at,
            True,
            f"runtime://browser/{session['browser_session_id']}/lease-handoff",
        )

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
        self._backend = None
