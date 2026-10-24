"""Idempotent N10 final-report finalization and rebuildable projections.

A final report is a projection of an already-converged Mission Evidence Manifest.
Repeated finalization replays the same immutable report instead of re-counting
R1 after the report itself has added Artifact/Evidence rows. External/back-office
projection success or failure is recorded separately and can never rewrite the
Mission test conclusion.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .autonomous_events import AutonomousEvent
from .autonomous_n10_node import (
    AutonomousN10Error,
    AutonomousN10Service,
    FinalReportReceipt,
)
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, EventRecord, Evidence
from .truth_overlay import append_entity


class N10FinalizationError(AutonomousN10Error):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class ReportProjectionReceipt:
    mission_id: str
    run_id: str
    report_artifact_id: str
    projector_ref: str
    status: str
    projection_ref: Optional[str]
    reason: Optional[str]
    artifact_id: str
    evidence_id: str
    receipt_sha256: str


class AutonomousN10FinalizationService(AutonomousN10Service):
    PROJECTION_RECEIPT_TYPE = "FINAL_REPORT_PROJECTION_RECEIPT"

    def generate_final_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> FinalReportReceipt:
        existing = self._existing_report(control, run_id=run_id)
        if existing is not None:
            reconciliation = self.reconcile_final_report(control, receipt=existing)
            if reconciliation.get("status") != "PASS":
                raise N10FinalizationError(
                    "EXISTING_FINAL_REPORT_RECONCILIATION_FAILED:%s"
                    % ",".join(reconciliation.get("mismatches") or [])
                )
            return existing
        return super().generate_final_report(control, run_id=run_id)

    def sync_projection(
        self,
        control: ClosedLoopControlPlane,
        *,
        report: FinalReportReceipt,
        projector_ref: str,
        projector: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> ReportProjectionReceipt:
        projector_ref = str(projector_ref or "").strip()
        if not projector_ref:
            raise N10FinalizationError("REPORT_PROJECTOR_REF_REQUIRED")
        mission_before = self._mission_state(control)
        if mission_before != "CONVERGED":
            raise N10FinalizationError("REPORT_PROJECTION_REQUIRES_CONVERGED_MISSION")
        report_payload = self._read_artifact_payload(
            control,
            report.artifact_id,
            expected_type=self.FINAL_REPORT_TYPE,
            code="REPORT_PROJECTION_FINAL_REPORT_INVALID",
        )
        if report_payload.get("run_id") != report.run_id:
            raise N10FinalizationError("REPORT_PROJECTION_RUN_MISMATCH")

        projection_ref: Optional[str] = None
        reason: Optional[str] = None
        status = "SYNCED"
        try:
            result = projector(report_payload)
            if not isinstance(result, Mapping):
                raise N10FinalizationError("REPORT_PROJECTOR_RESULT_MUST_BE_OBJECT")
            raw_ref = result.get("projection_ref")
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise N10FinalizationError("REPORT_PROJECTOR_PROJECTION_REF_REQUIRED")
            projection_ref = raw_ref.strip()
        except Exception as exc:  # projection failure is truth, not Mission failure
            status = "FAILED"
            reason = "%s:%s" % (exc.__class__.__name__, str(exc))

        payload = {
            "schema_version": "RC7_1_REPORT_PROJECTION_RECEIPT_V1",
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": report.run_id,
            "report_artifact_id": report.artifact_id,
            "report_sha256": report.report_sha256,
            "projector_ref": projector_ref,
            "status": status,
            "projection_ref": projection_ref,
            "reason": reason,
            "mission_state_before": mission_before,
            "truth_effect": "PROJECTION_ONLY",
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / report.run_id / "projection"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (
            "%s-%s-%s.json"
            % (projector_ref.replace("/", "_"), status.lower(), digest[:20])
        )
        if not path.exists():
            path.write_bytes(encoded)
        elif path.read_bytes() != encoded:
            raise N10FinalizationError("REPORT_PROJECTION_RECEIPT_IMMUTABILITY_VIOLATION")

        evidence_id = _stable_id(
            "EVD-REPORT-PROJECTION",
            control.mission_id,
            report.run_id,
            report.artifact_id,
            projector_ref,
            digest,
        )
        artifact_id = _stable_id(
            "ART-REPORT-PROJECTION",
            control.mission_id,
            report.run_id,
            report.artifact_id,
            projector_ref,
            digest,
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.PROJECTION_RECEIPT_TYPE,
            source_ref="runtime://n10-report-projection",
            content_ref="file://" + str(path),
            subject_refs=[report.artifact_id, projector_ref, status]
            + ([projection_ref] if projection_ref else []),
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.PROJECTION_RECEIPT_TYPE,
            producer_task_id=_stable_id(
                "TASK-N10-CONVERGENCE", control.mission_id, report.run_id
            ),
            content_ref="file://" + str(path),
            parent_refs=[report.artifact_id, report.convergence_receipt_artifact_id],
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)

        event_name = (
            AutonomousEvent.REPORT_PROJECTION_SYNCED.value
            if status == "SYNCED"
            else AutonomousEvent.REPORT_PROJECTION_FAILED.value
        )
        self._projection_event(
            control,
            run_id=report.run_id,
            event_name=event_name,
            refs=[report.artifact_id, artifact_id, evidence_id]
            + ([projection_ref] if projection_ref else []),
            data={
                "projector_ref": projector_ref,
                "status": status,
                "projection_ref": projection_ref,
                "reason": reason,
                "truth_effect": "PROJECTION_ONLY",
            },
        )
        mission_after = self._mission_state(control)
        if mission_after != mission_before:
            raise N10FinalizationError("REPORT_PROJECTION_MUTATED_MISSION_TRUTH")
        return ReportProjectionReceipt(
            mission_id=control.mission_id,
            run_id=report.run_id,
            report_artifact_id=report.artifact_id,
            projector_ref=projector_ref,
            status=status,
            projection_ref=projection_ref,
            reason=reason,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            receipt_sha256=digest,
        )

    def _existing_report(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> Optional[FinalReportReceipt]:
        matches = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.FINAL_REPORT_TYPE:
                continue
            payload = self._read_artifact_payload(
                control,
                str(row["artifact_id"]),
                expected_type=self.FINAL_REPORT_TYPE,
                code="EXISTING_FINAL_REPORT_INVALID",
            )
            if payload.get("run_id") != run_id:
                continue
            evidence_refs = list(row.get("evidence_refs") or [])
            if len(evidence_refs) != 1:
                raise N10FinalizationError("EXISTING_FINAL_REPORT_EVIDENCE_NOT_UNIQUE")
            evidence_rows = control.truth.query("rc7_evidence", evidence_id=evidence_refs[0])
            if len(evidence_rows) != 1 or evidence_rows[0].get("mission_id") != control.mission_id:
                raise N10FinalizationError("EXISTING_FINAL_REPORT_EVIDENCE_INVALID")
            content_hash = str(row.get("content_hash") or "")
            if not content_hash.startswith("sha256:"):
                raise N10FinalizationError("EXISTING_FINAL_REPORT_HASH_REQUIRED")
            matches.append(
                FinalReportReceipt(
                    run_id=run_id,
                    mission_id=control.mission_id,
                    convergence_receipt_artifact_id=str(
                        payload.get("convergence_receipt_artifact_id") or ""
                    ),
                    manifest_artifact_id=str(payload.get("manifest_artifact_id") or ""),
                    artifact_id=str(row["artifact_id"]),
                    evidence_id=str(evidence_refs[0]),
                    report_sha256=content_hash[len("sha256:"):],
                    report_path=str(row.get("content_ref") or "")[len("file://"):],
                )
            )
        if len(matches) > 1:
            raise N10FinalizationError("EXISTING_FINAL_REPORT_NOT_UNIQUE:%d" % len(matches))
        return matches[0] if matches else None

    @staticmethod
    def _mission_state(control: ClosedLoopControlPlane) -> str:
        rows = control.truth.query("rc7_mission", mission_id=control.mission_id)
        if len(rows) != 1:
            raise N10FinalizationError("REPORT_PROJECTION_MISSION_NOT_UNIQUE")
        return str(rows[0].get("state") or "")

    @staticmethod
    def _projection_event(
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        event_name: str,
        refs: Sequence[str],
        data: Mapping[str, Any],
    ) -> str:
        encoded = json.dumps(dict(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        event_id = _stable_id(
            "EVT-REPORT-PROJECTION",
            control.mission_id,
            run_id,
            event_name,
            encoded,
        )
        if not control.truth.query("rc7_control_event", event_id=event_id):
            append_entity(
                control.truth,
                EventRecord(
                    event_id=event_id,
                    mission_id=control.mission_id,
                    event_type=event_name,
                    subject_type="FINAL_REPORT_PROJECTION",
                    subject_id=run_id,
                    refs=list(dict.fromkeys(str(x) for x in refs if str(x))),
                    data=dict(data, run_id=run_id),
                ),
                release_id=control.release_id,
            )
        return event_id
