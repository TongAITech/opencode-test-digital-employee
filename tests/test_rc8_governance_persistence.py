import pytest

from rc8_center.coverage_repository import JsonFileCoverageRepository
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.governance_repository import JsonFileGovernanceRepository
from rc8_center.json_repository import DurableRepositoryError
from rc8_runtime.coverage import CoverageObservation
from rc8_runtime.governance import (
    AttemptRecord,
    AttemptStatus,
    CoverageDimension,
    CoverageMetric,
    GapRecord,
    GapSeverity,
    GapStatus,
    GapType,
    InvalidationRecord,
    ReleaseDecision,
    ReleaseDecisionRecord,
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)


def _stage():
    return StageInstance(
        stage_instance_id="stage-l1-1",
        test_run_id="run-1",
        stage_type="APPLICABLE_LAYER_EXECUTION",
        scope_version="scope-v1",
        attempt_no=1,
        state=StageState.COMPLETED,
        input_refs=("exec-spec:v1",),
        output_refs=("artifact:junit",),
    )


def _attempt(status=AttemptStatus.COMPLETED):
    terminal = status != AttemptStatus.STARTED
    return AttemptRecord(
        attempt_id="attempt-1",
        test_run_id="run-1",
        stage_instance_id="stage-l1-1",
        work_item_id="wi-l1-1",
        producer_node_id="node-1",
        producer_ref="worker:l1",
        input_snapshot_ref="git:abc",
        status=status,
        action_refs=("action:test",) if terminal else (),
        assertion_refs=("assertion:1",) if terminal else (),
        evidence_refs=("artifact:junit",) if terminal else (),
        coverage_refs=("coverage-observation:1",) if terminal else (),
        started_at=10,
        finished_at=20 if terminal else None,
    )


def _coverage():
    metric = CoverageMetric(
        metric_id="metric-changed-branch-1",
        dimension=CoverageDimension.CHANGED_BRANCH,
        covered=8,
        total=10,
        threshold=0.9,
        evidence_refs=("artifact:jacoco-xml",),
        critical=True,
    )
    return CoverageObservation(
        observation_id="coverage-observation-1",
        test_run_id="run-1",
        stage_instance_id="stage-l1-1",
        attempt_id="attempt-1",
        subject_ref="layer:L1",
        source_snapshot_ref="git:abc",
        metric=metric,
        source_tool="jacoco",
        artifact_refs=("artifact:jacoco-xml",),
    )


def test_governance_facts_survive_repository_restart(tmp_path):
    gov_path = tmp_path / "governance.json"
    cov_path = tmp_path / "coverage.json"
    gov = JsonFileGovernanceRepository(str(gov_path))
    cov = JsonFileCoverageRepository(str(cov_path))

    gov.upsert_stage(_stage())
    gov.upsert_attempt(_attempt())
    gap = GapRecord(
        gap_id="gap-coverage-1",
        test_run_id="run-1",
        source_stage_instance_id="stage-l1-1",
        source_attempt_id="attempt-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="critical changed branch uncovered",
        owner_stage="TEST_DESIGN",
        repair_strategy="delta design and targeted rerun",
        evidence_refs=("artifact:jacoco-xml",),
        invalidates=("layer:L1:sufficiency", "mission:test-sufficient"),
    )
    gov.upsert_gap(gap)
    cov.append(_coverage())
    invalidation = InvalidationRecord(
        invalidation_id="inv-1",
        test_run_id="run-1",
        source_ref="gap:gap-coverage-1",
        target_refs=("layer:L1:sufficiency",),
        reason="coverage gap invalidates prior sufficiency",
        evidence_refs=("artifact:jacoco-xml",),
    )
    gov.append_invalidation(invalidation)
    evaluation = SufficiencyEvaluation(
        evaluation_id="mission-eval-1",
        test_run_id="run-1",
        scope=StatusScope.MISSION,
        subject_id="run-1",
        evaluator_id="mission-evaluator",
        policy_version="policy-v1",
        result=SufficiencyResult.INSUFFICIENT,
        dimension_refs=("coverage:changed-branch",),
        evidence_refs=("artifact:jacoco-xml",),
        unsatisfied_requirement_refs=("coverage:critical-changed-branch",),
        unresolved_gap_ids=("gap-coverage-1",),
        explanation="critical branch coverage is below policy",
    )
    gov.append_evaluation(evaluation)
    release = ReleaseDecisionRecord(
        release_decision_id="release-1",
        test_run_id="run-1",
        decision=ReleaseDecision.HOLD,
        mission_evaluation_ref="mission-eval-1",
        evidence_refs=("artifact:jacoco-xml",),
        explanation="mission insufficient",
    )
    gov.append_release_decision(release)

    gov2 = JsonFileGovernanceRepository(str(gov_path))
    cov2 = JsonFileCoverageRepository(str(cov_path))
    projection = GovernanceProjectionService(gov2, cov2).test_run("run-1")

    assert projection["stage_count"] == 1
    assert projection["attempt_count"] == 1
    assert projection["active_gap_count"] == 1
    assert projection["coverage_observation_count"] == 1
    assert projection["coverage_observations"][0]["source_snapshot_ref"] == "git:abc"
    assert projection["coverage_observations"][0]["attempt_id"] == "attempt-1"
    assert projection["latest_mission_sufficiency"]["result"] == "INSUFFICIENT"
    assert projection["latest_release_decision"]["decision"] == "HOLD"
    assert projection["projection_contract"]["status_is_recorded_not_derived"] is True


