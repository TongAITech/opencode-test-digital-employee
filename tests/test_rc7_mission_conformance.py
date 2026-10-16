from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_conformance import MissionConformanceChecker
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import Mission, Task


def test_new_v2_bank_mission_conforms_before_domain_execution(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "c" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    started = start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-CONFORMANCE-V2",
        release_id="REL-V2",
        goal="validate graph v2 durable contract",
    )
    result = MissionConformanceChecker(TruthRuntime(r1)).check("MISSION-CONFORMANCE-V2")

    assert started["graph_version"] == "v2"
    assert result.status == "PASS"
    assert result.graph_version == "v2"
    assert result.mission_state == "RUNNING"
    assert result.violations == ()
    assert len(result.canonical_task_ids) == 6


def test_legacy_v1_without_graph_evidence_conforms_and_is_not_upgraded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "d" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="MISSION-CONFORMANCE-V1", release_id="REL-V1", goal="legacy mission"),
    )
    MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V1).install(control, "MISSION-CONFORMANCE-V1")

    result = MissionConformanceChecker(truth).check("MISSION-CONFORMANCE-V1")
    assert result.status == "PASS"
    assert result.graph_version == "v1"
    assert len(result.canonical_task_ids) == 5


def test_v2_conformance_rejects_flattened_preparation_or_report_tasks(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "e" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-CONFORMANCE-BAD",
        release_id="REL-BAD",
        goal="reject forbidden flattened stages",
    )
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, "REL-BAD", "MISSION-CONFORMANCE-BAD")
    control.register_task(
        Task(
            task_id="TASK-FORBIDDEN-PREP",
            mission_id="MISSION-CONFORMANCE-BAD",
            node="PRECONDITION_DATA",
            task_type="PRODUCE",
            objective="incorrectly flattened preparation",
        )
    )
    control.register_task(
        Task(
            task_id="TASK-FORBIDDEN-REPORT",
            mission_id="MISSION-CONFORMANCE-BAD",
            node="REPORT",
            task_type="PRODUCE",
            objective="incorrect pre-convergence report",
        )
    )

    result = MissionConformanceChecker(truth).check("MISSION-CONFORMANCE-BAD")
    assert result.status == "FAIL"
    assert any(item.startswith("V2_FORBIDDEN_TOP_LEVEL_TASK:") for item in result.violations)
