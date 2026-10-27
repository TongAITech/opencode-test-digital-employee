"""Formal Center wrapper that makes N7 execution authority non-bypassable.

N7 is authorized before Center starts the WorkItem and again before every
runtime write. A runtime mutation may enter while the current authority is
still valid and can then invalidate N5/N6 through canonical R1. Any later write
from the stale N7 execution is rejected before it can claim completion or PASS.

Worker runtime payloads are observations, not authority. For N7, case identity
and both Attempt identities are derived by Center admission and then enforced at
every write boundary. A worker holding case A's lease cannot write or invalidate
case B by forging case_id/attempt_id in a runtime event.

WorkItem COMPLETED is lifecycle truth, not business PASS. N7 completion is
therefore fail-closed until Center can deterministically derive a terminal case
execution result (PASS or FAIL) from canonical R1 assertion observations and
AVAILABLE evidence. Before lifecycle completion, a real production result is
also persisted as a Center-owned canonical R1 receipt so downstream N9/N10 can
replay historical truth without depending on current N5/N6 state.
"""
from __future__ import annotations

from typing import Any, Optional

from rc8_runtime import RuntimeProducerKind

from .execution_admission import CenterN7ExecutionAdmissionGate, N7ExecutionAdmission, N7ExecutionAdmissionError
from .n7_execution_result import CenterN7CaseExecutionResultAuthority, N7CaseExecutionOutcome, N7CaseExecutionResultError
from .n7_execution_result_receipt import (
    CenterN7CaseExecutionResultReceiptAuthority,
    DERIVED_RESULT_EVENT_TYPE,
    N7CaseExecutionResultReceiptError,
)
from .n7_tool_invocation import CenterN7ToolInvocationAuthority, N7ToolInvocationAuthorityError


