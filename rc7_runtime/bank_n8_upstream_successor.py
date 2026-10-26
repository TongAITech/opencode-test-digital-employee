"""BANK N8 successor closure for non-direct upstream repair without re-preparation.

Owner repair is already executed by the owning DSH node and independently
accepted before this coordinator runs.  This module consumes that durable work
order while the source EXECUTION task is still READY, asks the canonical N8
orchestrator to emit the repair receipt, then materializes the authorized fresh
PreparedAttempt after the source task is leased but before business execution.

REPREPARE_THEN_RETRY is deliberately not handled here.  AUTH/DATA/PRECONDITION
recovery remains fail-closed until the field preparation + canonical prepared
artifact path is completed.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .autonomous_recovery_orchestrator import (
    DurableRepairWorkOrder,
    N8RecoveryOrchestrationError,
    N8RecoveryOrchestrator,
)
from .bank_n8_recovery import BankN8RecoveryError, _file_payload
from .bank_n8_successor import BankN8SuccessorCoordinator
from .case_runtime import PREPARED_ATTEMPT_KIND, _mission_release, _state_ref, _write_immutable_json
from .closed_loop_control import ClosedLoopControlPlane
from .execution_recovery import ExecutionRecoveryPlanner, RecoveryWorkPlan
from .models import Evidence, GapStatus, TaskStatus
from .truth_overlay import append_entity


class BankN8UpstreamSuccessorError(RuntimeError):
    pass


class BankN8UpstreamSuccessorCoordinator:
    """Authorize and materialize UPSTREAM_REPAIR_THEN_RETRY successors."""

    SUCCESSOR_SOURCE_REF = "runtime://bank-n8/upstream-repair-successor"

    def __init__(self, *, state_root: str, evidence_root: str) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.orchestrator = N8RecoveryOrchestrator(evidence_root=evidence_root)
        self.prepared_reader = BankN8SuccessorCoordinator(state_root=str(self.state_root))

    @staticmethod
    def _plan(raw: Mapping[str, Any]) -> RecoveryWorkPlan:
        try:
            return RecoveryWorkPlan(
                diagnosis_id=str(raw["diagnosis_id"]),
                source_attempt_id=str(raw["source_attempt_id"]),
                action=str(raw["action"]),
                mode=str(raw["mode"]),
                target_node=str(raw["target_node"]),
                retry_allowed=bool(raw["retry_allowed"]),
                reprepare_required=bool(raw["reprepare_required"]),
                terminal=bool(raw["terminal"]),
                successor_attempt_id=(str(raw["successor_attempt_id"]) if raw.get("successor_attempt_id") else None),
                reason=str(raw["reason"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_PLAN_INVALID") from exc

    @staticmethod
    def _work_order_artifact(
        control: ClosedLoopControlPlane,
        *,
        evidence_id: str,
        content_ref: str,
    ) -> Mapping[str, Any]:
        rows = [
            row for row in control.truth.query("rc7_artifact", mission_id=control.mission_id)
            if row.get("artifact_type_name") == N8RecoveryOrchestrator.WORK_ORDER_TYPE
            and row.get("content_ref") == content_ref
            and evidence_id in set(str(x) for x in row.get("evidence_refs") or [])
        ]
        if len(rows) != 1:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_UPSTREAM_WORK_ORDER_ARTIFACT_NOT_UNIQUE:%d" % len(rows)
            )
        return rows[0]

    def _work_order(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        tc_id: str,
    ) -> Optional[Tuple[DurableRepairWorkOrder, RecoveryWorkPlan, Mapping[str, Any]]]:
        matches = []
        for evidence in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            if evidence.get("kind") != N8RecoveryOrchestrator.WORK_ORDER_TYPE:
                continue
            refs = set(str(x) for x in evidence.get("subject_refs") or [])
            if source_task_id not in refs:
                continue
            try:
                payload = _file_payload(evidence, "BANK_N8_UPSTREAM_WORK_ORDER")
            except BankN8RecoveryError as exc:
                raise BankN8UpstreamSuccessorError(str(exc)) from exc
            if payload.get("source_task_id") != source_task_id:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SOURCE_TASK_MISMATCH")
            raw_plan = payload.get("plan")
            if not isinstance(raw_plan, dict):
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_PLAN_REQUIRED")
            plan = self._plan(raw_plan)
            if plan.mode != "UPSTREAM_REPAIR_THEN_RETRY" or plan.reprepare_required:
                continue
            if plan.terminal or not plan.retry_allowed or not plan.successor_attempt_id:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_RETRYABLE_PLAN_REQUIRED")
            gap_id = str(payload.get("gap_id") or "")
            gaps = control.truth.query("rc7_gap", gap_id=gap_id)
            if len(gaps) != 1:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_GAP_NOT_UNIQUE")
            gap = gaps[0]
            if gap.get("mission_id") != control.mission_id:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_GAP_MISSION_MISMATCH")
            if tc_id not in set(str(x) for x in gap.get("subject_refs") or []):
                continue
            if gap.get("state") != GapStatus.EVIDENCE_PENDING.value:
                continue
            artifact = self._work_order_artifact(
                control,
                evidence_id=str(evidence["evidence_id"]),
                content_ref=str(evidence.get("content_ref") or ""),
            )
            work_order = DurableRepairWorkOrder(
                work_order_id=str(payload["work_order_id"]),
                source_task_id=source_task_id,
                repair_task_id=str(payload["repair_task_id"]),
                gap_id=gap_id,
                diagnosis_evidence_id=str(payload["diagnosis_evidence_id"]),
                diagnosis_id=plan.diagnosis_id,
                source_attempt_id=plan.source_attempt_id,
                successor_attempt_id=str(plan.successor_attempt_id),
                failure_signature_id=str(payload["failure_signature_id"]),
                strategy_key=str(payload["strategy_key"]),
                mode=plan.mode,
                target_node=plan.target_node,
                reprepare_required=False,
                artifact_id=str(artifact["artifact_id"]),
                evidence_id=str(evidence["evidence_id"]),
                content_hash=str(evidence.get("content_hash") or ""),
            )
            matches.append((work_order, plan, evidence))
        if not matches:
            return None
        if len(matches) != 1:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_UPSTREAM_WORK_ORDER_NOT_UNIQUE:%d" % len(matches)
            )
        return matches[0]

    @staticmethod
    def _receipt_for_work_order(
        control: ClosedLoopControlPlane,
        work_order_id: str,
    ) -> Optional[Mapping[str, Any]]:
        rows = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
            and work_order_id in set(str(x) for x in row.get("subject_refs") or [])
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_UPSTREAM_RECEIPT_NOT_UNIQUE:%d" % len(rows)
            )
        return rows[0]

    def authorize_if_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        tc_id: str,
        target_id: str,
    ) -> Optional[str]:
        current = self._work_order(
            control,
            source_task_id=source_task_id,
            tc_id=tc_id,
        )
        if current is None:
            return None
        work_order, plan, _work_order_evidence = current
        existing = self._receipt_for_work_order(control, work_order.work_order_id)
        if existing is not None:
            return str(existing["evidence_id"])
        source = control.scheduler.task(source_task_id)
        if source.state != TaskStatus.READY:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_UPSTREAM_AUTHORIZATION_REQUIRES_SOURCE_READY:%s" % source.state.value
            )
        prepared_before = self.prepared_reader._source_prepared(
            control,
            source_task_id=source_task_id,
            source_attempt_id=work_order.source_attempt_id,
            tc_id=tc_id,
            target_id=target_id,
        )
        try:
            authorization = self.orchestrator.accept_repair_receipt(
                control,
                work_order=work_order,
                plan=plan,
                prepared_before=prepared_before,
            )
        except N8RecoveryOrchestrationError as exc:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_UPSTREAM_RECEIPT_REJECTED:%s" % exc
            ) from exc
        return authorization.repair_receipt_evidence_id

    def materialize_if_authorized(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        worker_id: str,
        tc_id: str,
        target_id: str,
    ) -> Optional[Dict[str, Any]]:
        current = self._work_order(
            control,
            source_task_id=source_task_id,
            tc_id=tc_id,
        )
        if current is None:
            return None
        work_order, plan, _ = current
        receipt = self._receipt_for_work_order(control, work_order.work_order_id)
        if receipt is None:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SUCCESSOR_AUTHORIZATION_REQUIRED")
        task = control.scheduler.task(source_task_id)
        if task.state != TaskStatus.LEASED or task.lease_owner != worker_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SUCCESSOR_REQUIRES_CURRENT_SOURCE_LEASE")
        try:
            receipt_payload = _file_payload(receipt, "BANK_N8_UPSTREAM_RECEIPT")
        except BankN8RecoveryError as exc:
            raise BankN8UpstreamSuccessorError(str(exc)) from exc
        if receipt_payload.get("work_order_id") != work_order.work_order_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_RECEIPT_WORK_ORDER_MISMATCH")
        if receipt_payload.get("source_task_id") != source_task_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_RECEIPT_SOURCE_TASK_MISMATCH")
        if receipt_payload.get("reprepare_required") is not False:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_RECEIPT_REPREPARE_FORBIDDEN")
        successor_attempt = str(receipt_payload.get("successor_attempt_id") or "")
        if successor_attempt != work_order.successor_attempt_id or successor_attempt == work_order.source_attempt_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_RECEIPT_SUCCESSOR_MISMATCH")

        previous = self.prepared_reader._source_prepared(
            control,
            source_task_id=source_task_id,
            source_attempt_id=work_order.source_attempt_id,
            tc_id=tc_id,
            target_id=target_id,
        )
        successor = ExecutionRecoveryPlanner.compile_successor_prepared_attempt(previous, plan)
        if successor.attempt_id != successor_attempt:
            raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SUCCESSOR_PREPARATION_DRIFT")

        existing = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == PREPARED_ATTEMPT_KIND
            and self.prepared_reader._prepared_identity_matches(
                row,
                source_task_id=source_task_id,
                attempt_id=successor_attempt,
                tc_id=tc_id,
            )
        ]
        if existing:
            if len(existing) != 1 or existing[0].get("source_ref") != self.SUCCESSOR_SOURCE_REF:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SUCCESSOR_PREPARED_CONFLICT")
            durable = self.prepared_reader._source_prepared(
                control,
                source_task_id=source_task_id,
                source_attempt_id=successor_attempt,
                tc_id=tc_id,
                target_id=target_id,
            )
            if durable != successor:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_SUCCESSOR_PREPARED_DRIFT")
            return {
                "status": "PREPARED",
                "prepared_attempt": asdict(durable),
                "evidence_id": str(existing[0]["evidence_id"]),
                "replayed": True,
                "n8_successor": True,
                "authorization_evidence_id": str(receipt["evidence_id"]),
                "source_attempt_id": work_order.source_attempt_id,
            }

        payload = asdict(successor)
        target, digest = _write_immutable_json(
            self.state_root,
            Path(str(control.mission_id)) / str(successor_attempt) / "prepared-attempt.json",
            payload,
        )
        evidence_id = "EVD-PREPARED-" + hashlib.sha256(
            (control.mission_id + "\x1f" + source_task_id + "\x1f" + successor_attempt + "\x1f" + digest).encode("utf-8")
        ).hexdigest()[:24]
        append_entity(
            control.truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id=control.mission_id,
                kind=PREPARED_ATTEMPT_KIND,
                source_ref=self.SUCCESSOR_SOURCE_REF,
                content_ref=_state_ref(self.state_root, target),
                subject_refs=[
                    source_task_id,
                    worker_id,
                    successor_attempt,
                    tc_id,
                    target_id,
                    str(receipt["evidence_id"]),
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
            "authorization_evidence_id": str(receipt["evidence_id"]),
            "source_attempt_id": work_order.source_attempt_id,
        }
