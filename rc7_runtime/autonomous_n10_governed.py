"""Residual-risk governed N10 convergence and reporting.

The existing AutonomousN10Service remains the proven no-risk convergence engine.
This additive authority wraps it without creating a second runtime truth:

1. Reconstruct current ResidualRisk records from R1.
2. Fail closed while any risk is PENDING.
3. Persist a content-addressed risk-governance receipt.
4. Let the base N10 reconcile N1-N9/L1-L7 against that conformance receipt.
5. Supersede the candidate N10 manifest with an immutable governed manifest.
6. Publish a new N10 iteration whose Mission Evaluation is bound to the governed
   manifest, so ordinary converge_after_director_accept() consumes only current
   governed truth.

Test Sufficiency remains independent from Product Quality.  Dispositioned
residual risk yields SUFFICIENT_WITH_RESIDUAL_RISK and a CONDITIONAL release
recommendation; it is never silently converted into a testing failure or a
business release approval.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from .autonomous_contract import CANONICAL_LAYER_IDS
from .autonomous_events import AutonomousEvent
from .autonomous_n10_finalization import AutonomousN10FinalizationService
from .autonomous_n10_node import (
    AutonomousN10Error,
    AutonomousN10Service,
    FinalReportReceipt,
    N10PreparedNode,
    WaveFNodeAdoptionControl,
    _stable_id,
)
from .autonomous_residual_risk import ResidualRiskRegistry
from .closed_loop_control import ClosedLoopControlPlane
from .final_report import RC7FinalReportBuilder
from .models import Artifact, Evaluation, EvaluationResult, Evidence
from .truth_overlay import append_entity


class GovernedN10Error(AutonomousN10Error):
    pass


@dataclass(frozen=True)
class ResidualRiskGovernanceReceipt:
    artifact_id: str
    evidence_id: str
    receipt_sha256: str
    summary: Mapping[str, Any]


class GovernedAutonomousN10Service(AutonomousN10Service):
    RISK_GOVERNANCE_TYPE = "RESIDUAL_RISK_CONVERGENCE_RECEIPT"

    def prepare_ready(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> N10PreparedNode:
        registry = ResidualRiskRegistry(evidence_root=str(self.evidence_root))
        summary = registry.summary(control)
        risk_count = int(summary.get("risk_count") or 0)
        if risk_count == 0:
            return super().prepare_ready(control, run_id=run_id)
        pending = [str(x) for x in summary.get("pending_risk_ids") or []]
        if pending:
            raise GovernedN10Error(
                "N10_RESIDUAL_RISK_UNDISPOSED:%s" % ",".join(sorted(pending))
            )

        governance = self._persist_risk_governance(
            control,
            run_id=run_id,
            summary=summary,
        )
        candidate = super().prepare_ready(control, run_id=run_id)
        base_manifest = self._read_artifact_payload(
            control,
            candidate.manifest_artifact_id,
            expected_type=self.MANIFEST_TYPE,
            code="N10_BASE_MANIFEST_INVALID_FOR_RISK_GOVERNANCE",
        )
        governed_payload = dict(base_manifest)
        governed_payload["schema_version"] = "RC7_1_MISSION_EVIDENCE_MANIFEST_V3"
        governed_payload["residual_risk_summary"] = dict(summary)
        governed_payload["residual_risk_governance"] = {
            "receipt_artifact_id": governance.artifact_id,
            "receipt_evidence_id": governance.evidence_id,
            "receipt_sha256": governance.receipt_sha256,
        }
        readiness = dict(governed_payload.get("mission_readiness") or {})
        readiness.update(
            {
                "sufficiency_state": "SUFFICIENT_WITH_RESIDUAL_RISK",
                "release_recommendation": "CONDITIONAL",
                "residual_risk_count": risk_count,
                "residual_risk_dispositioned": True,
                "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
            }
        )
        governed_payload["mission_readiness"] = readiness
        completeness = dict(governed_payload.get("evidence_completeness") or {})
        completeness.update(
            {
                "residual_risk_registry_current": True,
                "residual_risk_all_dispositioned": True,
                "residual_risk_count": risk_count,
            }
        )
        governed_payload["evidence_completeness"] = completeness

        manifest_artifact_id, manifest_evidence_id, manifest_sha256 = self._persist_governed_manifest(
            control,
            run_id=run_id,
            task_id=candidate.task_id,
            payload=governed_payload,
            base_manifest_artifact_id=candidate.manifest_artifact_id,
            base_manifest_evidence_id=candidate.manifest_evidence_id,
            governance=governance,
            summary=summary,
        )
        evaluation_id = _stable_id(
            "EVAL-N10-RISK-GOVERNED",
            control.mission_id,
            run_id,
            manifest_sha256,
        )
        current_risk_evidence = [
            str(item["evidence_id"])
            for item in summary.get("risks") or []
            if isinstance(item, Mapping) and item.get("evidence_id")
        ]
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="MISSION_EVALUATION",
            artifact_refs=[manifest_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-independent-residual-risk-governance-authority",
            dimensions={
                "sufficiency_state": "SUFFICIENT_WITH_RESIDUAL_RISK",
                "coverage_state": "CLOSED",
                "quality_state": candidate.quality_state,
                "release_recommendation": "CONDITIONAL",
                "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
                "residual_risk_count": risk_count,
                "residual_risk_all_dispositioned": True,
                "manifest_sha256": manifest_sha256,
                "risk_governance_receipt_sha256": governance.receipt_sha256,
            },
            gap_refs=[],
            evidence_refs=list(
                dict.fromkeys(
                    [manifest_evidence_id, governance.evidence_id]
                    + current_risk_evidence
                )
            ),
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(control.truth, evaluation, release_id=control.release_id)
        self._pass_task(
            control,
            task_id=candidate.task_id,
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
        if prior is None:
            raise GovernedN10Error("N10_BASE_ITERATION_REQUIRED_FOR_RISK_GOVERNANCE")
        delta_hash = "sha256:" + manifest_sha256
        adoption.node_control.record_repair_completed(
            prior,
            repair_refs=[governance.evidence_id, manifest_evidence_id],
            delta_hash=delta_hash,
        )
        iteration = adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
            input_version="risk-governed-manifest:%s" % manifest_sha256,
            delta_hash=delta_hash,
        )
        artifact_refs = [manifest_artifact_id, governance.artifact_id] + [
            str(item["artifact_id"])
            for item in summary.get("risks") or []
            if isinstance(item, Mapping) and item.get("artifact_id")
        ]
        evidence_refs = [manifest_evidence_id, governance.evidence_id] + current_risk_evidence
        delivery = adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=candidate.task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=artifact_refs,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            coverage_summary=dict(candidate.delivery and base_manifest.get("layer_coverage") or {}),
            risk_summary={
                "quality_state": candidate.quality_state,
                "residual_risk_summary": dict(summary),
                "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
            },
            reviewer_result={
                "result": "PASS",
                "authority": "ResidualRiskRegistry+MissionConvergenceConformanceChecker",
                "risk_governance_receipt_artifact_id": governance.artifact_id,
            },
            sufficiency_result={
                "result": "PASS",
                "sufficiency_state": "SUFFICIENT_WITH_RESIDUAL_RISK",
                "coverage_state": "CLOSED",
                "quality_state": candidate.quality_state,
                "release_recommendation": "CONDITIONAL",
            },
        )
        self._event(
            control,
            run_id=run_id,
            event_name=AutonomousEvent.MISSION_READY_FOR_DIRECTOR_REVIEW.value,
            refs=[
                delivery.package_artifact_id,
                delivery.package_evidence_id,
                manifest_artifact_id,
                governance.artifact_id,
            ],
            data={
                "node_id": "N10",
                "iteration_count": delivery.iteration_count,
                "manifest_sha256": manifest_sha256,
                "sufficiency_state": "SUFFICIENT_WITH_RESIDUAL_RISK",
                "quality_state": candidate.quality_state,
                "release_recommendation": "CONDITIONAL",
                "residual_risk_count": risk_count,
            },
        )
        return N10PreparedNode(
            run_id=run_id,
            task_id=candidate.task_id,
            evaluation_id=evaluation_id,
            manifest_artifact_id=manifest_artifact_id,
            manifest_evidence_id=manifest_evidence_id,
            manifest_sha256=manifest_sha256,
            delivery=delivery,
            sufficiency_state="SUFFICIENT_WITH_RESIDUAL_RISK",
            release_recommendation="CONDITIONAL",
            quality_state=candidate.quality_state,
        )

    def generate_final_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> FinalReportReceipt:
        # No-risk Missions keep the proven base report path unchanged.
        summary = ResidualRiskRegistry(evidence_root=str(self.evidence_root)).summary(control)
        if int(summary.get("risk_count") or 0) == 0:
            return super().generate_final_report(control, run_id=run_id)

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
            raise GovernedN10Error("FINAL_REPORT_REQUIRES_CURRENT_CONVERGENCE_RECEIPT")
        convergence_artifact, convergence = convergence_artifacts[0]
        manifest_artifact_id = str(convergence.get("manifest_artifact_id") or "")
        manifest = self._read_artifact_payload(
            control,
            manifest_artifact_id,
            expected_type=self.MANIFEST_TYPE,
            code="FINAL_REPORT_MANIFEST_INVALID",
        )
        if manifest.get("residual_risk_summary") != summary:
            raise GovernedN10Error("FINAL_REPORT_RESIDUAL_RISK_SUMMARY_STALE")
        base = RC7FinalReportBuilder(control.truth).snapshot(control.mission_id)
        report = {
            "schema_version": "RC7_1_FINAL_REPORT_V2",
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
            "residual_risk_summary": manifest["residual_risk_summary"],
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
            raise GovernedN10Error("FINAL_REPORT_IMMUTABILITY_VIOLATION")
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
            evidence_refs=[evidence_id] + [
                str(item["evidence_id"])
                for item in summary.get("risks") or []
                if isinstance(item, Mapping) and item.get("evidence_id")
            ],
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
                "residual_risk_count": int(summary.get("risk_count") or 0),
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
        result = dict(super().reconcile_final_report(control, receipt=receipt))
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
        if manifest.get("residual_risk_summary") is not None:
            mismatches = list(result.get("mismatches") or [])
            if report.get("residual_risk_summary") != manifest.get("residual_risk_summary"):
                mismatches.append("residual_risk_summary")
            result = {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches}
        return result

    def _persist_risk_governance(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        summary: Mapping[str, Any],
    ) -> ResidualRiskGovernanceReceipt:
        risks = [dict(item) for item in summary.get("risks") or []]
        payload = {
            "schema_version": "RC7_1_RESIDUAL_RISK_CONVERGENCE_V1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "risk_count": int(summary.get("risk_count") or 0),
            "all_dispositioned": summary.get("all_dispositioned") is True,
            "counts_by_disposition": dict(summary.get("counts_by_disposition") or {}),
            "risks": risks,
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id / "residual-risk"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("residual-risk-governance-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise GovernedN10Error("RESIDUAL_RISK_GOVERNANCE_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N10-RISK-GOV", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-RISK-GOV", control.mission_id, run_id, digest)
        risk_artifacts = [str(item["artifact_id"]) for item in risks if item.get("artifact_id")]
        risk_evidence = [str(item["evidence_id"]) for item in risks if item.get("evidence_id")]
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.RISK_GOVERNANCE_TYPE,
            source_ref="runtime://n10-residual-risk-governance",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, run_id] + [str(item["risk_id"]) for item in risks],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.RISK_GOVERNANCE_TYPE,
            producer_task_id=_stable_id("TASK-N10-CONVERGENCE", control.mission_id, run_id),
            content_ref="file://" + str(path),
            parent_refs=risk_artifacts,
            evidence_refs=[evidence_id] + risk_evidence,
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return ResidualRiskGovernanceReceipt(artifact_id, evidence_id, digest, dict(summary))

    def _persist_governed_manifest(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        task_id: str,
        payload: Mapping[str, Any],
        base_manifest_artifact_id: str,
        base_manifest_evidence_id: str,
        governance: ResidualRiskGovernanceReceipt,
        summary: Mapping[str, Any],
    ) -> Tuple[str, str, str]:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("mission-evidence-manifest-governed-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise GovernedN10Error("N10_GOVERNED_MANIFEST_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id("EVD-N10-MANIFEST-V3", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-MANIFEST-V3", control.mission_id, run_id, digest)
        risks = [item for item in summary.get("risks") or [] if isinstance(item, Mapping)]
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.MANIFEST_TYPE,
            source_ref="runtime://n10-residual-risk-governed",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, task_id, run_id] + [str(item["risk_id"]) for item in risks],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.MANIFEST_TYPE,
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=[base_manifest_artifact_id, governance.artifact_id] + [
                str(item["artifact_id"]) for item in risks if item.get("artifact_id")
            ],
            evidence_refs=[evidence_id, base_manifest_evidence_id, governance.evidence_id] + [
                str(item["evidence_id"]) for item in risks if item.get("evidence_id")
            ],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return artifact_id, evidence_id, digest


class GovernedAutonomousN10FinalizationService(
    AutonomousN10FinalizationService,
    GovernedAutonomousN10Service,
):
    """Idempotent/report-projection facade with residual-risk governed N10 MRO."""

    def reconcile_final_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        receipt: FinalReportReceipt,
    ) -> Mapping[str, Any]:
        return GovernedAutonomousN10Service.reconcile_final_report(
            self,
            control,
            receipt=receipt,
        )
