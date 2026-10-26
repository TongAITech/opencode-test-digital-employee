"""BANK N5 closure with both direct and non-direct N8 successor authority.

The base recovery-aware N5 selector already admits direct-retry history only when
N8_DIRECT_RETRY_RECEIPT proves a complete predecessor -> successor edge.  This
subclass adds the same fail-closed admission for UPSTREAM_REPAIR_THEN_RETRY
successors authorized by canonical N8_REPAIR_RECEIPT.  Re-preparation successors
are intentionally not admitted here yet.
"""
from __future__ import annotations

from typing import Tuple

from .autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from . import bank_autonomous_preparation_closure as base
from .bank_n5_recovery_closure import BankN5RecoveryAwarePreparationClosureCoordinator
from .bank_n8_recovery import BankN8RecoveryError, _file_payload
from .bank_n8_upstream_successor import BankN8UpstreamSuccessorCoordinator
from .case_runtime import PREPARED_ATTEMPT_KIND


class BankN5FullRecoveryAwarePreparationClosureCoordinator(
    BankN5RecoveryAwarePreparationClosureCoordinator
):
    """Admit only durable direct or upstream-repair N8 successor chains."""

    @staticmethod
    def _n8_direct_edge(
        control,
        *,
        execution_task_id: str,
        tc_id: str,
        successor_attempt_id: str,
    ) -> Tuple[str, str]:
        predecessor, successor = BankN5RecoveryAwarePreparationClosureCoordinator._n8_direct_edge(
            control,
            execution_task_id=execution_task_id,
            tc_id=tc_id,
            successor_attempt_id=successor_attempt_id,
        )
        if predecessor:
            return predecessor, successor

        prepared_rows = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == PREPARED_ATTEMPT_KIND
            and execution_task_id in set(str(x) for x in row.get("subject_refs") or [])
            and successor_attempt_id in set(str(x) for x in row.get("subject_refs") or [])
        ]
        if len(prepared_rows) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_SUCCESSOR_PREPARED_NOT_UNIQUE:%s:%d"
                % (successor_attempt_id, len(prepared_rows))
            )
        prepared = prepared_rows[0]
        if prepared.get("source_ref") != BankN8UpstreamSuccessorCoordinator.SUCCESSOR_SOURCE_REF:
            return "", ""

        receipt_rows = []
        for ref in prepared.get("subject_refs") or []:
            rows = control.truth.query("rc7_evidence", evidence_id=str(ref))
            if len(rows) == 1 and rows[0].get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE:
                receipt_rows.append(rows[0])
        if len(receipt_rows) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_AUTHORIZATION_NOT_UNIQUE:%s:%d"
                % (successor_attempt_id, len(receipt_rows))
            )
        receipt = receipt_rows[0]
        try:
            receipt_payload = _file_payload(receipt, "BANK_N5_N8_UPSTREAM_RECEIPT")
        except BankN8RecoveryError as exc:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_AUTHORIZATION_INVALID:%s" % exc
            ) from exc
        if (
            receipt_payload.get("source_task_id") != execution_task_id
            or receipt_payload.get("successor_attempt_id") != successor_attempt_id
            or receipt_payload.get("reprepare_required") is not False
        ):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_AUTHORIZATION_IDENTITY_MISMATCH:%s" % successor_attempt_id
            )
        work_order_id = str(receipt_payload.get("work_order_id") or "")
        if not work_order_id:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_WORK_ORDER_ID_REQUIRED:%s" % successor_attempt_id
            )

        work_order_matches = []
        for row in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            if row.get("kind") != N8RecoveryOrchestrator.WORK_ORDER_TYPE:
                continue
            try:
                payload = _file_payload(row, "BANK_N5_N8_UPSTREAM_WORK_ORDER")
            except BankN8RecoveryError as exc:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_UPSTREAM_WORK_ORDER_INVALID:%s" % exc
                ) from exc
            if str(payload.get("work_order_id") or "") == work_order_id:
                work_order_matches.append((row, payload))
        if len(work_order_matches) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_WORK_ORDER_NOT_UNIQUE:%s:%d"
                % (successor_attempt_id, len(work_order_matches))
            )
        work_order = work_order_matches[0][1]
        raw_plan = work_order.get("plan")
        if not isinstance(raw_plan, dict):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_PLAN_REQUIRED:%s" % successor_attempt_id
            )
        source_attempt_id = str(raw_plan.get("source_attempt_id") or "")
        if (
            work_order.get("source_task_id") != execution_task_id
            or str(raw_plan.get("successor_attempt_id") or "") != successor_attempt_id
            or raw_plan.get("mode") != "UPSTREAM_REPAIR_THEN_RETRY"
            or raw_plan.get("reprepare_required") is not False
            or not source_attempt_id
            or source_attempt_id == successor_attempt_id
        ):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_WORK_ORDER_IDENTITY_MISMATCH:%s" % successor_attempt_id
            )
        gap_id = str(work_order.get("gap_id") or "")
        gaps = control.truth.query("rc7_gap", gap_id=gap_id)
        if len(gaps) != 1 or tc_id not in set(str(x) for x in gaps[0].get("subject_refs") or []):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_UPSTREAM_AUTHORIZATION_CASE_MISMATCH:%s" % successor_attempt_id
            )
        return source_attempt_id, successor_attempt_id
