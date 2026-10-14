from __future__ import annotations

import pytest

from rc7_runtime import Artifact, ArtifactStatus, Task, TaskStatus
from rc7_runtime.invalidation import ArtifactDependencyGraph, DependencyError


def _artifact(artifact_id: str, artifact_type: str, parents=None) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        mission_id="MISSION-1",
        artifact_type=artifact_type,
        producer_task_id="TASK-" + artifact_id,
        content_ref="artifact://" + artifact_id,
        parent_refs=list(parents or []),
    )


def test_requirement_change_invalidates_only_dependent_chain() -> None:
    req = _artifact("REQ-V1", "REQUIREMENT_MODEL")
    obligation = _artifact("OBL-V1", "TEST_OBLIGATION_SET", [req.artifact_id])
    cases = _artifact("CASE-V1", "TEST_CASE_SET", [obligation.artifact_id])
    script = _artifact("SCRIPT-V1", "TEST_SCRIPT", [cases.artifact_id])
    unrelated = _artifact("HISTORY-V1", "HISTORICAL_ASSET_SET")

    artifacts = {item.artifact_id: item for item in (req, obligation, cases, script, unrelated)}
    graph = ArtifactDependencyGraph()
    for artifact in artifacts.values():
        graph.register_artifact(artifact)

    case_task = Task(
        task_id="TASK-CASE",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="Produce cases",
        state=TaskStatus.PASS,
        input_artifact_refs=[obligation.artifact_id],
        output_artifact_refs=[cases.artifact_id],
        evaluation_id="EVAL-CASE",
    )
    unrelated_task = Task(
        task_id="TASK-HISTORY",
        mission_id="MISSION-1",
        node="HISTORY",
        task_type="READ",
        objective="Read historical assets",
        state=TaskStatus.PASS,
        output_artifact_refs=[unrelated.artifact_id],
        evaluation_id="EVAL-HISTORY",
    )

    result = graph.invalidate([req.artifact_id], artifacts, [case_task, unrelated_task])

    assert result.affected_artifact_ids == ("CASE-V1", "OBL-V1", "SCRIPT-V1")
    assert obligation.state == ArtifactStatus.REVALIDATION_REQUIRED
    assert cases.state == ArtifactStatus.REVALIDATION_REQUIRED
    assert script.state == ArtifactStatus.REVALIDATION_REQUIRED
    assert unrelated.state == ArtifactStatus.VALID
    assert case_task.state == TaskStatus.STALE
    assert unrelated_task.state == TaskStatus.PASS
    assert result.stale_task_ids == ("TASK-CASE",)


def test_dependency_cycle_is_rejected() -> None:
    graph = ArtifactDependencyGraph()
    graph.add("A", "B")
    graph.add("B", "C")
    with pytest.raises(DependencyError, match="DEPENDENCY_CYCLE_FORBIDDEN"):
        graph.add("C", "A")
