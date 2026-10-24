from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_defect_evidence import (
    AutonomousDefectEvidenceService,
    N9DefectEvidenceError,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.defect_evidence_policy import (
    DefectEvidencePolicy,
    RCAEvidenceChain,
    SeverityFactors,
)
from rc7_runtime.defect_loop import DefectRecord, DefectStatus
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    Task,
)
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-N9-EVIDENCE"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N9",
            goal="prove defect evidence closure before independent review",
        ),
    )
    return truth, control


def _seed_evidence_ready_defect(
    control: ClosedLoopControlPlane,
    *,
    suffix: str,
    requirement_id: str = "STBB19-320",
):
    gap_id = "GAP-PRODUCT-" + suffix
    task_id = "TASK-DEFECT-" + suffix
    defect_id = "DEFECT-" + suffix
    candidate_artifact_id = "ART-DEFECT-CANDIDATE-" + suffix
    base_evidence_id = "EVD-DEFECT-BASE-" + suffix
    qualification_evaluation_id = "EVAL-DEFECT-QUALIFIED-" + suffix

    gap = Gap(
        gap_id=gap_id,
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="trusted product-owned oracle failure",
        subject_refs=["ATT-ORIGINAL-" + suffix, "TC-" + suffix],
        evidence_refs=[base_evidence_id],
        acceptance_criteria=["independent defect evidence closure"],
        state=GapStatus.PLANNED,
    )
    # A QUALIFY_DEFECT owner task is leaseable only after the PRODUCT handoff
    # has entered PLANNED. This mirrors the real GapRepairPlanner lifecycle.
    append_entity(control.truth, gap, release_id=control.release_id)
    control.register_task(
        Task(
            task_id=task_id,
            mission_id=MISSION,
            node="DEFECT",
            task_type="QUALIFY_DEFECT",
            objective="qualify and review product defect",
            required_capabilities=["defect_analysis"],
            gap_refs=[gap_id],
        )
    )
    worker = "defect-worker-" + suffix
    leased = control.lease_next(worker_ref=worker, capabilities=("defect_analysis",))
    assert leased is not None and leased.task_id == task_id
    control.start(task_id, worker_ref=worker)
    base_evidence = Evidence(
        evidence_id=base_evidence_id,
        mission_id=MISSION,
        kind="DEFECT_QUALIFICATION_EVIDENCE",
        source_ref="runtime://defect-qualification",
        content_ref="evidence://defect/" + suffix,
        subject_refs=[task_id, gap_id, defect_id],
    )
    candidate = Artifact(
        artifact_id=candidate_artifact_id,
        mission_id=MISSION,
        artifact_type="DEFECT_CANDIDATE",
        producer_task_id=task_id,
        content_ref="artifact://defect/" + suffix,
        evidence_refs=[base_evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=task_id,
            worker_ref=worker,
            artifacts=(candidate,),
            evidence=(base_evidence,),
        )
    )
    qualification = Evaluation(
        evaluation_id=qualification_evaluation_id,
        mission_id=MISSION,
        node="DEFECT",
        artifact_refs=[candidate_artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-defect-qualification-gate",
        dimensions={
            "qualification": "PASS",
            "reproduction_conclusive": True,
            "reproduced": True,
        },
        evidence_refs=[base_evidence_id],
    )
    append_entity(control.truth, qualification, release_id=control.release_id)
    defect = DefectRecord(
        defect_id=defect_id,
        mission_id=MISSION,
        source_gap_id=gap_id,
        requirement_refs=[requirement_id],
        test_case_ids=["TC-" + suffix],
        execution_attempt_ids=["ATT-ORIGINAL-" + suffix, "ATT-REPRO-" + suffix],
        expected={"state": "PUBLISHED"},
        actual={"state": "DRAFT"},
        evidence_refs=[base_evidence_id],
        severity="HIGH",  # provisional legacy candidate value; N9 must derive final review severity.
        state=DefectStatus.EVIDENCE_READY,
        reproduction_attempts=1,
        reproduction_passes=1,
        latest_evaluation_id=qualification_evaluation_id,
    )
    append_entity(control.truth, defect, release_id=control.release_id, artifact_version=1)
    return {
        "gap_id": gap_id,
        "task_id": task_id,
        "defect_id": defect_id,
        "base_evidence_id": base_evidence_id,
    }


def _add_policy_evidence(control: ClosedLoopControlPlane, suffix: str):
    refs = []
    for kind in ("RUNTIME_FAILURE_DIAGNOSIS", "CAT_CORRELATION", "CODEGRAPH_EVIDENCE", "SEVERITY_IMPACT"):
        evidence_id = "EVD-%s-%s" % (kind, suffix)
        append_entity(
            control.truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id=MISSION,
                kind=kind,
                source_ref="runtime://n9-test",
                content_ref="evidence://%s/%s" % (kind.lower(), suffix),
                subject_refs=["DEFECT-" + suffix],
            ),
            release_id=control.release_id,
        )
        refs.append(evidence_id)
    return tuple(refs)


