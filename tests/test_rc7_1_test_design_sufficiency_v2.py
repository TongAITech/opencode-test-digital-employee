from __future__ import annotations

from rc7_runtime.test_design_loop import TestObligation
from rc7_runtime.test_design_sufficiency_v2 import TestDesignSufficiencyV2


def _obligation(index, *, kind="REQUIREMENT_ASSERTION", layer="L3", risk="MEDIUM"):
    return TestObligation(
        obligation_id="OBL-%03d" % index,
        kind=kind,
        layer=layer,
        risk=risk,
        evidence_refs=("EVD-%03d" % index,),
    )


def _case(tc_id, subject_ids, *, layer="L3"):
    return {
        "tc_id": tc_id,
        "layer": layer,
        "coverage_links": [
            {"subject_id": subject_id, "evidence_ref": "EVD-COVER-%s-%s" % (tc_id, subject_id)}
            for subject_id in subject_ids
        ],
    }


def test_100_obligations_20_cases_cannot_fake_100_percent_sufficiency():
    gate = TestDesignSufficiencyV2()
    obligations = [_obligation(index) for index in range(1, 101)]
    cases = []
    for case_index in range(20):
        start = case_index * 5 + 1
        cases.append(
            _case(
                "TC-%02d" % (case_index + 1),
                ["OBL-%03d" % value for value in range(start, start + 5)],
            )
        )

    result = gate.evaluate(obligations=obligations, cases=cases)

    assert result.passed is False
    assert result.metrics["required_subject_count"] == 100
    assert result.metrics["case_count"] == 20
    assert result.metrics["minimum_case_floor"] == 25
    assert any(reason.startswith("CASE_DENSITY_INSUFFICIENT:ALL:") for reason in result.reasons)
    assert any(request["reason"] == "CASE_DENSITY_INSUFFICIENT" for request in result.delta_requests)


def test_reasonably_distributed_large_design_can_pass_v2():
    gate = TestDesignSufficiencyV2()
    obligations = [_obligation(index) for index in range(1, 13)]
    cases = [
        _case("TC-01", ["OBL-001", "OBL-002", "OBL-003"]),
        _case("TC-02", ["OBL-004", "OBL-005", "OBL-006"]),
        _case("TC-03", ["OBL-007", "OBL-008", "OBL-009"]),
        _case("TC-04", ["OBL-010", "OBL-011", "OBL-012"]),
    ]

    result = gate.evaluate(obligations=obligations, cases=cases)

    assert result.passed is True
    assert result.reasons == ()
    assert result.metrics["minimum_case_floor"] == 3
    assert result.metrics["max_required_obligations_per_case"] == 3


def test_critical_obligation_needs_two_distinct_exercises_in_nontrivial_design():
    gate = TestDesignSufficiencyV2()
    obligations = [
        _obligation(1, kind="BOUNDARY", risk="CRITICAL"),
        _obligation(2, kind="REQUIREMENT_ASSERTION"),
        _obligation(3, kind="REQUIREMENT_ASSERTION"),
        _obligation(4, kind="REQUIREMENT_ASSERTION"),
        _obligation(5, kind="POSITIVE_PATH"),
        _obligation(6, kind="POSITIVE_PATH"),
        _obligation(7, kind="REGRESSION"),
        _obligation(8, kind="REGRESSION"),
    ]
    shallow_cases = [
        _case("TC-A", ["OBL-001", "OBL-002", "OBL-003", "OBL-004"]),
        _case("TC-B", ["OBL-005", "OBL-006", "OBL-007", "OBL-008"]),
    ]
    shallow = gate.evaluate(obligations=obligations, cases=shallow_cases)
    assert shallow.passed is False
    assert "CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT:OBL-001:cases=1:min=2" in shallow.reasons

    deep_cases = [
        shallow_cases[0],
        _case("TC-B", ["OBL-001", "OBL-005", "OBL-006", "OBL-007", "OBL-008"]),
    ]
    deep = gate.evaluate(obligations=obligations, cases=deep_cases)
    assert deep.passed is True
    assert deep.metrics["critical_depth_gaps"] == {}


def test_risk_relevant_kind_interaction_must_be_exercised():
    gate = TestDesignSufficiencyV2()
    obligations = [
        _obligation(1, kind="BUSINESS_RULE"),
        _obligation(2, kind="BUSINESS_RULE"),
        _obligation(3, kind="BOUNDARY"),
        _obligation(4, kind="BOUNDARY"),
    ]
    separated = [
        _case("TC-RULE", ["OBL-001", "OBL-002"]),
        _case("TC-BOUNDARY", ["OBL-003", "OBL-004"]),
    ]
    missing = gate.evaluate(obligations=obligations, cases=separated)
    assert missing.passed is False
    assert "INTERACTION_COVERAGE_MISSING:L3:BUSINESS_RULExBOUNDARY" in missing.reasons

    exercised = separated + [_case("TC-INTERACTION", ["OBL-001", "OBL-003"])]
    covered = gate.evaluate(obligations=obligations, cases=exercised)
    assert covered.passed is True
    assert covered.metrics["missing_interactions"] == []


def test_small_change_is_not_forced_to_manufacture_case_volume():
    gate = TestDesignSufficiencyV2()
    obligations = [_obligation(1), _obligation(2)]
    result = gate.evaluate(
        obligations=obligations,
        cases=[_case("TC-SMALL", ["OBL-001", "OBL-002"])],
    )

    assert result.passed is True
    assert result.metrics["minimum_case_floor"] == 0
    assert result.reasons == ()
