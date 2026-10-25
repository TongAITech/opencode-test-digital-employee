from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, ClosedLoopControlPlane, Evidence, Mission, Task, TaskStatus
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from rc7_runtime.models import EvaluationResult


MISSION = "MISSION-DSH-CODE"
TASK_ID = "TASK-DSH-CODE"
ARTIFACT_ID = "ART-DSH-CODE"
TARGET = "cfg-data"
ANALYZER = "worker-code-analyzer"
CURRENT_ATTEMPT = "attempt-code-1"


class FakeCodeReviewerLauncher:
    def __init__(self) -> None:
        self.coordinator_instance_id = "coordinator-code-review"
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
        assert role == "CODE_REVIEWER"
        return SimpleNamespace(
            worker_instance_id="worker-code-reviewer",
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-code-reviewer",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment, prompt):
        self.prompts.append(prompt)
        reviewer = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-code-reviewer",
            tool_calls=(
                {"call_ref": "dsh-review://git/diff", "tool_name": "git"},
                {"call_ref": "dsh-review://codegraph/callers", "tool_name": "codegraph"},
            ),
            evidence_refs=(
                "dsh://session/session-code-reviewer",
                "file:///tmp/code-reviewer.jsonl",
            ),
        )
        return reviewer, {"decision": "PASS", "gap_ids": [], "summary": "reviewed independently"}


def _append_worker_tool_event(
    truth,
    *,
    tool_name: str,
    call_ref: str,
    suffix: str,
    arguments,
    attempt_id: str = CURRENT_ATTEMPT,
) -> None:
    now = int(time.time())
    result_sha = "sha256:" + hashlib.sha256(("result:" + suffix).encode("utf-8")).hexdigest()
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": "are-code-%s" % suffix,
            "release_id": "RC7",
            "artifact_version": 1,
            "mission_id": MISSION,
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "coordinator-code",
            "occurred_at": now,
            "worker_instance_id": ANALYZER,
            "agent_id": "code-analysis",
            "attempt_id": attempt_id,
            "assignment_id": "assign-code-1",
            "lease_id": "lease-code-1",
            "parent_worker_id": "coordinator-code",
            "scope": "task:%s" % TASK_ID,
            "input_refs": [],
            "tool_calls": [{"call_ref": call_ref, "tool_name": tool_name}],
            "output_refs": [],
            "evidence_refs": [],
            "started_at": now,
            "finished_at": now,
            "result": "PASS",
            "tool_call": {
                "call_ref": call_ref,
                "tool_name": tool_name,
                "arguments": arguments,
                "result_ref": "dsh-event://tool-result/%s" % suffix,
                "result_sha256": result_sha,
                "result_status": "SUCCESS",
            },
        },
    )


def _semantic_payload(*, codegraph_required: bool = True):
    return {
        "requirement_ids": ["REQ-RATE-001"],
        "source_revisions": {TARGET: "abc123..def456"},
        "changed_files": ["RateService.java"],
        "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
        "symbol_explanations": [
            {"symbol_id": "SYM-1", "evidence_refs": ["evidence://git/diff"]}
        ],
        "reverse_requirement_mappings": [
            {
                "requirement_id": "REQ-RATE-001",
                "symbol_id": "SYM-1",
                "evidence_ref": "evidence://git/diff",
            }
        ],
        "impact_surfaces": [
            {
                "id": "SURF-CALLER-1",
                "kind": "CALLER",
                "source_symbol_id": "SYM-1",
                "source_file": "RateService.java",
                "target_ref": "RateController.adjustRate",
            },
            {
                "id": "SURF-API-1",
                "kind": "API",
                "source_symbol_id": "SYM-1",
                "source_file": "RateService.java",
                "target_ref": "POST /loan/rate/adjust",
            },
            {
                "id": "SURF-DB-1",
                "kind": "DATABASE",
                "source_symbol_id": "SYM-1",
                "source_file": "RateService.java",
                "target_ref": "loan_rate.rate",
            },
        ],
        "impact_dimension_exclusions": [
            {
                "dimension": dimension,
                "reason": "real Git/CodeGraph analysis found no %s impact for SYM-1" % dimension,
                "basis_symbol_ids": ["SYM-1"],
            }
            for dimension in (
                "CONFIG",
                "EVENT",
                "ERROR",
                "TRANSACTION",
                "SIDE_EFFECT",
                "SECURITY",
                "PERFORMANCE",
            )
        ],
        # Worker-authored calls and graph_evidence are intentionally forged.
        # The evaluator must replace both from current R1 runtime provenance.
        "tool_calls": [
            {
                "tool_id": "git",
                "call_ref": "worker-fake://git",
                "evidence_ref": "worker-fake://git-evidence",
                "target_id": TARGET,
            },
            {
                "tool_id": "codegraph",
                "call_ref": "worker-fake://codegraph",
                "evidence_ref": "worker-fake://codegraph-evidence",
                "target_id": TARGET,
            },
        ],
        "graph_evidence": [{"evidence_id": "worker-fake://graph"}],
        "evidence_refs": ["evidence://git/diff", "evidence://codegraph/callers"],
        "codegraph_required": codegraph_required,
    }


