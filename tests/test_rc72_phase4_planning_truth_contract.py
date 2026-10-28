from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_decomposer import (
    AdaptiveTaskDecomposer,
    DecompositionConfig,
    DecompositionSnapshot,
    ObligationPlanningSignal,
    PlanningCase,
)
from rc7_runtime.rc72_decomposition_truth import PersistentAdaptiveTaskDecomposer
from rc7_runtime.rc72_domain import ReleaseBatch, TestObligation
from rc7_runtime.rc72_repository import CanonicalRC72Repository


def _obligation(oid, sst):
    return TestObligation(
        obligation_id=oid,
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id=sst,
        application_id="cfg-center",
        business_scenario="scenario-%s" % oid,
        business_rule="rule-%s" % oid,
        risk_level="HIGH",
        test_level="L3",
        code_slice_refs=["Service#%s" % oid],
        oracle_refs=["HTTP", "DB"],
    )


def _case(cid, obligation):
    return PlanningCase(
        case_id=cid,
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id=obligation.sst_id,
        obligation_id=obligation.obligation_id,
        business_scenario=obligation.business_scenario,
        code_slice=obligation.code_slice_refs[0],
        test_level="L3",
        data_domain="guarantor",
        auth_role="maker",
        oracle_family="HTTP+DB",
        execution_tool="api",
        browser_context="none",
        environment="FAT1",
        estimated_duration_minutes=2,
        estimated_cost=1.0,
    )


def _signal(oid, *, change=0.0, defects=0.0, blast=0.0, blocked=0.0, uncertainty=0.0, contention=0.0, cost=0.0):
    return ObligationPlanningSignal(
        obligation_id=oid,
        requirement_priority=0.5,
        sst_criticality=0.5,
        change_impact=change,
        historical_defect_density=defects,
        uncovered_changed_code=0.5,
        coverage_yield_estimate=0.5,
        production_blast_radius=blast,
        blocked_downstream_work=blocked,
        execution_cost=cost,
        resource_contention=contention,
        uncertainty_reduction=uncertainty,
    )


def _config():
    return DecompositionConfig(
        target_min_cases=3,
        target_max_cases=8,
        target_duration_minutes=15,
        priority_weights={
            "business_risk": 2.0,
            "requirement_priority": 1.0,
            "sst_criticality": 1.0,
            "change_impact": 3.0,
            "historical_defect_density": 2.0,
            "uncovered_changed_code": 1.0,
            "coverage_yield_estimate": 1.0,
            "production_blast_radius": 2.0,
            "blocked_downstream_work": 1.0,
            "uncertainty_reduction": 1.0,
            "execution_cost": -1.0,
            "resource_contention": -2.0,
            "coverage_gap": 1.0,
            "coverage_yield": 1.0,
        },
    )


def test_priority_uses_explicit_multi_dimensional_signal_not_coverage_only():
    high = _obligation("TO-HIGH", "SST-H")
    low = _obligation("TO-LOW", "SST-L")
    cases = [_case("H-%d" % i, high) for i in range(1, 4)] + [_case("L-%d" % i, low) for i in range(1, 4)]
    snapshot = DecompositionSnapshot(
        snapshot_id="PLAN-PRIORITY",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=[high, low],
        cases=cases,
        planning_signals=[
            _signal("TO-HIGH", change=1.0, defects=0.9, blast=1.0, blocked=0.8, uncertainty=0.9),
            _signal("TO-LOW", change=0.1, defects=0.0, blast=0.1, blocked=0.0, uncertainty=0.1),
        ],
        config_version="phase4-v3",
    )

    result = AdaptiveTaskDecomposer(_config()).decompose(snapshot)

    assert result.obligation_priorities["TO-HIGH"] > result.obligation_priorities["TO-LOW"]
    explanation = result.priority_explanations["TO-HIGH"]
    for dimension in (
        "business_risk", "requirement_priority", "sst_criticality", "change_impact",
        "historical_defect_density", "uncovered_changed_code", "coverage_yield_estimate",
        "production_blast_radius", "blocked_downstream_work", "execution_cost",
        "resource_contention", "uncertainty_reduction",
    ):
        assert dimension in explanation


def test_resource_contention_and_execution_cost_are_visible_negative_priority_inputs():
    obligation = _obligation("TO-A", "SST-A")
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 4)]
    clean = DecompositionSnapshot(
        snapshot_id="PLAN-CLEAN",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=[obligation],
        cases=cases,
        planning_signals=[_signal("TO-A")],
        config_version="phase4-v3",
    )
    contended = DecompositionSnapshot(
        snapshot_id="PLAN-CONTENDED",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=[obligation],
        cases=cases,
        planning_signals=[_signal("TO-A", contention=1.0, cost=1.0)],
        config_version="phase4-v3",
    )
    decomposer = AdaptiveTaskDecomposer(_config())

    assert decomposer.decompose(contended).obligation_priorities["TO-A"] < decomposer.decompose(clean).obligation_priorities["TO-A"]


def test_planning_snapshot_and_result_are_persisted_in_same_r1_and_survive_replay(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    batch = ReleaseBatch(
        release_batch_id="RB-1",
        mission_id="M-1",
        name="batch",
        application_ids=["cfg-center"],
        requirement_ids=["REQ-1"],
    )
    obligation = _obligation("TO-A", "SST-A")
    repo.persist(batch)
    repo.persist(obligation)
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 4)]
    snapshot = DecompositionSnapshot(
        snapshot_id="PLAN-PERSISTED",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=[obligation],
        cases=cases,
        planning_signals=[_signal("TO-A", change=0.8, defects=0.5)],
        config_version="phase4-v3",
    )
    service = PersistentAdaptiveTaskDecomposer(
        truth,
        release_id="RC7.2",
        decomposer=AdaptiveTaskDecomposer(_config()),
    )

    result = service.plan_and_persist(snapshot)

    assert len(result.etus) == 1
    assert truth.query("rc72_decomposition_snapshot", snapshot_id="PLAN-PERSISTED")
    persisted_etu = truth.query("rc72_etu", etu_id=result.etus[0].etu_id)[0]
    assert persisted_etu["planning_snapshot_ref"] == "PLAN-PERSISTED"

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    persisted_plan = replayed.query("rc72_decomposition_snapshot", snapshot_id="PLAN-PERSISTED")[0]
    assert persisted_plan["config_version"] == "phase4-v3"
    assert persisted_plan["priority_weights"]["change_impact"] == 3.0
    assert persisted_plan["priority_explanations"]["TO-A"]
    assert replayed.query("rc72_etu", etu_id=result.etus[0].etu_id)
