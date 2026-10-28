from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_coverage_convergence import (
    CoverageFeedbackService,
    CoverageGapReason,
    CoverageMappingStatus,
)
from rc7_runtime.rc72_domain import ReleaseBatch, TestObligation
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import RC72StateMachine


def _setup(tmp_path: Path, *, reason=CoverageGapReason.CASE_MISSING):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-center",
            business_scenario="create guarantor",
            business_rule="government guarantor creation",
            risk_level="HIGH",
            test_level="L3",
            code_slice_refs=["GuarantorServiceImpl#create:type2"],
            oracle_refs=["HTTP", "DB"],
            coverage_targets=["GuarantorServiceImpl#create:type2"],
        )
    )
    service = CoverageFeedbackService(truth, release_id="RC7.2")
    service.record_observation(
        observation_id="OBS-BEFORE",
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=900,
        total_units=1000,
        target_ratio=0.92,
        evidence_ref="libra://before",
    )
    service.map_gap(
        gap_id="CG-1",
        observation_id="OBS-BEFORE",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=100,
    )
    service.classify_gap(
        gap_id="CG-1",
        gap_reason=reason,
        evidence_refs=["analysis://CG-1/a", "analysis://CG-1/b"],
        rationale="evidence-backed classification",
    )
    return truth, service


def _post_observation(service: CoverageFeedbackService, *, observation_id="OBS-AFTER"):
    service.record_observation(
        observation_id=observation_id,
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=920,
        total_units=1000,
        target_ratio=0.92,
        evidence_ref=f"libra://{observation_id}",
    )


def test_resolution_requires_distinct_post_repair_observation(tmp_path: Path):
    _, service = _setup(tmp_path)
    with pytest.raises(Exception, match="COVERAGE_GAP_VERIFICATION_REQUIRES_POST_OBSERVATION"):
        service.record_gap_verification(
            verification_id="CGV-1",
            gap_id="CG-1",
            observation_id="OBS-BEFORE",
            uncovered_units_after=0,
            evidence_ref="libra://verification/CG-1",
        )


