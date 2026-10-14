from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, ClosedLoopControlPlane, DshTestDesignEvaluator, Evidence, Mission, Task, TaskStatus
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import EvaluationResult
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-TD-PARENT-INVENTORY"
REQ_ART = "ART-PARENT-REQ"
CODE_ART = "ART-PARENT-CODE"
DESIGN_ART = "ART-PARENT-DESIGN"
TASK_ID = "TASK-PARENT-DESIGN"
DESIGNER = "worker-parent-designer"


class FakeReviewer:
    coordinator_instance_id = "coordinator-parent-review"

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
        return SimpleNamespace(
            worker_instance_id="worker-parent-reviewer",
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-parent-reviewer",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment, prompt):
        reviewer = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-parent-reviewer",
            tool_calls=(
                {"call_ref": "review://read/parents", "tool_name": "mcp__pfc_aitest_rc7__read_text"},
                {"call_ref": "review://codegraph/impact", "tool_name": "mcp__pfc_aitest_rc7__codegraph_query"},
            ),
            evidence_refs=("dsh://session/session-parent-reviewer",),
        )
        # Deliberately false confidence: the deterministic parent inventory must
        # still catch the missing Requirement boundary obligation.
        return reviewer, {"decision": "PASS", "gap_ids": [], "summary": "looks sufficient"}


def _persist_candidate(truth, tmp_path, *, artifact_id, artifact_type, producer_task_id, semantic_payload, evidence_id):
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="PARENT_SOURCE",
        source_ref="source://%s" % artifact_id,
        content_ref="evidence://%s" % artifact_id,
        subject_refs=[artifact_id],
    )
    append_entity(truth, evidence, release_id="RC7", artifact_version=1)
    envelope = {
        "task_id": producer_task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "content_ref": "source://%s" % artifact_id,
            "parent_refs": [],
            "evidence_refs": [evidence_id],
        },
        "semantic_payload": semantic_payload,
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / (artifact_id + ".json")
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type=artifact_type,
        producer_task_id=producer_task_id,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    append_entity(truth, artifact, release_id="RC7", artifact_version=1)


def _tool_event(truth, tool_name, suffix):
    now = int(time.time())
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": "are-parent-%s" % suffix,
            "release_id": "RC7",
            "artifact_version": 1,
            "mission_id": MISSION,
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "coordinator-parent",
            "occurred_at": now,
            "worker_instance_id": DESIGNER,
            "agent_id": "test-design",
            "attempt_id": "attempt-parent-design",
            "assignment_id": "assign-parent-design",
            "lease_id": "lease-parent-design",
            "parent_worker_id": "coordinator-parent",
            "scope": "task:%s" % TASK_ID,
            "input_refs": [REQ_ART, CODE_ART],
            "tool_calls": [{"call_ref": "dsh-event://%s" % suffix, "tool_name": tool_name}],
            "output_refs": [],
            "evidence_refs": [],
            "started_at": now,
            "finished_at": now,
            "result": "PASS",
            "tool_call": {"call_ref": "dsh-event://%s" % suffix, "tool_name": tool_name},
        },
    )


