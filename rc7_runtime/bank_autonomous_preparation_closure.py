"""BANK production adoption bridge for RC7.1 N5 preparation truth.

CasePreparationService remains the field provider runtime. This bridge does not
re-run providers and does not treat CASE_PREPARED_ATTEMPT evidence as sufficient
for node PASS. It adopts the current provider-backed preparation into the
canonical PREPARED_ATTEMPT contract, runs reservation/freshness/auth gates for
the current execution Attempt, records a per-Case finalization, and only closes
logical N5 after every Case in the accepted design denominator has a current
finalization for the same run/target/batch.

No business runner is launched by this module.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from rc6_runtime.preparation import PreparedAttempt

from .autonomous_node_adoption import AutonomousNodeAdoptionError
from .autonomous_preparation_node import (
    AutonomousPreparationNodeService,
    BatchPreparationPlanReceipt,
    WaveCNodeAdoptionControl,
)
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, Evaluation, EvaluationResult, Evidence, Task, TaskStatus
from .preparation_control import RuntimePreparedAttempt
from .truth_overlay import append_entity


class BankAutonomousPreparationClosureError(RuntimeError):
    pass


@dataclass(frozen=True)
class BankN5CaseGateReceipt:
    prepared: PreparedAttempt
    prepared_artifact_id: str
    finalization_artifact_id: str
    finalization_evidence_id: str
    node_closed: bool
    director_evaluation_id: str = ""


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BankAutonomousPreparationClosureError(code)
    return text


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class BankAutonomousPreparationClosureCoordinator:
    DEFAULT_DIRECTOR_REF = "rc7-bank-autonomous-node-director-gate"
    SOURCE_PREPARED_KIND = "CASE_PREPARED_ATTEMPT"
    AGGREGATE_TYPE = "PREPARATION_BATCH_FINALIZATION"

    def __init__(
        self,
        *,
        state_root: str,
        evidence_root: str,
        target_id: str,
        max_freshness_seconds: int = 300,
        director_ref: str = DEFAULT_DIRECTOR_REF,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.target_id = _required(target_id, "BANK_N5_TARGET_REQUIRED")
        self.max_freshness_seconds = max(1, int(max_freshness_seconds))
        self.director_ref = _required(director_ref, "BANK_N5_DIRECTOR_REF_REQUIRED")
        self.service = AutonomousPreparationNodeService(
            evidence_root=str(self.evidence_root),
            max_freshness_seconds=self.max_freshness_seconds,
        )

    @staticmethod
    def _prepared(raw: Mapping[str, Any]) -> PreparedAttempt:
        try:
            return PreparedAttempt(
                status=str(raw["status"]),
                attempt_id=str(raw["attempt_id"]),
                tc_id=str(raw["tc_id"]),
                case_version=int(raw["case_version"]),
                target_id=str(raw["target_id"]),
                precondition_evidence=tuple(raw.get("precondition_evidence") or ()),
                initial_state_bindings=dict(raw.get("initial_state_bindings") or {}),
                input_data_bindings=dict(raw.get("input_data_bindings") or {}),
                binding_evidence=tuple(raw.get("binding_evidence") or ()),
                cleanup_policy=dict(raw.get("cleanup_policy") or {}),
                oracle_snapshot=dict(raw.get("oracle_snapshot") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_PAYLOAD_INVALID") from exc

    def _source_prepared(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        prepared_result: Mapping[str, Any],
    ) -> Tuple[PreparedAttempt, Mapping[str, Any], int]:
        if prepared_result.get("status") != "PREPARED":
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_REQUIRED")
        prepared_raw = prepared_result.get("prepared_attempt")
        if not isinstance(prepared_raw, Mapping):
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_PAYLOAD_REQUIRED")
        prepared = self._prepared(prepared_raw)
        if prepared.status != "PREPARED":
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_STATUS_INVALID")
        if prepared.target_id != self.target_id:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_TARGET_MISMATCH")
        evidence_id = _required(prepared_result.get("evidence_id"), "BANK_N5_SOURCE_PREPARED_EVIDENCE_REQUIRED")
        rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_EVIDENCE_NOT_UNIQUE")
        row = rows[0]
        if row.get("mission_id") != control.mission_id:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_EVIDENCE_MISSION_MISMATCH")
        if row.get("kind") != self.SOURCE_PREPARED_KIND:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_EVIDENCE_KIND_INVALID")
        subjects = {str(x) for x in row.get("subject_refs") or []}
        required_subjects = {execution_task_id, prepared.attempt_id, prepared.tc_id, prepared.target_id}
        if not required_subjects.issubset(subjects):
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_EVIDENCE_BINDING_MISMATCH")
        created_at = int(row.get("created_at") or 0)
        now = int(time.time())
        if created_at <= 0 or created_at > now + 5 or now - created_at > self.max_freshness_seconds:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_EVIDENCE_STALE")
        ref = str(row.get("content_ref") or "")
        if not ref.startswith("state://"):
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_CONTENT_REF_INVALID")
        path = (self.state_root / ref[len("state://"):]).resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_PATH_ESCAPE") from exc
        if not path.is_file():
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_PAYLOAD_MISSING")
        raw_bytes = path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != str(row.get("content_hash") or ""):
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_HASH_MISMATCH")
        try:
            durable_payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_JSON_INVALID") from exc
        if durable_payload != dict(prepared_raw):
            raise BankAutonomousPreparationClosureError("BANK_N5_SOURCE_PREPARED_PAYLOAD_DRIFT")
        return prepared, row, created_at

    def _adopt_source_evidence(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        prepared: PreparedAttempt,
        evidence_id: str,
        canonical_kind: str,
    ) -> str:
        rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            raise BankAutonomousPreparationClosureError("BANK_N5_PROVIDER_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
        row = rows[0]
        if row.get("mission_id") != control.mission_id:
            raise BankAutonomousPreparationClosureError("BANK_N5_PROVIDER_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)
        created_at = int(row.get("created_at") or 0)
        if created_at <= 0:
            raise BankAutonomousPreparationClosureError("BANK_N5_PROVIDER_EVIDENCE_TIME_REQUIRED:%s" % evidence_id)
        adopted_id = _stable_id(
            "EVD-N5-ADOPT", control.mission_id, execution_task_id, prepared.attempt_id,
            canonical_kind, evidence_id, row.get("content_hash") or "",
        )
        existing = control.truth.query("rc7_evidence", evidence_id=adopted_id)
        if existing:
            if len(existing) != 1 or existing[0].get("mission_id") != control.mission_id or existing[0].get("kind") != canonical_kind:
                raise BankAutonomousPreparationClosureError("BANK_N5_ADOPTED_EVIDENCE_CONFLICT:%s" % adopted_id)
            return adopted_id
        append_entity(
            control.truth,
            Evidence(
                evidence_id=adopted_id,
                mission_id=control.mission_id,
                kind=canonical_kind,
                source_ref=str(row.get("source_ref") or ""),
                content_ref=str(row.get("content_ref") or ""),
                subject_refs=[execution_task_id, prepared.attempt_id, prepared.tc_id, prepared.target_id, evidence_id],
                content_hash=str(row.get("content_hash") or ""),
                created_at=created_at,
            ),
            release_id=control.release_id,
        )
        return adopted_id

    def _adopt_prepared_attempt(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        case: Mapping[str, Any],
        prepared: PreparedAttempt,
        source_row: Mapping[str, Any],
    ) -> RuntimePreparedAttempt:
        precondition_ids = tuple(
            self._adopt_source_evidence(
                control, execution_task_id=execution_task_id, prepared=prepared,
                evidence_id=str(ref), canonical_kind="PRECONDITION_EVIDENCE",
            )
            for ref in prepared.precondition_evidence if str(ref)
        )
        binding_ids = tuple(
            self._adopt_source_evidence(
                control, execution_task_id=execution_task_id, prepared=prepared,
                evidence_id=str(ref), canonical_kind="PREPARATION_BINDING_EVIDENCE",
            )
            for ref in prepared.binding_evidence if str(ref)
        )
        case_sha256 = hashlib.sha256(_canonical(dict(case))).hexdigest()
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "task_id": execution_task_id,
            "case_sha256": case_sha256,
            "target_id": prepared.target_id,
            "prepared": asdict(prepared),
            "source_prepared_evidence_id": str(source_row["evidence_id"]),
        }
        body = _canonical(payload)
        digest = hashlib.sha256(body).hexdigest()
        folder = self.evidence_root / "adopted-prepared" / control.mission_id / prepared.attempt_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("prepared-%s.json" % digest[:20])
        if path.exists() and path.read_bytes() != body:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_ARTIFACT_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)
        record_evidence_id = _stable_id(
            "EVD-N5-PREPARED", control.mission_id, execution_task_id, prepared.attempt_id, digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=record_evidence_id):
            append_entity(
                control.truth,
                Evidence(
                    evidence_id=record_evidence_id,
                    mission_id=control.mission_id,
                    kind="PREPARED_ATTEMPT_RECORD",
                    source_ref="runtime://bank-n5/case-runtime-adoption",
                    content_ref="file://" + str(path),
                    subject_refs=[execution_task_id, prepared.attempt_id, prepared.tc_id, prepared.target_id, str(source_row["evidence_id"])],
                    content_hash="sha256:" + digest,
                    created_at=int(source_row.get("created_at") or 0),
                ),
                release_id=control.release_id,
            )
        evidence_ids = tuple(dict.fromkeys(precondition_ids + binding_ids + (record_evidence_id, str(source_row["evidence_id"]))))
        artifact_id = _stable_id("ART-N5-PREPARED", control.mission_id, execution_task_id, prepared.attempt_id, digest)
        existing = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if not existing:
            append_entity(
                control.truth,
                Artifact(
                    artifact_id=artifact_id,
                    mission_id=control.mission_id,
                    artifact_type="PREPARED_ATTEMPT",
                    producer_task_id=execution_task_id,
                    content_ref="file://" + str(path),
                    parent_refs=[],
                    evidence_refs=list(evidence_ids),
                    content_hash="sha256:" + digest,
                ),
                release_id=control.release_id,
            )
        elif len(existing) != 1 or existing[0].get("mission_id") != control.mission_id or existing[0].get("producer_task_id") != execution_task_id or existing[0].get("content_hash") != "sha256:" + digest:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_ARTIFACT_CONFLICT")
        return RuntimePreparedAttempt(
            prepared=prepared,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            content_ref="file://" + str(path),
            content_hash="sha256:" + digest,
            case_sha256=case_sha256,
        )

    def _artifact_payload(
        self,
        control: ClosedLoopControlPlane,
        artifact_id: str,
        expected_type: str,
    ) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
        rows = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_NOT_UNIQUE:%s" % artifact_id)
        row = rows[0]
        if row.get("mission_id") != control.mission_id or row.get("artifact_type_name") != expected_type or row.get("state") != "VALID":
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_NOT_CURRENT:%s" % artifact_id)
        ref = str(row.get("content_ref") or "")
        if not ref.startswith("file://"):
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_FILE_REQUIRED:%s" % artifact_id)
        path = Path(ref[len("file://"):]).expanduser().resolve()
        if not path.is_file():
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_FILE_MISSING:%s" % artifact_id)
        raw = path.read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != str(row.get("content_hash") or ""):
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_HASH_MISMATCH:%s" % artifact_id)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_JSON_INVALID:%s" % artifact_id) from exc
        if not isinstance(payload, dict):
            raise BankAutonomousPreparationClosureError("BANK_N5_ARTIFACT_OBJECT_REQUIRED:%s" % artifact_id)
        return payload, row

    def _batch_plan(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        execution_task_id: str,
        accepted_cases: Sequence[Mapping[str, Any]],
    ) -> BatchPreparationPlanReceipt:
        expected_hashes = tuple(_sha(dict(case)) for case in accepted_cases)
        expected_ids = tuple(self.service.parser.parse(dict(case)).tc_id for case in accepted_cases)
        if len(expected_ids) != len(set(expected_ids)):
            raise BankAutonomousPreparationClosureError("BANK_N5_ACCEPTED_CASE_DENOMINATOR_DUPLICATE")
        matches = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.service.BATCH_TYPE:
                continue
            payload, artifact_row = self._artifact_payload(control, str(row["artifact_id"]), self.service.BATCH_TYPE)
            if payload.get("run_id") == run_id:
                matches.append((payload, artifact_row))
        if len(matches) > 1:
            raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_PLAN_NOT_UNIQUE")
        if matches:
            payload, row = matches[0]
            if payload.get("target_id") != self.target_id:
                raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_TARGET_DRIFT")
            cases = payload.get("cases")
            if not isinstance(cases, list):
                raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_CASES_INVALID")
            actual_hashes = tuple(str(item.get("case_hash") or "") for item in cases)
            actual_ids = tuple(str(item.get("tc_id") or "") for item in cases)
            if actual_ids != expected_ids or actual_hashes != expected_hashes:
                raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_DENOMINATOR_DRIFT")
            evidence_refs = [str(x) for x in row.get("evidence_refs") or [] if str(x)]
            if len(evidence_refs) != 1:
                raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_EVIDENCE_NOT_UNIQUE")
            content_hash = str(row.get("content_hash") or "")
            if not content_hash.startswith("sha256:"):
                raise BankAutonomousPreparationClosureError("BANK_N5_BATCH_HASH_INVALID")
            return BatchPreparationPlanReceipt(
                artifact_id=str(row["artifact_id"]),
                evidence_id=evidence_refs[0],
                plan_hash=content_hash.split(":", 1)[1],
                target_id=self.target_id,
                case_hashes=actual_hashes,
            )
        return self.service.create_batch_plan(
            control,
            run_id=run_id,
            target_id=self.target_id,
            cases=accepted_cases,
            producer_task_ids=[execution_task_id],
        )

    def _require_fresh_auth_if_needed(
        self,
        control: ClosedLoopControlPlane,
        preconditions: Sequence[Mapping[str, Any]],
        prepared: RuntimePreparedAttempt,
    ) -> str:
        if not any(str(item.get("type", "")).upper() == "AUTH" for item in preconditions):
            return ""
        now = int(time.time())
        candidates = []
        for evidence_id in prepared.evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                continue
            row = rows[0]
            if row.get("kind") != "PRECONDITION_EVIDENCE":
                continue
            if prepared.prepared.attempt_id not in {str(x) for x in row.get("subject_refs") or []}:
                continue
            provenance = (str(row.get("source_ref") or "") + " " + str(row.get("content_ref") or "")).lower()
            if "foura-auth" not in provenance and "foura_auth" not in provenance:
                continue
            created_at = int(row.get("created_at") or 0)
            if created_at <= 0 or created_at > now + 5 or now - created_at > self.max_freshness_seconds:
                continue
            candidates.append(str(row.get("evidence_id") or ""))
        if len(candidates) != 1:
            raise BankAutonomousPreparationClosureError("BANK_N5_CURRENT_FOURA_AUTH_EVIDENCE_REQUIRED")
        return candidates[0]

    def _record_case_finalization(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        execution_task_id: str,
        case: Mapping[str, Any],
        prepared: RuntimePreparedAttempt,
        batch: BatchPreparationPlanReceipt,
        source_prepared_evidence_id: str,
        source_verified_at: int,
    ) -> Tuple[str, str]:
        reservation = self.service.reserve_prepared_bindings(
            control, execution_task_id=execution_task_id, prepared=prepared,
        )
        freshness = self.service.record_freshness_check(
            control,
            execution_task_id=execution_task_id,
            prepared=prepared,
            reservation=reservation,
            raw_check_ref="r1://evidence/%s" % source_prepared_evidence_id,
            verified_at=source_verified_at,
        )
        self.service._require_execution_task(control, execution_task_id)
        self.service._require_prepared_artifact(control, execution_task_id, prepared)
        case_dict = dict(case)
        plan = self.service.parser.parse(case_dict)
        case_hash = _sha(case_dict)
        if plan.tc_id != prepared.prepared.tc_id or plan.case_version != prepared.prepared.case_version:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_CASE_IDENTITY_MISMATCH")
        if prepared.case_sha256 != hashlib.sha256(_canonical(case_dict)).hexdigest():
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_CASE_HASH_MISMATCH")
        self.service._require_batch(control, batch, case_hash=case_hash, target_id=prepared.prepared.target_id)
        self.service._require_reservation(control, prepared, reservation)
        self.service._require_freshness(control, prepared, reservation, freshness)
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
        final_artifact_id, final_evidence_id, final_digest = self.service._persist_artifact(
            control,
            artifact_type=self.service.FINALIZATION_TYPE,
            producer_task_id=execution_task_id,
            payload=final_payload,
            parent_refs=[batch.artifact_id, prepared.artifact_id, reservation.artifact_id],
            evidence_kind="CASE_PREPARATION_FINALIZATION_RECORD",
            subject_refs=[execution_task_id, prepared.prepared.attempt_id, prepared.prepared.tc_id, freshness.evidence_id],
            relative=Path("n5") / control.mission_id / prepared.prepared.attempt_id / "finalization.json",
        )
        evaluation_id = _stable_id("EVAL-N5-PREP", control.mission_id, run_id, prepared.prepared.attempt_id, final_digest)
        evaluation_evidence = tuple(dict.fromkeys(
            list(prepared.evidence_ids)
            + [batch.evidence_id, reservation.evidence_id, freshness.evidence_id, final_evidence_id]
            + ([auth_evidence_id] if auth_evidence_id else [])
        ))
        for evidence_id in evaluation_evidence:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise BankAutonomousPreparationClosureError("BANK_N5_EVALUATION_EVIDENCE_NOT_DURABLE:%s" % evidence_id)
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
        if not control.truth.query("rc7_task", task_id=task_id):
            append_entity(
                control.truth,
                Task(
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
                ),
                release_id=control.release_id,
            )
        else:
            row = control.truth.query("rc7_task", task_id=task_id)[0]
            if row.get("state") != TaskStatus.PASS.value or row.get("evaluation_id") != evaluation_id:
                raise BankAutonomousPreparationClosureError("BANK_N5_CASE_FINALIZATION_TASK_CONFLICT")
        return final_artifact_id, final_evidence_id

    def _aggregate_if_complete(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        execution_task_id: str,
        batch: BatchPreparationPlanReceipt,
        accepted_cases: Sequence[Mapping[str, Any]],
    ) -> Tuple[bool, str]:
        expected = {self.service.parser.parse(dict(case)).tc_id: _sha(dict(case)) for case in accepted_cases}
        finals: Dict[str, Tuple[str, str, Mapping[str, Any]]] = {}
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.service.FINALIZATION_TYPE:
                continue
            payload, artifact_row = self._artifact_payload(control, str(row["artifact_id"]), self.service.FINALIZATION_TYPE)
            if payload.get("run_id") != run_id or payload.get("target_id") != self.target_id or payload.get("batch_plan_artifact_id") != batch.artifact_id:
                continue
            tc_id = str(payload.get("tc_id") or "")
            if tc_id not in expected:
                raise BankAutonomousPreparationClosureError("BANK_N5_FINALIZATION_UNKNOWN_TC:%s" % tc_id)
            if payload.get("case_hash") != expected[tc_id]:
                raise BankAutonomousPreparationClosureError("BANK_N5_FINALIZATION_CASE_DRIFT:%s" % tc_id)
            if tc_id in finals:
                raise BankAutonomousPreparationClosureError("BANK_N5_FINALIZATION_DUPLICATE_TC:%s" % tc_id)
            evidence_refs = [str(x) for x in artifact_row.get("evidence_refs") or [] if str(x)]
            if len(evidence_refs) != 1:
                raise BankAutonomousPreparationClosureError("BANK_N5_FINALIZATION_EVIDENCE_NOT_UNIQUE:%s" % tc_id)
            finals[tc_id] = (str(artifact_row["artifact_id"]), evidence_refs[0], payload)
        if set(finals) != set(expected):
            return False, ""
        aggregate_payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "target_id": self.target_id,
            "batch_plan_artifact_id": batch.artifact_id,
            "case_denominator": sorted(expected),
            "case_hashes": {key: expected[key] for key in sorted(expected)},
            "case_finalization_artifact_ids": [finals[key][0] for key in sorted(finals)],
            "case_finalization_evidence_ids": [finals[key][1] for key in sorted(finals)],
            "status": "PREPARATION_DENOMINATOR_COMPLETE",
            "execution_proof": False,
        }
        aggregate_artifact_id, aggregate_evidence_id, aggregate_digest = self.service._persist_artifact(
            control,
            artifact_type=self.AGGREGATE_TYPE,
            producer_task_id=execution_task_id,
            payload=aggregate_payload,
            parent_refs=[batch.artifact_id] + [finals[key][0] for key in sorted(finals)],
            evidence_kind="PREPARATION_BATCH_FINALIZATION_RECORD",
            subject_refs=[run_id, self.target_id] + sorted(finals),
            relative=Path("n5") / control.mission_id / run_id / "batch-finalization.json",
        )
        evaluation_id = _stable_id("EVAL-N5-BATCH", control.mission_id, run_id, batch.plan_hash, aggregate_digest)
        evaluation_evidence = tuple(dict.fromkeys(
            [batch.evidence_id, aggregate_evidence_id] + [finals[key][1] for key in sorted(finals)]
        ))
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            artifact_refs=[aggregate_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-runtime-preparation-aggregate-authority",
            dimensions={
                "gate_status": "PREPARATION_DENOMINATOR_COMPLETE",
                "target_id": self.target_id,
                "case_denominator": sorted(expected),
                "prepared_case_count": len(finals),
                "required_case_count": len(expected),
                "batch_plan_is_execution_proof": False,
            },
            gap_refs=[],
            evidence_refs=list(evaluation_evidence),
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)
        task_id = _stable_id("TASK-N5-BATCH", control.mission_id, run_id, batch.plan_hash, aggregate_digest)
        if not control.truth.query("rc7_task", task_id=task_id):
            append_entity(
                control.truth,
                Task(
                    task_id=task_id,
                    mission_id=control.mission_id,
                    node="TEST_DATA_PREPARATION",
                    task_type="RUNTIME",
                    objective="close preparation only after the accepted Case denominator is current and prepared",
                    state=TaskStatus.PASS,
                    input_artifact_refs=[batch.artifact_id] + [finals[key][0] for key in sorted(finals)],
                    acceptance_criteria=[
                        "every accepted Case has current per-case finalization",
                        "all finalizations bind the same run, target, and batch plan",
                        "batch planning is not execution proof",
                    ],
                    lease_owner="rc7-runtime-preparation-aggregate",
                    output_artifact_refs=[aggregate_artifact_id],
                    evaluation_id=evaluation_id,
                ),
                release_id=control.release_id,
            )
        adoption = WaveCNodeAdoptionControl(
            control.truth, release_id=control.release_id, evidence_root=str(self.evidence_root),
        )
        input_version = "%s|%s|%s|%s" % (self.target_id, batch.plan_hash, aggregate_digest, ",".join(sorted(expected)))
        delta_hash = "sha256:" + hashlib.sha256((input_version + "|" + aggregate_evidence_id).encode("utf-8")).hexdigest()
        iteration = adoption.node_control.latest_iteration(mission_id=control.mission_id, run_id=run_id, node_id="N5")
        if iteration is None:
            iteration = adoption.node_control.start_iteration(
                mission_id=control.mission_id, run_id=run_id, node_id="N5",
                input_version=input_version, delta_hash=delta_hash,
            )
        elif iteration.input_version != input_version or iteration.delta_hash != delta_hash:
            raise BankAutonomousPreparationClosureError("BANK_N5_CURRENT_RUN_SOURCE_CHANGED_REQUIRES_REPAIR")
        delivery = adoption.node_control.latest_delivery(mission_id=control.mission_id, run_id=run_id, node_id="N5")
        all_artifacts = [batch.artifact_id, aggregate_artifact_id] + [finals[key][0] for key in sorted(finals)]
        all_evidence = list(evaluation_evidence) + [finals[key][1] for key in sorted(finals)]
        if delivery is None:
            delivery = adoption.publish_ready_from_evaluated_task(
                iteration=iteration,
                source_task_id=task_id,
                source_evaluation_id=evaluation_id,
                artifact_refs=list(dict.fromkeys(all_artifacts)),
                evidence_refs=list(dict.fromkeys(all_evidence)),
                member_ids=["rc7-runtime-preparation-aggregate"],
                coverage_summary={"required_cases": len(expected), "prepared_cases": len(finals), "coverage": "100%"},
                reviewer_result={"result": "PASS", "runtime_owned": True, "evaluator_ref": evaluation.evaluator_ref},
                sufficiency_result={
                    "result": "PASS",
                    "current_prepared_attempts": True,
                    "reservations_verified": True,
                    "freshness_verified": True,
                    "accepted_case_denominator_complete": True,
                    "batch_plan_is_execution_proof": False,
                },
            )
        elif delivery.iteration_count != iteration.iteration_count:
            raise BankAutonomousPreparationClosureError("BANK_N5_STALE_DELIVERY_FORBIDDEN")
        try:
            decision = adoption.director_accept(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N5",
                director_ref=self.director_ref,
            )
        except AutonomousNodeAdoptionError as exc:
            raise BankAutonomousPreparationClosureError("BANK_N5_DIRECTOR_GATE_FAILED:%s" % exc) from exc
        return True, decision.evaluation_id

    def adopt_case_and_gate(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        execution_task_id: str,
        case: Mapping[str, Any],
        prepared_result: Mapping[str, Any],
        accepted_cases: Sequence[Mapping[str, Any]],
    ) -> BankN5CaseGateReceipt:
        run_id = _required(run_id, "BANK_N5_RUN_ID_REQUIRED")
        if not accepted_cases:
            raise BankAutonomousPreparationClosureError("BANK_N5_ACCEPTED_CASE_DENOMINATOR_REQUIRED")
        prepared, source_row, source_verified_at = self._source_prepared(
            control, execution_task_id=execution_task_id, prepared_result=prepared_result,
        )
        plan = self.service.parser.parse(dict(case))
        if plan.tc_id != prepared.tc_id or plan.case_version != prepared.case_version:
            raise BankAutonomousPreparationClosureError("BANK_N5_PREPARED_CASE_IDENTITY_MISMATCH")
        accepted_ids = [self.service.parser.parse(dict(item)).tc_id for item in accepted_cases]
        if plan.tc_id not in accepted_ids:
            raise BankAutonomousPreparationClosureError("BANK_N5_CASE_NOT_IN_ACCEPTED_DENOMINATOR:%s" % plan.tc_id)
        canonical = self._adopt_prepared_attempt(
            control,
            execution_task_id=execution_task_id,
            case=case,
            prepared=prepared,
            source_row=source_row,
        )
        batch = self._batch_plan(
            control,
            run_id=run_id,
            execution_task_id=execution_task_id,
            accepted_cases=accepted_cases,
        )
        final_artifact_id, final_evidence_id = self._record_case_finalization(
            control,
            run_id=run_id,
            execution_task_id=execution_task_id,
            case=case,
            prepared=canonical,
            batch=batch,
            source_prepared_evidence_id=str(source_row["evidence_id"]),
            source_verified_at=source_verified_at,
        )
        node_closed, director_evaluation_id = self._aggregate_if_complete(
            control,
            run_id=run_id,
            execution_task_id=execution_task_id,
            batch=batch,
            accepted_cases=accepted_cases,
        )
        return BankN5CaseGateReceipt(
            prepared=prepared,
            prepared_artifact_id=canonical.artifact_id,
            finalization_artifact_id=final_artifact_id,
            finalization_evidence_id=final_evidence_id,
            node_closed=node_closed,
            director_evaluation_id=director_evaluation_id,
        )
