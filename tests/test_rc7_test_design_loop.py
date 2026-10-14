from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import GapStatus, Task, TaskStatus, transition_gap, transition_task
from rc7_runtime.test_design_loop import TestDesignClosedLoop, TestObligation


def _obligations():
    return [
        TestObligation(
            obligation_id="OBL-BUSINESS-1",
            kind="BUSINESS_RULE",
            layer="L3",
            risk="HIGH",
            evidence_refs=("EVD-RULE-1",),
        ),
        TestObligation(
            obligation_id="OBL-BOUNDARY-1",
            kind="BOUNDARY",
            layer="L3",
            risk="CRITICAL",
            evidence_refs=("EVD-BOUNDARY-1",),
        ),
    ]


def _case(tc_id: str, obligation_id: str, *, complete_oracle: bool = True):
    checks = [
        {"type": "API_RESPONSE", "evidence_ref": "EVD-%s-API" % tc_id},
        {"type": "BUSINESS_RULE", "evidence_ref": "EVD-%s-RULE" % tc_id},
    ]
    if complete_oracle:
        checks.append(
            {"type": "EVIDENCE_CORRELATION", "evidence_ref": "EVD-%s-CORRELATION" % tc_id}
        )
    return {
        "tc_id": tc_id,
        "layer": "L3",
        "risk": "HIGH",
        "status": "CANDIDATE",
        "coverage_links": [
            {"subject_id": obligation_id, "evidence_ref": "EVD-%s-COVERAGE" % tc_id}
        ],
        "action_semantics": {
            "state_changing": False,
            "negative": False,
            "authorization_sensitive": False,
        },
        "oracle": {"checks": checks},
    }


def _candidate_task() -> Task:
    task = Task(
        task_id="TASK-TD-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="Produce sufficient Test Obligation coverage",
        acceptance_criteria=["semantic obligation closure passes"],
    )
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="test-design-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    return task


def test_twenty_cases_do_not_pass_when_one_critical_obligation_is_uncovered(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    loop = TestDesignClosedLoop()
    task = _candidate_task()

    # Deliberately create 20 cases, all covering the same business-rule
    # obligation. Case volume must not hide the uncovered CRITICAL boundary.
    initial_cases = [
        _case("TC-%02d" % index, "OBL-BUSINESS-1")
        for index in range(1, 21)
    ]
    first = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-CASESET-1",
        obligations=_obligations(),
        cases=initial_cases,
    )

    assert first.case_count == 20
    assert first.semantic_coverage == 0.5
    assert first.evaluation.result.value == "REPAIR_REQUIRED"
    boundary_gap = next(gap for gap in first.gaps if gap.category == "UNCOVERED_BOUNDARY")
    assert boundary_gap.severity.value == "CRITICAL"
    assert first.delta_requests == (
        {
            "layer": "L3",
            "obligation_ids": ["OBL-BOUNDARY-1"],
            "obligation_refs": ["coverage-subject://OBL-BOUNDARY-1"],
            "reason": "SEMANTIC_COVERAGE_GAP",
        },
    )

    loop.persist(truth, release_id="RC7", result=first)
    loop.accept_candidate(task, first)
    assert task.state == TaskStatus.REPAIR_REQUIRED

    transition_gap(boundary_gap, GapStatus.PLANNED)
    transition_gap(boundary_gap, GapStatus.REPAIRING)
    transition_gap(boundary_gap, GapStatus.EVIDENCE_PENDING)

    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="test-design-session-B")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)

    repaired_cases = initial_cases + [_case("TC-BOUNDARY-01", "OBL-BOUNDARY-1")]
    repaired = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-CASESET-2",
        obligations=_obligations(),
        cases=repaired_cases,
    )
    assert repaired.case_count == 21
    assert repaired.semantic_coverage == 1.0
    assert repaired.evaluation.result.value == "PASS"
    assert repaired.gaps == ()

    resolved = loop.resolve_repaired_gaps([boundary_gap], repaired)
    assert resolved == (boundary_gap,)
    assert boundary_gap.state == GapStatus.RESOLVED

    loop.persist(truth, release_id="RC7", result=repaired)
    loop.persist_gap_updates(truth, release_id="RC7", gaps=resolved, artifact_version=2)
    loop.accept_candidate(task, repaired)
    assert task.state == TaskStatus.PASS

    projected_gap = truth.query("rc7_gap", gap_id=boundary_gap.gap_id)[0]
    assert projected_gap["state"] == "RESOLVED"
    assert projected_gap["artifact_version"] == 2


def test_full_obligation_coverage_still_fails_when_oracle_is_incomplete() -> None:
    loop = TestDesignClosedLoop()
    obligation = TestObligation(
        obligation_id="OBL-RULE-ONLY",
        kind="BUSINESS_RULE",
        layer="L3",
        risk="HIGH",
        evidence_refs=("EVD-RULE",),
    )
    result = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-CASESET-ORACLE-GAP",
        obligations=[obligation],
        cases=[_case("TC-ORACLE-GAP", "OBL-RULE-ONLY", complete_oracle=False)],
    )

    assert result.semantic_coverage == 1.0
    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert any(gap.category == "ORACLE_INCOMPLETE" for gap in result.gaps)
