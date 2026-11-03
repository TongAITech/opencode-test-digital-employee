"""Lease-fenced real human browser event collector for RC7.2 Journey Teaching.

The human uses an already running, independently leased browser. This collector
observes DOM actions and network response metadata through Playwright/CDP,
persists on-disk snapshots/screenshot evidence, and sends non-executable
recording steps to JourneyTeachingService. It never stores input values,
cookies, request bodies, or response bodies.

Invoke poll() during teaching; explicit input value/credential references and
business assertions are supplied by a separate human-controlled binding step.
Recording is not promoted and is not itself a runnable Journey.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode
from .rc72_journey_playwright import JourneyPlaywrightAdapter, _atomic_json, _public_url, _safe_id
from .rc72_journey_teaching import JourneyActionType, JourneyTeachingService

_CAPTURE_SCRIPT = r"""
(() => {
 if (window.__rc72Capture) return;
 const events = [];
 const ref = el => {
   if (!el || !el.tagName) return null;
   if (el.getAttribute('data-testid')) return 'testid:' + el.getAttribute('data-testid');
   if (el.id) return 'css:#' + CSS.escape(el.id);
   if (el.getAttribute('name')) return 'css:' + el.tagName.toLowerCase() +
     '[name="' + CSS.escape(el.getAttribute('name')) + '"]';
   return null;
 };
 const push = (type, e) => {
   const el = e.target;
   if (el && el.closest && el.closest('[data-rc72-no-record]')) return;
   const r = ref(el);
   const payload = {type, element_ref:r, tag:el && el.tagName || 'UNKNOWN',
     url:location.origin + location.pathname, at:Date.now()};
   if (typeof window.__rc72ReportEvent === 'function') {
     Promise.resolve(window.__rc72ReportEvent(payload)).catch(() => events.push(payload));
   } else events.push(payload);
 };
 document.addEventListener('click', e => push('CLICK', e), true);
 document.addEventListener('change', e => push(e.target && e.target.tagName === 'SELECT' ? 'SELECT' : 'INPUT', e), true);
 window.__rc72Capture = {drain: () => events.splice(0)};
})()
"""

_DOM_SUMMARY_SCRIPT = """() => ({
 ready_state: document.readyState, title: document.title,
 elements: Array.from(document.querySelectorAll('a,button,input,select,textarea,[role]'))
   .slice(0, 500).map(x => ({
     tag: x.tagName, id: x.id, role: x.getAttribute('role'),
     testid: x.getAttribute('data-testid'), name: x.getAttribute('name'),
     type: x.getAttribute('type'), disabled: !!x.disabled
   }))
})"""


class JourneyCDPTeachingRecorder:
    adapter_kind = "PLAYWRIGHT_CDP_TEACHING"
    field_verified = False

    def __init__(
        self,
        *,
        teaching: JourneyTeachingService,
        evidence_root: Path,
        connector=None,
        timeout_ms: int = 15000,
    ) -> None:
        if not isinstance(teaching, JourneyTeachingService):
            raise ContractError("JOURNEY_TEACHING_SERVICE_REQUIRED")
        self.teaching = teaching
        self.pool = teaching.browser_pool
        self.browser = JourneyPlaywrightAdapter(
            browser_pool=self.pool, evidence_root=evidence_root,
            reference_resolver=lambda ref, kind, context: None,
            connector=connector, timeout_ms=timeout_ms)
        self.root = Path(evidence_root).resolve()
        self.recording = None
        self.page = None
        self.responses: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self._response_listener = None
        self.last_url = ""

    def _guard(self) -> Dict[str, Any]:
        if self.recording is None:
            raise ContractError("JOURNEY_TEACHING_NOT_STARTED")
        r = self.recording
        lease = self.pool.assert_usable(
            browser_lease_id=r["browser_lease_id"], mission_id=r["mission_id"],
            workitem_id=r["workitem_id"], attempt_id=r["attempt_id"],
            worker_id=r["worker_id"], access_mode=BrowserAccessMode.WRITE)
        if str(lease.get("purpose") or "").upper() != "JOURNEY_TEACHING":
            raise ContractError("JOURNEY_TEACHING_BROWSER_PURPOSE_MISMATCH")
        rows = self.pool.truth.query(
            "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])
        if len(rows) != 1 or rows[0].get("state") != "READY":
            raise ContractError("JOURNEY_TEACHING_BROWSER_INSTANCE_UNAVAILABLE")
        return rows[0]

    def begin(self, **recording_args: Any) -> None:
        if self.recording is not None:
            raise ContractError("JOURNEY_TEACHING_ALREADY_STARTED")
        # Establish exact ownership before registering the capture state.
        self.recording = dict(recording_args)
        try:
            instance = self._guard()
            endpoint = str(instance["cdp_endpoint"])
            if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:", "ws://127.0.0.1:", "ws://localhost:")):
                raise ContractError("JOURNEY_TEACHING_CDP_LOCAL_ENDPOINT_REQUIRED")
            page = self.browser._page(endpoint)
            if callable(getattr(page.context, "expose_binding", None)):
                page.context.expose_binding(
                    "__rc72ReportEvent", lambda source, event: self.events.append(dict(event)))
            page.context.add_init_script(script=_CAPTURE_SCRIPT)
            page.evaluate(_CAPTURE_SCRIPT)
            self.page = page
            self.last_url = _public_url(page.url)
            def response_listener(response: Any) -> None:
                try:
                    self.responses.append({
                        "url": _public_url(response.url),
                        "method": str(response.request.method),
                        "status": int(response.status),
                        "captured_at": int(time.time()),
                    })
                except Exception:
                    pass
            page.on("response", response_listener)
            self._response_listener = response_listener
            self.teaching.start_recording(**recording_args)
            # A teaching run begun on an already-loaded application needs an
            # initial navigation in its replayable IR, not a bare CLICK.
            if self.last_url.startswith(("https://", "http://")):
                self._step(action_type="NAVIGATE", element_ref=None,
                           page_role="INITIAL_PAGE", metadata={"label": "initial navigation"})
        except Exception:
            self.stop()
            raise

    def _step(
        self,
        *,
        action_type: str,
        element_ref: Optional[str],
        page_role: str,
        metadata: Mapping[str, Any],
        event_url: Optional[str] = None,
    ) -> str:
        self._guard()
        if self.page is None:
            raise ContractError("JOURNEY_TEACHING_PAGE_UNAVAILABLE")
        recording_id = _safe_id(self.recording["recording_id"])
        current = self.teaching.truth.query("rc72_journey_recording", recording_id=recording_id)
        if len(current) != 1 or current[0]["state"] != "CAPTURING":
            raise ContractError("JOURNEY_TEACHING_RECORDING_NOT_ACTIVE")
        sequence = int(current[0]["step_count"]) + 1
        folder = self.root / recording_id / ("capture-%04d" % sequence)
        url = _public_url(event_url or self.page.url)
        try:
            dom = self.page.evaluate(_DOM_SUMMARY_SCRIPT)
        except Exception as exc:
            raise ContractError("JOURNEY_TEACHING_DOM_CAPTURE_FAILED") from exc
        page_ref = _atomic_json(folder / "page.json", {
            "url": url, "role": page_role, "captured_at": int(time.time()),
            "auth_asset_ref": self.recording.get("auth_asset_ref"),
        })
        dom_ref = _atomic_json(folder / "dom.json", dom)
        network_ref = _atomic_json(folder / "network.json", {"responses": list(self.responses)})
        self.responses.clear()
        try:
            self._guard()
            folder.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(
                path=str(folder / "screen.png"), full_page=True,
                mask=[self.page.locator('input[type="password"],input[autocomplete="one-time-code"]')],
                timeout=self.browser.timeout_ms)
        except Exception as exc:
            raise ContractError("JOURNEY_TEACHING_SCREENSHOT_REQUIRED") from exc
        screenshot_ref = (folder / "screen.png").resolve().as_uri()
        # All inputs are ref-bound after capture, never copied from DOM events.
        allowed_metadata = {"label": str(metadata.get("label") or action_type)}
        for key in ("value_ref", "oracle_ref", "api_code_mapping_ref"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                allowed_metadata[key] = value.strip()
        wait = str(metadata.get("wait_semantics") or "domcontentloaded")
        self._guard()
        self.teaching.append_step(
            recording_id=recording_id, step_id="%s:%d" % (recording_id, sequence),
            sequence=sequence, action_type=JourneyActionType(action_type),
            url=url, page_role=page_role, element_ref=element_ref,
            page_state_ref=page_ref, dom_ref=dom_ref,
            network_refs=[network_ref], screenshot_ref=screenshot_ref,
            wait_semantics=wait, evidence_refs=[page_ref, dom_ref, network_ref, screenshot_ref],
            capture_metadata=allowed_metadata,
            credential_ref=metadata.get("credential_ref"))
        return "%s:%d" % (recording_id, sequence)

    def poll(self, *, page_role: str, bindings: Optional[Mapping[str, Mapping[str, Any]]] = None) -> List[str]:
        self._guard()
        if self.page is None:
            raise ContractError("JOURNEY_TEACHING_PAGE_UNAVAILABLE")
        buffered = list(self.events)
        self.events.clear()
        drained = self.page.evaluate("() => window.__rc72Capture ? window.__rc72Capture.drain() : []")
        if not isinstance(drained, list):
            raise ContractError("JOURNEY_TEACHING_EVENTS_INVALID")
        events = buffered + drained
        result = []
        current_url = _public_url(self.page.url)
        for event in events:
            if not isinstance(event, dict) or event.get("type") not in {"CLICK", "INPUT", "SELECT"}:
                raise ContractError("JOURNEY_TEACHING_EVENT_INVALID")
            ref = event.get("element_ref")
            if not ref:
                raise ContractError("JOURNEY_TEACHING_ELEMENT_LOCATOR_REQUIRED")
            bound = (bindings or {}).get(ref, {})
            if not isinstance(bound, Mapping):
                raise ContractError("JOURNEY_TEACHING_BINDING_INVALID")
            result.append(self._step(
                action_type=event["type"], element_ref=ref,
                page_role=page_role, metadata=dict(bound),
                event_url=event.get("url")))
        # DOM event happened before the navigation it triggered; the IR order
        # must preserve CLICK -> NAVIGATE, not NAVIGATE -> CLICK.
        if current_url != self.last_url:
            result.append(self._step(action_type="NAVIGATE", element_ref=None,
                                     page_role=page_role, metadata={"label": "navigation"}))
            self.last_url = current_url
        return result

    def record_assertion(self, *, page_role: str, oracle_ref: str,
                         element_ref: Optional[str] = None) -> str:
        if not isinstance(oracle_ref, str) or not oracle_ref.strip():
            raise ContractError("JOURNEY_TEACHING_ORACLE_REF_REQUIRED")
        return self._step(action_type="ASSERT", element_ref=element_ref,
                          page_role=page_role, metadata={"oracle_ref": oracle_ref})

    def record_wait(self, *, page_role: str, wait_semantics: str,
                    element_ref: Optional[str] = None) -> str:
        if wait_semantics not in {"network-idle", "networkidle", "domcontentloaded", "load", "visible"}:
            raise ContractError("JOURNEY_TEACHING_WAIT_SEMANTICS_INVALID")
        return self._step(action_type="WAIT", element_ref=element_ref,
                          page_role=page_role, metadata={"wait_semantics": wait_semantics})

    def finish(self) -> Any:
        self._guard()
        ref = _atomic_json(
            self.root / _safe_id(self.recording["recording_id"]) / "teaching-summary.json",
            {"recording_id": self.recording["recording_id"],
             "completed_at": int(time.time()), "browser_kind": self.adapter_kind})
        result = self.teaching.complete_recording(
            recording_id=self.recording["recording_id"], evidence_refs=[ref])
        self.stop()
        return result

    def stop(self) -> None:
        if self.page is not None and self._response_listener is not None:
            try:
                self.page.remove_listener("response", self._response_listener)
            except Exception:
                pass
        self.browser.close()
        self.page = None
        self.recording = None
        self._response_listener = None
        self.responses.clear()
