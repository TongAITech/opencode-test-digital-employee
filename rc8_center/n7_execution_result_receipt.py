"""Durable Center-derived N7 case execution result receipts in canonical R1.

The deterministic N7 evaluator decides PASS/FAIL from assertion observations
and AVAILABLE evidence.  This module persists that already-derived terminal
result before the N7 WorkItem can complete, so downstream N9/N10 consumers can
replay historical execution truth without depending on whichever N5/N6 state is
currently active later.

Receipt persistence does not replace assertion/evidence truth.  It is a
Center-owned summary fact whose identity and payload are checked against the
same N7 result object that was just derived from canonical R1.
"""
from __future__ import annotations

import time
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind

from .n7_execution_result import N7CaseExecutionOutcome, N7CaseExecutionResult


class N7CaseExecutionResultReceiptError(ValueError):
    pass


DERIVED_RESULT_EVENT_TYPE = "CASE_EXECUTION_RESULT_DERIVED"
DERIVED_RESULT_PRODUCER_REF = "rc8-center-n7-result-authority"
DERIVED_RESULT_AUTHORITY = "CENTER_DETERMINISTIC_N7_RESULT"


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N7CaseExecutionResultReceiptError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: object, name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise N7CaseExecutionResultReceiptError("%s_MUST_BE_LIST" % name.upper())
    out = []
    for value in values:
        ref = _required(value, name[:-1] if name.endswith("s") else name)
        if ref not in out:
            out.append(ref)
    return tuple(out)


