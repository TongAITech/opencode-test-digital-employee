"""BANK production bridge from execution diagnosis to governed RC7.1 N8 recovery.

This module does not classify failures.  Runtime execution/diagnosis remains the
authority.  The bridge replays the current Attempt's immutable diagnosis evidence,
freezes the already-produced RecoveryWorkPlan into durable N8 work, and prevents
an EXECUTION/REPAIR task from directly replaying the business Case.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .autonomous_recovery_orchestrator import (
    DurableRepairWorkOrder,
    N8RecoveryOrchestrationError,
    N8RecoveryOrchestrator,
)
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .execution_recovery import RecoveryWorkPlan
from .models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    GapStatus,
    MissionStatus,
    Task,
    TaskStatus,
)
from .state_machine import transition_gap, transition_mission, transition_task
from .truth_overlay import append_entity


class BankN8RecoveryError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BankN8RecoveryError(code)
    return text


def _file_payload(row: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise BankN8RecoveryError(code + "_FILE_REQUIRED")
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise BankN8RecoveryError(code + "_FILE_MISSING")
    body = path.read_bytes()
    expected = str(row.get("content_hash") or "")
    if expected != "sha256:" + hashlib.sha256(body).hexdigest():
        raise BankN8RecoveryError(code + "_HASH_MISMATCH")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BankN8RecoveryError(code + "_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise BankN8RecoveryError(code + "_OBJECT_REQUIRED")
    return payload


@dataclass(frozen=True)
class DurableDirectRetryOrder:
    order_id: str
    source_task_id: str
    repair_task_id: str
    gap_id: str
    diagnosis_evidence_id: str
    failure_signature_id: str
    strategy_key: str
    source_attempt_id: str
    successor_attempt_id: str
    artifact_id: str
    evidence_id: str


class BankN8RecoveryCoordinator:
    """Adopt current execution failure truth into durable N8 recovery work."""

    DIRECT_ORDER_TYPE = "N8_DIRECT_RETRY_ORDER"
    DIRECT_RECEIPT_TYPE = "N8_DIRECT_RETRY_RECEIPT"
    BUDGET_BLOCK_TYPE = "N8_RECOVERY_BUDGET_BLOCK"
    DIRECT_WORKER_REF = "rc7-n8-direct-retry-authority"
    DIRECT_EVALUATOR_REF = "rc7-n8-direct-retry-independent-gate"

    def __init__(self, *, evidence_root: str, max_same_signature_direct_retries: int = 2) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.max_same_signature_direct_retries = int(max_same_signature_direct_retries)
        if self.max_same_signature_direct_retries < 1:
            raise ValueError("max_same_signature_direct_retries must be >= 1")
        self.orchestrator = N8RecoveryOrchestrator(evidence_root=str(self.evidence_root))

    @staticmethod
    def _diagnosis_evidence(control: ClosedLoopControlPlane, *, source_task_id: str, attempt_id: str, evidence_ids) -> Mapping[str, Any]:
        matches = []
        for evidence_id in evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=str(evidence_id))
            if len(rows) != 1:
                continue
            row = rows[0]
            refs = set(str(x) for x in row.get("subject_refs") or [])
            if (
                row.get("mission_id") == control.mission_id
                and row.get("kind") == "RUNTIME_FAILURE_DIAGNOSIS"
                and source_task_id in refs
                and attempt_id in refs
            ):
                matches.append(row)
        if len(matches) != 1:
            raise BankN8RecoveryError("BANK_N8_CURRENT_DIAGNOSIS_EVIDENCE_NOT_UNIQUE:%d" % len(matches))
        return matches[0]

    @staticmethod
    def _plan(payload: Mapping[str, Any], *, attempt_id: str) -> tuple[RecoveryWorkPlan, str]:
        diagnosis = payload.get("diagnosis")
        recovery = payload.get("recovery")
        raw_plan = payload.get("work_plan")
        if not isinstance(diagnosis, dict) or not isinstance(recovery, dict) or not isinstance(raw_plan, dict):
            raise BankN8RecoveryError("BANK_N8_COMPLETE_DIAGNOSIS_RECOVERY_PLAN_REQUIRED")
        try:
            plan = RecoveryWorkPlan(
                diagnosis_id=str(raw_plan["diagnosis_id"]),
                source_attempt_id=str(raw_plan["source_attempt_id"]),
                action=str(raw_plan["action"]),
                mode=str(raw_plan["mode"]),
                target_node=str(raw_plan["target_node"]),
                retry_allowed=bool(raw_plan["retry_allowed"]),
                reprepare_required=bool(raw_plan["reprepare_required"]),
                terminal=bool(raw_plan["terminal"]),
                successor_attempt_id=(str(raw_plan["successor_attempt_id"]) if raw_plan.get("successor_attempt_id") else None),
                reason=str(raw_plan["reason"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BankN8RecoveryError("BANK_N8_RECOVERY_PLAN_PAYLOAD_INVALID") from exc
        if plan.source_attempt_id != attempt_id or str(recovery.get("attempt_id") or "") != attempt_id:
            raise BankN8RecoveryError("BANK_N8_RECOVERY_ATTEMPT_MISMATCH")
        if str(recovery.get("diagnosis_id") or "") != plan.diagnosis_id:
            raise BankN8RecoveryError("BANK_N8_RECOVERY_DIAGNOSIS_MISMATCH")
        signature = diagnosis.get("failure_signature")
        if not isinstance(signature, dict):
            raise BankN8RecoveryError("BANK_N8_FAILURE_SIGNATURE_REQUIRED")
        failure_signature_id = _required(signature.get("signature_id"), "BANK_N8_FAILURE_SIGNATURE_ID_REQUIRED")
        return plan, failure_signature_id

    @staticmethod
    def _single_gap(result, plan: RecoveryWorkPlan):
        gaps = tuple(result.loop_result.gaps)
        if len(gaps) != 1:
            raise BankN8RecoveryError("BANK_N8_SINGLE_EXECUTION_GAP_REQUIRED:%d" % len(gaps))
        gap = gaps[0]
        if gap.source_node != "EXECUTION" or gap.target_node != plan.target_node:
            raise BankN8RecoveryError("BANK_N8_GAP_RECOVERY_OWNER_MISMATCH")
        return gap

    def _block_retry_budget(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        gap_id: str,
        plan: RecoveryWorkPlan,
        diagnosis_evidence_id: str,
        failure_signature_id: str,
        reason: str,
    ) -> str:
        """Persist budget exhaustion as an explicit durable Mission boundary."""
        repair_row = self._repair_task(
            control,
            gap_id=gap_id,
            target_node=plan.target_node,
        )
        if repair_row.get("state") != TaskStatus.READY.value:
            raise BankN8RecoveryError("BANK_N8_BUDGET_BLOCK_REPAIR_READY_REQUIRED")
        gap = control._gap(gap_id)
        if gap.state != GapStatus.PLANNED:
            raise BankN8RecoveryError("BANK_N8_BUDGET_BLOCK_GAP_PLANNED_REQUIRED")
        source = control.scheduler.task(source_task_id)
        if source.state != TaskStatus.REPAIR_REQUIRED:
            raise BankN8RecoveryError("BANK_N8_BUDGET_BLOCK_SOURCE_REPAIR_REQUIRED")
        successor = _required(plan.successor_attempt_id, "BANK_N8_BUDGET_BLOCK_SUCCESSOR_REQUIRED")
        if plan.mode == "DIRECT_RETRY":
            strategy_key = _stable_id("N8-DIRECT-STRATEGY", plan.action, plan.mode, plan.target_node)
            budget_limit = self.max_same_signature_direct_retries
        else:
            strategy_key = _stable_id("RECOVERY-STRATEGY", plan.action, plan.mode, plan.target_node)
            budget_limit = self.orchestrator.max_same_strategy_repairs
        payload = {
            "schema": "pfc.aitest.rc7.1.n8-recovery-budget-block.v1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "source_task_id": source_task_id,
            "repair_task_id": str(repair_row["task_id"]),
            "gap_id": gap_id,
            "diagnosis_evidence_id": diagnosis_evidence_id,
            "failure_signature_id": failure_signature_id,
            "strategy_key": strategy_key,
            "action": plan.action,
            "mode": plan.mode,
            "target_node": plan.target_node,
            "source_attempt_id": plan.source_attempt_id,
            "successor_attempt_id": successor,
            "budget_limit": budget_limit,
            "reason": reason,
            "business_action_executed": False,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        evidence_id = _stable_id(
            "EVD-N8-BUDGET-BLOCK",
            control.mission_id,
            source_task_id,
            gap_id,
            failure_signature_id,
            strategy_key,
            reason,
        )
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "budget-blocks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (evidence_id + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankN8RecoveryError("BANK_N8_BUDGET_BLOCK_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        existing = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if existing:
            if len(existing) != 1 or existing[0].get("content_hash") != "sha256:" + digest:
                raise BankN8RecoveryError("BANK_N8_BUDGET_BLOCK_EVIDENCE_CONFLICT")
        else:
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind=self.BUDGET_BLOCK_TYPE,
                    source_ref="runtime://bank-n8/recovery-budget",
                    content_ref="file://" + str(path),
                    subject_refs=[
                        source_task_id,
                        str(repair_row["task_id"]),
                        gap_id,
                        plan.source_attempt_id,
                        successor,
                        failure_signature_id,
                        strategy_key,
                    ],
                    content_hash="sha256:" + digest,
                ),
                release_id=control.release_id,
            )
        if evidence_id not in gap.evidence_refs:
            gap.evidence_refs.append(evidence_id)
        transition_gap(gap, GapStatus.BLOCKED)
        control._persist_gap(gap)
        repair_task = control.scheduler.task(str(repair_row["task_id"]))
        transition_task(repair_task, TaskStatus.BLOCKED)
        control.scheduler.persist_evaluated_task(repair_task)
        mission = control._mission()
        if mission.state != MissionStatus.BLOCKED:
            if mission.state not in {MissionStatus.RUNNING, MissionStatus.REPAIRING, MissionStatus.EVALUATING}:
                raise BankN8RecoveryError(
                    "BANK_N8_BUDGET_BLOCK_MISSION_STATE_INVALID:%s" % mission.state.value
                )
            transition_mission(mission, MissionStatus.BLOCKED)
        control._sync_mission(mission)
        return evidence_id

    def capture_after_execution(self, control: ClosedLoopControlPlane, *, source_task_id: str, result):
        """Freeze current REPAIR_REQUIRED diagnosis into durable N8 work."""
        if result.loop_result.evaluation.result != EvaluationResult.REPAIR_REQUIRED:
            return None
        attempt_id = _required(result.execution_record.attempt_id, "BANK_N8_SOURCE_ATTEMPT_REQUIRED")
        row = self._diagnosis_evidence(
            control,
            source_task_id=source_task_id,
            attempt_id=attempt_id,
            evidence_ids=result.evidence_ids,
        )
        payload = _file_payload(row, "BANK_N8_DIAGNOSIS")
        plan, failure_signature_id = self._plan(payload, attempt_id=attempt_id)
        if plan.terminal or not plan.retry_allowed or not plan.successor_attempt_id:
            raise BankN8RecoveryError("BANK_N8_REPAIR_REQUIRED_MUST_HAVE_RETRYABLE_PLAN")
        gap = self._single_gap(result, plan)
        if plan.mode == "DIRECT_RETRY":
            try:
                return self._create_direct_retry_order(
                    control,
                    source_task_id=source_task_id,
                    gap_id=gap.gap_id,
                    plan=plan,
                    diagnosis_evidence_id=str(row["evidence_id"]),
                    failure_signature_id=failure_signature_id,
                )
            except BankN8RecoveryError as exc:
                if str(exc) != "BANK_N8_DIRECT_RETRY_BUDGET_EXHAUSTED":
                    raise
                return self._block_retry_budget(
                    control,
                    source_task_id=source_task_id,
                    gap_id=gap.gap_id,
                    plan=plan,
                    diagnosis_evidence_id=str(row["evidence_id"]),
                    failure_signature_id=failure_signature_id,
                    reason=str(exc),
                )
        if plan.mode in {"REPREPARE_THEN_RETRY", "UPSTREAM_REPAIR_THEN_RETRY"}:
            try:
                return self.orchestrator.create_work_order(
                    control,
                    source_task_id=source_task_id,
                    gap_id=gap.gap_id,
                    plan=plan,
                    diagnosis_evidence_id=str(row["evidence_id"]),
                    failure_signature_id=failure_signature_id,
                )
            except N8RecoveryOrchestrationError as exc:
                if str(exc) == "SAME_FAILURE_SIGNATURE_STRATEGY_BUDGET_EXHAUSTED":
                    return self._block_retry_budget(
                        control,
                        source_task_id=source_task_id,
                        gap_id=gap.gap_id,
                        plan=plan,
                        diagnosis_evidence_id=str(row["evidence_id"]),
                        failure_signature_id=failure_signature_id,
                        reason=str(exc),
                    )
                raise BankN8RecoveryError("BANK_N8_WORK_ORDER_FAILED:%s" % exc) from exc
        raise BankN8RecoveryError("BANK_N8_RECOVERY_MODE_UNSUPPORTED:%s" % plan.mode)

    @staticmethod
    def _repair_task(control: ClosedLoopControlPlane, *, gap_id: str, target_node: str) -> Mapping[str, Any]:
        rows = [
            row for row in control.truth.query("rc7_task", mission_id=control.mission_id)
            if row.get("task_type") == "REPAIR"
            and row.get("node") == target_node
            and row.get("gap_refs") == [gap_id]
        ]
        if len(rows) != 1:
            raise BankN8RecoveryError("BANK_N8_REPAIR_TASK_NOT_UNIQUE:%d" % len(rows))
        return rows[0]

    def _create_direct_retry_order(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        gap_id: str,
        plan: RecoveryWorkPlan,
        diagnosis_evidence_id: str,
        failure_signature_id: str,
    ) -> DurableDirectRetryOrder:
        if plan.mode != "DIRECT_RETRY" or plan.target_node != "EXECUTION":
            raise BankN8RecoveryError("BANK_N8_DIRECT_RETRY_PLAN_REQUIRED")
        repair = self._repair_task(control, gap_id=gap_id, target_node="EXECUTION")
        if repair.get("state") != TaskStatus.READY.value:
            raise BankN8RecoveryError("BANK_N8_DIRECT_REPAIR_TASK_READY_REQUIRED")
        strategy_key = _stable_id("N8-DIRECT-STRATEGY", plan.action, plan.mode, plan.target_node)
        prior = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == self.DIRECT_RECEIPT_TYPE
            and failure_signature_id in set(row.get("subject_refs") or [])
            and strategy_key in set(row.get("subject_refs") or [])
        ]
        if len(prior) >= self.max_same_signature_direct_retries:
            raise BankN8RecoveryError("BANK_N8_DIRECT_RETRY_BUDGET_EXHAUSTED")
        successor = _required(plan.successor_attempt_id, "BANK_N8_DIRECT_SUCCESSOR_REQUIRED")
        order_id = _stable_id(
            "N8-DIRECT-ORDER", control.mission_id, source_task_id, gap_id,
            plan.source_attempt_id, successor, strategy_key,
        )
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "order_id": order_id,
            "source_task_id": source_task_id,
            "repair_task_id": str(repair["task_id"]),
            "gap_id": gap_id,
            "diagnosis_evidence_id": diagnosis_evidence_id,
            "failure_signature_id": failure_signature_id,
            "strategy_key": strategy_key,
            "plan": asdict(plan),
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "direct-orders"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (order_id + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankN8RecoveryError("BANK_N8_DIRECT_ORDER_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N8-DIRECT-ORDER", order_id, digest)
        artifact_id = _stable_id("ART-N8-DIRECT-ORDER", order_id, digest)
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind=self.DIRECT_ORDER_TYPE,
                    source_ref="runtime://bank-n8/direct-retry-order",
                    content_ref="file://" + str(path),
                    subject_refs=[source_task_id, str(repair["task_id"]), gap_id, plan.source_attempt_id, successor, failure_signature_id, strategy_key],
                    content_hash="sha256:" + digest,
                ),
                release_id=control.release_id,
            )
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(
                control.truth,
                Artifact(
                    artifact_id=artifact_id,
                    mission_id=control.mission_id,
                    artifact_type=self.DIRECT_ORDER_TYPE,
                    producer_task_id=source_task_id,
                    content_ref="file://" + str(path),
                    evidence_refs=[evidence_id, diagnosis_evidence_id],
                    content_hash="sha256:" + digest,
                ),
                release_id=control.release_id,
            )
        return DurableDirectRetryOrder(
            order_id=order_id,
            source_task_id=source_task_id,
            repair_task_id=str(repair["task_id"]),
            gap_id=gap_id,
            diagnosis_evidence_id=diagnosis_evidence_id,
            failure_signature_id=failure_signature_id,
            strategy_key=strategy_key,
            source_attempt_id=plan.source_attempt_id,
            successor_attempt_id=successor,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
        )

    def _direct_order_for_repair(self, control: ClosedLoopControlPlane, task: Task) -> tuple[DurableDirectRetryOrder, RecoveryWorkPlan]:
        candidates = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.DIRECT_ORDER_TYPE or row.get("state") != "VALID":
                continue
            payload = _file_payload(row, "BANK_N8_DIRECT_ORDER")
            if payload.get("repair_task_id") == task.task_id and payload.get("gap_id") in task.gap_refs:
                candidates.append((row, payload))
        if len(candidates) != 1:
            raise BankN8RecoveryError("BANK_N8_DIRECT_ORDER_NOT_UNIQUE:%d" % len(candidates))
        row, payload = candidates[0]
        raw_plan = payload.get("plan")
        if not isinstance(raw_plan, dict):
            raise BankN8RecoveryError("BANK_N8_DIRECT_ORDER_PLAN_REQUIRED")
        plan = RecoveryWorkPlan(
            diagnosis_id=str(raw_plan["diagnosis_id"]),
            source_attempt_id=str(raw_plan["source_attempt_id"]),
            action=str(raw_plan["action"]),
            mode=str(raw_plan["mode"]),
            target_node=str(raw_plan["target_node"]),
            retry_allowed=bool(raw_plan["retry_allowed"]),
            reprepare_required=bool(raw_plan["reprepare_required"]),
            terminal=bool(raw_plan["terminal"]),
            successor_attempt_id=(str(raw_plan["successor_attempt_id"]) if raw_plan.get("successor_attempt_id") else None),
            reason=str(raw_plan["reason"]),
        )
        evidence_refs = [str(x) for x in row.get("evidence_refs") or [] if str(x)]
        order_evidence = next((x for x in evidence_refs if x.startswith("EVD-N8-DIRECT-ORDER")), "")
        return DurableDirectRetryOrder(
            order_id=str(payload["order_id"]),
            source_task_id=str(payload["source_task_id"]),
            repair_task_id=str(payload["repair_task_id"]),
            gap_id=str(payload["gap_id"]),
            diagnosis_evidence_id=str(payload["diagnosis_evidence_id"]),
            failure_signature_id=str(payload["failure_signature_id"]),
            strategy_key=str(payload["strategy_key"]),
            source_attempt_id=plan.source_attempt_id,
            successor_attempt_id=_required(plan.successor_attempt_id, "BANK_N8_DIRECT_SUCCESSOR_REQUIRED"),
            artifact_id=str(row["artifact_id"]),
            evidence_id=order_evidence,
        ), plan

    def handle_execution_repair(self, control: ClosedLoopControlPlane, task: Task) -> str:
        """Complete EXECUTION/REPAIR as retry authorization, never business execution."""
        if task.node != "EXECUTION" or task.task_type != "REPAIR":
            raise BankN8RecoveryError("BANK_N8_EXECUTION_REPAIR_TASK_REQUIRED")
        order, plan = self._direct_order_for_repair(control, task)
        if plan.mode != "DIRECT_RETRY" or plan.terminal or not plan.retry_allowed:
            raise BankN8RecoveryError("BANK_N8_DIRECT_RETRY_AUTHORIZATION_INVALID")
        gap_rows = control.truth.query("rc7_gap", gap_id=order.gap_id)
        if len(gap_rows) != 1 or gap_rows[0].get("state") != GapStatus.PLANNED.value:
            raise BankN8RecoveryError("BANK_N8_DIRECT_GAP_PLANNED_REQUIRED")
        leased = control.lease_next(worker_ref=self.DIRECT_WORKER_REF, capabilities=("test_execution",))
        if leased is None or leased.task_id != task.task_id:
            raise BankN8RecoveryError("BANK_N8_DIRECT_REPAIR_LEASE_MISMATCH")
        control.start(task.task_id, worker_ref=self.DIRECT_WORKER_REF)
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "order_id": order.order_id,
            "source_task_id": order.source_task_id,
            "repair_task_id": task.task_id,
            "gap_id": order.gap_id,
            "source_attempt_id": order.source_attempt_id,
            "successor_attempt_id": order.successor_attempt_id,
            "failure_signature_id": order.failure_signature_id,
            "strategy_key": order.strategy_key,
            "action": plan.action,
            "mode": plan.mode,
            "business_action_executed": False,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "direct-receipts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (order.order_id + "-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankN8RecoveryError("BANK_N8_DIRECT_RECEIPT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N8-DIRECT-RECEIPT", order.order_id, digest)
        artifact_id = _stable_id("ART-N8-DIRECT-RECEIPT", order.order_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.DIRECT_RECEIPT_TYPE,
            source_ref="runtime://bank-n8/direct-retry-authorization",
            content_ref="file://" + str(path),
            subject_refs=[order.order_id, order.source_task_id, task.task_id, order.gap_id, order.source_attempt_id, order.successor_attempt_id, order.failure_signature_id, order.strategy_key],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.DIRECT_RECEIPT_TYPE,
            producer_task_id=task.task_id,
            content_ref="file://" + str(path),
            parent_refs=[order.artifact_id],
            evidence_refs=[evidence_id, order.evidence_id, order.diagnosis_evidence_id],
            content_hash="sha256:" + digest,
        )
        control.submit_worker_output(
            WorkerOutput(task_id=task.task_id, worker_ref=self.DIRECT_WORKER_REF, artifacts=(artifact,), evidence=(evidence,))
        )
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-N8-DIRECT-RETRY", order.order_id, digest),
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=self.DIRECT_EVALUATOR_REF,
            dimensions={
                "n8_direct_retry_authorized": True,
                "source_attempt_id": order.source_attempt_id,
                "successor_attempt_id": order.successor_attempt_id,
                "failure_signature_id": order.failure_signature_id,
                "business_action_executed": False,
            },
            evidence_refs=[evidence_id, order.diagnosis_evidence_id],
        )
        control.accept_evaluation(task.task_id, evaluation=evaluation)
        return order.successor_attempt_id
