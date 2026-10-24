"""RC7.1 N10 immutable Mission Evidence Manifest.

The manifest is a reconciliation artifact, never a new source of runtime truth.
It can be built only from current Director-accepted N1-N9 NodeDelivery packages,
current L1-L7 coverage receipts/denominators, formal runtime execution evidence,
terminal defect truth and independent Mission conformance.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .autonomous_contract import CANONICAL_LAYER_IDS, NodeLoopState
from .autonomous_coverage_closure import AutonomousCoverageClosureService
from .autonomous_events import AutonomousEvent
from .autonomous_node_control import AutonomousNodeControl
from .closed_loop_control import ClosedLoopControlPlane
from .mission_convergence_conformance import MissionConvergenceConformanceChecker
from .mission_formal_evidence_builder import R1FormalMissionEvidenceSnapshotBuilder
from .mission_sufficiency import MissionSufficiencyClosedLoop, MissionSufficiencyResult
from .models import Artifact, Evidence
from .truth_overlay import append_entity


class MissionEvidenceManifestError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MissionEvidenceManifestError(code)
    return text


_OPEN_GAP_STATES = {
    "OPEN", "PLANNED", "REPAIRING", "EVIDENCE_PENDING", "HUMAN_REQUIRED", "BLOCKED",
}
_ACTIVE_TASK_STATES = {
    "REGISTERED", "READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED", "EVALUATING",
    "REPAIR_REQUIRED", "BLOCKED", "HUMAN_REQUIRED", "FAILED", "STALE",
}
_TERMINAL_DEFECT_STATES = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}


@dataclass(frozen=True)
class BuiltMissionEvidenceManifest:
    artifact_id: str
    evidence_id: str
    manifest_sha256: str
    payload: Mapping[str, Any]
    sufficiency: MissionSufficiencyResult
    formal_snapshot_artifact_id: str
    formal_snapshot_evidence_id: str


class AutonomousMissionEvidenceManifestBuilder:
    MANIFEST_TYPE = "MISSION_EVIDENCE_MANIFEST"
    REQUIRED_NODE_IDS = tuple("N%d" % number for number in range(1, 10))

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def build(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        producer_task_id: str,
    ) -> BuiltMissionEvidenceManifest:
        run_id = _required(run_id, "N10_RUN_ID_REQUIRED")
        producer_task_id = _required(producer_task_id, "N10_PRODUCER_TASK_REQUIRED")
        self._require_no_unowned_active_work(control, producer_task_id=producer_task_id)
        self._require_no_open_gaps(control)

        node_truth = self.reconcile_node_deliveries(control, run_id=run_id)
        coverage_truth = self.reconcile_layer_coverage(
            control,
            run_id=run_id,
            n7_package=node_truth["N7"]["package"],
        )

        formal = R1FormalMissionEvidenceSnapshotBuilder(
            evidence_root=str(self.evidence_root / "formal-mission-evidence")
        ).build(
            control.truth,
            mission_id=control.mission_id,
            producer_task_id=producer_task_id,
        )
        sufficiency = MissionSufficiencyClosedLoop().evaluate(formal.snapshot)
        if sufficiency.evaluation.result.value != "PASS" or not sufficiency.report_ready:
            raise MissionEvidenceManifestError(
                "N10_MISSION_SUFFICIENCY_NOT_PASS:%s:%s"
                % (
                    sufficiency.sufficiency_state,
                    ",".join(gap.category for gap in sufficiency.gaps),
                )
            )

        convergence = MissionConvergenceConformanceChecker(control.truth).check(control.mission_id)
        if not convergence.enforced:
            raise MissionEvidenceManifestError("N10_MISSION_CONVERGENCE_CONTRACT_NOT_ENFORCED")
        if convergence.status != "PASS":
            raise MissionEvidenceManifestError(
                "N10_MISSION_CONVERGENCE_CONFORMANCE_FAILED:%s"
                % ",".join(convergence.violations)
            )

        quality = self._quality_ledger(control)
        defects = self._defect_ledger(control)
        node_artifact_ids = [
            str(node_truth[node_id]["package_artifact_id"])
            for node_id in self.REQUIRED_NODE_IDS
        ]
        coverage_artifact_ids = [
            str(coverage_truth[layer]["receipt_artifact_id"])
            for layer in CANONICAL_LAYER_IDS
        ]
        evidence_refs = tuple(dict.fromkeys(
            [
                str(node_truth[node_id]["package_evidence_id"])
                for node_id in self.REQUIRED_NODE_IDS
            ]
            + [
                str(coverage_truth[layer]["receipt_evidence_id"])
                for layer in CANONICAL_LAYER_IDS
            ]
            + [formal.evidence.evidence_id]
        ))
        self._require_evidence(control, evidence_refs)

        payload: Dict[str, Any] = {
            "schema_version": "RC7_1_MISSION_EVIDENCE_MANIFEST_V1",
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
            },
            "quality_ledger": quality,
            "defect_ledger": defects,
            "mission_sufficiency": {
                "evaluation_id": sufficiency.evaluation.evaluation_id,
                "sufficiency_state": sufficiency.sufficiency_state,
                "release_recommendation": sufficiency.release_recommendation,
                "metrics": dict(sufficiency.evaluation.dimensions.get("metrics") or {}),
                "report_ready": sufficiency.report_ready,
            },
            "mission_convergence_conformance": convergence.as_dict(),
            "evidence_completeness": {
                "required_nodes": list(self.REQUIRED_NODE_IDS),
                "accepted_node_count": len(node_truth),
                "required_layers": list(CANONICAL_LAYER_IDS),
                "ready_layer_count": len(coverage_truth),
                "evidence_ref_count": len(evidence_refs),
                "all_current": True,
            },
        }
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "n10" / control.mission_id / run_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("mission-evidence-manifest-" + digest[:20] + ".json")
        if path.exists() and path.read_bytes() != encoded:
            raise MissionEvidenceManifestError("N10_MANIFEST_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        evidence_id = _stable_id("EVD-N10-MANIFEST", control.mission_id, run_id, digest)
        artifact_id = _stable_id("ART-N10-MANIFEST", control.mission_id, run_id, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.MANIFEST_TYPE,
            source_ref="runtime://n10-mission-manifest",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, producer_task_id, run_id] + list(self.REQUIRED_NODE_IDS),
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.MANIFEST_TYPE,
            producer_task_id=producer_task_id,
            content_ref="file://" + str(path),
            parent_refs=node_artifact_ids + coverage_artifact_ids + [formal.artifact.artifact_id],
            evidence_refs=[evidence_id] + list(evidence_refs),
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id)
        return BuiltMissionEvidenceManifest(
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            manifest_sha256=digest,
            payload=payload,
            sufficiency=sufficiency,
            formal_snapshot_artifact_id=formal.artifact.artifact_id,
            formal_snapshot_evidence_id=formal.evidence.evidence_id,
        )

    def reconcile_node_deliveries(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
    ) -> Dict[str, Mapping[str, Any]]:
        run_id = _required(run_id, "N10_RUN_ID_REQUIRED")
        node_control = AutonomousNodeControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        out: Dict[str, Mapping[str, Any]] = {}
        for node_id in self.REQUIRED_NODE_IDS:
            iteration = node_control.latest_iteration(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id=node_id,
            )
            delivery = node_control.latest_delivery(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id=node_id,
            )
            if iteration is None or delivery is None:
                raise MissionEvidenceManifestError("N10_NODE_DELIVERY_REQUIRED:%s" % node_id)
            if delivery.iteration_count != iteration.iteration_count:
                raise MissionEvidenceManifestError("N10_STALE_NODE_DELIVERY:%s" % node_id)
            package = self._read_artifact_payload(
                control,
                delivery.package_artifact_id,
                expected_type="NODE_DELIVERY_PACKAGE",
                code="N10_NODE_DELIVERY_PACKAGE_INVALID:%s" % node_id,
            )
            if (
                package.get("mission_id") != control.mission_id
                or package.get("run_id") != run_id
                or package.get("node_id") != node_id
                or int(package.get("iteration_count") or 0) != iteration.iteration_count
                or package.get("input_version") != iteration.input_version
                or package.get("terminal_status") != NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value
            ):
                raise MissionEvidenceManifestError("N10_NODE_DELIVERY_IDENTITY_MISMATCH:%s" % node_id)
            if list(package.get("unresolved_gap_ids") or []):
                raise MissionEvidenceManifestError("N10_NODE_HAS_UNRESOLVED_GAPS:%s" % node_id)
            if list(package.get("blocked_item_ids") or []):
                raise MissionEvidenceManifestError("N10_NODE_HAS_BLOCKED_ITEMS:%s" % node_id)

            accept_events = [
                row
                for row in control.truth.query("rc7_control_event", mission_id=control.mission_id)
                if row.get("event_type_name") == AutonomousEvent.DIRECTOR_NODE_ACCEPTED.value
                and row.get("subject_type") == AutonomousNodeControl.SUBJECT_TYPE
                and row.get("subject_id") == AutonomousNodeControl._subject_id(run_id, node_id)
                and isinstance(row.get("data"), dict)
                and row["data"].get("iteration_count") == iteration.iteration_count
            ]
            if len(accept_events) != 1:
                raise MissionEvidenceManifestError(
                    "N10_CURRENT_DIRECTOR_ACCEPT_NOT_UNIQUE:%s:%d" % (node_id, len(accept_events))
                )
            accept = accept_events[0]
            director_eval_id = _required(
                accept.get("data", {}).get("evaluation_id"),
                "N10_DIRECTOR_EVALUATION_REQUIRED:%s" % node_id,
            )
            director_eval = self._one(
                control,
                "rc7_evaluation",
                "evaluation_id",
                director_eval_id,
                "N10_DIRECTOR_EVALUATION_NOT_UNIQUE:%s" % node_id,
            )
            if (
                director_eval.get("node") != "AUTONOMOUS_NODE_GATE"
                or director_eval.get("result") != "PASS"
                or director_eval.get("dimensions", {}).get("decision") != "ACCEPT"
                or director_eval.get("dimensions", {}).get("node_id") != node_id
                or delivery.package_artifact_id not in list(director_eval.get("artifact_refs") or [])
                or delivery.package_evidence_id not in list(director_eval.get("evidence_refs") or [])
            ):
                raise MissionEvidenceManifestError("N10_DIRECTOR_ACCEPT_EVALUATION_INVALID:%s" % node_id)
            terminal_events = [
                row
                for row in control.truth.query("rc7_control_event", mission_id=control.mission_id)
                if row.get("event_type_name") == AutonomousEvent.NODE_TERMINAL.value
                and row.get("subject_id") == AutonomousNodeControl._subject_id(run_id, node_id)
                and isinstance(row.get("data"), dict)
                and row["data"].get("iteration_count") == iteration.iteration_count
                and row["data"].get("state") == NodeLoopState.PASS.value
                and row["data"].get("evaluation_id") == director_eval_id
            ]
            if len(terminal_events) != 1:
                raise MissionEvidenceManifestError("N10_NODE_TERMINAL_PASS_REQUIRED:%s" % node_id)

            delivery_artifact = self._one(
                control,
                "rc7_artifact",
                "artifact_id",
                delivery.package_artifact_id,
                "N10_NODE_DELIVERY_ARTIFACT_NOT_UNIQUE:%s" % node_id,
            )
            actual_hash = str(delivery_artifact.get("content_hash") or "")
            if actual_hash != "sha256:" + delivery.package_sha256:
                raise MissionEvidenceManifestError("N10_NODE_DELIVERY_HASH_DRIFT:%s" % node_id)
            self._require_evidence(control, (delivery.package_evidence_id,))
            out[node_id] = {
                "iteration_count": iteration.iteration_count,
                "input_version": iteration.input_version,
                "package_artifact_id": delivery.package_artifact_id,
                "package_evidence_id": delivery.package_evidence_id,
                "package_sha256": delivery.package_sha256,
                "director_evaluation_id": director_eval_id,
                "director_accept_event_id": str(accept.get("event_id") or ""),
                "terminal_event_id": str(terminal_events[0].get("event_id") or ""),
                "package": package,
            }
        return out

    def reconcile_layer_coverage(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        n7_package: Mapping[str, Any],
    ) -> Dict[str, Mapping[str, Any]]:
        summary = n7_package.get("coverage_summary")
        if not isinstance(summary, dict) or set(summary) != set(CANONICAL_LAYER_IDS):
            raise MissionEvidenceManifestError("N10_N7_CANONICAL_LAYER_SUMMARY_REQUIRED")
        coverage = AutonomousCoverageClosureService(evidence_root=str(self.evidence_root))
        out: Dict[str, Mapping[str, Any]] = {}
        for layer in CANONICAL_LAYER_IDS:
            expected = summary[layer]
            if not isinstance(expected, dict):
                raise MissionEvidenceManifestError("N10_LAYER_SUMMARY_INVALID:%s" % layer)
            target_id = _required(expected.get("target_id"), "N10_LAYER_TARGET_REQUIRED:%s" % layer)
            current = coverage.current_denominator(control, layer=layer, target_id=target_id)
            if current is None:
                raise MissionEvidenceManifestError("N10_CURRENT_DENOMINATOR_REQUIRED:%s" % layer)
            if (
                current.snapshot.denominator_version != expected.get("denominator_version")
                or current.snapshot.denominator_hash != expected.get("denominator_hash")
            ):
                raise MissionEvidenceManifestError("N10_STALE_N7_LAYER_SUMMARY:%s" % layer)
            matches = []
            for artifact in control.truth.query("rc7_artifact", mission_id=control.mission_id):
                if artifact.get("artifact_type_name") != coverage.RECEIPT_TYPE or artifact.get("state") != "VALID":
                    continue
                payload = self._read_artifact_payload(
                    control,
                    str(artifact["artifact_id"]),
                    expected_type=coverage.RECEIPT_TYPE,
                    code="N10_LAYER_RECEIPT_INVALID:%s" % layer,
                )
                receipt = payload.get("receipt")
                if not isinstance(receipt, dict):
                    continue
                if (
                    payload.get("run_id") == run_id
                    and receipt.get("layer") == layer
                    and receipt.get("target_id") == target_id
                    and receipt.get("denominator_version") == current.snapshot.denominator_version
                    and receipt.get("denominator_hash") == current.snapshot.denominator_hash
                    and receipt.get("status") == "READY"
                ):
                    matches.append((artifact, payload))
            if len(matches) != 1:
                raise MissionEvidenceManifestError(
                    "N10_CURRENT_LAYER_RECEIPT_NOT_UNIQUE:%s:%d" % (layer, len(matches))
                )
            artifact, payload = matches[0]
            receipt = payload["receipt"]
            if (
                int(receipt.get("covered") or 0) != int(receipt.get("total") or 0)
                or list(receipt.get("open_gap_ids") or [])
                or list(receipt.get("blocked_obligation_ids") or [])
            ):
                raise MissionEvidenceManifestError("N10_LAYER_RECEIPT_NOT_CLOSED:%s" % layer)
            evidence_refs = list(artifact.get("evidence_refs") or [])
            if len(evidence_refs) != 1:
                raise MissionEvidenceManifestError("N10_LAYER_RECEIPT_EVIDENCE_REQUIRED:%s" % layer)
            self._require_evidence(control, tuple(evidence_refs))
            out[layer] = {
                "target_id": target_id,
                "denominator_artifact_id": current.artifact_id,
                "denominator_evidence_id": current.evidence_id,
                "denominator_version": current.snapshot.denominator_version,
                "denominator_hash": current.snapshot.denominator_hash,
                "obligation_count": len(current.snapshot.obligation_ids),
                "excluded_obligation_count": len(current.snapshot.excluded_obligation_ids),
                "receipt_artifact_id": str(artifact["artifact_id"]),
                "receipt_evidence_id": str(evidence_refs[0]),
                "covered": int(receipt["covered"]),
                "total": int(receipt["total"]),
                "covered_pass": int(receipt["covered_pass"]),
                "covered_fail": int(receipt["covered_fail"]),
                "excluded_with_evidence": int(receipt["excluded_with_evidence"]),
                "metrics": dict(payload.get("metrics") or {}),
                "status": "READY",
            }
        return out

    @staticmethod
    def _quality_ledger(control: ClosedLoopControlPlane) -> Mapping[str, Any]:
        rows = []
        for evaluation in control.truth.query("rc7_evaluation", mission_id=control.mission_id):
            if evaluation.get("node") != "EXECUTION":
                continue
            dims = evaluation.get("dimensions")
            if not isinstance(dims, dict):
                continue
            test_result = str(dims.get("test_result") or "").upper()
            if test_result not in {"PASS", "FAIL"}:
                continue
            rows.append({
                "evaluation_id": str(evaluation.get("evaluation_id") or ""),
                "attempt_id": str(dims.get("attempt_id") or ""),
                "purpose": str(dims.get("purpose") or "ORDINARY"),
                "test_result": test_result,
                "failure_class": str(dims.get("failure_class") or ""),
                "conclusive": dims.get("conclusive") is True,
                "evidence_refs": list(evaluation.get("evidence_refs") or []),
            })
        result_counts = {"PASS": 0, "FAIL": 0}
        product_fail_count = 0
        inconclusive_count = 0
        for row in rows:
            result_counts[row["test_result"]] += 1
            if row["test_result"] == "FAIL" and row["failure_class"] == "PRODUCT":
                product_fail_count += 1
            if not row["conclusive"]:
                inconclusive_count += 1
        return {
            "execution_evaluations": rows,
            "test_result_counts": result_counts,
            "product_fail_count": product_fail_count,
            "inconclusive_count": inconclusive_count,
            "all_recorded_from_r1": True,
        }

    @staticmethod
    def _defect_ledger(control: ClosedLoopControlPlane) -> Mapping[str, Any]:
        defects = control.truth.query("rc7_defect", mission_id=control.mission_id)
        counts: Dict[str, int] = {}
        items = []
        for row in defects:
            state = str(row.get("state") or "UNKNOWN")
            counts[state] = counts.get(state, 0) + 1
            items.append({
                "defect_id": str(row.get("defect_id") or ""),
                "source_gap_id": str(row.get("source_gap_id") or ""),
                "state": state,
                "severity": str(row.get("severity") or ""),
                "latest_evaluation_id": str(row.get("latest_evaluation_id") or ""),
            })
        nonterminal = sorted(
            item["defect_id"] for item in items if item["state"] not in _TERMINAL_DEFECT_STATES
        )
        if nonterminal:
            raise MissionEvidenceManifestError(
                "N10_NONTERMINAL_DEFECTS_REMAIN:%s" % ",".join(nonterminal)
            )
        return {
            "counts_by_state": dict(sorted(counts.items())),
            "defects": sorted(items, key=lambda item: item["defect_id"]),
            "terminal_disposition_complete": True,
        }

    @staticmethod
    def _require_no_open_gaps(control: ClosedLoopControlPlane) -> None:
        open_ids = sorted(
            str(row.get("gap_id") or "")
            for row in control.truth.query("rc7_gap", mission_id=control.mission_id)
            if str(row.get("state") or "") in _OPEN_GAP_STATES
        )
        if open_ids:
            raise MissionEvidenceManifestError("N10_OPEN_GAPS_REMAIN:%s" % ",".join(open_ids))

    @staticmethod
    def _require_no_unowned_active_work(
        control: ClosedLoopControlPlane,
        *,
        producer_task_id: str,
    ) -> None:
        active = sorted(
            str(row.get("task_id") or "")
            for row in control.truth.query("rc7_task", mission_id=control.mission_id)
            if str(row.get("state") or "") in _ACTIVE_TASK_STATES
            and str(row.get("task_id") or "") != producer_task_id
        )
        if active:
            raise MissionEvidenceManifestError("N10_ACTIVE_WORK_REMAINS:%s" % ",".join(active))

    def _read_artifact_payload(
        self,
        control: ClosedLoopControlPlane,
        artifact_id: str,
        *,
        expected_type: str,
        code: str,
    ) -> Mapping[str, Any]:
        row = self._one(control, "rc7_artifact", "artifact_id", artifact_id, code)
        if row.get("mission_id") != control.mission_id or row.get("state") != "VALID":
            raise MissionEvidenceManifestError(code)
        if row.get("artifact_type_name") != expected_type:
            raise MissionEvidenceManifestError(code)
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise MissionEvidenceManifestError(code)
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise MissionEvidenceManifestError(code)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise MissionEvidenceManifestError("%s_HASH_MISMATCH" % code)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MissionEvidenceManifestError(code) from exc
        if not isinstance(payload, dict):
            raise MissionEvidenceManifestError(code)
        return payload

    @staticmethod
    def _require_evidence(
        control: ClosedLoopControlPlane,
        refs: Sequence[str],
    ) -> None:
        if not refs:
            raise MissionEvidenceManifestError("N10_EVIDENCE_REQUIRED")
        for evidence_id in refs:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                raise MissionEvidenceManifestError("N10_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
            if rows[0].get("mission_id") != control.mission_id:
                raise MissionEvidenceManifestError("N10_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)

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
            raise MissionEvidenceManifestError(code)
        return rows[0]
