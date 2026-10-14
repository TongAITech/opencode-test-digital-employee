from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import GapStatus, Task, TaskStatus, transition_gap, transition_task
from rc7_runtime.code_loop import CodeAnalysisClosedLoop


TARGET_ID = "TARGET-CFG-DATA"


def _analysis(*, include_codegraph: bool):
    tool_calls = [
        {
            "tool_id": "git",
            "call_ref": "git://diff/base..head",
            "evidence_ref": "EVD-GIT-1",
            "target_id": TARGET_ID,
        }
    ]
    if include_codegraph:
        tool_calls.append(
            {
                "tool_id": "codegraph",
                "call_ref": "codegraph://callers/RateService.adjustRate",
                "evidence_ref": "EVD-CODEGRAPH-1",
                "target_id": TARGET_ID,
            }
        )
    return {
        "analysis_id": "CODE-AN-1",
        "release_id": "RC7",
        "analyzer_worker_id": "worker-code-analyzer",
        "requirement_ids": ["REQ-1"],
        "source_revisions": {"cfg-data": "abc123..def456"},
        "changed_files": ["RateService.java"],
        "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
        "symbol_explanations": [
            {"symbol_id": "SYM-1", "evidence_refs": ["EVD-GIT-1"]}
        ],
        "reverse_requirement_mappings": [
            {"requirement_id": "REQ-1", "symbol_id": "SYM-1", "evidence_ref": "EVD-GIT-1"}
        ],
        "tool_calls": tool_calls,
        "evidence_refs": ["EVD-GIT-1"],
        "codegraph_required": True,
    }


def _review(review_id: str):
    return {
        "review_id": review_id,
        "subject_analysis_id": "CODE-AN-1",
        "reviewer_worker_id": "worker-code-reviewer",
        "analyzer_worker_id": "worker-code-analyzer",
        "decision": "PASS",
        "evidence_refs": ["EVD-CODE-REVIEW-1"],
        "gap_ids": [],
    }


def _candidate_task() -> Task:
    task = Task(
        task_id="TASK-CODE-1",
        mission_id="MISSION-1",
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective="Produce sufficient code impact analysis",
        acceptance_criteria=["independent code sufficiency gate passes"],
    )
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="code-worker-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    return task


def test_missing_real_codegraph_evidence_repairs_then_converges(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    loop = CodeAnalysisClosedLoop()
    task = _candidate_task()

    first = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-CODE-1",
        target_id=TARGET_ID,
        analysis=_analysis(include_codegraph=False),
        review=_review("CODE-REVIEW-1"),
    )
    assert first.evaluation.result.value == "REPAIR_REQUIRED"
    assert first.evaluation.dimensions["metrics"]["git_evidence_calls"] == 1
    assert first.evaluation.dimensions["metrics"]["codegraph_evidence_calls"] == 0
    codegraph_gap = next(gap for gap in first.gaps if gap.category == "CODEGRAPH_INCOMPLETE")
    assert codegraph_gap.target_node == "CODE_ANALYSIS"

    loop.persist(truth, release_id="RC7", result=first)
    loop.accept_candidate(task, first)
    assert task.state == TaskStatus.REPAIR_REQUIRED

    transition_gap(codegraph_gap, GapStatus.PLANNED)
    transition_gap(codegraph_gap, GapStatus.REPAIRING)
    transition_gap(codegraph_gap, GapStatus.EVIDENCE_PENDING)

    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="code-worker-session-B")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)

    repaired = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-CODE-2",
        target_id=TARGET_ID,
        analysis=_analysis(include_codegraph=True),
        review=_review("CODE-REVIEW-2"),
    )
    assert repaired.evaluation.result.value == "PASS"
    assert repaired.evaluation.dimensions["metrics"]["codegraph_evidence_calls"] == 1
    assert repaired.gaps == ()

    resolved = loop.resolve_repaired_gaps([codegraph_gap], repaired)
    assert resolved == (codegraph_gap,)
    assert codegraph_gap.state == GapStatus.RESOLVED
    assert codegraph_gap.resolution_evaluation_id == repaired.evaluation.evaluation_id

    loop.persist(truth, release_id="RC7", result=repaired)
    loop.persist_gap_updates(truth, release_id="RC7", gaps=resolved, artifact_version=2)
    loop.accept_candidate(task, repaired)
    assert task.state == TaskStatus.PASS

    projected = truth.query("rc7_gap", gap_id=codegraph_gap.gap_id)[0]
    assert projected["state"] == "RESOLVED"
    assert projected["artifact_version"] == 2
    assert len(truth.query("rc7_evaluation", mission_id="MISSION-1")) == 2
