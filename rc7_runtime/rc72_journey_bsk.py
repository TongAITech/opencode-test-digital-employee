"""Primary BSK Journey replay/official adapter.

Uses B-group authorized BrowserSkill session via its CLI/DSH-compatible
protocol; never starts/borrows user tabs, connects to raw CDP, retries a
mutating action, or silently falls back to Playwright. Every action is fenced
by the same BrowserLease contract as other RC7.2 workers.

Official Field identity/signatures are supplied by A/B services; this
adapter cannot self-declare FIELD_VERIFIED. BrowserSkill step's "ok"/"phase"
and evaluate's in-band "ok" must be checked, not merely shell exit status.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode, BrowserPool
from .rc72_journey_playwright import _atomic_json, _public_url, _safe_id
from .rc72_journey_png import verify_png_file

class JourneyBSKAdapter:
    adapter_kind = "BROWSERSKILL_NATIVE"
    field_verified = False

    def __init__(
        self,
        *,
        browser_pool: BrowserPool,
        evidence_root: Path,
        bsk_executable: Path,
        session_resolver: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
        reference_resolver: Callable[[str, str, Mapping[str, Any]], Any],
        runner: Optional[Callable[[Any], Mapping[str, Any]]] = None,
        timeout_seconds: int = 45,
    ) -> None:
        if not isinstance(browser_pool, BrowserPool):
            raise ContractError("JOURNEY_BSK_BROWSER_POOL_REQUIRED")
        if not callable(session_resolver) or not callable(reference_resolver):
            raise ContractError("JOURNEY_BSK_SESSION_AND_REFERENCE_RESOLVERS_REQUIRED")
        binary = Path(bsk_executable).resolve()
        if runner is None and not binary.is_file():
            raise ContractError("JOURNEY_BSK_OFFLINE_EXECUTABLE_MISSING")
        if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 120:
            raise ContractError("JOURNEY_BSK_TIMEOUT_INVALID")
        self.pool = browser_pool
        self.root = Path(evidence_root).resolve()
        self.binary = binary
        self.session_for = session_resolver
        self.resolve = reference_resolver
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self._run_id = None
        self._attempt = None
        self._session = None
        self._tab_id = None
        self._fingerprint = None
        self._seen_steps = set()

    def close(self) -> None:
        # B group owns the actual BSK session; this method only invalidates
        # the adapter's ownership cache, never kills a shared daemon.
        self._run_id = self._attempt = self._session = self._tab_id = self._fingerprint = None

    def _guard(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        for field in ("mission_id", "workitem_id", "attempt_id", "worker_id", "session_id", "browser_lease_id"):
            if not isinstance(context.get(field), str) or not context[field]:
                raise ContractError("JOURNEY_BSK_ATTEMPT_SCOPE_REQUIRED")
        expected = ("OFFICIAL_JOURNEY_EXECUTION" if context.get("execution_id")
                    else "JOURNEY_REPLAY" if context.get("replay_id") else None)
        if not expected:
            raise ContractError("JOURNEY_BSK_EXECUTION_ID_REQUIRED")
        lease = self.pool.assert_usable(
            browser_lease_id=context["browser_lease_id"],
            mission_id=context["mission_id"], workitem_id=context["workitem_id"],
            attempt_id=context["attempt_id"], worker_id=context["worker_id"],
            access_mode=BrowserAccessMode.WRITE)
        if str(lease.get("purpose") or "").upper() != expected:
            raise ContractError("JOURNEY_BSK_BROWSER_PURPOSE_MISMATCH")
        rows = self.pool.truth.query(
            "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])
        if len(rows) != 1 or rows[0].get("state") != "READY":
            raise ContractError("JOURNEY_BSK_BROWSER_INSTANCE_NOT_READY")
        instance = rows[0]
        fingerprint = tuple(str(instance.get(x) or "") for x in (
            "browser_instance_id", "profile_dir", "cdp_endpoint",
            "bsk_endpoint", "auth_asset_ref"))
        if self._fingerprint is not None and fingerprint != self._fingerprint:
            raise ContractError("JOURNEY_BSK_BROWSER_INSTANCE_SWITCH_FORBIDDEN")
        # The session resolver MUST return an authoritative B-group ownership
        # receipt, not a caller-supplied arbitrary session id. Validate all
        # lease/Attempt/4A/profile dimensions against the live BrowserPool.
        ownership = self.session_for(context, instance)
        if not isinstance(ownership, Mapping):
            raise ContractError("JOURNEY_BSK_SESSION_OWNERSHIP_RECEIPT_REQUIRED")
        session = ownership.get("bsk_session_id")
        tab_id = ownership.get("tab_id")
        if type(tab_id) is not int or tab_id <= 0:
            raise ContractError("JOURNEY_BSK_OWNED_TAB_REQUIRED")
        if self._tab_id is not None and self._tab_id != tab_id:
            raise ContractError("JOURNEY_BSK_TAB_SWITCH_FORBIDDEN")
        if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session):
            raise ContractError("JOURNEY_BSK_OWNED_SESSION_REQUIRED")
        required = {
            "browser_instance_id": instance["browser_instance_id"],
            "profile_dir": instance["profile_dir"],
            "bsk_endpoint": instance["bsk_endpoint"],
            "auth_asset_ref": instance.get("auth_asset_ref"),
            "browser_lease_id": context["browser_lease_id"],
            "mission_id": context["mission_id"],
            "workitem_id": context["workitem_id"],
            "attempt_id": context["attempt_id"],
            "worker_id": context["worker_id"],
            "dsh_session_id": context.get("session_id"),
        }
        if any(ownership.get(key) != value for key, value in required.items()):
            raise ContractError("JOURNEY_BSK_SESSION_RECEIPT_SCOPE_MISMATCH")
        if ownership.get("state") != "ACTIVE" or not ownership.get("source_receipt_ref"):
            raise ContractError("JOURNEY_BSK_SESSION_NOT_AUTHORIZED")
        if self._session is not None and self._session != session:
            raise ContractError("JOURNEY_BSK_SESSION_SWITCH_FORBIDDEN")
        return {"instance": instance, "fingerprint": fingerprint,
                "session": session, "tab_id": tab_id}

    def _run(self, args):
        command = [str(self.binary)] + list(args)
        if self.runner is not None:
            response = self.runner(command)
            if not isinstance(response, Mapping):
                raise ContractError("JOURNEY_BSK_CLI_RESULT_INVALID")
            # Injected test runner uses a normalized subprocess-style envelope
            # and cannot bypass the real production response parser.
            code = response.get("returncode")
            raw = response.get("stdout")
        else:
            env = dict(os.environ)
            env["BSK_AUTO_START"] = "0"
            try:
                proc = subprocess.run(command, check=False, shell=False,
                                      capture_output=True, text=True,
                                      timeout=self.timeout_seconds, env=env)
            except subprocess.TimeoutExpired as exc:
                raise ContractError("JOURNEY_BSK_EFFECT_UNKNOWN_TIMEOUT") from exc
            except OSError as exc:
                raise ContractError("JOURNEY_BSK_CLI_UNAVAILABLE") from exc
            code, raw = proc.returncode, proc.stdout
        if code != 0:
            raise ContractError("JOURNEY_BSK_CLI_FAILURE_EFFECT_UNKNOWN")
        try:
            reply = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ContractError("JOURNEY_BSK_CLI_JSON_INVALID") from exc
        if not isinstance(reply, Mapping):
            raise ContractError("JOURNEY_BSK_CLI_RESULT_INVALID")
        return reply

    def _sync(self, session: str, tab_id: int) -> None:
        # BrowserSkill target/strict control requires a fresh cooperative
        # sync and a positive usable action context. Human hold/borrowed
        # ownership must not be bypassed by issuing the browser command.
        reply = self._run([
            "cooperate", "sync", "--session", session,
            "--tab-id", str(tab_id), "--policy", "strict", "--json"])
        if not isinstance(reply.get("context_id"), str) or not reply["context_id"]:
            raise ContractError("JOURNEY_BSK_CONTROL_SYNC_NOT_GRANTED")
        actual_tab = reply.get("tab_id")
        if actual_tab is not None and actual_tab != tab_id:
            raise ContractError("JOURNEY_BSK_CONTROL_TAB_MISMATCH")

    def _selector(self, raw_ref: str, context: Mapping[str, Any]) -> str:
        descriptor = self.resolve(raw_ref, "locator", context)
        if descriptor is None:
            if raw_ref.startswith("css:"):
                return raw_ref[4:]
            if raw_ref.startswith("testid:"):
                value = raw_ref[7:]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                    raise ContractError("JOURNEY_BSK_TESTID_UNSAFE")
                return '[data-testid="' + value + '"]'
            raise ContractError("JOURNEY_BSK_STABLE_SELECTOR_REQUIRED")
        if isinstance(descriptor, str):
            return descriptor
        if (isinstance(descriptor, Mapping) and set(descriptor) == {"css"}
                and isinstance(descriptor["css"], str)):
            return descriptor["css"]
        raise ContractError("JOURNEY_BSK_SELECTOR_DESCRIPTOR_UNSUPPORTED")

    def _page_read(self, session: str, selector: Optional[str] = None,
                   attribute: Optional[str] = None):
        # Only fixed, read-only page evaluation. Arbitrary supplied JS is
        # rejected; all dynamic values are JSON literals, not executable code.
        exp = """(() => {
          const selector = %s, attribute = %s;
          const matches = selector ? document.querySelectorAll(selector) : [];
          const el = matches.length === 1 ? matches[0] : null;
          const visible = !!el && !!(el.offsetWidth || el.offsetHeight ||
             el.getClientRects().length);
          return {url: location.origin + location.pathname,
                  match_count: matches.length,
                  exists: !!el, visible: visible,
                  text: el ? el.innerText : null,
                  attribute: el && attribute ? el.getAttribute(attribute) : null};
        })()""" % (json.dumps(selector), json.dumps(attribute))
        reply = self._run([
            "evaluate", exp, "--session", session,
            "--tab-id", str(self._tab_id), "--json"])
        # IMPORTANT: BrowserSkill returns exit 0 for in-band evaluate ok=false.
        if reply.get("ok") is not True or not isinstance(reply.get("value"), Mapping):
            raise ContractError("JOURNEY_BSK_EVALUATE_UNVERIFIED")
        return reply["value"]

    def _assert(self, step: Mapping[str, Any], context: Mapping[str, Any], session: str) -> None:
        oracle_ref = step.get("oracle_ref")
        if not isinstance(oracle_ref, str) or not oracle_ref:
            raise ContractError("JOURNEY_BSK_BUSINESS_ORACLE_REQUIRED")
        oracle = self.resolve(oracle_ref, "oracle", context)
        if not isinstance(oracle, Mapping):
            raise ContractError("JOURNEY_BSK_ORACLE_UNRESOLVED")
        kind = oracle.get("type")
        if kind == "network_status":
            # Debug request/operation timing is correlation, not causation.
            # Do not fabricate a network PASS from any unrelated HTTP 200.
            raise ContractError("JOURNEY_BSK_NETWORK_ORACLE_REQUIRES_INDEPENDENT_PROOF")
        selector = None
        if kind in {"visible", "text_equals", "attribute_equals"}:
            selector = self._selector(
                str(oracle.get("element_ref") or step.get("element_ref") or ""),
                context)
        elif kind != "url_equals":
            raise ContractError("JOURNEY_BSK_ORACLE_TYPE_UNSUPPORTED")
        values = self._page_read(
            session, selector,
            str(oracle.get("attribute") or "") if kind == "attribute_equals" else None)
        if context.get("execution_id") and kind in {"url_equals", "visible"}:
            raise ContractError("JOURNEY_BSK_OFFICIAL_BUSINESS_ORACLE_TOO_WEAK")
        if selector is not None and values.get("match_count") != 1:
            raise ContractError("JOURNEY_BSK_ORACLE_ELEMENT_NOT_UNIQUE")
        if kind == "url_equals":
            passed = values.get("url") == _public_url(oracle.get("expected"))
        elif kind == "visible":
            passed = values.get("exists") is True and values.get("visible") is True
        elif kind == "text_equals":
            passed = values.get("exists") is True and values.get("text") == oracle.get("expected")
        else:
            passed = values.get("exists") is True and values.get("attribute") == oracle.get("expected")
        if not passed:
            raise ContractError("JOURNEY_BSK_BUSINESS_ORACLE_FAILED")

    def _action(self, step: Mapping[str, Any], context: Mapping[str, Any], session: str):
        kind = str(step.get("action_type") or "").upper()
        if kind == "ASSERT":
            self._assert(step, context, session)
            return {"action": "ASSERT", "verified": True}
        if kind == "WAIT":
            if str(step.get("wait_semantics") or "") != "visible":
                raise ContractError("JOURNEY_BSK_WAIT_UNSUPPORTED")
            selector = self._selector(str(step.get("element_ref") or ""), context)
            reply = self._run(["wait-for-element", selector, "--state", "visible",
                               "--timeout", "15s", "--session", session,
                               "--tab-id", str(self._tab_id), "--json"])
            if reply.get("satisfied") is not True:
                raise ContractError("JOURNEY_BSK_WAIT_CONDITION_NOT_MET")
            return {"action": kind, "verified": True}
        args = {}
        action = {
            "NAVIGATE": "navigate", "CLICK": "click",
            "INPUT": "fill", "SELECT": "select",
            "PRESS": "press", "HOVER": "hover",
            "SCROLL_TO": "scroll-to", "DRAG": "drag",
        }.get(kind)
        if not action:
            raise ContractError("JOURNEY_BSK_ACTION_UNSUPPORTED")
        if action == "navigate":
            url = step.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                raise ContractError("JOURNEY_BSK_NAVIGATION_URL_REQUIRED")
            args["url"] = url
        elif action == "drag":
            source = self._selector(str(step.get("element_ref") or ""), context)
            target = self._selector(str(step.get("target_ref") or ""), context)
            args["source"] = {"selector": source}
            args["target"] = {"selector": target}
        else:
            args["selector"] = self._selector(str(step.get("element_ref") or ""), context)
            if action == "press":
                key = step.get("key")
                if key not in {
                    "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown",
                    "ArrowLeft", "ArrowRight", "Space", "Backspace",
                    "Delete", "Home", "End", "PageUp", "PageDown",
                }:
                    raise ContractError("JOURNEY_BSK_PRESS_KEY_UNSAFE")
                args["key"] = key
            if action in {"fill", "select"}:
                # CLI argv is visible in process diagnostics. Never place 4A
                # passwords/OTP or other CredentialRefs on a shell command
                # line; B/DSH's native bsk_* tool handles credential input.
                if step.get("credential_ref") and not step.get("value_ref"):
                    raise ContractError("JOURNEY_BSK_CREDENTIAL_NATIVE_TOOL_REQUIRED")
                value_ref = step.get("value_ref")
                if not isinstance(value_ref, str) or not value_ref:
                    raise ContractError("JOURNEY_BSK_VALUE_REFERENCE_REQUIRED")
                value = self.resolve(
                    value_ref, "value" if step.get("value_ref") else "credential", context)
                if not isinstance(value, str):
                    raise ContractError("JOURNEY_BSK_VALUE_UNRESOLVED")
                if action == "fill":
                    args["value"] = value
                else:
                    args["values"] = [value]
        result = self._run([
            "step", "--session", session, "--tab-id", str(self._tab_id),
            "--policy", "strict", "--action", action,
            "--params", json.dumps(args), "--json"])
        if (result.get("ok") is not True or result.get("phase") != "observed"
                or result.get("action_replayed") is not False
                or not isinstance(result.get("post"), Mapping)
                or not isinstance(result["post"].get("context_id"), str)):
            raise ContractError("JOURNEY_BSK_ACTION_UNKNOWN_OR_UNOBSERVED")
        return {"action": kind, "verified": True}

    def execute_step(self, step: Mapping[str, Any],
                     context: Mapping[str, Any]) -> Dict[str, Any]:
        run_id = _safe_id(str(context.get("replay_id") or context.get("execution_id") or ""))
        seq = step.get("sequence")
        if type(seq) is not int or seq < 1:
            raise ContractError("JOURNEY_BSK_STEP_SEQUENCE_INVALID")
        folder = self.root / run_id / ("step-%04d" % seq)
        screenshot = folder / "screen.png"
        actual_path = folder / "actual.json"
        key = (run_id, seq)
        if key in self._seen_steps or actual_path.exists() or screenshot.exists():
            # Unknown side effects or existing Actual are never retried in a
            # fresh invocation. Do not overwrite the original PASS/FAIL files.
            rejected = _atomic_json(folder / "repeat-rejected.json", {
                "status": "FAILED",
                "failure_code": "JOURNEY_BSK_DUPLICATE_STEP_EFFECT_UNKNOWN",
                "source_step_id": step.get("source_step_id"),
                "replay_id": run_id, "sequence": seq, "field_verified": False})
            return {
                "status": "FAILED", "failure_code": "JOURNEY_BSK_DUPLICATE_STEP_EFFECT_UNKNOWN",
                "actual_refs": [rejected], "evidence_refs": [rejected]}
        self._seen_steps.add(key)
        status, failure = "PASSED", None
        session = None
        step_result: Dict[str, Any] = {}
        started_at = int(time.time())
        evidence_refs = []
        png_proof = None
        try:
            binding = self._guard(context)
            if self._run_id is not None and (
                    self._run_id != run_id or self._attempt != context["attempt_id"]):
                raise ContractError("JOURNEY_BSK_ATTEMPT_SWITCH_REQUIRES_CLOSE")
            self._run_id, self._attempt = run_id, context["attempt_id"]
            self._fingerprint = binding["fingerprint"]
            self._session = binding["session"]
            self._tab_id = binding["tab_id"]
            session = binding["session"]
            self._sync(session, binding["tab_id"])
            self._guard(context)
            step_result = self._action(step, context, session)
            # BSK's session may be stopped/borrow ownership revoked during the
            # action; never issue screenshot or PASS without a fresh lease guard.
            self._guard(context)
            folder.mkdir(parents=True, exist_ok=True)
            picture = self._run([
                "screenshot", "--session", session,
                "--tab-id", str(binding["tab_id"]),
                "--out", str(screenshot), "--json"])
            png_proof = verify_png_file(screenshot)
            if (picture.get("byte_size") != png_proof["bytes"]
                    or picture.get("tab_id") != binding["tab_id"]
                    or picture.get("format") != "png"):
                raise ContractError("JOURNEY_BSK_SCREENSHOT_INVALID")
            self._guard(context)
            evidence_refs.append(screenshot.resolve().as_uri())
        except Exception as exc:
            status = "FAILED"
            failure = (str(exc).split(":")[0][:100] if isinstance(exc, ContractError)
                       else "JOURNEY_BSK_UNEXPECTED_FAILURE")
        receipt = _atomic_json(actual_path, {
            "status": status, "failure_code": failure,
            "source": "BROWSERSKILL_CLI",
            "field_verified": (
                getattr(self, "_approved_run", None) ==
                (run_id, context.get("attempt_id"), context.get("browser_lease_id"))
                and int(time.time()) < getattr(self, "_proof_expires_at", 0)),
            "bsk_session_fingerprint": (
                hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
                if session is not None else None),
            "action_type": str(step.get("action_type") or ""),
            "source_step_id": step.get("source_step_id"),
            "started_at": started_at, "completed_at": int(time.time()),
            "result_category": step_result.get("action"),
            "screenshot_sha256": png_proof["sha256"] if png_proof else None,
            "screenshot_dimensions": (
                [png_proof["width"], png_proof["height"]]
                if png_proof else None),
        })
        evidence_refs.append(receipt)
        return {"status": status, "actual_refs": [receipt],
                "evidence_refs": evidence_refs, "failure_code": failure}