def test_parent_requirement_boundary_cannot_disappear_from_design_denominator(tmp_path):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="parent-derived Test Obligation denominator"),
    )

    _persist_candidate(
        truth,
        tmp_path,
        artifact_id=REQ_ART,
        artifact_type="REQUIREMENT_MODEL",
        producer_task_id="TASK-PARENT-REQ",
        evidence_id="EVD-PARENT-REQ",
        semantic_payload={
            "atomic_statements": [],
            "business_rules": [{"id": "BR-1"}],
            "normal_paths": [],
            "negative_paths": [],
            "boundaries": [{"id": "BOUND-1", "rule": "500000.00 / 500000.01"}],
            "states": [],
            "roles": [],
            "data_constraints": [],
            "side_effects": [],
        },
    )
    _persist_candidate(
        truth,
        tmp_path,
        artifact_id=CODE_ART,
        artifact_type="CODE_IMPACT_MODEL",
        producer_task_id="TASK-PARENT-CODE",
        evidence_id="EVD-PARENT-CODE",
        semantic_payload={
            "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
        },
    )

    task = Task(
        task_id=TASK_ID,
        mission_id=MISSION,
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="design from accepted Requirement and Code parents",
        required_capabilities=["test_design"],
        input_artifact_refs=[REQ_ART, CODE_ART],
    )
    control.register_task(task)
    leased = control.lease_next(worker_ref=DESIGNER, capabilities=["test_design"])
    assert leased is not None
    control.start(TASK_ID, worker_ref=DESIGNER)

    design_evidence = Evidence(
        evidence_id="EVD-PARENT-DESIGN",
        mission_id=MISSION,
        kind="DESIGN_SOURCE",
        source_ref="source://accepted-parents",
        content_ref="evidence://parent-design",
        subject_refs=[TASK_ID, REQ_ART, CODE_ART],
    )
    # The Designer covers its own BUSINESS_RULE and CODE_IMPACT obligations but
    # deliberately omits BOUND-1. Self-authored semantic coverage is therefore
    # 100%, while the parent-derived denominator must still fail it.
    semantic = {
        "obligations": [
            {
                "obligation_id": "OBL-BR-1",
                "kind": "BUSINESS_RULE",
                "layer": "L3",
                "risk": "HIGH",
                "required": True,
                "source_refs": ["BR-1"],
                "evidence_refs": ["evidence://parent-design"],
            },
            {
                "obligation_id": "OBL-CODE-1",
                "kind": "CODE_IMPACT",
                "layer": "L3",
                "risk": "HIGH",
                "required": True,
                "source_refs": ["SYM-1"],
                "evidence_refs": ["evidence://parent-design"],
            },
        ],
        "cases": [
            {
                "tc_id": "TC-PARENT-1",
                "layer": "L3",
                "risk": "HIGH",
                "status": "CANDIDATE",
                "coverage_links": [
                    {"subject_id": "OBL-BR-1", "evidence_ref": "evidence://parent-design"},
                    {"subject_id": "OBL-CODE-1", "evidence_ref": "evidence://parent-design"},
                ],
                "action_semantics": {
                    "state_changing": False,
                    "negative": False,
                    "authorization_sensitive": False,
                },
                "oracle": {
                    "checks": [
                        {"type": "API_RESPONSE", "evidence_ref": "evidence://parent-design"},
                        {"type": "BUSINESS_RULE", "evidence_ref": "evidence://parent-design"},
                        {"type": "EVIDENCE_CORRELATION", "evidence_ref": "evidence://parent-design"},
                    ]
                },
            }
        ],
    }
    envelope = {
        "task_id": TASK_ID,
        "artifact": {
            "artifact_id": DESIGN_ART,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "source://parent-design",
            "parent_refs": [REQ_ART, CODE_ART],
            "evidence_refs": [design_evidence.evidence_id],
        },
        "semantic_payload": semantic,
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "parent-design.json"
    path.write_bytes(raw)
    design_artifact = Artifact(
        artifact_id=DESIGN_ART,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id=TASK_ID,
        content_ref="file://" + str(path.resolve()),
        parent_refs=[REQ_ART, CODE_ART],
        evidence_refs=[design_evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=TASK_ID,
            worker_ref=DESIGNER,
            artifacts=(design_artifact,),
            evidence=(design_evidence,),
        )
    )
    _tool_event(truth, "mcp__pfc_aitest_rc7__read_text", "read")
    _tool_event(truth, "mcp__pfc_aitest_rc7__codegraph_query", "codegraph")

    evaluated = DshTestDesignEvaluator(FakeReviewer()).evaluate_and_apply(control, TASK_ID, DESIGN_ART)

    assert evaluated.loop_result.semantic_coverage == 1.0
    assert evaluated.review["decision"] == "PASS"
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    dimensions = evaluated.loop_result.evaluation.dimensions
    assert dimensions["parent_obligation_source_total"] == 3
    assert dimensions["parent_obligation_missing_total"] == 1
    assert dimensions["parent_obligation_coverage"] == "GAPS"
    assert dimensions["missing_parent_obligation_sources"] == [
        "SOURCE_OBLIGATION_MISSING:BOUNDARY:BOUND-1"
    ]
    assert control.scheduler.task(TASK_ID).state == TaskStatus.REPAIR_REQUIRED
    repair_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row["task_type"] == "REPAIR" and row["node"] == "TEST_DESIGN"
    ]
    assert repair_rows and all(row["state"] == "READY" for row in repair_rows)
