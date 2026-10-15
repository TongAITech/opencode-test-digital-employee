from __future__ import annotations

from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission, MissionTaskGraphCompiler
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, GapStatus, TaskStatus


MISSION = "MISSION-DSH-REPAIR-RERUN"


class RerunLauncher:
    def __init__(self, graph, state_root):
        self.graph = graph
        self.state_root = state_root
        self.coordinator_instance_id = "coordinator-control-plane"
        self.assignments = []
        self.executions = 0

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
        number = len(self.assignments) + 1
        assignment = SimpleNamespace(
            worker_instance_id="worker-dsh-rerun-%d" % number,
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id="assign-%d" % number,
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )
        self.assignments.append(assignment)
        return assignment

    def execute(self, assignment, prompt):
        self.executions += 1
        number = self.executions
        invocation = SimpleNamespace(
            mission_id=assignment.mission_id,
            worker_instance_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,
            dsh_session_id="session-rerun-%d" % number,
            tool_calls=(
                {
                    "tool_name": "filesystem",
                    "call_ref": "tool://requirement/%d" % number,
                    "arguments": {"revision": number},
                },
            ),
            evidence_refs=("file:///tmp/rc7-rerun-%d.jsonl" % number,),
        )
        task_id = assignment.scope.split("task:", 1)[1]
        output = {
            "task_id": task_id,
            "artifact": {
                "artifact_id": self.graph.artifact_ids["REQUIREMENT_ANALYSIS"],
                "artifact_type": "REQUIREMENT_MODEL",
                "content_ref": "worker://requirement/revision/%d" % number,
                "parent_refs": [],
                "evidence_refs": [],
            },
            "semantic_payload": {
                "revision": number,
                "business_rules": [{"id": "BR-RERUN", "revision": number}],
            },
            "evidence": [
                {
                    "kind": "SOURCE_DOCUMENT",
                    "source_ref": "filesystem://sst.md",
                    "content_ref": "evidence://sst/revision/%d" % number,
                    "subject_refs": [task_id],
                }
            ],
        }
        return invocation, output


def test_gap_repair_source_rerun_advances_same_artifact_revision(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="prove repair rerun revision lineage"),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(control, MISSION)
    launcher = RerunLauncher(graph, tmp_path / "dsh-state")
    bridge = DshTaskWorkerBridge(control, launcher)

    first = bridge.run_next()
    assert first is not None
    source_task_id = graph.task("REQUIREMENT_ANALYSIS").task_id
    artifact_id = graph.artifact_ids["REQUIREMENT_ANALYSIS"]
    assert first.task_id == source_task_id
    assert truth.query("rc7_artifact", artifact_id=artifact_id)[0]["version"] == 1

    gap = Gap(
        gap_id="GAP-REQ-RERUN-BOUNDARY",
        mission_id=MISSION,
        source_node="REQUIREMENT_ANALYSIS",
        category="MISSING_BOUNDARY",
        severity=GapSeverity.HIGH,
        target_node="REQUIREMENT_ANALYSIS",
        description="boundary rule is missing from first candidate",
        subject_refs=[artifact_id],
        evidence_refs=[first.evidence_ids[0]],
        acceptance_criteria=["boundary rule is evidenced and independently re-evaluated"],
    )
    first_eval = Evaluation(
        evaluation_id="EVAL-REQ-RERUN-1",
        mission_id=MISSION,
        node="REQUIREMENT_ANALYSIS",
        artifact_refs=[artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="independent-requirement-evaluator",
        gap_refs=[gap.gap_id],
        evidence_refs=[first.evidence_ids[0]],
    )
    control.accept_evaluation(source_task_id, evaluation=first_eval, gaps=(gap,))

    repair = next(
        task
        for task in control.scheduler.ready_tasks(MISSION)
        if task.task_type == "REPAIR" and task.gap_refs == [gap.gap_id]
    )
    leased = control.lease_next(
        worker_ref="worker-requirement-repair",
        capabilities=repair.required_capabilities,
    )
    assert leased is not None and leased.task_id == repair.task_id
    control.start(repair.task_id, worker_ref="worker-requirement-repair")
    repair_evidence = Evidence(
        evidence_id="EVD-REQ-RERUN-REPAIR",
        mission_id=MISSION,
        kind="REPAIR_PROOF",
        source_ref="dsh://worker/worker-requirement-repair",
        content_ref="evidence://repair/boundary",
        subject_refs=[repair.task_id, gap.gap_id],
    )
    repair_artifact = Artifact(
        artifact_id="ART-REQ-RERUN-REPAIR",
        mission_id=MISSION,
        artifact_type="REQUIREMENT_ANALYSIS_OUTPUT",
        producer_task_id=repair.task_id,
        content_ref="artifact://repair/boundary",
        evidence_refs=[repair_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair.task_id,
            worker_ref="worker-requirement-repair",
            artifacts=(repair_artifact,),
            evidence=(repair_evidence,),
        )
    )
    repair_eval = Evaluation(
        evaluation_id="EVAL-REQ-RERUN-REPAIR",
        mission_id=MISSION,
        node="REQUIREMENT_ANALYSIS",
        artifact_refs=[repair_artifact.artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-repair-evaluator",
        evidence_refs=[repair_evidence.evidence_id],
    )
    control.accept_evaluation(repair.task_id, evaluation=repair_eval)

    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == GapStatus.EVIDENCE_PENDING.value
    assert control.scheduler.task(source_task_id).state == TaskStatus.READY

    second = bridge.run_next()
    assert second is not None and second.task_id == source_task_id
    latest = truth.query("rc7_artifact", artifact_id=artifact_id)[0]
    assert latest["version"] == 2
    history = truth.projection.history("rc7_artifact", artifact_id)
    assert [row["version"] for row in history] == [1, 2]
    assert history[0]["content_hash"] != history[1]["content_hash"]
    assert launcher.assignments[0].attempt_id != launcher.assignments[1].attempt_id

    second_eval = Evaluation(
        evaluation_id="EVAL-REQ-RERUN-2",
        mission_id=MISSION,
        node="REQUIREMENT_ANALYSIS",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-requirement-evaluator-2",
        evidence_refs=[second.evidence_ids[0]],
    )
    control.accept_evaluation(source_task_id, evaluation=second_eval)
    resolved = truth.query("rc7_gap", gap_id=gap.gap_id)[0]
    assert resolved["state"] == GapStatus.RESOLVED.value
    assert resolved["resolution_evaluation_id"] == second_eval.evaluation_id
