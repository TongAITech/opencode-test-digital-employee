from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from aitest_runtime.common import now_iso, redact
from aitest_runtime.durable_core import canonical_sha256

from .contracts import BrowserContextObservation, R3E3Error


@dataclass(frozen=True)
class BackendBootstrap:
    backend_kind: str
    available: bool
    revision: str
    source_ref: str
    reason_code: str | None = None


@dataclass(frozen=True)
class BackendActionObservation:
    outcome: str
    observed_url_or_origin: str | None
    state_digest: str
    source_ref: str
    status_code: int | None = None


@dataclass(frozen=True)
class VerifierObservation:
    authenticated: bool
    principal_ref: str | None
    verifier_kind: str
    source_locator: str
    source_revision: str
    source_digest: str
    status_code: int | None
    checks: Mapping[str, Any]
    observed_at: str
    reason_code: str | None = None


class BrowserBackend(Protocol):
    backend_kind: str
    requires_browser_launch: bool

    def bootstrap(self) -> BackendBootstrap:
        ...

    def connect(self, browser_session: Mapping[str, Any]) -> None:
        ...

    def inspect(self, browser_session: Mapping[str, Any]) -> BrowserContextObservation:
        ...

    def navigate(self, browser_session: Mapping[str, Any], url: str) -> BackendActionObservation:
        ...

    def action(self, browser_session: Mapping[str, Any], action_kind: str, target: str, value: str | None = None) -> BackendActionObservation:
        ...

    def verify_protected_probe(
        self,
        browser_session: Mapping[str, Any],
        probe_url: str,
        policy: Mapping[str, Any],
    ) -> VerifierObservation:
        ...

    def close(self) -> None:
        ...


