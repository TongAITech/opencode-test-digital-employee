from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    ClosedLoopControlPlane,
    Evaluation,
    EvaluationResult,
    Evidence,
    Mission,
    MissionStatus,
    MissionTaskGraphCompiler,
    TaskStatus,
)
from rc7_runtime.control_plane import WorkerOutput


def test_runtime_compiled_core_graph_executes_same_mission_to_convergence(tmp_path) -> None:
    path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="MISSION-E2E-1",
            release_id="RC7",
            goal="requirement to execution closed-loop mission",
        ),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(control, "MISSION-E2E-1")

    # Runtime owns the initial route. Code cannot run before Requirement PASS;
    # Design cannot run before both Requirement/Code PASS, and so on.
    assert control.snapshot()["ready_task_ids"] == [graph.task("REQUIREMENT_ANALYSIS").task_id]

    for index, node in enumerate(compiler.NODE_ORDER, start=1):
        task = graph.task(node)
        worker = "worker-%s" % node.lower()
        leased = control.lease_next(
            worker_ref=worker,
            capabilities=compiler.REQUIRED_CAPABILITIES[node],
        )
        assert leased is not None
        assert leased.task_id == task.task_id
        control.start(task.task_id, worker_ref=worker)

        evidence_id = "EVD-E2E-%s" % node
        artifact_id = graph.artifact_ids[node]
        candidate = control.submit_worker_output(
            WorkerOutput(
                task_id=task.task_id,
                worker_ref=worker,
                evidence=(
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id="MISSION-E2E-1",
                        kind="NODE_OUTPUT_PROOF",
                        source_ref="worker://%s" % worker,
                        content_ref="evidence://%s" % evidence_id,
                    ),
                ),
                artifacts=(
                    Artifact(
                        artifact_id=artifact_id,
                        mission_id="MISSION-E2E-1",
                        artifact_type=compiler.OUTPUT_TYPES[node],
                        producer_task_id=task.task_id,
                        content_ref="artifact://%s" % artifact_id,
                        parent_refs=list(task.input_artifact_refs),
                        evidence_refs=[evidence_id],
                    ),
                ),
            )
        )
        assert candidate.state == TaskStatus.OUTPUT_PRODUCED

        evaluation = Evaluation(
            evaluation_id="EVAL-E2E-%02d-%s" % (index, node),
            mission_id="MISSION-E2E-1",
            node=node,
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="evaluator-%s" % node.lower(),
            dimensions={"gate_status": "PASS", "same_mission": True},
            evidence_refs=[evidence_id],
        )
        accepted = control.accept_evaluation(task.task_id, evaluation=evaluation)
        assert accepted.state == TaskStatus.PASS

        if index < len(compiler.NODE_ORDER):
            next_node = compiler.NODE_ORDER[index]
            ready = control.snapshot()["ready_task_ids"]
            assert ready == [graph.task(next_node).task_id]

    before_convergence = control.snapshot()
    assert before_convergence["ready_task_ids"] == []
    assert before_convergence["open_gap_ids"] == []
    assert all(
        control.scheduler.task(graph.task(node).task_id).state == TaskStatus.PASS
        for node in compiler.NODE_ORDER
    )

    mission_eval = Evaluation(
        evaluation_id="EVAL-E2E-MISSION",
        mission_id="MISSION-E2E-1",
        node="MISSION_EVALUATION",
        artifact_refs=[graph.artifact_ids["EXECUTION"]],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={
            "sufficiency_state": "SUFFICIENT",
            "workflow_complete": True,
            "test_sufficient": True,
        },
        evidence_refs=["EVD-E2E-EXECUTION"],
    )
    mission = control.converge_mission(mission_eval)
    assert mission.state == MissionStatus.CONVERGED

    # Process/session recreation must not lose the graph or completion truth.
    replayed = TruthRuntime(path)
    recovered = ClosedLoopControlPlane(replayed, "RC7", "MISSION-E2E-1")
    assert recovered.snapshot()["mission_state"] == "CONVERGED"
    for node in compiler.NODE_ORDER:
        assert recovered.scheduler.task(graph.task(node).task_id).state == TaskStatus.PASS

    # Defect is intentionally not pre-created. It only exists when Execution
    # produces a trusted PRODUCT_DEFECT Gap.
    assert not [row for row in replayed.query("rc7_task", mission_id="MISSION-E2E-1") if row["node"] == "DEFECT"]
