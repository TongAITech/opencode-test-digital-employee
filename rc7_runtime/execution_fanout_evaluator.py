"""Runtime-only fan-out overlay for canonical EXECUTION.

One real execution attempt concludes one accepted Case.  For Missions carrying
CASE_FANOUT_CONTRACT, the first successful Case is never allowed to collapse
the top-level EXECUTION task.  Its terminal proof is recorded, missing Cases
become deterministic EXECUTION_CASE_PENDING gaps, and their REPAIR tasks remain
Runtime-owned.  Only the final aggregate pass binds every current Case terminal
receipt.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional, Tuple

from .case_fanout_conformance import SCRIPT_READY_KIND, contract_enabled
from .case_runtime import PREPARED_ATTEMPT_KIND
from .closed_loop_control import ClosedLoopControlPlane
from .execution_fanout_conformance import (
    ExecutionFanoutConformanceError,
    check_execution_barrier,
    record_execution_terminal,
)
from .execution_loop import ExecutionLoopResult
from .models import Evaluation, EvaluationResult, Gap, GapSeverity
from .runtime_execution import VerifiedScriptExecutionBundle


class ExecutionCaseFanoutEvaluatorError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _load_file_payload(row) -> dict:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        return {}
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        return {}
    raw = path.read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != str(row.get("content_hash") or ""):
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class RuntimeCaseFanoutExecutionEvaluator:
    def __init__(self, *, state_root: str, evidence_root: str) -> None:
        self.state_root = str(Path(state_root).expanduser().resolve())
        self.evidence_root = str(Path(evidence_root).expanduser().resolve())

    def apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        bundle: VerifiedScriptExecutionBundle,
        record_evidence_id: str,
        loop_result: ExecutionLoopResult,
    ) -> ExecutionLoopResult:
        if not contract_enabled(control.truth, control.mission_id):
            return loop_result
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION":
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_FANOUT_REQUIRES_EXECUTION_TASK")
        # Inconclusive/repair outcomes are governed by the existing diagnosis
        # and recovery loop.  A terminal receipt is created only once the Case
        # itself has a conclusive runtime outcome.
        if not loop_result.conclusive:
            return loop_result

        record = self._record_from_runtime_evidence(control, record_evidence_id)
        if record.attempt_id != str(loop_result.evaluation.dimensions.get("attempt_id") or ""):
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_FANOUT_ATTEMPT_MISMATCH")
        if record.tc_id != bundle.spec.tc_id or record.case_version != bundle.spec.case_version:
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_FANOUT_BUNDLE_CASE_MISMATCH")
        script_receipt_id = self._script_receipt_id(control, bundle)
        prepared_evidence_id = self._prepared_evidence_id(
            control,
            task_id=task_id,
            attempt_id=record.attempt_id,
            tc_id=record.tc_id,
        )
        receipt_id = record_execution_terminal(
            control.truth,
            mission_id=control.mission_id,
            release_id=control.release_id,
            task_id=task_id,
            script_receipt_id=script_receipt_id,
            prepared_evidence_id=prepared_evidence_id,
            record_evidence_id=record_evidence_id,
            record=record,
            loop_result=loop_result,
            state_root=self.state_root,
            evidence_root=self.evidence_root,
        )

        # A Runtime-owned repair task corresponds to exactly one pending Case.
        # It may complete its source Gap; it never owns the aggregate barrier.
        if task.task_type == "REPAIR":
            return self._bind_receipt(loop_result, (receipt_id,), aggregate=False)

        barrier = check_execution_barrier(control.truth, control.mission_id)
        if barrier.status == "PASS":
            return self._bind_receipt(loop_result, barrier.receipt_ids, aggregate=True)

        gaps = tuple(
            Gap(
                gap_id=_stable_id(
                    "GAP-CASE-EXEC",
                    control.mission_id,
                    barrier.design_artifact_id,
                    tc_id,
                ),
                mission_id=control.mission_id,
                source_node="EXECUTION",
                category="EXECUTION_CASE_PENDING",
                severity=GapSeverity.HIGH,
                target_node="EXECUTION",
                description="Accepted Test Design Case has no pass-ready terminal execution receipt: %s" % tc_id,
                subject_refs=[barrier.design_artifact_id, tc_id],
                evidence_refs=list(dict.fromkeys([receipt_id] + list(barrier.receipt_ids))),
                acceptance_criteria=[
                    "prepare accepted Case %s through Runtime-owned preparation" % tc_id,
                    "execute Case %s with its current CASE_SCRIPT_READY receipt" % tc_id,
                    "persist actual result, Oracle outcome and CASE_EXECUTION_TERMINAL receipt",
                ],
            )
            for tc_id in barrier.missing_tc_ids
        )
        dimensions = dict(loop_result.evaluation.dimensions)
        dimensions.update(
            {
                "case_execution_fanout": "INCOMPLETE",
                "required_case_count": len(barrier.required_tc_ids),
                "pass_ready_case_count": len(barrier.pass_ready_tc_ids),
                "blocked_tc_ids": list(barrier.blocked_tc_ids),
                "missing_tc_ids": list(barrier.missing_tc_ids),
                "case_execution_receipt_ids": list(barrier.receipt_ids),
            }
        )
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-CASE-EXEC-FANOUT",
                control.mission_id,
                record.attempt_id,
                ",".join(barrier.missing_tc_ids),
            ),
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=list(loop_result.evaluation.artifact_refs),
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="rc7-runtime-case-execution-fanout-barrier",
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(
                dict.fromkeys(
                    list(loop_result.evaluation.evidence_refs)
                    + [receipt_id]
                    + list(barrier.receipt_ids)
                )
            ),
        )
        return ExecutionLoopResult(
            evaluation=evaluation,
            gaps=gaps,
            test_result=loop_result.test_result,
            conclusive=False,
            recovery_action=loop_result.recovery_action,
        )

    def _script_receipt_id(
        self,
        control: ClosedLoopControlPlane,
        bundle: VerifiedScriptExecutionBundle,
    ) -> str:
        matches = []
        for row in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            if row.get("kind") != SCRIPT_READY_KIND:
                continue
            payload = _load_file_payload(row)
            if (
                payload.get("tc_id") == bundle.spec.tc_id
                and payload.get("case_version") == bundle.spec.case_version
                and payload.get("spec_id") == bundle.spec.spec_id
                and payload.get("script_id") == bundle.script.script_id
                and payload.get("case_fingerprint") == bundle.spec.case_fingerprint
                and payload.get("oracle_fingerprint") == bundle.spec.oracle_fingerprint
            ):
                matches.append(str(row.get("evidence_id") or ""))
        matches = sorted(set(item for item in matches if item))
        if len(matches) != 1:
            raise ExecutionCaseFanoutEvaluatorError(
                "EXECUTION_CASE_SCRIPT_RECEIPT_NOT_UNIQUE:%s:%d"
                % (bundle.spec.tc_id, len(matches))
            )
        return matches[0]

    @staticmethod
    def _prepared_evidence_id(
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        attempt_id: str,
        tc_id: str,
    ) -> str:
        matches = []
        for row in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            refs = list(row.get("subject_refs") or [])
            if (
                row.get("kind") == PREPARED_ATTEMPT_KIND
                and task_id in refs
                and attempt_id in refs
                and tc_id in refs
            ):
                matches.append(str(row.get("evidence_id") or ""))
        matches = sorted(set(item for item in matches if item))
        if len(matches) != 1:
            raise ExecutionCaseFanoutEvaluatorError(
                "EXECUTION_CASE_PREPARED_EVIDENCE_NOT_UNIQUE:%s:%d" % (tc_id, len(matches))
            )
        return matches[0]

    @staticmethod
    def _record_from_runtime_evidence(control: ClosedLoopControlPlane, evidence_id: str):
        from rc6_runtime.execution import ExecutionRecord

        rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_RECORD_EVIDENCE_NOT_UNIQUE")
        payload = _load_file_payload(rows[0])
        raw = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_RECORD_PAYLOAD_REQUIRED")
        try:
            return ExecutionRecord(
                attempt_id=str(raw["attempt_id"]),
                tc_id=str(raw["tc_id"]),
                case_version=int(raw["case_version"]),
                target_id=str(raw["target_id"]),
                layer=str(raw["layer"]),
                worker_id=str(raw["worker_id"]),
                lease_id=str(raw["lease_id"]),
                status=str(raw["status"]),
                integrity_passed=bool(raw["integrity_passed"]),
                actual_result=raw.get("actual_result"),
                tool_call_refs=tuple(raw.get("tool_call_refs") or ()),
                evidence_refs=tuple(raw.get("evidence_refs") or ()),
                assertion_ref=raw.get("assertion_ref"),
                assertion_passed=raw.get("assertion_passed"),
                reason=raw.get("reason"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionCaseFanoutEvaluatorError("EXECUTION_RECORD_PAYLOAD_INVALID") from exc

    @staticmethod
    def _bind_receipt(
        loop_result: ExecutionLoopResult,
        receipt_ids: Tuple[str, ...],
        *,
        aggregate: bool,
    ) -> ExecutionLoopResult:
        evaluation = loop_result.evaluation
        dimensions = dict(evaluation.dimensions)
        dimensions["case_execution_fanout"] = "PASS" if aggregate else "CASE_TERMINAL"
        dimensions["case_execution_receipt_ids"] = list(receipt_ids)
        bound = Evaluation(
            evaluation_id=evaluation.evaluation_id,
            mission_id=evaluation.mission_id,
            node=evaluation.node,
            artifact_refs=list(evaluation.artifact_refs),
            result=evaluation.result,
            evaluator_ref=evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=list(evaluation.gap_refs),
            evidence_refs=list(dict.fromkeys(list(evaluation.evidence_refs) + list(receipt_ids))),
        )
        return replace(loop_result, evaluation=bound)
