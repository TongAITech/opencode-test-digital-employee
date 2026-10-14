from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, ClosedLoopControlPlane, Evidence, Mission, Task, TaskStatus
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.dsh_test_design_evaluator import DshTestDesignEvaluator, DshTestDesignEvaluatorError
from rc7_runtime.models import EvaluationResult


MISSION = "MISSION-DSH-TEST-DESIGN"
TASK_ID = "TASK-DSH-TEST-DESIGN"
ARTIFACT_ID = "ART-DSH-TEST-DESIGN"
DESIGNER = "worker-test-designer"


class FakeDesignReviewerLauncher:
    def __init__(self, *, tool_mode="full", decision="PASS", gap_ids=None) -> None:
        self.coordinator_instance_id = "coordinator-design-review"
        self.tool_mode = tool_mode
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
        assert role == "RC7_TEST_DESIGN_REVIEWER"
        return SimpleNamespace(
            worker_instance_id="worker-test-design-reviewer",
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-design-reviewer",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment, prompt):
        self.prompts.append(prompt)
        if self.tool_mode == "full":
            calls = (
                {"call_ref": "dsh-review://read/parents", "tool_name": "mcp__pfc_aitest_rc7__read_text"},
                {"call_ref": "dsh-review://codegraph/impact", "tool_name": "mcp__pfc_aitest_rc7__codegraph_query"},
            )
        else:
            calls = (
                {"call_ref": "dsh-review://runtime/status", "tool_name": "mcp__pfc_aitest_rc6__runtime_status"},
            )
        reviewer = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-test-design-reviewer",
            tool_calls=calls,
            evidence_refs=("dsh://session/session-test-design-reviewer",),
        )
        return reviewer, {
            "decision": self.decision,
            "gap_ids": list(self.gap_ids),
            "summary": "independent design review",
        }


def _append_tool_event(truth, tool_name, suffix):
    now = int(time.time())
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": "are-td-%s" % suffix,
            "release_id": "RC7",
            "artifact_version": 1,
            "mission_id": MISSION,
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "coordinator-design",
            "occurred_at": now,
            "worker_instance_id": DESIGNER,
            "agent_id": "test-design",
            "attempt_id": "attempt-design-1",
            "assignment_id": "assign-design-1",
            "lease_id": "lease-design-1",
            "parent_worker_id": "coordinator-design",
            "scope": "task:%s" % TASK_ID,
            "input_refs": [],
            "tool_calls": [{"call_ref": "dsh-event://%s" % suffix, "tool_name": tool_name}],
            "output_refs": [],
            "evidence_refs": [],
            "started_at": now,
            "finished_at": now,
            "result": "PASS",
            "tool_call": {"call_ref": "dsh-event://%s" % suffix, "tool_name": tool_name},
        },
    )


def _semantic_payload(*, bad_evidence=False):
    evidence = "invented://not-durable" if bad_evidence else "evidence://design/source"
    return {
        "obligations": [
            {
                "obligation_id": "OBL-RULE-1",
                "kind": "BUSINESS_RULE",
                "layer": "L3",
                "risk": "HIGH",
                "required": True,
                "evidence_refs": [evidence],
            },
            {
                "obligation_id": "OBL-CODE-1",
                "kind": "CODE_IMPACT",
                "layer": "L3",
                "risk": "HIGH",
                "required": True,
                "evidence_refs": [evidence],
            },
        ],
        "cases": [
            {
                "tc_id": "TC-RATE-1",
                "layer": "L3",
                "risk": "HIGH",
                "status": "CANDIDATE",
                "coverage_links": [
                    {"subject_id": "OBL-RULE-1", "evidence_ref": evidence},
                    {"subject_id": "OBL-CODE-1", "evidence_ref": evidence},
                ],
                "action_semantics": {
                    "state_changing": False,
                    "negative": False,
                    "authorization_sensitive": False,
                },
                "oracle": {
                    "checks": [
                        {"type": "API_RESPONSE", "evidence_ref": evidence},
                        {"type": "BUSINESS_RULE", "evidence_ref": evidence},
                        {"type": "EVIDENCE_CORRELATION", "evidence_ref": evidence},
                    ]
                },
            }
        ],
    }


