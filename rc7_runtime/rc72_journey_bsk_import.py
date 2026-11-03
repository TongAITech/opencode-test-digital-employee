"""BSK-native Journey teaching importer: actual BrowserSkill debug export -> C09 R1.

This is the PRIMARY C09 recording path. BSK records human/agent actions
and network data; the signed Journey service owns Case/Attempt/BrowserLease
admission. This importer does not treat an HTTP 200, debugging window, or
human_operator_ref as Field approval. BSK evidence must be complete and bound
to real per-operation snapshots/screenshots before compiling a Candidate.

BrowserSkill protocol: Tencent/BrowserSkill debug/types.ts DebugRecording v1.
No login cookies, request/response bodies, page input values, or artificial
actual:// screenshots are copied into the canonical R1.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode
from .rc72_journey_playwright import _atomic_json, _public_url, _safe_id
from .rc72_journey_png import verify_png_file
from .rc72_journey_teaching import JourneyActionType, JourneyTeachingService

_OPERATION_KINDS = {
    "navigate": JourneyActionType.NAVIGATE,
    "click": JourneyActionType.CLICK,
    "fill": JourneyActionType.INPUT,
    "select": JourneyActionType.SELECT,
    "press": JourneyActionType.PRESS,
    "hover": JourneyActionType.HOVER,
    "scroll-to": JourneyActionType.SCROLL_TO,
    "drag": JourneyActionType.DRAG,
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _real_file(ref: Any, *, suffix: Optional[str] = None,
               capture_root: Optional[Path] = None) -> Path:
    if not isinstance(ref, str) or not ref.startswith("file://"):
        raise ContractError("JOURNEY_BSK_LOCAL_EVIDENCE_REF_REQUIRED")
    parsed = urlsplit(ref)
    if parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
        raise ContractError("JOURNEY_BSK_LOCAL_EVIDENCE_REF_INVALID")
    target = Path(url2pathname(parsed.path)).resolve()
    if capture_root is not None:
        try:
            inside = os.path.commonpath(
                [str(target), str(capture_root.resolve())]) == str(capture_root.resolve())
        except ValueError:
            inside = False
        if not inside:
            raise ContractError("JOURNEY_BSK_EVIDENCE_OUTSIDE_AUTHORIZED_CAPTURE_ROOT")
    if not target.is_file() or target.stat().st_size == 0:
        raise ContractError("JOURNEY_BSK_REAL_EVIDENCE_FILE_REQUIRED")
    if suffix is not None and target.suffix.lower() != suffix:
        raise ContractError("JOURNEY_BSK_EVIDENCE_EXTENSION_INVALID")
    return target


def _check_recording(doc: Mapping[str, Any], session_id: str) -> Dict[str, Any]:
    if not isinstance(doc, Mapping) or doc.get("version") != 1:
        raise ContractError("JOURNEY_BSK_EXPORT_VERSION_UNSUPPORTED")
    run = doc.get("run")
    if not isinstance(run, Mapping) or run.get("session_id") != session_id:
        raise ContractError("JOURNEY_BSK_SESSION_SCOPE_MISMATCH")
    if run.get("state") != "stopped" or not run.get("stopped_at"):
        raise ContractError("JOURNEY_BSK_CAPTURE_NOT_STOPPED")
    if run.get("storage_error") or any(run.get(k, 0) for k in (
            "dropped_requests", "dropped_operations", "dropped_console")):
        raise ContractError("JOURNEY_BSK_CAPTURE_INCOMPLETE")
    if run.get("coverage") and any(
            str(reason) not in {"complete"} for reason in run["coverage"]):
        raise ContractError("JOURNEY_BSK_CAPTURE_COVERAGE_GAP")
    ops = doc.get("operations")
    requests = doc.get("requests")
    if not isinstance(ops, list) or not ops or not isinstance(requests, list):
        raise ContractError("JOURNEY_BSK_EXPORT_OPERATIONS_REQUIRED")
    if len({op.get("id") for op in ops if isinstance(op, Mapping)}) != len(ops):
        raise ContractError("JOURNEY_BSK_OPERATION_IDS_DUPLICATE")
    if len({r.get("id") for r in requests if isinstance(r, Mapping)}) != len(requests):
        raise ContractError("JOURNEY_BSK_REQUEST_IDS_DUPLICATE")
    return dict(run)


class BSKJourneyTeachingImporter:
    """Accepts native BSK debug v1 exports, never synthetic browser evidence.

    evidence_map keys are actual BSK operation ids. Each entry requires
    BSK-observed DOM/HTML snapshot and PNG screenshot file refs. Since
    @eN refs expire on navigation, stable locator_ref must be reviewed,
    not blindly taken from a transient operation target.

    Source recording stays nonexecutable, and official promotion requires
    separate Field benchmark and verified human approval.
    """

    def __init__(self, *, teaching: JourneyTeachingService,
                 evidence_root: Path,
                 authorized_capture_root: Path) -> None:
        if not isinstance(teaching, JourneyTeachingService):
            raise ContractError("JOURNEY_BSK_TEACHING_SERVICE_REQUIRED")
        self.teaching = teaching
        self.root = Path(evidence_root).resolve()
        self.capture_root = Path(authorized_capture_root).resolve()
        if not self.capture_root.is_dir():
            raise ContractError("JOURNEY_BSK_AUTHORIZED_CAPTURE_ROOT_REQUIRED")

    def import_export(self, *, export_file: Path, bsk_session_id: str,
                      recording_args: Mapping[str, Any],
                      bsk_session_receipt: Mapping[str, Any],
                      evidence_map: Mapping[str, Mapping[str, Any]],
                      assertions: Sequence[Mapping[str, Any]] = ()):
        if not isinstance(bsk_session_id, str) or not bsk_session_id.strip():
            raise ContractError("JOURNEY_BSK_SESSION_REQUIRED")
        if not isinstance(recording_args, Mapping) or not isinstance(evidence_map, Mapping):
            raise ContractError("JOURNEY_BSK_IMPORT_BINDINGS_REQUIRED")
        export_path = Path(export_file)
        if not export_path.is_file() or not export_path.stat().st_size:
            raise ContractError("JOURNEY_BSK_EXPORT_FILE_REQUIRED")
        # The exported recording may retain sensitive HTTP bodies. Read only
        # transiently, never embed it wholesale in canonical R1 or Evidence.
        try:
            doc = json.loads(export_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ContractError("JOURNEY_BSK_EXPORT_JSON_INVALID") from exc
        run = _check_recording(doc, bsk_session_id)
        if not isinstance(bsk_session_receipt, Mapping):
            raise ContractError("JOURNEY_BSK_TEACHING_SESSION_RECEIPT_REQUIRED")
        if (bsk_session_receipt.get("bsk_session_id") != bsk_session_id
                or bsk_session_receipt.get("tab_id") != run.get("tab_id")
                or bsk_session_receipt.get("state") != "ACTIVE"
                or not bsk_session_receipt.get("source_receipt_ref")):
            raise ContractError("JOURNEY_BSK_TEACHING_SESSION_PROVENANCE_INVALID")
        lease = self.teaching.browser_pool.assert_usable(
            browser_lease_id=recording_args.get("browser_lease_id"),
            mission_id=recording_args.get("mission_id"),
            workitem_id=recording_args.get("workitem_id"),
            attempt_id=recording_args.get("attempt_id"),
            worker_id=recording_args.get("worker_id"),
            access_mode=BrowserAccessMode.WRITE)
        if str(lease.get("purpose") or "").upper() != "JOURNEY_TEACHING":
            raise ContractError("JOURNEY_BSK_TEACHING_LEASE_PURPOSE_INVALID")
        instances = self.teaching.truth.query(
            "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])
        if len(instances) != 1 or instances[0].get("state") != "READY":
            raise ContractError("JOURNEY_BSK_TEACHING_INSTANCE_INVALID")
        instance = instances[0]
        required = {
            "browser_instance_id": instance["browser_instance_id"],
            "profile_dir": instance["profile_dir"],
            "bsk_endpoint": instance["bsk_endpoint"],
            "auth_asset_ref": instance.get("auth_asset_ref"),
            "browser_lease_id": recording_args["browser_lease_id"],
            "mission_id": recording_args["mission_id"],
            "workitem_id": recording_args["workitem_id"],
            "attempt_id": recording_args["attempt_id"],
            "worker_id": recording_args["worker_id"],
            "dsh_session_id": recording_args["session_id"],
        }
        if (any(bsk_session_receipt.get(key) != val for key, val in required.items())
                or recording_args.get("auth_asset_ref") != instance.get("auth_asset_ref")):
            raise ContractError("JOURNEY_BSK_TEACHING_SESSION_SCOPE_MISMATCH")
        if not isinstance(run.get("id"), str) or not run["id"]:
            raise ContractError("JOURNEY_BSK_RUN_ID_REQUIRED")
        if not isinstance(recording_args.get("recording_id"), str):
            raise ContractError("JOURNEY_BSK_RECORDING_ID_REQUIRED")
        recording_id = _safe_id(recording_args["recording_id"])
        ops = sorted(doc["operations"], key=lambda row: int(row.get("sequence") or 0))
        if [op.get("sequence") for op in ops] != list(range(1, len(ops) + 1)):
            raise ContractError("JOURNEY_BSK_OPERATION_SEQUENCE_INVALID")
        reqs = {row["id"]: row for row in doc["requests"]
                if isinstance(row, Mapping) and isinstance(row.get("id"), str)}
        prepared: List[Dict[str, Any]] = []
        used_dom = set()
        used_png = set()
        if set(evidence_map) != {op["id"] for op in ops}:
            raise ContractError("JOURNEY_BSK_EVIDENCE_OPERATION_SET_MISMATCH")
        for op in ops:
            if (not isinstance(op, Mapping) or
                    op.get("run_id") != run.get("id") or
                    op.get("state") != "completed" or
                    op.get("truncated") is True):
                raise ContractError("JOURNEY_BSK_OPERATION_INCOMPLETE")
            method = str(op.get("method") or "").lower()
            if method.startswith("tool."):
                method = method[5:]
            kind = _OPERATION_KINDS.get(method)
            if kind is None:
                raise ContractError("JOURNEY_BSK_OPERATION_UNSUPPORTED:" + method)
            step_info = evidence_map.get(op.get("id"))
            if not isinstance(step_info, Mapping):
                raise ContractError("JOURNEY_BSK_OPERATION_EVIDENCE_BINDING_REQUIRED")
            dom_ref, screenshot_ref = step_info.get("dom_ref"), step_info.get("screenshot_ref")
            dom_file = _real_file(dom_ref, suffix=".json",
                                  capture_root=self.capture_root)
            try:
                observation = json.loads(dom_file.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ContractError("JOURNEY_BSK_OBSERVATION_JSON_INVALID") from exc
            if (not isinstance(observation, Mapping)
                    or observation.get("session_id") != bsk_session_id
                    or observation.get("tab_id") != bsk_session_receipt["tab_id"]
                    or not isinstance(observation.get("context_id"), str)
                    or not observation["context_id"]):
                raise ContractError("JOURNEY_BSK_OBSERVATION_SCOPE_INVALID")
            shot = _real_file(screenshot_ref, suffix=".png",
                              capture_root=self.capture_root)
            if dom_ref in used_dom or screenshot_ref in used_png:
                raise ContractError("JOURNEY_BSK_OPERATION_EVIDENCE_REUSED")
            used_dom.add(dom_ref)
            used_png.add(screenshot_ref)
            screenshot_proof = verify_png_file(shot)
            page = op.get("after") or op.get("before")
            if not isinstance(page, Mapping) or page.get("state") != "available":
                raise ContractError("JOURNEY_BSK_PAGE_OBSERVATION_REQUIRED")
            page_url = _public_url(page.get("url"))
            if not page_url.startswith(("http://", "https://")):
                raise ContractError("JOURNEY_BSK_PAGE_URL_REQUIRED")
            ref = step_info.get("locator_ref")
            if kind not in {JourneyActionType.NAVIGATE} and (
                    not isinstance(ref, str) or
                    not ref.startswith(("css:", "testid:"))):
                raise ContractError("JOURNEY_BSK_STABLE_LOCATOR_BINDING_REQUIRED")
            bound = {}
            if kind == JourneyActionType.PRESS:
                key = step_info.get("key")
                if key not in {
                    "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown",
                    "ArrowLeft", "ArrowRight", "Space", "Backspace",
                    "Delete", "Home", "End", "PageUp", "PageDown",
                }:
                    raise ContractError("JOURNEY_BSK_PRESS_KEY_REQUIRED")
                bound["key"] = key
            if kind == JourneyActionType.DRAG:
                target_ref = step_info.get("target_ref")
                if not isinstance(target_ref, str) or not target_ref.startswith(
                        ("css:", "testid:")):
                    raise ContractError("JOURNEY_BSK_DRAG_TARGET_REQUIRED")
                bound["target_ref"] = target_ref
            if kind in {JourneyActionType.INPUT, JourneyActionType.SELECT}:
                refkey = step_info.get("value_ref") or step_info.get("credential_ref")
                if not isinstance(refkey, str) or not refkey.strip():
                    raise ContractError("JOURNEY_BSK_VALUE_REFERENCE_REQUIRED")
                if step_info.get("value_ref"):
                    bound["value_ref"] = refkey
            network = []
            if not isinstance(op.get("request_ids"), list):
                raise ContractError("JOURNEY_BSK_REQUEST_IDS_REQUIRED")
            for request_id in op["request_ids"]:
                request = reqs.get(request_id)
                if not isinstance(request, Mapping) or request.get("run_id") != run["id"]:
                    raise ContractError("JOURNEY_BSK_REQUEST_PROVENANCE_INVALID")
                if (request.get("state") not in {"complete", "failed", "redirected"}
                        or request.get("intervention") is not None
                        or request.get("replay_id") is not None):
                    raise ContractError("JOURNEY_BSK_REQUEST_UNKNOWN_OR_MODIFIED")
                network.append({
                    "bsk_request_id": request_id,
                    "method": request.get("method"),
                    "url": _public_url(request.get("url")),
                    "status": request.get("status"),
                    # BSK's time-window link is correlation, not causation.
                    "association": "BSK_OPERATION_WINDOW_NOT_CAUSAL_PROOF",
                })
            prepared.append({
                "kind": kind, "op": op, "page_url": page_url,
                "page_role": str(step_info.get("page_role") or "BSK_PAGE"),
                "element_ref": ref if kind != JourneyActionType.NAVIGATE else None,
                "dom_ref": dom_ref, "screenshot_ref": screenshot_ref,
                "network": network, "metadata": bound,
                "screenshot_sha256": screenshot_proof["sha256"],
                "credential_ref": step_info.get("credential_ref"),
                "wait_semantics": str(step_info.get("wait_semantics") or "domcontentloaded"),
            })
        # Business oracles are human-defined refs, NOT HTTP 200 guesses.
        # The caller may deliberately leave no assertions, but promotion will
        # reject such a candidate; do not invent a business-success oracle.
        for a in assertions:
            if not isinstance(a, Mapping) or not isinstance(a.get("oracle_ref"), str) or not a["oracle_ref"]:
                raise ContractError("JOURNEY_BSK_ASSERTION_ORACLE_REF_REQUIRED")
            if not isinstance(a.get("source_operation_id"), str) or a["source_operation_id"] not in {
                    op["id"] for op in ops}:
                raise ContractError("JOURNEY_BSK_ASSERTION_OPERATION_REQUIRED")

        # Admission and browser ownership are checked by the canonical
        # JourneyTeachingService; no source mutation happens before preflight.
        args = dict(recording_args)
        self.teaching.start_recording(**args)
        summary = {
            "schema": "rc72-bsk-debug-export-lineage-v1",
            "bsk_run_id": str(run["id"]),
            "bsk_session_id": bsk_session_id,
            "source_export_sha256": hashlib.sha256(export_path.read_bytes()).hexdigest(),
            "operation_count": len(ops),
            "source": "BROWSERSKILL_DEBUG_EXPORT",
            "field_verified": False,
        }
        folder = self.root / recording_id
        summary_ref = _atomic_json(folder / "bsk-source.json", summary)
        # An Oracle belongs immediately after its source business action,
        # never at the tail of a multi-page recording. Otherwise the later
        # page could make an earlier checkpoint appear to pass or fail.
        assertions_after: Dict[str, List[Mapping[str, Any]]] = {}
        for assertion in assertions:
            assertions_after.setdefault(assertion["source_operation_id"], []).append(assertion)
        sequence = 0
        for step in prepared:
            sequence += 1
            page_ref = _atomic_json(
                folder / ("step-%04d-page.json" % sequence),
                {"source": "BROWSER_SKILL_DEBUG",
                 "operation_id": step["op"]["id"], "url": step["page_url"],
                 "page_role": step["page_role"],
                 "value_source": "REDACTED_BSK_PAGE_OBSERVATION",
                 "screenshot_sha256": step["screenshot_sha256"]})
            network_ref = _atomic_json(
                folder / ("step-%04d-network.json" % sequence),
                {"responses": step["network"],
                 "association": "BSK_OPERATION_WINDOW_NOT_CAUSAL_PROOF"})
            evidence = [summary_ref, page_ref, step["dom_ref"],
                        network_ref, step["screenshot_ref"]]
            self.teaching.append_step(
                recording_id=recording_id, step_id="%s:%d" % (recording_id, sequence),
                sequence=sequence, action_type=step["kind"],
                url=step["page_url"], page_role=step["page_role"],
                element_ref=step["element_ref"],
                page_state_ref=page_ref, dom_ref=step["dom_ref"],
                network_refs=[network_ref], screenshot_ref=step["screenshot_ref"],
                wait_semantics=step["wait_semantics"],
                evidence_refs=evidence, capture_metadata=step["metadata"],
                credential_ref=step["credential_ref"])
            for assertion in assertions_after.get(step["op"]["id"], ()):
                sequence += 1
                assertion_page = _atomic_json(
                    folder / ("assert-%04d-page.json" % sequence),
                    {"source": "BROWSER_SKILL_VERIFIED_OPERATOR_ORACLE",
                     "source_operation_id": step["op"]["id"],
                     "url": step["page_url"]})
                self.teaching.append_step(
                    recording_id=recording_id,
                    step_id="%s:%d" % (recording_id, sequence),
                    sequence=sequence, action_type=JourneyActionType.ASSERT,
                    url=step["page_url"], page_role=step["page_role"],
                    element_ref=assertion.get("locator_ref"),
                    page_state_ref=assertion_page, dom_ref=step["dom_ref"],
                    network_refs=[], screenshot_ref=step["screenshot_ref"],
                    wait_semantics="visible" if assertion.get("locator_ref") else "none",
                    evidence_refs=[assertion_page, step["screenshot_ref"]],
                    capture_metadata={"oracle_ref": assertion["oracle_ref"]})
        return self.teaching.complete_recording(
            recording_id=recording_id, evidence_refs=[summary_ref])
