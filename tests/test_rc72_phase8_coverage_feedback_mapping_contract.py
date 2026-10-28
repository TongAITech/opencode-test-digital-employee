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


def _setup(tmp_path: Path, *, ambiguous: bool = False):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1", "REQ-2"],
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
            change_refs=["commit://center/abc"],
            oracle_refs=["HTTP", "DB", "CAT"],
            coverage_targets=["GuarantorServiceImpl#create:type2"],
        )
    )
    if ambiguous:
        repo.persist(
            TestObligation(
                obligation_id="TO-2",
                mission_id="M-1",
                release_batch_id="RB-1",
                requirement_id="REQ-2",
                sst_id="SST-2",
                application_id="cfg-center",
                business_scenario="reuse shared guarantor branch",
                business_rule="shared branch validation",
                risk_level="MEDIUM",
                test_level="L3",
                code_slice_refs=["GuarantorServiceImpl#create:type2"],
                oracle_refs=["HTTP"],
                coverage_targets=["GuarantorServiceImpl#create:type2"],
            )
        )
    service = CoverageFeedbackService(truth, release_id="RC7.2")
    service.record_observation(
        observation_id="COV-OBS-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=920,
        total_units=1000,
        target_ratio=0.92,
        evidence_ref="libra://snapshot/1",
    )
    return truth, service


def test_libra_observation_is_release_batch_scoped_feedback_truth(tmp_path: Path):
    truth, _ = _setup(tmp_path)
    row = truth.query("rc72_coverage_observation", observation_id="COV-OBS-1")[0]
    assert row["source"] == "LIBRA"
    assert row["mission_id"] == "M-1"
    assert row["release_batch_id"] == "RB-1"
    assert row["application_id"] == "cfg-center"
    assert row["covered_units"] == 920
    assert row["total_units"] == 1000
    assert row["target_ratio"] == 0.92
    assert row["evidence_ref"] == "libra://snapshot/1"


def test_exact_code_slice_maps_back_to_existing_requirement_sst_obligation(tmp_path: Path):
    truth, service = _setup(tmp_path)
    result = service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )

    assert result.status == CoverageMappingStatus.MAPPED
    assert result.requirement_id == "REQ-1"
    assert result.sst_id == "SST-1"
    assert result.obligation_id == "TO-1"
    assert result.gap_reason is None
    assert result.action == "CLASSIFY_GAP_REASON"
    assert len(truth.query("rc72_test_obligation")) == 1
    assert not truth.query("rc72_etu")


def test_unmapped_code_slice_routes_investigation_and_never_creates_orphan_work(tmp_path: Path):
    truth, service = _setup(tmp_path)
    result = service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="UnknownService#hiddenBranch",
        uncovered_units=20,
    )

    assert result.status == CoverageMappingStatus.UNMAPPED
    assert result.gap_reason == CoverageGapReason.NO_REQUIREMENT_MAPPING
    assert result.responsible_nodes == ["N2_REQUIREMENT", "N3_CODE_ANALYSIS"]
    assert result.action == "INVESTIGATE_LINEAGE"
    assert result.obligation_id is None
    assert len(truth.query("rc72_test_obligation")) == 1
    assert not truth.query("rc72_etu")


def test_ambiguous_code_slice_fails_closed_without_picking_an_obligation(tmp_path: Path):
    truth, service = _setup(tmp_path, ambiguous=True)
    result = service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )

    assert result.status == CoverageMappingStatus.AMBIGUOUS
    assert result.gap_reason == CoverageGapReason.AMBIGUOUS_OBLIGATION_MAPPING
    assert result.obligation_id is None
    assert sorted(result.candidate_obligation_ids) == ["TO-1", "TO-2"]
    assert result.responsible_nodes == ["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"]
    assert result.action == "INVESTIGATE_LINEAGE"
    assert not truth.query("rc72_etu")


