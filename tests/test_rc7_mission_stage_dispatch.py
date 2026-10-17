from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher, MissionStageDispatchError
from rc7_runtime.models import Gap, GapSeverity, Task
from rc7_runtime.reality_recon import RuntimeRealityReconService


def _facts():
    return {
        "release_id": "REL-DISPATCH",
        "source_revision": "commit:dispatch123",
        "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
        "runtime_profile": "BANK_PROTECTED",
    }


def test_v2_dispatch_routes_runtime_reality_before_any_producer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "f" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-DISPATCH",
        release_id="REL-DISPATCH",
        goal="route by graph owner",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "REL-DISPATCH", "MISSION-DISPATCH")
    producer_calls = []
    runtime_calls = []
    reality = RuntimeRealityReconService(evidence_root=str(tmp_path / "evidence"))

    def run_reality(task):
        runtime_calls.append(task.task_id)
        return reality.reconcile(
            control,
            task.task_id,
            facts=_facts(),
            evidence_refs=("git://source/dispatch123", "runtime://profile/bank-protected"),
        )

    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={"REALITY_RECON": run_reality},
        producer_runner=lambda: producer_calls.append("producer") or "PRODUCER_CALLED",
    )

    initial = dispatcher.next_route()
    assert initial is not None
    assert initial.node == "REALITY_RECON"
    assert initial.owner == "RUNTIME"
    assert initial.action == "RUNTIME_HANDLER"

    result = dispatcher.dispatch_next()
    assert result.task_state == "PASS"
    assert len(runtime_calls) == 1
    assert producer_calls == []

    next_route = dispatcher.next_route()
    assert next_route is not None
    assert next_route.node == "REQUIREMENT_ANALYSIS"
    assert next_route.owner == "PRODUCER_WORKER"
    assert next_route.action == "PRODUCER_WORKER"

    assert dispatcher.dispatch_next() == "PRODUCER_CALLED"
    assert producer_calls == ["producer"]


def test_runtime_owned_ready_task_never_falls_through_to_producer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "1" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-DISPATCH-NO-HANDLER",
        release_id="REL-DISPATCH",
        goal="fail closed when runtime handler missing",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "REL-DISPATCH", "MISSION-DISPATCH-NO-HANDLER")
    producer_calls = []
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={},
        producer_runner=lambda: producer_calls.append("producer"),
    )

    try:
        dispatcher.dispatch_next()
    except Exception as exc:
        assert str(exc) == "RUNTIME_HANDLER_REQUIRED:REALITY_RECON"
    else:
        raise AssertionError("missing Runtime owner must fail closed")
    assert producer_calls == []


def test_dynamic_runtime_repair_routes_to_worker_only_with_governed_gap(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "2" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    mission_id = "MISSION-DYNAMIC-REPAIR"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="REL-DISPATCH",
        goal="route governed dynamic repair",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "REL-DISPATCH", mission_id)
    gap = Gap(
        gap_id="GAP-RUNTIME-REPAIR",
        mission_id=mission_id,
        source_node="EXECUTION",
        category="AUTH_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="RUNTIME",
        description="4A runtime recovery is required",
    )
    task = control.gap_planner.plan(gap, priority=0)
    assert task is not None
    control.refresh_ready()

    dispatcher = MissionStageDispatcher(control, producer_runner=lambda: "WORKER")
    route = dispatcher.next_route()

    assert route is not None
    assert route.task_id == task.task_id
    assert route.node == "RUNTIME"
    assert route.owner == "PRODUCER_WORKER"
    assert route.action == "PRODUCER_WORKER"


def test_dynamic_repair_without_governed_gap_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "3" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    mission_id = "MISSION-DYNAMIC-FORGED"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="REL-DISPATCH",
        goal="reject forged dynamic work",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "REL-DISPATCH", mission_id)
    control.register_task(
        Task(
            task_id="TASK-FORGED-RUNTIME-REPAIR",
            mission_id=mission_id,
            node="RUNTIME",
            task_type="REPAIR",
            objective="forged repair without a governed gap",
            required_capabilities=["runtime_recovery"],
            priority=0,
        )
    )
    dispatcher = MissionStageDispatcher(control, producer_runner=lambda: "WORKER")

    with pytest.raises(MissionStageDispatchError, match="DYNAMIC_TASK_GOVERNED_GAP_REQUIRED"):
        dispatcher.next_route()