def test_nonzero_post_repair_gap_cannot_be_resolved(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _post_observation(service)
    service.record_gap_verification(
        verification_id="CGV-1",
        gap_id="CG-1",
        observation_id="OBS-AFTER",
        uncovered_units_after=12,
        evidence_ref="libra://verification/CG-1",
    )
    with pytest.raises(Exception, match="COVERAGE_GAP_STILL_UNCOVERED"):
        service.resolve_gap(
            gap_id="CG-1",
            verification_id="CGV-1",
            evidence_refs=["execution://repair/CG-1"],
            rationale="repair complete",
        )
    assert truth.query("rc72_coverage_gap", gap_id="CG-1")[0]["status"] == "CLASSIFIED"


def test_classified_gap_resolves_only_after_zero_gap_verification(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _post_observation(service)
    service.record_gap_verification(
        verification_id="CGV-1",
        gap_id="CG-1",
        observation_id="OBS-AFTER",
        uncovered_units_after=0,
        evidence_ref="libra://verification/CG-1",
    )
    result = service.resolve_gap(
        gap_id="CG-1",
        verification_id="CGV-1",
        evidence_refs=["execution://repair/CG-1"],
        rationale="new cases executed and the mapped code slice is now covered",
    )

    assert result.status == CoverageMappingStatus.RESOLVED
    row = truth.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert row["status"] == "RESOLVED"
    assert row["excluded"] is False
    assert row["resolution_verification_id"] == "CGV-1"
    assert row["resolved_at"] is not None
    assert row["action"] == "CLOSED_BY_POST_REPAIR_VERIFICATION"


def test_unmapped_or_ambiguous_gap_cannot_be_closed_by_verification(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    service = CoverageFeedbackService(truth, release_id="RC7.2")
    service.record_observation(
        observation_id="OBS-BEFORE",
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=900,
        total_units=1000,
        target_ratio=0.92,
        evidence_ref="libra://before",
    )
    service.map_gap(
        gap_id="CG-UNMAPPED",
        observation_id="OBS-BEFORE",
        code_slice="UnknownService#branch",
        uncovered_units=100,
    )
    service.record_observation(
        observation_id="OBS-AFTER",
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=920,
        total_units=1000,
        target_ratio=0.92,
        evidence_ref="libra://after",
    )
    with pytest.raises(Exception, match="COVERAGE_GAP_VERIFICATION_REQUIRES_CLASSIFIED_MAPPING"):
        service.record_gap_verification(
            verification_id="CGV-X",
            gap_id="CG-UNMAPPED",
            observation_id="OBS-AFTER",
            uncovered_units_after=0,
            evidence_ref="libra://verification/unmapped",
        )


def test_unreachable_gap_requires_explicit_human_approval_for_exclusion(tmp_path: Path):
    truth, service = _setup(tmp_path, reason=CoverageGapReason.UNREACHABLE)
    row = truth.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert row["status"] == "EXCLUSION_REVIEW_REQUIRED"
    assert row["excluded"] is False

    with pytest.raises(Exception, match="COVERAGE_EXCLUSION_HUMAN_APPROVAL_REQUIRED"):
        service.approve_exclusion(
            gap_id="CG-1",
            reviewer_worker_id="reviewer-1",
            reviewer_session_id="review-session-1",
            human_approval_ref="",
            evidence_refs=["codegraph://reachability/CG-1", "scope://review/CG-1"],
            rationale="branch is unreachable in this release scope",
        )

    result = service.approve_exclusion(
        gap_id="CG-1",
        reviewer_worker_id="reviewer-1",
        reviewer_session_id="review-session-1",
        human_approval_ref="human-gate://coverage-exclusion/CG-1",
        evidence_refs=["codegraph://reachability/CG-1", "scope://review/CG-1"],
        rationale="human approved the proven unreachable branch for this release scope",
    )
    assert result.status == CoverageMappingStatus.EXCLUDED_APPROVED
    approved = truth.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert approved["status"] == "EXCLUDED_APPROVED"
    assert approved["excluded"] is True
    assert approved["human_approval_ref"] == "human-gate://coverage-exclusion/CG-1"
    assert approved["exclusion_approved_at"] is not None


def test_normal_business_gap_cannot_be_excluded_instead_of_repaired(tmp_path: Path):
    _, service = _setup(tmp_path, reason=CoverageGapReason.CASE_MISSING)
    with pytest.raises(Exception, match="COVERAGE_EXCLUSION_ONLY_FOR_UNREACHABLE"):
        service.approve_exclusion(
            gap_id="CG-1",
            reviewer_worker_id="reviewer-1",
            reviewer_session_id="review-session-1",
            human_approval_ref="human-gate://bad-exclusion",
            evidence_refs=["analysis://a", "analysis://b"],
            rationale="do not allow coverage target gaming",
        )


def test_unreachable_gap_cannot_use_normal_resolution_path(tmp_path: Path):
    _, service = _setup(tmp_path, reason=CoverageGapReason.UNREACHABLE)
    _post_observation(service)
    with pytest.raises(Exception, match="COVERAGE_EXCLUSION_REQUIRES_APPROVAL_PATH"):
        service.record_gap_verification(
            verification_id="CGV-1",
            gap_id="CG-1",
            observation_id="OBS-AFTER",
            uncovered_units_after=0,
            evidence_ref="libra://verification/CG-1",
        )


def test_resolved_and_approved_exclusion_truth_survive_replay(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _post_observation(service)
    service.record_gap_verification(
        verification_id="CGV-1",
        gap_id="CG-1",
        observation_id="OBS-AFTER",
        uncovered_units_after=0,
        evidence_ref="libra://verification/CG-1",
    )
    service.resolve_gap(
        gap_id="CG-1",
        verification_id="CGV-1",
        evidence_refs=["execution://repair/CG-1"],
        rationale="repair complete",
    )

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    verification = replay.query("rc72_coverage_gap_verification", verification_id="CGV-1")[0]
    gap = replay.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert verification["uncovered_units_after"] == 0
    assert gap["status"] == "RESOLVED"
    assert gap["resolution_verification_id"] == "CGV-1"