class PlaywrightCDPBackend:
    """Real controlled Browser backend over the existing Chrome CDP port.

    The dependency is imported lazily so the package remains importable when
    Playwright is not installed. A missing dependency is an explicit runtime
    capability gap, never a mock success.
    """

    backend_kind = "PLAYWRIGHT_CDP"
    requires_browser_launch = True

    def __init__(self, *, playwright_factory: Any | None = None) -> None:
        self._playwright_factory = playwright_factory
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._session: Mapping[str, Any] | None = None
        self._revision = "playwright-cdp-v1"

    def bootstrap(self) -> BackendBootstrap:
        try:
            if self._playwright_factory is not None:
                self._playwright_factory
            else:
                import playwright.sync_api  # noqa: F401
        except Exception as exc:
            return BackendBootstrap(self.backend_kind, False, self._revision, "runtime://playwright-cdp", "R3_E3_BROWSER_BACKEND_UNAVAILABLE")
        return BackendBootstrap(self.backend_kind, True, self._revision, "runtime://playwright-cdp")

    def connect(self, browser_session: Mapping[str, Any]) -> None:
        debug_port = browser_session.get("debug_port")
        if not debug_port:
            raise R3E3Error("R3_E3_BROWSER_BACKEND_UNAVAILABLE", "BrowserSession has no live debug port")
        cdp_endpoint = browser_session.get("cdp_endpoint") or os.environ.get("AITEST_BROWSER_CDP_ENDPOINT")
        if not cdp_endpoint:
            cdp_endpoint = f"http://127.0.0.1:{int(debug_port)}"
        else:
            cdp_endpoint = str(cdp_endpoint).replace("{debug_port}", str(int(debug_port)))
            if "://" not in cdp_endpoint:
                cdp_endpoint = f"http://{cdp_endpoint}"
        try:
            if self._playwright_factory is not None:
                self._playwright = self._playwright_factory().start()
            else:
                from playwright.sync_api import sync_playwright

                self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_endpoint)
            contexts = list(self._browser.contexts)
            if not contexts:
                raise R3E3Error("R3_E3_BROWSER_CONTEXT_NOT_FOUND", "controlled Browser exposed no context")
            self._context = contexts[0]
            pages = list(self._context.pages)
            self._page = pages[0] if pages else self._context.new_page()
            self._session = dict(browser_session)
        except R3E3Error:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise R3E3Error("R3_E3_BROWSER_BACKEND_UNAVAILABLE", f"controlled Browser CDP connection failed: {type(exc).__name__}") from exc

    def _require_connected(self, browser_session: Mapping[str, Any]) -> None:
        if self._browser is None or self._context is None or self._page is None:
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_NOT_FOUND", "controlled Browser context is not connected")
        if hasattr(self._browser, "is_connected") and not self._browser.is_connected():
            raise R3E3Error("R3_E3_BROWSER_CONTEXT_CLOSED", "controlled Browser connection is closed")
        process_id = browser_session.get("process_id")
        if process_id:
            try:
                os.kill(int(process_id), 0)
            except OSError as exc:
                raise R3E3Error("R3_E3_BROWSER_CONTEXT_CLOSED", "Browser process is dead") from exc

    def _context_guid(self) -> str:
        impl = getattr(self._context, "_impl_obj", None)
        guid = getattr(impl, "_guid", None)
        if guid:
            return str(guid)
        return str(id(self._context))

    def _state_digest(self) -> str:
        try:
            url = str(self._page.url or "")
            title = str(self._page.title() or "")
        except Exception:
            url, title = "", ""
        return hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()

    def _origin(self) -> str | None:
        try:
            url = str(self._page.url or "")
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url or None
        except Exception:
            return None

    def inspect(self, browser_session: Mapping[str, Any]) -> BrowserContextObservation:
        self._require_connected(browser_session)
        process_id = str(browser_session.get("process_id") or "unknown")
        debug_port = str(browser_session.get("debug_port") or "unknown")
        context_id = f"{process_id}:{debug_port}:{self._context_guid()}"
        binding_digest = canonical_sha256({
            "browser_session_id": browser_session.get("browser_session_id"),
            "context_id_or_epoch": context_id,
            "backend": self.backend_kind,
        })
        return BrowserContextObservation(
            browser_session_id=str(browser_session["browser_session_id"]),
            context_id_or_epoch=context_id,
            context_binding_digest=binding_digest,
            lease_owner=str(browser_session.get("lease_owner") or "UNKNOWN").upper(),
            process_alive=True,
            context_alive=True,
            current_origin=self._origin(),
            state_digest=self._state_digest(),
            observed_at=now_iso(),
            backend_kind=self.backend_kind,
            source_ref=f"runtime://browser/{browser_session['browser_session_id']}/{context_id}",
        )

    def navigate(self, browser_session: Mapping[str, Any], url: str) -> BackendActionObservation:
        self._require_connected(browser_session)
        try:
            response = self._page.goto(url, wait_until="domcontentloaded")
            status = int(response.status) if response is not None else None
            if status is not None and status >= 400:
                raise R3E3Error("R3_E3_BROWSER_NAVIGATION_FAILED", f"SUT navigation returned HTTP {status}")
            return BackendActionObservation("NAVIGATED", self._origin(), self._state_digest(), "runtime://browser/navigation", status)
        except R3E3Error:
            raise
        except Exception as exc:
            raise R3E3Error("R3_E3_BROWSER_NAVIGATION_FAILED", f"real navigation failed: {type(exc).__name__}") from exc

    def action(self, browser_session: Mapping[str, Any], action_kind: str, target: str, value: str | None = None) -> BackendActionObservation:
        self._require_connected(browser_session)
        kind = action_kind.upper()
        try:
            if kind == "CLICK":
                self._page.locator(target).click()
            elif kind == "FILL_NON_SECRET":
                if value is None:
                    raise R3E3Error("R3_E3_REAL_ACTION_REQUIRED", "FILL_NON_SECRET requires an in-memory non-secret value")
                self._page.locator(target).fill(value)
            elif kind == "SUBMIT":
                self._page.locator(target).press("Enter")
            elif kind == "READ_STATE":
                pass
            else:
                raise R3E3Error("R3_E3_REAL_ACTION_REQUIRED", f"unsupported real Browser action: {kind}")
            return BackendActionObservation(kind, self._origin(), self._state_digest(), f"runtime://browser/action/{kind}")
        except R3E3Error:
            raise
        except Exception as exc:
            raise R3E3Error("R3_E3_BROWSER_ACTION_FAILED", f"real Browser action failed: {type(exc).__name__}") from exc

    def verify_protected_probe(self, browser_session: Mapping[str, Any], probe_url: str, policy: Mapping[str, Any]) -> VerifierObservation:
        self._require_connected(browser_session)
        try:
            response = self._page.goto(probe_url, wait_until="domcontentloaded")
            status = int(response.status) if response is not None else None
            selector = policy.get("principal_selector")
            if not selector:
                return VerifierObservation(False, None, "PLAYWRIGHT_CDP_SUT_PROBE", probe_url, self._revision, self._state_digest(), status, {"protected_probe": False, "principal_observed": False}, now_iso(), "R3_E3_SUT_VERIFIER_UNAVAILABLE")
            text = self._page.locator(str(selector)).first.text_content()
            principal_value = (text or "").strip()
            expected_marker = policy.get("authenticated_marker")
            authenticated = bool(status is not None and 200 <= status < 400 and principal_value and (not expected_marker or expected_marker in principal_value))
            principal_ref = f"principal:{hashlib.sha256(principal_value.encode('utf-8')).hexdigest()}" if authenticated else None
            source_digest = canonical_sha256({"probe_url": probe_url, "status": status, "state_digest": self._state_digest()})
            return VerifierObservation(
                authenticated,
                principal_ref,
                "PLAYWRIGHT_CDP_SUT_PROBE",
                probe_url,
                self._revision,
                source_digest,
                status,
                {"protected_probe": authenticated, "principal_observed": bool(principal_ref), "status_code": status},
                now_iso(),
                None if authenticated else "R3_E3_SUT_VERIFICATION_FAILED",
            )
        except R3E3Error:
            raise
        except Exception as exc:
            raise R3E3Error("R3_E3_SUT_VERIFIER_UNAVAILABLE", f"protected SUT probe failed: {type(exc).__name__}") from exc

    def close(self) -> None:
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
