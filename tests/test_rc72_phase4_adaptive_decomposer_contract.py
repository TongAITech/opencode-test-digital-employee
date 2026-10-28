from dataclasses import replace

import pytest

from rc7_runtime.rc72_decomposer import (
    AdaptiveTaskDecomposer,
    CoverageGapSignal,
    DecompositionConfig,
    DecompositionSnapshot,
    PlanningCase,
)
from rc7_runtime.rc72_domain import TestObligation


def _obligation(oid, sst, level="L3", risk="HIGH", code="Service#create"):
    return TestObligation(
        obligation_id=oid,
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id=sst,
        application_id="cfg-center",
        business_scenario="guarantor creation %s" % sst,
        business_rule="required fields persist %s" % sst,
        risk_level=risk,
        test_level=level,
        code_slice_refs=[code],
        oracle_refs=["HTTP", "DB"],
    )


def _case(cid, obligation, *, level=None, tool="api", data="guarantor", role="maker", browser="none", env="FAT1", kind="POSITIVE"):
    return PlanningCase(
        case_id=cid,
        release_batch_id=obligation.release_batch_id,
        requirement_id=obligation.requirement_id,
        sst_id=obligation.sst_id,
        obligation_id=obligation.obligation_id,
        business_scenario=obligation.business_scenario,
        code_slice=obligation.code_slice_refs[0],
        test_level=level or obligation.test_level,
        data_domain=data,
        auth_role=role,
        oracle_family="HTTP+DB",
        execution_tool=tool,
        browser_context=browser,
        environment=env,
        case_kind=kind,
        estimated_duration_minutes=2,
        estimated_cost=1.0,
    )


def _snapshot(obligations, cases, *, coverage=(), completed=()):
    return DecompositionSnapshot(
        snapshot_id="PLAN-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        current_node="N4_TEST_DESIGN",
        obligations=list(obligations),
        cases=list(cases),
        coverage_gaps=list(coverage),
        completed_case_ids=list(completed),
        config_version="phase4-v1",
    )


def _decomposer():
    return AdaptiveTaskDecomposer(
        DecompositionConfig(
            target_min_cases=3,
            target_max_cases=8,
            target_duration_minutes=15,
            priority_weights={
                "business_risk": 5.0,
                "change_impact": 3.0,
                "coverage_gap": 2.0,
                "execution_cost": -1.0,
            },
        )
    )


def test_unrelated_ssts_never_merge_merely_because_api_tool_and_data_are_same():
    a = _obligation("TO-A", "SST-A")
    b = _obligation("TO-B", "SST-B")
    cases = [_case("A-%d" % i, a) for i in range(1, 4)] + [_case("B-%d" % i, b) for i in range(1, 4)]

    result = _decomposer().decompose(_snapshot([a, b], cases))

    assert len(result.etus) == 2
    assert {tuple(etu.case_ids) for etu in result.etus} == {
        ("A-1", "A-2", "A-3"),
        ("B-1", "B-2", "B-3"),
    }
    assert all(len({result.case_index[cid].sst_id for cid in etu.case_ids}) == 1 for etu in result.etus)


def test_same_obligation_same_semantics_small_cases_merge_into_one_cohesive_etu():
    obligation = _obligation("TO-A", "SST-A")
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 8)]

    result = _decomposer().decompose(_snapshot([obligation], cases))

    assert len(result.etus) == 1
    etu = result.etus[0]
    assert etu.obligation_id == "TO-A"
    assert etu.case_ids == ["TC-1", "TC-2", "TC-3", "TC-4", "TC-5", "TC-6", "TC-7"]
    assert 0.0 <= etu.cohesion_score <= 1.0
    assert "same_obligation" in etu.cohesion_explanation
    assert etu.planning_snapshot_ref == "PLAN-1"


def test_twenty_plus_heterogeneous_cases_split_into_small_lineage_preserving_etus():
    obligations = [
        _obligation("TO-A", "SST-A", code="A#m"),
        _obligation("TO-B", "SST-B", code="B#m"),
        _obligation("TO-C", "SST-C", code="C#m"),
    ]
    cases = []
    for obligation in obligations:
        cases.extend(_case("%s-%02d" % (obligation.obligation_id, i), obligation) for i in range(1, 9))

    result = _decomposer().decompose(_snapshot(obligations, cases))

    assert len(result.etus) >= 3
    assert all(1 <= len(etu.case_ids) <= 8 for etu in result.etus)
    assert all(etu.release_batch_id == "RB-1" and etu.mission_id == "M-1" for etu in result.etus)
    for etu in result.etus:
        obligation_ids = {result.case_index[cid].obligation_id for cid in etu.case_ids}
        sst_ids = {result.case_index[cid].sst_id for cid in etu.case_ids}
        assert obligation_ids == {etu.obligation_id}
        assert len(sst_ids) == 1


