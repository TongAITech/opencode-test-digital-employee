from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_n10_finalization import AutonomousN10FinalizationService
from rc7_runtime.autonomous_n10_governed import (
    GovernedAutonomousN10FinalizationService,
    GovernedAutonomousN10Service,
    GovernedN10Error,
)
from rc7_runtime.autonomous_n10_node import (
    AutonomousN10Service,
    N10PreparedNode,
    WaveFNodeAdoptionControl,
)
from rc7_runtime.autonomous_residual_risk import ResidualRiskRegistry
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_convergence_conformance import MissionConvergenceConformanceChecker
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-N10-RISK"
RELEASE = "RC7.1-N10-RISK"
RUN = "RUN-N10-RISK"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove residual risk governance is part of N10 truth",
        ),
    )
    return truth, control


def _evidence(control: ClosedLoopControlPlane, evidence_id: str):
    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="RISK_SOURCE_EVIDENCE",
            source_ref="runtime://n10-risk-test",
            content_ref="evidence://" + evidence_id,
            subject_refs=[MISSION],
        ),
        release_id=RELEASE,
    )


def _seed_risk(control: ClosedLoopControlPlane, tmp_path: Path, *, dispose: bool):
    _evidence(control, "EVD-RISK-SOURCE")
    _evidence(control, "EVD-RISK-DISPOSITION")
    registry = ResidualRiskRegistry(evidence_root=str(tmp_path / "risk"))
    registry.record(
        control,
        risk_id="RISK-FIELD-TRAFFIC",
        source="N7/L6 performance observation",
        severity="HIGH",
        description="production-like traffic duration remains limited",
        reason="controlled engineering cannot reproduce bank production traffic profile",
        evidence_refs=["EVD-RISK-SOURCE"],
        owner="release-risk-owner",
    )
    if dispose:
        registry.disposition(
            control,
            risk_id="RISK-FIELD-TRAFFIC",
            disposition="MONITOR",
            acceptance_ref="risk-monitor://CAB-2026-001",
            evidence_refs=["EVD-RISK-DISPOSITION"],
        )
    return registry


def _fake_base_prepare(self, control: ClosedLoopControlPlane, *, run_id: str):
    task_id = self._ensure_task(control, run_id)
    payload = {
        "schema_version": "RC7_1_MISSION_EVIDENCE_MANIFEST_V2",
        "mission_id": MISSION,
        "release_id": RELEASE,
        "run_id": run_id,
        "source": "R1_EVENT_STREAM_RECONCILIATION",
        "node_deliveries": {"N%d" % n: {"status": "PASS"} for n in range(1, 10)},
        "layer_coverage": {"L%d" % n: {"covered": 1, "total": 1, "status": "READY"} for n in range(1, 8)},
        "formal_mission_snapshot": {"role": "FORMAL_EXECUTION_TRACEABILITY_NOT_PRODUCT_QUALITY_GATE"},
        "quality_ledger": {"product_fail_count": 0},
        "defect_ledger": {"counts_by_state": {}},
        "mission_readiness": {
            "sufficiency_state": "SUFFICIENT",
            "coverage_state": "CLOSED",
            "quality_state": "CONVERGED_CLEAN",
            "release_recommendation": "RECOMMENDED",
            "business_release_decision": "NOT_DECIDED_BY_TEST_SYSTEM",
        },
        "evidence_completeness": {"all_current": True},
    }
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    folder = Path(self.evidence_root) / "fake-base"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + ".json")
    path.write_bytes(encoded)
    evidence_id = "EVD-BASE-MANIFEST-" + digest[:12]
    artifact_id = "ART-BASE-MANIFEST-" + digest[:12]
    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="MISSION_EVIDENCE_MANIFEST",
            source_ref="runtime://n10-risk-test/base",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, task_id, run_id],
            content_hash="sha256:" + digest,
        ),
        release_id=RELEASE,
    )
    append_entity(
        control.truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=MISSION,
            artifact_type="MISSION_EVIDENCE_MANIFEST",
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        ),
        release_id=RELEASE,
    )
    evaluation_id = "EVAL-BASE-N10-" + digest[:12]
    append_entity(
        control.truth,
        Evaluation(
            evaluation_id=evaluation_id,
            mission_id=MISSION,
            node="MISSION_EVALUATION",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="base-n10-independent-gate",
            dimensions={
                "sufficiency_state": "SUFFICIENT",
                "quality_state": "CONVERGED_CLEAN",
                "release_recommendation": "RECOMMENDED",
            },
            evidence_refs=[evidence_id],
        ),
        release_id=RELEASE,
    )
    self._pass_task(
        control,
        task_id=task_id,
        evaluation_id=evaluation_id,
        artifact_id=artifact_id,
    )
    adoption = WaveFNodeAdoptionControl(
        control.truth,
        release_id=RELEASE,
        evidence_root=str(self.evidence_root),
    )
    iteration = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id=run_id,
        node_id="N10",
        input_version="manifest:%s" % digest,
        delta_hash="sha256:" + digest,
    )
    delivery = adoption.publish_ready_from_evaluated_task(
        iteration=iteration,
        source_task_id=task_id,
        source_evaluation_id=evaluation_id,
        artifact_refs=[artifact_id],
        evidence_refs=[evidence_id],
        risk_summary={"quality_state": "CONVERGED_CLEAN"},
        sufficiency_result={"result": "PASS", "sufficiency_state": "SUFFICIENT"},
    )
    return N10PreparedNode(
        run_id=run_id,
        task_id=task_id,
        evaluation_id=evaluation_id,
        manifest_artifact_id=artifact_id,
        manifest_evidence_id=evidence_id,
        manifest_sha256=digest,
        delivery=delivery,
        sufficiency_state="SUFFICIENT",
        release_recommendation="RECOMMENDED",
        quality_state="CONVERGED_CLEAN",
    )


