from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Task, TaskStatus
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.session_continuity import SessionContinuityManager


def test_running_task_rotates_a_to_b_without_task_recreation_or_chat_history(tmp_path) -> None:
    event_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(event_path)
    scheduler = TaskScheduler(truth, "RC7")
    scheduler.register(
        Task(
            task_id="TASK-LONG-1",
            mission_id="MISSION-1",
            node="CODE_ANALYSIS",
            task_type="PRODUCE",
            objective="continue a long code-analysis task across sessions",
            required_capabilities=["code_reasoning"],
        )
    )
    scheduler.refresh_ready("MISSION-1")
    task = scheduler.lease_next(
        "MISSION-1",
        worker_ref="SESSION-A",
        capabilities=["code_reasoning"],
    )
    assert task is not None
    scheduler.start(task.task_id, worker_ref="SESSION-A")
    before = truth.query("rc7_task", task_id=task.task_id)[0]
    assert before["state"] == "RUNNING"
    assert before["lease_owner"] == "SESSION-A"

    continuity = SessionContinuityManager(truth, "RC7")
    handoff = continuity.prepare(
        mission_id="MISSION-1",
        task_id=task.task_id,
        predecessor_session_ref="SESSION-A",
        artifact_refs=("ART-CODE-PARTIAL-1",),
        gap_refs=("GAP-CODE-OPEN-1",),
    )
    assert handoff.status.value == "PREPARED"

    activated = continuity.activate(handoff.handoff_id, "SESSION-B")
    assert activated.status.value == "ACTIVATED"
    envelope = continuity.resume_envelope(handoff.handoff_id)
    assert envelope == {
        "mission_id": "MISSION-1",
        "task_id": "TASK-LONG-1",
        "task_state": "RUNNING",
        "generation": 1,
        "active_session_ref": "SESSION-B",
        "artifact_refs": ["ART-CODE-PARTIAL-1"],
        "gap_refs": ["GAP-CODE-OPEN-1"],
    }
    assert "conversation" not in envelope
    assert "transcript" not in envelope

    # Fresh process/runtime reconstructs exactly the same active Task from R1.
    replayed = TruthRuntime(event_path)
    scheduler2 = TaskScheduler(replayed, "RC7")
    resumed = scheduler2.task("TASK-LONG-1")
    assert resumed.task_id == task.task_id
    assert resumed.state == TaskStatus.RUNNING
    assert resumed.lease_owner == "SESSION-B"
    rows = replayed.query("rc7_task", mission_id="MISSION-1")
    assert [row["task_id"] for row in rows] == ["TASK-LONG-1"]


def test_successor_must_be_fresh_and_prepared_handoff_must_be_activated_first(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    scheduler = TaskScheduler(truth, "RC7")
    scheduler.register(
        Task(
            task_id="TASK-1",
            mission_id="MISSION-1",
            node="TEST_DESIGN",
            task_type="PRODUCE",
            objective="long design task",
            required_capabilities=["test_design"],
        )
    )
    scheduler.refresh_ready("MISSION-1")
    scheduler.lease_next("MISSION-1", worker_ref="SESSION-A", capabilities=["test_design"])
    scheduler.start("TASK-1", worker_ref="SESSION-A")

    continuity = SessionContinuityManager(truth, "RC7")
    first = continuity.prepare(
        mission_id="MISSION-1",
        task_id="TASK-1",
        predecessor_session_ref="SESSION-A",
    )
    with pytest.raises(RuntimeError, match="SUCCESSOR_ACTIVATION_REQUIRED"):
        continuity.prepare(
            mission_id="MISSION-1",
            task_id="TASK-1",
            predecessor_session_ref="SESSION-A",
        )
    with pytest.raises(RuntimeError, match="SUCCESSOR_SESSION_MUST_BE_FRESH"):
        continuity.activate(first.handoff_id, "SESSION-A")

    continuity.activate(first.handoff_id, "SESSION-B")
    second = continuity.prepare(
        mission_id="MISSION-1",
        task_id="TASK-1",
        predecessor_session_ref="SESSION-B",
    )
    with pytest.raises(RuntimeError, match="SUCCESSOR_SESSION_MUST_BE_FRESH"):
        continuity.activate(second.handoff_id, "SESSION-A")
