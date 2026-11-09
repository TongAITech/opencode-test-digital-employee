"""Playwright/CDP worker adapter for RC7.2 Journey replay and official L4/L5.

Connects only to a B-group registered BrowserInstance, never launches a shared
browser. All actions are gated by the live BrowserLease, and the adapter emits
real on-disk Actual/Evidence even on exception. CI is engineering evidence only;
the adapter intentionally cannot self-assert bank FIELD_VERIFIED.

Playwright is loaded lazily: offline Windows/Linux distributions must ship the
matching Playwright package and compatible Chromium themselves.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode, BrowserPool


def _safe_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", value):
        raise ContractError("JOURNEY_EVIDENCE_IDENTIFIER_INVALID")
    return value


def _public_url(raw: Any) -> str:
    """Do not put token-bearing URL queries/fragments in evidence."""
    parts = urlsplit(str(raw or ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temp), str(path))
    return path.resolve().as_uri()


class JourneyPlaywrightAdapter:
    """Concrete synchronous adapter accepted by both Journey execution services.

    reference_resolver(ref, kind, context) returns a scalar for value refs,
    a locator mapping or CSS selector for element refs, and a *structured*
    oracle mapping for oracle refs. There is no guessing of dom:// references.
    The caller must supply a distinct B-group WRITE lease for every attempt.
    """

    adapter_kind = "PLAYWRIGHT_CDP_LOCAL"
    field_verified = False

    def __init__(
        self,
        *,
        browser_pool: BrowserPool,
        evidence_root: Path,
        reference_resolver: Callable[[str, str, Mapping[str, Any]], Any],
        connector: Optional[Callable[[str], Any]] = None,
        timeout_ms: int = 15000,
    ) -> None:
        if not isinstance(browser_pool, BrowserPool):
            raise ContractError("JOURNEY_BROWSER_POOL_REQUIRED")
        if not callable(reference_resolver):
            raise ContractError("JOURNEY_REFERENCE_RESOLVER_REQUIRED")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1000 <= timeout_ms <= 60000:
            raise ContractError("JOURNEY_ACTION_TIMEOUT_INVALID")
        self.pool = browser_pool
        self.root = Path(evidence_root).resolve()
        self.resolve = reference_resolver
        self.connector = connector
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._endpoint = None
        self._active_run_id = None
        self._active_attempt_id = None
        self._instance_fingerprint = None
        self._network_observations = {}
        self._network_request_origins = {}
        self._network_response_origins = {}
        self._network_page = None
        self._network_handlers = None
        self._active_source = None
        self._network_overflow = set()
        self._oracle_proofs = {}

    def close(self) -> None:
        # Stop the client connection; BrowserPool/B group owns browser lifetime.
        if self._network_page is not None and self._network_handlers is not None:
            for event, handler in self._network_handlers:
                try:
                    self._network_page.remove_listener(event, handler)
                except Exception:
                    pass
        self._network_page = None
        self._network_handlers = None
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._endpoint = None
        self._active_run_id = None
        self._active_attempt_id = None
        self._instance_fingerprint = None
        self._network_observations.clear()
        self._network_request_origins.clear()
        self._network_response_origins.clear()
        self._network_overflow.clear()
        self._oracle_proofs.clear()
        self._active_source = None

    def _guard(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        required = ("mission_id", "workitem_id", "attempt_id", "worker_id", "browser_lease_id")
        if any(not isinstance(context.get(key), str) or not context[key].strip() for key in required):
            raise ContractError("JOURNEY_BROWSER_CALL_SCOPE_REQUIRED")
        lease = self.pool.assert_usable(
            browser_lease_id=context["browser_lease_id"],
            mission_id=context["mission_id"],
            workitem_id=context["workitem_id"],
            attempt_id=context["attempt_id"],
            worker_id=context["worker_id"],
            access_mode=BrowserAccessMode.WRITE,
        )
        required_purpose = (
            "OFFICIAL_JOURNEY_EXECUTION" if context.get("execution_id")
            else "JOURNEY_REPLAY" if context.get("replay_id")
            else None)
        if not required_purpose or str(lease.get("purpose") or "").upper() != required_purpose:
            raise ContractError("JOURNEY_BROWSER_PURPOSE_MISMATCH")
        instances = self.pool.truth.query(
            "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])
        if len(instances) != 1 or instances[0].get("state") != "READY":
            raise ContractError("JOURNEY_BROWSER_INSTANCE_UNAVAILABLE")
        endpoint = str(instances[0]["cdp_endpoint"])
        if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:", "ws://127.0.0.1:", "ws://localhost:")):
            raise ContractError("JOURNEY_CDP_LOCAL_ENDPOINT_REQUIRED")
        instance = instances[0]
        fingerprint = tuple(str(instance.get(k) or "") for k in (
            "browser_instance_id", "profile_dir", "cdp_endpoint",
            "bsk_endpoint", "auth_asset_ref"))
        if self._instance_fingerprint is not None and fingerprint != self._instance_fingerprint:
            raise ContractError("JOURNEY_BROWSER_INSTANCE_IDENTITY_CHANGED")
        return {"lease": lease, "instance": instance, "endpoint": endpoint, "fingerprint": fingerprint}

    def _attach(self, endpoint: str) -> Any:
        if self._browser is not None:
            if endpoint != self._endpoint:
                raise ContractError("JOURNEY_CDP_INSTANCE_SWITCH_FORBIDDEN")
            return self._browser
        if self.connector is not None:
            browser = self.connector(endpoint)
        else:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise ContractError("JOURNEY_PLAYWRIGHT_OFFLINE_PACKAGE_MISSING") from exc
            self._playwright = sync_playwright().start()
            try:
                browser = self._playwright.chromium.connect_over_cdp(endpoint, timeout=self.timeout_ms)
            except Exception:
                self.close()
                raise
        self._browser = browser
        self._endpoint = endpoint
        return browser

    def _page(self, endpoint: str) -> Any:
        browser = self._attach(endpoint)
        contexts = list(browser.contexts)
        if len(contexts) != 1:
            raise ContractError("JOURNEY_CDP_CONTEXT_AMBIGUOUS")
        pages = list(contexts[0].pages)
        if len(pages) != 1:
            raise ContractError("JOURNEY_CDP_PAGE_AMBIGUOUS")
        return pages[0]

    def _track_network(self, page: Any, run_id: str) -> None:
        # SPA XHR/fetch responses can complete between Journey steps. A
        # request must be attributed when it begins, not at response time;
        # a later unrelated 200 must never satisfy the click Oracle.
        if self._network_page is not None:
            if self._network_page is not page:
                raise ContractError("JOURNEY_CDP_TRACKED_PAGE_SWITCH_FORBIDDEN")
            return

        def on_request(request: Any) -> None:
            if self._active_source is not None:
                self._network_request_origins[id(request)] = dict(self._active_source)

        def on_response(response: Any) -> None:
            try:
                origin = self._network_request_origins.pop(id(response.request), None)
                if not origin:
                    return
                self._network_response_origins[id(response)] = dict(origin)
                row = {
                    "method": str(response.request.method),
                    "url": _public_url(response.url),
                    "status": int(response.status),
                    "source_step_id": origin["source_step_id"],
                    "action_type": origin["action_type"],
                }
                records = self._network_observations.setdefault(run_id, [])
                if len(records) >= 1000:
                    self._network_overflow.add(run_id)
                else:
                    records.append(row)
            except Exception:
                # Unknown request lineage is not proof of business success.
                pass

        page.on("request", on_request)
        page.on("response", on_response)
        self._network_page = page
        self._network_handlers = [("request", on_request), ("response", on_response)]

    def _resolve_locator(self, page: Any, ref: str, context: Mapping[str, Any]) -> Any:
        if not ref:
            raise ContractError("JOURNEY_ELEMENT_REF_REQUIRED")
        descriptor = self.resolve(ref, "locator", context)
        if descriptor is None:
            if ref.startswith("css:"):
                descriptor = {"css": ref[4:]}
            elif ref.startswith("testid:"):
                descriptor = {"testid": ref[7:]}
            else:
                raise ContractError("JOURNEY_LOCATOR_UNRESOLVED")
        if isinstance(descriptor, str):
            descriptor = {"css": descriptor}
        if not isinstance(descriptor, Mapping) or len(descriptor) != 1:
            raise ContractError("JOURNEY_LOCATOR_DESCRIPTOR_INVALID")
        kind, value = next(iter(descriptor.items()))
        if not isinstance(value, str) or not value.strip():
            raise ContractError("JOURNEY_LOCATOR_DESCRIPTOR_INVALID")
        if kind == "css":
            return page.locator(value)
        if kind == "testid":
            return page.get_by_test_id(value)
        if kind == "text":
            return page.get_by_text(value, exact=True)
        raise ContractError("JOURNEY_LOCATOR_KIND_UNSUPPORTED")

    def _wait(self, page: Any, step: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        wait = str(step.get("wait_semantics") or "").lower()
        if wait in {"network-idle", "networkidle"}:
            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        elif wait in {"domcontentloaded", "load"}:
            page.wait_for_load_state(wait, timeout=self.timeout_ms)
        elif wait == "visible":
            if not step.get("element_ref"):
                raise ContractError("JOURNEY_VISIBLE_WAIT_ELEMENT_REQUIRED")
            self._resolve_locator(page, str(step["element_ref"]), context).wait_for(
                state="visible", timeout=self.timeout_ms)
        elif wait not in {"", "none", "visible", "explicit"}:
            raise ContractError("JOURNEY_WAIT_SEMANTICS_UNSUPPORTED")

    def _assert(self, page: Any, step: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        ref = str(step.get("oracle_ref") or "")
        oracle = self.resolve(ref, "oracle", context)
        if not isinstance(oracle, Mapping):
            raise ContractError("JOURNEY_ORACLE_UNRESOLVED")
        kind = oracle.get("type")
        if kind == "network_status":
            method = oracle.get("method")
            url = oracle.get("url")
            status = oracle.get("status")
            trigger_step_id = oracle.get("trigger_source_step_id")
            if (not isinstance(method, str) or not method.strip()
                    or not isinstance(url, str) or not url.startswith(("http://", "https://"))
                    or not isinstance(status, int) or isinstance(status, bool)
                    or not isinstance(trigger_step_id, str) or not trigger_step_id.strip()
                    or trigger_step_id == step.get("source_step_id")):
                raise ContractError("JOURNEY_NETWORK_ORACLE_TRIGGER_STEP_REQUIRED")
            run_id = str(context.get("replay_id") or context.get("execution_id") or "")
            observations = self._network_observations.get(run_id, [])
            matching = next((
                row for row in observations
                if row.get("method") == method.upper()
                and row.get("url") == _public_url(url)
                and row.get("status") == status
                and row.get("source_step_id") == trigger_step_id
                and row.get("action_type") in {"NAVIGATE", "CLICK", "INPUT", "SELECT", "WAIT"}
            ), None)
            if matching is None:
                raise ContractError("JOURNEY_ASSERT_NETWORK_STATUS_MISMATCH")
            self._oracle_proofs[
                (run_id, str(step.get("source_step_id") or ""))] = dict(matching)
        elif kind == "url_equals":
            if page.url != oracle.get("expected"):
                raise ContractError("JOURNEY_ASSERT_URL_MISMATCH")
        elif kind in {"visible", "text_equals", "attribute_equals"}:
            target = str(oracle.get("element_ref") or step.get("element_ref") or "")
            locator = self._resolve_locator(page, target, context)
            if kind == "visible":
                if not locator.is_visible():
                    raise ContractError("JOURNEY_ASSERT_NOT_VISIBLE")
            elif kind == "text_equals":
                expected = oracle.get("expected")
                if not isinstance(expected, str):
                    raise ContractError("JOURNEY_ASSERT_TEXT_MISMATCH")
                # HTTP response completion / networkidle does not imply that a
                # SPA has committed its asynchronous DOM state. Use Playwright's
                # retrying assertion with an exact, anchored text Oracle.
                waiter = getattr(locator, "wait_for_text", None)
                if callable(waiter):
                    try:
                        waiter(expected, timeout_ms=self.timeout_ms)
                    except Exception as exc:
                        raise ContractError("JOURNEY_ASSERT_TEXT_MISMATCH") from exc
                else:
                    try:
                        from playwright.sync_api import expect
                        expect(locator).to_have_text(
                            re.compile(r"^" + re.escape(expected) + r"$"),
                            timeout=self.timeout_ms, use_inner_text=True)
                    except ImportError as exc:
                        raise ContractError(
                            "JOURNEY_PLAYWRIGHT_TEXT_ASSERTION_RUNTIME_MISSING") from exc
                    except Exception as exc:
                        raise ContractError("JOURNEY_ASSERT_TEXT_MISMATCH") from exc
            elif kind == "attribute_equals":
                attribute = str(oracle.get("attribute") or "")
                if not attribute or locator.get_attribute(attribute, timeout=self.timeout_ms) != oracle.get("expected"):
                    raise ContractError("JOURNEY_ASSERT_ATTRIBUTE_MISMATCH")
        else:
            raise ContractError("JOURNEY_ORACLE_TYPE_UNSUPPORTED")

    def _action(self, page: Any, step: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        action = str(step.get("action_type") or "").upper()
        if action == "NAVIGATE":
            url = str(step.get("url") or "")
            if not url.startswith(("https://", "http://")):
                raise ContractError("JOURNEY_NAVIGATION_URL_INVALID")
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        elif action in {"CLICK", "INPUT", "SELECT"}:
            locator = self._resolve_locator(page, str(step.get("element_ref") or ""), context)
            if action == "CLICK":
                locator.click(timeout=self.timeout_ms)
            else:
                ref = str(step.get("value_ref") or step.get("credential_ref") or "")
                if not ref:
                    raise ContractError("JOURNEY_VALUE_REF_REQUIRED")
                value = self.resolve(ref, "credential" if step.get("credential_ref") and not step.get("value_ref") else "value", context)
                if not isinstance(value, str):
                    raise ContractError("JOURNEY_VALUE_UNRESOLVED")
                if action == "INPUT":
                    locator.fill(value, timeout=self.timeout_ms)
                else:
                    locator.select_option(value, timeout=self.timeout_ms)
        elif action == "WAIT":
            if str(step.get("wait_semantics") or "").lower() in {"", "none", "explicit"}:
                raise ContractError("JOURNEY_WAIT_REQUIRED")
        elif action == "ASSERT":
            self._assert(page, step, context)
        else:
            raise ContractError("JOURNEY_ACTION_UNSUPPORTED")
        self._guard(context)
        self._wait(page, step, context)

    def execute_step(self, step: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        # Do not use event-only success receipts. Persist actual files on every path.
        run_id = _safe_id(str(context.get("replay_id") or context.get("execution_id") or ""))
        sequence = step.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ContractError("JOURNEY_STEP_SEQUENCE_INVALID")
        dirname = self.root / run_id / ("step-%04d" % sequence)
        actual_path = dirname / "actual.json"
        screenshot_path = dirname / "screen.png"
        page = None
        status = "PASSED"
        failure_code = None
        responses = []
        started_at = int(time.time())
        try:
            binding = self._guard(context)
            # A worker may not reuse a CDP connection (or cached network
            # observations) as a fresh benchmark / N7 Attempt. Explicit
            # close() and a new adapter are required to cross ownership.
            if self._active_run_id is not None and (
                    self._active_run_id != run_id
                    or self._active_attempt_id != context["attempt_id"]):
                raise ContractError("JOURNEY_ADAPTER_ATTEMPT_SWITCH_REQUIRES_CLOSE")
            self._active_run_id = run_id
            self._active_attempt_id = context["attempt_id"]
            self._instance_fingerprint = binding["fingerprint"]
            page = self._page(binding["endpoint"])
            self._track_network(page, run_id)
            self._active_source = {
                "source_step_id": str(step.get("source_step_id") or ""),
                "action_type": str(step.get("action_type") or "").upper(),
            }
            def on_response(response: Any) -> None:
                try:
                    origin = self._network_response_origins.get(id(response))
                    record = {
                        "method": str(response.request.method),
                        "url": _public_url(response.url),
                        "status": int(response.status),
                    }
                    if origin:
                        record["origin_source_step_id"] = origin["source_step_id"]
                    responses.append(record)
                except Exception:
                    pass
            page.on("response", on_response)
            dialogs = []
            dialog_policy_ref = step.get("dialog_policy_ref")
            def on_dialog(dialog: Any) -> None:
                # Default: dismiss unexpected prompts and FAIL. Never silently
                # accept a SUT confirmation just because the browser can.
                observed = {"type": str(dialog.type), "authorized": False}
                dialogs.append(observed)
                policy = (self.resolve(dialog_policy_ref, "dialog", context)
                          if isinstance(dialog_policy_ref, str) and dialog_policy_ref else None)
                if (isinstance(policy, Mapping)
                        and policy.get("type") == observed["type"]
                        and policy.get("action") in {"accept", "dismiss"}):
                    observed["authorized"] = True
                    if policy["action"] == "accept":
                        prompt_ref = policy.get("prompt_value_ref")
                        if prompt_ref:
                            prompt_value = self.resolve(prompt_ref, "value", context)
                            if not isinstance(prompt_value, str):
                                raise ContractError("JOURNEY_DIALOG_PROMPT_VALUE_UNRESOLVED")
                            dialog.accept(prompt_text=prompt_value)
                        else:
                            dialog.accept()
                    else:
                        dialog.dismiss()
                else:
                    dialog.dismiss()
            page.on("dialog", on_dialog)
            try:
                self._action(page, step, context)
                if any(not d["authorized"] for d in dialogs):
                    raise ContractError("JOURNEY_UNEXPECTED_DIALOG")
                if dialog_policy_ref and not dialogs:
                    raise ContractError("JOURNEY_EXPECTED_DIALOG_MISSING")
                # Revoked/expired ownership after a long action cannot yield PASS.
                self._guard(context)
            finally:
                page.remove_listener("response", on_response)
                page.remove_listener("dialog", on_dialog)
        except Exception as exc:
            status = "FAILED"
            failure_code = "JOURNEY_STEP_%s" % type(exc).__name__.upper()
            if isinstance(exc, ContractError):
                failure_code = str(exc).split(":")[0][:100]
        # Preserve observed responses across NAVIGATE/CLICK -> ASSERT steps of
        # the same signed replay or official execution, not across Attempts.
        # Source-step attribution prevents an earlier coincidental HTTP
        # response from satisfying a later business action's network oracle.
        attributed = [
            dict(row, source_step_id=row.get("origin_source_step_id")
                 or str(step.get("source_step_id") or ""),
                 action_type=str(step.get("action_type") or "").upper())
            for row in responses]
        previous = self._network_observations.setdefault(run_id, [])
        # The persistent request listener may have already recorded a real
        # response under its source action. Keep only unmatched legacy
        # per-step records (e.g. older FakePage fixtures).
        fresh = [
            row for row in attributed
            if not any(
                old.get("method") == row["method"]
                and old.get("url") == row["url"]
                and old.get("status") == row["status"]
                and old.get("source_step_id") == row["source_step_id"]
                for old in previous)
        ]
        if run_id in self._network_overflow or len(previous) + len(fresh) > 1000:
            status = "FAILED"
            failure_code = "JOURNEY_NETWORK_OBSERVATION_LIMIT_EXCEEDED"
        else:
            previous.extend(fresh)
        evidence_refs = []
        if page is not None:
            try:
                # Do not screenshot an instance after ownership expires.
                self._guard(context)
                masks = page.locator('input[type="password"],input[autocomplete="one-time-code"]')
                dirname.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_path), full_page=True, mask=[masks], timeout=self.timeout_ms)
                if not screenshot_path.is_file() or screenshot_path.stat().st_size == 0:
                    raise ContractError("JOURNEY_SCREENSHOT_EVIDENCE_MISSING")
                evidence_refs.append(screenshot_path.resolve().as_uri())
            except Exception as exc:
                if status == "PASSED":
                    status, failure_code = "FAILED", "JOURNEY_SCREENSHOT_EVIDENCE_FAILED"
                if isinstance(exc, ContractError) and "BROWSER_LEASE" in str(exc):
                    failure_code = str(exc).split(":")[0][:100]
        state = {"url": _public_url(getattr(page, "url", "") if page is not None else ""),
                 "started_at": started_at, "completed_at": int(time.time()),
                 "action_type": str(step.get("action_type") or ""),
                 "source_step_id": str(step.get("source_step_id") or ""),
                 "status": status, "failure_code": failure_code,
                 "response_metadata": responses,
                 "network_oracle_proof": self._oracle_proofs.get((
                     run_id, str(step.get("source_step_id") or ""))),
                 "browser_instance_id": (self.pool.lease(context["browser_lease_id"]).get("browser_instance_id")
                                         if isinstance(context.get("browser_lease_id"), str)
                                         and self.pool.truth.query("rc72_browser_lease", browser_lease_id=context["browser_lease_id"])
                                         else None)}
        actual_ref = _atomic_json(actual_path, state)
        # A durable failure JSON is genuine evidence even without a screenshot.
        evidence_refs.append(actual_ref)
        return {"status": status, "actual_refs": [actual_ref],
                "evidence_refs": evidence_refs, "failure_code": failure_code}