def test_projection_does_not_invent_pass_from_completed_attempt(tmp_path):
    gov = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    cov = JsonFileCoverageRepository(str(tmp_path / "coverage.json"))
    gov.upsert_stage(_stage())
    gov.upsert_attempt(_attempt())

    projection = GovernanceProjectionService(gov, cov).test_run("run-1")
    assert projection["latest_mission_sufficiency"] is None
    assert projection["latest_release_decision"] is None
    assert projection["stage_count"] == 1
    assert projection["attempt_count"] == 1


def test_attempt_projection_advances_monotonically_but_attempt_identity_is_preserved(tmp_path):
    gov = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    started = _attempt(AttemptStatus.STARTED)
    gov.upsert_attempt(started)
    assert gov.get_attempt("attempt-1").status == AttemptStatus.STARTED

    completed = _attempt(AttemptStatus.COMPLETED)
    gov.upsert_attempt(completed)
    restored = gov.get_attempt("attempt-1")
    assert restored.status == AttemptStatus.COMPLETED
    assert restored.started_at == 10
    assert restored.finished_at == 20
    assert restored.evidence_refs == ("artifact:junit",)

    # Exact R1 replay is idempotent.
    gov.upsert_attempt(completed)
    assert gov.get_attempt("attempt-1") == completed

    rewritten_identity = AttemptRecord(
        attempt_id="attempt-1",
        test_run_id="run-OTHER",
        stage_instance_id="stage-l1-1",
        work_item_id="wi-l1-1",
        producer_node_id="node-1",
        producer_ref="worker:l1",
        input_snapshot_ref="git:abc",
        status=AttemptStatus.COMPLETED,
        evidence_refs=("artifact:junit",),
        started_at=10,
        finished_at=20,
    )
    with pytest.raises(DurableRepositoryError, match="ATTEMPT_IDENTITY_IMMUTABLE"):
        gov.upsert_attempt(rewritten_identity)

    regressed = _attempt(AttemptStatus.STARTED)
    with pytest.raises(DurableRepositoryError, match="ATTEMPT_TERMINAL_STATE_IMMUTABLE"):
        gov.upsert_attempt(regressed)


def test_coverage_observation_is_immutable_but_exact_r1_replay_is_idempotent(tmp_path):
    cov = JsonFileCoverageRepository(str(tmp_path / "coverage.json"))
    observation = _coverage()
    cov.append(observation)
    cov.append(observation)
    assert cov.get("coverage-observation-1") == observation

    changed_metric = CoverageMetric(
        metric_id="metric-changed-branch-1",
        dimension=CoverageDimension.CHANGED_BRANCH,
        covered=9,
        total=10,
        threshold=0.9,
        evidence_refs=("artifact:jacoco-xml",),
        critical=True,
    )
    changed = CoverageObservation(
        observation_id="coverage-observation-1",
        test_run_id="run-1",
        stage_instance_id="stage-l1-1",
        attempt_id="attempt-1",
        subject_ref="layer:L1",
        source_snapshot_ref="git:abc",
        metric=changed_metric,
        source_tool="jacoco",
        artifact_refs=("artifact:jacoco-xml",),
    )
    with pytest.raises(DurableRepositoryError, match="COVERAGE_OBSERVATION_ID_CONFLICT"):
        cov.append(changed)


def test_gap_can_close_but_identity_and_original_evidence_cannot_be_rewritten(tmp_path):
    gov = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    gap = GapRecord(
        gap_id="gap-1",
        test_run_id="run-1",
        source_stage_instance_id="stage-l1-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="uncovered branch",
        owner_stage="TEST_DESIGN",
        repair_strategy="delta test",
        evidence_refs=("artifact:attempt-1",),
        opened_at=10,
    )
    gov.upsert_gap(gap)
    closed = GapRecord(
        gap_id="gap-1",
        test_run_id="run-1",
        source_stage_instance_id="stage-l1-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="uncovered branch",
        owner_stage="TEST_DESIGN",
        repair_strategy="delta test",
        status=GapStatus.CLOSED,
        evidence_refs=("artifact:attempt-1",),
        closure_evidence_refs=("artifact:attempt-2",),
        opened_at=10,
        closed_at=20,
    )
    gov.upsert_gap(closed)
    restored = gov.get_gap("gap-1")
    assert restored.status == GapStatus.CLOSED
    assert restored.evidence_refs == ("artifact:attempt-1",)
    assert restored.closure_evidence_refs == ("artifact:attempt-2",)

    rewritten = GapRecord(
        gap_id="gap-1",
        test_run_id="run-other",
        source_stage_instance_id="stage-l1-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="rewrite",
        owner_stage="TEST_DESIGN",
        repair_strategy="rewrite",
        evidence_refs=("artifact:other",),
        opened_at=10,
    )
    with pytest.raises(DurableRepositoryError, match="GAP_IDENTITY_IMMUTABLE"):
        gov.upsert_gap(rewritten)
