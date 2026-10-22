import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.governance import (
    AttemptRecord,
    AttemptStatus,
    ClaimState,
    CoverageDimension,
    CoverageMetric,
    FailureOwnership,
    GapRecord,
    GapSeverity,
    GapStatus,
    GapType,
    InvalidationRecord,
    MissionRuntimeState,
    ReleaseDecision,
    ReleaseDecisionRecord,
    ScopedStatusClaim,
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
    route_failure,
    route_gap,
    transition_stage,
)


def _stage(state=StageState.PENDING):
    return StageInstance(
        stage_instance_id="stage-l1-1",
        test_run_id="run-1",
        stage_type="L1_EXECUTION",
        scope_version="scope-v1",
        attempt_no=1,
        state=state,
    )


def test_tool_reality_requires_real_evidence_and_cannot_claim_sufficiency():
    with pytest.raises(RC8ContractError, match="REALITY_VERIFIED_REQUIRES_REALITY_EVIDENCE"):
        ScopedStatusClaim(
            scope=StatusScope.TOOL,
            subject_id="maven-junit",
            state=ClaimState.REALITY_VERIFIED,
        )

    tool = ScopedStatusClaim(
        scope=StatusScope.TOOL,
        subject_id="maven-junit",
        state=ClaimState.REALITY_VERIFIED,
        evidence_refs=("artifact:junit",),
        reality_refs=("bank-reality:run-1",),
    )
    assert tool.state == ClaimState.REALITY_VERIFIED

    with pytest.raises(RC8ContractError, match="CLAIM_STATE_NOT_ALLOWED_FOR_SCOPE"):
        ScopedStatusClaim(
            scope=StatusScope.TOOL,
            subject_id="maven-junit",
            state=ClaimState.SUFFICIENT,
            evaluator_ref="eval",
            evidence_refs=("artifact:junit",),
        )


def test_layer_sufficiency_cannot_be_inferred_from_green_execution():
    with pytest.raises(RC8ContractError, match="SUFFICIENT_REQUIRES_EVALUATOR_AND_EVIDENCE"):
        ScopedStatusClaim(
            scope=StatusScope.LAYER,
            subject_id="L1",
            state=ClaimState.SUFFICIENT,
        )

    with pytest.raises(RC8ContractError, match="LAYER_SUFFICIENT_REQUIRES_COVERAGE"):
        ScopedStatusClaim(
            scope=StatusScope.LAYER,
            subject_id="L1",
            state=ClaimState.SUFFICIENT,
            evaluator_ref="l1-sufficiency-v1",
            evidence_refs=("artifact:junit-green",),
        )

    with pytest.raises(RC8ContractError, match="SUFFICIENT_REQUIRES_ZERO_UNRESOLVED_GAPS"):
        ScopedStatusClaim(
            scope=StatusScope.LAYER,
            subject_id="L1",
            state=ClaimState.SUFFICIENT,
            evaluator_ref="l1-sufficiency-v1",
            evidence_refs=("artifact:junit", "artifact:jacoco"),
            coverage_refs=("coverage:changed-branch",),
            unresolved_gap_ids=("gap-uncovered-branch",),
        )

    claim = ScopedStatusClaim(
        scope=StatusScope.LAYER,
        subject_id="L1",
        state=ClaimState.SUFFICIENT,
        evaluator_ref="l1-sufficiency-v1",
        evidence_refs=("artifact:junit", "artifact:jacoco"),
        coverage_refs=("coverage:changed-method", "coverage:changed-branch"),
    )
    assert claim.state == ClaimState.SUFFICIENT