def _runtime(tmp_path, *, actual_tool_events: bool, codegraph_required: bool = True):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="prove real code tool evidence"),
    )
    task = Task(
        task_id=TASK_ID,
        mission_id=MISSION,
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective="analyze changed code with real Git and CodeGraph evidence",
        required_capabilities=["code_reasoning", "code_reality"],
    )
    control.register_task(task)
    leased = control.lease_next(
        worker_ref=ANALYZER,
        capabilities=["code_reasoning", "code_reality"],
    )
    assert leased is not None
    control.start(TASK_ID, worker_ref=ANALYZER)

    source_evidence = Evidence(
        evidence_id="EVD-GIT-SOURCE",
        mission_id=MISSION,
        kind="GIT_DIFF",
        source_ref="git://cfg-data/abc123..def456",
        content_ref="evidence://git/diff",
        subject_refs=[TASK_ID, TARGET],
    )
    graph_evidence = Evidence(
        evidence_id="EVD-CODEGRAPH-SOURCE",
        mission_id=MISSION,
        kind="CODEGRAPH_QUERY",
        source_ref="codegraph://cfg-data/RateService.adjustRate/callers",
        content_ref="evidence://codegraph/callers",
        subject_refs=[TASK_ID, TARGET],
    )
    runtime_evidence = Evidence(
        evidence_id="EVD-DSH-CODE-RUNTIME",
        mission_id=MISSION,
        kind="DSH_RUNTIME_PROOF",
        source_ref="dsh://worker/%s" % ANALYZER,
        content_ref="dsh://session/session-code-analyzer",
        subject_refs=[TASK_ID, CURRENT_ATTEMPT],
    )
    envelope = {
        "task_id": TASK_ID,
        "artifact": {
            "artifact_id": ARTIFACT_ID,
            "artifact_type": "CODE_IMPACT_MODEL",
            "content_ref": "source://code-analysis",
            "parent_refs": [],
            "evidence_refs": [source_evidence.evidence_id, graph_evidence.evidence_id, runtime_evidence.evidence_id],
        },
        "semantic_payload": _semantic_payload(codegraph_required=codegraph_required),
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "code-candidate.json"
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=ARTIFACT_ID,
        mission_id=MISSION,
        artifact_type="CODE_IMPACT_MODEL",
        producer_task_id=TASK_ID,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[source_evidence.evidence_id, graph_evidence.evidence_id, runtime_evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=TASK_ID,
            worker_ref=ANALYZER,
            artifacts=(artifact,),
            evidence=(source_evidence, graph_evidence, runtime_evidence),
        )
    )
    if actual_tool_events:
        _append_worker_tool_event(
            truth,
            tool_name="mcp__pfc_aitest_rc7__git_diff",
            call_ref="dsh-event://git/diff/abc123..def456",
            suffix="git",
            arguments={"repo_path": TARGET, "base_ref": "abc123", "head_ref": "def456"},
        )
        _append_worker_tool_event(
            truth,
            tool_name="mcp__pfc_aitest_rc7__codegraph_query",
            call_ref="dsh-event://codegraph/callers/RateService.adjustRate",
            suffix="codegraph",
            arguments={"repo_path": TARGET, "args": ["callers", "RateService.adjustRate", "--json"]},
        )
    return truth, control


def test_code_gate_passes_only_after_current_r1_git_and_codegraph_results(tmp_path) -> None:
    truth, control = _runtime(tmp_path, actual_tool_events=True)
    launcher = FakeCodeReviewerLauncher()

    evaluated = DshCodeEvaluator(launcher).evaluate_and_apply(
        control,
        TASK_ID,
        ARTIFACT_ID,
        target_id=TARGET,
    )

    assert evaluated.analyzer_worker_id == ANALYZER
    assert evaluated.reviewer_worker_id == "worker-code-reviewer"
    assert evaluated.reviewer_worker_id != evaluated.analyzer_worker_id
    assert evaluated.loop_result.evaluation.result == EvaluationResult.PASS
    assert control.scheduler.task(TASK_ID).state == TaskStatus.PASS
    assert {item["tool_id"] for item in evaluated.analysis["tool_calls"]} == {"git", "codegraph"}
    assert all(not item["call_ref"].startswith("worker-fake://") for item in evaluated.analysis["tool_calls"])
    assert evaluated.analysis["symbol_explanations"][0]["evidence_refs"] == ["EVD-GIT-SOURCE"]
    assert evaluated.analysis["reverse_requirement_mappings"][0]["evidence_ref"] == "EVD-GIT-SOURCE"
    assert evaluated.loop_result.evaluation.dimensions["code_impact_sufficiency_v2_ready"] is True
    assert evaluated.loop_result.evaluation.dimensions["metrics"]["impact_sufficiency_v2"]["impact_surface_count"] == 3
    assert len(evaluated.analysis["graph_evidence"]) == 1
    runtime_graph = evaluated.analysis["graph_evidence"][0]
    assert runtime_graph["analyzer_attempt_id"] == CURRENT_ATTEMPT
    assert runtime_graph["source_revision"] == "abc123..def456"
    assert runtime_graph["changed_files"] == ["RateService.java"]
    assert runtime_graph["changed_symbol_ids"] == ["SYM-1"]
    graph_rows = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "GRAPH_EVIDENCE_CURRENT_ANALYSIS"
    ]
    assert len(graph_rows) == 1
    assert runtime_graph["evidence_id"] == graph_rows[0]["evidence_id"]


