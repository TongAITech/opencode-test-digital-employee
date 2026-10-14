"""R1-native RC7 session rotation.

Session handoff never becomes a second state store. PREPARED/ACTIVATED handoff
records and the transferred Task lease are appended to the same R1 Event Stream.
The Task id and Task state remain unchanged across A -> B rotation.
"""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Any, Dict, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .models import TaskStatus
from .session_models import SessionHandoff, SessionHandoffStatus
from .truth_overlay import append_entity, install_rc7_truth_overlay


SESSION_EVENT = "RC7_SESSION_HANDOFF_UPSERTED"
SESSION_ARTIFACT = "rc7_session_handoff"


def _validate_session_handoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    for field in (
        "handoff_id",
        "mission_id",
        "release_id",
        "task_id",
        "predecessor_session_ref",
        "status",
        "task_state",
    ):
        out[field] = _contracts._require_str(out, field)
    out["artifact_version"] = _contracts._artifact_version(out)
    out["artifact_type"] = SESSION_ARTIFACT
    generation = out.get("generation")
    if not isinstance(generation, int) or generation < 1:
        raise _contracts.DomainValidationError("SESSION_HANDOFF_GENERATION_INVALID")
    for field in ("artifact_refs", "gap_refs"):
        _contracts._require_string_list(out, field)
    successor = out.get("successor_session_ref")
    if successor is not None and (not isinstance(successor, str) or not successor.strip()):
        raise _contracts.DomainValidationError("SUCCESSOR_SESSION_REF_INVALID")
    if out["status"].upper() == SessionHandoffStatus.ACTIVATED.value:
        if not isinstance(successor, str) or not successor.strip():
            raise _contracts.DomainValidationError("ACTIVATED_HANDOFF_REQUIRES_SUCCESSOR")
        if successor == out["predecessor_session_ref"]:
            raise _contracts.DomainValidationError("SUCCESSOR_SESSION_MUST_BE_FRESH")
        activated_at = out.get("activated_at")
        if not isinstance(activated_at, int) or activated_at <= 0:
            raise _contracts.DomainValidationError("ACTIVATED_HANDOFF_TIME_REQUIRED")
    return out


def install_session_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[SESSION_ARTIFACT] = _validate_session_handoff
    _truth.EVENT_TYPES[SESSION_EVENT] = (SESSION_ARTIFACT, "handoff_id")
    _truth.BUCKETS[SESSION_ARTIFACT] = "rc7_session_handoffs"
    _truth.IDENTITY_FIELDS[SESSION_ARTIFACT] = "handoff_id"


