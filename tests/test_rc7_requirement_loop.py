from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import GapStatus, Task, TaskStatus, transition_gap, transition_task
from rc7_runtime.requirement_loop import RequirementClosedLoop


def _analysis(*, boundaries):
    atomic = {
        "id": "A-1",
        "statement": "Rate adjustment must satisfy the documented rule",
        "testable": True,
        "source_ref": "SRC-1",
    }
    return {
        "analysis_id": "REQ-AN-1",
        "release_id": "RC7",
        "requirement_id": "REQ-1",
        "analyzer_worker_id": "worker-analyzer",
        "source_assertions": [{"id": "SRC-1", "text": "source"}],
        "atomic_statements": [atomic],
        "trace_links": [{"source_id": "SRC-1", "atomic_id": "A-1", "evidence_ref": "EVD-SRC-1"}],
        "evidence_refs": ["EVD-SRC-1"],
        "business_rules": [{"id": "BR-1"}],
        "roles": [{"id": "ROLE-1"}],
        "preconditions": [{"id": "PRE-1"}],
        "normal_paths": [{"id": "NP-1"}],
        "negative_paths": [{"id": "NEG-1"}],
        "boundaries": boundaries,
        "states": [{"id": "STATE-1"}],
        "data_constraints": [{"id": "DATA-1"}],
        "dependencies": [{"id": "DEP-1"}],
        "side_effects": [{"id": "SIDE-1"}],
    }


def _review(review_id: str):
    return {
        "id": review_id,
        "review_id": review_id,
        "release_id": "RC7",
        "requirement_id": "REQ-1",
        "subject_analysis_id": "REQ-AN-1",
        "reviewer_worker_id": "worker-reviewer",
        "analyzer_worker_id": "worker-analyzer",
        "decision": "PASS",
        "evidence_refs": ["EVD-REVIEW-1"],
        "gap_ids": [],
    }


def _candidate_task() -> Task:
    task = Task(
        task_id="TASK-REQ-1",
        mission_id="MISSION-1",
        node="REQUIREMENT_ANALYSIS",
        task_type="PRODUCE",
        objective="Produce sufficient requirement analysis",
        acceptance_criteria=["independent requirement gate passes"],
    )
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="worker-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    return task


def test_requirement_gap_repairs_then_converges_only_after_reevaluation(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    loop = RequirementClosedLoop()
    task = _candidate_task()

    first = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-REQ-1",
        analysis=_analysis(boundaries=[]),
        review=_review("REVIEW-1"),
    )
    assert first.evaluation.result.value == "REPAIR_REQUIRED"
    assert any(gap.category == "MISSING_BOUNDARY" for gap in first.gaps)
    boundary_gap = next(gap for gap in first.gaps if gap.category == "MISSING_BOUNDARY")
    assert boundary_gap.severity.value == "CRITICAL"

    loop.persist(truth, release_id="RC7", result=first)
    loop.accept_candidate(task, first)
    assert task.state == TaskStatus.REPAIR_REQUIRED

    # Runtime plans and executes a targeted repair.  Producing the patch does
    # not close the gap; it must wait for independent reevaluation evidence.
    transition_gap(boundary_gap, GapStatus.PLANNED)
    transition_gap(boundary_gap, GapStatus.REPAIRING)
    transition_gap(boundary_gap, GapStatus.EVIDENCE_PENDING)

    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="worker-session-B")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)

    repaired = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-REQ-2",
        analysis=_analysis(boundaries=[{"id": "BOUNDARY-1", "rule": "min/max evidenced"}]),
        review=_review("REVIEW-2"),
    )
    assert repaired.evaluation.result.value == "PASS"
    assert repaired.gaps == ()

    resolved = loop.resolve_repaired_gaps([boundary_gap], repaired)
    assert resolved == (boundary_gap,)
    assert boundary_gap.state == GapStatus.RESOLVED
    assert boundary_gap.resolution_evaluation_id == repaired.evaluation.evaluation_id

    loop.persist(truth, release_id="RC7", result=repaired, evaluation_version=1)
    loop.persist_gap_updates(truth, release_id="RC7", gaps=resolved, artifact_version=2)
    loop.accept_candidate(task, repaired)
    assert task.state == TaskStatus.PASS
    assert task.evaluation_id == repaired.evaluation.evaluation_id

    # R1 projection exposes the latest resolved gap version and both independent
    # evaluations.  No side database is involved.
    projected_gap = truth.query("rc7_gap", gap_id=boundary_gap.gap_id)[0]
    assert projected_gap["state"] == "RESOLVED"
    assert projected_gap["artifact_version"] == 2
    assert len(truth.query("rc7_evaluation", mission_id="MISSION-1")) == 2
