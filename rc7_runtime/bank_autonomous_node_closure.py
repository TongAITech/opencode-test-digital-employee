"""Production bridge from evaluated BANK tasks to canonical autonomous node truth.

The BANK Mission DAG predates RC-AUTONOMOUS-TEST-LOOP@1.0.0. Its mature
Requirement/Code/Test-Design/Script evaluators remain specialist authorities,
but their Task PASS must not be mistaken for autonomous Node PASS. This
coordinator reconciles only already-PASS, independently evaluated source tasks
into the canonical NodeDelivery + Director gate.

It is intentionally restart-safe and fail-closed:
* no source PASS/evaluation => no delivery;
* the same durable source input is idempotently recovered after process restart;
* a changed source input never manufactures repair lineage;
* Director identity is separate from producer/evaluator identity;
* N6 can only close from the aggregate non-REPAIR Script task after the
  durable Case fan-out barrier has passed and the semantic matrix gate passes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .autonomous_events import AutonomousEvent
from .autonomous_node_adoption import (
    AutonomousNodeAdoptionControl,
    AutonomousNodeAdoptionError,
    DirectorNodeDecision,
)
from .autonomous_node_control import (
    AutonomousNodeControl,
    AutonomousNodeControlError,
    NodeDeliveryReceipt,
)
from .autonomous_preparation_node import WaveCNodeAdoptionControl
from .autonomous_script_node import AutonomousScriptNodeError, AutonomousScriptNodeService
from .candidate_payload import CandidatePayloadError, CandidatePayloadReader
from .case_fanout_conformance import contract_enabled
from .closed_loop_control import ClosedLoopControlPlane
from .models import TaskStatus
from .script_contract import AcceptedTestDesignScriptContractCompiler, ScriptContractError


class BankAutonomousNodeClosureError(RuntimeError):
    pass


_SOURCE_NODES: Tuple[Tuple[str, str], ...] = (
    ("N2", "REQUIREMENT_ANALYSIS"),
    ("N3", "CODE_ANALYSIS"),
    ("N4", "TEST_DESIGN"),
)


@dataclass(frozen=True)
class BankNodeClosureReceipt:
    node_id: str
    source_task_id: str
    source_evaluation_id: str
    delivery: NodeDeliveryReceipt
    director_decision: Optional[DirectorNodeDecision]
    recovered: bool


class BankAutonomousNodeClosureCoordinator:
    """Reconcile evaluated BANK Tasks into canonical autonomous node truth."""

    DEFAULT_DIRECTOR_REF = "rc7-bank-autonomous-node-director-gate"

    def __init__(
        self,
        *,
        release_id: str,
        run_id: str,
        evidence_root: str,
        director_ref: str = DEFAULT_DIRECTOR_REF,
    ) -> None:
        self.release_id = self._required(release_id, "BANK_NODE_RELEASE_ID_REQUIRED")
        self.run_id = self._required(run_id, "BANK_NODE_RUN_ID_REQUIRED")
        self.evidence_root = str(Path(evidence_root).expanduser().resolve())
        self.director_ref = self._required(
            director_ref, "BANK_NODE_DIRECTOR_REF_REQUIRED"
        )
        self.script_reader = CandidatePayloadReader()
        self.script_compiler = AcceptedTestDesignScriptContractCompiler()
        self.script_service = AutonomousScriptNodeService(
            evidence_root=str(Path(self.evidence_root) / "n6-script")
        )

    def reconcile_passed_nodes(
        self,
        control: ClosedLoopControlPlane,
    ) -> Tuple[BankNodeClosureReceipt, ...]:
        receipts = []
        for node_id, source_node in _SOURCE_NODES:
            tasks = [
                row
                for row in control.truth.query(
                    "rc7_task", mission_id=control.mission_id
                )
                if row.get("node") == source_node
                and row.get("state") == TaskStatus.PASS.value
            ]
            if not tasks:
                continue
            if len(tasks) != 1:
                raise BankAutonomousNodeClosureError(
                    "BANK_NODE_SOURCE_TASK_NOT_UNIQUE:%s:%d"
                    % (source_node, len(tasks))
                )
            receipts.append(
                self.reconcile_passed_task(
                    control,
                    node_id=node_id,
                    source_task_id=str(tasks[0]["task_id"]),
                )
            )

        # New graph-v2 BANK Missions opt in through CASE_FANOUT_CONTRACT. Old
        # Missions without that durable contract remain resumable and are not
        # silently upgraded into the N6 autonomous semantics.
        if contract_enabled(control.truth, control.mission_id):
            script_tasks = [
                row
                for row in control.truth.query(
                    "rc7_task", mission_id=control.mission_id
                )
                if row.get("node") == "SCRIPT_READINESS"
                and row.get("state") == TaskStatus.PASS.value
                and str(row.get("task_type") or "").upper() != "REPAIR"
            ]
            if len(script_tasks) > 1:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_SOURCE_TASK_NOT_UNIQUE:%d" % len(script_tasks)
                )
            if script_tasks:
                receipts.append(
                    self.reconcile_script_task(
                        control,
                        source_task_id=str(script_tasks[0]["task_id"]),
                    )
                )
        return tuple(receipts)

    def reconcile_script_task(
        self,
        control: ClosedLoopControlPlane,
        *,
        source_task_id: str,
    ) -> BankNodeClosureReceipt:
        """Close N6 only from aggregate Script readiness + semantic truth."""
        task = control.scheduler.task(
            self._required(source_task_id, "BANK_N6_SOURCE_TASK_ID_REQUIRED")
        )
        if task.mission_id != control.mission_id:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SOURCE_TASK_MISSION_MISMATCH"
            )
        if task.node != "SCRIPT_READINESS":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SCRIPT_READINESS_TASK_REQUIRED"
            )
        if task.task_type == "REPAIR":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_REPAIR_TASK_CANNOT_CLOSE_NODE"
            )
        if task.state != TaskStatus.PASS:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SOURCE_TASK_PASS_REQUIRED"
            )
        evaluation_id = self._required(
            task.evaluation_id,
            "BANK_N6_SOURCE_EVALUATION_REQUIRED",
        )
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "BANK_N6_SOURCE_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("mission_id") != control.mission_id:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SOURCE_EVALUATION_MISSION_MISMATCH"
            )
        if evaluation.get("node") != "SCRIPT_READINESS":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SOURCE_EVALUATION_NODE_MISMATCH"
            )
        if evaluation.get("result") != "PASS":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SOURCE_EVALUATION_PASS_REQUIRED"
            )
        if list(evaluation.get("gap_refs") or []):
            raise BankAutonomousNodeClosureError(
                "BANK_N6_PASS_EVALUATION_HAS_GAPS"
            )
        if str(evaluation.get("evaluator_ref") or "") == self.director_ref:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR"
            )
        dimensions = evaluation.get("dimensions") or {}
        if not isinstance(dimensions, dict) or dimensions.get("case_fanout_contract") != "PASS":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_CASE_FANOUT_PASS_REQUIRED"
            )

        artifact_refs = tuple(
            str(ref) for ref in task.output_artifact_refs if str(ref)
        )
        if len(artifact_refs) != 1:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SINGLE_SCRIPT_CANDIDATE_REQUIRED:%d" % len(artifact_refs)
            )
        artifact_id = artifact_refs[0]
        try:
            candidate = self.script_reader.load(
                control.truth,
                artifact_id,
                expected_mission_id=control.mission_id,
                expected_task_id=task.task_id,
            )
        except CandidatePayloadError as exc:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_CANDIDATE_INVALID:%s" % exc
            ) from exc
        if candidate.artifact_type != "SCRIPT_CANDIDATE":
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SCRIPT_CANDIDATE_REQUIRED"
            )
        binding = candidate.semantic_payload.get("binding")
        if not isinstance(binding, dict):
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SCRIPT_BINDING_REQUIRED"
            )
        tc_id = self._required(
            binding.get("tc_id"),
            "BANK_N6_SCRIPT_TC_ID_REQUIRED",
        )

        design_refs = []
        for ref in task.input_artifact_refs:
            rows = control.truth.query("rc7_artifact", artifact_id=ref)
            if len(rows) == 1 and rows[0].get("artifact_type_name") == "TEST_DESIGN_MODEL":
                design_refs.append(str(ref))
        if len(design_refs) != 1:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SCRIPT_DESIGN_ARTIFACT_NOT_UNIQUE"
            )
        try:
            contract = self.script_compiler.compile(
                control.truth,
                mission_id=control.mission_id,
                design_artifact_id=design_refs[0],
                tc_id=tc_id,
            )
        except ScriptContractError as exc:
            raise BankAutonomousNodeClosureError(
                "BANK_N6_SCRIPT_CONTRACT_INVALID:%s" % exc
            ) from exc

        expected_input_version = "%s|%s|%s|%s" % (
            contract.spec.spec_id,
            contract.spec.case_fingerprint,
            contract.spec.oracle_fingerprint,
            candidate.content_hash,
        )
        adoption = WaveCNodeAdoptionControl(
            control.truth,
            release_id=self.release_id,
            evidence_root=self.evidence_root,
        )
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=self.run_id,
            node_id="N6",
        )
        delivery = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=self.run_id,
            node_id="N6",
        )
        recovered = prior is not None
        if delivery is None:
            try:
                delivery = self.script_service.publish_ready(
                    control,
                    run_id=self.run_id,
                    task_id=task.task_id,
                    artifact_id=artifact_id,
                    spec=contract.spec,
                    member_ids=((str(task.lease_owner),) if task.lease_owner else ()),
                )
            except (
                AutonomousScriptNodeError,
                AutonomousNodeControlError,
            ) as exc:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_SEMANTIC_GATE_FAILED:%s" % exc
                ) from exc
        else:
            if prior is None:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_DELIVERY_WITHOUT_ITERATION"
                )
            if prior.input_version != expected_input_version:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_SOURCE_CHANGED_REQUIRES_DURABLE_REPAIR"
                )
            if delivery.iteration_count != prior.iteration_count:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_STALE_DELIVERY_FORBIDDEN"
                )

        decision = None
        if not self._current_director_terminal(
            control,
            node_id="N6",
            iteration_count=delivery.iteration_count,
        ):
            try:
                decision = adoption.director_accept(
                    mission_id=control.mission_id,
                    run_id=self.run_id,
                    node_id="N6",
                    director_ref=self.director_ref,
                )
            except AutonomousNodeAdoptionError as exc:
                raise BankAutonomousNodeClosureError(
                    "BANK_N6_DIRECTOR_GATE_FAILED:%s" % exc
                ) from exc

        return BankNodeClosureReceipt(
            node_id="N6",
            source_task_id=task.task_id,
            source_evaluation_id=evaluation_id,
            delivery=delivery,
            director_decision=decision,
            recovered=recovered,
        )

    def reconcile_passed_task(
        self,
        control: ClosedLoopControlPlane,
        *,
        node_id: str,
        source_task_id: str,
    ) -> BankNodeClosureReceipt:
        expected = dict(_SOURCE_NODES).get(
            self._required(node_id, "BANK_NODE_ID_REQUIRED")
        )
        if expected is None:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_N2_N4_REQUIRED:%s" % node_id
            )

        task = control.scheduler.task(
            self._required(source_task_id, "BANK_NODE_SOURCE_TASK_ID_REQUIRED")
        )
        if task.mission_id != control.mission_id:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_TASK_MISSION_MISMATCH:%s" % node_id
            )
        if task.node != expected:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_TASK_NODE_MISMATCH:%s:%s"
                % (node_id, task.node)
            )
        if task.state != TaskStatus.PASS:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_TASK_PASS_REQUIRED:%s" % node_id
            )
        evaluation_id = self._required(
            task.evaluation_id,
            "BANK_NODE_SOURCE_EVALUATION_REQUIRED:%s" % node_id,
        )
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "BANK_NODE_SOURCE_EVALUATION_NOT_UNIQUE:%s" % node_id,
        )
        if evaluation.get("mission_id") != control.mission_id:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_EVALUATION_MISSION_MISMATCH:%s" % node_id
            )
        if evaluation.get("node") != expected:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_EVALUATION_NODE_MISMATCH:%s" % node_id
            )
        if evaluation.get("result") != "PASS":
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_EVALUATION_PASS_REQUIRED:%s" % node_id
            )
        if list(evaluation.get("gap_refs") or []):
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_PASS_EVALUATION_HAS_GAPS:%s" % node_id
            )
        if str(evaluation.get("evaluator_ref") or "") == self.director_ref:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR:%s" % node_id
            )

        artifact_refs = tuple(
            dict.fromkeys(
                [
                    str(ref)
                    for ref in list(task.output_artifact_refs)
                    + list(evaluation.get("artifact_refs") or [])
                    if str(ref)
                ]
            )
        )
        if not artifact_refs:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_ARTIFACT_REQUIRED:%s" % node_id
            )
        artifacts = []
        evidence_refs = [
            str(ref)
            for ref in evaluation.get("evidence_refs") or []
            if str(ref)
        ]
        for artifact_id in artifact_refs:
            artifact = self._one(
                control,
                "rc7_artifact",
                "artifact_id",
                artifact_id,
                "BANK_NODE_SOURCE_ARTIFACT_NOT_UNIQUE:%s:%s"
                % (node_id, artifact_id),
            )
            if artifact.get("mission_id") != control.mission_id:
                raise BankAutonomousNodeClosureError(
                    "BANK_NODE_SOURCE_ARTIFACT_MISSION_MISMATCH:%s:%s"
                    % (node_id, artifact_id)
                )
            artifacts.append(artifact)
            evidence_refs.extend(
                str(ref)
                for ref in artifact.get("evidence_refs") or []
                if str(ref)
            )
        evidence_refs = list(dict.fromkeys(evidence_refs))
        if not evidence_refs:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_SOURCE_EVIDENCE_REQUIRED:%s" % node_id
            )
        for evidence_id in evidence_refs:
            row = self._one(
                control,
                "rc7_evidence",
                "evidence_id",
                evidence_id,
                "BANK_NODE_SOURCE_EVIDENCE_NOT_UNIQUE:%s:%s"
                % (node_id, evidence_id),
            )
            if row.get("mission_id") != control.mission_id:
                raise BankAutonomousNodeClosureError(
                    "BANK_NODE_SOURCE_EVIDENCE_MISSION_MISMATCH:%s:%s"
                    % (node_id, evidence_id)
                )

        fingerprint_payload: Dict[str, Any] = {
            "mission_id": control.mission_id,
            "run_id": self.run_id,
            "node_id": node_id,
            "source_task_id": task.task_id,
            "source_task_updated_at": task.updated_at,
            "source_evaluation_id": evaluation_id,
            "source_evaluation_created_at": evaluation.get("created_at"),
            "artifact_fingerprints": [
                {
                    "artifact_id": row.get("artifact_id"),
                    "version": row.get("version"),
                    "content_hash": row.get("content_hash"),
                    "content_ref": row.get("content_ref"),
                }
                for row in artifacts
            ],
            "evidence_refs": evidence_refs,
        }
        encoded = json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        input_version = "bank-evaluated:%s" % digest
        delta_hash = "sha256:" + hashlib.sha256(
            b"bank-node-delta-v1\x1f" + encoded
        ).hexdigest()

        adoption = AutonomousNodeAdoptionControl(
            control.truth,
            release_id=self.release_id,
            evidence_root=self.evidence_root,
        )
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=self.run_id,
            node_id=node_id,
        )
        delivery = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=self.run_id,
            node_id=node_id,
        )
        recovered = prior is not None
        if prior is None:
            iteration = adoption.node_control.start_iteration(
                mission_id=control.mission_id,
                run_id=self.run_id,
                node_id=node_id,
                input_version=input_version,
                delta_hash=delta_hash,
            )
        else:
            if prior.input_version != input_version or prior.delta_hash != delta_hash:
                raise BankAutonomousNodeClosureError(
                    "BANK_NODE_SOURCE_CHANGED_REQUIRES_DURABLE_REPAIR:%s" % node_id
                )
            iteration = prior

        if delivery is None:
            delivery = adoption.publish_ready_from_evaluated_task(
                iteration=iteration,
                source_task_id=task.task_id,
                source_evaluation_id=evaluation_id,
                artifact_refs=artifact_refs,
                evidence_refs=tuple(evidence_refs),
                member_ids=(
                    (str(task.lease_owner),)
                    if task.lease_owner
                    else ()
                ),
                reviewer_result={
                    "result": "PASS",
                    "source_evaluation_id": evaluation_id,
                    "source_evaluator_ref": evaluation.get("evaluator_ref"),
                    "production_reconciliation": True,
                },
                sufficiency_result={
                    "result": "PASS",
                    "source_evaluation_id": evaluation_id,
                    "source_dimensions": dict(
                        evaluation.get("dimensions") or {}
                    ),
                },
            )
        elif delivery.iteration_count != iteration.iteration_count:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_STALE_DELIVERY_FORBIDDEN:%s" % node_id
            )

        decision = None
        if not self._current_director_terminal(
            control,
            node_id=node_id,
            iteration_count=iteration.iteration_count,
        ):
            try:
                decision = adoption.director_accept(
                    mission_id=control.mission_id,
                    run_id=self.run_id,
                    node_id=node_id,
                    director_ref=self.director_ref,
                )
            except AutonomousNodeAdoptionError as exc:
                raise BankAutonomousNodeClosureError(
                    "BANK_NODE_DIRECTOR_GATE_FAILED:%s:%s" % (node_id, exc)
                ) from exc

        return BankNodeClosureReceipt(
            node_id=node_id,
            source_task_id=task.task_id,
            source_evaluation_id=evaluation_id,
            delivery=delivery,
            director_decision=decision,
            recovered=recovered,
        )

    def _current_director_terminal(
        self,
        control: ClosedLoopControlPlane,
        *,
        node_id: str,
        iteration_count: int,
    ) -> bool:
        subject_id = AutonomousNodeControl._subject_id(self.run_id, node_id)
        scoped = [
            row
            for row in control.truth.query(
                "rc7_control_event", mission_id=control.mission_id
            )
            if row.get("subject_type") == AutonomousNodeControl.SUBJECT_TYPE
            and row.get("subject_id") == subject_id
            and isinstance(row.get("data"), dict)
            and row["data"].get("run_id") == self.run_id
            and row["data"].get("node_id") == node_id
            and row["data"].get("iteration_count") == iteration_count
        ]
        accepted = [
            row
            for row in scoped
            if row.get("event_type_name")
            == AutonomousEvent.DIRECTOR_NODE_ACCEPTED.value
        ]
        terminal = [
            row
            for row in scoped
            if row.get("event_type_name") == AutonomousEvent.NODE_TERMINAL.value
            and row.get("data", {}).get("state") == "PASS"
        ]
        if len(accepted) > 1:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_DIRECTOR_ACCEPT_NOT_UNIQUE:%s:%d"
                % (node_id, len(accepted))
            )
        if len(terminal) > 1:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_TERMINAL_NOT_UNIQUE:%s:%d"
                % (node_id, len(terminal))
            )
        if terminal and not accepted:
            raise BankAutonomousNodeClosureError(
                "BANK_NODE_TERMINAL_WITHOUT_DIRECTOR_ACCEPT:%s" % node_id
            )
        return len(accepted) == 1 and len(terminal) == 1

    @staticmethod
    def _one(
        control: ClosedLoopControlPlane,
        entity_type: str,
        field: str,
        value: str,
        code: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query(entity_type, **{field: value})
        if len(rows) != 1:
            raise BankAutonomousNodeClosureError(code)
        return rows[0]

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise BankAutonomousNodeClosureError(code)
        return text
