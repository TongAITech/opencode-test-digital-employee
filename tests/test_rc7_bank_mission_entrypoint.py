from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_release.package import (
    ADMIN_ENTRYPOINT,
    ENTRYPOINTS,
    MISSION_ENTRYPOINT,
    REQUIRED_PRODUCT_FILES,
    SHARED_R1_DEFAULT,
)
from rc7_runtime import ClosedLoopControlPlane, Mission, MissionTaskGraphCompiler
from rc7_runtime.bank_mission import BankMissionError, start_or_resume


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40


def test_bank_mission_start_and_resume_are_durable(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", SOURCE_COMMIT)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    v2 = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V2)

    started = start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-MISSION-001",
        release_id="BLOAN-PF-RC7",
        goal="Validate one real bank release through the governed closed loop",
    )
    assert started["status"] == "STARTED"
    assert started["graph_version"] == "v2"
    assert started["task_count"] == len(v2.NODE_ORDER)
    assert started["real_mission_pass"] is False
    assert [item["node"] for item in started["ready_tasks"]] == ["REALITY_RECON"]
    assert started["stage_ownership"]["REALITY_RECON"] == "RUNTIME"
    assert started["stage_ownership"]["REQUIREMENT_SUFFICIENCY"] == "INDEPENDENT_AUTHORITY"
    assert started["stage_ownership"]["FINAL_REPORT"] == "POST_CONVERGENCE"
    assert started["runtime_substages"] == ["PRECONDITIONS", "TEST_DATA_PREPARATION", "ACTUAL_RESULT", "ORACLE"]
    assert started["post_convergence_stages"] == ["FINAL_REPORT"]
    assert Path(started["r1_path"]) == r1.resolve()

    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-MISSION-001",
        release_id="BLOAN-PF-RC7",
        goal="Validate one real bank release through the governed closed loop",
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["graph_version"] == "v2"
    assert resumed["task_count"] == len(v2.NODE_ORDER)
    assert resumed["real_mission_pass"] is False

    truth = TruthRuntime(r1)
    assert len(truth.query("rc7_mission", mission_id="BANK-MISSION-001")) == 1
    assert len(truth.query("rc7_task", mission_id="BANK-MISSION-001")) == len(v2.NODE_ORDER)
    identity = truth.query("rc7_evidence", mission_id="BANK-MISSION-001")
    assert any(row.get("kind") == "RC7_RUNTIME_IDENTITY" for row in identity)
    graph_contract = [row for row in identity if row.get("kind") == "MISSION_GRAPH_CONTRACT"]
    assert len(graph_contract) == 1
    assert graph_contract[0]["source_ref"].endswith("/v2")


def test_pre_graph_contract_v1_mission_resumes_without_upgrade(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", SOURCE_COMMIT)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="LEGACY-V1", release_id="REL-V1", goal="legacy field mission"),
    )
    v1 = MissionTaskGraphCompiler(MissionTaskGraphCompiler.GRAPH_V1)
    v1.install(control, "LEGACY-V1")
    assert not [row for row in truth.query("rc7_evidence", mission_id="LEGACY-V1") if row.get("kind") == "MISSION_GRAPH_CONTRACT"]

    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id="LEGACY-V1",
        release_id="REL-V1",
        goal="legacy field mission",
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["graph_version"] == "v1"
    assert resumed["task_count"] == 5
    assert [item["node"] for item in resumed["ready_tasks"]] == ["REQUIREMENT_ANALYSIS"]


def test_bank_mission_resume_rejects_identity_drift(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", SOURCE_COMMIT)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id="BANK-MISSION-002",
        release_id="REL-A",
        goal="original goal",
    )

    with pytest.raises(BankMissionError, match="MISSION_RELEASE_MISMATCH"):
        start_or_resume(
            r1_path=str(r1),
            mission_id="BANK-MISSION-002",
            release_id="REL-B",
            goal="original goal",
        )

    with pytest.raises(BankMissionError, match="MISSION_GOAL_MISMATCH"):
        start_or_resume(
            r1_path=str(r1),
            mission_id="BANK-MISSION-002",
            release_id="REL-A",
            goal="different goal",
        )


def test_turnkey_mission_and_admin_share_the_same_r1_contract():
    mission_cmd = (REPO_ROOT / "packaging" / "rc7" / "START-RC7-BANK-MISSION.cmd").read_text(encoding="utf-8")
    admin_cmd = (REPO_ROOT / "packaging" / "rc7" / "START-RC7-ADMIN.cmd").read_text(encoding="utf-8")
    mission_sh = (REPO_ROOT / "packaging" / "rc7" / "START-RC7-BANK-MISSION.sh").read_text(encoding="utf-8")
    admin_sh = (REPO_ROOT / "packaging" / "rc7" / "START-RC7-ADMIN.sh").read_text(encoding="utf-8")

    assert "%ROOT%\\runtime-state" in mission_cmd
    assert "%ROOT%\\runtime-state" in admin_cmd
    assert "%PFC_AITEST_STATE_DIR%\\r1\\event-stream.jsonl" in mission_cmd
    assert "%PFC_AITEST_STATE_DIR%\\r1\\event-stream.jsonl" in admin_cmd
    assert '"$ROOT/runtime-state"' in mission_sh
    assert '"$ROOT/runtime-state"' in admin_sh
    assert '"$STATE_ROOT/r1/event-stream.jsonl"' in mission_sh
    assert '"$STATE_ROOT/r1/event-stream.jsonl"' in admin_sh
    assert "state\\rc7-r1.jsonl" not in mission_cmd
    assert "state\\rc7-r1.jsonl" not in admin_cmd
    assert "state/rc7-r1.jsonl" not in mission_sh
    assert "state/rc7-r1.jsonl" not in admin_sh
    assert "workspace-template\\runtime\\python\\python.exe" in mission_cmd
    assert "-m rc7_runtime.bank_mission" in mission_cmd
    assert "-m rc7_admin" in admin_cmd


def test_turnkey_package_contract_requires_mission_and_full_admin_platform():
    assert MISSION_ENTRYPOINT in ENTRYPOINTS
    assert ADMIN_ENTRYPOINT in ENTRYPOINTS
    assert SHARED_R1_DEFAULT == "runtime-state/r1/event-stream.jsonl"
    required = set(REQUIRED_PRODUCT_FILES)
    assert "rc7_runtime/bank_mission.py" in required
    assert "rc7_admin/__main__.py" in required
    assert "rc7_admin/server.py" in required
    assert "rc7_admin/projection.py" in required
    assert "rc7_admin/derived.py" in required
    assert "rc7_admin/static/index.html" in required