def test_mission_and_release_are_separate_gates():
    with pytest.raises(RC8ContractError, match="MISSION_SUFFICIENT_REQUIRES_STAGE_LAYER_CLAIMS"):
        ScopedStatusClaim(
            scope=StatusScope.MISSION,
            subject_id="run-1",
            state=ClaimState.SUFFICIENT,
            evaluator_ref="mission-eval-v1",
            evidence_refs=("artifact:mission",),
        )

    mission = ScopedStatusClaim(
        scope=StatusScope.MISSION,
        subject_id="run-1",
        state=ClaimState.SUFFICIENT,
        evaluator_ref="mission-eval-v1",
        evidence_refs=("artifact:mission",),
        dependency_claim_refs=("layer:L1:sufficient", "stage:code-analysis:sufficient"),
    )
    assert mission.state == ClaimState.SUFFICIENT

    with pytest.raises(RC8ContractError, match="RELEASE_PASS_FORBIDS_BLOCKING_DEFECTS"):
        ReleaseDecisionRecord(
            release_decision_id="release-1",
            test_run_id="run-1",
            decision=ReleaseDecision.PASS,
            mission_evaluation_ref="mission-eval-v1",
            evidence_refs=("artifact:mission",),
            blocking_defect_refs=("defect-1",),
            explanation="blocking defect still open",
        )

    hold = ReleaseDecisionRecord(
        release_decision_id="release-2",
        test_run_id="run-1",
        decision=ReleaseDecision.HOLD,
        mission_evaluation_ref="mission-eval-v1",
        evidence_refs=("artifact:mission", "artifact:defect"),
        blocking_defect_refs=("defect-1",),
        explanation="testing sufficient but release blocked by product defect",
    )
    assert hold.decision == ReleaseDecision.HOLD


def test_stage_completed_is_not_stage_sufficient_and_transitions_are_gated():
    completed = _stage(StageState.COMPLETED)
    assert completed.state == StageState.COMPLETED
    assert completed.evaluator_id is None

    with pytest.raises(RC8ContractError, match="STAGE_TRANSITION_FORBIDDEN"):
        transition_stage(_stage(), StageState.COMPLETED)

    stage = transition_stage(_stage(), StageState.READY)
    stage = transition_stage(stage, StageState.LEASED)
    stage = transition_stage(stage, StageState.EXECUTING)
    stage = transition_stage(stage, StageState.EVIDENCE_PENDING)
    stage = transition_stage(stage, StageState.EVALUATING)
    with pytest.raises(RC8ContractError, match="EVALUATOR_ID_REQUIRED"):
        transition_stage(stage, StageState.SUFFICIENT)
    stage = transition_stage(stage, StageState.SUFFICIENT, evaluator_id="eval-l1")
    stage = transition_stage(stage, StageState.COMPLETED)
    assert stage.state == StageState.COMPLETED
    assert stage.evaluator_id == "eval-l1"


def test_attempt_is_append_only_and_completed_attempt_requires_evidence():
    runtime = MissionRuntimeState("run-1")
    runtime.add_stage(_stage())

    with pytest.raises(RC8ContractError, match="COMPLETED_ATTEMPT_REQUIRES_EVIDENCE"):
        AttemptRecord(
            attempt_id="attempt-1",
            test_run_id="run-1",
            stage_instance_id="stage-l1-1",
            work_item_id="wi-1",
            producer_node_id="node-1",
            producer_ref="worker-l1",
            input_snapshot_ref="git:abc",
            status=AttemptStatus.COMPLETED,
            finished_at=2,
        )

    attempt = AttemptRecord(
        attempt_id="attempt-1",
        test_run_id="run-1",
        stage_instance_id="stage-l1-1",
        work_item_id="wi-1",
        producer_node_id="node-1",
        producer_ref="worker-l1",
        input_snapshot_ref="git:abc",
        status=AttemptStatus.COMPLETED,
        evidence_refs=("artifact:junit",),
        finished_at=2,
    )
    runtime.add_attempt(attempt)
    with pytest.raises(RC8ContractError, match="ATTEMPT_APPEND_ONLY"):
        runtime.add_attempt(attempt)


def test_coverage_metric_is_evidence_bound_and_threshold_aware():
    metric = CoverageMetric(
        metric_id="cov-branch-1",
        dimension=CoverageDimension.CHANGED_BRANCH,
        covered=8,
        total=10,
        threshold=0.9,
        evidence_refs=("artifact:jacoco-xml",),
        critical=True,
    )
    assert metric.ratio == 0.8
    assert metric.satisfied is False

    with pytest.raises(RC8ContractError, match="COVERAGE_REQUIRES_EVIDENCE"):
        CoverageMetric(
            metric_id="cov-line-1",
            dimension=CoverageDimension.CHANGED_LINE,
            covered=9,
            total=10,
            threshold=0.9,
            evidence_refs=(),
        )