def _signature(refs, *, symptom="version state remains DRAFT after publish"):
    return DefectEvidencePolicy.build_signature(
        product_area="loan-version-management",
        requirement_refs=["STBB19-320"],
        affected_application="cfg-data",
        surface_ref="POST /loan/version/publish",
        failure_signature_id="FSIG-PUBLISH-STATE",
        business_error_code="BIZ-409",
        root_stack_frame="LoanVersionService.publish",
        suspected_symbols=["LoanVersionService.publish", "VersionRepository.save"],
        codegraph_root="LoanVersionService.publish",
        business_symptom=symptom,
        final_state_mismatch="expected=PUBLISHED actual=DRAFT",
        root_cause_statement="publish path leaves version in DRAFT",
        evidence_refs=refs[:3],
    )


def _severity(refs, *, critical=False):
    return SeverityFactors(
        business_impact=3 if critical else 1,
        blast_radius=3 if critical else 1,
        data_integrity=4 if critical else 0,
        security_compliance=0,
        transaction_criticality=4 if critical else 1,
        workaround_unavailable=3 if critical else 1,
        reproducibility=4 if critical else 1,
        evidence_refs=(refs[3],),
    )


def _rca(refs, *, level=2):
    kwargs = {
        "symptom_evidence_refs": (refs[0],),
        "affected_application": "cfg-data" if level >= 1 else "",
        "service_or_endpoint": "POST /loan/version/publish" if level >= 2 else "",
        "module_or_symbol": "LoanVersionService.publish" if level >= 3 else "",
        "evidence_refs": tuple(refs[1:3]),
    }
    if level >= 4:
        kwargs.update(
            code_change_refs=("git-change://abc123",),
            codegraph_refs=("codegraph://LoanVersionService.publish",),
            git_refs=("git://abc123",),
            requirement_refs=("STBB19-320",),
        )
    return RCAEvidenceChain(**kwargs)


def test_evidence_ready_defect_requires_rca_l2_before_review(tmp_path: Path):
    truth, control = _control(tmp_path)
    seeded = _seed_evidence_ready_defect(control, suffix="L1")
    refs = _add_policy_evidence(control, "L1")
    service = AutonomousDefectEvidenceService(evidence_root=str(tmp_path / "n9"))

    with pytest.raises(N9DefectEvidenceError, match="N9_RCA_FILING_MINIMUM_NOT_MET:RCA-L1"):
        service.prepare_for_review(
            control,
            defect_task_id=seeded["task_id"],
            defect_id=seeded["defect_id"],
            signature=_signature(refs),
            severity_factors=_severity(refs),
            rca_chain=_rca(refs, level=1),
        )
    row = truth.query("rc7_defect", defect_id=seeded["defect_id"])[0]
    assert row["state"] == "EVIDENCE_READY"
    assert not truth.query("rc7_evidence", mission_id=MISSION, kind="N9_DEFECT_EVIDENCE_PACKAGE")


def test_policy_derived_severity_and_rca_package_move_to_ready_for_review(tmp_path: Path):
    truth, control = _control(tmp_path)
    seeded = _seed_evidence_ready_defect(control, suffix="READY")
    refs = _add_policy_evidence(control, "READY")
    receipt = AutonomousDefectEvidenceService(evidence_root=str(tmp_path / "n9")).prepare_for_review(
        control,
        defect_task_id=seeded["task_id"],
        defect_id=seeded["defect_id"],
        signature=_signature(refs),
        severity_factors=_severity(refs, critical=True),
        rca_chain=_rca(refs, level=2),
    )

    assert receipt.defect_state == "READY_FOR_REVIEW"
    assert receipt.severity == "CRITICAL"
    assert receipt.rca_level == "RCA-L2"
    assert receipt.duplicate_disposition == "DISTINCT"
    row = truth.query("rc7_defect", defect_id=seeded["defect_id"])[0]
    assert row["state"] == "READY_FOR_REVIEW"
    assert row["severity"] == "CRITICAL"
    assert row["root_cause_hypothesis"]["confidence"] == 0.55
    assert receipt.package_evidence_id in row["evidence_refs"]
    package = truth.query("rc7_artifact", artifact_id=receipt.package_artifact_id)[0]
    assert package["artifact_type_name"] == "N9_DEFECT_EVIDENCE_PACKAGE"
    # N9 enrichment is not independent disposition authority.
    assert row["duplicate_of"] is None


def test_duplicate_recommendation_does_not_auto_transition_defect(tmp_path: Path):
    truth, control = _control(tmp_path)
    first = _seed_evidence_ready_defect(control, suffix="FIRST")
    first_refs = _add_policy_evidence(control, "FIRST")
    service = AutonomousDefectEvidenceService(evidence_root=str(tmp_path / "n9"))
    service.prepare_for_review(
        control,
        defect_task_id=first["task_id"],
        defect_id=first["defect_id"],
        signature=_signature(first_refs),
        severity_factors=_severity(first_refs),
        rca_chain=_rca(first_refs, level=4),
    )

    second = _seed_evidence_ready_defect(control, suffix="SECOND")
    second_refs = _add_policy_evidence(control, "SECOND")
    receipt = service.prepare_for_review(
        control,
        defect_task_id=second["task_id"],
        defect_id=second["defect_id"],
        signature=_signature(second_refs),
        severity_factors=_severity(second_refs),
        rca_chain=_rca(second_refs, level=4),
    )
    assert receipt.duplicate_disposition == "DUPLICATE"
    assert receipt.duplicate_of_candidate == first["defect_id"]
    current = truth.query("rc7_defect", defect_id=second["defect_id"])[0]
    assert current["state"] == "READY_FOR_REVIEW"
    assert current["duplicate_of"] is None
