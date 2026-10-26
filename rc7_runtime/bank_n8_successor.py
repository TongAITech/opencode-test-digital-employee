"""Materialize durable BANK N8 successor preparation for authorized direct retry.

The previous PreparedAttempt is immutable history.  A direct retry authorization
may reuse its verified bindings/oracle, but only by creating a fresh durable
CASE_PREPARED_ATTEMPT for the RecoveryDecision successor attempt.  This module
never executes the business Case and never handles re-preparation recovery.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.preparation import PreparedAttempt

from .bank_n8_recovery import BankN8RecoveryCoordinator, BankN8RecoveryError, _file_payload
from .case_runtime import (
    PREPARED_ATTEMPT_KIND,
    CaseRuntimeError,
    _mission_release,
    _state_ref,
    _write_immutable_json,
)
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evidence, GapStatus, TaskStatus
from .truth_overlay import append_entity


class BankN8SuccessorError(RuntimeError):
    pass


class BankN8SuccessorCoordinator:
    """Consume one unconsumed direct-retry receipt into a fresh PreparedAttempt."""

    def __init__(self, *, state_root) -> None:
        from pathlib import Path
        self.state_root = Path(state_root).expanduser().resolve()

    @staticmethod
    def _prepared_from_payload(raw: Mapping[str, Any]) -> PreparedAttempt:
        try:
            return PreparedAttempt(
                status=str(raw["status"]),
                attempt_id=str(raw["attempt_id"]),
                tc_id=str(raw["tc_id"]),
                case_version=int(raw["case_version"]),
                target_id=str(raw["target_id"]),
                precondition_evidence=tuple(raw.get("precondition_evidence") or ()),
                initial_state_bindings=dict(raw.get("initial_state_bindings") or {}),
                input_data_bindings=dict(raw.get("input_data_bindings") or {}),
                binding_evidence=tuple(raw.get("binding_evidence") or ()),
                cleanup_policy=dict(raw.get("cleanup_policy") or {}),
                oracle_snapshot=dict(raw.get("oracle_snapshot") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_PAYLOAD_INVALID") from exc

    @staticmethod
    def _pending_direct_receipt(
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        tc_id: str,
    ) -> Optional[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
        candidates = []
        for row in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            if row.get("kind") != BankN8RecoveryCoordinator.DIRECT_RECEIPT_TYPE:
                continue
            refs = set(str(x) for x in row.get("subject_refs") or [])
            if source_task_id not in refs:
                continue
            try:
                payload = _file_payload(row, "BANK_N8_DIRECT_RECEIPT")
            except BankN8RecoveryError as exc:
                raise BankN8SuccessorError(str(exc)) from exc
            if payload.get("source_task_id") != source_task_id:
                raise BankN8SuccessorError("BANK_N8_DIRECT_RECEIPT_SOURCE_TASK_MISMATCH")
            gap_id = str(payload.get("gap_id") or "")
            gap_rows = control.truth.query("rc7_gap", gap_id=gap_id)
            if len(gap_rows) != 1:
                raise BankN8SuccessorError("BANK_N8_DIRECT_RECEIPT_GAP_NOT_UNIQUE")
            gap = gap_rows[0]
            if gap.get("mission_id") != control.mission_id:
                raise BankN8SuccessorError("BANK_N8_DIRECT_RECEIPT_GAP_MISSION_MISMATCH")
            if tc_id not in set(str(x) for x in gap.get("subject_refs") or []):
                continue
            if gap.get("state") != GapStatus.EVIDENCE_PENDING.value:
                continue
            successor = str(payload.get("successor_attempt_id") or "")
            source_attempt = str(payload.get("source_attempt_id") or "")
            if not successor or not source_attempt or successor == source_attempt:
                raise BankN8SuccessorError("BANK_N8_DIRECT_RECEIPT_SUCCESSOR_INVALID")
            already_prepared = [
                evidence
                for evidence in control.truth.query("rc7_evidence", mission_id=control.mission_id)
                if evidence.get("kind") == PREPARED_ATTEMPT_KIND
                and source_task_id in set(str(x) for x in evidence.get("subject_refs") or [])
                and successor in set(str(x) for x in evidence.get("subject_refs") or [])
            ]
            if already_prepared:
                # This authorization has already been consumed.  It must never
                # be selected again for a later retry or sibling Case.
                continue
            candidates.append((row, payload))
        if not candidates:
            return None
        if len(candidates) != 1:
            raise BankN8SuccessorError("BANK_N8_PENDING_DIRECT_SUCCESSOR_NOT_UNIQUE:%d" % len(candidates))
        return candidates[0]

    def _source_prepared(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        source_attempt_id: str,
        tc_id: str,
        target_id: str,
    ) -> PreparedAttempt:
        rows = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == PREPARED_ATTEMPT_KIND
            and source_task_id in set(str(x) for x in row.get("subject_refs") or [])
            and source_attempt_id in set(str(x) for x in row.get("subject_refs") or [])
        ]
        if len(rows) != 1:
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_NOT_UNIQUE:%d" % len(rows))
        row = rows[0]
        ref = str(row.get("content_ref") or "")
        if not ref.startswith("state://"):
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_STATE_REF_REQUIRED")
        path = (self.state_root / ref[len("state://"):]).resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_PATH_ESCAPE") from exc
        if not path.is_file():
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_FILE_MISSING")
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != str(row.get("content_hash") or ""):
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_HASH_MISMATCH")
        import json
        try:
            raw = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_JSON_INVALID") from exc
        if not isinstance(raw, dict):
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_OBJECT_REQUIRED")
        prepared = self._prepared_from_payload(raw)
        if (
            prepared.status != "PREPARED"
            or prepared.attempt_id != source_attempt_id
            or prepared.tc_id != tc_id
            or prepared.target_id != target_id
        ):
            raise BankN8SuccessorError("BANK_N8_SOURCE_PREPARED_IDENTITY_MISMATCH")
        return prepared

    def materialize_direct_successor(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        worker_id: str,
        tc_id: str,
        target_id: str,
    ) -> Optional[Dict[str, Any]]:
        pending = self._pending_direct_receipt(
            control,
            source_task_id=source_task_id,
            tc_id=tc_id,
        )
        if pending is None:
            return None
        receipt_row, receipt = pending
        task = control.scheduler.task(source_task_id)
        if task.state != TaskStatus.LEASED or task.lease_owner != worker_id:
            raise BankN8SuccessorError("BANK_N8_SUCCESSOR_REQUIRES_CURRENT_SOURCE_LEASE")
        if receipt.get("business_action_executed") is not False:
            raise BankN8SuccessorError("BANK_N8_DIRECT_AUTHORIZATION_MUST_NOT_EXECUTE_BUSINESS")
        source_attempt = str(receipt["source_attempt_id"])
        successor_attempt = str(receipt["successor_attempt_id"])
        previous = self._source_prepared(
            control,
            source_task_id=source_task_id,
            source_attempt_id=source_attempt,
            tc_id=tc_id,
            target_id=target_id,
        )
        successor = replace(previous, attempt_id=successor_attempt)
        from dataclasses import asdict
        payload = asdict(successor)
        from pathlib import Path
        target, digest = _write_immutable_json(
            self.state_root,
            Path(str(control.mission_id)) / str(successor_attempt) / "prepared-attempt.json",
            payload,
        )
        evidence_id = "EVD-PREPARED-" + hashlib.sha256(
            (control.mission_id + "\x1f" + source_task_id + "\x1f" + successor_attempt + "\x1f" + digest).encode("utf-8")
        ).hexdigest()[:24]
        existing = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if existing:
            if len(existing) != 1 or existing[0].get("content_hash") != digest:
                raise BankN8SuccessorError("BANK_N8_SUCCESSOR_PREPARED_EVIDENCE_CONFLICT")
        else:
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind=PREPARED_ATTEMPT_KIND,
                    source_ref="runtime://bank-n8/direct-retry-successor",
                    content_ref=_state_ref(self.state_root, target),
                    subject_refs=[
                        source_task_id,
                        worker_id,
                        successor_attempt,
                        tc_id,
                        target_id,
                        str(receipt_row["evidence_id"]),
                        source_attempt,
                    ],
                    content_hash=digest,
                ),
                release_id=_mission_release(control.truth, control.mission_id),
                artifact_version=1,
            )
        return {
            "status": "PREPARED",
            "prepared_attempt": payload,
            "evidence_id": evidence_id,
            "replayed": False,
            "n8_successor": True,
            "authorization_evidence_id": str(receipt_row["evidence_id"]),
            "source_attempt_id": source_attempt,
        }