def _runtime(tmp_path, *, producer_proof=True, bad_evidence=False):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="prove semantic test design sufficiency"),
    )
    task = Task(
        task_id=TASK_ID,
        mission_id=MISSION,
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="produce obligation-driven test design",
        required_capabilities=["test_design"],
    )
    control.register_task(task)
    leased = control.lease_next(worker_ref=DESIGNER, capabilities=["test_design"])
    assert leased is not None
    control.start(TASK_ID, worker_ref=DESIGNER)

    evidence = Evidence(
        evidence_id="EVD-DESIGN-SOURCE",
        mission_id=MISSION,
        kind="DESIGN_SOURCE",
        source_ref="source://requirement+code",
        content_ref="evidence://design/source",
        subject_refs=[TASK_ID],
    )
    envelope = {
        "task_id": TASK_ID,
        "artifact": {
            "artifact_id": ARTIFACT_ID,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "source://test-design",
            "parent_refs": [],
            "evidence_refs": [evidence.evidence_id],
        },
        "semantic_payload": _semantic_payload(bad_evidence=bad_evidence),
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "test-design-candidate.json"
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=ARTIFACT_ID,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id=TASK_ID,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(task_id=TASK_ID, worker_ref=DESIGNER, artifacts=(artifact,), evidence=(evidence,))
    )
    if producer_proof:
        _append_tool_event(truth, "mcp__pfc_aitest_rc7__read_text", "read")
        _append_tool_event(truth, "mcp__pfc_aitest_rc7__codegraph_query", "codegraph")
    return truth, control


def test_design_pass_requires_durable_evidence_real_tools_and_independent_review(tmp_path):
    _truth, control = _runtime(tmp_path, producer_proof=True)
    launcher = FakeDesignReviewerLauncher(tool_mode="full")

    evaluated = DshTestDesignEvaluator(launcher).evaluate_and_apply(control, TASK_ID, ARTIFACT_ID)

    assert evaluated.designer_worker_id == DESIGNER
    assert evaluated.reviewer_worker_id != evaluated.designer_worker_id
    assert evaluated.loop_result.evaluation.result == EvaluationResult.PASS
    assert evaluated.loop_result.semantic_coverage == 1.0
    assert control.scheduler.task(TASK_ID).state == TaskStatus.PASS
    assert evaluated.obligations[0].evidence_refs == ("EVD-DESIGN-SOURCE",)
    assert evaluated.cases[0]["coverage_links"][0]["evidence_ref"] == "EVD-DESIGN-SOURCE"
    assert "Case count is never a sufficiency criterion" in launcher.prompts[0]


def test_worker_claimed_design_is_repair_when_real_source_tools_missing(tmp_path):
    _truth, control = _runtime(tmp_path, producer_proof=False)
    launcher = FakeDesignReviewerLauncher(tool_mode="full")

    evaluated = DshTestDesignEvaluator(launcher).evaluate_and_apply(control, TASK_ID, ARTIFACT_ID)

    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    gaps = evaluated.loop_result.evaluation.dimensions["review_gap_ids"]
    assert "DESIGNER_REAL_SOURCE_READ_MISSING" in gaps
    assert "DESIGNER_CODEGRAPH_PROOF_MISSING" in gaps
    assert control.scheduler.task(TASK_ID).state == TaskStatus.REPAIR_REQUIRED


def test_reviewer_false_pass_cannot_hide_missing_real_review_tools(tmp_path):
    _truth, control = _runtime(tmp_path, producer_proof=True)
    launcher = FakeDesignReviewerLauncher(tool_mode="runtime_only", decision="PASS")

    evaluated = DshTestDesignEvaluator(launcher).evaluate_and_apply(control, TASK_ID, ARTIFACT_ID)

    assert evaluated.review["decision"] == "GAPS"
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    gaps = evaluated.loop_result.evaluation.dimensions["review_gap_ids"]
    assert "REVIEWER_REAL_SOURCE_READ_MISSING" in gaps
    assert "REVIEWER_CODEGRAPH_PROOF_MISSING" in gaps


def test_design_semantic_evidence_alias_must_resolve_to_r1(tmp_path):
    _truth, control = _runtime(tmp_path, producer_proof=True, bad_evidence=True)
    launcher = FakeDesignReviewerLauncher(tool_mode="full")

    with pytest.raises(DshTestDesignEvaluatorError, match="TEST_DESIGN_OBLIGATION_EVIDENCE_NOT_DURABLE"):
        DshTestDesignEvaluator(launcher).evaluate_and_apply(control, TASK_ID, ARTIFACT_ID)
    assert control.scheduler.task(TASK_ID).state == TaskStatus.OUTPUT_PRODUCED
