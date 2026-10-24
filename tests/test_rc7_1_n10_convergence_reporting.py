from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_contract import CANONICAL_LAYER_IDS
from rc7_runtime.autonomous_mission_manifest import AutonomousMissionEvidenceManifestBuilder
from rc7_runtime.autonomous_n10_node import (
    AutonomousN10Error,
    AutonomousN10Service,
    WaveFNodeAdoptionControl,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_convergence_conformance import MissionConvergenceConformanceChecker
from rc7_runtime.mission_formal_evidence_builder import R1FormalMissionEvidenceSnapshotBuilder
from rc7_runtime.mission_sufficiency import MissionEvidenceSnapshot
from rc7_runtime.models import Artifact, Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-N10-ORCHESTRATION"
RELEASE = "RC7.1-N10-ORCHESTRATION"
RUN = "RUN-N10-ORCHESTRATION"


@dataclass(frozen=True)
class _FakeConformance:
    status: str = "PASS"
    enforced: bool = True
    violations: tuple = ()

    def as_dict(self):
        return {
            "status": self.status,
            "enforced": self.enforced,
            "violations": list(self.violations),
        }


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove N10 convergence ordering and report projection",
        ),
    )
    return truth, control


def _seed_ref(control: ClosedLoopControlPlane, *, artifact_id: str, evidence_id: str, artifact_type: str):
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind=artifact_type + "_EVIDENCE",
        source_ref="runtime://n10-test",
        content_ref="evidence://" + evidence_id,
        subject_refs=[artifact_id],
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type=artifact_type,
        producer_task_id="TASK-SEED-" + artifact_id,
        content_ref="artifact://" + artifact_id,
        evidence_refs=[evidence_id],
    )
    append_entity(control.truth, evidence, release_id=RELEASE)
    append_entity(control.truth, artifact, release_id=RELEASE)
    return artifact, evidence


def _patch_prepare_dependencies(monkeypatch, control: ClosedLoopControlPlane):
    node_truth = {}
    for number in range(1, 10):
        node_id = "N%d" % number
        artifact, evidence = _seed_ref(
            control,
            artifact_id="ART-NODE-" + node_id,
            evidence_id="EVD-NODE-" + node_id,
            artifact_type="NODE_DELIVERY_PACKAGE",
        )
        node_truth[node_id] = {
            "package_artifact_id": artifact.artifact_id,
            "package_evidence_id": evidence.evidence_id,
            "package": {"coverage_summary": {}},
        }

    coverage_truth = {}
    for layer in CANONICAL_LAYER_IDS:
        artifact, evidence = _seed_ref(
            control,
            artifact_id="ART-LAYER-" + layer,
            evidence_id="EVD-LAYER-" + layer,
            artifact_type="LAYER_COVERAGE_RECEIPT",
        )
        coverage_truth[layer] = {
            "target_id": "TARGET-" + layer,
            "denominator_artifact_id": "ART-DENOM-" + layer,
            "denominator_evidence_id": "EVD-DENOM-" + layer,
            "denominator_version": "v0001",
            "denominator_hash": "sha256:" + layer.lower() * 8,
            "obligation_count": 1,
            "excluded_obligation_count": 0,
            "receipt_artifact_id": artifact.artifact_id,
            "receipt_evidence_id": evidence.evidence_id,
            "covered": 1,
            "total": 1,
            "covered_pass": 0 if layer == "L3" else 1,
            "covered_fail": 1 if layer == "L3" else 0,
            "excluded_with_evidence": 0,
            "metrics": {"contract_metric": 1.0},
            "status": "READY",
        }

    formal_artifact, formal_evidence = _seed_ref(
        control,
        artifact_id="ART-FORMAL-N10",
        evidence_id="EVD-FORMAL-N10",
        artifact_type="MISSION_EVIDENCE_SNAPSHOT",
    )
    formal_snapshot = MissionEvidenceSnapshot(
        mission_id=MISSION,
        release_id=RELEASE,
        snapshot_ref="formal://n10-product-fail",
        evidence_refs=(formal_evidence.evidence_id,),
        critical_requirements_total=1,
        critical_requirements_verified=0,
        unverified_requirement_refs=("REQ-PRODUCT-FAIL",),
        critical_obligations_total=1,
        critical_obligations_verified=0,
        unverified_obligation_refs=("OBL-PRODUCT-FAIL",),
        critical_branches_total=1,
        critical_branches_verified=0,
        unverified_branch_refs=("BRANCH-PRODUCT-FAIL",),
        critical_executions_total=1,
        critical_executions_conclusive=0,
        inconclusive_execution_refs=("TC-PRODUCT-FAIL",),
    )
    formal = SimpleNamespace(
        artifact=formal_artifact,
        evidence=formal_evidence,
        snapshot=formal_snapshot,
        basis={"formal_runtime_record_count": 1},
    )

    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "_require_no_unowned_active_work",
        lambda self, control, producer_task_id: None,
    )
    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "_require_no_open_gaps",
        lambda self, control: None,
    )
    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "reconcile_node_deliveries",
        lambda self, control, run_id: node_truth,
    )
    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "reconcile_layer_coverage",
        lambda self, control, run_id, n7_package: coverage_truth,
    )
    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "_quality_ledger",
        staticmethod(
            lambda control: {
                "execution_evaluations": [
                    {
                        "evaluation_id": "EVAL-PRODUCT-FAIL",
                        "attempt_id": "ATT-PRODUCT-FAIL",
                        "purpose": "ORDINARY",
                        "test_result": "FAIL",
                        "failure_class": "PRODUCT",
                        "conclusive": True,
                        "evidence_refs": ["EVD-FORMAL-N10"],
                    }
                ],
                "test_result_counts": {"PASS": 0, "FAIL": 1},
                "product_fail_count": 1,
                "inconclusive_count": 0,
                "all_recorded_from_r1": True,
            }
        ),
    )
    monkeypatch.setattr(
        AutonomousMissionEvidenceManifestBuilder,
        "_defect_ledger",
        staticmethod(
            lambda control: {
                "counts_by_state": {"CLOSED": 1},
                "defects": [
                    {
                        "defect_id": "DEFECT-1",
                        "source_gap_id": "GAP-PRODUCT-1",
                        "state": "CLOSED",
                        "severity": "HIGH",
                        "latest_evaluation_id": "EVAL-DEFECT-CLOSED",
                    }
                ],
                "terminal_disposition_complete": True,
            }
        ),
    )
    monkeypatch.setattr(
        R1FormalMissionEvidenceSnapshotBuilder,
        "build",
        lambda self, truth, mission_id, producer_task_id: formal,
    )
    monkeypatch.setattr(
        MissionConvergenceConformanceChecker,
        "check",
        lambda self, mission_id: _FakeConformance(),
    )
    return coverage_truth