def test_pending_residual_risk_blocks_n10_before_base_convergence(tmp_path: Path, monkeypatch):
    _, control = _control(tmp_path)
    _seed_risk(control, tmp_path, dispose=False)
    monkeypatch.setattr(AutonomousN10Service, "prepare_ready", _fake_base_prepare)
    service = GovernedAutonomousN10Service(evidence_root=str(tmp_path / "n10"))

    with pytest.raises(GovernedN10Error, match="N10_RESIDUAL_RISK_UNDISPOSED:RISK-FIELD-TRAFFIC"):
        service.prepare_ready(control, run_id=RUN)
    assert not [
        row for row in control.truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == "RESIDUAL_RISK_CONVERGENCE_RECEIPT"
    ]


def test_dispositioned_risk_creates_governed_n10_iteration_and_conditional_release(tmp_path: Path, monkeypatch):
    truth, control = _control(tmp_path)
    registry = _seed_risk(control, tmp_path, dispose=True)
    monkeypatch.setattr(AutonomousN10Service, "prepare_ready", _fake_base_prepare)
    service = GovernedAutonomousN10Service(evidence_root=str(tmp_path / "n10"))

    prepared = service.prepare_ready(control, run_id=RUN)

    assert prepared.sufficiency_state == "SUFFICIENT_WITH_RESIDUAL_RISK"
    assert prepared.release_recommendation == "CONDITIONAL"
    assert prepared.quality_state == "CONVERGED_CLEAN"
    assert prepared.delivery.iteration_count == 2
    manifest = service._read_artifact_payload(
        control,
        prepared.manifest_artifact_id,
        expected_type="MISSION_EVIDENCE_MANIFEST",
        code="manifest",
    )
    expected_summary = json.loads(
        json.dumps(registry.summary(control), ensure_ascii=False, sort_keys=True, default=str)
    )
    assert manifest["residual_risk_summary"] == expected_summary
    assert manifest["mission_readiness"]["sufficiency_state"] == "SUFFICIENT_WITH_RESIDUAL_RISK"
    assert manifest["mission_readiness"]["release_recommendation"] == "CONDITIONAL"
    assert manifest["mission_readiness"]["business_release_decision"] == "NOT_DECIDED_BY_TEST_SYSTEM"
    task = truth.query("rc7_task", task_id=prepared.task_id)[0]
    assert task["evaluation_id"] == prepared.evaluation_id
    evaluation = truth.query("rc7_evaluation", evaluation_id=prepared.evaluation_id)[0]
    assert evaluation["dimensions"]["residual_risk_count"] == 1
    assert evaluation["dimensions"]["release_recommendation"] == "CONDITIONAL"

    conformance_payload, violations = MissionConvergenceConformanceChecker(truth)._residual_risk_conformance(MISSION)
    assert violations == []
    assert conformance_payload["status"] == "PASS"
    assert conformance_payload["triggered"] is True


def test_residual_risk_conformance_rejects_unreceipted_risk_set(tmp_path: Path):
    truth, control = _control(tmp_path)
    _seed_risk(control, tmp_path, dispose=True)

    payload, violations = MissionConvergenceConformanceChecker(truth)._residual_risk_conformance(MISSION)
    assert payload["status"] == "FAIL"
    assert any("RESIDUAL_RISK_GOVERNANCE" in item for item in violations)


def test_governed_finalization_mro_uses_risk_governed_prepare(tmp_path: Path):
    service = GovernedAutonomousN10FinalizationService(evidence_root=str(tmp_path / "n10"))
    assert isinstance(service, AutonomousN10FinalizationService)
    assert service.prepare_ready.__func__ is GovernedAutonomousN10Service.prepare_ready