def test_worker_claimed_calls_cannot_pass_without_current_r1_events(tmp_path) -> None:
    _truth, control = _runtime(tmp_path, actual_tool_events=False)
    launcher = FakeCodeReviewerLauncher()

    evaluated = DshCodeEvaluator(launcher).evaluate_and_apply(
        control,
        TASK_ID,
        ARTIFACT_ID,
        target_id=TARGET,
    )

    assert evaluated.analysis["tool_calls"] == []
    assert evaluated.analysis["graph_evidence"] == []
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    reasons = evaluated.loop_result.evaluation.dimensions["reasons"]
    assert "GIT_REAL_TOOL_EVIDENCE_MISSING" in reasons
    assert "CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING" in reasons
    assert control.scheduler.task(TASK_ID).state == TaskStatus.REPAIR_REQUIRED


def test_stale_prior_attempt_tool_events_cannot_satisfy_current_analysis(tmp_path) -> None:
    truth, control = _runtime(tmp_path, actual_tool_events=False)
    _append_worker_tool_event(
        truth,
        tool_name="mcp__pfc_aitest_rc7__git_diff",
        call_ref="dsh-event://stale/git",
        suffix="stale-git",
        arguments={"repo_path": TARGET, "base_ref": "abc123", "head_ref": "def456"},
        attempt_id="attempt-old",
    )
    _append_worker_tool_event(
        truth,
        tool_name="mcp__pfc_aitest_rc7__codegraph_query",
        call_ref="dsh-event://stale/codegraph",
        suffix="stale-codegraph",
        arguments={"repo_path": TARGET, "args": ["callers", "RateService.adjustRate", "--json"]},
        attempt_id="attempt-old",
    )

    evaluated = DshCodeEvaluator(FakeCodeReviewerLauncher()).evaluate_and_apply(
        control, TASK_ID, ARTIFACT_ID, target_id=TARGET
    )
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert evaluated.analysis["graph_evidence"] == []


def test_probe_or_list_is_not_a_codegraph_query_result(tmp_path) -> None:
    truth, control = _runtime(tmp_path, actual_tool_events=False)
    _append_worker_tool_event(
        truth,
        tool_name="mcp__pfc_aitest_rc7__git_diff",
        call_ref="dsh-event://git/current",
        suffix="current-git",
        arguments={"repo_path": TARGET, "base_ref": "abc123", "head_ref": "def456"},
    )
    _append_worker_tool_event(
        truth,
        tool_name="mcp__pfc_aitest_rc7__codegraph_query",
        call_ref="dsh-event://codegraph/probe",
        suffix="probe",
        arguments={"repo_path": TARGET, "args": ["probe", "RateService.adjustRate"]},
    )

    evaluated = DshCodeEvaluator(FakeCodeReviewerLauncher()).evaluate_and_apply(
        control, TASK_ID, ARTIFACT_ID, target_id=TARGET
    )
    reasons = evaluated.loop_result.evaluation.dimensions["reasons"]
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING" in reasons
    assert evaluated.analysis["graph_evidence"] == []


def test_java_change_cannot_opt_out_of_codegraph(tmp_path) -> None:
    truth, control = _runtime(tmp_path, actual_tool_events=False, codegraph_required=False)
    _append_worker_tool_event(
        truth,
        tool_name="mcp__pfc_aitest_rc7__git_diff",
        call_ref="dsh-event://git/current",
        suffix="git-only",
        arguments={"repo_path": TARGET, "base_ref": "abc123", "head_ref": "def456"},
    )

    evaluated = DshCodeEvaluator(FakeCodeReviewerLauncher()).evaluate_and_apply(
        control, TASK_ID, ARTIFACT_ID, target_id=TARGET
    )
    reasons = evaluated.loop_result.evaluation.dimensions["reasons"]
    assert evaluated.analysis["codegraph_required"] is True
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert "CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING" in reasons
