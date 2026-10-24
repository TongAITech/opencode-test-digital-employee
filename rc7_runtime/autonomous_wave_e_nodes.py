"""RC7.1 Wave-E logical node closure for N8 and N9.

N8 replays the canonical Execution Recovery Contract and may carry only a
trusted PRODUCT_DEFECT handoff forward to N9. N9 replays Defect Review
Conformance across every product gap. Neither service re-performs specialist
work; they project already durable Runtime truth into NodeDeliveryPackages for
an independent Director gate.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Mapping, Sequence, Tuple

from .autonomous_contract import NodeDeliveryPackage, NodeLoopState, require_node
from .autonomous_n7_node import WaveDNodeAdoptionControl
from .autonomous_node_control import NodeDeliveryReceipt, NodeIterationSnapshot
from .closed_loop_control import ClosedLoopControlPlane
from .defect_review_conformance import DefectReviewConformanceChecker
from .execution_recovery_conformance import ExecutionRecoveryConformanceChecker
from .mission_convergence_conformance import canonical_execution_task_id
from .models import Artifact, Evaluation, EvaluationResult, Evidence, Task, TaskStatus
from .truth_overlay import append_entity


class WaveENodeClosureError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WaveENodeClosureError(code)
    return text


class WaveENodeAdoptionControl(WaveDNodeAdoptionControl):
    @staticmethod
    def source_node(node_id: str) -> str:
        node_id = require_node(node_id).value
        if node_id == "N8":
            return "EXECUTION"
        if node_id == "N9":
            return "DEFECT"
        return WaveDNodeAdoptionControl.source_node(node_id)


class WaveENodeClosureService:
    N8_PACKAGE_TYPE = "N8_FAILURE_RECOVERY_PACKAGE"
    N9_PACKAGE_TYPE = "N9_DEFECT_CONVERGENCE_PACKAGE"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def publish_n8_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> NodeDeliveryReceipt:
        run_id = _required(run_id, "N8_RUN_ID_REQUIRED")
        task_id = canonical_execution_task_id(control.truth, control.mission_id)
        if not task_id:
            raise WaveENodeClosureError("N8_EXECUTION_RECOVERY_CONTRACT_REQUIRED")
        task = self._one(control, "rc7_task", "task_id", task_id, "N8_CANONICAL_EXECUTION_TASK_NOT_UNIQUE")
        if task.get("state") != "PASS":
            raise WaveENodeClosureError("N8_CANONICAL_EXECUTION_TASK_PASS_REQUIRED")
        evaluation_id = _required(task.get("evaluation_id"), "N8_EXECUTION_EVALUATION_REQUIRED")
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "N8_EXECUTION_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("node") != "EXECUTION" or evaluation.get("result") != "PASS":
            raise WaveENodeClosureError("N8_EXECUTION_PASS_EVALUATION_REQUIRED")

        recovery = ExecutionRecoveryConformanceChecker(control.truth).check_task(
            control.mission_id,
            task_id,
        )
        if recovery.status != "PASS":
            raise WaveENodeClosureError(
                "N8_EXECUTION_RECOVERY_CONFORMANCE_FAILED:%s"
                % ",".join(recovery.violations)
            )

        handoff_gap_ids = []
        for gap_id in list(evaluation.get("gap_refs") or []):
            gap = self._one(control, "rc7_gap", "gap_id", str(gap_id), "N8_HANDOFF_GAP_NOT_UNIQUE")
            if (
                gap.get("mission_id") != control.mission_id
                or gap.get("source_node") != "EXECUTION"
                or gap.get("category") != "PRODUCT_DEFECT"
                or gap.get("target_node") != "DEFECT"
            ):
                raise WaveENodeClosureError("N8_PASS_EVALUATION_HAS_NON_PRODUCT_HANDOFF_GAP:%s" % gap_id)
            handoff_gap_ids.append(str(gap_id))

        diagnosis_evidence = [
            str(row["evidence_id"])
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == "RUNTIME_FAILURE_DIAGNOSIS"
        ]
        repair_receipts = [
            str(row["evidence_id"])
            for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == "N8_REPAIR_RECEIPT"
        ]
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "node_id": "N8",
            "execution_task_id": task_id,
            "execution_evaluation_id": evaluation_id,
            "recovery_conformance": recovery.as_dict(),
            "product_handoff_gap_ids": sorted(handoff_gap_ids),
            "diagnosis_evidence_ids": sorted(diagnosis_evidence),
            "repair_receipt_evidence_ids": sorted(repair_receipts),
            "status": "RECOVERED_OR_PRODUCT_HANDOFF_READY",
        }
        package_artifact_id, package_evidence_id, digest = self._persist_package(
            control,
            producer_task_id=task_id,
            artifact_type=self.N8_PACKAGE_TYPE,
            evidence_kind=self.N8_PACKAGE_TYPE,
            payload=payload,
            subject_refs=[run_id, task_id, evaluation_id] + handoff_gap_ids,
            relative=Path("wave-e") / control.mission_id / run_id / "n8-recovery.json",
        )

        adoption = WaveENodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        input_version = "exec-eval:%s|recovery:%s" % (evaluation_id, digest)
        iteration = self._iteration(
            adoption,
            control=control,
            run_id=run_id,
            node_id="N8",
            input_version=input_version,
            delta_hash="sha256:" + digest,
            repair_ref=package_evidence_id,
        )
        existing = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N8",
        )
        if existing is not None and existing.iteration_count == iteration.iteration_count:
            return existing

        artifact_refs = list(dict.fromkeys(
            list(task.get("output_artifact_refs") or [])
            + list(evaluation.get("artifact_refs") or [])
            + [package_artifact_id]
        ))
        evidence_refs = list(dict.fromkeys(
            list(evaluation.get("evidence_refs") or [])
            + diagnosis_evidence
            + repair_receipts
            + [package_evidence_id]
        ))
        package = NodeDeliveryPackage(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N8",
            input_version=iteration.input_version,
            iteration_count=iteration.iteration_count,
            artifact_refs=tuple(artifact_refs),
            evidence_refs=tuple(evidence_refs),
            unresolved_gap_ids=(),
            blocked_item_ids=(),
            terminal_status=NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value,
            r1_refs=(iteration.start_event_id, task_id, evaluation_id) + tuple(handoff_gap_ids),
            coverage_summary={
                "attempt_ids": list(recovery.attempt_ids),
                "terminal_statuses": list(recovery.terminal_statuses),
            },
            risk_summary={
                "product_handoff_count": len(handoff_gap_ids),
                "product_handoff_gap_ids": sorted(handoff_gap_ids),
                "unknown_failure_count": 0,
            },
            reviewer_result={
                "result": "PASS",
                "authority": "ExecutionRecoveryConformanceChecker",
                "violations": list(recovery.violations),
            },
            sufficiency_result={
                "result": "PASS",
                "execution_recovery_conformance": recovery.status,
                "only_product_handoff_gaps_allowed": True,
            },
        )
        return adoption.node_control.ready_for_director_review(
            iteration,
            package,
            producer_task_id=task_id,
        )

    def publish_n9_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> NodeDeliveryReceipt:
        run_id = _required(run_id, "N9_RUN_ID_REQUIRED")
        conformance = DefectReviewConformanceChecker(control.truth).check_mission(control.mission_id)
        if conformance.status != "PASS":
            raise WaveENodeClosureError(
                "N9_DEFECT_REVIEW_CONFORMANCE_FAILED:%s"
                % ",".join(conformance.violations)
            )
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "node_id": "N9",
            "defect_review_conformance": conformance.as_dict(),
            "status": "DEFECT_DISPOSITION_CLOSED" if conformance.triggered else "NOT_TRIGGERED",
        }
        aggregate_task_id = _stable_id("TASK-N9-CONVERGENCE", control.mission_id, run_id)
        package_artifact_id, package_evidence_id, digest = self._persist_package(
            control,
            producer_task_id=aggregate_task_id,
            artifact_type=self.N9_PACKAGE_TYPE,
            evidence_kind=self.N9_PACKAGE_TYPE,
            payload=payload,
            subject_refs=[run_id, aggregate_task_id] + list(conformance.product_gap_ids) + list(conformance.defect_ids),
            relative=Path("wave-e") / control.mission_id / run_id / "n9-defects.json",
        )
        evaluation_id = _stable_id(
            "EVAL-N9-CONVERGENCE",
            control.mission_id,
            run_id,
            digest,
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(
                control.truth,
                Evaluation(
                    evaluation_id=evaluation_id,
                    mission_id=control.mission_id,
                    node="DEFECT",
                    artifact_refs=[package_artifact_id],
                    result=EvaluationResult.PASS,
                    evaluator_ref="rc7-independent-defect-convergence-authority",
                    dimensions={
                        "gate_status": "DEFECT_REVIEW_CONFORMANCE_PASS",
                        "triggered": conformance.triggered,
                        "product_gap_ids": list(conformance.product_gap_ids),
                        "defect_ids": list(conformance.defect_ids),
                        "closed_defect_ids": list(conformance.closed_defect_ids),
                        "violations": list(conformance.violations),
                    },
                    evidence_refs=[package_evidence_id],
                ),
                release_id=control.release_id,
            )
        self._persist_n9_aggregate_task(
            control,
            task_id=aggregate_task_id,
            evaluation_id=evaluation_id,
            artifact_id=package_artifact_id,
        )

        adoption = WaveENodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        input_version = "defect-conformance:%s" % digest
        iteration = self._iteration(
            adoption,
            control=control,
            run_id=run_id,
            node_id="N9",
            input_version=input_version,
            delta_hash="sha256:" + digest,
            repair_ref=package_evidence_id,
        )
        existing = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N9",
        )
        if existing is not None and existing.iteration_count == iteration.iteration_count:
            return existing
        return adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=aggregate_task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=[package_artifact_id],
            evidence_refs=[package_evidence_id],
            coverage_summary={
                "product_gap_count": len(conformance.product_gap_ids),
                "defect_count": len(conformance.defect_ids),
                "closed_defect_count": len(conformance.closed_defect_ids),
            },
            risk_summary={
                "triggered": conformance.triggered,
                "terminal_disposition_complete": True,
            },
            reviewer_result={
                "result": "PASS",
                "authority": "DefectReviewConformanceChecker",
                "violations": list(conformance.violations),
            },
            sufficiency_result={
                "result": "PASS",
                "defect_review_conformance": conformance.status,
                "all_product_gaps_dispositioned": True,
            },
        )

    def _persist_n9_aggregate_task(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        evaluation_id: str,
        artifact_id: str,
    ) -> None:
        rows = control.truth.query("rc7_task", task_id=task_id)
        version = 0
        current = None
        if rows:
            if len(rows) != 1:
                raise WaveENodeClosureError("N9_AGGREGATE_TASK_NOT_UNIQUE")
            current = rows[0]
            version = int(current.get("artifact_version", 0))
            if current.get("state") == "PASS" and current.get("evaluation_id") == evaluation_id:
                return
            append_entity(
                control.truth,
                Task(
                    task_id=task_id,
                    mission_id=control.mission_id,
                    node="DEFECT",
                    task_type="N9_CONVERGENCE",
                    objective="aggregate independently reviewed defect disposition truth",
                    state=TaskStatus.READY,
                ),
                release_id=control.release_id,
                artifact_version=version + 1,
            )
            version += 1
        else:
            append_entity(
                control.truth,
                Task(
                    task_id=task_id,
                    mission_id=control.mission_id,
                    node="DEFECT",
                    task_type="N9_CONVERGENCE",
                    objective="aggregate independently reviewed defect disposition truth",
                    state=TaskStatus.READY,
                ),
                release_id=control.release_id,
                artifact_version=1,
            )
            version = 1
        append_entity(
            control.truth,
            Task(
                task_id=task_id,
                mission_id=control.mission_id,
                node="DEFECT",
                task_type="N9_CONVERGENCE",
                objective="aggregate independently reviewed defect disposition truth",
                state=TaskStatus.PASS,
                output_artifact_refs=[artifact_id],
                evaluation_id=evaluation_id,
            ),
            release_id=control.release_id,
            artifact_version=version + 1,
        )

    def _iteration(
        self,
        adoption: WaveENodeAdoptionControl,
        *,
        control: ClosedLoopControlPlane,
        run_id: str,
        node_id: str,
        input_version: str,
        delta_hash: str,
        repair_ref: str,
    ) -> NodeIterationSnapshot:
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        existing = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        if prior is not None and prior.input_version == input_version and existing is not None:
            return prior
        if prior is not None:
            adoption.node_control.record_repair_completed(
                prior,
                repair_refs=[repair_ref],
                delta_hash=delta_hash,
            )
        return adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id=node_id,
            input_version=input_version,
            delta_hash=delta_hash,
        )

    def _persist_package(
        self,
        control: ClosedLoopControlPlane,
        *,
        producer_task_id: str,
        artifact_type: str,
        evidence_kind: str,
        payload: Mapping[str, object],
        subject_refs: Sequence[str],
        relative: Path,
    ) -> Tuple[str, str, str]:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        path = self.evidence_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            # The path is a current projection only; immutable R1 content remains
            # content-addressed by artifact/evidence IDs. Do not silently reuse
            # stale bytes after a new iteration.
            path = path.with_name(path.stem + "-" + digest[:20] + path.suffix)
        if path.exists() and path.read_bytes() != encoded:
            raise WaveENodeClosureError("WAVE_E_PACKAGE_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-WAVE-E", control.mission_id, artifact_type, digest)
        artifact_id = _stable_id("ART-WAVE-E", control.mission_id, artifact_type, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=evidence_kind,
            source_ref="runtime://wave-e-node-closure",
            content_ref="file://" + str(path),
            subject_refs=list(dict.fromkeys(str(x) for x in subject_refs if str(x))),
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=artifact_type,
            producer_task_id=producer_task_id,
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return artifact_id, evidence_id, digest

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
            raise WaveENodeClosureError(code)
        return rows[0]
