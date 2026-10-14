from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Task,
    TaskStatus,
    transition_task,
)
from rc7_runtime.control_plane import GapRepairPlanner, TaskScheduler, WorkerOutput
from rc7_runtime.truth_overlay import append_entity


def _accept(scheduler: TaskScheduler, task: Task, evaluation_id: str) -> Task:
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=task.mission_id,
        node=task.node,
        artifact_refs=list(task.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="independent-evaluator",
        evidence_refs=["EVD-EVAL-%s" % evaluation_id],
    )
    append_entity(scheduler.truth, evaluation, release_id=scheduler.release_id)
    transition_task(task, TaskStatus.EVALUATING)
    transition_task(task, TaskStatus.PASS, evaluation_id=evaluation_id)
    scheduler.persist_evaluated_task(task)
    return task


def test_scheduler_releases_only_dependency_ready_tasks_and_worker_cannot_self_accept(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    scheduler = TaskScheduler(truth, "RC7")

    req = Task(
        task_id="TASK-REQ",
        mission_id="MISSION-1",
        node="REQUIREMENT_ANALYSIS",
        task_type="PRODUCE",
        objective="requirements",
        required_capabilities=["requirement_reasoning"],
        priority=10,
    )
    code = Task(
        task_id="TASK-CODE",
        mission_id="MISSION-1",
        node="CODE_ANALYSIS",
        task_type="PRODUCE",
        objective="code impact",
        required_capabilities=["code_reasoning", "code_reality"],
        priority=20,
    )
    design = Task(
        task_id="TASK-DESIGN",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="test obligations and cases",
        required_capabilities=["test_design"],
        dependency_task_ids=["TASK-REQ", "TASK-CODE"],
        input_artifact_refs=["ART-REQ", "ART-CODE"],
        priority=30,
    )
    scheduler.register(req)
    scheduler.register(code)
    scheduler.register(design)

    ready = scheduler.refresh_ready("MISSION-1")
    assert [task.task_id for task in ready] == ["TASK-REQ", "TASK-CODE"]
    assert scheduler.task("TASK-DESIGN").state == TaskStatus.REGISTERED

    leased_req = scheduler.lease_next(
        "MISSION-1",
        worker_ref="worker-req",
        capabilities=["requirement_reasoning"],
    )
    assert leased_req is not None and leased_req.task_id == "TASK-REQ"
    scheduler.start("TASK-REQ", worker_ref="worker-req")
    req_output = scheduler.submit_worker_output(
        WorkerOutput(
            task_id="TASK-REQ",
            worker_ref="worker-req",
            evidence=(
                Evidence(
                    evidence_id="EVD-REQ",
                    mission_id="MISSION-1",
                    kind="SOURCE_DOCUMENT",
                    source_ref="sst://1",
                    content_ref="evidence://req",
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id="ART-REQ",
                    mission_id="MISSION-1",
                    artifact_type="REQUIREMENT_MODEL",
                    producer_task_id="TASK-REQ",
                    content_ref="artifact://req",
                    evidence_refs=["EVD-REQ"],
                ),
            ),
        )
    )
    assert req_output.state == TaskStatus.OUTPUT_PRODUCED
    assert req_output.state != TaskStatus.PASS
    _accept(scheduler, req_output, "EVAL-REQ")

    # Design is still blocked because Code is not accepted yet.
    assert scheduler.refresh_ready("MISSION-1") == ()
    assert scheduler.task("TASK-DESIGN").state == TaskStatus.REGISTERED

    leased_code = scheduler.lease_next(
        "MISSION-1",
        worker_ref="worker-code",
        capabilities=["code_reasoning", "code_reality"],
    )
    assert leased_code is not None and leased_code.task_id == "TASK-CODE"
    scheduler.start("TASK-CODE", worker_ref="worker-code")
    code_output = scheduler.submit_worker_output(
        WorkerOutput(
            task_id="TASK-CODE",
            worker_ref="worker-code",
            evidence=(
                Evidence(
                    evidence_id="EVD-CODE",
                    mission_id="MISSION-1",
                    kind="GIT_DIFF",
                    source_ref="git://base..head",
                    content_ref="evidence://code",
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id="ART-CODE",
                    mission_id="MISSION-1",
                    artifact_type="CODE_IMPACT_MODEL",
                    producer_task_id="TASK-CODE",
                    content_ref="artifact://code",
                    evidence_refs=["EVD-CODE"],
                ),
            ),
        )
    )
    _accept(scheduler, code_output, "EVAL-CODE")

    ready_after_both = scheduler.refresh_ready("MISSION-1")
    assert [task.task_id for task in ready_after_both] == ["TASK-DESIGN"]

    # Fresh TruthRuntime replay derives the same scheduler state from R1 only.
    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    scheduler2 = TaskScheduler(replayed, "RC7")
    assert scheduler2.task("TASK-REQ").state == TaskStatus.PASS
    assert scheduler2.task("TASK-CODE").state == TaskStatus.PASS
    assert scheduler2.task("TASK-DESIGN").state == TaskStatus.READY


def test_gap_router_creates_targeted_repair_task_and_persists_planned_gap(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    scheduler = TaskScheduler(truth, "RC7")
    planner = GapRepairPlanner(truth, "RC7", scheduler)
    gap = Gap(
        gap_id="GAP-ROUTE-1",
        mission_id="MISSION-1",
        source_node="EXECUTION",
        category="API_ROUTE_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="CODE_ANALYSIS",
        description="runtime route differs from static route",
        evidence_refs=["EVD-404", "EVD-NETWORK"],
        acceptance_criteria=["runtime route is confirmed and execution contract updated"],
    )

    repair = planner.plan(gap)
    assert repair is not None
    assert repair.node == "CODE_ANALYSIS"
    assert repair.task_type == "REPAIR"
    assert repair.gap_refs == [gap.gap_id]
    assert set(repair.required_capabilities) == {"code_reasoning", "code_reality"}
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "PLANNED"

    scheduler.refresh_ready("MISSION-1")
    assert scheduler.task(repair.task_id).state == TaskStatus.READY