@pytest.mark.parametrize(
    "reason, expected_nodes, expected_action",
    [
        (CoverageGapReason.ANALYSIS_MISSING, ["N3_CODE_ANALYSIS"], "REPAIR_ANALYSIS"),
        (CoverageGapReason.CASE_MISSING, ["N4_TEST_DESIGN"], "REPAIR_TEST_DESIGN"),
        (CoverageGapReason.DATA_BLOCKED, ["N5_TEST_DATA"], "REPAIR_TEST_DATA"),
        (CoverageGapReason.EXECUTABLE_BLOCKED, ["N6_EXECUTABLE_READINESS"], "REPAIR_EXECUTABLE"),
        (CoverageGapReason.PATH_NOT_REACHED, ["N8_DIAGNOSIS_RECOVERY"], "DIAGNOSE_PATH"),
    ],
)
def test_mapped_gap_reason_routes_to_responsible_node(tmp_path: Path, reason, expected_nodes, expected_action):
    truth, service = _setup(tmp_path)
    service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )
    result = service.classify_gap(
        gap_id="CG-1",
        gap_reason=reason,
        evidence_refs=["analysis://coverage-gap/CG-1"],
        rationale="deterministic coverage-gap classification",
    )

    assert result.status == CoverageMappingStatus.CLASSIFIED
    assert result.requirement_id == "REQ-1"
    assert result.sst_id == "SST-1"
    assert result.obligation_id == "TO-1"
    assert result.gap_reason == reason
    assert result.responsible_nodes == expected_nodes
    assert result.action == expected_action
    row = truth.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert row["requirement_id"] == "REQ-1"
    assert row["sst_id"] == "SST-1"
    assert row["obligation_id"] == "TO-1"
    assert row["gap_reason"] == reason.value


def test_coverage_alone_cannot_guess_case_missing_for_mapped_gap(tmp_path: Path):
    truth, service = _setup(tmp_path)
    result = service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )
    assert result.gap_reason is None
    assert result.action == "CLASSIFY_GAP_REASON"
    row = truth.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert row["gap_reason"] is None


def test_unreachable_requires_evidence_and_human_review_before_exclusion(tmp_path: Path):
    truth, service = _setup(tmp_path)
    service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )
    with pytest.raises(Exception, match="COVERAGE_EXCLUSION_EVIDENCE_REQUIRED"):
        service.classify_gap(
            gap_id="CG-1",
            gap_reason=CoverageGapReason.UNREACHABLE,
            evidence_refs=[],
            rationale="unreachable candidate",
        )

    result = service.classify_gap(
        gap_id="CG-1",
        gap_reason=CoverageGapReason.UNREACHABLE,
        evidence_refs=["codegraph://reachability/CG-1", "review://scope/CG-1"],
        rationale="branch is proven unreachable in the release scope",
    )
    assert result.status == CoverageMappingStatus.EXCLUSION_REVIEW_REQUIRED
    assert result.responsible_nodes == ["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"]
    assert result.action == "HUMAN_REVIEW_COVERAGE_EXCLUSION"
    assert truth.query("rc72_coverage_gap", gap_id="CG-1")[0]["excluded"] is False


def test_classification_requires_unique_canonical_mapping(tmp_path: Path):
    _, service = _setup(tmp_path, ambiguous=True)
    service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )
    with pytest.raises(Exception, match="COVERAGE_GAP_REQUIRES_UNIQUE_MAPPING"):
        service.classify_gap(
            gap_id="CG-1",
            gap_reason=CoverageGapReason.CASE_MISSING,
            evidence_refs=["analysis://gap"],
            rationale="case missing",
        )


def test_coverage_feedback_truth_survives_r1_replay(tmp_path: Path):
    truth, service = _setup(tmp_path)
    service.map_gap(
        gap_id="CG-1",
        observation_id="COV-OBS-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )
    service.classify_gap(
        gap_id="CG-1",
        gap_reason=CoverageGapReason.CASE_MISSING,
        evidence_refs=["analysis://coverage-gap/CG-1"],
        rationale="missing business case",
    )

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    observation = replay.query("rc72_coverage_observation", observation_id="COV-OBS-1")[0]
    gap = replay.query("rc72_coverage_gap", gap_id="CG-1")[0]
    assert observation["release_batch_id"] == "RB-1"
    assert gap["requirement_id"] == "REQ-1"
    assert gap["sst_id"] == "SST-1"
    assert gap["obligation_id"] == "TO-1"
    assert gap["gap_reason"] == "CASE_MISSING"
