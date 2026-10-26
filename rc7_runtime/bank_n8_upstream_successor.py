"""BANK N8 successor closure for non-direct owner repair.

UPSTREAM_REPAIR_THEN_RETRY is authorized while the source EXECUTION task is still
READY, then materialized after the source is leased and before business execution.
REPREPARE_THEN_RETRY is handled only after the source is leased: the coordinator
re-runs the canonical CasePreparationService for the successor Attempt, persists
its canonical PreparedAttempt artifact, accepts the independently evaluated owner
repair receipt, and only then returns the fresh successor preparation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.preparation import PreparedAttempt

from .autonomous_recovery_orchestrator import (
    DurableRepairWorkOrder,
    N8RecoveryOrchestrationError,
    N8RecoveryOrchestrator,
    RecoverySuccessorAuthorization,
)
from .bank_n8_recovery import BankN8RecoveryError, _file_payload
from .bank_n8_successor import BankN8SuccessorCoordinator
from .candidate_payload import CandidatePayloadReader
from .case_fanout_conformance import AcceptedCaseInventoryReader
from .case_runtime import (
    PREPARED_ATTEMPT_KIND,
    CasePreparationService,
    _mission_release,
    _state_ref,
    _write_immutable_json,
)
from .closed_loop_control import ClosedLoopControlPlane
from .execution_recovery import ExecutionRecoveryPlanner, RecoveryWorkPlan
from .models import Artifact, Evidence, GapStatus, TaskStatus
from .truth_overlay import append_entity


class BankN8UpstreamSuccessorError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class BankN8UpstreamSuccessorCoordinator:
    """Authorize and materialize non-direct N8 successors before business execution."""

    SUCCESSOR_SOURCE_REF = "runtime://bank-n8/upstream-repair-successor"
    REPREPARE_SOURCE_REF = "runtime://case-runtime/preparation"

    def __init__(
        self,
        *,
        state_root: str,
        evidence_root: str,
        provider_config: Optional[str] = None,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.provider_config = (
            Path(provider_config).expanduser().resolve() if provider_config else None
        )
        self.orchestrator = N8RecoveryOrchestrator(evidence_root=str(self.evidence_root))
        self.prepared_reader = BankN8SuccessorCoordinator(state_root=str(self.state_root))
        self.inventory = AcceptedCaseInventoryReader()
        self.candidate_reader = CandidatePayloadReader()

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
            if plan.mode not in {"UPSTREAM_REPAIR_THEN_RETRY", "REPREPARE_THEN_RETRY"}:
                continue
            if plan.mode == "UPSTREAM_REPAIR_THEN_RETRY" and plan.reprepare_required:
                raise BankN8UpstreamSuccessorError("BANK_N8_UPSTREAM_REPREPARE_MODE_DRIFT")
            if plan.mode == "REPREPARE_THEN_RETRY" and not plan.reprepare_required:
                raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_MODE_DRIFT")
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
                reprepare_required=bool(plan.reprepare_required),
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
        if plan.mode == "REPREPARE_THEN_RETRY":
            return None
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

    def _accepted_case(
        self,
        control: ClosedLoopControlPlane,
        *,
        tc_id: str,
    ) -> Dict[str, Any]:
        inventory = self.inventory.load(control.truth, control.mission_id)
        candidate = self.candidate_reader.load(
            control.truth,
            inventory.design_artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=inventory.design_task_id,
        )
        raw_cases = candidate.semantic_payload.get("cases")
        if not isinstance(raw_cases, list):
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_ACCEPTED_CASES_REQUIRED")
        matches = [dict(row) for row in raw_cases if isinstance(row, dict) and str(row.get("tc_id") or "") == tc_id]
        if len(matches) != 1:
            raise BankN8UpstreamSuccessorError(
                "BANK_N8_REPREPARE_ACCEPTED_CASE_NOT_UNIQUE:%s:%d" % (tc_id, len(matches))
            )
        return matches[0]

    def _persist_canonical_prepared_artifact(
        self,
        control: ClosedLoopControlPlane,
        *,
        work_order: DurableRepairWorkOrder,
        prepared: PreparedAttempt,
        preparation_evidence_id: str,
    ) -> str:
        payload = {
            "work_order_id": work_order.work_order_id,
            "prepared": asdict(prepared),
            "preparation_evidence_id": preparation_evidence_id,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "reprepare-prepared"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (prepared.attempt_id + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_CANONICAL_PREPARED_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        artifact_id = _stable_id(
            "ART-PREPARED",
            control.mission_id,
            work_order.source_task_id,
            prepared.attempt_id,
        )
        existing = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if existing:
            if (
                len(existing) != 1
                or existing[0].get("content_hash") != "sha256:" + digest
                or existing[0].get("content_ref") != "file://" + str(path)
            ):
                raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_CANONICAL_PREPARED_ARTIFACT_CONFLICT")
            return artifact_id
        append_entity(
            control.truth,
            Artifact(
                artifact_id=artifact_id,
                mission_id=control.mission_id,
                artifact_type="PREPARED_ATTEMPT",
                producer_task_id=work_order.source_task_id,
                content_ref="file://" + str(path),
                evidence_refs=[preparation_evidence_id, work_order.evidence_id],
                content_hash="sha256:" + digest,
            ),
            release_id=control.release_id,
        )
        return artifact_id

    def _accept_reprepare_receipt_leased(
        self,
        control: ClosedLoopControlPlane,
        *,
        work_order: DurableRepairWorkOrder,
        plan: RecoveryWorkPlan,
        prepared_before: PreparedAttempt,
        successor_prepared: PreparedAttempt,
        worker_id: str,
    ) -> RecoverySuccessorAuthorization:
        self.orchestrator._require_work_order_current(control, work_order, plan)
        if prepared_before.attempt_id != work_order.source_attempt_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SOURCE_PREPARED_ATTEMPT_MISMATCH")
        repair_task = control.scheduler.task(work_order.repair_task_id)
        if repair_task.state != TaskStatus.PASS or repair_task.node != work_order.target_node:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_OWNER_REPAIR_PASS_REQUIRED")
        gap = self.orchestrator._one(
            control,
            "rc7_gap",
            "gap_id",
            work_order.gap_id,
            "BANK_N8_REPREPARE_GAP_NOT_UNIQUE",
        )
        if gap.get("state") != GapStatus.EVIDENCE_PENDING.value:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_GAP_EVIDENCE_PENDING_REQUIRED")
        source = control.scheduler.task(work_order.source_task_id)
        if source.state != TaskStatus.LEASED or source.lease_owner != worker_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SOURCE_LEASE_REQUIRED")

        evaluation_id = str(repair_task.evaluation_id or "").strip()
        if not evaluation_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_OWNER_EVALUATION_REQUIRED")
        evaluation = self.orchestrator._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "BANK_N8_REPREPARE_OWNER_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("result") != "PASS" or evaluation.get("node") != repair_task.node:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_OWNER_PASS_EVALUATION_REQUIRED")
        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, dict):
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_EVALUATION_DIMENSIONS_REQUIRED")
        if dimensions.get("repair_work_order_id") != work_order.work_order_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_WORK_ORDER_BINDING_MISMATCH")
        before = str(dimensions.get("repair_before_fingerprint") or "").strip()
        after = str(dimensions.get("repair_after_fingerprint") or "").strip()
        if not before or not after:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_FINGERPRINT_REQUIRED")
        if before == after:
            raise BankN8UpstreamSuccessorError("SAME_FAILURE_SIGNATURE_NO_DELTA")
        raw_delta_refs = dimensions.get("repair_delta_refs")
        if not isinstance(raw_delta_refs, list) or not raw_delta_refs:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_DELTA_EVIDENCE_REQUIRED")
        delta_refs = tuple(dict.fromkeys(str(ref).strip() for ref in raw_delta_refs if str(ref).strip()))
        if not delta_refs:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_DELTA_EVIDENCE_REQUIRED")
        evaluation_evidence = set(str(x) for x in evaluation.get("evidence_refs") or [])
        if not set(delta_refs).issubset(evaluation_evidence):
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_DELTA_NOT_BOUND_TO_EVALUATION")
        for evidence_id in delta_refs:
            row = self.orchestrator._one(
                control,
                "rc7_evidence",
                "evidence_id",
                evidence_id,
                "BANK_N8_REPREPARE_DELTA_EVIDENCE_NOT_UNIQUE",
            )
            if row.get("mission_id") != control.mission_id:
                raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_DELTA_EVIDENCE_MISSION_MISMATCH")

        repeated = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
            and work_order.failure_signature_id in set(row.get("subject_refs") or [])
            and work_order.strategy_key in set(row.get("subject_refs") or [])
            and after in set(row.get("subject_refs") or [])
        ]
        if repeated:
            raise BankN8UpstreamSuccessorError("SAME_FAILURE_SIGNATURE_SAME_STRATEGY_NO_NEW_DELTA")

        try:
            self.orchestrator._require_durable_successor_prepared(
                control,
                work_order=work_order,
                prepared=successor_prepared,
            )
        except N8RecoveryOrchestrationError as exc:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SUCCESSOR_INVALID:%s" % exc) from exc
        if successor_prepared.attempt_id != work_order.successor_attempt_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SUCCESSOR_ATTEMPT_MISMATCH")

        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "work_order_id": work_order.work_order_id,
            "source_task_id": work_order.source_task_id,
            "repair_task_id": work_order.repair_task_id,
            "gap_id": work_order.gap_id,
            "failure_signature_id": work_order.failure_signature_id,
            "strategy_key": work_order.strategy_key,
            "repair_evaluation_id": evaluation_id,
            "repair_before_fingerprint": before,
            "repair_after_fingerprint": after,
            "repair_delta_refs": list(delta_refs),
            "successor_attempt_id": successor_prepared.attempt_id,
            "reprepare_required": True,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n8-recovery" / control.mission_id / "receipts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (work_order.work_order_id + "-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_RECEIPT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N8-REPAIR-RECEIPT", work_order.work_order_id, digest)
        artifact_id = _stable_id("ART-N8-REPAIR-RECEIPT", work_order.work_order_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=N8RecoveryOrchestrator.RECEIPT_TYPE,
            source_ref="runtime://bank-n8/reprepare-receipt-gate",
            content_ref="file://" + str(path),
            subject_refs=[
                work_order.work_order_id,
                work_order.source_task_id,
                work_order.repair_task_id,
                work_order.gap_id,
                work_order.failure_signature_id,
                work_order.strategy_key,
                after,
                successor_prepared.attempt_id,
            ],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=N8RecoveryOrchestrator.RECEIPT_TYPE,
            producer_task_id=work_order.repair_task_id,
            content_ref="file://" + str(path),
            parent_refs=[work_order.artifact_id] + list(repair_task.output_artifact_refs),
            evidence_refs=[evidence_id] + list(delta_refs),
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return RecoverySuccessorAuthorization(
            work_order_id=work_order.work_order_id,
            source_task_id=work_order.source_task_id,
            repair_task_id=work_order.repair_task_id,
            gap_id=work_order.gap_id,
            successor_attempt_id=successor_prepared.attempt_id,
            repair_receipt_artifact_id=artifact_id,
            repair_receipt_evidence_id=evidence_id,
            delta_fingerprint=after,
            prepared=successor_prepared,
        )

    def _materialize_reprepare(
        self,
        control: ClosedLoopControlPlane,
        *,
        work_order: DurableRepairWorkOrder,
        plan: RecoveryWorkPlan,
        worker_id: str,
        tc_id: str,
        target_id: str,
    ) -> Dict[str, Any]:
        task = control.scheduler.task(work_order.source_task_id)
        if task.state != TaskStatus.LEASED or task.lease_owner != worker_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SOURCE_LEASE_REQUIRED")
        receipt = self._receipt_for_work_order(control, work_order.work_order_id)
        successor_attempt = work_order.successor_attempt_id
        if receipt is not None:
            durable = self.prepared_reader._source_prepared(
                control,
                source_task_id=work_order.source_task_id,
                source_attempt_id=successor_attempt,
                tc_id=tc_id,
                target_id=target_id,
            )
            prepared_rows = [
                row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
                if row.get("kind") == PREPARED_ATTEMPT_KIND
                and self.prepared_reader._prepared_identity_matches(
                    row,
                    source_task_id=work_order.source_task_id,
                    attempt_id=successor_attempt,
                    tc_id=tc_id,
                )
            ]
            if len(prepared_rows) != 1:
                raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SUCCESSOR_PREPARED_NOT_UNIQUE")
            return {
                "status": "PREPARED",
                "prepared_attempt": asdict(durable),
                "evidence_id": str(prepared_rows[0]["evidence_id"]),
                "replayed": True,
                "n8_successor": True,
                "n8_reprepare": True,
                "authorization_evidence_id": str(receipt["evidence_id"]),
                "source_attempt_id": work_order.source_attempt_id,
            }

        frozen_case = self._accepted_case(control, tc_id=tc_id)
        preparation = CasePreparationService(
            control.truth,
            self.state_root,
            provider_config=self.provider_config,
        )
        result = preparation.prepare(
            mission_id=control.mission_id,
            task_id=work_order.source_task_id,
            worker_id=worker_id,
            case=frozen_case,
            attempt_id=successor_attempt,
            target_id=target_id,
        )
        if result.get("status") != "PREPARED":
            return result
        prepared = self.prepared_reader._prepared_from_payload(result["prepared_attempt"])
        if prepared.attempt_id != successor_attempt or prepared.tc_id != tc_id or prepared.target_id != target_id:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_PREPARED_IDENTITY_MISMATCH")
        self._persist_canonical_prepared_artifact(
            control,
            work_order=work_order,
            prepared=prepared,
            preparation_evidence_id=str(result["evidence_id"]),
        )
        prepared_before = self.prepared_reader._source_prepared(
            control,
            source_task_id=work_order.source_task_id,
            source_attempt_id=work_order.source_attempt_id,
            tc_id=tc_id,
            target_id=target_id,
        )
        authorization = self._accept_reprepare_receipt_leased(
            control,
            work_order=work_order,
            plan=plan,
            prepared_before=prepared_before,
            successor_prepared=prepared,
            worker_id=worker_id,
        )
        try:
            N8RecoveryOrchestrator.verify_successor(authorization, prepared)
        except N8RecoveryOrchestrationError as exc:
            raise BankN8UpstreamSuccessorError("BANK_N8_REPREPARE_SUCCESSOR_VERIFY_FAILED:%s" % exc) from exc
        result = dict(result)
        result.update(
            {
                "n8_successor": True,
                "n8_reprepare": True,
                "authorization_evidence_id": authorization.repair_receipt_evidence_id,
                "source_attempt_id": work_order.source_attempt_id,
            }
        )
        return result

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
        if plan.mode == "REPREPARE_THEN_RETRY":
            return self._materialize_reprepare(
                control,
                work_order=work_order,
                plan=plan,
                worker_id=worker_id,
                tc_id=tc_id,
                target_id=target_id,
            )

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
