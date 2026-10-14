from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    ClosedLoopControlPlane,
    DshRequirementEvaluator,
    EvaluationResult,
    Evidence,
    Mission,
    MissionTaskGraphCompiler,
    TaskStatus,
)
from rc7_runtime.control_plane import WorkerOutput


class FakeIndependentReviewerLauncher:
    def __init__(self, *, decision="PASS", gap_ids=None) -> None:
        self.coordinator_instance_id = "coordinator-review-test"
        self.decision = decision
        self.gap_ids = list(gap_ids or [])
        self.prompts = []

    def assign(
        self,
        *,
        agent_id,
        role,
        phase,
        mission_id,
        attempt_id,
        scope,
        input_refs,
        allowed_artifact_types,
        allowed_tools,
        parent_worker_id=None,
        generation=0,
    ):
        assert role == "REQUIREMENT_REVIEWER"
        return SimpleNamespace(
            worker_instance_id="worker-independent-reviewer",
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-reviewer",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment, prompt):
        self.prompts.append(prompt)
        invocation = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-independent-reviewer",
            tool_calls=(
                {
                    "call_ref": "dsh-event://tool-call/review-runtime-status",
                    "tool_name": "mcp__pfc_aitest_rc6__runtime_status",
                },
            ),
            evidence_refs=(
                "dsh://session/session-independent-reviewer",
                "file:///tmp/independent-reviewer-output.jsonl",
            ),
        )
        return invocation, {
            "decision": self.decision,
            "gap_ids": list(self.gap_ids),
            "summary": "independent review result",
        }


def _analysis_payload(*, include_boundary: bool):
    return {
        "requirement_id": "REQ-RATE-001",
        "source_assertions": [{"id": "SRC-1", "text": "rate upper bound"}],
        "atomic_statements": [
            {
                "id": "A-1",
                "text": "500000.00 allowed and 500000.01 rejected",
                "testable": True,
                "source_ref": "SRC-1",
            }
        ],
        "trace_links": [
            {"source_id": "SRC-1", "atomic_id": "A-1", "evidence_ref": "EVD-REQ-SOURCE"}
        ],
        "evidence_refs": ["worker-declared-will-be-overridden"],
        "business_rules": [{"id": "BR-1"}],
        "roles": [{"id": "ROLE-1"}],
        "preconditions": [{"id": "PRE-1"}],
        "normal_paths": [{"id": "NP-1"}],
        "negative_paths": [{"id": "NEG-1"}],
        "boundaries": ([{"id": "BOUND-1", "rule": "500000.00/500000.01"}] if include_boundary else []),
        "states": [{"id": "STATE-1"}],
        "data_constraints": [{"id": "DATA-1"}],
        "dependencies": [{"id": "DEP-1"}],
        "side_effects": [{"id": "SIDE-1"}],
    }


def _candidate(control, graph, tmp_path, *, include_boundary: bool):
    task = graph.task("REQUIREMENT_ANALYSIS")
    leased = control.lease_next(
        worker_ref="worker-requirement-analyzer",
        capabilities=["requirement_reasoning"],
    )
    assert leased is not None and leased.task_id == task.task_id
    running = control.start(task.task_id, worker_ref="worker-requirement-analyzer")
    artifact_id = graph.artifact_ids["REQUIREMENT_ANALYSIS"]
    envelope = {
        "task_id": task.task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "REQUIREMENT_MODEL",
            "content_ref": "source://requirement-analysis",
            "parent_refs": list(running.input_artifact_refs),
            "evidence_refs": ["EVD-REQ-SOURCE"],
        },
        "semantic_payload": _analysis_payload(include_boundary=include_boundary),
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "requirement-candidate.json"
    path.write_bytes(raw)
    evidence = Evidence(
        evidence_id="EVD-REQ-SOURCE",
        mission_id=control.mission_id,
        kind="SOURCE_DOCUMENT",
        source_ref="file:///requirements/rate-rule.md",
        content_ref="evidence://rate-rule",
        subject_refs=[task.task_id],
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=control.mission_id,
        artifact_type="REQUIREMENT_MODEL",
        producer_task_id=task.task_id,
        content_ref="file://" + str(path.resolve()),
        parent_refs=list(running.input_artifact_refs),
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    produced = control.submit_worker_output(
        WorkerOutput(
            task_id=task.task_id,
            worker_ref="worker-requirement-analyzer",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    assert produced.state == TaskStatus.OUTPUT_PRODUCED
    return task, artifact_id


def _runtime(tmp_path, mission_id):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=mission_id, release_id="RC7", goal="independent requirement review"),
    )
    graph = MissionTaskGraphCompiler().install(control, mission_id)
    return truth, control, graph


def test_independent_reviewer_plus_deterministic_gate_accepts_complete_requirement(tmp_path) -> None:
    truth, control, graph = _runtime(tmp_path, "MISSION-REQ-REVIEW-PASS")
    task, artifact_id = _candidate(control, graph, tmp_path, include_boundary=True)
    launcher = FakeIndependentReviewerLauncher(decision="PASS")

    evaluated = DshRequirementEvaluator(launcher).evaluate_and_apply(
        control,
        task.task_id,
        artifact_id,
    )

    assert evaluated.analyzer_worker_id == "worker-requirement-analyzer"
    assert evaluated.reviewer_worker_id == "worker-independent-reviewer"
    assert evaluated.reviewer_worker_id != evaluated.analyzer_worker_id
    assert evaluated.reviewer_session_id == "session-independent-reviewer"
    assert evaluated.loop_result.evaluation.result == EvaluationResult.PASS
    assert control.scheduler.task(task.task_id).state == TaskStatus.PASS
    assert control.scheduler.task(graph.task("CODE_ANALYSIS").task_id).state == TaskStatus.READY
    assert evaluated.analysis["evidence_refs"] == ["EVD-REQ-SOURCE"]
    assert evaluated.review["evidence_refs"]
    assert len(truth.query("rc7_evidence", mission_id=control.mission_id)) >= 3
    assert "Do not emit a canonical Evaluation" in launcher.prompts[0]


def test_reviewer_false_pass_cannot_hide_missing_boundary(tmp_path) -> None:
    _truth, control, graph = _runtime(tmp_path, "MISSION-REQ-REVIEW-FALSE-PASS")
    task, artifact_id = _candidate(control, graph, tmp_path, include_boundary=False)
    # Reviewer says PASS, but deterministic gate must independently detect the
    # missing boundary and route repair.
    launcher = FakeIndependentReviewerLauncher(decision="PASS")

    evaluated = DshRequirementEvaluator(launcher).evaluate_and_apply(
        control,
        task.task_id,
        artifact_id,
    )

    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "REQ_BOUNDARY_RULE_MISSING" in evaluated.loop_result.evaluation.dimensions["reasons"]
    assert control.scheduler.task(task.task_id).state == TaskStatus.REPAIR_REQUIRED
    persisted_gaps = control.truth.query("rc7_gap", mission_id=control.mission_id)
    assert any(row["category"] == "MISSING_BOUNDARY" for row in persisted_gaps)
    repair_tasks = [
        row
        for row in control.truth.query("rc7_task", mission_id=control.mission_id)
        if row["task_type"] == "REPAIR" and row["node"] == "REQUIREMENT_ANALYSIS"
    ]
    assert len(repair_tasks) == 1
    assert repair_tasks[0]["state"] == "READY"
