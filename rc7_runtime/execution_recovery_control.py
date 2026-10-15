"""Control-plane consumption of DIRECT_RETRY recovery plans.

Direct retry is not a hidden while-loop.  A failed Execution Task first creates
an ordinary Gap and an EXECUTION/REPAIR ownership Task.  This controller may
auto-complete only that narrow repair task when an evidence-backed
RecoveryWorkPlan authorizes DIRECT_RETRY.  Existing ClosedLoopControlPlane then
moves the Gap to EVIDENCE_PENDING and reactivates the original Execution Task.
The caller receives exactly one successor PreparedAttempt and must use its new
attempt id for the next execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from rc6_runtime.preparation import PreparedAttempt

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .execution_recovery import ExecutionRecoveryPlanner, RecoveryWorkPlan
from .models import Artifact, Evaluation, EvaluationResult, Evidence, TaskStatus


class RecoveryControlError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DirectRetryAuthorization:
    source_task_id: str
    repair_task_id: str
    gap_id: str
    plan_artifact_id: str
    plan_evidence_id: str
    successor_attempt_id: str
    prepared: PreparedAttempt


class ExecutionRecoveryController:
    WORKER_REF = "rc7-runtime-recovery-worker"
    EVALUATOR_REF = "rc7-runtime-recovery-gate"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).resolve()

    def authorize_direct_retry(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
        gap_id: str,
        plan: RecoveryWorkPlan,
        prepared: PreparedAttempt,
        diagnosis_evidence_id: Optional[str] = None,
    ) -> DirectRetryAuthorization:
        if plan.mode != "DIRECT_RETRY" or plan.target_node != "EXECUTION":
            raise RecoveryControlError("DIRECT_RETRY_PLAN_REQUIRED")
        if not plan.retry_allowed or plan.terminal or plan.reprepare_required:
            raise RecoveryControlError("DIRECT_RETRY_PLAN_FLAGS_INVALID")
        if not plan.successor_attempt_id:
            raise RecoveryControlError("DIRECT_RETRY_SUCCESSOR_REQUIRED")
        if prepared.attempt_id != plan.source_attempt_id:
            raise RecoveryControlError("DIRECT_RETRY_SOURCE_ATTEMPT_MISMATCH")

        source = control.scheduler.task(source_task_id)
        if source.node != "EXECUTION" or source.state != TaskStatus.REPAIR_REQUIRED:
            raise RecoveryControlError("DIRECT_RETRY_SOURCE_TASK_NOT_REPAIR_REQUIRED")
        if gap_id not in source.gap_refs:
            raise RecoveryControlError("DIRECT_RETRY_GAP_NOT_OWNED_BY_SOURCE")

        gap_rows = control.truth.query("rc7_gap", gap_id=gap_id)
        if len(gap_rows) != 1:
            raise RecoveryControlError("DIRECT_RETRY_GAP_NOT_UNIQUE")
        gap = gap_rows[0]
        if gap.get("mission_id") != control.mission_id:
            raise RecoveryControlError("DIRECT_RETRY_GAP_MISSION_MISMATCH")
        if gap.get("source_node") != "EXECUTION" or gap.get("target_node") != "EXECUTION":
            raise RecoveryControlError("DIRECT_RETRY_GAP_ROUTE_INVALID")
        if gap.get("category") not in {"TRANSIENT_FAILURE", "FLAKY_SUSPECTED"}:
            raise RecoveryControlError("DIRECT_RETRY_GAP_CATEGORY_INVALID")
        if gap.get("state") != "PLANNED":
            raise RecoveryControlError("DIRECT_RETRY_GAP_NOT_PLANNED")

        repair_rows = [
            row
            for row in control.truth.query("rc7_task", mission_id=control.mission_id)
            if row.get("node") == "EXECUTION"
            and row.get("task_type") == "REPAIR"
            and row.get("gap_refs") == [gap_id]
        ]
        if len(repair_rows) != 1:
            raise RecoveryControlError("DIRECT_RETRY_REPAIR_TASK_NOT_UNIQUE")
        repair_task_id = str(repair_rows[0]["task_id"])
        repair = control.scheduler.task(repair_task_id)
        if repair.state != TaskStatus.READY:
            raise RecoveryControlError("DIRECT_RETRY_REPAIR_TASK_NOT_READY")

        eligible = [
            item
            for item in control.scheduler.ready_tasks(control.mission_id)
            if set(item.required_capabilities).issubset({"test_execution"})
        ]
        if not eligible or eligible[0].task_id != repair_task_id:
            raise RecoveryControlError("DIRECT_RETRY_REPAIR_TASK_NOT_NEXT_READY")
        leased = control.lease_next(
            worker_ref=self.WORKER_REF,
            capabilities=("test_execution",),
        )
        if leased is None or leased.task_id != repair_task_id:
            raise RecoveryControlError("DIRECT_RETRY_REPAIR_LEASE_MISMATCH")
        control.start(repair_task_id, worker_ref=self.WORKER_REF)

        folder = self.evidence_root / "recovery-plans" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (gap_id + ".json")
        payload = {
            "mission_id": control.mission_id,
            "source_task_id": source_task_id,
            "repair_task_id": repair_task_id,
            "gap_id": gap_id,
            "plan": asdict(plan),
            "diagnosis_evidence_id": diagnosis_evidence_id,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        path.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        evidence_id = _stable_id("EVD-RECOVERY-PLAN", control.mission_id, gap_id, digest)
        artifact_id = _stable_id("ART-RECOVERY-PLAN", control.mission_id, gap_id, digest)
        evidence_refs = [evidence_id]
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind="RECOVERY_WORK_PLAN",
            source_ref="runtime://execution-recovery-controller",
            content_ref="file://" + str(path),
            subject_refs=[source_task_id, repair_task_id, gap_id, plan.source_attempt_id, plan.successor_attempt_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type="RECOVERY_WORK_PLAN",
            producer_task_id=repair_task_id,
            content_ref="file://" + str(path),
            evidence_refs=evidence_refs,
            content_hash="sha256:" + digest,
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=repair_task_id,
                worker_ref=self.WORKER_REF,
                artifacts=(artifact,),
                evidence=(evidence,),
            )
        )
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-RECOVERY-PLAN", control.mission_id, gap_id, digest),
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=self.EVALUATOR_REF,
            dimensions={
                "recovery_action": plan.action,
                "recovery_mode": plan.mode,
                "source_attempt_id": plan.source_attempt_id,
                "successor_attempt_id": plan.successor_attempt_id,
                "retry_allowed": True,
                "reprepare_required": False,
            },
            evidence_refs=evidence_refs,
        )
        control.accept_evaluation(repair_task_id, evaluation=evaluation)

        reactivated = control.scheduler.task(source_task_id)
        if reactivated.state != TaskStatus.READY:
            raise RecoveryControlError("DIRECT_RETRY_SOURCE_TASK_NOT_REACTIVATED")
        gap_after = control.truth.query("rc7_gap", gap_id=gap_id)[0]
        if gap_after.get("state") != "EVIDENCE_PENDING":
            raise RecoveryControlError("DIRECT_RETRY_GAP_NOT_EVIDENCE_PENDING")

        successor = ExecutionRecoveryPlanner.compile_successor_prepared_attempt(prepared, plan)
        return DirectRetryAuthorization(
            source_task_id=source_task_id,
            repair_task_id=repair_task_id,
            gap_id=gap_id,
            plan_artifact_id=artifact_id,
            plan_evidence_id=evidence_id,
            successor_attempt_id=plan.successor_attempt_id,
            prepared=successor,
        )

    @staticmethod
    def verify_successor(
        authorization: DirectRetryAuthorization,
        prepared: PreparedAttempt,
    ) -> None:
        if prepared.attempt_id != authorization.successor_attempt_id:
            raise RecoveryControlError("UNAUTHORIZED_RETRY_ATTEMPT_ID")
        if prepared != authorization.prepared:
            raise RecoveryControlError("UNAUTHORIZED_RETRY_PREPARATION_DRIFT")
