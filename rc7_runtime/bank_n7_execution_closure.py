"""BANK production bridge from completed execution fan-out to governed N7.

This module deliberately does not implement a second coverage evaluator.  It
binds the production BANK execution truth to the existing
``AutonomousN7NodeService`` at the real batch boundary:

current accepted Test Design inventory
-> current CASE_EXECUTION_TERMINAL receipts
-> current-run N5 preparation finalizations / Attempts
-> current L1-L7 coverage denominators and receipts
-> AutonomousN7NodeService READY_FOR_DIRECTOR_REVIEW
-> the shared Wave-D independent Director gate
-> durable N7 NODE_TERMINAL.

Coverage closure and product quality remain separate truths.  A trusted product
failure may therefore be a terminal execution receipt and COVERED_FAIL coverage,
but this bridge never converts it into a product-quality PASS.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .autonomous_contract import CanonicalLayer, LayerCoverageReceipt
from .autonomous_coverage_closure import DurableLayerCoverageReceipt
from .autonomous_n7_node import AutonomousN7NodeError, AutonomousN7NodeService, WaveDNodeAdoptionControl
from .autonomous_node_adoption import AutonomousNodeAdoptionError
from .case_fanout_conformance import AcceptedCaseInventoryReader
from .closed_loop_control import ClosedLoopControlPlane
from .execution_fanout_conformance import (
    ExecutionFanoutConformanceError,
    check_execution_barrier,
    load_execution_terminal_receipt,
)


class BankN7ExecutionClosureError(RuntimeError):
    pass


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BankN7ExecutionClosureError(code)
    return text


def _file_payload(row: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise BankN7ExecutionClosureError(code + "_FILE_REQUIRED")
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise BankN7ExecutionClosureError(code + "_FILE_MISSING")
    raw = path.read_bytes()
    expected = str(row.get("content_hash") or "")
    if expected != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise BankN7ExecutionClosureError(code + "_HASH_MISMATCH")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BankN7ExecutionClosureError(code + "_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise BankN7ExecutionClosureError(code + "_OBJECT_REQUIRED")
    return payload


class BankN7ExecutionClosureCoordinator:
    """Fail-closed production adoption of BANK execution into logical N7."""

    DEFAULT_DIRECTOR_REF = "rc7-bank-mission-director-gate"
    N5_FINALIZATION_TYPE = "CASE_PREPARATION_FINALIZATION"

    def __init__(
        self,
        *,
        target_id: str,
        evidence_root: str,
        director_ref: str = DEFAULT_DIRECTOR_REF,
    ) -> None:
        self.target_id = _required(target_id, "BANK_N7_TARGET_REQUIRED")
        self.evidence_root = str(Path(evidence_root).expanduser().resolve())
        self.director_ref = _required(director_ref, "BANK_N7_DIRECTOR_REF_REQUIRED")
        self.service = AutonomousN7NodeService(evidence_root=self.evidence_root)
        self.adoption = None

    def _adoption(self, control: ClosedLoopControlPlane) -> WaveDNodeAdoptionControl:
        if self.adoption is not None:
            return self.adoption
        return WaveDNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=self.evidence_root,
        )

    @staticmethod
    def _artifact_row(
        control: ClosedLoopControlPlane,
        artifact_id: str,
        expected_type: str,
        code: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise BankN7ExecutionClosureError(code + "_NOT_UNIQUE")
        row = rows[0]
        if (
            row.get("mission_id") != control.mission_id
            or row.get("artifact_type_name") != expected_type
            or row.get("state") != "VALID"
        ):
            raise BankN7ExecutionClosureError(code + "_NOT_CURRENT")
        return row

    @staticmethod
    def _evidence_row(
        control: ClosedLoopControlPlane,
        evidence_id: str,
        *,
        expected_kind: str = "",
        code: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            raise BankN7ExecutionClosureError(code + "_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != control.mission_id:
            raise BankN7ExecutionClosureError(code + "_MISSION_MISMATCH")
        if expected_kind and row.get("kind") != expected_kind:
            raise BankN7ExecutionClosureError(code + "_KIND_MISMATCH")
        return row

    def _current_n5_finalization(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        terminal: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        attempt_id = _required(terminal.get("attempt_id"), "BANK_N7_EXECUTION_ATTEMPT_REQUIRED")
        tc_id = _required(terminal.get("tc_id"), "BANK_N7_EXECUTION_TC_REQUIRED")
        execution_task_id = _required(
            terminal.get("execution_task_id"), "BANK_N7_EXECUTION_TASK_REQUIRED"
        )
        matches = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.N5_FINALIZATION_TYPE or row.get("state") != "VALID":
                continue
            payload = _file_payload(row, "BANK_N7_N5_FINALIZATION")
            if (
                payload.get("run_id") == run_id
                and payload.get("target_id") == self.target_id
                and payload.get("attempt_id") == attempt_id
                and payload.get("tc_id") == tc_id
                and payload.get("execution_task_id") == execution_task_id
                and payload.get("status") == "PREPARED_FOR_EXECUTION"
            ):
                matches.append(payload)
        if len(matches) != 1:
            raise BankN7ExecutionClosureError(
                "BANK_N7_CURRENT_ATTEMPT_N5_FINALIZATION_REQUIRED:%s:%d" % (tc_id, len(matches))
            )
        return matches[0]

    def _validate_execution_receipt(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        receipt_id: str,
        current_design_artifact_id: str,
        current_design_content_hash: str,
    ) -> Mapping[str, Any]:
        try:
            terminal = load_execution_terminal_receipt(
                control.truth,
                mission_id=control.mission_id,
                receipt_id=receipt_id,
            )
        except ExecutionFanoutConformanceError as exc:
            raise BankN7ExecutionClosureError(
                "BANK_N7_EXECUTION_RECEIPT_INVALID:%s:%s" % (receipt_id, exc)
            ) from exc

        if terminal.get("design_artifact_id") != current_design_artifact_id:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_RECEIPT_STALE_DESIGN:%s" % receipt_id)
        if terminal.get("design_content_hash") != current_design_content_hash:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_RECEIPT_STALE_DESIGN_HASH:%s" % receipt_id)
        if terminal.get("target_id") != self.target_id:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_RECEIPT_TARGET_MISMATCH:%s" % receipt_id)

        outcome = str(terminal.get("outcome") or "").upper()
        if outcome in {"UNKNOWN", "NOT_EXECUTED", ""}:
            raise BankN7ExecutionClosureError(
                "BANK_N7_EXECUTION_RECEIPT_NOT_EXECUTED:%s:%s" % (receipt_id, outcome or "MISSING")
            )
        if outcome not in {"PASS", "PRODUCT_DEFECT"}:
            raise BankN7ExecutionClosureError(
                "BANK_N7_EXECUTION_RECEIPT_NON_TERMINAL:%s:%s" % (receipt_id, outcome)
            )

        tc_id = _required(terminal.get("tc_id"), "BANK_N7_EXECUTION_TC_REQUIRED")
        layer = _required(terminal.get("layer"), "BANK_N7_EXECUTION_LAYER_REQUIRED").upper()
        if layer not in {item.value for item in CanonicalLayer}:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_LAYER_INVALID:%s:%s" % (tc_id, layer))
        _required(terminal.get("attempt_id"), "BANK_N7_EXECUTION_ATTEMPT_REQUIRED")
        _required(terminal.get("execution_artifact_id"), "BANK_N7_EXECUTION_ARTIFACT_REQUIRED")
        _required(terminal.get("evaluation_id"), "BANK_N7_EXECUTION_EVALUATION_REQUIRED")
        _required(terminal.get("oracle_fingerprint"), "BANK_N7_EXECUTION_ORACLE_REQUIRED")
        _required(terminal.get("prepared_evidence_id"), "BANK_N7_PREPARED_EVIDENCE_REQUIRED")
        record_evidence_id = _required(
            terminal.get("record_evidence_id"), "BANK_N7_RUNTIME_RECORD_EVIDENCE_REQUIRED"
        )

        record_row = self._evidence_row(
            control,
            record_evidence_id,
            expected_kind="RUNTIME_EXECUTION_RECORD",
            code="BANK_N7_RUNTIME_RECORD_EVIDENCE",
        )
        record_payload = _file_payload(record_row, "BANK_N7_RUNTIME_RECORD")
        record = record_payload.get("record")
        if not isinstance(record, dict):
            raise BankN7ExecutionClosureError("BANK_N7_RUNTIME_RECORD_REQUIRED:%s" % tc_id)
        expected_identity = {
            "attempt_id": terminal.get("attempt_id"),
            "tc_id": tc_id,
            "case_version": terminal.get("case_version"),
            "target_id": self.target_id,
            "layer": layer,
        }
        for field, expected in expected_identity.items():
            if record.get(field) != expected:
                raise BankN7ExecutionClosureError(
                    "BANK_N7_RUNTIME_RECORD_IDENTITY_MISMATCH:%s:%s" % (tc_id, field)
                )
        if record.get("actual_result") is None:
            raise BankN7ExecutionClosureError("BANK_N7_ACTUAL_RESULT_REQUIRED:%s" % tc_id)
        if not str(record.get("assertion_ref") or "").strip():
            raise BankN7ExecutionClosureError("BANK_N7_ASSERTION_REF_REQUIRED:%s" % tc_id)
        assertion_passed = record.get("assertion_passed")
        if not isinstance(assertion_passed, bool):
            raise BankN7ExecutionClosureError("BANK_N7_ASSERTION_STATE_REQUIRED:%s" % tc_id)
        if outcome == "PASS" and (
            str(record.get("status") or "").upper() != "PASS" or assertion_passed is not True
        ):
            raise BankN7ExecutionClosureError("BANK_N7_PASS_RECEIPT_ORACLE_MISMATCH:%s" % tc_id)
        if outcome == "PRODUCT_DEFECT" and (
            str(record.get("status") or "").upper() != "FAIL" or assertion_passed is not False
        ):
            raise BankN7ExecutionClosureError("BANK_N7_PRODUCT_FAIL_ORACLE_MISMATCH:%s" % tc_id)

        # The terminal receipt itself predates logical N7 and therefore does not
        # invent a run id.  Its exact Attempt is bound to the autonomous run by
        # the already-governed N5 per-Case finalization.
        self._current_n5_finalization(control, run_id=run_id, terminal=terminal)
        return terminal

    def _validate_execution_batch(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> Tuple[Mapping[str, Any], ...]:
        try:
            barrier = check_execution_barrier(control.truth, control.mission_id)
            inventory = AcceptedCaseInventoryReader().load(control.truth, control.mission_id)
        except Exception as exc:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_BARRIER_INVALID:%s" % exc) from exc
        if barrier.status != "PASS" or barrier.missing_tc_ids or barrier.blocked_tc_ids:
            raise BankN7ExecutionClosureError(
                "BANK_N7_CURRENT_EXECUTION_RECEIPTS_INCOMPLETE:missing=%s:blocked=%s"
                % (",".join(barrier.missing_tc_ids), ",".join(barrier.blocked_tc_ids))
            )
        if barrier.design_artifact_id != inventory.design_artifact_id:
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_BARRIER_STALE_DESIGN")
        if set(barrier.required_tc_ids) != set(inventory.tc_ids):
            raise BankN7ExecutionClosureError("BANK_N7_EXECUTION_DENOMINATOR_DRIFT")
        if len(barrier.receipt_ids) != len(inventory.tc_ids):
            raise BankN7ExecutionClosureError("BANK_N7_ONE_CURRENT_RECEIPT_PER_CASE_REQUIRED")

        by_case: Dict[str, Mapping[str, Any]] = {}
        for receipt_id in barrier.receipt_ids:
            terminal = self._validate_execution_receipt(
                control,
                run_id=run_id,
                receipt_id=str(receipt_id),
                current_design_artifact_id=inventory.design_artifact_id,
                current_design_content_hash=inventory.design_content_hash,
            )
            tc_id = str(terminal["tc_id"])
            if tc_id in by_case:
                raise BankN7ExecutionClosureError("BANK_N7_DUPLICATE_CURRENT_RECEIPT:%s" % tc_id)
            by_case[tc_id] = terminal
        if set(by_case) != set(inventory.tc_ids):
            raise BankN7ExecutionClosureError("BANK_N7_CURRENT_RECEIPT_CASE_SET_MISMATCH")
        return tuple(by_case[key] for key in sorted(by_case))

    def _current_layer_receipts(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> Tuple[DurableLayerCoverageReceipt, ...]:
        receipts = []
        for layer_enum in CanonicalLayer:
            layer = layer_enum.value
            current = self.service.coverage.current_denominator(
                control,
                layer=layer,
                target_id=self.target_id,
            )
            if current is None:
                raise BankN7ExecutionClosureError("BANK_N7_CURRENT_DENOMINATOR_REQUIRED:%s" % layer)
            denominator_row = self._artifact_row(
                control,
                current.artifact_id,
                self.service.coverage.DENOMINATOR_TYPE,
                "BANK_N7_CURRENT_DENOMINATOR",
            )
            denominator_payload = _file_payload(denominator_row, "BANK_N7_CURRENT_DENOMINATOR")
            if denominator_payload.get("run_id") != run_id:
                raise BankN7ExecutionClosureError("BANK_N7_STALE_DENOMINATOR_RUN:%s" % layer)
            snapshot = denominator_payload.get("snapshot")
            if not isinstance(snapshot, dict) or snapshot.get("target_id") != self.target_id:
                raise BankN7ExecutionClosureError("BANK_N7_DENOMINATOR_TARGET_MISMATCH:%s" % layer)

            candidates = []
            for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
                if row.get("artifact_type_name") != self.service.coverage.RECEIPT_TYPE or row.get("state") != "VALID":
                    continue
                payload = _file_payload(row, "BANK_N7_LAYER_RECEIPT")
                raw = payload.get("receipt")
                if not isinstance(raw, dict):
                    continue
                if (
                    payload.get("run_id") == run_id
                    and payload.get("denominator_artifact_id") == current.artifact_id
                    and raw.get("layer") == layer
                    and raw.get("target_id") == self.target_id
                ):
                    candidates.append((int(row.get("created_at") or 0), str(row.get("artifact_id") or ""), row, payload, raw))
            if not candidates:
                raise BankN7ExecutionClosureError("BANK_N7_CURRENT_LAYER_RECEIPT_REQUIRED:%s" % layer)
            _, _, row, payload, raw = max(candidates, key=lambda item: (item[0], item[1]))
            evidence_ids = [str(x) for x in row.get("evidence_refs") or [] if str(x)]
            if len(evidence_ids) != 1:
                raise BankN7ExecutionClosureError("BANK_N7_LAYER_RECEIPT_EVIDENCE_NOT_UNIQUE:%s" % layer)
            self._evidence_row(
                control,
                evidence_ids[0],
                expected_kind="LAYER_COVERAGE_RECEIPT_RECORD",
                code="BANK_N7_LAYER_RECEIPT_EVIDENCE",
            )
            try:
                receipt = LayerCoverageReceipt(
                    layer=str(raw["layer"]),
                    source_revision=str(raw["source_revision"]),
                    target_id=str(raw["target_id"]),
                    denominator_version=str(raw["denominator_version"]),
                    denominator_hash=str(raw["denominator_hash"]),
                    covered=int(raw["covered"]),
                    total=int(raw["total"]),
                    covered_pass=int(raw["covered_pass"]),
                    covered_fail=int(raw["covered_fail"]),
                    excluded_with_evidence=int(raw["excluded_with_evidence"]),
                    open_gap_ids=tuple(str(x) for x in raw.get("open_gap_ids") or []),
                    blocked_obligation_ids=tuple(str(x) for x in raw.get("blocked_obligation_ids") or []),
                    evidence_refs=tuple(str(x) for x in raw.get("evidence_refs") or []),
                    status=str(raw["status"]),
                )
                metrics_raw = payload.get("metrics")
                if not isinstance(metrics_raw, dict):
                    raise ValueError("metrics")
                metrics = {str(key): float(value) for key, value in metrics_raw.items()}
            except (KeyError, TypeError, ValueError) as exc:
                raise BankN7ExecutionClosureError("BANK_N7_LAYER_RECEIPT_PAYLOAD_INVALID:%s" % layer) from exc
            if receipt.status != "READY":
                raise BankN7ExecutionClosureError("BANK_N7_LAYER_RECEIPT_NOT_READY:%s:%s" % (layer, receipt.status))
            if (
                receipt.denominator_version != current.snapshot.denominator_version
                or receipt.denominator_hash != current.snapshot.denominator_hash
            ):
                raise BankN7ExecutionClosureError("BANK_N7_STALE_LAYER_RECEIPT:%s" % layer)
            receipts.append(
                DurableLayerCoverageReceipt(
                    artifact_id=str(row["artifact_id"]),
                    evidence_id=evidence_ids[0],
                    receipt=receipt,
                    metrics=metrics,
                    delta_plan_artifact_id=str(payload.get("delta_plan_artifact_id") or ""),
                )
            )
        return tuple(receipts)

    @staticmethod
    def _input_version(receipts: Sequence[DurableLayerCoverageReceipt]) -> str:
        return "|".join(
            "%s:%s:%s" % (
                durable.receipt.layer,
                durable.receipt.denominator_version,
                durable.receipt.denominator_hash,
            )
            for durable in sorted(receipts, key=lambda item: item.receipt.layer)
        )

    def close_current_batch(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ):
        run_id = _required(run_id, "BANK_N7_RUN_ID_REQUIRED")
        # This is the real batch boundary.  Never close N7 from one Case/task.
        self._validate_execution_batch(control, run_id=run_id)
        receipts = self._current_layer_receipts(control, run_id=run_id)
        adoption = self._adoption(control)

        current_iteration = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N7",
        )
        current_input = self._input_version(receipts)
        terminal_current = False
        if current_iteration is not None and current_iteration.input_version == current_input:
            events = adoption.node_control._events(control.mission_id, run_id, "N7")
            terminal_current = any(
                row.get("event_type_name") == "NODE_TERMINAL"
                and row.get("data", {}).get("iteration_count") == current_iteration.iteration_count
                and row.get("data", {}).get("state") == "PASS"
                for row in events
            )

        if not terminal_current:
            try:
                self.service.publish_ready(
                    control,
                    run_id=run_id,
                    receipts=receipts,
                )
            except AutonomousN7NodeError as exc:
                raise BankN7ExecutionClosureError("BANK_N7_PUBLISH_READY_FAILED:%s" % exc) from exc

        try:
            decision = adoption.director_accept(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N7",
                director_ref=self.director_ref,
            )
        except AutonomousNodeAdoptionError as exc:
            raise BankN7ExecutionClosureError("BANK_N7_DIRECTOR_GATE_FAILED:%s" % exc) from exc
        if decision.accepted is not True or not decision.terminal_event_id:
            raise BankN7ExecutionClosureError("BANK_N7_TERMINAL_DIRECTOR_ACCEPT_REQUIRED")
        terminal_rows = control.truth.query("rc7_control_event", event_id=decision.terminal_event_id)
        if len(terminal_rows) != 1:
            raise BankN7ExecutionClosureError("BANK_N7_TERMINAL_EVENT_NOT_DURABLE")
        data = terminal_rows[0].get("data") or {}
        if data.get("run_id") != run_id or data.get("node_id") != "N7" or data.get("state") != "PASS":
            raise BankN7ExecutionClosureError("BANK_N7_TERMINAL_EVENT_IDENTITY_MISMATCH")
        return decision
