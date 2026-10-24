"""RC7.1 Wave-F N10 Mission Truth Convergence.

Coverage sufficiency is authoritative from current N7 layer receipts, not from
"last assertion must PASS" counters. Formal execution snapshots remain required
evidence/traceability truth. Product COVERED_FAIL therefore remains a quality
failure without reopening already closed coverage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .autonomous_contract import CANONICAL_LAYER_IDS, NodeLoopState
from .autonomous_events import AutonomousEvent
from .autonomous_mission_manifest import AutonomousMissionEvidenceManifestBuilder
from .autonomous_node_control import AutonomousNodeControl, NodeDeliveryReceipt
from .autonomous_wave_e_nodes import WaveENodeAdoptionControl
from .closed_loop_control import ClosedLoopControlPlane
from .final_report import RC7FinalReportBuilder
from .mission_convergence_conformance import MissionConvergenceConformanceChecker
from .mission_formal_evidence_builder import R1FormalMissionEvidenceSnapshotBuilder
from .models import Artifact, Evaluation, EvaluationResult, EventRecord, Evidence, Task, TaskStatus
from .truth_overlay import append_entity


class AutonomousN10Error(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AutonomousN10Error(code)
    return text


@dataclass(frozen=True)
class N10PreparedNode:
    run_id: str
    task_id: str
    evaluation_id: str
    manifest_artifact_id: str
    manifest_evidence_id: str
    manifest_sha256: str
    delivery: NodeDeliveryReceipt
    sufficiency_state: str
    release_recommendation: str
    quality_state: str


@dataclass(frozen=True)
class MissionConvergenceReceipt:
    run_id: str
    mission_id: str
    manifest_artifact_id: str
    manifest_evidence_id: str
    n10_delivery_artifact_id: str
    n10_director_evaluation_id: str
    mission_evaluation_id: str
    artifact_id: str
    evidence_id: str
    receipt_sha256: str


@dataclass(frozen=True)
class FinalReportReceipt:
    run_id: str
    mission_id: str
    convergence_receipt_artifact_id: str
    manifest_artifact_id: str
    artifact_id: str
    evidence_id: str
    report_sha256: str
    report_path: str


class WaveFNodeAdoptionControl(WaveENodeAdoptionControl):
    @staticmethod
    def source_node(node_id: str) -> str:
        if str(node_id) == "N10":
            return "MISSION_EVALUATION"
        return WaveENodeAdoptionControl.source_node(node_id)


class AutonomousN10Service:
    MANIFEST_TYPE = "MISSION_EVIDENCE_MANIFEST"
    CONVERGENCE_RECEIPT_TYPE = "MISSION_CONVERGENCE_RECEIPT"
    FINAL_REPORT_TYPE = "RC7_1_FINAL_REPORT"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def prepare_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> N10PreparedNode:
        run_id = _required(run_id, "N10_RUN_ID_REQUIRED")
        task_id = self._ensure_task(control, run_id)
        manifest_tools = AutonomousMissionEvidenceManifestBuilder(
            evidence_root=str(self.evidence_root)
        )
        manifest_tools._require_no_unowned_active_work(control, producer_task_id=task_id)
        manifest_tools._require_no_open_gaps(control)
        node_truth = manifest_tools.reconcile_node_deliveries(control, run_id=run_id)
        coverage_truth = manifest_tools.reconcile_layer_coverage(
            control,
            run_id=run_id,
            n7_package=node_truth["N7"]["package"],
        )

        formal = R1FormalMissionEvidenceSnapshotBuilder(
            evidence_root=str(self.evidence_root / "formal-mission-evidence")
        ).build(
            control.truth,
            mission_id=control.mission_id,
            producer_task_id=task_id,
        )
        conformance = MissionConvergenceConformanceChecker(control.truth).check(control.mission_id)
        if not conformance.enforced:
            raise AutonomousN10Error("N10_MISSION_CONVERGENCE_CONTRACT_NOT_ENFORCED")
        if conformance.status != "PASS":
            raise AutonomousN10Error(
                "N10_MISSION_CONVERGENCE_CONFORMANCE_FAILED:%s"
                % ",".join(conformance.violations)
            )
        quality = manifest_tools._quality_ledger(control)
        defects = manifest_tools._defect_ledger(control)

        covered_fail_total = sum(
            int(coverage_truth[layer]["covered_fail"])
            for layer in CANONICAL_LAYER_IDS
        )
        total_coverage = sum(int(coverage_truth[layer]["total"]) for layer in CANONICAL_LAYER_IDS)
        closed_coverage = sum(int(coverage_truth[layer]["covered"]) for layer in CANONICAL_LAYER_IDS)
        if total_coverage != closed_coverage:
            raise AutonomousN10Error("N10_COVERAGE_TOTAL_NOT_CLOSED")
        product_fail_count = int(quality.get("product_fail_count") or 0)
        defect_count = len(defects.get("defects") or [])
        quality_state = (
            "CONVERGED_WITH_DEFECT_HISTORY"
            if covered_fail_total or product_fail_count or defect_count
            else "CONVERGED_CLEAN"
        )
        release_recommendation = (
            "RECOMMENDED_WITH_RESOLVED_DEFECT_HISTORY"
            if quality_state == "CONVERGED_WITH_DEFECT_HISTORY"
            else "RECOMMENDED"
        )
        sufficiency_state = "SUFFICIENT"

        payload: Dict[str, Any] = {
            "schema_version": "RC7_1_MISSION_EVIDENCE_MANIFEST_V2",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "source": "R1_EVENT_STREAM_RECONCILIATION",
            "node_deliveries": node_truth,
            "layer_coverage": coverage_truth,
            "formal_mission_snapshot": {
                "artifact_id": formal.artifact.artifact_id,
                "evidence_id": formal.evidence.evidence_id,
                "snapshot": asdict(formal.snapshot),
                "basis": formal.basis,
                "role": "FORMAL_EXECUTION_TRACEABILITY_NOT_PRODUCT_QUALITY_GATE",
            },
            "quality_ledger": quality,
            "defect_ledger": defects,
            "mission_convergence_conformance": conformance.as_dict(),
            "mission_readiness": {
                "sufficiency_state": sufficiency_state,
                "coverage_state": "CLOSED",
                "quality_state": quality_state,
                "covered_fail_total": covered_fail_total,
                "product_fail_count": product_fail_count,
                "release_recommendation": release_recommendation,
                "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
            },
            "evidence_completeness": {
                "required_nodes": ["N%d" % n for n in range(1, 10)],
                "accepted_node_count": len(node_truth),
                "required_layers": list(CANONICAL_LAYER_IDS),
                "ready_layer_count": len(coverage_truth),
                "formal_runtime_evidence": True,
                "independent_convergence_conformance": True,
                "all_current": True,
            },
        }
        manifest_artifact_id, manifest_evidence_id, manifest_sha256 = self._persist_manifest(
            control,
            run_id=run_id,
            task_id=task_id,
            payload=payload,
            node_truth=node_truth,
            coverage_truth=coverage_truth,
            formal_artifact_id=formal.artifact.artifact_id,
            formal_evidence_id=formal.evidence.evidence_id,
        )

        evaluation_id = _stable_id(
            "EVAL-N10-MISSION",
            control.mission_id,
            run_id,
            manifest_sha256,
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="MISSION_EVALUATION",
            artifact_refs=[manifest_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-independent-mission-convergence-authority",
            dimensions={
                "sufficiency_state": sufficiency_state,
                "coverage_state": "CLOSED",
                "quality_state": quality_state,
                "covered_fail_total": covered_fail_total,
                "product_fail_count": product_fail_count,
                "release_recommendation": release_recommendation,
                "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
                "manifest_sha256": manifest_sha256,
                "conformance_status": conformance.status,
            },
            gap_refs=[],
            evidence_refs=[manifest_evidence_id, formal.evidence.evidence_id],
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)
        self._pass_task(
            control,
            task_id=task_id,
            evaluation_id=evaluation_id,
            artifact_id=manifest_artifact_id,
        )

        adoption = WaveFNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        prior = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        existing = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        input_version = "manifest:%s" % manifest_sha256
        delta_hash = "sha256:" + manifest_sha256
        if prior is not None and prior.input_version == input_version and existing is not None:
            delivery = existing
        else:
            if prior is not None:
                adoption.node_control.record_repair_completed(
                    prior,
                    repair_refs=[manifest_evidence_id],
                    delta_hash=delta_hash,
                )
            iteration = adoption.node_control.start_iteration(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N10",
                input_version=input_version,
                delta_hash=delta_hash,
            )
            delivery = adoption.publish_ready_from_evaluated_task(
                iteration=iteration,
                source_task_id=task_id,
                source_evaluation_id=evaluation_id,
                artifact_refs=[manifest_artifact_id, formal.artifact.artifact_id],
                evidence_refs=[manifest_evidence_id, formal.evidence.evidence_id],
                coverage_summary={
                    layer: dict(coverage_truth[layer]) for layer in CANONICAL_LAYER_IDS
                },
                risk_summary={
                    "quality_state": quality_state,
                    "covered_fail_total": covered_fail_total,
                    "product_fail_count": product_fail_count,
                    "defect_counts": dict(defects.get("counts_by_state") or {}),
                    "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
                },
                reviewer_result={
                    "result": "PASS",
                    "authority": "MissionConvergenceConformanceChecker",
                    "conformance": conformance.as_dict(),
                },
                sufficiency_result={
                    "result": "PASS",
                    "sufficiency_state": sufficiency_state,
                    "coverage_state": "CLOSED",
                    "quality_state": quality_state,
                    "release_recommendation": release_recommendation,
                },
            )
        self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.MISSION_READY_FOR_DIRECTOR_REVIEW.value,
            refs=[delivery.package_artifact_id, delivery.package_evidence_id, manifest_artifact_id],
            data={
                "node_id": "N10",
                "iteration_count": delivery.iteration_count,
                "manifest_sha256": manifest_sha256,
                "sufficiency_state": sufficiency_state,
                "quality_state": quality_state,
            },
        )
        return N10PreparedNode(
            run_id=run_id,
            task_id=task_id,
            evaluation_id=evaluation_id,
            manifest_artifact_id=manifest_artifact_id,
            manifest_evidence_id=manifest_evidence_id,
            manifest_sha256=manifest_sha256,
            delivery=delivery,
            sufficiency_state=sufficiency_state,
            release_recommendation=release_recommendation,
            quality_state=quality_state,
        )

    def converge_after_director_accept(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> MissionConvergenceReceipt:
        run_id = _required(run_id, "N10_RUN_ID_REQUIRED")
        adoption = WaveFNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        iteration = adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        delivery = adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        if iteration is None or delivery is None or delivery.iteration_count != iteration.iteration_count:
            raise AutonomousN10Error("N10_CURRENT_DELIVERY_REQUIRED")
        accepted = [
            row
            for row in control.truth.query("rc7_control_event", mission_id=control.mission_id)
            if row.get("event_type_name") == AutonomousEvent.DIRECTOR_NODE_ACCEPTED.value
            and row.get("subject_type") == AutonomousNodeControl.SUBJECT_TYPE
            and row.get("subject_id") == AutonomousNodeControl._subject_id(run_id, "N10")
            and isinstance(row.get("data"), dict)
            and row["data"].get("iteration_count") == iteration.iteration_count
        ]
        if len(accepted) != 1:
            raise AutonomousN10Error("N10_DIRECTOR_ACCEPT_REQUIRED")
        director_evaluation_id = _required(
            accepted[0].get("data", {}).get("evaluation_id"),
            "N10_DIRECTOR_EVALUATION_REQUIRED",
        )
        director_eval = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            director_evaluation_id,
            "N10_DIRECTOR_EVALUATION_NOT_UNIQUE",
        )
        if director_eval.get("result") != "PASS" or director_eval.get("dimensions", {}).get("decision") != "ACCEPT":
            raise AutonomousN10Error("N10_DIRECTOR_ACCEPT_INVALID")

        task_id = _stable_id("TASK-N10-CONVERGENCE", control.mission_id, run_id)
        task = self._one(control, "rc7_task", "task_id", task_id, "N10_TASK_NOT_UNIQUE")
        if task.get("state") != "PASS":
            raise AutonomousN10Error("N10_SOURCE_TASK_PASS_REQUIRED")
        mission_eval_id = _required(task.get("evaluation_id"), "N10_MISSION_EVALUATION_REQUIRED")
        mission_eval_row = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            mission_eval_id,
            "N10_MISSION_EVALUATION_NOT_UNIQUE",
        )
        mission_eval = Evaluation(
            evaluation_id=str(mission_eval_row["evaluation_id"]),
            mission_id=str(mission_eval_row["mission_id"]),
            node=str(mission_eval_row["node"]),
            artifact_refs=list(mission_eval_row.get("artifact_refs") or []),
            result=EvaluationResult(str(mission_eval_row["result"])),
            evaluator_ref=str(mission_eval_row["evaluator_ref"]),
            dimensions=dict(mission_eval_row.get("dimensions") or {}),
            gap_refs=list(mission_eval_row.get("gap_refs") or []),
            evidence_refs=list(mission_eval_row.get("evidence_refs") or []),
        )
        mission = control.converge_mission(mission_eval)
        if mission.state.value != "CONVERGED":
            raise AutonomousN10Error("N10_MISSION_NOT_CONVERGED")

        manifest_artifact_id = str(mission_eval.artifact_refs[0])
        manifest = self._read_artifact_payload(
            control,
            manifest_artifact_id,
            expected_type=self.MANIFEST_TYPE,
            code="N10_MANIFEST_INVALID_AT_CONVERGENCE",
        )
        manifest_evidence_id = self._one(
            control,
            "rc7_artifact",
            "artifact_id",
            manifest_artifact_id,
            "N10_MANIFEST_ARTIFACT_NOT_UNIQUE",
        ).get("evidence_refs", [""])[0]
        payload = {
            "schema_version": "RC7_1_MISSION_CONVERGENCE_RECEIPT_V1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "mission_state": "CONVERGED",
            "sufficiency_state": mission_eval.dimensions.get("sufficiency_state"),
            "quality_state": mission_eval.dimensions.get("quality_state"),
            "release_recommendation": mission_eval.dimensions.get("release_recommendation"),
            "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
            "manifest_artifact_id": manifest_artifact_id,
            "manifest_sha256": hashlib.sha256(
                (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
            ).hexdigest(),
            "n10_delivery_artifact_id": delivery.package_artifact_id,
            "n10_delivery_evidence_id": delivery.package_evidence_id,
            "n10_director_evaluation_id": director_evaluation_id,
            "mission_evaluation_id": mission_eval_id,
        }
        artifact_id, evidence_id, receipt_sha256 = self._persist_receipt(
            control,
            run_id=run_id,
            task_id=task_id,
            payload=payload,
            parent_refs=[manifest_artifact_id, delivery.package_artifact_id],
            evidence_refs=[str(manifest_evidence_id), delivery.package_evidence_id],
        )
        mission_accept_event = self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.DIRECTOR_MISSION_ACCEPTED.value,
            refs=[str(accepted[0].get("event_id") or ""), director_evaluation_id, artifact_id],
            data={
                "node_id": "N10",
                "iteration_count": iteration.iteration_count,
                "director_evaluation_id": director_evaluation_id,
                "mission_evaluation_id": mission_eval_id,
                "state": "PASS",
            },
        )
        self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.MISSION_CONVERGED.value,
            refs=[mission_accept_event, artifact_id, evidence_id, manifest_artifact_id],
            data={
                "state": "CONVERGED",
                "sufficiency_state": mission_eval.dimensions.get("sufficiency_state"),
                "quality_state": mission_eval.dimensions.get("quality_state"),
            },
        )
        return MissionConvergenceReceipt(
            run_id=run_id,
            mission_id=control.mission_id,
            manifest_artifact_id=manifest_artifact_id,
            manifest_evidence_id=str(manifest_evidence_id),
            n10_delivery_artifact_id=delivery.package_artifact_id,
            n10_director_evaluation_id=director_evaluation_id,
            mission_evaluation_id=mission_eval_id,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            receipt_sha256=receipt_sha256,
        )

    def generate_final_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> FinalReportReceipt:
        run_id = _required(run_id, "N10_RUN_ID_REQUIRED")
        convergence_artifacts = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.CONVERGENCE_RECEIPT_TYPE:
                continue
            payload = self._read_artifact_payload(
                control,
                str(row["artifact_id"]),
                expected_type=self.CONVERGENCE_RECEIPT_TYPE,
                code="N10_CONVERGENCE_RECEIPT_INVALID",
            )
            if payload.get("run_id") == run_id and payload.get("mission_state") == "CONVERGED":
                convergence_artifacts.append((row, payload))
        if len(convergence_artifacts) != 1:
            raise AutonomousN10Error("FINAL_REPORT_REQUIRES_CURRENT_CONVERGENCE_RECEIPT")
        convergence_artifact, convergence = convergence_artifacts[0]
        manifest_artifact_id = _required(
            convergence.get("manifest_artifact_id"),
            "FINAL_REPORT_MANIFEST_REQUIRED",
        )
        manifest = self._read_artifact_payload(
            control,
            manifest_artifact_id,
            expected_type=self.MANIFEST_TYPE,
            code="FINAL_REPORT_MANIFEST_INVALID",
        )
        base = RC7FinalReportBuilder(control.truth).snapshot(control.mission_id)
        report = {
            "schema_version": "RC7_1_FINAL_REPORT_V1",
            "source": "MISSION_EVIDENCE_MANIFEST_AND_R1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "mission_state": "CONVERGED",
            "sufficiency_state": manifest["mission_readiness"]["sufficiency_state"],
            "quality_state": manifest["mission_readiness"]["quality_state"],
            "release_recommendation": manifest["mission_readiness"]["release_recommendation"],
            "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
            "node_deliveries": manifest["node_deliveries"],
            "layer_coverage": manifest["layer_coverage"],
            "quality_ledger": manifest["quality_ledger"],
            "defect_ledger": manifest["defect_ledger"],
            "formal_mission_snapshot": manifest["formal_mission_snapshot"],
            "evidence_completeness": manifest["evidence_completeness"],
            "convergence_receipt_artifact_id": str(convergence_artifact["artifact_id"]),
            "manifest_artifact_id": manifest_artifact_id,
            "base_r1_report": base,
        }
        encoded = (
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id / "final-report"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("final-report-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousN10Error("FINAL_REPORT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N10-FINAL-REPORT", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-FINAL-REPORT", control.mission_id, run_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.FINAL_REPORT_TYPE,
            source_ref="runtime://n10-final-report",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, str(convergence_artifact["artifact_id"]), manifest_artifact_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.FINAL_REPORT_TYPE,
            producer_task_id=_stable_id("TASK-N10-CONVERGENCE", control.mission_id, run_id),
            content_ref="file://" + str(path),
            parent_refs=[str(convergence_artifact["artifact_id"]), manifest_artifact_id],
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.FINAL_REPORT_GENERATED.value,
            refs=[artifact_id, evidence_id, str(convergence_artifact["artifact_id"]), manifest_artifact_id],
            data={
                "report_sha256": digest,
                "mission_state": "CONVERGED",
                "truth_source": "MISSION_EVIDENCE_MANIFEST_AND_R1",
            },
        )
        return FinalReportReceipt(
            run_id=run_id,
            mission_id=control.mission_id,
            convergence_receipt_artifact_id=str(convergence_artifact["artifact_id"]),
            manifest_artifact_id=manifest_artifact_id,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            report_sha256=digest,
            report_path=str(path),
        )

    def reconcile_final_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        receipt: FinalReportReceipt,
    ) -> Mapping[str, Any]:
        report = self._read_artifact_payload(
            control,
            receipt.artifact_id,
            expected_type=self.FINAL_REPORT_TYPE,
            code="FINAL_REPORT_ARTIFACT_INVALID",
        )
        manifest = self._read_artifact_payload(
            control,
            receipt.manifest_artifact_id,
            expected_type=self.MANIFEST_TYPE,
            code="FINAL_REPORT_MANIFEST_INVALID",
        )
        mismatches = []
        comparisons = {
            "mission_id": (report.get("mission_id"), manifest.get("mission_id")),
            "release_id": (report.get("release_id"), manifest.get("release_id")),
            "node_deliveries": (report.get("node_deliveries"), manifest.get("node_deliveries")),
            "layer_coverage": (report.get("layer_coverage"), manifest.get("layer_coverage")),
            "quality_ledger": (report.get("quality_ledger"), manifest.get("quality_ledger")),
            "defect_ledger": (report.get("defect_ledger"), manifest.get("defect_ledger")),
            "evidence_completeness": (
                report.get("evidence_completeness"),
                manifest.get("evidence_completeness"),
            ),
        }
        for field, values in comparisons.items():
            if values[0] != values[1]:
                mismatches.append(field)
        status = "PASS" if not mismatches else "FAIL"
        self._event(
            control,
            run_id=receipt.run_id,
            event_name=AutonomousEvent.FINAL_REPORT_RECONCILED.value,
            refs=[receipt.artifact_id, receipt.evidence_id, receipt.manifest_artifact_id],
            data={"status": status, "mismatches": mismatches},
        )
        return {"status": status, "mismatches": mismatches}

    def _ensure_task(self, control: ClosedLoopControlPlane, run_id: str) -> str:
        task_id = _stable_id("TASK-N10-CONVERGENCE", control.mission_id, run_id)
        rows = control.truth.query("rc7_task", task_id=task_id)
        if rows:
            return task_id
        append_entity(
            control.truth,
            Task(
                task_id=task_id,
                mission_id=control.mission_id,
                node="MISSION_EVALUATION",
                task_type="N10_CONVERGENCE",
                objective="reconcile current N1-N9, L1-L7, quality, defect and evidence truth",
                state=TaskStatus.READY,
                acceptance_criteria=[
                    "current Director-accepted N1-N9 delivery",
                    "current READY L1-L7 coverage receipts",
                    "formal runtime execution evidence",
                    "independent Mission convergence conformance PASS",
                    "no open Gap or nonterminal Defect",
                ],
            ),
            release_id=control.release_id,
            artifact_version=1,
        )
        self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.MISSION_RECONCILIATION_STARTED.value,
            refs=[task_id],
            data={"state": "IN_PROGRESS"},
        )
        return task_id

    @staticmethod
    def _pass_task(
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        evaluation_id: str,
        artifact_id: str,
    ) -> None:
        rows = control.truth.query("rc7_task", task_id=task_id)
        if len(rows) != 1:
            raise AutonomousN10Error("N10_TASK_NOT_UNIQUE")
        row = rows[0]
        if row.get("state") == "PASS" and row.get("evaluation_id") == evaluation_id:
            return
        append_entity(
            control.truth,
            Task(
                task_id=task_id,
                mission_id=control.mission_id,
                node="MISSION_EVALUATION",
                task_type="N10_CONVERGENCE",
                objective="reconcile current N1-N9, L1-L7, quality, defect and evidence truth",
                state=TaskStatus.PASS,
                output_artifact_refs=[artifact_id],
                evaluation_id=evaluation_id,
            ),
            release_id=control.release_id,
            artifact_version=int(row.get("artifact_version", 0)) + 1,
        )

    def _persist_manifest(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        task_id: str,
        payload: Mapping[str, Any],
        node_truth: Mapping[str, Mapping[str, Any]],
        coverage_truth: Mapping[str, Mapping[str, Any]],
        formal_artifact_id: str,
        formal_evidence_id: str,
    ) -> Tuple[str, str, str]:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("mission-evidence-manifest-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousN10Error("N10_MANIFEST_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N10-MANIFEST-V2", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-MANIFEST-V2", control.mission_id, run_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.MANIFEST_TYPE,
            source_ref="runtime://n10-convergence",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, task_id, run_id] + ["N%d" % n for n in range(1, 10)],
            content_hash="sha256:" + digest,
        )
        parent_refs = [
            str(node_truth["N%d" % n]["package_artifact_id"])
            for n in range(1, 10)
        ] + [
            str(coverage_truth[layer]["receipt_artifact_id"])
            for layer in CANONICAL_LAYER_IDS
        ] + [formal_artifact_id]
        evidence_refs = [evidence_id] + [
            str(node_truth["N%d" % n]["package_evidence_id"])
            for n in range(1, 10)
        ] + [
            str(coverage_truth[layer]["receipt_evidence_id"])
            for layer in CANONICAL_LAYER_IDS
        ] + [formal_evidence_id]
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.MANIFEST_TYPE,
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=parent_refs,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return artifact_id, evidence_id, digest

    def _persist_receipt(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        task_id: str,
        payload: Mapping[str, Any],
        parent_refs: Sequence[str],
        evidence_refs: Sequence[str],
    ) -> Tuple[str, str, str]:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("mission-convergence-receipt-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousN10Error("N10_CONVERGENCE_RECEIPT_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N10-CONVERGED", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-CONVERGED", control.mission_id, run_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.CONVERGENCE_RECEIPT_TYPE,
            source_ref="runtime://n10-convergence",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, task_id, run_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.CONVERGENCE_RECEIPT_TYPE,
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=list(parent_refs),
            evidence_refs=[evidence_id] + list(dict.fromkeys(str(x) for x in evidence_refs if str(x))),
            content_hash="sha256:" + digest,
        )
        append_entity(control.truth, evidence, release_id=control.release_id)
        append_entity(control.truth, artifact, release_id=control.release_id)
        return artifact_id, evidence_id, digest

    def _event(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        event_name: str,
        refs: Sequence[str],
        data: Mapping[str, Any],
    ) -> str:
        encoded = json.dumps(dict(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        event_id = _stable_id("EVT-N10", control.mission_id, run_id, event_name, encoded)
        if control.truth.query("rc7_control_event", event_id=event_id):
            return event_id
        append_entity(
            control.truth,
            EventRecord(
                event_id=event_id,
                mission_id=control.mission_id,
                event_type=event_name,
                subject_type="MISSION_CONVERGENCE",
                subject_id=run_id,
                refs=list(dict.fromkeys(str(x) for x in refs if str(x))),
                data=dict(data, run_id=run_id),
            ),
            release_id=control.release_id,
        )
        return event_id

    def _read_artifact_payload(
        self,
        control: ClosedLoopControlPlane,
        artifact_id: str,
        *,
        expected_type: str,
        code: str,
    ) -> Mapping[str, Any]:
        row = self._one(control, "rc7_artifact", "artifact_id", artifact_id, code)
        if row.get("mission_id") != control.mission_id or row.get("artifact_type_name") != expected_type:
            raise AutonomousN10Error(code)
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise AutonomousN10Error(code)
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise AutonomousN10Error(code)
        raw = path.read_bytes()
        if row.get("content_hash") != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise AutonomousN10Error("%s_HASH_MISMATCH" % code)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutonomousN10Error(code) from exc
        if not isinstance(payload, dict):
            raise AutonomousN10Error(code)
        return payload

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
            raise AutonomousN10Error(code)
        return rows[0]