def test_gap_routing_is_deterministic_and_product_failure_does_not_route_to_retry():
    assert route_gap(GapType.COVERAGE_GAP) == "TEST_DESIGN"
    assert route_gap(GapType.CODE_UNCERTAIN) == "CODE_ANALYSIS"
    assert route_failure(FailureOwnership.PRODUCT) == "DEFECT"
    assert route_failure(FailureOwnership.SCRIPT) == "EXECUTABLE_SPEC"
    assert route_failure(FailureOwnership.DATA) == "PRECONDITION_DATA_PREP"
    assert route_failure(FailureOwnership.UNKNOWN) == "DURABLE_GAP"

    runtime = MissionRuntimeState("run-1")
    runtime.add_stage(_stage())
    wrong_owner = GapRecord(
        gap_id="gap-1",
        test_run_id="run-1",
        source_stage_instance_id="stage-l1-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="changed branch uncovered",
        owner_stage="L1_EXECUTION",
        repair_strategy="blind retry",
        evidence_refs=("artifact:jacoco",),
    )
    with pytest.raises(RC8ContractError, match="GAP_OWNER_ROUTE_MISMATCH"):
        runtime.open_gap(wrong_owner)


def test_gap_close_requires_new_closure_evidence_and_history_is_preserved():
    runtime = MissionRuntimeState("run-1")
    runtime.add_stage(_stage())
    gap = GapRecord(
        gap_id="gap-1",
        test_run_id="run-1",
        source_stage_instance_id="stage-l1-1",
        gap_type=GapType.COVERAGE_GAP,
        severity=GapSeverity.P1,
        description="changed branch uncovered",
        owner_stage="TEST_DESIGN",
        repair_strategy="delta design and targeted rerun",
        evidence_refs=("artifact:jacoco-attempt-1",),
        invalidates=("layer:L1:sufficiency", "mission:test-sufficient"),
    )
    runtime.open_gap(gap)
    assert runtime.active_gap_ids() == ("gap-1",)
    runtime.route_gap("gap-1")
    closed = runtime.close_gap("gap-1", ("artifact:jacoco-attempt-2",))
    assert closed.status == GapStatus.CLOSED
    assert closed.evidence_refs == ("artifact:jacoco-attempt-1",)
    assert closed.closure_evidence_refs == ("artifact:jacoco-attempt-2",)
    assert runtime.active_gap_ids() == ()


def test_sufficiency_evaluation_rejects_open_requirements_and_gaps():
    with pytest.raises(RC8ContractError, match="SUFFICIENT_REQUIRES_NO_UNSATISFIED_OR_UNRESOLVED"):
        SufficiencyEvaluation(
            evaluation_id="eval-1",
            test_run_id="run-1",
            scope=StatusScope.LAYER,
            subject_id="L1",
            evaluator_id="l1-evaluator",
            policy_version="v1",
            result=SufficiencyResult.SUFFICIENT,
            dimension_refs=("coverage:branch",),
            evidence_refs=("artifact:jacoco",),
            unsatisfied_requirement_refs=("risk:R1",),
            unresolved_gap_ids=("gap-1",),
            explanation="not actually sufficient",
        )

    baseline = SufficiencyEvaluation(
        evaluation_id="eval-l6-baseline",
        test_run_id="run-1",
        scope=StatusScope.LAYER,
        subject_id="L6",
        evaluator_id="l6-evaluator",
        policy_version="v1",
        result=SufficiencyResult.BASELINE_ONLY,
        dimension_refs=("coverage:performance-baseline",),
        evidence_refs=("artifact:k6-baseline",),
        unsatisfied_requirement_refs=("nfr:authoritative-threshold-missing",),
        explanation="no authoritative NFR, so PASS is forbidden",
    )
    assert baseline.result == SufficiencyResult.BASELINE_ONLY


def test_invalidation_requires_evidence_and_preserves_history():
    with pytest.raises(RC8ContractError, match="INVALIDATION_REQUIRES_EVIDENCE"):
        InvalidationRecord(
            invalidation_id="inv-1",
            test_run_id="run-1",
            source_ref="code-analysis:v2",
            target_refs=("test-design:v1", "layer:L1:sufficiency:v1"),
            reason="new impacted method discovered",
            evidence_refs=(),
        )

    runtime = MissionRuntimeState("run-1")
    record = InvalidationRecord(
        invalidation_id="inv-1",
        test_run_id="run-1",
        source_ref="code-analysis:v2",
        target_refs=("test-design:v1", "layer:L1:sufficiency:v1"),
        reason="new impacted method discovered",
        evidence_refs=("artifact:code-analysis-v2",),
    )
    runtime.add_invalidation(record)
    assert runtime.invalidations["inv-1"].target_refs == (
        "test-design:v1",
        "layer:L1:sufficiency:v1",
    )
