"""RC7.1 N5 autonomous preparation closure.

This module does not replace the existing PreparationRuntime / CaseRuntime.
It adds the missing autonomous-node lifecycle around their immutable truth:

Batch planning -> per-attempt reservation -> freshness verification -> current
PreparedAttempt -> Runtime sufficiency -> NodeDelivery -> Director acceptance.

A batch plan is explicitly non-execution proof.  Every execution attempt still
requires its own current PreparedAttempt and final Runtime gate.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.preparation import PreparationSpecParser

from .autonomous_contract import NodeDeliveryPackage, NodeLoopState, require_node
from .autonomous_node_adoption import AutonomousNodeAdoptionControl, AutonomousNodeAdoptionError
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, Evaluation, EvaluationResult, Evidence, Task, TaskStatus
from .preparation_control import RuntimePreparedAttempt
from .truth_overlay import append_entity


class AutonomousPreparationNodeError(RuntimeError):
    pass


class WaveCNodeAdoptionControl(AutonomousNodeAdoptionControl):
    """Extend the shared adoption gate to Wave-C logical nodes without drift."""

    @staticmethod
    def source_node(node_id: str) -> str:
        node_id = require_node(node_id).value
        if node_id == "N5":
            return "TEST_DATA_PREPARATION"
        if node_id == "N6":
            return "SCRIPT_READINESS"
        return AutonomousNodeAdoptionControl.source_node(node_id)


@dataclass(frozen=True)
class BatchPreparationPlanReceipt:
    artifact_id: str
    evidence_id: str
    plan_hash: str
    target_id: str
    case_hashes: Tuple[str, ...]


@dataclass(frozen=True)
class ResourceReservationReceipt:
    artifact_id: str
    evidence_id: str
    reservation_id: str
    binding_hash: str
    mode: str


@dataclass(frozen=True)
class FreshnessReceipt:
    evidence_id: str
    binding_hash: str
    verified_at: int


@dataclass(frozen=True)
class N5PreparationReady:
    task_id: str
    evaluation_id: str
    finalization_artifact_id: str
    finalization_evidence_id: str
    delivery_artifact_id: str
    delivery_evidence_id: str
    ready_event_id: str


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class AutonomousPreparationNodeService:
    BATCH_TYPE = "PREPARATION_BATCH_PLAN"
    RESERVATION_TYPE = "PREPARATION_RESOURCE_RESERVATION"
    FINALIZATION_TYPE = "CASE_PREPARATION_FINALIZATION"
    FRESHNESS_KIND = "PREPARATION_FRESHNESS_CHECK"

    def __init__(self, *, evidence_root: str, max_freshness_seconds: int = 300) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.max_freshness_seconds = max(1, int(max_freshness_seconds))
        self.parser = PreparationSpecParser()

    def create_batch_plan(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        target_id: str,
        cases: Sequence[Mapping[str, Any]],
        producer_task_ids: Sequence[str],
    ) -> BatchPreparationPlanReceipt:
        run_id = self._required(run_id, "N5_RUN_ID_REQUIRED")
        target_id = self._required(target_id, "N5_TARGET_ID_REQUIRED")
        if not cases:
            raise AutonomousPreparationNodeError("N5_BATCH_CASES_REQUIRED")
        task_ids = tuple(dict.fromkeys(self._required(x, "N5_EXECUTION_TASK_ID_REQUIRED") for x in producer_task_ids))
        if not task_ids:
            raise AutonomousPreparationNodeError("N5_EXECUTION_TASKS_REQUIRED")
        for task_id in task_ids:
            self._require_execution_task(control, task_id)

        case_entries = []
        demand = {"precondition_types": {}, "initial_state": 0, "input_data": 0}
        for raw_case in cases:
            case = dict(raw_case)
            plan = self.parser.parse(case)
            case_hash = _sha(case)
            case_entries.append({
                "tc_id": plan.tc_id,
                "case_version": plan.case_version,
                "layer": plan.layer,
                "case_hash": case_hash,
                "precondition_ids": [x["id"] for x in plan.preconditions],
                "data_requirement_ids": [x["id"] for x in plan.initial_state_requirements + plan.input_data_requirements],
            })
            for pre in plan.preconditions:
                ptype = str(pre["type"])
                demand["precondition_types"][ptype] = int(demand["precondition_types"].get(ptype, 0)) + 1
            demand["initial_state"] += len(plan.initial_state_requirements)
            demand["input_data"] += len(plan.input_data_requirements)

        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "target_id": target_id,
            "cases": case_entries,
            "demand": demand,
            "producer_task_ids": list(task_ids),
            "execution_proof": False,
            "status": "PLANNED",
        }
        artifact_id, evidence_id, digest = self._persist_artifact(
            control,
            artifact_type=self.BATCH_TYPE,
            producer_task_id=task_ids[0],
            payload=payload,
            parent_refs=[],
            evidence_kind="PREPARATION_BATCH_PLAN_RECORD",
            subject_refs=[run_id, target_id] + list(task_ids),
            relative=Path("n5") / control.mission_id / run_id / "batch-plan.json",
        )
        return BatchPreparationPlanReceipt(
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            plan_hash=digest,
            target_id=target_id,
            case_hashes=tuple(item["case_hash"] for item in case_entries),
        )

    def reserve_prepared_bindings(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        prepared: RuntimePreparedAttempt,
        mode: str = "EXCLUSIVE",
    ) -> ResourceReservationReceipt:
        self._require_execution_task(control, execution_task_id)
        mode = str(mode or "").strip().upper()
        if mode not in {"EXCLUSIVE", "SHARED_READONLY"}:
            raise AutonomousPreparationNodeError("N5_RESERVATION_MODE_INVALID")
        self._require_prepared_artifact(control, execution_task_id, prepared)
        binding_payload = {
            "initial_state_bindings": prepared.prepared.initial_state_bindings,
            "input_data_bindings": prepared.prepared.input_data_bindings,
        }
        binding_hash = _sha(binding_payload)
        reservation_id = _stable_id(
            "RESV-N5",
            control.mission_id,
            prepared.prepared.attempt_id,
            binding_hash,
            mode,
        )
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "reservation_id": reservation_id,
            "attempt_id": prepared.prepared.attempt_id,
            "tc_id": prepared.prepared.tc_id,
            "case_version": prepared.prepared.case_version,
            "target_id": prepared.prepared.target_id,
            "binding_hash": binding_hash,
            "mode": mode,
            "state": "RESERVED",
            "prepared_artifact_id": prepared.artifact_id,
        }
        artifact_id, evidence_id, _ = self._persist_artifact(
            control,
            artifact_type=self.RESERVATION_TYPE,
            producer_task_id=execution_task_id,
            payload=payload,
            parent_refs=[prepared.artifact_id],
            evidence_kind="PREPARATION_RESERVATION_RECORD",
            subject_refs=[execution_task_id, prepared.prepared.attempt_id, reservation_id, binding_hash],
            relative=Path("n5") / control.mission_id / prepared.prepared.attempt_id / "reservation.json",
        )
        return ResourceReservationReceipt(
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            reservation_id=reservation_id,
            binding_hash=binding_hash,
            mode=mode,
        )

    def record_freshness_check(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        prepared: RuntimePreparedAttempt,
        reservation: ResourceReservationReceipt,
        raw_check_ref: str,
        verified_at: Optional[int] = None,
    ) -> FreshnessReceipt:
        self._require_execution_task(control, execution_task_id)
        self._require_prepared_artifact(control, execution_task_id, prepared)
        self._require_reservation(control, prepared, reservation)
        raw_check_ref = self._required(raw_check_ref, "N5_FRESHNESS_RAW_CHECK_REF_REQUIRED")
        verified_at = int(time.time()) if verified_at is None else int(verified_at)
        if verified_at <= 0:
            raise AutonomousPreparationNodeError("N5_FRESHNESS_TIME_INVALID")
        evidence_id = _stable_id(
            "EVD-N5-FRESH",
            control.mission_id,
            prepared.prepared.attempt_id,
            reservation.binding_hash,
            raw_check_ref,
            verified_at,
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.FRESHNESS_KIND,
            source_ref="runtime://preparation/freshness",
            content_ref=raw_check_ref,
            subject_refs=[
                execution_task_id,
                prepared.prepared.attempt_id,
                prepared.prepared.tc_id,
                prepared.prepared.target_id,
                reservation.reservation_id,
                reservation.binding_hash,
                "verified_at:%d" % verified_at,
            ],
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        return FreshnessReceipt(evidence_id=evidence_id, binding_hash=reservation.binding_hash, verified_at=verified_at)

    def finalize_case(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        execution_task_id: str,
        case: Mapping[str, Any],
        prepared: RuntimePreparedAttempt,
        batch: BatchPreparationPlanReceipt,
        reservation: ResourceReservationReceipt,
        freshness: FreshnessReceipt,
        director_evidence_refs: Sequence[str] = (),
    ) -> N5PreparationReady:
        run_id = self._required(run_id, "N5_RUN_ID_REQUIRED")
        execution_task = self._require_execution_task(control, execution_task_id)
        self._require_prepared_artifact(control, execution_task_id, prepared)
        case_dict = dict(case)
        plan = self.parser.parse(case_dict)
        case_hash = _sha(case_dict)
        if plan.tc_id != prepared.prepared.tc_id or plan.case_version != prepared.prepared.case_version:
            raise AutonomousPreparationNodeError("N5_PREPARED_CASE_IDENTITY_MISMATCH")
        if prepared.case_sha256 != hashlib.sha256(_canonical(case_dict)).hexdigest():
            raise AutonomousPreparationNodeError("N5_PREPARED_CASE_HASH_MISMATCH")
        self._require_batch(control, batch, case_hash=case_hash, target_id=prepared.prepared.target_id)
        self._require_reservation(control, prepared, reservation)
        self._require_freshness(control, prepared, reservation, freshness)
        auth_evidence_id = self._require_fresh_auth_if_needed(control, plan.preconditions, prepared)

        final_payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "execution_task_id": execution_task_id,
            "attempt_id": prepared.prepared.attempt_id,
            "tc_id": prepared.prepared.tc_id,
            "case_version": prepared.prepared.case_version,
            "case_hash": case_hash,
            "target_id": prepared.prepared.target_id,
            "prepared_artifact_id": prepared.artifact_id,
            "batch_plan_artifact_id": batch.artifact_id,
            "reservation_artifact_id": reservation.artifact_id,
            "freshness_evidence_id": freshness.evidence_id,
            "fresh_auth_evidence_id": auth_evidence_id,
            "binding_hash": reservation.binding_hash,
            "cleanup_policy": prepared.prepared.cleanup_policy,
            "status": "PREPARED_FOR_EXECUTION",
            "batch_plan_is_execution_proof": False,
        }
        final_artifact_id, final_evidence_id, final_digest = self._persist_artifact(
            control,
            artifact_type=self.FINALIZATION_TYPE,
            producer_task_id=execution_task_id,
            payload=final_payload,
            parent_refs=[batch.artifact_id, prepared.artifact_id, reservation.artifact_id],
            evidence_kind="CASE_PREPARATION_FINALIZATION_RECORD",
            subject_refs=[execution_task_id, prepared.prepared.attempt_id, prepared.prepared.tc_id, freshness.evidence_id],
            relative=Path("n5") / control.mission_id / prepared.prepared.attempt_id / "finalization.json",
        )

        evaluation_id = _stable_id(
            "EVAL-N5-PREP",
            control.mission_id,
            run_id,
            prepared.prepared.attempt_id,
            final_digest,
        )
        evaluation_evidence = tuple(dict.fromkeys(
            list(prepared.evidence_ids)
            + [batch.evidence_id, reservation.evidence_id, freshness.evidence_id, final_evidence_id]
            + ([auth_evidence_id] if auth_evidence_id else [])
            + [str(x) for x in director_evidence_refs if str(x)]
        ))
        for evidence_id in evaluation_evidence:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise AutonomousPreparationNodeError("N5_EVALUATION_EVIDENCE_NOT_DURABLE:%s" % evidence_id)
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            artifact_refs=[final_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-runtime-preparation-authority",
            dimensions={
                "gate_status": "PREPARED_FOR_EXECUTION",
                "attempt_id": prepared.prepared.attempt_id,
                "tc_id": prepared.prepared.tc_id,
                "target_id": prepared.prepared.target_id,
                "binding_hash": reservation.binding_hash,
                "freshness_verified_at": freshness.verified_at,
                "auth_required": any(str(x.get("type", "")).upper() == "AUTH" for x in plan.preconditions),
                "auth_evidence_id": auth_evidence_id,
                "batch_plan_is_execution_proof": False,
            },
            gap_refs=[],
            evidence_refs=list(evaluation_evidence),
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)

        task_id = _stable_id("TASK-N5-PREP", control.mission_id, run_id, prepared.prepared.attempt_id)
        runtime_task = Task(
            task_id=task_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            task_type="RUNTIME",
            objective="finalize current per-case preparation before execution",
            state=TaskStatus.PASS,
            input_artifact_refs=[batch.artifact_id, prepared.artifact_id, reservation.artifact_id],
            acceptance_criteria=[
                "current immutable PreparedAttempt",
                "resource reservation bound to current binding fingerprint",
                "freshness verified immediately before execution",
                "fresh 4A auth evidence when AUTH precondition exists",
            ],
            lease_owner="rc7-runtime-preparation-executor",
            output_artifact_refs=[final_artifact_id],
            evaluation_id=evaluation_id,
        )
        if not control.truth.query("rc7_task", task_id=task_id):
            append_entity(control.truth, runtime_task, release_id=control.release_id)

        adoption = WaveCNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        input_version = "%s|%s|%s|%s" % (
            prepared.prepared.target_id,
            case_hash,
            prepared.content_hash,
            reservation.binding_hash,
        )
        delta_hash = "sha256:" + hashlib.sha256(
            (input_version + "|" + freshness.evidence_id + "|" + final_digest).encode("utf-8")
        ).hexdigest()
        iteration = adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N5",
            input_version=input_version,
            delta_hash=delta_hash,
        )
        delivery = adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=[batch.artifact_id, prepared.artifact_id, reservation.artifact_id, final_artifact_id],
            evidence_refs=list(evaluation_evidence),
            reviewer_result={
                "result": "PASS",
                "runtime_owned": True,
                "evaluator_ref": evaluation.evaluator_ref,
            },
            sufficiency_result={
                "result": "PASS",
                "attempt_id": prepared.prepared.attempt_id,
                "current_prepared_attempt": True,
                "reservation_verified": True,
                "freshness_verified": True,
                "fresh_auth_verified": bool(auth_evidence_id) if any(str(x.get("type", "")).upper() == "AUTH" for x in plan.preconditions) else True,
                "cleanup_policy_defined": bool(prepared.prepared.cleanup_policy),
                "batch_plan_is_execution_proof": False,
            },
        )
        return N5PreparationReady(
            task_id=task_id,
            evaluation_id=evaluation_id,
            finalization_artifact_id=final_artifact_id,
            finalization_evidence_id=final_evidence_id,
            delivery_artifact_id=delivery.package_artifact_id,
            delivery_evidence_id=delivery.package_evidence_id,
            ready_event_id=delivery.ready_event_id,
        )

    def _require_fresh_auth_if_needed(
        self,
        control: ClosedLoopControlPlane,
        preconditions: Sequence[Mapping[str, Any]],
        prepared: RuntimePreparedAttempt,
    ) -> str:
        if not any(str(item.get("type", "")).upper() == "AUTH" for item in preconditions):
            return ""
        candidates = []
        for evidence_id in prepared.evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                continue
            row = rows[0]
            if row.get("kind") != "PRECONDITION_EVIDENCE":
                continue
            if prepared.prepared.attempt_id not in set(str(x) for x in row.get("subject_refs") or []):
                continue
            content_ref = str(row.get("content_ref") or "").lower()
            if "foura-auth" not in content_ref and "foura_auth" not in content_ref:
                continue
            created_at = int(row.get("created_at") or 0)
            if created_at <= 0 or int(time.time()) - created_at > self.max_freshness_seconds:
                continue
            candidates.append(str(row.get("evidence_id")))
        if len(candidates) != 1:
            raise AutonomousPreparationNodeError("N5_CURRENT_FOURA_AUTH_EVIDENCE_REQUIRED")
        return candidates[0]

    def _require_freshness(
        self,
        control: ClosedLoopControlPlane,
        prepared: RuntimePreparedAttempt,
        reservation: ResourceReservationReceipt,
        freshness: FreshnessReceipt,
    ) -> None:
        if freshness.binding_hash != reservation.binding_hash:
            raise AutonomousPreparationNodeError("N5_FRESHNESS_BINDING_MISMATCH")
        rows = control.truth.query("rc7_evidence", evidence_id=freshness.evidence_id)
        if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
            raise AutonomousPreparationNodeError("N5_FRESHNESS_EVIDENCE_NOT_DURABLE")
        row = rows[0]
        if row.get("kind") != self.FRESHNESS_KIND:
            raise AutonomousPreparationNodeError("N5_FRESHNESS_EVIDENCE_KIND_INVALID")
        subjects = set(str(x) for x in row.get("subject_refs") or [])
        required = {prepared.prepared.attempt_id, reservation.reservation_id, reservation.binding_hash}
        if not required.issubset(subjects):
            raise AutonomousPreparationNodeError("N5_FRESHNESS_EVIDENCE_BINDING_MISMATCH")
        now = int(time.time())
        if freshness.verified_at > now + 5 or now - freshness.verified_at > self.max_freshness_seconds:
            raise AutonomousPreparationNodeError("N5_FRESHNESS_EXPIRED")

    def _require_batch(
        self,
        control: ClosedLoopControlPlane,
        batch: BatchPreparationPlanReceipt,
        *,
        case_hash: str,
        target_id: str,
    ) -> None:
        rows = control.truth.query("rc7_artifact", artifact_id=batch.artifact_id)
        if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
            raise AutonomousPreparationNodeError("N5_BATCH_PLAN_NOT_DURABLE")
        if rows[0].get("artifact_type_name") != self.BATCH_TYPE:
            raise AutonomousPreparationNodeError("N5_BATCH_PLAN_TYPE_INVALID")
        if batch.target_id != target_id or case_hash not in set(batch.case_hashes):
            raise AutonomousPreparationNodeError("N5_BATCH_PLAN_SCOPE_MISMATCH")
        if not control.truth.query("rc7_evidence", evidence_id=batch.evidence_id):
            raise AutonomousPreparationNodeError("N5_BATCH_PLAN_EVIDENCE_REQUIRED")

    def _require_reservation(
        self,
        control: ClosedLoopControlPlane,
        prepared: RuntimePreparedAttempt,
        reservation: ResourceReservationReceipt,
    ) -> None:
        expected_hash = _sha({
            "initial_state_bindings": prepared.prepared.initial_state_bindings,
            "input_data_bindings": prepared.prepared.input_data_bindings,
        })
        if reservation.binding_hash != expected_hash:
            raise AutonomousPreparationNodeError("N5_RESERVATION_BINDING_DRIFT")
        rows = control.truth.query("rc7_artifact", artifact_id=reservation.artifact_id)
        if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
            raise AutonomousPreparationNodeError("N5_RESERVATION_NOT_DURABLE")
        if rows[0].get("artifact_type_name") != self.RESERVATION_TYPE:
            raise AutonomousPreparationNodeError("N5_RESERVATION_TYPE_INVALID")
        evidence = control.truth.query("rc7_evidence", evidence_id=reservation.evidence_id)
        if len(evidence) != 1 or evidence[0].get("mission_id") != control.mission_id:
            raise AutonomousPreparationNodeError("N5_RESERVATION_EVIDENCE_REQUIRED")

    @staticmethod
    def _require_execution_task(control: ClosedLoopControlPlane, task_id: str) -> Mapping[str, Any]:
        rows = control.truth.query("rc7_task", task_id=task_id)
        if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
            raise AutonomousPreparationNodeError("N5_EXECUTION_TASK_NOT_UNIQUE")
        if rows[0].get("node") != "EXECUTION":
            raise AutonomousPreparationNodeError("N5_EXECUTION_TASK_REQUIRED")
        return rows[0]

    @staticmethod
    def _require_prepared_artifact(
        control: ClosedLoopControlPlane,
        execution_task_id: str,
        prepared: RuntimePreparedAttempt,
    ) -> Mapping[str, Any]:
        rows = control.truth.query("rc7_artifact", artifact_id=prepared.artifact_id)
        if len(rows) != 1:
            raise AutonomousPreparationNodeError("N5_PREPARED_ATTEMPT_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != control.mission_id or row.get("producer_task_id") != execution_task_id:
            raise AutonomousPreparationNodeError("N5_PREPARED_ATTEMPT_OWNERSHIP_MISMATCH")
        if row.get("artifact_type_name") != "PREPARED_ATTEMPT" or row.get("state") != "VALID":
            raise AutonomousPreparationNodeError("N5_PREPARED_ATTEMPT_NOT_CURRENT")
        if row.get("content_hash") != prepared.content_hash:
            raise AutonomousPreparationNodeError("N5_PREPARED_ATTEMPT_HASH_MISMATCH")
        return row

    def _persist_artifact(
        self,
        control: ClosedLoopControlPlane,
        *,
        artifact_type: str,
        producer_task_id: str,
        payload: Mapping[str, Any],
        parent_refs: Sequence[str],
        evidence_kind: str,
        subject_refs: Sequence[str],
        relative: Path,
    ) -> Tuple[str, str, str]:
        encoded = _canonical(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        path = self.evidence_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousPreparationNodeError("N5_IMMUTABLE_PAYLOAD_CONFLICT:%s" % path)
        if not path.exists():
            path.write_bytes(encoded)
        artifact_id = _stable_id("ART-N5", control.mission_id, artifact_type, digest)
        evidence_id = _stable_id("EVD-N5", control.mission_id, artifact_type, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=evidence_kind,
            source_ref="runtime://autonomous-preparation",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id] + [str(x) for x in subject_refs if str(x)],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=artifact_type,
            producer_task_id=producer_task_id,
            content_ref="file://" + str(path),
            parent_refs=[str(x) for x in parent_refs if str(x)],
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return artifact_id, evidence_id, digest

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise AutonomousPreparationNodeError(code)
        return text
