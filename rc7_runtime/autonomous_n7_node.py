"""N7 node-level convergence over durable per-layer coverage truth."""
from __future__ import annotations

import hashlib
from typing import Dict, Mapping, Sequence, Tuple

from .autonomous_contract import CanonicalLayer, NodeLoopState
from .autonomous_coverage_closure import (
    AutonomousCoverageClosureError,
    AutonomousCoverageClosureService,
    DurableCoverageDenominator,
    DurableLayerCoverageReceipt,
    _stable_id,
)
from .autonomous_preparation_node import WaveCNodeAdoptionControl
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evaluation, EvaluationResult, Gap, GapSeverity, Task, TaskStatus
from .truth_overlay import append_entity


class AutonomousN7NodeError(RuntimeError):
    pass


class WaveDNodeAdoptionControl(WaveCNodeAdoptionControl):
    @staticmethod
    def source_node(node_id: str) -> str:
        if str(node_id) == "N7":
            return "EXECUTION"
        return WaveCNodeAdoptionControl.source_node(node_id)


class AutonomousN7NodeService:
    """The only supported N7 orchestration surface for denominator lifecycle."""

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = str(evidence_root)
        self.coverage = AutonomousCoverageClosureService(evidence_root=evidence_root)

    def freeze_denominator(self, control: ClosedLoopControlPlane, **kwargs) -> DurableCoverageDenominator:
        layer = str(kwargs.get("layer") or "")
        target_id = str(kwargs.get("target_id") or "")
        prior = self.coverage.current_denominator(control, layer=layer, target_id=target_id) if layer and target_id else None
        current = self.coverage.freeze_denominator(control, **kwargs)
        if prior is not None and current.artifact_id != prior.artifact_id:
            run_id = str(kwargs.get("run_id") or "")
            self._reopen_n7(control, run_id=run_id, denominator=current)
        return current

    def reconcile_layer(self, control: ClosedLoopControlPlane, **kwargs) -> DurableLayerCoverageReceipt:
        return self.coverage.reconcile_layer(control, **kwargs)

    def publish_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        receipts: Sequence[DurableLayerCoverageReceipt],
    ):
        run_id = self._required(run_id, "N7_RUN_ID_REQUIRED")
        by_layer: Dict[str, DurableLayerCoverageReceipt] = {}
        for durable in receipts:
            layer = str(durable.receipt.layer)
            if layer in by_layer:
                raise AutonomousN7NodeError("N7_DUPLICATE_LAYER_RECEIPT:%s" % layer)
            by_layer[layer] = durable
        required_layers = {layer.value for layer in CanonicalLayer}
        if set(by_layer) != required_layers:
            missing = sorted(required_layers - set(by_layer))
            extra = sorted(set(by_layer) - required_layers)
            raise AutonomousN7NodeError("N7_ALL_CANONICAL_LAYER_RECEIPTS_REQUIRED:missing=%s:extra=%s" % (",".join(missing), ",".join(extra)))

        artifact_refs = []
        evidence_refs = []
        coverage_summary: Dict[str, Mapping[str, object]] = {}
        input_parts = []
        covered_fail_total = 0
        for layer in sorted(by_layer):
            durable = by_layer[layer]
            receipt = durable.receipt
            if receipt.status != "READY":
                raise AutonomousN7NodeError("N7_LAYER_NOT_READY:%s" % layer)
            artifact = self._one(control, "rc7_artifact", "artifact_id", durable.artifact_id, "N7_LAYER_RECEIPT_ARTIFACT_NOT_UNIQUE")
            if artifact.get("mission_id") != control.mission_id or artifact.get("artifact_type_name") != self.coverage.RECEIPT_TYPE:
                raise AutonomousN7NodeError("N7_LAYER_RECEIPT_ARTIFACT_INVALID:%s" % layer)
            evidence = self._one(control, "rc7_evidence", "evidence_id", durable.evidence_id, "N7_LAYER_RECEIPT_EVIDENCE_NOT_UNIQUE")
            if evidence.get("mission_id") != control.mission_id:
                raise AutonomousN7NodeError("N7_LAYER_RECEIPT_EVIDENCE_MISSION_MISMATCH:%s" % layer)
            current = self.coverage.current_denominator(control, layer=layer, target_id=receipt.target_id)
            if current is None:
                raise AutonomousN7NodeError("N7_CURRENT_DENOMINATOR_REQUIRED:%s" % layer)
            if (
                current.snapshot.denominator_version != receipt.denominator_version
                or current.snapshot.denominator_hash != receipt.denominator_hash
            ):
                raise AutonomousN7NodeError("N7_STALE_LAYER_RECEIPT:%s" % layer)
            # A READY receipt has already enforced the canonical metric target set;
            # preserve the actual values in the node package for N10/reporting.
            coverage_summary[layer] = {
                "target_id": receipt.target_id,
                "denominator_version": receipt.denominator_version,
                "denominator_hash": receipt.denominator_hash,
                "covered": receipt.covered,
                "total": receipt.total,
                "percent": receipt.percent,
                "covered_pass": receipt.covered_pass,
                "covered_fail": receipt.covered_fail,
                "excluded_with_evidence": receipt.excluded_with_evidence,
                "metrics": dict(durable.metrics),
                "quality_pass_required": False,
            }
            covered_fail_total += receipt.covered_fail
            artifact_refs.append(durable.artifact_id)
            evidence_refs.append(durable.evidence_id)
            evidence_refs.extend(receipt.evidence_refs)
            input_parts.append("%s:%s:%s" % (layer, receipt.denominator_version, receipt.denominator_hash))

        evidence_refs = list(dict.fromkeys(str(x) for x in evidence_refs if str(x)))
        for evidence_id in evidence_refs:
            row = self._one(control, "rc7_evidence", "evidence_id", evidence_id, "N7_NODE_EVIDENCE_NOT_UNIQUE")
            if row.get("mission_id") != control.mission_id:
                raise AutonomousN7NodeError("N7_NODE_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)

        task_id = self.coverage._ensure_runtime_task(control, run_id)
        evaluation_id = _stable_id(
            "EVAL-N7-COVERAGE",
            control.mission_id,
            run_id,
            *input_parts,
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=list(artifact_refs),
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-runtime-coverage-authority",
            dimensions={
                "gate_status": "ALL_LAYER_COVERAGE_READY",
                "canonical_layers": sorted(required_layers),
                "covered_fail_total": covered_fail_total,
                "product_quality_pass_required": False,
                "all_current_denominator_versions": True,
            },
            gap_refs=[],
            evidence_refs=evidence_refs,
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)
        append_entity(
            control.truth,
            Task(
                task_id=task_id,
                mission_id=control.mission_id,
                node="EXECUTION",
                task_type="RUNTIME",
                objective="close current L1-L7 coverage denominators",
                state=TaskStatus.PASS,
                acceptance_criteria=[
                    "all canonical layer receipts READY",
                    "all receipts bind current denominator versions",
                    "coverage gaps zero on current denominator",
                    "COVERED_FAIL remains valid coverage and separate quality truth",
                ],
                lease_owner="rc7-runtime-coverage-executor",
                output_artifact_refs=list(artifact_refs),
                evaluation_id=evaluation_id,
            ),
            release_id=control.release_id,
        )

        adoption = WaveDNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=self.evidence_root,
        )
        input_version = "|".join(input_parts)
        delta_hash = "sha256:" + hashlib.sha256(
            (input_version + "|" + ",".join(sorted(artifact_refs))).encode("utf-8")
        ).hexdigest()
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N7",
        )
        if prior is not None:
            events = adoption.node_control._events(control.mission_id, run_id, "N7")
            repairable = {
                "NODE_GAP_DETECTED",
                "NODE_REPAIR_COMPLETED",
                "DIRECTOR_NODE_REJECTED",
            }
            prior_events = [
                row for row in events
                if row.get("data", {}).get("iteration_count") == prior.iteration_count
            ]
            if not any(row.get("event_type_name") in repairable for row in prior_events):
                raise AutonomousN7NodeError("N7_REOPEN_REQUIRES_DURABLE_DENOMINATOR_GAP")
        iteration = adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N7",
            input_version=input_version,
            delta_hash=delta_hash,
        )
        return adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            coverage_summary=coverage_summary,
            risk_summary={
                "covered_fail_total": covered_fail_total,
                "coverage_closed": True,
                "product_quality_pass": None,
            },
            reviewer_result={
                "result": "PASS",
                "runtime_owned": True,
                "evaluator_ref": "rc7-runtime-coverage-authority",
            },
            sufficiency_result={
                "result": "PASS",
                "all_canonical_layers_ready": True,
                "all_current_denominator_versions": True,
                "coverage_closure_independent_of_product_quality": True,
            },
        )

    def _reopen_n7(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        denominator: DurableCoverageDenominator,
    ) -> None:
        run_id = self._required(run_id, "N7_RUN_ID_REQUIRED")
        task_id = self.coverage._ensure_runtime_task(control, run_id)
        # A denominator expansion immediately invalidates the current execution
        # convergence projection, even before the new obligation is executed.
        append_entity(
            control.truth,
            Task(
                task_id=task_id,
                mission_id=control.mission_id,
                node="EXECUTION",
                task_type="RUNTIME",
                objective="close current L1-L7 coverage denominators",
                state=TaskStatus.READY,
                acceptance_criteria=[
                    "close expanded current denominator",
                    "do not reuse stale layer receipts",
                ],
            ),
            release_id=control.release_id,
        )
        adoption = WaveDNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=self.evidence_root,
        )
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N7",
        )
        if prior is None:
            return
        gap_id = _stable_id(
            "GAP-N7-DENOM-EXPANDED",
            control.mission_id,
            run_id,
            denominator.snapshot.layer,
            denominator.snapshot.denominator_hash,
        )
        gap = Gap(
            gap_id=gap_id,
            mission_id=control.mission_id,
            source_node="EXECUTION",
            category="COVERAGE_DENOMINATOR_EXPANDED",
            severity=GapSeverity.HIGH,
            target_node="EXECUTION",
            description="current coverage denominator expanded; stale READY receipt is invalid",
            subject_refs=[
                run_id,
                denominator.snapshot.layer,
                denominator.snapshot.target_id,
                denominator.snapshot.denominator_hash,
            ],
            evidence_refs=[denominator.evidence_id],
            acceptance_criteria=[
                "execute only newly uncovered obligations",
                "publish a READY receipt bound to the expanded denominator",
            ],
        )
        if not control.truth.query("rc7_gap", gap_id=gap_id):
            append_entity(control.truth, gap, release_id=control.release_id)
        existing = [
            row for row in adoption.node_control._events(control.mission_id, run_id, "N7")
            if row.get("event_type_name") == "NODE_GAP_DETECTED"
            and gap_id in set(str(x) for x in row.get("data", {}).get("gap_ids", []))
        ]
        if not existing:
            adoption.node_control.record_gap_detected(
                prior,
                gap_ids=[gap_id],
                evidence_refs=[denominator.evidence_id],
            )

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
            raise AutonomousN7NodeError(code)
        return rows[0]

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise AutonomousN7NodeError(code)
        return text
