from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane, Mission, MissionTaskGraphCompiler


def test_external_inputs_are_bound_into_canonical_node_tasks(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    mission_id = "MISSION-EXTERNAL-INPUTS"
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=mission_id, release_id="RC7", goal="bind real sources into runtime tasks"),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(
        control,
        mission_id,
        external_inputs={
            "REQUIREMENT_ANALYSIS": (
                "file:///inputs/STB915-7489.md",
                "file:///inputs/STB913-14130.md",
            ),
            "CODE_ANALYSIS": ("git://cfg-data/revision/abc123",),
            "EXECUTION": ("env://bank-test",),
        },
    )

    requirement = control.scheduler.task(graph.task("REQUIREMENT_ANALYSIS").task_id)
    assert requirement.input_artifact_refs == [
        "file:///inputs/STB915-7489.md",
        "file:///inputs/STB913-14130.md",
    ]

    code = control.scheduler.task(graph.task("CODE_ANALYSIS").task_id)
    assert code.input_artifact_refs == [
        graph.artifact_ids["REQUIREMENT_ANALYSIS"],
        "git://cfg-data/revision/abc123",
    ]

    execution = control.scheduler.task(graph.task("EXECUTION").task_id)
    assert execution.input_artifact_refs == [
        graph.artifact_ids["SCRIPT_READINESS"],
        "env://bank-test",
    ]

    # Inputs are durable task truth, not transient constructor state.
    replay = TruthRuntime(tmp_path / "r1.jsonl")
    row = replay.query("rc7_task", task_id=requirement.task_id)[0]
    assert row["input_artifact_refs"] == requirement.input_artifact_refs


def test_external_input_contract_rejects_unknown_node_and_string_shortcut() -> None:
    compiler = MissionTaskGraphCompiler()
    with pytest.raises(ValueError, match="MISSION_GRAPH_EXTERNAL_INPUT_NODE_UNKNOWN"):
        compiler.compile("MISSION-BAD-NODE", external_inputs={"UNKNOWN": ("file:///x",)})

    with pytest.raises(ValueError, match="MISSION_GRAPH_EXTERNAL_INPUTS_MUST_BE_SEQUENCE"):
        compiler.compile(
            "MISSION-BAD-SHAPE",
            external_inputs={"REQUIREMENT_ANALYSIS": "file:///not-a-sequence"},
        )
