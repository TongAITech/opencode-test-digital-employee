"""RC7.1 N7 durable coverage-driven execution closure.

Coverage is a versioned Runtime truth, not a case counter.  This service
persists frozen denominators, reconciles evidence-backed obligation states,
routes exact coverage gaps to the real owner, produces delta-only plans and
invalidates stale receipts when a denominator expands.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .autonomous_contract import (
    CANONICAL_COVERAGE_TARGETS,
    CanonicalLayer,
    CoverageDenominatorSnapshot,
    CoverageLedger,
    CoverageObligation,
    CoverageObligationState,
    LayerCoverageReceipt,
    require_layer,
)
from .autonomous_events import AutonomousEvent
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, EventRecord, Evidence, Gap, GapSeverity, Task, TaskStatus
from .truth_overlay import append_entity


class AutonomousCoverageClosureError(RuntimeError):
    pass


@dataclass(frozen=True)
class DurableCoverageDenominator:
    artifact_id: str
    evidence_id: str
    snapshot: CoverageDenominatorSnapshot


@dataclass(frozen=True)
class DurableLayerCoverageReceipt:
    artifact_id: str
    evidence_id: str
    receipt: LayerCoverageReceipt
    metrics: Mapping[str, float]
    delta_plan_artifact_id: str = ""


CAUSE_TARGETS: Dict[str, str] = {
    "REQUIREMENT_SOURCE": "REQUIREMENT_ANALYSIS",
    "DENOMINATOR_SOURCE": "REQUIREMENT_ANALYSIS",
    "CODE_IMPACT": "CODE_ANALYSIS",
    "MISSING_SCENARIO": "TEST_DESIGN",
    "ORACLE_DESIGN": "TEST_DESIGN",
    "DATA": "TEST_DATA_PREPARATION",
    "PRECONDITION": "TEST_DATA_PREPARATION",
    "AUTH": "TEST_DATA_PREPARATION",
    "SCRIPT": "SCRIPT_READINESS",
    "TRANSIENT": "EXECUTION",
    "FLAKY": "EXECUTION",
    "UNKNOWN": "FAILURE_DIAGNOSIS",
    "PRODUCT": "DEFECT",
}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class AutonomousCoverageClosureService:
    DENOMINATOR_TYPE = "LAYER_COVERAGE_DENOMINATOR"
    LEDGER_TYPE = "LAYER_COVERAGE_LEDGER"
    RECEIPT_TYPE = "LAYER_COVERAGE_RECEIPT"
    DELTA_PLAN_TYPE = "COVERAGE_DELTA_PLAN"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def freeze_denominator(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        layer: str,
        source_revision: str,
        target_id: str,
        obligation_ids: Sequence[str],
        evidence_refs: Sequence[str],
        excluded_obligation_ids: Sequence[str] = (),
        discovered_from_layer: str = "",
    ) -> DurableCoverageDenominator:
        run_id = self._required(run_id, "N7_RUN_ID_REQUIRED")
        layer = require_layer(layer).value
        source_revision = self._required(source_revision, "N7_SOURCE_REVISION_REQUIRED")
        target_id = self._required(target_id, "N7_TARGET_ID_REQUIRED")
        obligations = tuple(dict.fromkeys(self._required(x, "N7_OBLIGATION_ID_REQUIRED") for x in obligation_ids))
        if not obligations:
            raise AutonomousCoverageClosureError("N7_DENOMINATOR_EMPTY")
        excluded = tuple(dict.fromkeys(self._required(x, "N7_EXCLUDED_OBLIGATION_ID_REQUIRED") for x in excluded_obligation_ids))
        if not set(excluded).issubset(set(obligations)):
            raise AutonomousCoverageClosureError("N7_EXCLUSION_OUTSIDE_DENOMINATOR")
        evidence = self._require_evidence(control, evidence_refs, code="N7_DENOMINATOR_EVIDENCE")
        if discovered_from_layer:
            require_layer(discovered_from_layer)

        prior = self.current_denominator(control, layer=layer, target_id=target_id)
        prior_ids = set(prior.snapshot.obligation_ids) if prior else set()
        next_ids = set(obligations)
        if prior:
            if prior.snapshot.source_revision != source_revision:
                # A revision change is a new input version, but the prior denominator
                # still cannot silently disappear.  New scope must account for it.
                if not prior_ids.issubset(next_ids):
                    raise AutonomousCoverageClosureError("COVERAGE_DENOMINATOR_SHRINK_FORBIDDEN")
            elif not prior_ids.issubset(next_ids):
                raise AutonomousCoverageClosureError("COVERAGE_DENOMINATOR_SHRINK_FORBIDDEN")
            if prior_ids == next_ids and set(prior.snapshot.excluded_obligation_ids) == set(excluded):
                return prior
            version_number = self._version_number(prior.snapshot.denominator_version) + 1
        else:
            version_number = 1

        version = "v%04d" % version_number
        denominator_hash = "sha256:" + _sha({
            "mission_id": control.mission_id,
            "layer": layer,
            "source_revision": source_revision,
            "target_id": target_id,
            "obligation_ids": sorted(obligations),
            "excluded_obligation_ids": sorted(excluded),
        })
        snapshot = CoverageDenominatorSnapshot(
            mission_id=control.mission_id,
            layer=layer,
            source_revision=source_revision,
            target_id=target_id,
            denominator_version=version,
            denominator_hash=denominator_hash,
            obligation_ids=tuple(sorted(obligations)),
            evidence_refs=evidence,
            excluded_obligation_ids=tuple(sorted(excluded)),
        )
        payload = {
            "run_id": run_id,
            "snapshot": asdict(snapshot),
            "discovered_from_layer": discovered_from_layer,
            "prior_denominator_artifact_id": prior.artifact_id if prior else "",
        }
        artifact_id, evidence_id, _ = self._persist(
            control,
            producer_task_id=self._ensure_runtime_task(control, run_id),
            artifact_type=self.DENOMINATOR_TYPE,
            evidence_kind="LAYER_COVERAGE_DENOMINATOR_RECORD",
            payload=payload,
            parent_refs=[prior.artifact_id] if prior else [],
            subject_refs=[run_id, layer, target_id, version, denominator_hash] + list(evidence),
            relative=Path("n7") / control.mission_id / run_id / layer.lower() / ("denominator-%s.json" % version),
        )
        durable = DurableCoverageDenominator(artifact_id=artifact_id, evidence_id=evidence_id, snapshot=snapshot)
        event_name = AutonomousEvent.COVERAGE_DENOMINATOR_BUILT.value
        self._event(
            control,
            run_id=run_id,
            layer=layer,
            event_name=event_name,
            refs=[artifact_id, evidence_id] + list(evidence),
            data={
                "target_id": target_id,
                "denominator_version": version,
                "denominator_hash": denominator_hash,
                "obligation_count": len(obligations),
            },
        )
        if prior:
            self._event(
                control,
                run_id=run_id,
                layer=layer,
                event_name=AutonomousEvent.LAYER_DENOMINATOR_EXPANDED.value,
                refs=[prior.artifact_id, artifact_id, evidence_id],
                data={
                    "target_id": target_id,
                    "prior_version": prior.snapshot.denominator_version,
                    "current_version": version,
                    "added_obligation_ids": sorted(next_ids - prior_ids),
                    "discovered_from_layer": discovered_from_layer,
                },
            )
            self._event(
                control,
                run_id=run_id,
                layer=layer,
                event_name=AutonomousEvent.LAYER_REOPENED.value,
                refs=[prior.artifact_id, artifact_id],
                data={
                    "target_id": target_id,
                    "reason": "DENOMINATOR_EXPANDED",
                    "current_version": version,
                },
            )
        return durable

    def reconcile_layer(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        denominator: DurableCoverageDenominator,
        updates: Mapping[str, Mapping[str, Any]],
        metrics: Mapping[str, float],
    ) -> DurableLayerCoverageReceipt:
        run_id = self._required(run_id, "N7_RUN_ID_REQUIRED")
        current = self.current_denominator(
            control,
            layer=denominator.snapshot.layer,
            target_id=denominator.snapshot.target_id,
        )
        if not current or current.artifact_id != denominator.artifact_id:
            raise AutonomousCoverageClosureError("N7_STALE_DENOMINATOR_FORBIDDEN")
        prior = self._latest_ledger_payload(control, denominator)
        prior_by_id = {
            str(row["obligation_id"]): row
            for row in (prior.get("obligations", []) if prior else [])
            if isinstance(row, dict) and row.get("obligation_id")
        }
        unknown_updates = set(str(x) for x in updates) - set(denominator.snapshot.obligation_ids)
        if unknown_updates:
            raise AutonomousCoverageClosureError("N7_UPDATE_OUTSIDE_DENOMINATOR:%s" % ",".join(sorted(unknown_updates)))

        obligations = []
        routed_gaps = []
        for obligation_id in denominator.snapshot.obligation_ids:
            update = dict(updates.get(obligation_id) or {})
            prior_row = prior_by_id.get(obligation_id, {})
            state = str(update.get("state") or prior_row.get("state") or CoverageObligationState.UNEXECUTED.value).upper()
            evidence_refs = tuple(dict.fromkeys(
                str(x) for x in (update.get("evidence_refs") if "evidence_refs" in update else prior_row.get("evidence_refs", [])) if str(x)
            ))
            gap_ids = tuple(dict.fromkeys(
                str(x) for x in (prior_row.get("gap_ids", [])) if str(x)
            ))
            exclusion_reason = str(update.get("exclusion_reason") or prior_row.get("exclusion_reason") or "")
            if state in {
                CoverageObligationState.COVERED_PASS.value,
                CoverageObligationState.COVERED_FAIL.value,
                CoverageObligationState.EXCLUDED_WITH_EVIDENCE.value,
            }:
                self._require_evidence(control, evidence_refs, code="N7_COVERAGE_RESULT_EVIDENCE")
                gap_ids = ()
            elif state in {
                CoverageObligationState.UNEXECUTED.value,
                CoverageObligationState.BLOCKED.value,
            }:
                cause = str(update.get("cause") or "").upper()
                if cause:
                    gap_id = self._coverage_gap(
                        control,
                        run_id=run_id,
                        denominator=denominator,
                        obligation_id=obligation_id,
                        cause=cause,
                        evidence_refs=tuple(str(x) for x in update.get("evidence_refs") or denominator.snapshot.evidence_refs),
                    )
                    gap_ids = (gap_id,)
                    routed_gaps.append(gap_id)
            obligations.append(CoverageObligation(
                obligation_id=obligation_id,
                state=state,
                evidence_refs=evidence_refs,
                gap_ids=gap_ids,
                exclusion_reason=exclusion_reason,
            ))

        ledger = CoverageLedger(denominator=denominator.snapshot, obligations=tuple(obligations))
        normalized_metrics = self._validate_metrics(denominator.snapshot.layer, metrics)
        metric_gap_ids = []
        for metric_name, target in CANONICAL_COVERAGE_TARGETS[require_layer(denominator.snapshot.layer)].items():
            actual = normalized_metrics[metric_name]
            if actual + 1e-12 < target:
                metric_gap_ids.append(self._coverage_gap(
                    control,
                    run_id=run_id,
                    denominator=denominator,
                    obligation_id="METRIC:%s" % metric_name,
                    cause="TRANSIENT",
                    evidence_refs=denominator.snapshot.evidence_refs,
                    description="%s=%.6f target=%.6f" % (metric_name, actual, target),
                ))

        ledger_payload = {
            "run_id": run_id,
            "denominator_artifact_id": denominator.artifact_id,
            "denominator_version": denominator.snapshot.denominator_version,
            "denominator_hash": denominator.snapshot.denominator_hash,
            "layer": denominator.snapshot.layer,
            "target_id": denominator.snapshot.target_id,
            "obligations": [asdict(item) for item in ledger.obligations],
            "metrics": normalized_metrics,
        }
        ledger_artifact_id, ledger_evidence_id, _ = self._persist(
            control,
            producer_task_id=self._ensure_runtime_task(control, run_id),
            artifact_type=self.LEDGER_TYPE,
            evidence_kind="LAYER_COVERAGE_LEDGER_RECORD",
            payload=ledger_payload,
            parent_refs=[denominator.artifact_id],
            subject_refs=[run_id, denominator.snapshot.layer, denominator.snapshot.target_id, denominator.snapshot.denominator_hash],
            relative=Path("n7") / control.mission_id / run_id / denominator.snapshot.layer.lower() / ("ledger-%s-%s.json" % (denominator.snapshot.denominator_version, _sha(ledger_payload)[:16])),
        )

        open_gap_ids = tuple(dict.fromkeys(list(ledger.open_gap_ids) + metric_gap_ids))
        ready = ledger.closure_count == ledger.total and not ledger.blocked_obligation_ids and not open_gap_ids
        status = "READY" if ready else ("BLOCKED" if ledger.blocked_obligation_ids else "IN_PROGRESS")
        evidence_refs = tuple(dict.fromkeys(
            list(ledger.receipt().evidence_refs) + [denominator.evidence_id, ledger_evidence_id]
        ))
        receipt = LayerCoverageReceipt(
            layer=denominator.snapshot.layer,
            source_revision=denominator.snapshot.source_revision,
            target_id=denominator.snapshot.target_id,
            denominator_version=denominator.snapshot.denominator_version,
            denominator_hash=denominator.snapshot.denominator_hash,
            covered=ledger.closure_count,
            total=ledger.total,
            covered_pass=ledger.covered_pass,
            covered_fail=ledger.covered_fail,
            excluded_with_evidence=ledger.excluded_with_evidence,
            open_gap_ids=open_gap_ids,
            blocked_obligation_ids=ledger.blocked_obligation_ids,
            evidence_refs=evidence_refs,
            status=status,
        )
        delta_plan_artifact_id = ""
        if not ready:
            delta_plan_artifact_id = self._persist_delta_plan(
                control,
                run_id=run_id,
                denominator=denominator,
                ledger=ledger,
                metric_gap_ids=metric_gap_ids,
            )
        receipt_payload = {
            "run_id": run_id,
            "denominator_artifact_id": denominator.artifact_id,
            "ledger_artifact_id": ledger_artifact_id,
            "receipt": asdict(receipt),
            "metrics": normalized_metrics,
            "delta_plan_artifact_id": delta_plan_artifact_id,
            "quality_pass_required": False,
        }
        receipt_artifact_id, receipt_evidence_id, _ = self._persist(
            control,
            producer_task_id=self._ensure_runtime_task(control, run_id),
            artifact_type=self.RECEIPT_TYPE,
            evidence_kind="LAYER_COVERAGE_RECEIPT_RECORD",
            payload=receipt_payload,
            parent_refs=[denominator.artifact_id, ledger_artifact_id] + ([delta_plan_artifact_id] if delta_plan_artifact_id else []),
            subject_refs=[run_id, denominator.snapshot.layer, denominator.snapshot.target_id, denominator.snapshot.denominator_hash, status],
            relative=Path("n7") / control.mission_id / run_id / denominator.snapshot.layer.lower() / ("receipt-%s-%s.json" % (denominator.snapshot.denominator_version, _sha(receipt_payload)[:16])),
        )
        self._event(
            control,
            run_id=run_id,
            layer=denominator.snapshot.layer,
            event_name=AutonomousEvent.COVERAGE_MEASURED.value,
            refs=[denominator.artifact_id, ledger_artifact_id, receipt_artifact_id, receipt_evidence_id],
            data={
                "target_id": denominator.snapshot.target_id,
                "denominator_version": denominator.snapshot.denominator_version,
                "covered": receipt.covered,
                "total": receipt.total,
                "covered_pass": receipt.covered_pass,
                "covered_fail": receipt.covered_fail,
                "status": receipt.status,
                "metrics": normalized_metrics,
            },
        )
        if ready:
            self._event(
                control,
                run_id=run_id,
                layer=denominator.snapshot.layer,
                event_name=AutonomousEvent.COVERAGE_TARGET_REACHED.value,
                refs=[receipt_artifact_id, receipt_evidence_id],
                data={
                    "target_id": denominator.snapshot.target_id,
                    "denominator_version": denominator.snapshot.denominator_version,
                    "covered_fail": receipt.covered_fail,
                    "quality_pass_required": False,
                },
            )
            self._event(
                control,
                run_id=run_id,
                layer=denominator.snapshot.layer,
                event_name=AutonomousEvent.LAYER_COVERAGE_READY.value,
                refs=[receipt_artifact_id, receipt_evidence_id],
                data={
                    "target_id": denominator.snapshot.target_id,
                    "denominator_version": denominator.snapshot.denominator_version,
                    "denominator_hash": denominator.snapshot.denominator_hash,
                },
            )
        else:
            self._event(
                control,
                run_id=run_id,
                layer=denominator.snapshot.layer,
                event_name=AutonomousEvent.COVERAGE_GAP_DETECTED.value,
                refs=[receipt_artifact_id] + list(open_gap_ids),
                data={
                    "target_id": denominator.snapshot.target_id,
                    "denominator_version": denominator.snapshot.denominator_version,
                    "open_gap_ids": list(open_gap_ids),
                    "delta_plan_artifact_id": delta_plan_artifact_id,
                },
            )
        return DurableLayerCoverageReceipt(
            artifact_id=receipt_artifact_id,
            evidence_id=receipt_evidence_id,
            receipt=receipt,
            metrics=normalized_metrics,
            delta_plan_artifact_id=delta_plan_artifact_id,
        )

    def current_denominator(
        self,
        control: ClosedLoopControlPlane,
        *,
        layer: str,
        target_id: str,
    ) -> Optional[DurableCoverageDenominator]:
        layer = require_layer(layer).value
        candidates = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.DENOMINATOR_TYPE or row.get("state") != "VALID":
                continue
            payload = self._read_payload(row, "N7_DENOMINATOR_PAYLOAD_INVALID")
            snapshot_raw = payload.get("snapshot")
            if not isinstance(snapshot_raw, dict):
                continue
            if snapshot_raw.get("layer") != layer or snapshot_raw.get("target_id") != target_id:
                continue
            snapshot = CoverageDenominatorSnapshot(
                mission_id=str(snapshot_raw["mission_id"]),
                layer=str(snapshot_raw["layer"]),
                source_revision=str(snapshot_raw["source_revision"]),
                target_id=str(snapshot_raw["target_id"]),
                denominator_version=str(snapshot_raw["denominator_version"]),
                denominator_hash=str(snapshot_raw["denominator_hash"]),
                obligation_ids=tuple(snapshot_raw["obligation_ids"]),
                evidence_refs=tuple(snapshot_raw["evidence_refs"]),
                excluded_obligation_ids=tuple(snapshot_raw.get("excluded_obligation_ids") or []),
            )
            candidates.append((self._version_number(snapshot.denominator_version), row, snapshot))
        if not candidates:
            return None
        _, row, snapshot = max(candidates, key=lambda item: item[0])
        evidence_refs = tuple(str(x) for x in row.get("evidence_refs") or [])
        own_evidence = next((x for x in evidence_refs if x), "")
        if not own_evidence:
            raise AutonomousCoverageClosureError("N7_DENOMINATOR_ARTIFACT_EVIDENCE_REQUIRED")
        return DurableCoverageDenominator(
            artifact_id=str(row["artifact_id"]),
            evidence_id=own_evidence,
            snapshot=snapshot,
        )

    def _coverage_gap(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        denominator: DurableCoverageDenominator,
        obligation_id: str,
        cause: str,
        evidence_refs: Sequence[str],
        description: str = "",
    ) -> str:
        cause = str(cause or "").upper()
        target = CAUSE_TARGETS.get(cause)
        if not target:
            raise AutonomousCoverageClosureError("N7_COVERAGE_CAUSE_UNKNOWN:%s" % cause)
        # A product Oracle failure that reached the business target must be
        # represented as COVERED_FAIL and handled by N8/N9 quality flow, not as
        # an uncovered coverage gap.
        if cause == "PRODUCT":
            raise AutonomousCoverageClosureError("PRODUCT_FAILURE_IS_NOT_COVERAGE_GAP")
        evidence = self._require_evidence(control, evidence_refs, code="N7_GAP_EVIDENCE")
        gap_id = _stable_id(
            "GAP-N7-COVERAGE",
            control.mission_id,
            denominator.snapshot.denominator_hash,
            obligation_id,
            cause,
            target,
        )
        gap = Gap(
            gap_id=gap_id,
            mission_id=control.mission_id,
            source_node="EXECUTION",
            category="COVERAGE_GAP_%s" % cause,
            severity=GapSeverity.HIGH,
            target_node=target,
            description=description or "coverage obligation %s is not closed: %s" % (obligation_id, cause),
            subject_refs=[
                run_id,
                denominator.snapshot.layer,
                denominator.snapshot.target_id,
                denominator.snapshot.denominator_hash,
                obligation_id,
            ],
            evidence_refs=list(evidence),
            acceptance_criteria=[
                "repair only this uncovered obligation or its exact dependency",
                "produce new evidence/delta before re-execution",
                "reconcile against the current denominator version",
            ],
        )
        if not control.truth.query("rc7_gap", gap_id=gap_id):
            append_entity(control.truth, gap, release_id=control.release_id)
        self._event(
            control,
            run_id=run_id,
            layer=denominator.snapshot.layer,
            event_name=AutonomousEvent.COVERAGE_GAP_ROUTED.value,
            refs=[gap_id] + list(evidence),
            data={"obligation_id": obligation_id, "cause": cause, "target_node": target},
        )
        return gap_id

    def _persist_delta_plan(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        denominator: DurableCoverageDenominator,
        ledger: CoverageLedger,
        metric_gap_ids: Sequence[str],
    ) -> str:
        open_rows = []
        for item in ledger.obligations:
            if item.state in {
                CoverageObligationState.COVERED_PASS.value,
                CoverageObligationState.COVERED_FAIL.value,
                CoverageObligationState.EXCLUDED_WITH_EVIDENCE.value,
            }:
                continue
            targets = []
            for gap_id in item.gap_ids:
                rows = control.truth.query("rc7_gap", gap_id=gap_id)
                if len(rows) == 1:
                    targets.append(str(rows[0].get("target_node") or ""))
            open_rows.append({
                "obligation_id": item.obligation_id,
                "state": item.state,
                "gap_ids": list(item.gap_ids),
                "target_nodes": sorted(set(x for x in targets if x)),
            })
        payload = {
            "run_id": run_id,
            "layer": denominator.snapshot.layer,
            "target_id": denominator.snapshot.target_id,
            "denominator_version": denominator.snapshot.denominator_version,
            "denominator_hash": denominator.snapshot.denominator_hash,
            "delta_only": True,
            "closed_obligations_must_not_rerun": True,
            "open_obligations": open_rows,
            "metric_gap_ids": list(metric_gap_ids),
        }
        artifact_id, _, _ = self._persist(
            control,
            producer_task_id=self._ensure_runtime_task(control, run_id),
            artifact_type=self.DELTA_PLAN_TYPE,
            evidence_kind="COVERAGE_DELTA_PLAN_RECORD",
            payload=payload,
            parent_refs=[denominator.artifact_id],
            subject_refs=[run_id, denominator.snapshot.layer, denominator.snapshot.denominator_hash],
            relative=Path("n7") / control.mission_id / run_id / denominator.snapshot.layer.lower() / ("delta-%s.json" % _sha(payload)[:20]),
        )
        return artifact_id

    def _latest_ledger_payload(
        self,
        control: ClosedLoopControlPlane,
        denominator: DurableCoverageDenominator,
    ) -> Optional[Mapping[str, Any]]:
        candidates = []
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.LEDGER_TYPE or row.get("state") != "VALID":
                continue
            payload = self._read_payload(row, "N7_LEDGER_PAYLOAD_INVALID")
            if payload.get("denominator_artifact_id") != denominator.artifact_id:
                continue
            candidates.append((str(row.get("created_at") or ""), str(row.get("artifact_id") or ""), payload))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def _ensure_runtime_task(self, control: ClosedLoopControlPlane, run_id: str) -> str:
        task_id = _stable_id("TASK-N7-COVERAGE", control.mission_id, run_id)
        rows = control.truth.query("rc7_task", task_id=task_id)
        if rows:
            return task_id
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
                    "current versioned denominator for each required layer",
                    "exact delta execution for uncovered obligations",
                    "COVERED_FAIL counts coverage but not product quality pass",
                ],
            ),
            release_id=control.release_id,
        )
        return task_id

    def _persist(
        self,
        control: ClosedLoopControlPlane,
        *,
        producer_task_id: str,
        artifact_type: str,
        evidence_kind: str,
        payload: Mapping[str, Any],
        parent_refs: Sequence[str],
        subject_refs: Sequence[str],
        relative: Path,
    ) -> Tuple[str, str, str]:
        encoded = _canonical(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        path = self.evidence_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousCoverageClosureError("N7_IMMUTABLE_PAYLOAD_CONFLICT:%s" % path)
        if not path.exists():
            path.write_bytes(encoded)
        artifact_id = _stable_id("ART-N7", control.mission_id, artifact_type, digest)
        evidence_id = _stable_id("EVD-N7", control.mission_id, artifact_type, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=evidence_kind,
            source_ref="runtime://coverage-closure",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, producer_task_id] + [str(x) for x in subject_refs if str(x)],
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

    def _event(
        self,
        control: ClosedLoopControlPlane,
        *,
        run_id: str,
        layer: str,
        event_name: str,
        refs: Sequence[str],
        data: Mapping[str, Any],
    ) -> str:
        event_id = _stable_id("EVT-N7", control.mission_id, run_id, layer, event_name, _sha(data))
        if control.truth.query("rc7_control_event", event_id=event_id):
            return event_id
        append_entity(
            control.truth,
            EventRecord(
                event_id=event_id,
                mission_id=control.mission_id,
                event_type=event_name,
                subject_type="LAYER_COVERAGE",
                subject_id="%s:%s" % (run_id, layer),
                refs=[str(x) for x in refs if str(x)],
                data=dict(data, run_id=run_id, layer=layer),
            ),
            release_id=control.release_id,
        )
        return event_id

    def _require_evidence(
        self,
        control: ClosedLoopControlPlane,
        refs: Sequence[str],
        *,
        code: str,
    ) -> Tuple[str, ...]:
        values = tuple(dict.fromkeys(self._required(x, "%s_REQUIRED" % code) for x in refs))
        if not values:
            raise AutonomousCoverageClosureError("%s_REQUIRED" % code)
        for evidence_id in values:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                raise AutonomousCoverageClosureError("%s_NOT_UNIQUE:%s" % (code, evidence_id))
            if rows[0].get("mission_id") != control.mission_id:
                raise AutonomousCoverageClosureError("%s_MISSION_MISMATCH:%s" % (code, evidence_id))
        return values

    @staticmethod
    def _validate_metrics(layer: str, metrics: Mapping[str, float]) -> Dict[str, float]:
        if not isinstance(metrics, Mapping):
            raise AutonomousCoverageClosureError("N7_LAYER_METRICS_REQUIRED")
        required = CANONICAL_COVERAGE_TARGETS[require_layer(layer)]
        if set(metrics) != set(required):
            raise AutonomousCoverageClosureError("N7_LAYER_METRIC_SET_MISMATCH:%s" % layer)
        out = {}
        for name, value in metrics.items():
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise AutonomousCoverageClosureError("N7_LAYER_METRIC_INVALID:%s" % name) from exc
            if number < 0.0 or number > 1.0:
                raise AutonomousCoverageClosureError("N7_LAYER_METRIC_RANGE_INVALID:%s" % name)
            out[str(name)] = number
        return out

    @staticmethod
    def _read_payload(row: Mapping[str, Any], code: str) -> Mapping[str, Any]:
        ref = str(row.get("content_ref") or "")
        if not ref.startswith("file://"):
            raise AutonomousCoverageClosureError(code)
        path = Path(ref[len("file://"):])
        if not path.is_file():
            raise AutonomousCoverageClosureError(code)
        raw = path.read_bytes()
        expected = str(row.get("content_hash") or "")
        if expected != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise AutonomousCoverageClosureError("%s_HASH_MISMATCH" % code)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise AutonomousCoverageClosureError(code) from exc
        if not isinstance(payload, dict):
            raise AutonomousCoverageClosureError(code)
        return payload

    @staticmethod
    def _version_number(version: str) -> int:
        text = str(version or "")
        if len(text) != 5 or not text.startswith("v") or not text[1:].isdigit():
            raise AutonomousCoverageClosureError("N7_DENOMINATOR_VERSION_INVALID")
        return int(text[1:])

    @staticmethod
    def _required(value: object, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise AutonomousCoverageClosureError(code)
        return text
