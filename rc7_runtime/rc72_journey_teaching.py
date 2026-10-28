"""RC7.2 canonical Journey Teaching capture truth.

This is deliberately only the human-teaching capture boundary. A CAPTURED
recording is a CANDIDATE_SOURCE, never an executable/official Journey. Compiler,
replay, benchmark and human-review promotion are later Phase-9 slices.

Browser ownership is reused from Phase 7: start/append operations require the
same Mission/WorkItem/Attempt/Worker to hold an ACTIVE WRITE BrowserLease.
Real BSK/CDP event collection remains a Field adapter concern; this module
persists only structured references to captured DOM/network/page/screenshot
artifacts and rejects plaintext secret-bearing metadata.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode, BrowserPool
from .truth_overlay import install_rc7_truth_overlay

_RECORDING = "rc72_journey_recording"
_CAPTURE_STEP = "rc72_journey_capture_step"
_EVENT_TYPES = {
    "RC72_JOURNEY_RECORDING_UPSERTED": (_RECORDING, "recording_id"),
    "RC72_JOURNEY_CAPTURE_STEP_UPSERTED": (_CAPTURE_STEP, "step_id"),
}
_BUCKETS = {
    _RECORDING: "rc72_journey_recordings",
    _CAPTURE_STEP: "rc72_journey_capture_steps",
}
_SECRET_KEYS = {
    "password", "passwd", "authorization", "cookie", "set-cookie",
    "access_token", "refresh_token", "session_token", "client_secret",
    "secret", "api_key", "apikey",
}


class JourneyRecordingState(str, Enum):
    CAPTURING = "CAPTURING"
    CAPTURED = "CAPTURED"
    REJECTED = "REJECTED"


class JourneyActionType(str, Enum):
    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    INPUT = "INPUT"
    SELECT = "SELECT"
    WAIT = "WAIT"
    ASSERT = "ASSERT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class JourneyRecordingResult:
    recording_id: str
    state: JourneyRecordingState


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _optional(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())


def _string_list(out: Dict[str, Any], name: str, *, allow_empty: bool = True) -> List[str]:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    out[name] = list(value)
    return out[name]


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    out[identity] = _required(out, identity)
    out["mission_id"] = _required(out, "mission_id")
    out["release_id"] = _required(out, "release_id")
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_recording(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _RECORDING, "recording_id")
    for name in (
        "release_batch_id", "requirement_id", "sst_id", "obligation_id",
        "workitem_id", "attempt_id", "worker_id", "session_id",
        "browser_lease_id", "human_operator_ref", "state", "asset_class",
    ):
        out[name] = _required(out, name)
    _optional(out, "auth_asset_ref")
    try:
        out["state"] = JourneyRecordingState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_STATE_INVALID") from exc
    if out["asset_class"] != "CANDIDATE_SOURCE":
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_ASSET_CLASS_INVALID")
    if out.get("executable") is not False:
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_MUST_NOT_BE_EXECUTABLE")
    if "official" in out or "official_asset_id" in out or "executable_contract_ref" in out:
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_PROMOTION_FIELD_FORBIDDEN")
    if not isinstance(out.get("step_count"), int) or out["step_count"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_STEP_COUNT_INVALID")
    if not isinstance(out.get("started_at"), int) or out["started_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_STARTED_AT_INVALID")
    completed_at = out.get("completed_at")
    if completed_at is not None and (not isinstance(completed_at, int) or completed_at < 0):
        raise _contracts.DomainValidationError("JOURNEY_RECORDING_COMPLETED_AT_INVALID")
    if "evidence_refs" not in out:
        out["evidence_refs"] = []
    _string_list(out, "evidence_refs")
    if out["state"] == JourneyRecordingState.CAPTURED.value:
        if out["step_count"] < 1:
            raise _contracts.DomainValidationError("JOURNEY_RECORDING_STEPS_REQUIRED")
        if not out["evidence_refs"] or completed_at is None:
            raise _contracts.DomainValidationError("JOURNEY_RECORDING_CAPTURE_AUDIT_REQUIRED")
    return out


def _validate_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPTURE_STEP, "step_id")
    for name in ("recording_id", "action_type", "url", "page_role", "page_state_ref", "dom_ref", "wait_semantics"):
        out[name] = _required(out, name)
    _optional(out, "element_ref")
    _optional(out, "screenshot_ref")
    _optional(out, "credential_ref")
    try:
        out["action_type"] = JourneyActionType(out["action_type"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_ACTION_TYPE_INVALID") from exc
    if not isinstance(out.get("sequence"), int) or out["sequence"] < 1:
        raise _contracts.DomainValidationError("JOURNEY_STEP_SEQUENCE_INVALID")
    _string_list(out, "network_refs")
    _string_list(out, "evidence_refs", allow_empty=False)
    metadata = out.get("capture_metadata")
    if not isinstance(metadata, dict):
        raise _contracts.DomainValidationError("JOURNEY_CAPTURE_METADATA_INVALID")
    if not isinstance(out.get("captured_at"), int) or out["captured_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_STEP_CAPTURED_AT_INVALID")
    return out


def install_rc72_journey_teaching_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_RECORDING] = _validate_recording
    _contracts.VALIDATORS[_CAPTURE_STEP] = _validate_step
    for artifact_type, bucket in _BUCKETS.items():
        _truth.BUCKETS[artifact_type] = bucket
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(truth.projection, bucket):
            setattr(truth.projection, bucket, {})
        truth.projection._versions.setdefault(artifact_type, {})


def _reject_plaintext_secrets(value: Any, path: str = "capture_metadata") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in {key.replace("-", "_") for key in _SECRET_KEYS}:
                raise ContractError("JOURNEY_CAPTURE_SECRET_FIELD_FORBIDDEN:%s.%s" % (path, key))
            _reject_plaintext_secrets(item, "%s.%s" % (path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_plaintext_secrets(item, "%s[%d]" % (path, index))


class JourneyTeachingService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, browser_pool: BrowserPool) -> None:
        install_rc72_journey_teaching_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("JOURNEY_RELEASE_ID_REQUIRED")
        if not isinstance(browser_pool, BrowserPool):
            raise ContractError("JOURNEY_BROWSER_POOL_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.browser_pool = browser_pool

    def install_overlay(self) -> None:
        install_rc72_journey_teaching_overlay()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("JOURNEY_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _binding(self, recording: Mapping[str, Any]) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=str(recording["workitem_id"]))
        rows = [row for row in rows if row.get("mission_id") == recording.get("mission_id")]
        rows = [row for row in rows if row.get("attempt_id") == recording.get("attempt_id")]
        rows = [row for row in rows if row.get("worker_id") == recording.get("worker_id")]
        rows = [row for row in rows if row.get("session_id") == recording.get("session_id")]
        if len(rows) != 1:
            raise ContractError("JOURNEY_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("JOURNEY_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def _assert_browser(self, recording: Mapping[str, Any]) -> Dict[str, Any]:
        return self.browser_pool.assert_usable(
            browser_lease_id=str(recording["browser_lease_id"]),
            mission_id=str(recording["mission_id"]),
            workitem_id=str(recording["workitem_id"]),
            attempt_id=str(recording["attempt_id"]),
            worker_id=str(recording["worker_id"]),
            access_mode=BrowserAccessMode.WRITE,
        )

    def start_recording(
        self,
        *,
        recording_id: str,
        mission_id: str,
        release_batch_id: str,
        requirement_id: str,
        sst_id: str,
        obligation_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
        browser_lease_id: str,
        human_operator_ref: str,
        auth_asset_ref: Optional[str] = None,
    ) -> JourneyRecordingResult:
        if self.truth.query(_RECORDING, recording_id=recording_id):
            raise ContractError("JOURNEY_RECORDING_ALREADY_EXISTS")
        batch_rows = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        obligation_rows = self.truth.query("rc72_test_obligation", obligation_id=obligation_id)
        if len(batch_rows) != 1 or len(obligation_rows) != 1:
            raise ContractError("JOURNEY_LINEAGE_MISMATCH")
        batch, obligation = batch_rows[0], obligation_rows[0]
        lineage_ok = (
            batch.get("mission_id") == mission_id
            and requirement_id in list(batch.get("requirement_ids") or [])
            and obligation.get("mission_id") == mission_id
            and obligation.get("release_batch_id") == release_batch_id
            and obligation.get("requirement_id") == requirement_id
            and obligation.get("sst_id") == sst_id
        )
        if not lineage_ok:
            raise ContractError("JOURNEY_LINEAGE_MISMATCH")
        if str(obligation.get("test_level") or "").upper() not in {"L4", "L5"}:
            raise ContractError("JOURNEY_TEACHING_REQUIRES_L4_OR_L5")
        for value, name in (
            (recording_id, "recording_id"), (workitem_id, "workitem_id"), (attempt_id, "attempt_id"),
            (worker_id, "worker_id"), (session_id, "session_id"),
            (browser_lease_id, "browser_lease_id"), (human_operator_ref, "human_operator_ref"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        candidate = {
            "recording_id": recording_id, "mission_id": mission_id,
            "release_batch_id": release_batch_id, "requirement_id": requirement_id,
            "sst_id": sst_id, "obligation_id": obligation_id, "workitem_id": workitem_id,
            "attempt_id": attempt_id, "worker_id": worker_id, "session_id": session_id,
            "browser_lease_id": browser_lease_id, "human_operator_ref": human_operator_ref,
            "auth_asset_ref": auth_asset_ref, "state": JourneyRecordingState.CAPTURING.value,
            "asset_class": "CANDIDATE_SOURCE", "executable": False, "step_count": 0,
            "evidence_refs": [], "started_at": _now(), "completed_at": None,
        }
        self._binding(candidate)
        self._assert_browser(candidate)
        self._append("RC72_JOURNEY_RECORDING_UPSERTED", candidate)
        return JourneyRecordingResult(recording_id=recording_id, state=JourneyRecordingState.CAPTURING)

    def append_step(
        self,
        *,
        recording_id: str,
        step_id: str,
        sequence: int,
        action_type: JourneyActionType,
        url: str,
        page_role: str,
        element_ref: Optional[str],
        page_state_ref: str,
        dom_ref: str,
        network_refs: Sequence[str],
        screenshot_ref: Optional[str],
        wait_semantics: str,
        evidence_refs: Sequence[str],
        capture_metadata: Mapping[str, Any],
        credential_ref: Optional[str] = None,
    ) -> None:
        if self.truth.query(_CAPTURE_STEP, step_id=step_id):
            raise ContractError("JOURNEY_STEP_ALREADY_EXISTS")
        recording = self._one(_RECORDING, recording_id=recording_id)
        if recording.get("state") != JourneyRecordingState.CAPTURING.value:
            raise ContractError("JOURNEY_RECORDING_NOT_CAPTURING")
        self._binding(recording)
        self._assert_browser(recording)
        if not isinstance(sequence, int) or sequence != int(recording.get("step_count") or 0) + 1:
            raise ContractError("JOURNEY_STEP_SEQUENCE_INVALID")
        metadata = dict(capture_metadata or {})
        _reject_plaintext_secrets(metadata)
        mode = action_type if isinstance(action_type, JourneyActionType) else JourneyActionType(str(action_type).upper())
        self._append(
            "RC72_JOURNEY_CAPTURE_STEP_UPSERTED",
            {
                "step_id": step_id, "recording_id": recording_id,
                "mission_id": recording["mission_id"], "sequence": sequence,
                "action_type": mode.value, "url": url, "page_role": page_role,
                "element_ref": element_ref, "page_state_ref": page_state_ref, "dom_ref": dom_ref,
                "network_refs": list(network_refs), "screenshot_ref": screenshot_ref,
                "wait_semantics": wait_semantics, "evidence_refs": list(evidence_refs),
                "capture_metadata": metadata, "credential_ref": credential_ref,
                "captured_at": _now(),
            },
        )
        updated = dict(recording)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(recording.get("artifact_version", 1)) + 1
        updated["step_count"] = sequence
        self._append("RC72_JOURNEY_RECORDING_UPSERTED", updated)

    def complete_recording(self, *, recording_id: str, evidence_refs: Sequence[str]) -> JourneyRecordingResult:
        recording = self._one(_RECORDING, recording_id=recording_id)
        if recording.get("state") != JourneyRecordingState.CAPTURING.value:
            raise ContractError("JOURNEY_RECORDING_NOT_CAPTURING")
        if int(recording.get("step_count") or 0) < 1:
            raise ContractError("JOURNEY_RECORDING_STEPS_REQUIRED")
        evidence = [str(ref).strip() for ref in evidence_refs if isinstance(ref, str) and str(ref).strip()]
        if not evidence:
            raise ContractError("JOURNEY_RECORDING_EVIDENCE_REQUIRED")
        updated = dict(recording)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(recording.get("artifact_version", 1)) + 1
        updated["state"] = JourneyRecordingState.CAPTURED.value
        updated["evidence_refs"] = evidence
        updated["completed_at"] = _now()
        self._append("RC72_JOURNEY_RECORDING_UPSERTED", updated)
        return JourneyRecordingResult(recording_id=recording_id, state=JourneyRecordingState.CAPTURED)


install_rc72_journey_teaching_overlay()