class N7AdmissionAwareFormalCenterControlPlane:
    """Re-authorize N7 at start, runtime writes, and completion."""

    def __init__(
        self,
        control_plane: object,
        execution_admission: CenterN7ExecutionAdmissionGate,
        result_authority: Optional[CenterN7CaseExecutionResultAuthority] = None,
        tool_invocation_authority: Optional[CenterN7ToolInvocationAuthority] = None,
        result_receipt_authority: Optional[CenterN7CaseExecutionResultReceiptAuthority] = None,
    ) -> None:
        self._control_plane = control_plane
        self.execution_admission = execution_admission
        self.result_authority = result_authority
        self.tool_invocation_authority = tool_invocation_authority
        # Production's real evaluator already owns the canonical ledger. Reuse
        # it so manual/real-HTTP construction cannot accidentally omit durable
        # result receipts. Test doubles without a ledger remain truth-neutral.
        if result_receipt_authority is None and result_authority is not None:
            ledger = getattr(result_authority, "runtime_ledger", None)
            if ledger is not None:
                result_receipt_authority = CenterN7CaseExecutionResultReceiptAuthority(ledger)
        self.result_receipt_authority = result_receipt_authority

    def __getattr__(self, name: str) -> Any:
        return getattr(self._control_plane, name)

    def _authorize_current_execution(self, work_item_id: str, node_id: str, lease_id: str):
        work = self._control_plane._require_active_lease(work_item_id, node_id, lease_id)
        stage_instance_id = self._control_plane.stage_instance_id_for_work_item(work_item_id)
        admission = self.execution_admission.authorize_start(work=work, stage_instance_id=stage_instance_id)
        return work, admission

    @staticmethod
    def _validate_runtime_event_identity(event: object, admission: N7ExecutionAdmission, *, lease_id: str) -> None:
        if str(getattr(event, "test_run_id", "") or "") != admission.test_run_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_TEST_RUN_AUTHORITY_MISMATCH")
        if str(getattr(event, "work_item_id", "") or "") != admission.work_item_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_WORK_ITEM_AUTHORITY_MISMATCH")
        if str(getattr(event, "case_id", "") or "") != admission.case_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_CASE_AUTHORITY_MISMATCH")
        event_type = str(getattr(event, "event_type", "") or "").strip().upper()
        supplied_attempt_id = str(getattr(event, "attempt_id", "") or "").strip()
        expected_attempt_id = str(lease_id) if event_type.startswith("ATTEMPT_") else admission.case_execution_attempt_id
        if supplied_attempt_id != expected_attempt_id:
            raise N7ExecutionAdmissionError("N7_RUNTIME_EVENT_ATTEMPT_AUTHORITY_MISMATCH")

    def _authorize_result_tool_write(
        self,
        admission: N7ExecutionAdmission,
        *,
        node_id: str,
        lease_id: str,
        producer_ref: str,
        case_id: str,
        attempt_id: str,
        tool_invocation_token: Optional[str],
    ) -> None:
        if self.tool_invocation_authority is None:
            raise N7ExecutionAdmissionError("N7_RESULT_TOOL_INVOCATION_AUTHORITY_NOT_CONFIGURED")
        try:
            self.tool_invocation_authority.authorize(
                admission,
                node_id=node_id,
                governance_lease_id=lease_id,
                token=str(tool_invocation_token or ""),
                producer_ref=producer_ref,
                case_id=case_id,
                case_execution_attempt_id=attempt_id,
            )
        except N7ToolInvocationAuthorityError as exc:
            raise N7ExecutionAdmissionError(str(exc)) from exc

    def authorize_n7_result_evidence_producer(
        self,
        *,
        work_item_id: str,
        node_id: str,
        lease_id: str,
        producer_ref: str,
        case_id: str,
        attempt_id: str,
        tool_invocation_token: Optional[str],
    ) -> None:
        _, admission = self._authorize_current_execution(work_item_id, node_id, lease_id)
        if admission is None:
            return
        if self.tool_invocation_authority is None:
            raise N7ExecutionAdmissionError("N7_RESULT_TOOL_INVOCATION_AUTHORITY_NOT_CONFIGURED")
        try:
            requires = self.tool_invocation_authority.producer_requires_grant(admission, producer_ref)
        except N7ToolInvocationAuthorityError as exc:
            raise N7ExecutionAdmissionError(str(exc)) from exc
        if requires:
            self._authorize_result_tool_write(
                admission,
                node_id=node_id,
                lease_id=lease_id,
                producer_ref=producer_ref,
                case_id=case_id,
                attempt_id=attempt_id,
                tool_invocation_token=tool_invocation_token,
            )

    def start_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        self._authorize_current_execution(work_item_id, node_id, lease_id)
        return self._control_plane.start_work_item(work_item_id, node_id, lease_id)

    def append_runtime_event(self, event: object, *, lease_id: str, n7_tool_invocation_token: Optional[str] = None):
        _, admission = self._authorize_current_execution(
            str(getattr(event, "work_item_id", "")),
            str(getattr(event, "node_id", "")),
            lease_id,
        )
        if admission is not None:
            self._validate_runtime_event_identity(event, admission, lease_id=lease_id)
            event_type = str(getattr(event, "event_type", "") or "").strip().upper()
            if event_type == DERIVED_RESULT_EVENT_TYPE:
                raise N7ExecutionAdmissionError("CENTER_OWNS_N7_DERIVED_RESULT_RECEIPT")
            if getattr(event, "producer_kind", None) == RuntimeProducerKind.TOOL and event_type == "ASSERTION_OBSERVED":
                self._authorize_result_tool_write(
                    admission,
                    node_id=str(getattr(event, "node_id", "") or ""),
                    lease_id=lease_id,
                    producer_ref=str(getattr(event, "producer_ref", "") or ""),
                    case_id=str(getattr(event, "case_id", "") or ""),
                    attempt_id=str(getattr(event, "attempt_id", "") or ""),
                    tool_invocation_token=n7_tool_invocation_token,
                )
        return self._control_plane.append_runtime_event(event, lease_id=lease_id)

    def complete_work_item(self, work_item_id: str, node_id: str, lease_id: str):
        _, admission = self._authorize_current_execution(work_item_id, node_id, lease_id)
        if admission is not None:
            if self.result_authority is None:
                raise N7ExecutionAdmissionError("N7_CASE_EXECUTION_RESULT_AUTHORITY_REQUIRED")
            try:
                result = self.result_authority.evaluate(admission)
            except N7CaseExecutionResultError as exc:
                raise N7ExecutionAdmissionError("N7_CASE_EXECUTION_RESULT_INVALID:%s" % exc) from exc
            if result.outcome == N7CaseExecutionOutcome.PENDING:
                raise N7ExecutionAdmissionError("N7_CASE_EXECUTION_RESULT_PENDING:%s" % result.reason)
            if self.result_receipt_authority is not None:
                try:
                    self.result_receipt_authority.record(result, node_id=node_id)
                except N7CaseExecutionResultReceiptError as exc:
                    raise N7ExecutionAdmissionError("N7_DERIVED_RESULT_RECEIPT_INVALID:%s" % exc) from exc
            elif isinstance(self.result_authority, CenterN7CaseExecutionResultAuthority):
                # A real evaluator without a durable receipt boundary is a
                # production misconfiguration; do not complete the WorkItem.
                raise N7ExecutionAdmissionError("N7_DERIVED_RESULT_RECEIPT_AUTHORITY_REQUIRED")
        return self._control_plane.complete_work_item(work_item_id, node_id, lease_id)
