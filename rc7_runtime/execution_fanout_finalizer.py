"""Receipt-only finalization for RC7.1 Case Execution Fanout.

The per-Case workers already performed the business side effects. Once every
accepted Case has a trustworthy terminal receipt, the canonical EXECUTION task
must not run one of those Cases again merely to turn the parent green.

This finalizer consumes only canonical R1 receipts, writes an immutable
aggregate conclusion and evaluates the canonical EXECUTION task. It never
invokes a test runner, browser, API, provider, database or other field tool.
That makes finalization restart-safe and prevents confirmed/uncertain business
side effects from being replayed after the final sibling repair completes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

from .case_fanout_conformance import contract_enabled, contract_row
from .control_plane import WorkerOutput
from .execution_fanout_conformance import (
    ExecutionFanoutConformanceError,
    check_execution_barrier,
    deferred_product_defect_gaps,
)
from .models import Artifact, Evidence, Evaluation, EvaluationResult, TaskStatus
from .state_machine import transition_task


AGGREGATE_EVIDENCE_KIND = "CASE_EXECUTION_AGGREGATE"
AGGREGATE_SCHEMA_VERSION = "pfc.aitest.rc7.case-execution-aggregate.v1"
AGGREGATOR_WORKER = "runtime://case-fanout/receipt-aggregator"
AGGREGATOR_EVALUATOR = "rc7-runtime-case-execution-fanout-barrier"


class ExecutionFanoutFinalizeError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


@dataclass(frozen=True)
class FanoutFinalizeResult:
    status: str
    source_task_id: Optional[str]
    evaluation_id: Optional[str]
    receipt_ids: Tuple[str, ...] = ()
    reason: Optional[str] = None


class ReceiptOnlyExecutionFanoutFinalizer:
    """Close the canonical EXECUTION task from durable per-Case receipts."""

    def __init__(self, *, evidence_root: str) -> None:
        if not evidence_root:
            raise ExecutionFanoutFinalizeError("EVIDENCE_ROOT_REQUIRED")
        self.evidence_root = str(evidence_root)

    def try_finalize(self, control) -> FanoutFinalizeResult:
        truth = control.truth
        mission_id = control.mission_id
        if not contract_enabled(truth, mission_id):
            return FanoutFinalizeResult("NOT_APPLICABLE", None, None, reason="CASE_FANOUT_DISABLED")

        try:
            barrier = check_execution_barrier(truth, mission_id)
        except ExecutionFanoutConformanceError as exc:
            raise ExecutionFanoutFinalizeError(str(exc)) from exc
        if barrier.status != "PASS":
            return FanoutFinalizeResult(
                "NOT_READY",
                self._source_task_id(control),
                None,
                receipt_ids=barrier.receipt_ids,
                reason="EXECUTION_BARRIER_%s" % barrier.status,
            )

        source_task_id = self._source_task_id(control)
        source = control.scheduler.task(source_task_id)
        if source.state == TaskStatus.PASS:
            return FanoutFinalizeResult(
                "ALREADY_FINALIZED",
                source_task_id,
                source.evaluation_id,
                receipt_ids=barrier.receipt_ids,
            )
        if source.state != TaskStatus.READY:
            return FanoutFinalizeResult(
                "NOT_READY",
                source_task_id,
                None,
                receipt_ids=barrier.receipt_ids,
                reason="SOURCE_TASK_%s" % source.state.value,
            )

        # Exact controller-owned lease. We intentionally do not use lease_next:
        # finalization must never lease an unrelated READY task and it is not a
        # business test execution. The source identity comes from the immutable
        # CASE_FANOUT_CONTRACT and the barrier has already validated every
        # terminal receipt against the current accepted design.
        row = control.scheduler._required_row(source_task_id)
        transition_task(source, TaskStatus.LEASED, lease_owner=AGGREGATOR_WORKER)
        control.scheduler._persist_task(source, int(row["artifact_version"]) + 1)
        control.start(source_task_id, worker_ref=AGGREGATOR_WORKER)

        evidence, artifact = self._aggregate_output(control, source_task_id, barrier)
        control.submit_worker_output(
            WorkerOutput(
                task_id=source_task_id,
                worker_ref=AGGREGATOR_WORKER,
                artifacts=(artifact,),
                evidence=(evidence,),
            )
        )

        deferred = deferred_product_defect_gaps(
            truth,
            mission_id=mission_id,
            receipt_ids=barrier.receipt_ids,
        )
        evaluation_id = _stable_id(
            "EVAL-EXEC-FANOUT",
            mission_id,
            barrier.design_artifact_id,
            evidence.content_hash or "",
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=mission_id,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=AGGREGATOR_EVALUATOR,
            dimensions={
                "case_execution_fanout": "PASS",
                "receipt_only_aggregate": True,
                "runner_reexecuted": False,
                "business_side_effect_replayed": False,
                "design_artifact_id": barrier.design_artifact_id,
                "required_tc_ids": list(barrier.required_tc_ids),
                "pass_ready_tc_ids": list(barrier.pass_ready_tc_ids),
                "terminal_receipt_ids": list(barrier.receipt_ids),
                "required_case_count": len(barrier.required_tc_ids),
                "terminal_case_count": len(barrier.pass_ready_tc_ids),
            },
            gap_refs=[gap.gap_id for gap in deferred],
            evidence_refs=[evidence.evidence_id] + list(barrier.receipt_ids),
        )
        accepted = control.accept_evaluation(
            source_task_id,
            evaluation=evaluation,
            gaps=deferred,
        )
        if accepted.state != TaskStatus.PASS:
            raise ExecutionFanoutFinalizeError("CANONICAL_EXECUTION_NOT_PASS_AFTER_AGGREGATE")
        return FanoutFinalizeResult(
            "FINALIZED",
            source_task_id,
            evaluation_id,
            receipt_ids=barrier.receipt_ids,
        )

    def _source_task_id(self, control) -> str:
        row = contract_row(control.truth, control.mission_id)
        if row is None:
            raise ExecutionFanoutFinalizeError("CASE_FANOUT_CONTRACT_REQUIRED")
        candidates = []
        for ref in list(row.get("subject_refs") or []):
            task_rows = control.truth.query("rc7_task", task_id=str(ref))
            if len(task_rows) != 1:
                continue
            task_row = task_rows[0]
            if (
                task_row.get("mission_id") == control.mission_id
                and task_row.get("node") == "EXECUTION"
                and task_row.get("task_type") != "REPAIR"
            ):
                candidates.append(str(ref))
        candidates = sorted(set(candidates))
        if len(candidates) != 1:
            raise ExecutionFanoutFinalizeError("CANONICAL_EXECUTION_TASK_NOT_UNIQUE")
        return candidates[0]

    def _aggregate_output(self, control, source_task_id: str, barrier):
        payload = {
            "schema_version": AGGREGATE_SCHEMA_VERSION,
            "mission_id": control.mission_id,
            "source_task_id": source_task_id,
            "design_artifact_id": barrier.design_artifact_id,
            "required_tc_ids": list(barrier.required_tc_ids),
            "pass_ready_tc_ids": list(barrier.pass_ready_tc_ids),
            "blocked_tc_ids": list(barrier.blocked_tc_ids),
            "missing_tc_ids": list(barrier.missing_tc_ids),
            "terminal_receipt_ids": list(barrier.receipt_ids),
            "aggregate_status": barrier.status,
            "source": "canonical_r1_terminal_receipts",
            "receipt_only_aggregate": True,
            "runner_reexecuted": False,
            "business_side_effect_replayed": False,
        }
        body = _canonical(payload)
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        evidence_id = _stable_id(
            "EVD-EXEC-FANOUT-AGG",
            control.mission_id,
            barrier.design_artifact_id,
            digest,
        )
        artifact_id = _stable_id(
            "ART-EXEC-FANOUT-AGG",
            control.mission_id,
            barrier.design_artifact_id,
            digest,
        )
        folder = (
            Path(self.evidence_root).expanduser().resolve()
            / "case-fanout"
            / control.mission_id
            / "aggregate"
        )
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (evidence_id + ".json")
        if path.exists() and path.read_bytes() != body:
            raise ExecutionFanoutFinalizeError("CASE_EXECUTION_AGGREGATE_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)

        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=AGGREGATE_EVIDENCE_KIND,
            source_ref="runtime://case-fanout/receipt-aggregate",
            content_ref="file://" + str(path),
            subject_refs=[
                source_task_id,
                barrier.design_artifact_id,
            ] + list(barrier.required_tc_ids) + list(barrier.receipt_ids),
            content_hash=digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=source_task_id,
            content_ref="file://" + str(path),
            parent_refs=[barrier.design_artifact_id],
            evidence_refs=[evidence_id] + list(barrier.receipt_ids),
            content_hash=digest,
        )
        return evidence, artifact
