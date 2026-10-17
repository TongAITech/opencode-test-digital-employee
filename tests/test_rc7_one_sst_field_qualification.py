from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_release.one_sst_field_qualification import (
    build_status,
    finalize,
    start_one_sst,
)


MISSION = "MISSION-ONE-SST-FIELD"
RELEASE = "BLOAN-PF-FIELD"
SST = "STB-FIELD-0001"
COMMIT = "a" * 40
GOAL = "Qualify one fixed Bank SST field identity"


def _root(tmp_path: Path) -> Path:
    (tmp_path / "SOURCE_COMMIT").write_text(COMMIT + "\n", encoding="utf-8")
    return tmp_path


def test_start_one_sst_binds_requirement_input_and_resume_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)

    started = start_one_sst(
        package_root=str(root),
        mission_id=MISSION,
        release_id=RELEASE,
        sst_ids=[SST],
        goal=GOAL,
    )
    assert started["status"] == "STARTED"
    assert started["graph_version"] == "v2"
    assert started["sst_ids"] == [SST]
    assert started["bank_field_pass"] is False
    assert started["real_mission_pass"] is False

    truth = TruthRuntime(Path(started["r1_path"]))
    requirement = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS" and row.get("task_type") != "EVALUATE"
    ]
    assert len(requirement) == 1
    assert "sst://" + SST in requirement[0]["input_artifact_refs"]

    resumed = start_one_sst(
        package_root=str(root),
        mission_id=MISSION,
        release_id=RELEASE,
        sst_ids=[SST],
        goal=GOAL,
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["sst_ids"] == [SST]

    # Hold the Mission goal constant so this assertion proves the SST input
    # identity itself cannot be silently retargeted on resume.
    with pytest.raises(Exception, match="MISSION_GRAPH_INPUT_MISMATCH"):
        start_one_sst(
            package_root=str(root),
            mission_id=MISSION,
            release_id=RELEASE,
            sst_ids=["STB-FIELD-DIFFERENT"],
            goal=GOAL,
        )


def test_one_sst_rejects_multiple_distinct_ssts_but_duplicate_same_id_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)

    duplicate = start_one_sst(
        package_root=str(root),
        mission_id=MISSION,
        release_id=RELEASE,
        sst_ids=[SST, "sst://" + SST, SST],
        goal=GOAL,
    )
    assert duplicate["sst_ids"] == [SST]

    with pytest.raises(Exception, match="EXACTLY_ONE_SST_REQUIRED"):
        start_one_sst(
            package_root=str(root),
            mission_id="MISSION-ONE-SST-INVALID",
            release_id=RELEASE,
            sst_ids=[SST, "STB-FIELD-0002"],
            goal=GOAL,
        )


def test_fresh_one_sst_status_is_in_progress_and_never_claims_bank_final(tmp_path: Path) -> None:
    root = _root(tmp_path)
    start_one_sst(
        package_root=str(root),
        mission_id=MISSION,
        release_id=RELEASE,
        sst_ids=[SST],
    )

    status = build_status(
        package_root=str(root),
        mission_id=MISSION,
        source_commit=COMMIT,
    )

    assert status["status"] == "IN_PROGRESS"
    assert status["stage"] == "MISSION_IN_PROGRESS"
    assert status["next_action"] == "CONTINUE_DSH_RUNTIME_FROM_SAME_R1"
    assert status["sst_ids"] == [SST]
    assert status["bank_field_pass"] is False
    assert status["real_mission_pass"] is False
    assert status["strict_qualification_status"] == "HOLD"
    assert status["strict_blocking_reasons"]
    assert [row["node"] for row in status["ready_tasks"]] == ["REALITY_RECON"]
    assert status["task_state_counts"]["READY"] == 1
    assert status["case_coverage"]["enforced"] is True
    assert status["case_coverage"]["status"] != "PASS"


def test_finalize_fails_closed_before_real_mission_convergence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    start_one_sst(
        package_root=str(root),
        mission_id=MISSION,
        release_id=RELEASE,
        sst_ids=[SST],
    )

    payload, rc = finalize(
        package_root=str(root),
        mission_id=MISSION,
        source_commit=COMMIT,
    )

    assert rc == 2
    assert payload["stage"] == "MISSION_IN_PROGRESS"
    assert payload["bank_field_pass"] is False
    assert payload["real_mission_pass"] is False
    assert "bank_final_exit_code" not in payload


def test_one_sst_packaging_entrypoints_are_thin_and_portable() -> None:
    root = Path(__file__).resolve().parents[1]
    sh_path = root / "packaging" / "rc7" / "FIELD-QUALIFY-ONE-SST.sh"
    cmd_path = root / "packaging" / "rc7" / "FIELD-QUALIFY-ONE-SST.cmd"
    sh = sh_path.read_text(encoding="utf-8")
    cmd = cmd_path.read_text(encoding="utf-8")

    assert "rc7_release.one_sst_field_qualification" in sh
    assert "rc7_release.one_sst_field_qualification" in cmd
    assert "workspace-template/runtime/python/python.exe" in sh
    assert "workspace-template\\runtime\\python\\python.exe" in cmd
    assert "SOURCE_COMMIT" in sh
    assert "SOURCE_COMMIT" in cmd

    bash = shutil.which("bash")
    if bash:
        completed = subprocess.run([bash, "-n", str(sh_path)], check=False)
        assert completed.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd qualification")
def test_windows_cmd_entrypoint_executes_bound_python_cli() -> None:
    root = Path(__file__).resolve().parents[1]
    cmd_path = root / "packaging" / "rc7" / "FIELD-QUALIFY-ONE-SST.cmd"
    assert cmd_path.is_file()
    env = dict(os.environ)
    env["PFC_PYTHON_BIN"] = sys.executable
    command = subprocess.list2cmdline([str(cmd_path), "--help"])
    proc = subprocess.run(
        command,
        cwd=str(root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "start-sst" in proc.stdout
    assert "finalize" in proc.stdout