class CenterN7CaseExecutionResultReceiptAuthority:
    """Persist/read immutable Center-derived N7 terminal result facts."""

    def __init__(self, runtime_ledger: object, *, now_fn=None) -> None:
        self.runtime_ledger = runtime_ledger
        self.now_fn = now_fn or (lambda: int(time.time()))

    @staticmethod
    def event_id_for(result: N7CaseExecutionResult) -> str:
        return "center-n7-case-result:%s:%s" % (
            result.work_item_id,
            result.case_execution_attempt_id,
        )

    def record(self, result: N7CaseExecutionResult, *, node_id: str) -> N7CaseExecutionResult:
        self._require_terminal(result)
        node_id = _required(node_id, "node_id")
        event_id = self.event_id_for(result)
        existing = self._event_by_id(event_id)
        if existing is not None:
            persisted = self._parse(existing)
            if persisted != result:
                raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_RECEIPT_CONFLICT")
            return persisted

        sequence = self.runtime_ledger.latest_node_sequence(
            test_run_id=result.test_run_id,
            node_id=node_id,
        ) + 1
        occurred_at = int(self.now_fn())
        event = RuntimeEventEnvelope(
            event_id=event_id,
            test_run_id=result.test_run_id,
            work_item_id=result.work_item_id,
            node_id=node_id,
            producer_kind=RuntimeProducerKind.NODE_AGENT,
            producer_ref=DERIVED_RESULT_PRODUCER_REF,
            event_type=DERIVED_RESULT_EVENT_TYPE,
            sequence=sequence,
            case_id=result.case_id,
            attempt_id=result.case_execution_attempt_id,
            refs=["artifact:%s" % value for value in result.evidence_refs],
            data={
                "authority": DERIVED_RESULT_AUTHORITY,
                "outcome": result.outcome.value,
                "prepared_attempt_id": result.prepared_attempt_id,
                "executable_spec_id": result.executable_spec_id,
                "assertion_refs": list(result.assertion_refs),
                "resolved_assertion_refs": list(result.resolved_assertion_refs),
                "evidence_refs": list(result.evidence_refs),
                "reason": result.reason,
            },
            occurred_at=occurred_at,
        )
        self.runtime_ledger.assert_next_node_sequence(event)
        self.runtime_ledger.append_runtime(event)
        return self._parse(self._event_by_id(event_id))

    def read_for_work_item(self, work_item_id: str) -> N7CaseExecutionResult:
        work_item_id = _required(work_item_id, "work_item_id")
        matches = []
        for event in self.runtime_ledger.runtime_events(work_item_id=work_item_id):
            if str(event.get("event_type") or "") != DERIVED_RESULT_EVENT_TYPE:
                continue
            if str(event.get("producer_ref") or "") != DERIVED_RESULT_PRODUCER_REF:
                continue
            matches.append(event)
        if not matches:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_RECEIPT_NOT_FOUND")
        if len(matches) != 1:
            raise N7CaseExecutionResultReceiptError("MULTIPLE_N7_DERIVED_RESULT_RECEIPTS")
        result = self._parse(matches[0])
        if self.event_id_for(result) != str(matches[0].get("event_id") or ""):
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_EVENT_ID_INVALID")
        return result

    def _event_by_id(self, event_id: str) -> Optional[Dict[str, object]]:
        found = []
        for event in self.runtime_ledger.runtime_events():
            if str(event.get("event_id") or "") == event_id:
                found.append(event)
        if len(found) > 1:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_EVENT_ID_DUPLICATE")
        return found[0] if found else None

    @staticmethod
    def _require_terminal(result: N7CaseExecutionResult) -> None:
        if not isinstance(result, N7CaseExecutionResult):
            raise N7CaseExecutionResultReceiptError("N7_CASE_EXECUTION_RESULT_REQUIRED")
        if result.outcome not in {N7CaseExecutionOutcome.PASS, N7CaseExecutionOutcome.FAIL}:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_REQUIRES_TERMINAL_OUTCOME")
        if not result.evidence_refs:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_REQUIRES_EVIDENCE")

    @classmethod
    def _parse(cls, event: Optional[Mapping[str, object]]) -> N7CaseExecutionResult:
        if not isinstance(event, Mapping):
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_RECEIPT_NOT_FOUND")
        if str(event.get("event_type") or "") != DERIVED_RESULT_EVENT_TYPE:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_EVENT_TYPE_INVALID")
        if str(event.get("producer_kind") or "") != RuntimeProducerKind.NODE_AGENT.value:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_PRODUCER_KIND_INVALID")
        if str(event.get("producer_ref") or "") != DERIVED_RESULT_PRODUCER_REF:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_PRODUCER_INVALID")
        data = event.get("data")
        if not isinstance(data, Mapping):
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_DATA_REQUIRED")
        if str(data.get("authority") or "") != DERIVED_RESULT_AUTHORITY:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_AUTHORITY_INVALID")
        try:
            outcome = N7CaseExecutionOutcome(_required(data.get("outcome"), "outcome"))
        except ValueError as exc:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_OUTCOME_INVALID") from exc
        result = N7CaseExecutionResult(
            outcome=outcome,
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            work_item_id=_required(event.get("work_item_id"), "work_item_id"),
            case_id=_required(event.get("case_id"), "case_id"),
            case_execution_attempt_id=_required(event.get("attempt_id"), "attempt_id"),
            prepared_attempt_id=_required(data.get("prepared_attempt_id"), "prepared_attempt_id"),
            executable_spec_id=_required(data.get("executable_spec_id"), "executable_spec_id"),
            assertion_refs=_refs(data.get("assertion_refs"), "assertion_refs"),
            resolved_assertion_refs=_refs(data.get("resolved_assertion_refs"), "resolved_assertion_refs"),
            evidence_refs=_refs(data.get("evidence_refs"), "evidence_refs"),
            reason=_required(data.get("reason"), "reason"),
        )
        cls._require_terminal(result)
        expected_refs = tuple("artifact:%s" % value for value in result.evidence_refs)
        actual_refs = _refs(event.get("refs"), "refs")
        if actual_refs != expected_refs:
            raise N7CaseExecutionResultReceiptError("N7_DERIVED_RESULT_EVIDENCE_REFS_MISMATCH")
        return result