def test_mixed_l3_l4_work_is_split_by_test_level_tool_and_browser_semantics():
    l3 = _obligation("TO-L3", "SST-A", level="L3")
    l4 = _obligation("TO-L4", "SST-A", level="L4")
    cases = [
        _case("API-1", l3, tool="api"),
        _case("API-2", l3, tool="api"),
        _case("API-3", l3, tool="api"),
        _case("UI-1", l4, tool="browser", browser="maker-session"),
        _case("UI-2", l4, tool="browser", browser="maker-session"),
        _case("UI-3", l4, tool="browser", browser="maker-session"),
    ]

    result = _decomposer().decompose(_snapshot([l3, l4], cases))

    assert len(result.etus) == 2
    assert {etu.test_level for etu in result.etus} == {"L3", "L4"}
    assert {etu.primary_tool_family for etu in result.etus} == {"api", "browser"}


def test_unmapped_coverage_gap_is_investigation_and_cannot_create_orphan_case_or_etu():
    gap = CoverageGapSignal(
        signal_id="CG-UNMAPPED",
        code_slice="UnknownService#m",
        uncovered_units=20,
        requirement_id=None,
        sst_id=None,
        obligation_id=None,
    )

    result = _decomposer().decompose(_snapshot([], [], coverage=[gap]))

    assert result.etus == []
    assert result.generated_case_ids == []
    route = result.coverage_routes[0]
    assert route.signal_id == "CG-UNMAPPED"
    assert route.gap_reason == "NO_REQUIREMENT_MAPPING"
    assert route.responsible_nodes == ["N2_REQUIREMENT", "N3_CODE_ANALYSIS"]
    assert route.action == "INVESTIGATE"


def test_mapped_coverage_gap_reprioritizes_existing_obligation_without_becoming_asset_root():
    obligation = _obligation("TO-A", "SST-A", risk="HIGH")
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 4)]
    gap = CoverageGapSignal(
        signal_id="CG-A",
        code_slice="Service#create",
        uncovered_units=40,
        requirement_id="REQ-1",
        sst_id="SST-A",
        obligation_id="TO-A",
        gap_reason="CASE_MISSING",
    )

    result = _decomposer().decompose(_snapshot([obligation], cases, coverage=[gap]))

    assert result.coverage_routes[0].responsible_nodes == ["N4_TEST_DESIGN"]
    assert result.coverage_routes[0].action == "REPAIR_OBLIGATION"
    assert result.obligation_priorities["TO-A"] > 0
    assert all(etu.obligation_id == "TO-A" for etu in result.etus)
    assert result.generated_case_ids == []


def test_completed_cases_are_not_recreated_on_replan_without_explicit_reason():
    obligation = _obligation("TO-A", "SST-A")
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 7)]

    result = _decomposer().decompose(
        _snapshot([obligation], cases, completed=["TC-1", "TC-2", "TC-3"])
    )

    scheduled = [cid for etu in result.etus for cid in etu.case_ids]
    assert scheduled == ["TC-4", "TC-5", "TC-6"]
    assert result.skipped_completed_case_ids == ["TC-1", "TC-2", "TC-3"]


def test_same_frozen_input_and_config_produces_deterministic_etu_identity_and_order():
    obligation = _obligation("TO-A", "SST-A")
    cases = [_case("TC-%d" % i, obligation) for i in range(1, 9)]
    snapshot = _snapshot([obligation], cases)
    decomposer = _decomposer()

    first = decomposer.decompose(snapshot)
    second = decomposer.decompose(snapshot)

    assert [etu.etu_id for etu in first.etus] == [etu.etu_id for etu in second.etus]
    assert [etu.case_ids for etu in first.etus] == [etu.case_ids for etu in second.etus]
    assert first.obligation_priorities == second.obligation_priorities
