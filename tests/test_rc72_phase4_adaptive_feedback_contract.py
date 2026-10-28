from rc7_runtime.rc72_decomposer import (
    AdaptiveTaskDecomposer,
    DecompositionConfig,
    DecompositionSnapshot,
    ExecutionHistoryMetric,
    PlanningCase,
)
from rc7_runtime.rc72_domain import TestObligation


def _obligation(oid="TO-A", sst="SST-A", risk="HIGH"):
    return TestObligation(
        obligation_id=oid,
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id=sst,
        application_id="cfg-center",
        business_scenario="guarantor creation",
        business_rule="required fields persist",
        risk_level=risk,
        test_level="L3",
        code_slice_refs=["Service#create"],
        oracle_refs=["HTTP", "DB"],
    )


def _case(cid, obligation, *, role="maker", browser="none", isolated=False, resource=""):
    return PlanningCase(
        case_id=cid,
        release_batch_id=obligation.release_batch_id,
        requirement_id=obligation.requirement_id,
        sst_id=obligation.sst_id,
        obligation_id=obligation.obligation_id,
        business_scenario=obligation.business_scenario,
        code_slice=obligation.code_slice_refs[0],
        test_level=obligation.test_level,
        data_domain="guarantor",
        auth_role=role,
        oracle_family="HTTP+DB",
        execution_tool="api" if browser == "none" else "browser",
        browser_context=browser,
        environment="FAT1",
        estimated_duration_minutes=2,
        estimated_cost=1.0,
        data_strategy="EXCLUSIVE_MUTATION" if isolated else "SHARED_REFERENCE",
        data_resource_key=resource,
        requires_isolated_data=isolated,
    )


def _config():
    return DecompositionConfig(
        target_min_cases=3,
        target_max_cases=8,
        target_duration_minutes=15,
        priority_weights={
            "business_risk": 5.0,
            "coverage_gap": 2.0,
            "coverage_yield": 2.0,
            "execution_cost": -1.0,
        },
    )


def _snapshot(obligation, cases, history=()):
    return DecompositionSnapshot(
        snapshot_id="PLAN-FEEDBACK",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=[obligation],
        cases=list(cases),
        execution_history=list(history),
        config_version="phase4-v2",
    )


def test_exclusive_mutable_data_conflict_forces_isolated_etus():
    obligation = _obligation()
    cases = [
        _case("TC-1", obligation, isolated=True, resource="subproject:SP-1"),
        _case("TC-2", obligation, isolated=True, resource="subproject:SP-1"),
        _case("TC-3", obligation, isolated=True, resource="subproject:SP-1"),
    ]

    result = AdaptiveTaskDecomposer(_config()).decompose(_snapshot(obligation, cases))

    assert len(result.etus) == 3
    assert all(len(etu.case_ids) == 1 for etu in result.etus)
    assert all("exclusive_data_isolation" in etu.cohesion_explanation for etu in result.etus)


def test_shared_reference_data_does_not_force_artificial_split():
    obligation = _obligation()
    cases = [_case("TC-%d" % i, obligation, resource="dictionary:guarantor-type") for i in range(1, 5)]

    result = AdaptiveTaskDecomposer(_config()).decompose(_snapshot(obligation, cases))

    assert len(result.etus) == 1
    assert result.etus[0].case_ids == ["TC-1", "TC-2", "TC-3", "TC-4"]


def test_different_auth_roles_and_browser_contexts_are_separate_etus():
    obligation = _obligation()
    cases = [
        _case("MAKER-1", obligation, role="maker", browser="maker-browser"),
        _case("MAKER-2", obligation, role="maker", browser="maker-browser"),
        _case("APPROVER-1", obligation, role="approver", browser="approver-browser"),
        _case("APPROVER-2", obligation, role="approver", browser="approver-browser"),
    ]

    result = AdaptiveTaskDecomposer(_config()).decompose(_snapshot(obligation, cases))

    assert len(result.etus) == 2
    grouped_roles = [{result.case_index[cid].auth_role for cid in etu.case_ids} for etu in result.etus]
    assert {tuple(sorted(group)) for group in grouped_roles} == {("maker",), ("approver",)}


def test_low_coverage_yield_history_penalizes_priority_and_requests_replan():
    obligation = _obligation()
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 4)]
    decomposer = AdaptiveTaskDecomposer(_config())
    baseline = decomposer.decompose(_snapshot(obligation, cases))
    low_yield = ExecutionHistoryMetric(
        metric_id="H-1",
        obligation_id="TO-A",
        predicted_coverage_yield=20.0,
        actual_coverage_delta=0.0,
        execution_duration_minutes=15,
        tool_calls=40,
        token_cost=100000,
        failure_classification="NONE",
    )

    result = decomposer.decompose(_snapshot(obligation, cases, history=[low_yield]))

    assert result.obligation_priorities["TO-A"] < baseline.obligation_priorities["TO-A"]
    assert "LOW_COVERAGE_YIELD" in result.replan_reasons["TO-A"]


def test_product_defect_history_does_not_get_misclassified_as_low_yield_bruteforce_signal():
    obligation = _obligation()
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 4)]
    history = ExecutionHistoryMetric(
        metric_id="H-DEFECT",
        obligation_id="TO-A",
        predicted_coverage_yield=20.0,
        actual_coverage_delta=0.0,
        execution_duration_minutes=8,
        tool_calls=10,
        token_cost=10000,
        failure_classification="PRODUCT_DEFECT",
    )

    result = AdaptiveTaskDecomposer(_config()).decompose(_snapshot(obligation, cases, history=[history]))

    assert "LOW_COVERAGE_YIELD" not in result.replan_reasons.get("TO-A", [])
