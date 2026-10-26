"""RC7.1 N8 durable orchestration for non-direct recovery.

Runtime diagnosis decides ownership and recovery. This module never performs the
repair itself. It records a durable RepairWorkOrder, verifies that the original
owner completed an independently evaluated REPAIR task with an evidence-backed
delta, and only then authorizes a new successor execution attempt.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional

from rc6_runtime.preparation import PreparedAttempt

from .closed_loop_control import ClosedLoopControlPlane
from .execution_recovery import ExecutionRecoveryPlanner, RecoveryWorkPlan
from .models import Artifact, Evidence, TaskStatus
from .truth_overlay import append_entity


class N8RecoveryOrchestrationError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise N8RecoveryOrchestrationError(code)
    return text


@dataclass(frozen=True)
class DurableRepairWorkOrder:
    work_order_id: str
    source_task_id: str
    repair_task_id: str
    gap_id: str
    diagnosis_evidence_id: str
    diagnosis_id: str
    source_attempt_id: str
    successor_attempt_id: str
    failure_signature_id: str
    strategy_key: str
    mode: str
    target_node: str
    reprepare_required: bool
    artifact_id: str
    evidence_id: str
    content_hash: str
    budget_scope_id: str = ""


@dataclass(frozen=True)
class RecoverySuccessorAuthorization:
    work_order_id: str
    source_task_id: str
    repair_task_id: str
    gap_id: str
    successor_attempt_id: str
    repair_receipt_artifact_id: str
    repair_receipt_evidence_id: str
    delta_fingerprint: str
    prepared: PreparedAttempt


class N8RecoveryOrchestrator:
    WORK_ORDER_TYPE = "N8_REPAIR_WORK_ORDER"
    RECEIPT_TYPE = "N8_REPAIR_RECEIPT"

    def __init__(self, *, evidence_root: str, max_same_strategy_repairs: int = 2) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.max_same_strategy_repairs = int(max_same_strategy_repairs)
        if self.max_same_strategy_repairs < 1:
            raise ValueError("max_same_strategy_repairs must be >= 1")

    def create_work_order(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        gap_id: str,
        plan: RecoveryWorkPlan,
        diagnosis_evidence_id: str,
        failure_signature_id: str,
        budget_scope_id: Optional[str] = None,
    ) -> DurableRepairWorkOrder:
        if plan.mode not in {"REPREPARE_THEN_RETRY", "UPSTREAM_REPAIR_THEN_RETRY"}:
            raise N8RecoveryOrchestrationError("N8_NON_DIRECT_RECOVERY_PLAN_REQUIRED")
        if not plan.retry_allowed or plan.terminal:
            raise N8RecoveryOrchestrationError("N8_RETRYABLE_NON_TERMINAL_PLAN_REQUIRED")
        successor_attempt_id = _required(plan.successor_attempt_id, "N8_SUCCESSOR_ATTEMPT_REQUIRED")
        if successor_attempt_id == plan.source_attempt_id:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_ATTEMPT_MUST_BE_NEW")
        failure_signature_id = _required(failure_signature_id, "N8_FAILURE_SIGNATURE_REQUIRED")
        explicit_budget_scope = bool(str(budget_scope_id or "").strip())
        resolved_budget_scope = _required(
            budget_scope_id or _stable_id("N8-RECOVERY-SCOPE", source_task_id),
            "N8_BUDGET_SCOPE_REQUIRED",
        )

        diagnosis = self._one(
            control,
            "rc7_evidence",
            "evidence_id",
            diagnosis_evidence_id,
            "N8_DIAGNOSIS_EVIDENCE_NOT_UNIQUE",
        )
        if diagnosis.get("mission_id") != control.mission_id:
            raise N8RecoveryOrchestrationError("N8_DIAGNOSIS_MISSION_MISMATCH")
        if diagnosis.get("kind") != "RUNTIME_FAILURE_DIAGNOSIS":
            raise N8RecoveryOrchestrationError("N8_RUNTIME_DIAGNOSIS_EVIDENCE_REQUIRED")
        if plan.source_attempt_id not in set(diagnosis.get("subject_refs", [])):
            raise N8RecoveryOrchestrationError("N8_DIAGNOSIS_ATTEMPT_NOT_PROVEN")

        source = control.scheduler.task(source_task_id)
        if source.node != "EXECUTION" or source.state != TaskStatus.REPAIR_REQUIRED:
            raise N8RecoveryOrchestrationError("N8_SOURCE_EXECUTION_REPAIR_REQUIRED")
        if gap_id not in source.gap_refs:
            raise N8RecoveryOrchestrationError("N8_SOURCE_GAP_OWNERSHIP_MISMATCH")

        gap = self._one(control, "rc7_gap", "gap_id", gap_id, "N8_RECOVERY_GAP_NOT_UNIQUE")
        if gap.get("mission_id") != control.mission_id:
            raise N8RecoveryOrchestrationError("N8_GAP_MISSION_MISMATCH")
        if gap.get("source_node") != "EXECUTION":
            raise N8RecoveryOrchestrationError("N8_GAP_SOURCE_EXECUTION_REQUIRED")
        if gap.get("target_node") != plan.target_node:
            raise N8RecoveryOrchestrationError("N8_RECOVERY_OWNER_PLAN_MISMATCH")
        if gap.get("state") != "PLANNED":
            raise N8RecoveryOrchestrationError("N8_RECOVERY_GAP_MUST_BE_PLANNED")

        repair_rows = [
            row
            for row in control.truth.query("rc7_task", mission_id=control.mission_id)
            if row.get("task_type") == "REPAIR"
            and row.get("node") == plan.target_node
            and row.get("gap_refs") == [gap_id]
        ]
        if len(repair_rows) != 1:
            raise N8RecoveryOrchestrationError("N8_REPAIR_OWNER_TASK_NOT_UNIQUE")
        repair_task_id = str(repair_rows[0]["task_id"])
        if repair_rows[0].get("state") != TaskStatus.READY.value:
            raise N8RecoveryOrchestrationError("N8_REPAIR_OWNER_TASK_NOT_READY")

        strategy_key = _stable_id("RECOVERY-STRATEGY", plan.action, plan.mode, plan.target_node)
        prior = [
            row
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == self.RECEIPT_TYPE
            and failure_signature_id in set(row.get("subject_refs", []))
            and strategy_key in set(row.get("subject_refs", []))
            and (
                not explicit_budget_scope
                or resolved_budget_scope in set(row.get("subject_refs", []))
            )
        ]
        if len(prior) >= self.max_same_strategy_repairs:
            raise N8RecoveryOrchestrationError("SAME_FAILURE_SIGNATURE_STRATEGY_BUDGET_EXHAUSTED")

        work_order_id = _stable_id(
            "N8-WORK-ORDER",
            control.mission_id,
            source_task_id,
            gap_id,
            plan.diagnosis_id,
            plan.source_attempt_id,
            successor_attempt_id,
            strategy_key,
            resolved_budget_scope,
        )
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "work_order_id": work_order_id,
            "source_task_id": source_task_id,
            "repair_task_id": repair_task_id,
            "gap_id": gap_id,
            "diagnosis_evidence_id": diagnosis_evidence_id,
            "failure_signature_id": failure_signature_id,
            "strategy_key": strategy_key,
            "budget_scope_id": resolved_budget_scope,
            "plan": asdict(plan),
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "work-orders"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (work_order_id + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence_id = _stable_id("EVD-N8-WORK-ORDER", work_order_id, digest)
        artifact_id = _stable_id("ART-N8-WORK-ORDER", work_order_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.WORK_ORDER_TYPE,
            source_ref="runtime://n8-recovery-orchestrator",
            content_ref="file://" + str(path),
            subject_refs=[
                source_task_id,
                repair_task_id,
                gap_id,
                plan.source_attempt_id,
                successor_attempt_id,
                failure_signature_id,
                strategy_key,
                resolved_budget_scope,
            ],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.WORK_ORDER_TYPE,
            producer_task_id=source_task_id,
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id, diagnosis_evidence_id],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)

        return DurableRepairWorkOrder(
            work_order_id=work_order_id,
            source_task_id=source_task_id,
            repair_task_id=repair_task_id,
            gap_id=gap_id,
            diagnosis_evidence_id=diagnosis_evidence_id,
            diagnosis_id=plan.diagnosis_id,
            source_attempt_id=plan.source_attempt_id,
            successor_attempt_id=successor_attempt_id,
            failure_signature_id=failure_signature_id,
            strategy_key=strategy_key,
            mode=plan.mode,
            target_node=plan.target_node,
            reprepare_required=bool(plan.reprepare_required),
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            content_hash="sha256:" + digest,
            budget_scope_id=resolved_budget_scope,
        )

    def accept_repair_receipt(
        self,
        control: ClosedLoopControlPlane,
        *,
        work_order: DurableRepairWorkOrder,
        plan: RecoveryWorkPlan,
        prepared_before: PreparedAttempt,
        successor_prepared: Optional[PreparedAttempt] = None,
    ) -> RecoverySuccessorAuthorization:
        self._require_work_order_current(control, work_order, plan)
        if prepared_before.attempt_id != work_order.source_attempt_id:
            raise N8RecoveryOrchestrationError("N8_REPAIR_SOURCE_PREPARED_ATTEMPT_MISMATCH")

        repair_task = control.scheduler.task(work_order.repair_task_id)
        if repair_task.state != TaskStatus.PASS:
            raise N8RecoveryOrchestrationError("N8_OWNER_REPAIR_TASK_PASS_REQUIRED")
        if repair_task.node != work_order.target_node:
            raise N8RecoveryOrchestrationError("N8_OWNER_REPAIR_TASK_NODE_MISMATCH")
        gap = self._one(control, "rc7_gap", "gap_id", work_order.gap_id, "N8_REPAIR_GAP_NOT_UNIQUE")
        if gap.get("state") != "EVIDENCE_PENDING":
            raise N8RecoveryOrchestrationError("N8_REPAIR_GAP_EVIDENCE_PENDING_REQUIRED")
        if control.scheduler.task(work_order.source_task_id).state != TaskStatus.READY:
            raise N8RecoveryOrchestrationError("N8_SOURCE_TASK_MUST_BE_REACTIVATED")

        evaluation_id = _required(repair_task.evaluation_id, "N8_OWNER_REPAIR_EVALUATION_REQUIRED")
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "N8_OWNER_REPAIR_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("result") != "PASS" or evaluation.get("node") != repair_task.node:
            raise N8RecoveryOrchestrationError("N8_OWNER_REPAIR_PASS_EVALUATION_REQUIRED")
        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, dict):
            raise N8RecoveryOrchestrationError("N8_REPAIR_EVALUATION_DIMENSIONS_REQUIRED")
        if dimensions.get("repair_work_order_id") != work_order.work_order_id:
            raise N8RecoveryOrchestrationError("N8_REPAIR_WORK_ORDER_BINDING_MISMATCH")
        before = _required(dimensions.get("repair_before_fingerprint"), "N8_REPAIR_BEFORE_FINGERPRINT_REQUIRED")
        after = _required(dimensions.get("repair_after_fingerprint"), "N8_REPAIR_AFTER_FINGERPRINT_REQUIRED")
        if before == after:
            raise N8RecoveryOrchestrationError("SAME_FAILURE_SIGNATURE_NO_DELTA")
        raw_delta_refs = dimensions.get("repair_delta_refs")
        if not isinstance(raw_delta_refs, list) or not raw_delta_refs:
            raise N8RecoveryOrchestrationError("N8_REPAIR_DELTA_EVIDENCE_REQUIRED")
        delta_refs = tuple(dict.fromkeys(_required(ref, "N8_REPAIR_DELTA_EVIDENCE_REQUIRED") for ref in raw_delta_refs))
        evaluation_evidence = set(evaluation.get("evidence_refs", []))
        if not set(delta_refs).issubset(evaluation_evidence):
            raise N8RecoveryOrchestrationError("N8_REPAIR_DELTA_NOT_BOUND_TO_EVALUATION")
        for evidence_id in delta_refs:
            row = self._one(
                control,
                "rc7_evidence",
                "evidence_id",
                evidence_id,
                "N8_REPAIR_DELTA_EVIDENCE_NOT_UNIQUE",
            )
            if row.get("mission_id") != control.mission_id:
                raise N8RecoveryOrchestrationError("N8_REPAIR_DELTA_EVIDENCE_MISSION_MISMATCH")

        repeated = [
            row
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == self.RECEIPT_TYPE
            and work_order.failure_signature_id in set(row.get("subject_refs", []))
            and work_order.strategy_key in set(row.get("subject_refs", []))
            and (
                not work_order.budget_scope_id
                or work_order.budget_scope_id in set(row.get("subject_refs", []))
            )
            and after in set(row.get("subject_refs", []))
        ]
        if repeated:
            raise N8RecoveryOrchestrationError("SAME_FAILURE_SIGNATURE_SAME_STRATEGY_NO_NEW_DELTA")

        if work_order.reprepare_required:
            if successor_prepared is None:
                raise N8RecoveryOrchestrationError("N8_REPREPARE_SUCCESSOR_REQUIRED")
            prepared = successor_prepared
            self._require_durable_successor_prepared(control, work_order=work_order, prepared=prepared)
        else:
            prepared = ExecutionRecoveryPlanner.compile_successor_prepared_attempt(prepared_before, plan)
            if successor_prepared is not None and successor_prepared != prepared:
                raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARATION_DRIFT")

        if prepared.attempt_id != work_order.successor_attempt_id:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_ATTEMPT_ID_MISMATCH")

        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "work_order_id": work_order.work_order_id,
            "source_task_id": work_order.source_task_id,
            "repair_task_id": work_order.repair_task_id,
            "gap_id": work_order.gap_id,
            "failure_signature_id": work_order.failure_signature_id,
            "strategy_key": work_order.strategy_key,
            "budget_scope_id": work_order.budget_scope_id,
            "repair_evaluation_id": evaluation_id,
            "repair_before_fingerprint": before,
            "repair_after_fingerprint": after,
            "repair_delta_refs": list(delta_refs),
            "successor_attempt_id": prepared.attempt_id,
            "reprepare_required": work_order.reprepare_required,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "receipts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (work_order.work_order_id + "-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise N8RecoveryOrchestrationError("N8_REPAIR_RECEIPT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence_id = _stable_id("EVD-N8-REPAIR-RECEIPT", work_order.work_order_id, digest)
        artifact_id = _stable_id("ART-N8-REPAIR-RECEIPT", work_order.work_order_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.RECEIPT_TYPE,
            source_ref="runtime://n8-recovery-orchestrator",
            content_ref="file://" + str(path),
            subject_refs=[
                work_order.work_order_id,
                work_order.source_task_id,
                work_order.repair_task_id,
                work_order.gap_id,
                work_order.failure_signature_id,
                work_order.strategy_key,
                work_order.budget_scope_id,
                after,
                prepared.attempt_id,
            ],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.RECEIPT_TYPE,
            producer_task_id=work_order.repair_task_id,
            content_ref="file://" + str(path),
            parent_refs=[work_order.artifact_id] + list(repair_task.output_artifact_refs),
            evidence_refs=[evidence_id] + list(delta_refs),
            content_hash="sha256:" + digest,
        )
        append_entity(control.truth, evidence, release_id=control.release_id)
        append_entity(control.truth, artifact, release_id=control.release_id)

        return RecoverySuccessorAuthorization(
            work_order_id=work_order.work_order_id,
            source_task_id=work_order.source_task_id,
            repair_task_id=work_order.repair_task_id,
            gap_id=work_order.gap_id,
            successor_attempt_id=prepared.attempt_id,
            repair_receipt_artifact_id=artifact_id,
            repair_receipt_evidence_id=evidence_id,
            delta_fingerprint=after,
            prepared=prepared,
        )

    @staticmethod
    def verify_successor(authorization: RecoverySuccessorAuthorization, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id != authorization.successor_attempt_id:
            raise N8RecoveryOrchestrationError("N8_UNAUTHORIZED_SUCCESSOR_ATTEMPT")
        if prepared != authorization.prepared:
            raise N8RecoveryOrchestrationError("N8_UNAUTHORIZED_SUCCESSOR_PREPARATION_DRIFT")

    def _require_work_order_current(
        self,
        control: ClosedLoopControlPlane,
        work_order: DurableRepairWorkOrder,
        plan: RecoveryWorkPlan,
    ) -> None:
        if plan.diagnosis_id != work_order.diagnosis_id:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_DIAGNOSIS_MISMATCH")
        if plan.source_attempt_id != work_order.source_attempt_id:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_SOURCE_ATTEMPT_MISMATCH")
        if plan.successor_attempt_id != work_order.successor_attempt_id:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_SUCCESSOR_MISMATCH")
        if plan.mode != work_order.mode or plan.target_node != work_order.target_node:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_PLAN_DRIFT")
        artifact = self._one(
            control,
            "rc7_artifact",
            "artifact_id",
            work_order.artifact_id,
            "N8_WORK_ORDER_ARTIFACT_NOT_UNIQUE",
        )
        evidence = self._one(
            control,
            "rc7_evidence",
            "evidence_id",
            work_order.evidence_id,
            "N8_WORK_ORDER_EVIDENCE_NOT_UNIQUE",
        )
        if artifact.get("mission_id") != control.mission_id or evidence.get("mission_id") != control.mission_id:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_MISSION_MISMATCH")
        if artifact.get("artifact_type_name") != self.WORK_ORDER_TYPE or evidence.get("kind") != self.WORK_ORDER_TYPE:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_TYPE_MISMATCH")
        if work_order.budget_scope_id and work_order.budget_scope_id not in set(evidence.get("subject_refs", [])):
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_BUDGET_SCOPE_MISMATCH")
        content_ref = artifact.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_CONTENT_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_CONTENT_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if artifact.get("content_hash") != "sha256:" + digest or evidence.get("content_hash") != "sha256:" + digest:
            raise N8RecoveryOrchestrationError("N8_WORK_ORDER_CONTENT_HASH_MISMATCH")
        if work_order.budget_scope_id:
            try:
                durable = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise N8RecoveryOrchestrationError("N8_WORK_ORDER_CONTENT_INVALID") from exc
            if durable.get("budget_scope_id") != work_order.budget_scope_id:
                raise N8RecoveryOrchestrationError("N8_WORK_ORDER_BUDGET_SCOPE_CONTENT_MISMATCH")

    def _require_durable_successor_prepared(
        self,
        control: ClosedLoopControlPlane,
        *,
        work_order: DurableRepairWorkOrder,
        prepared: PreparedAttempt,
    ) -> None:
        if prepared.status != "PREPARED":
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_STATUS_REQUIRED")
        if prepared.attempt_id != work_order.successor_attempt_id:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_ATTEMPT_ID_MISMATCH")
        artifact_id = _stable_id("ART-PREPARED", control.mission_id, work_order.source_task_id, prepared.attempt_id)
        row = self._one(
            control,
            "rc7_artifact",
            "artifact_id",
            artifact_id,
            "N8_SUCCESSOR_PREPARED_ARTIFACT_NOT_UNIQUE",
        )
        if row.get("mission_id") != control.mission_id:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_MISSION_MISMATCH")
        if row.get("artifact_type_name") != "PREPARED_ATTEMPT":
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_ARTIFACT_REQUIRED")
        if row.get("producer_task_id") != work_order.source_task_id:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_TASK_MISMATCH")
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_CONTENT_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_CONTENT_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_CONTENT_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
            durable = payload["prepared"]
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_CONTENT_INVALID") from exc
        if (
            durable.get("attempt_id") != prepared.attempt_id
            or durable.get("tc_id") != prepared.tc_id
            or int(durable.get("case_version")) != prepared.case_version
            or durable.get("target_id") != prepared.target_id
            or durable.get("status") != "PREPARED"
        ):
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_CONTENT_DRIFT")
        evidence_refs = list(row.get("evidence_refs", []))
        if not evidence_refs:
            raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_EVIDENCE_REQUIRED")
        for evidence_id in evidence_refs:
            evidence = self._one(
                control,
                "rc7_evidence",
                "evidence_id",
                evidence_id,
                "N8_SUCCESSOR_PREPARED_EVIDENCE_NOT_UNIQUE",
            )
            if evidence.get("mission_id") != control.mission_id:
                raise N8RecoveryOrchestrationError("N8_SUCCESSOR_PREPARED_EVIDENCE_MISSION_MISMATCH")

    @staticmethod
    def _one(
        control: ClosedLoopControlPlane,
        entity_type: str,
        field: str,
        value: str,
        code: str,
    ) -> Mapping[str, object]:
        rows = control.truth.query(entity_type, **{field: value})
        if len(rows) != 1:
            raise N8RecoveryOrchestrationError(code)
        return rows[0]
