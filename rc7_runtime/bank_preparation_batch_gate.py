"""BANK production adoption gate for autonomous N5 preparation.

The field Case Runtime remains the only component allowed to perform preparation
side effects. This coordinator promotes those already-durable field results to
the canonical PREPARED_ATTEMPT artifact model, verifies the whole accepted-case
denominator, and publishes exactly one N5 delivery for independent Director
acceptance before any business test execution is allowed to start.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from rc6_runtime.preparation import PreparedAttempt, PreparationSpecParser

from .autonomous_events import AutonomousEvent
from .autonomous_node_adoption import AutonomousNodeAdoptionError, DirectorNodeDecision
from .autonomous_preparation_node import AutonomousPreparationNodeService, WaveCNodeAdoptionControl
from .case_runtime import PREPARED_ATTEMPT_KIND
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, Evidence, Evaluation, EvaluationResult, Task, TaskStatus
from .preparation_control import RuntimePreparedAttempt
from .truth_overlay import append_entity


class BankPreparationBatchGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class BankPreparationBatchGateReceipt:
    run_id: str
    task_id: str
    evaluation_id: str
    delivery_artifact_id: str
    director_evaluation_id: str
    prepared_by_case: Mapping[str, RuntimePreparedAttempt]
    recovered: bool


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _case_hash(case: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(case))).hexdigest()


class BankPreparationBatchGate:
    DEFAULT_DIRECTOR_REF = "rc7-bank-n5-director-gate"
    EVALUATOR_REF = "rc7-runtime-preparation-batch-authority"

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
        self.target_id = self._required(target_id, "BANK_N5_TARGET_REQUIRED")
        self.max_freshness_seconds = max(1, int(max_freshness_seconds))
        self.director_ref = self._required(director_ref, "BANK_N5_DIRECTOR_REF_REQUIRED")
        self.parser = PreparationSpecParser()
        self.service = AutonomousPreparationNodeService(
            evidence_root=str(self.evidence_root / "n5-formal"),
            max_freshness_seconds=self.max_freshness_seconds,
        )

    def accepted(self, control: ClosedLoopControlPlane) -> bool:
        run_id = self._current_run_id(control)
        for row in control.truth.query("rc7_control_event", mission_id=control.mission_id):
            if row.get("event_type") != AutonomousEvent.NODE_TERMINAL.value:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if (
                data.get("run_id") == run_id
                and data.get("node_id") == "N5"
                and data.get("state") == "PASS"
            ):
                return True
        return False

    def close_batch(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        worker_id: str,
        cases: Sequence[Mapping[str, Any]],
        prepared_results: Sequence[Mapping[str, Any]],
    ) -> BankPreparationBatchGateReceipt:
        run_id = self._current_run_id(control)
        worker_id = self._required(worker_id, "BANK_N5_WORKER_REQUIRED")
        if worker_id == self.director_ref:
            raise BankPreparationBatchGateError("BANK_N5_DIRECTOR_SPECIALIST_COLLISION")
        task_rows = control.truth.query("rc7_task", task_id=execution_task_id)
        if len(task_rows) != 1 or task_rows[0].get("mission_id") != control.mission_id:
            raise BankPreparationBatchGateError("BANK_N5_EXECUTION_TASK_NOT_UNIQUE")
        if task_rows[0].get("node") != "EXECUTION":
            raise BankPreparationBatchGateError("BANK_N5_EXECUTION_TASK_REQUIRED")

        denominator = self._validate_denominator(cases, prepared_results)
        batch = self.service.create_batch_plan(
            control,
            run_id=run_id,
            target_id=self.target_id,
            cases=[case for case, _ in denominator],
            producer_task_ids=[execution_task_id],
        )

        prepared_by_case: Dict[str, RuntimePreparedAttempt] = {}
        reservation_ids = []
        freshness_ids = []
        evidence_ids = [batch.evidence_id]
        artifact_ids = [batch.artifact_id]
        case_summary = []
        for case, result in denominator:
            raw = result.get("prepared_attempt")
            source_evidence_id = self._required(
                result.get("evidence_id"), "BANK_N5_SOURCE_PREPARED_EVIDENCE_REQUIRED"
            )
            if not isinstance(raw, dict):
                raise BankPreparationBatchGateError("BANK_N5_PREPARED_PAYLOAD_REQUIRED")
            prepared = self._promote_field_prepared(
                control,
                execution_task_id=execution_task_id,
                case=case,
                raw=raw,
                source_evidence_id=source_evidence_id,
            )
            tc_id = prepared.prepared.tc_id
            reservation = self.service.reserve_prepared_bindings(
                control,
                execution_task_id=execution_task_id,
                prepared=prepared,
            )
            source_row = self._source_prepared_row(
                control,
                execution_task_id=execution_task_id,
                prepared=prepared.prepared,
                source_evidence_id=source_evidence_id,
            )
            self._require_recent(source_row, "BANK_N5_SOURCE_PREPARATION_STALE")
            freshness = self.service.record_freshness_check(
                control,
                execution_task_id=execution_task_id,
                prepared=prepared,
                reservation=reservation,
                raw_check_ref=self._required(
                    source_row.get("content_ref"), "BANK_N5_SOURCE_PREPARATION_REF_REQUIRED"
                ),
            )
            auth_evidence_id = self._require_fresh_foura_if_needed(
                control, case=case, prepared=prepared.prepared
            )
            if not prepared.prepared.cleanup_policy:
                raise BankPreparationBatchGateError(
                    "BANK_N5_CLEANUP_POLICY_REQUIRED:%s" % tc_id
                )

            prepared_by_case[tc_id] = prepared
            artifact_ids.extend([prepared.artifact_id, reservation.artifact_id])
            reservation_ids.append(reservation.artifact_id)
            freshness_ids.append(freshness.evidence_id)
            evidence_ids.extend(
                list(prepared.evidence_ids)
                + [reservation.evidence_id, freshness.evidence_id]
                + ([auth_evidence_id] if auth_evidence_id else [])
            )
            case_summary.append(
                {
                    "tc_id": tc_id,
                    "case_version": prepared.prepared.case_version,
                    "attempt_id": prepared.prepared.attempt_id,
                    "prepared_artifact_id": prepared.artifact_id,
                    "reservation_artifact_id": reservation.artifact_id,
                    "freshness_evidence_id": freshness.evidence_id,
                    "auth_evidence_id": auth_evidence_id,
                    "cleanup_policy_defined": True,
                }
            )

        required_tc_ids = {self.parser.parse(dict(case)).tc_id for case, _ in denominator}
        if set(prepared_by_case) != required_tc_ids:
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_DENOMINATOR_MISMATCH")

        aggregate_payload = {
            "schema": "pfc.aitest.rc7.1.bank-n5-batch-finalization.v1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "target_id": self.target_id,
            "execution_task_id": execution_task_id,
            "required_tc_ids": sorted(prepared_by_case),
            "prepared_case_count": len(prepared_by_case),
            "cases": sorted(case_summary, key=lambda item: item["tc_id"]),
            "batch_plan_artifact_id": batch.artifact_id,
            "reservation_artifact_ids": sorted(reservation_ids),
            "freshness_evidence_ids": sorted(freshness_ids),
            "execution_proof": False,
            "status": "PREPARED_FOR_EXECUTION",
        }
        final_artifact_id, final_evidence_id, final_digest = self.service._persist_artifact(
            control,
            artifact_type="BATCH_PREPARATION_FINALIZATION",
            producer_task_id=execution_task_id,
            payload=aggregate_payload,
            parent_refs=list(dict.fromkeys(artifact_ids)),
            evidence_kind="BATCH_PREPARATION_FINALIZATION_RECORD",
            subject_refs=[run_id, self.target_id, execution_task_id] + sorted(prepared_by_case),
            relative=Path("n5") / control.mission_id / run_id / "batch-finalization.json",
        )
        artifact_ids.append(final_artifact_id)
        evidence_ids.append(final_evidence_id)
        evidence_ids = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
        for evidence_id in evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise BankPreparationBatchGateError(
                    "BANK_N5_EVIDENCE_NOT_DURABLE:%s" % evidence_id
                )

        evaluation_id = _stable_id(
            "EVAL-BANK-N5-BATCH",
            control.mission_id,
            run_id,
            self.target_id,
            final_digest,
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            artifact_refs=[final_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=self.EVALUATOR_REF,
            dimensions={
                "gate_status": "PREPARED_FOR_EXECUTION",
                "run_id": run_id,
                "target_id": self.target_id,
                "required_tc_ids": sorted(prepared_by_case),
                "required_case_count": len(prepared_by_case),
                "prepared_case_count": len(prepared_by_case),
                "denominator_closed": True,
                "all_reservations_verified": True,
                "all_freshness_verified": True,
                "all_required_auth_verified": True,
                "all_cleanup_policies_defined": True,
                "business_execution_performed": False,
            },
            gap_refs=[],
            evidence_refs=evidence_ids,
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)

        runtime_task_id = _stable_id(
            "TASK-BANK-N5-BATCH", control.mission_id, run_id, final_digest
        )
        runtime_task = Task(
            task_id=runtime_task_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            task_type="RUNTIME",
            objective="finalize whole accepted Case preparation denominator before execution",
            state=TaskStatus.PASS,
            input_artifact_refs=[batch.artifact_id]
            + sorted(item.artifact_id for item in prepared_by_case.values()),
            acceptance_criteria=[
                "all accepted Cases have current immutable PreparedAttempt artifacts",
                "all prepared bindings are reserved and fresh",
                "current 4A evidence exists for every AUTH precondition",
                "cleanup policy is defined for every prepared Case",
                "no business test execution occurs before independent Director acceptance",
            ],
            lease_owner=worker_id,
            output_artifact_refs=[final_artifact_id],
            evaluation_id=evaluation_id,
        )
        if not control.truth.query("rc7_task", task_id=runtime_task_id):
            append_entity(control.truth, runtime_task, release_id=control.release_id)

        adoption = WaveCNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root / "n5-adoption"),
        )
        input_version = hashlib.sha256(
            _canonical(
                {
                    "target_id": self.target_id,
                    "required_tc_ids": sorted(prepared_by_case),
                    "prepared": {
                        tc_id: prepared_by_case[tc_id].content_hash
                        for tc_id in sorted(prepared_by_case)
                    },
                    "final_digest": final_digest,
                }
            )
        ).hexdigest()
        delta_hash = "sha256:" + hashlib.sha256(
            (input_version + "|" + final_evidence_id).encode("utf-8")
        ).hexdigest()

        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id, run_id=run_id, node_id="N5"
        )
        delivery = adoption.node_control.latest_delivery(
            mission_id=control.mission_id, run_id=run_id, node_id="N5"
        )
        recovered = prior is not None
        if prior is None:
            iteration = adoption.node_control.start_iteration(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N5",
                input_version=input_version,
                delta_hash=delta_hash,
            )
        else:
            if prior.input_version != input_version:
                raise BankPreparationBatchGateError(
                    "BANK_N5_SOURCE_CHANGED_REQUIRES_DURABLE_REPAIR"
                )
            iteration = prior
        if delivery is None:
            delivery = adoption.publish_ready_from_evaluated_task(
                iteration=iteration,
                source_task_id=runtime_task_id,
                source_evaluation_id=evaluation_id,
                artifact_refs=list(dict.fromkeys(artifact_ids)),
                evidence_refs=evidence_ids,
                member_ids=(worker_id,),
                coverage_summary={
                    "required_case_count": len(prepared_by_case),
                    "prepared_case_count": len(prepared_by_case),
                    "denominator_closed": True,
                },
                reviewer_result={
                    "result": "PASS",
                    "runtime_owned": True,
                    "evaluator_ref": self.EVALUATOR_REF,
                },
                sufficiency_result={
                    "result": "PASS",
                    "denominator_closed": True,
                    "current_prepared_attempts": True,
                    "reservations_verified": True,
                    "freshness_verified": True,
                    "required_auth_verified": True,
                    "cleanup_policies_defined": True,
                    "business_execution_performed": False,
                },
            )
        elif delivery.iteration_count != iteration.iteration_count:
            raise BankPreparationBatchGateError("BANK_N5_STALE_DELIVERY_FORBIDDEN")

        try:
            decision: DirectorNodeDecision = adoption.director_accept(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N5",
                director_ref=self.director_ref,
            )
        except AutonomousNodeAdoptionError as exc:
            raise BankPreparationBatchGateError(
                "BANK_N5_DIRECTOR_GATE_FAILED:%s" % exc
            ) from exc
        if decision.accepted is not True:
            raise BankPreparationBatchGateError("BANK_N5_DIRECTOR_ACCEPT_REQUIRED")
        return BankPreparationBatchGateReceipt(
            run_id=run_id,
            task_id=runtime_task_id,
            evaluation_id=evaluation_id,
            delivery_artifact_id=delivery.package_artifact_id,
            director_evaluation_id=decision.evaluation_id,
            prepared_by_case=prepared_by_case,
            recovered=recovered,
        )

    def _validate_denominator(
        self,
        cases: Sequence[Mapping[str, Any]],
        prepared_results: Sequence[Mapping[str, Any]],
    ) -> Tuple[Tuple[Dict[str, Any], Mapping[str, Any]], ...]:
        if not cases or len(cases) != len(prepared_results):
            raise BankPreparationBatchGateError("BANK_N5_DENOMINATOR_COUNT_MISMATCH")
        pairs = []
        seen = set()
        for case, result in zip(cases, prepared_results):
            case_dict = dict(case)
            tc_id = self.parser.parse(case_dict).tc_id
            if tc_id in seen:
                raise BankPreparationBatchGateError(
                    "BANK_N5_DENOMINATOR_DUPLICATE:%s" % tc_id
                )
            seen.add(tc_id)
            if result.get("status") != "PREPARED":
                raise BankPreparationBatchGateError(
                    "BANK_N5_CASE_NOT_PREPARED:%s:%s"
                    % (tc_id, result.get("status"))
                )
            raw = result.get("prepared_attempt")
            if not isinstance(raw, dict) or raw.get("tc_id") != tc_id:
                raise BankPreparationBatchGateError(
                    "BANK_N5_PREPARED_CASE_MISMATCH:%s" % tc_id
                )
            pairs.append((case_dict, result))
        return tuple(pairs)

    def _promote_field_prepared(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        case: Mapping[str, Any],
        raw: Mapping[str, Any],
        source_evidence_id: str,
    ) -> RuntimePreparedAttempt:
        prepared = self._prepared(raw)
        if prepared.target_id != self.target_id:
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_TARGET_MISMATCH")
        case_dict = dict(case)
        plan = self.parser.parse(case_dict)
        if plan.tc_id != prepared.tc_id or plan.case_version != prepared.case_version:
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_CASE_IDENTITY_MISMATCH")
        source = self._source_prepared_row(
            control,
            execution_task_id=execution_task_id,
            prepared=prepared,
            source_evidence_id=source_evidence_id,
        )
        self._require_recent(source, "BANK_N5_SOURCE_PREPARATION_STALE")

        raw_evidence_ids = []
        for evidence_id in tuple(prepared.precondition_evidence) + tuple(prepared.binding_evidence):
            evidence_id = self._required(evidence_id, "BANK_N5_RAW_EVIDENCE_ID_REQUIRED")
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise BankPreparationBatchGateError(
                    "BANK_N5_RAW_EVIDENCE_NOT_DURABLE:%s" % evidence_id
                )
            raw_evidence_ids.append(evidence_id)

        case_sha256 = _case_hash(case_dict)
        artifact_id = _stable_id(
            "ART-PREPARED", control.mission_id, execution_task_id, prepared.attempt_id
        )
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "task_id": execution_task_id,
            "case_sha256": case_sha256,
            "target_id": self.target_id,
            "prepared": asdict(prepared),
            "adopted_from_case_runtime_evidence_id": source_evidence_id,
            "provider_reexecuted": False,
        }
        encoded = _canonical(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n5-formal" / "prepared-attempts" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (prepared.attempt_id + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(encoded)

        record_evidence_id = _stable_id(
            "EVD-PREP-RECORD", control.mission_id, prepared.attempt_id, digest
        )
        record_evidence = Evidence(
            evidence_id=record_evidence_id,
            mission_id=control.mission_id,
            kind="RUNTIME_PREPARATION_RECORD",
            source_ref="runtime://bank-preparation-adoption",
            content_ref="file://" + str(path),
            subject_refs=[
                execution_task_id,
                prepared.attempt_id,
                prepared.tc_id,
                prepared.target_id,
                source_evidence_id,
            ],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=record_evidence_id):
            append_entity(control.truth, record_evidence, release_id=control.release_id)
        evidence_ids = tuple(
            dict.fromkeys(raw_evidence_ids + [source_evidence_id, record_evidence_id])
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type="PREPARED_ATTEMPT",
            producer_task_id=execution_task_id,
            content_ref="file://" + str(path),
            parent_refs=[],
            evidence_refs=list(evidence_ids),
            content_hash="sha256:" + digest,
        )
        existing = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if existing:
            if len(existing) != 1:
                raise BankPreparationBatchGateError("BANK_N5_CANONICAL_PREPARED_NOT_UNIQUE")
            row = existing[0]
            if (
                row.get("mission_id") != control.mission_id
                or row.get("producer_task_id") != execution_task_id
                or row.get("artifact_type_name") != "PREPARED_ATTEMPT"
                or row.get("content_hash") != artifact.content_hash
            ):
                raise BankPreparationBatchGateError("BANK_N5_CANONICAL_PREPARED_DRIFT")
        else:
            append_entity(control.truth, artifact, release_id=control.release_id, artifact_version=1)
        return RuntimePreparedAttempt(
            prepared=prepared,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            content_ref=artifact.content_ref,
            content_hash=artifact.content_hash or "",
            case_sha256=case_sha256,
        )

    def _source_prepared_row(
        self,
        control: ClosedLoopControlPlane,
        *,
        execution_task_id: str,
        prepared: PreparedAttempt,
        source_evidence_id: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query("rc7_evidence", evidence_id=source_evidence_id)
        if len(rows) != 1:
            raise BankPreparationBatchGateError("BANK_N5_SOURCE_PREPARED_NOT_UNIQUE")
        row = rows[0]
        refs = {str(item) for item in row.get("subject_refs") or []}
        required = {
            execution_task_id,
            prepared.attempt_id,
            prepared.tc_id,
            prepared.target_id,
        }
        if (
            row.get("mission_id") != control.mission_id
            or row.get("kind") != PREPARED_ATTEMPT_KIND
            or not required.issubset(refs)
        ):
            raise BankPreparationBatchGateError("BANK_N5_SOURCE_PREPARED_IDENTITY_MISMATCH")
        return row

    def _require_fresh_foura_if_needed(
        self,
        control: ClosedLoopControlPlane,
        *,
        case: Mapping[str, Any],
        prepared: PreparedAttempt,
    ) -> str:
        plan = self.parser.parse(dict(case))
        if not any(str(item.get("type") or "").upper() == "AUTH" for item in plan.preconditions):
            return ""
        matches = []
        for evidence_id in prepared.precondition_evidence:
            rows = control.truth.query("rc7_evidence", evidence_id=str(evidence_id))
            if len(rows) != 1:
                continue
            row = rows[0]
            source_ref = str(row.get("source_ref") or "").lower()
            if "precondition_auth" not in source_ref:
                continue
            if "foura" not in source_ref and "4a" not in source_ref:
                continue
            try:
                self._require_recent(row, "BANK_N5_CURRENT_FOURA_AUTH_EVIDENCE_REQUIRED")
            except BankPreparationBatchGateError:
                continue
            matches.append(str(row.get("evidence_id") or ""))
        matches = sorted(set(item for item in matches if item))
        if len(matches) != 1:
            raise BankPreparationBatchGateError(
                "BANK_N5_CURRENT_FOURA_AUTH_EVIDENCE_REQUIRED:%s:%d"
                % (prepared.tc_id, len(matches))
            )
        return matches[0]

    def _current_run_id(self, control: ClosedLoopControlPlane) -> str:
        run_ids = set()
        for row in control.truth.query("rc7_control_event", mission_id=control.mission_id):
            if row.get("event_type") != AutonomousEvent.NODE_TERMINAL.value:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if data.get("node_id") == "N4" and data.get("state") == "PASS":
                run_id = str(data.get("run_id") or "").strip()
                if run_id:
                    run_ids.add(run_id)
        if len(run_ids) != 1:
            raise BankPreparationBatchGateError(
                "BANK_N5_CURRENT_RUN_NOT_UNIQUE:%d" % len(run_ids)
            )
        return next(iter(run_ids))

    def _require_recent(self, row: Mapping[str, Any], code: str) -> None:
        try:
            created = float(row.get("created_at") or 0)
        except (TypeError, ValueError) as exc:
            raise BankPreparationBatchGateError(code) from exc
        now = time.time()
        while created > now * 100:
            created /= 1000.0
        if created <= 0 or created > now + 5 or now - created > self.max_freshness_seconds:
            raise BankPreparationBatchGateError(code)

    @staticmethod
    def _prepared(raw: Mapping[str, Any]) -> PreparedAttempt:
        try:
            prepared = PreparedAttempt(
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
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_PAYLOAD_INVALID") from exc
        if prepared.status != "PREPARED":
            raise BankPreparationBatchGateError("BANK_N5_PREPARED_STATUS_INVALID")
        return prepared

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise BankPreparationBatchGateError(code)
        return text
