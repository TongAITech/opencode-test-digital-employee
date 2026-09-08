"""Local CDP browser observation and R1-governed Human Takeover port.

Browser profiles/processes are operational resources. Teaching, lease decisions
and HumanGate state are written only through canonical G3/G4 services.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote

from .canonical_runtime import create_canonical_runtime, runtime_status
from .common import now_iso
from .durable_core import canonical_sha256
from .g3.service import G3TestingIntelligenceService
from .r3_e2.contracts import BrowserContextRef

SENSITIVE = re.compile(r"password|passwd|pwd|secret|token|authorization|cookie|credential|otp|mfa|private.?key|account.?number|card.?number", re.I)
AUTH_PATH = re.compile(r"(^|/)(login|signin|sign-in|auth|oauth|sso|4a|mfa|otp)(/|$)", re.I)


def safe_url(value):
    parsed = urlsplit(str(value))
    if parsed.scheme not in {"http", "https"}:
        return "about:blank"
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def scrub(value, depth=0):
    if depth > 5:
        return "[depth limited]"
    if isinstance(value, dict):
        return {str(key)[:80]: scrub(item, depth + 1) for key, item in list(value.items())[:50] if not SENSITIVE.search(str(key))}
    if isinstance(value, list):
        return [scrub(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[^\s]+", "[redacted]", value)
        value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted]", value)
        value = re.sub(r"(?i)(password|passwd|pwd|secret|token|otp|cookie|authorization)\s*[:=]\s*[^\s,;]+", "[redacted]", value)
        value = re.sub(r"\b\d{12,19}\b", "[redacted]", value)
        return value[:1024]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported]"


def load_binding(root):
    path = Path(root) / "bindings/browser.json"
    if not path.is_file():
        raise RuntimeError("BROWSER_BANK_BINDING_REQUIRED")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("approved") is not True or not value.get("approval_ref") or not value.get("allowed_origins"):
        raise RuntimeError("BROWSER_APPROVED_BINDING_REQUIRED")
    endpoint = str(value.get("cdp_endpoint") or "http://127.0.0.1:9222").rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError("BROWSER_CDP_MUST_BE_LOOPBACK")
    value["cdp_endpoint"] = endpoint
    return value


class CDPBrowserProvider:
    def __init__(self, root, config=None, runtime=None):
        self.root = Path(root).resolve()
        self.config = dict(config) if config is not None else load_binding(self.root)
        self.endpoint = self.config["cdp_endpoint"]
        self.runtime = runtime
        self._pending_owner = None

    def allowed(self, value):
        parsed = urlsplit(str(value))
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/").lower()
        return parsed.scheme in {"http", "https"} and not parsed.username and not parsed.password and origin in {str(x).rstrip("/").lower() for x in self.config["allowed_origins"]}

    def _get(self, path):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.endpoint + path, timeout=3) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise RuntimeError("BROWSER_CDP_OBSERVATION_BUDGET")
        return json.loads(data)

    def context_ref(self):
        version = self._get("/json/version")
        websocket = str(version.get("webSocketDebuggerUrl") or "")
        if "/devtools/browser/" not in websocket:
            raise RuntimeError("BROWSER_CDP_IDENTITY_INVALID")
        identity = websocket.rsplit("/", 1)[-1]
        digest = canonical_sha256({"endpoint": self.endpoint, "browser_identity": identity, "profile": "package-default-context"})
        ref = BrowserContextRef("cdp:" + identity, "cdp-default:" + identity, digest, "AI", now_iso())
        return BrowserContextRef(ref.browser_session_id, ref.browser_context_id_or_epoch, digest, self.inspect_lease(ref), ref.observed_at)

    def _runtime(self):
        return self.runtime or create_canonical_runtime(self.root)

    def _durable_lease(self, ref):
        runtime = self._runtime()
        # All lease owner decisions originate from the canonical G4 stream.
        import sqlite3
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            missions = [row[0] for row in connection.execute("SELECT mission_id FROM mission_projection")]
        finally:
            connection.close()
        found = []
        for mission in missions:
            composed = runtime.replay_composed(mission)
            state = composed.extension_state("g4_real_execution_goal_convergence")
            if state is None:
                continue
            for fact in state.by_kind("BROWSER_LEASE"):
                if (fact.payload.get("browser_context_ref") or {}).get("context_binding_digest") == ref.context_binding_digest:
                    found.append(fact)
        if not found:
            return "AI", None
        latest = max(found, key=lambda fact: (fact.created_at, fact.created_seq))
        return str(latest.payload.get("owner") or "UNKNOWN"), latest.fact_id

    def inspect_lease(self, browser_context_ref):
        owner, fact_id = self._durable_lease(browser_context_ref)
        pending = self._pending_owner
        if pending is not None and pending[0] == browser_context_ref.context_binding_digest and pending[1] == fact_id:
            return pending[2]
        return owner

    def inspect_context(self, browser_context_ref):
        current = self.context_ref()
        if current.context_binding_digest != browser_context_ref.context_binding_digest:
            raise RuntimeError("BROWSER_CONTEXT_REPLACED")
        return current

    def transfer_lease(self, browser_context_ref, *, from_owner, to_owner):
        self.inspect_context(browser_context_ref)
        if self.inspect_lease(browser_context_ref) != from_owner or (from_owner, to_owner) not in {("AI", "HUMAN"), ("HUMAN", "AI")}:
            raise RuntimeError("BROWSER_LEASE_TRANSFER_REJECTED")
        _, fact_id = self._durable_lease(browser_context_ref)
        # This pending receipt bridges one G4 transfer call only. G4 records the
        # result durably before the method returns to its caller. After a crash,
        # pending gate/lease reconciliation rebuilds from R1.
        self._pending_owner = (browser_context_ref.context_binding_digest, fact_id, to_owner)
        return {"owner": to_owner, "context_binding_digest": browser_context_ref.context_binding_digest}

    def verify_resume_condition(self, *, mission_id, browser_context_ref, resume_condition, completion_mode):
        self.inspect_context(browser_context_ref)
        checks = self.config.get("resume_checks") or {}
        required = ("authenticated_selector", "page_selector", "business_selector")
        if not all(isinstance(checks.get(key), str) and checks[key] for key in required):
            raise RuntimeError("BROWSER_RESUME_CHECKS_BANK_BINDING_REQUIRED")
        if resume_condition and resume_condition != checks:
            raise RuntimeError("BROWSER_RESUME_CONDITION_BINDING_MISMATCH")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as driver:
            browser = driver.chromium.connect_over_cdp(self.endpoint, timeout=5000)
            pages = [page for page in (browser.contexts[0].pages if browser.contexts else []) if self.allowed(page.url)]
            passed = False
            for page in pages:
                if AUTH_PATH.search(urlsplit(page.url).path):
                    continue
                if all(page.locator(checks[key]).first.is_visible() for key in required):
                    passed = True
                    break
        self.inspect_context(browser_context_ref)
        result = {"resume_safe": passed, "auth_state": "AUTHENTICATED" if passed else "UNVERIFIED",
                  "page_identity": "MATCHED" if passed else "UNVERIFIED", "business_state": "RESUME_SAFE" if passed else "UNVERIFIED",
                  "source_ref": "browser-cdp:approved-dom-resume-checks", "observed_at": now_iso()}
        result["evidence_digest"] = canonical_sha256({"checks": checks, "result": result, "context": browser_context_ref.context_binding_digest})
        return result

    def _chromium_path(self):
        chrome = self.root / "runtime/browser/chrome-win64/chrome.exe"
        if os.name != "nt" and self.config.get("local_chromium_path"):
            chrome = Path(self.config["local_chromium_path"])
        return chrome

    def launch_browser(self, *, headless=False):
        try:
            return {"status": "READY", "browser_context_ref": self.context_ref().to_dict(), "reused": True}
        except (OSError, ValueError, RuntimeError):
            pass
        chrome = self._chromium_path()
        if not chrome.is_file():
            raise RuntimeError("BROWSER_OFFLINE_CHROMIUM_PAYLOAD_REQUIRED")
        start_url = str(self.config.get("start_url") or "")
        if not self.allowed(start_url):
            raise RuntimeError("BROWSER_START_URL_OUTSIDE_APPROVED_SCOPE")
        operational = Path(os.environ.get("PFC_LOCAL_STATE_ROOT") or self.root / "data")
        profile = operational / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)
        port = urlsplit(self.endpoint).port or 9222
        # Keep externally launched Chrome compatible with CDP attachment:
        # disable Windows relaunch and optimization downloads, and retain the
        # RenderDocument workaround used by the native construction browser.
        args = [str(chrome), "--disable-features=RenderDocument,AutoDeElevate,OptimizationHints", "--disable-extensions",
                f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "about:blank"]
        if headless:
            args.insert(1, "--headless=new")
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("BROWSER_PROCESS_EXITED")
                try:
                    ref = self.context_ref()
                except (OSError, ValueError, RuntimeError):
                    time.sleep(0.2)
                    continue
                # Windows Chromium can leave the first document uninitialized for
                # CDP if navigation precedes attachment. Bootstrap only this newly
                # launched browser on a blank page, then open the approved URL.
                # The reuse path above never changes an existing human-owned page.
                from playwright.sync_api import sync_playwright
                with sync_playwright() as driver:
                    browser = driver.chromium.connect_over_cdp(self.endpoint, timeout=15000)
                    pages = browser.contexts[0].pages if browser.contexts else []
                    blank = next((page for page in pages if page.url == "about:blank"), None)
                    if blank is None:
                        raise RuntimeError("BROWSER_FRESH_BOOTSTRAP_PAGE_REQUIRED")
                    blank.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                self.inspect_context(ref)
                return {"status": "READY", "browser_context_ref": ref.to_dict(), "reused": False, "pid": process.pid}
            raise RuntimeError("BROWSER_CDP_START_TIMEOUT")
        except BaseException:
            # This handle belongs only to the newly launched controlled profile.
            # Reused browsers return before launch and never enter this cleanup.
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            raise

    def status(self):
        try:
            return {"status": "READY", "browser_context_ref": self.context_ref().to_dict(), "mode": "HUMAN_DRIVES_AI_OBSERVES", "g6": "HOLD"}
        except Exception as exc:
            return {"status": "FAIL", "error": type(exc).__name__, "g6": "HOLD"}


ELEMENT_OBSERVER = r"""(() => {
  const binding = 'aitestTeachingElement';
  if (window.__aitestTeachingBinding === binding) return;
  if (window.__aitestTeachingHandler) for (const type of ['click','change','keydown']) document.removeEventListener(type, window.__aitestTeachingHandler, true);
  window.__aitestTeachingBinding = binding;
  window.__aitestTeachingHandler = e => {
    const n=e.target; if (!(n instanceof Element)) return;
    if (document.querySelector('input[type="password"]') || n.matches('[data-sensitive],input[type="password"]')) return;
    if (e.type==='keydown' && !['Enter','Tab','Escape','ArrowDown','ArrowUp'].includes(e.key)) return;
    const tag=n.tagName.toLowerCase(); const label=(n.getAttribute('aria-label')||(n.labels && n.labels[0] && n.labels[0].innerText)||'').slice(0,120);
    const role=n.getAttribute('role')||({button:'button',a:'link',select:'combobox',textarea:'textbox'})[tag]||(tag==='input'?'textbox':'');
    const name=(label||(['button','a'].includes(tag)?n.textContent:'')||'').trim().slice(0,120);
    const candidates=[];
    if(n.getAttribute('data-testid')) candidates.push({testid:n.getAttribute('data-testid')});
    if(role && name) candidates.push({role,name});
    if(label) candidates.push({label});
    if(n.id) candidates.push({css:'#'+CSS.escape(n.id)});
    let action=e.type==='click'?'click':e.type==='keydown'?'keyboard':tag==='select'?'select':n.type==='checkbox'?(n.checked?'check':'uncheck'):'fill';
    // Values/OTP/passwords are never recorded; replay needs explicit test data.
    const placeholder=['fill','select'].includes(action)?'field_'+(n.getAttribute('data-testid')||n.id||n.name||'unbound'):null;
    window.aitestTeachingElement({event:e.type,action,tag,role,label,target:name,
      locator_candidates:candidates,semantic_page:document.title.slice(0,120),
      frame_name:window.frameElement ? window.frameElement.name||null:null,
      test_data_placeholder:placeholder,keyboard:e.type==='keydown'?e.key:null}).catch(()=>{});
  };
  for (const type of ['click','change','keydown']) document.addEventListener(type,window.__aitestTeachingHandler,{capture:true,passive:true});
})()"""

class TeachingObserver:
    def __init__(self, provider, mission_id, *, max_events=60):
        self.provider = provider
        self.mission_id = mission_id
        self.runtime = provider._runtime()
        if self.runtime.replay_composed(mission_id).core_state.mission is None:
            raise RuntimeError("TEACHING_CANONICAL_MISSION_REQUIRED")
        self.g3 = G3TestingIntelligenceService(self.runtime)
        g4 = self.runtime.replay_composed(mission_id).extension_state("g4_real_execution_goal_convergence")
        self.execution_lineage = {}
        if g4 is not None and hasattr(g4, "by_kind"):
            takeover = next((f for f in reversed(g4.by_kind("HUMAN_TAKEOVER_REQUEST")) if f.payload.get("status") == "HUMAN_CONTROLLED"), None)
            if takeover:
                self.execution_lineage = {key: takeover.payload.get(key) for key in
                    ("human_gate_id", "attempt_id", "root_attempt_id", "task_id", "step_id", "browser_context_ref")}

        self.max_events = min(max(1, max_events), 100)
        self.events = []
        self.errors = []
        self.omitted_events = 0
        self.event_bytes = 0
        self.attached = set()
        self.auth_pages = set()
        self.responses = []
        self.response_deadlines = {}
        self.finished_requests = set()
        self.capture_id = uuid.uuid4().hex
        self.binding_name = "aitestTeachingElement_" + self.capture_id
        self.batch = 0
        self.pending_recovery_targets = set()
        self.evidence_root = Path(os.environ.get("PFC_LOCAL_STATE_ROOT") or provider.root / "data") / "evidence/teaching"
        self.evidence_root.mkdir(parents=True, exist_ok=True)

    def _add(self, value):
        value = scrub(value)
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 8192:
            if "response_body" in value:
                value["response_body"] = {"capture_status": "BODY_EXCEEDS_EVENT_BUDGET"}
            else:
                value = {"kind": value.get("kind", "OBSERVATION"), "capture_status": "EVENT_EXCEEDS_BUDGET", "sha256": hashlib.sha256(encoded).hexdigest()}
            encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(self.events) >= self.max_events or self.event_bytes + len(encoded) > 32768:
            self.omitted_events += 1
            return
        self.events.append(value)
        self.event_bytes += len(encoded)

    def _auth_page(self, page):
        return bool(AUTH_PATH.search(urlsplit(page.url).path)) or page.locator('input[type="password"]').count() > 0

    def _element(self, source, element):
        try:
            page = source["page"]
            if self.execution_lineage:
                ref = BrowserContextRef.from_dict(self.execution_lineage["browser_context_ref"])
                if self.provider.inspect_lease(ref) != "HUMAN":
                    return
            # Exposed-binding callbacks cannot call synchronous Playwright APIs:
            # doing so deadlocks the click awaiting this callback's return.
            if self.provider.allowed(page.url) and page not in self.auth_pages and not AUTH_PATH.search(urlsplit(page.url).path):
                self._add({"kind": "ELEMENT", "url": safe_url(page.url), "element": element})
        except Exception as exc:
            self.errors.append(type(exc).__name__)

    def _response(self, response):
        # Transport callbacks enqueue handles only. Body/DOM inspection happens
        # on the main observer tick, after requestfinished, outside callbacks.
        if self.provider.allowed(response.url) and len(self.responses) < self.max_events:
            self.responses.append(response)
            self.response_deadlines[response] = time.monotonic() + 10

    def _finished(self, request):
        if any(response.request == request for response in self.responses):
            self.finished_requests.add(request)

    def _capture_response(self, response):
        try:
            if not self.provider.allowed(response.url):
                return
            value = {"kind": "NETWORK_RESPONSE", "url": safe_url(response.url), "method": response.request.method,
                     "resource_type": response.request.resource_type, "status": response.status}
            body_paths = self.provider.config.get("response_body_paths") or []
            if urlsplit(response.url).path in body_paths and not AUTH_PATH.search(urlsplit(response.url).path):
                # Body capture is opt-in per approved path; never store headers,
                # request POST data, auth endpoints, or raw response bodies.
                length = response.header_value("content-length")
                encoding = response.header_value("content-encoding")
                if length and int(length) <= 65536 and encoding in (None, "identity") and "json" in str(response.header_value("content-type") or ""):
                    raw = response.body()
                    if len(raw) <= 65536:
                        value["response_body"] = scrub(json.loads(raw))
                        value["response_body_sha256"] = hashlib.sha256(raw).hexdigest()
                else:
                    value["response_body_status"] = "OMITTED_UNBOUNDED_OR_NON_JSON"
            else:
                value["response_body_status"] = "PATH_NOT_APPROVED_OR_AUTH_PAGE"
            self._add(value)
        except Exception as exc:
            self.errors.append(type(exc).__name__)

    def _attach(self, page):
        if page in self.attached:
            return
        self.attached.add(page)
        page.on("response", self._response)
        page.on("requestfinished", self._finished)
        page.on("crash", lambda _: self._add({"kind": "PAGE_CRASH", "recovery": "RELOAD_OR_NEW_PAGE_ON_NEXT_TICK"}))
        page.expose_binding(self.binding_name, self._element)
        script = ELEMENT_OBSERVER.replace("aitestTeachingElement", self.binding_name)
        page.add_init_script(script)
        try:
            page.evaluate(script)
        except Exception:
            pass

    def snapshot(self, page):
        if not self.provider.allowed(page.url):
            return
        self._attach(page)
        if self._auth_page(page):
            self.auth_pages.add(page)
            self._add({"kind": "PAGE", "url": safe_url(page.url), "capture_status": "AUTH_SCREEN_CONTENT_SUPPRESSED"})
            return
        self.auth_pages.discard(page)
        tags = page.locator("button,a,input,select,textarea,[role]").evaluate_all("nodes=>nodes.slice(0,100).map(n=>({tag:n.tagName.toLowerCase(),role:n.getAttribute('role')||''}))")
        self._add({"kind": "PAGE", "url": safe_url(page.url), "elements": tags, "input_values_collected": False})
        image_path = self.evidence_root / f"{self.capture_id}-{self.batch}-{len(self.events)}.png"
        masks = [page.locator("input,textarea,select,iframe,[contenteditable],[data-sensitive]")]
        masks.extend(page.locator(selector) for selector in self.provider.config.get("mask_selectors") or [])
        page.screenshot(path=str(image_path), full_page=False, mask=masks, timeout=10000)
        self._add({"kind": "SCREENSHOT", "artifact_ref": str(image_path), "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "masked": True})

    def flush(self):
        pending = []
        for response in self.responses:
            if response.request in self.finished_requests:
                self._capture_response(response)
                self.finished_requests.discard(response.request)
                self.response_deadlines.pop(response, None)
            elif time.monotonic() > self.response_deadlines.get(response, 0):
                self._add({"kind": "NETWORK_RESPONSE", "url": safe_url(response.url), "status": response.status,
                           "response_body_status": "OMITTED_RESPONSE_NOT_FINISHED_WITHIN_BUDGET"})
                self.response_deadlines.pop(response, None)
            else:
                pending.append(response)
        self.responses = pending
        if not self.events and not self.errors:
            return None
        payload = {"asset_id": f"teaching:{self.capture_id}:{self.batch}", "mode": "HUMAN_DRIVES_AI_OBSERVES",
                   "execution_lineage": self.execution_lineage, "observations": self.events, "isolated_errors": self.errors[:10], "observed_at": now_iso(),
                   "omitted_events": self.omitted_events, "batch_observation_max_bytes": 32768,
                   "g6": "HOLD", "learning_authority": "HUMAN_REVIEW_REQUIRED", "automatic_promotion": False,
                   "approval_ref": self.provider.config["approval_ref"], "recording_scope": list(self.provider.config["allowed_origins"])}
        result = self.g3._record(self.mission_id, "TEACHING_ASSET", payload,
                                 provenance_refs=(self.provider.config["approval_ref"], "runtime:cdp-human-observer"))
        if self.execution_lineage and any(item.get("kind") == "ELEMENT" for item in self.events):
            from .recovery_teaching import generate_candidate
            try:
                generate_candidate(self.runtime, self.mission_id, result["fact_id"])
            except Exception:
                # The trace stays durable; incomplete/ambiguous locators remain
                # review candidates and never disable the HumanGate observer.
                pass
        self.events = []
        self.errors = []
        self.omitted_events = 0
        self.event_bytes = 0
        self.batch += 1
        return result

    def _recover_crashed_targets(self):
        # A crashed renderer can prevent Playwright from attaching any page.
        # The browser's HTTP endpoint still identifies explicit crash targets.
        # Replace only those targets, preserving the browser profile/context.
        target = self.provider.config.get("start_url")
        if not target or not self.provider.allowed(target):
            return False
        recovered = False
        for page in self.provider._get("/json/list"):
            if page.get("type") != "page" or str(page.get("url", "")).rstrip('/') not in {"chrome://crash", "about:crash"}:
                continue
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            # Create the replacement before closing the last crashed tab, so
            # Chromium does not exit and discard the authenticated context.
            request = urllib.request.Request(self.provider.endpoint + "/json/new?about:blank", method="PUT")
            with opener.open(request, timeout=5) as response:
                replacement = json.loads(response.read(4096))
            self.pending_recovery_targets.add(str(replacement["id"]))
            with opener.open(self.provider.endpoint + "/json/close/" + quote(str(page["id"]), safe=''), timeout=5) as response:
                response.read(4096)
            self._add({"kind": "PAGE_RECOVERY", "status": "REPLACEMENT_AWAITING_APPROVED_NAVIGATION",
                       "url": safe_url(target), "resume_authority": "G4_FRESH_VERIFICATION_REQUIRED"})
            recovered = True
        return recovered

    def _navigate_recovery_targets(self, browser):
        if not self.pending_recovery_targets or not browser.contexts:
            return
        target = self.provider.config.get("start_url")
        if not target or not self.provider.allowed(target):
            raise RuntimeError("BROWSER_CRASH_APPROVED_RECOVERY_URL_REQUIRED")
        context = browser.contexts[0]
        for page in context.pages:
            session = context.new_cdp_session(page)
            try:
                target_id = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            finally:
                session.detach()
            if target_id not in self.pending_recovery_targets:
                continue
            self.pending_recovery_targets.discard(target_id)
            # Only the exact blank tab created by this observer is eligible.
            # A human navigation since its creation always wins.
            if page.url != "about:blank":
                continue
            page.goto(target, wait_until="domcontentloaded", timeout=10000)
            self._add({"kind": "PAGE_RECOVERY", "status": "REPLACED_CRASHED_TAB_SAME_BROWSER_CONTEXT",
                       "url": safe_url(target), "resume_authority": "G4_FRESH_VERIFICATION_REQUIRED"})

    def _recover_page(self, page):
        target = page.url if self.provider.allowed(page.url) else self.provider.config.get("start_url")
        if not target or not self.provider.allowed(target):
            raise RuntimeError("BROWSER_CRASH_APPROVED_RECOVERY_URL_REQUIRED")
        page.goto(target, wait_until="domcontentloaded", timeout=10000)
        self._add({"kind": "PAGE_RECOVERY", "status": "RELOADED", "url": safe_url(target),
                   "context_preserved": True, "resume_authority": "G4_FRESH_VERIFICATION_REQUIRED"})

    def run(self, *, duration=300, interval=5, stop=None, gate_only=False):
        from playwright.sync_api import sync_playwright
        stop = stop or threading.Event()
        asset_refs = []
        productive = False
        with sync_playwright() as driver:
            # Driver startup can be slow on an offline/loaded host. The user
            # observation window begins after driver initialization.
            deadline = time.monotonic() + min(max(duration, 0.1), 3600)
            browser = None
            while not stop.is_set() and time.monotonic() < deadline:
                if gate_only:
                    if not self.execution_lineage:
                        break
                    ref = BrowserContextRef.from_dict(self.execution_lineage["browser_context_ref"])
                    if self.provider.inspect_lease(ref) != "HUMAN":
                        break
                try:
                    if browser is None or not browser.is_connected():
                        browser = driver.chromium.connect_over_cdp(self.provider.endpoint, timeout=5000)
                        self.attached.clear()
                        self.auth_pages.clear()
                        self.responses.clear()
                        self.response_deadlines.clear()
                        self.finished_requests.clear()
                        self.binding_name = "aitestTeachingElement_" + uuid.uuid4().hex
                    self._navigate_recovery_targets(browser)
                    pages = list(browser.contexts[0].pages) if browser.contexts else []
                    if not pages:
                        break
                    for page in pages[:10]:
                        try:
                            if page.url.rstrip('/') in {"chrome://crash", "about:crash"}:
                                self._recover_page(page)
                            self.snapshot(page)
                        except Exception as exc:
                            self.errors.append(type(exc).__name__)
                            # A crashed page is isolated. Reloading retains the
                            # same authenticated BrowserContext, not a new profile.
                            try:
                                self._recover_page(page)
                                self.snapshot(page)
                            except Exception as recovery_error:
                                self.errors.append(type(recovery_error).__name__)
                    pages[0].wait_for_timeout(min(interval * 1000, max(1, (deadline - time.monotonic()) * 1000)))
                except Exception as exc:
                    self.errors.append(type(exc).__name__)
                    browser = None
                    try:
                        self._recover_crashed_targets()
                    except Exception as recovery_error:
                        self.errors.append(type(recovery_error).__name__)
                    stop.wait(min(interval, max(0, deadline - time.monotonic())))
                result = self.flush()
                if result:
                    asset_refs.append(result["fact_id"])
                    productive = productive or any(item.get("kind") in {"PAGE", "SCREENSHOT", "ELEMENT", "NETWORK_RESPONSE"} for item in result["payload"]["observations"])
        result = self.flush()
        if result:
            asset_refs.append(result["fact_id"])
            productive = productive or any(item.get("kind") in {"PAGE", "SCREENSHOT", "ELEMENT", "NETWORK_RESPONSE"} for item in result["payload"]["observations"])
        return {"status": "RECORDED" if productive else "NO_OBSERVATIONS", "truth_source": "R1_EVENT_STREAM", "asset_refs": asset_refs, "g6": "HOLD"}


def observer_lock(root):
    """Operational OS lock; crash release prevents duplicate observers."""
    path=Path(os.environ.get('PFC_LOCAL_STATE_ROOT') or Path(root)/'data')/'state/browser-observer.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b');handle.seek(0)
    if path.stat().st_size==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return handle
    except OSError:handle.close();return None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--mission-id")
    parser.add_argument("--duration", type=float, default=300)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-input", action="store_true")
    parser.add_argument("--gate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        provider = CDPBrowserProvider(args.workspace_root)
        if args.status:
            result = provider.status()
        else:
            mission_id = args.mission_id
            if not mission_id:
                missions = runtime_status(args.workspace_root).get("missions") or []
                active = [item for item in missions if item.get("status") == "ACTIVE"]
                if len(active) != 1:
                    raise RuntimeError("TEACHING_SELECT_ONE_ACTIVE_MISSION")
                mission_id = active[0]["mission_id"]
            provider.launch_browser()
            stop = threading.Event()
            if not args.no_input and sys.stdin.isatty():
                print("浏览器示教已开始。请直接操作浏览器；4A 登录内容会抑制采集。完成后按回车。", flush=True)
                def wait_for_enter():
                    try:
                        input()
                    except EOFError:
                        pass
                    stop.set()
                threading.Thread(target=wait_for_enter, daemon=True).start()
            lock=observer_lock(args.workspace_root)
            if lock is None:
                print('当前受控浏览器已有观察进程，完成操作后回到对话请求继续。')
                return 0
            try:result = TeachingObserver(provider, mission_id).run(duration=args.duration, stop=stop, gate_only=args.gate_only, interval=1 if args.gate_only else 5)
            finally:lock.close()
        if args.status or args.no_input:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print("教学结果：" + result["status"] + "；已保存 " + str(len(result.get("asset_refs", []))) + " 组记录。返回对话继续测试。")
        return 0 if result["status"] in {"READY", "RECORDED"} else 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc), "g6": "HOLD"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
