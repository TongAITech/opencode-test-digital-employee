from __future__ import annotations

import json

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_test_design_oracle_evaluator import DshExecutionReadyTestDesignEvaluator
from rc7_runtime.models import Evaluation, EvaluationResult, Gap, GapSeverity, Mission
from rc7_runtime.test_design_loop import TestDesignLoopResult


PREFIX = "TEST_DESIGN_DELTA_V1:"


def _delta_rows():
    return (
        {
            "layer": "L3",
            "obligation_ids": ["OB-CRITICAL-1"],
            "reason": "CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT",
            "required_case_floor": 2,
            "current_case_count": 1,
        },
        {
            "layer": "L4",
            "obligation_ids": ["OB-RULE-1", "OB-BOUNDARY-1"],
            "reason": "INTERACTION_COVERAGE_MISSING",
            "interaction": "BUSINESS_RULExBOUNDARY",
        },
    )


def _base_result(delta_requests=None):
    rows = tuple(delta_requests if delta_requests is not None else _delta_rows())
    gap = Gap(
        gap_id="GAP-TD-DELTA-1",
        mission_id="M-TD-DELTA",
        source_node="TEST_DESIGN",
        category="CRITICAL_TEST_DEPTH_INSUFFICIENT",
        severity=GapSeverity.CRITICAL,
        target_node="TEST_DESIGN",
        description="CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT:OB-CRITICAL-1:cases=1:min=2",
        subject_refs=["ART-TD-1", "OB-CRITICAL-1"],
        evidence_refs=["EVID-TD-1"],
        acceptance_criteria=["critical obligation depth is independently re-exercised"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-TD-DELTA-1",
        mission_id="M-TD-DELTA",
        node="TEST_DESIGN",
        artifact_refs=["ART-TD-1"],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="independent-test-design-evaluator",
        dimensions={"gate_status": "NOT_SUFFICIENT"},
        gap_refs=[gap.gap_id],
        evidence_refs=["EVID-TD-1"],
    )
    return TestDesignLoopResult(
        evaluation=evaluation,
        gaps=(gap,),
        delta_requests=rows,
        semantic_coverage=1.0,
        case_count=1,
    )


def _contracts(criteria):
    return [item for item in criteria if item.startswith(PREFIX)]


def _parse_contract(value):
    assert value.startswith(PREFIX)
    return json.loads(value[len(PREFIX):])


def test_delta_requests_survive_evaluation_gap_and_repair_task_r1(tmp_path):
    base = _base_result()
    guarded = DshExecutionReadyTestDesignEvaluator._persist_delta_contracts(base)

    assert guarded.evaluation.dimensions["delta_requests"] == list(_delta_rows())
    assert guarded.evaluation.dimensions["test_design_repair_delta_contract_version"] == "v1"
    gap_contracts = _contracts(guarded.gaps[0].acceptance_criteria)
    assert [_parse_contract(item) for item in gap_contracts] == list(_delta_rows())

    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="M-TD-DELTA",
            release_id="R-TD-DELTA",
            goal="prove exact test-design delta repair survives R1 planning",
        ),
    )
    repair = control.gap_planner.plan(guarded.gaps[0])
    assert repair is not None
    assert repair.task_type == "REPAIR"
    assert repair.node == "TEST_DESIGN"
    repair_contracts = _contracts(repair.acceptance_criteria)
    assert [_parse_contract(item) for item in repair_contracts] == list(_delta_rows())

    rows = truth.query("rc7_task", task_id=repair.task_id)
    assert len(rows) == 1
    r1_contracts = _contracts(rows[0]["acceptance_criteria"])
    assert [_parse_contract(item) for item in r1_contracts] == list(_delta_rows())


def test_delta_contract_is_canonical_deduplicated_and_not_description_only():
    delta = {
        "obligation_ids": ["OB-2", "OB-1"],
        "reason": "CASE_DENSITY_INSUFFICIENT",
        "layer": "L2",
        "current_case_count": 1,
        "required_case_floor": 3,
    }
    guarded = DshExecutionReadyTestDesignEvaluator._persist_delta_contracts(
        _base_result((delta, dict(delta)))
    )

    assert guarded.delta_requests == (delta,)
    assert guarded.evaluation.dimensions["delta_requests"] == [delta]
    contracts = _contracts(guarded.gaps[0].acceptance_criteria)
    assert len(contracts) == 1
    expected = PREFIX + json.dumps(
        delta,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert contracts[0] == expected
    assert contracts[0] != guarded.gaps[0].description
    assert _parse_contract(contracts[0]) == delta