def _stable_id(*parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "HANDOFF-%s" % hashlib.sha256(raw).hexdigest()[:20]


def _payload(handoff: SessionHandoff, release_id: str, artifact_version: int) -> Dict[str, Any]:
    data = asdict(handoff)
    if isinstance(handoff.status, SessionHandoffStatus):
        data["status"] = handoff.status.value
    data["release_id"] = release_id
    data["artifact_version"] = artifact_version
    return data


class SessionContinuityManager:
    def __init__(self, truth: _truth.TruthRuntime, release_id: str) -> None:
        if not release_id:
            raise ValueError("RELEASE_ID_REQUIRED")
        install_session_overlay()
        self.truth = truth
        self.release_id = release_id

    def prepare(
        self,
        *,
        mission_id: str,
        task_id: str,
        predecessor_session_ref: str,
        artifact_refs: Tuple[str, ...] = (),
        gap_refs: Tuple[str, ...] = (),
    ) -> SessionHandoff:
        task_rows = self.truth.query("rc7_task", task_id=task_id)
        if not task_rows:
            raise RuntimeError("TASK_NOT_FOUND")
        task = task_rows[0]
        if task["mission_id"] != mission_id:
            raise RuntimeError("TASK_MISSION_MISMATCH")
        if task["state"] not in {TaskStatus.LEASED.value, TaskStatus.RUNNING.value}:
            raise RuntimeError("SESSION_ROTATION_REQUIRES_ACTIVE_TASK")
        if task.get("lease_owner") != predecessor_session_ref:
            raise RuntimeError("SESSION_ROTATION_LEASE_OWNER_MISMATCH")

        prior = self.truth.query(SESSION_ARTIFACT, mission_id=mission_id)
        generation = 1 + max((int(row.get("generation", 0)) for row in prior), default=0)
        for row in prior:
            if row["status"] == SessionHandoffStatus.PREPARED.value:
                raise RuntimeError("SUCCESSOR_ACTIVATION_REQUIRED")
        handoff = SessionHandoff(
            handoff_id=_stable_id(mission_id, task_id, str(generation), predecessor_session_ref),
            mission_id=mission_id,
            task_id=task_id,
            generation=generation,
            predecessor_session_ref=predecessor_session_ref,
            task_state=str(task["state"]),
            artifact_refs=list(artifact_refs),
            gap_refs=list(gap_refs),
        )
        receipt = self.truth.append_atomic(
            SESSION_EVENT,
            _payload(handoff, self.release_id, 1),
        )
        if receipt.status != "PERSISTENCE_VERIFIED":
            raise RuntimeError("SESSION_HANDOFF_PERSISTENCE_FAILED")
        return handoff

    def activate(self, handoff_id: str, successor_session_ref: str) -> SessionHandoff:
        rows = self.truth.query(SESSION_ARTIFACT, handoff_id=handoff_id)
        if not rows:
            raise RuntimeError("SESSION_HANDOFF_NOT_FOUND")
        row = rows[0]
        if row["status"] != SessionHandoffStatus.PREPARED.value:
            raise RuntimeError("SESSION_HANDOFF_ALREADY_ACTIVATED")
        successor = successor_session_ref.strip() if isinstance(successor_session_ref, str) else ""
        if not successor:
            raise RuntimeError("SUCCESSOR_SESSION_REF_REQUIRED")
        if successor == row["predecessor_session_ref"]:
            raise RuntimeError("SUCCESSOR_SESSION_MUST_BE_FRESH")
        for existing in self.truth.query(SESSION_ARTIFACT, mission_id=row["mission_id"]):
            if successor in {
                existing.get("predecessor_session_ref"),
                existing.get("successor_session_ref"),
            }:
                raise RuntimeError("SUCCESSOR_SESSION_MUST_BE_FRESH")

        task_rows = self.truth.query("rc7_task", task_id=row["task_id"])
        if not task_rows:
            raise RuntimeError("TASK_NOT_FOUND")
        task_row = task_rows[0]
        if task_row["state"] != row["task_state"]:
            raise RuntimeError("TASK_STATE_DRIFT_DURING_HANDOFF")
        if task_row.get("lease_owner") != row["predecessor_session_ref"]:
            raise RuntimeError("TASK_LEASE_DRIFT_DURING_HANDOFF")

        # Rehydrate canonical Task, change lease owner only, preserve Task id/state.
        from .control_plane import TaskScheduler

        scheduler = TaskScheduler(self.truth, self.release_id)
        task = scheduler.task(row["task_id"])
        task.lease_owner = successor
        append_entity(
            self.truth,
            task,
            release_id=self.release_id,
            artifact_version=int(task_row["artifact_version"]) + 1,
        )

        handoff = SessionHandoff(
            handoff_id=row["handoff_id"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            generation=int(row["generation"]),
            predecessor_session_ref=row["predecessor_session_ref"],
            successor_session_ref=successor,
            status=SessionHandoffStatus.ACTIVATED,
            task_state=row["task_state"],
            artifact_refs=list(row.get("artifact_refs", [])),
            gap_refs=list(row.get("gap_refs", [])),
            created_at=int(row.get("created_at", 0)),
            activated_at=int(time.time()),
        )
        receipt = self.truth.append_atomic(
            SESSION_EVENT,
            _payload(handoff, self.release_id, int(row["artifact_version"]) + 1),
        )
        if receipt.status != "PERSISTENCE_VERIFIED":
            raise RuntimeError("SESSION_HANDOFF_ACTIVATION_PERSISTENCE_FAILED")
        return handoff

    def resume_envelope(self, handoff_id: str) -> Dict[str, Any]:
        rows = self.truth.query(SESSION_ARTIFACT, handoff_id=handoff_id)
        if not rows:
            raise RuntimeError("SESSION_HANDOFF_NOT_FOUND")
        row = rows[0]
        if row["status"] != SessionHandoffStatus.ACTIVATED.value:
            raise RuntimeError("SESSION_HANDOFF_NOT_ACTIVATED")
        task_rows = self.truth.query("rc7_task", task_id=row["task_id"])
        if not task_rows:
            raise RuntimeError("TASK_NOT_FOUND")
        task = task_rows[0]
        if task.get("lease_owner") != row.get("successor_session_ref"):
            raise RuntimeError("SUCCESSOR_LEASE_NOT_ACTIVE")
        return {
            "mission_id": row["mission_id"],
            "task_id": row["task_id"],
            "task_state": task["state"],
            "generation": row["generation"],
            "active_session_ref": row["successor_session_ref"],
            "artifact_refs": list(row.get("artifact_refs", [])),
            "gap_refs": list(row.get("gap_refs", [])),
        }


install_session_overlay()