def test_n10_uses_coverage_closure_even_when_formal_snapshot_contains_product_fail(tmp_path: Path, monkeypatch):
    truth, control = _control(tmp_path)
    _patch_prepare_dependencies(monkeypatch, control)
    service = AutonomousN10Service(evidence_root=str(tmp_path / "n10"))

    prepared = service.prepare_ready(control, run_id=RUN)

    assert prepared.sufficiency_state == "SUFFICIENT"
    assert prepared.quality_state == "CONVERGED_WITH_DEFECT_HISTORY"
    assert prepared.release_recommendation == "RECOMMENDED_WITH_RESOLVED_DEFECT_HISTORY"
    manifest = service._read_artifact_payload(
        control,
        prepared.manifest_artifact_id,
        expected_type="MISSION_EVIDENCE_MANIFEST",
        code="manifest",
    )
    assert manifest["layer_coverage"]["L3"]["covered_fail"] == 1
    assert manifest["mission_readiness"]["coverage_state"] == "CLOSED"
    assert manifest["mission_readiness"]["quality_state"] == "CONVERGED_WITH_DEFECT_HISTORY"
    assert manifest["formal_mission_snapshot"]["snapshot"]["critical_executions_conclusive"] == 0
    assert manifest["formal_mission_snapshot"]["role"] == "FORMAL_EXECUTION_TRACEABILITY_NOT_PRODUCT_QUALITY_GATE"
    assert truth.query("rc7_task", task_id=prepared.task_id)[0]["state"] == "PASS"
    assert prepared.delivery.node_id == "N10"


def test_n10_cannot_converge_before_director_accept(tmp_path: Path, monkeypatch):
    _, control = _control(tmp_path)
    _patch_prepare_dependencies(monkeypatch, control)
    service = AutonomousN10Service(evidence_root=str(tmp_path / "n10"))
    service.prepare_ready(control, run_id=RUN)

    with pytest.raises(AutonomousN10Error, match="N10_DIRECTOR_ACCEPT_REQUIRED"):
        service.converge_after_director_accept(control, run_id=RUN)


def test_n10_director_accept_remains_separate_from_mission_authority(tmp_path: Path, monkeypatch):
    _, control = _control(tmp_path)
    _patch_prepare_dependencies(monkeypatch, control)
    service = AutonomousN10Service(evidence_root=str(tmp_path / "n10"))
    prepared = service.prepare_ready(control, run_id=RUN)

    adoption = WaveFNodeAdoptionControl(
        control.truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "n10"),
    )
    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N10",
        director_ref="director-final",
    )
    assert decision.accepted is True
    # Director accepts N10 delivery; it does not itself mutate Mission to CONVERGED.
    assert control.truth.query("rc7_mission", mission_id=MISSION)[0]["state"] != "CONVERGED"
    assert prepared.delivery.package_artifact_id in control.truth.query(
        "rc7_evaluation", evaluation_id=decision.evaluation_id
    )[0]["artifact_refs"]


def test_final_report_requires_convergence_receipt(tmp_path: Path):
    _, control = _control(tmp_path)
    with pytest.raises(AutonomousN10Error, match="FINAL_REPORT_REQUIRES_CURRENT_CONVERGENCE_RECEIPT"):
        AutonomousN10Service(evidence_root=str(tmp_path / "n10")).generate_final_report(
            control,
            run_id=RUN,
        )
