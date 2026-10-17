from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from rc7_runtime.mission_convergence_conformance import (
    MissionConvergenceConformanceChecker,
    canonical_execution_task_id,
)
from rc7_runtime.models import Task
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


COMMIT = "d" * 40
RELEASE = "REL-CONVERGENCE"


def _start(tmp_path: Path, monkeypatch, *, mission_id: str, graph_version: str):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", COMMIT)
    r1 = tmp_path / mission_id / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=RELEASE,
        goal="qualify convergence authority",
        graph_version=graph_version,
    )
    return r1


def test_new_graph_v2_convergence_authority_is_enforced_and_rejects_missing_runtime_truth(tmp_path, monkeypatch):
    mission_id = "MISSION-CONVERGENCE-V2"
    r1 = _start(tmp_path, monkeypatch, mission_id=mission_id, graph_version="v2")
    truth = TruthRuntime(r1)

    result = MissionConvergenceConformanceChecker(truth).check(mission_id)

    assert result.enforced is True
    assert result.status == "FAIL"
    assert result.canonical_execution_task_id
    assert result.execution_recovery_conformance["status"] == "FAIL"
    assert result.actual_result_oracle_conformance["status"] == "FAIL"
    assert result.defect_review_conformance["status"] == "PASS"
    assert result.defect_review_conformance["triggered"] is False
    assert any(
        reason.startswith("EXECUTION_RECOVERY_CONFORMANCE_FAILED:")
        for reason in result.violations
    )
    assert any(
        reason.startswith("ACTUAL_RESULT_ORACLE_CONFORMANCE_FAILED:")
        for reason in result.violations
    )


def test_canonical_execution_resolution_ignores_governed_dynamic_execution_tasks(tmp_path, monkeypatch):
    mission_id = "MISSION-CONVERGENCE-DYNAMIC"
    r1 = _start(tmp_path, monkeypatch, mission_id=mission_id, graph_version="v2")
    install_rc7_truth_overlay()
    truth = TruthRuntime(r1)
    canonical = canonical_execution_task_id(truth, mission_id)

    for task_type in (
        "REPAIR",
        "DEFECT_REPRODUCTION",
        "DEFECT_FIX_VERIFICATION",
        "DEFECT_IMPACT_REGRESSION",
    ):
        task = Task(
            task_id="TASK-DYNAMIC-%s" % task_type,
            mission_id=mission_id,
            node="EXECUTION",
            task_type=task_type,
            objective="governed dynamic execution",
        )
        append_entity(truth, task, release_id=RELEASE)

    assert canonical_execution_task_id(truth, mission_id) == canonical

    control = ClosedLoopControlPlane(truth, RELEASE, mission_id)
    for task_type in (
        "REPAIR",
        "DEFECT_REPRODUCTION",
        "DEFECT_FIX_VERIFICATION",
        "DEFECT_IMPACT_REGRESSION",
    ):
        dynamic = control.scheduler.task("TASK-DYNAMIC-%s" % task_type)
        # The top-level recovery contract is intentionally not applicable to
        # these tasks. Dedicated recovery/defect authorities own their proof.
        control._require_execution_recovery_pass_ready(dynamic)

    rogue = Task(
        task_id="TASK-DYNAMIC-ROGUE",
        mission_id=mission_id,
        node="EXECUTION",
        task_type="UNDECLARED_EXECUTION_PATH",
        objective="must fail closed",
    )
    with pytest.raises(
        ClosedLoopControlError,
        match="NONCANONICAL_EXECUTION_TASK_NOT_COVERED_BY_RUNTIME_CONTRACT",
    ):
        control._require_execution_recovery_pass_ready(rogue)


def test_legacy_v1_convergence_authority_remains_not_enforced(tmp_path, monkeypatch):
    mission_id = "MISSION-CONVERGENCE-V1"
    r1 = _start(tmp_path, monkeypatch, mission_id=mission_id, graph_version="v1")
    result = MissionConvergenceConformanceChecker(TruthRuntime(r1)).check(mission_id)

    assert result.status == "PASS"
    assert result.enforced is False
    assert result.canonical_execution_task_id == ""
    assert result.violations == ()

    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=RELEASE,
        goal="qualify convergence authority",
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["graph_version"] == "v1"
