from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shell_bank_mission_starts_graph_v2_without_mission_env(tmp_path: Path) -> None:
    script = REPO_ROOT / "packaging" / "rc7" / "START-RC7-BANK-MISSION.sh"
    patch = tmp_path / "rc7-dsh.patch.yml"
    patch.write_text("patch: true\n", encoding="utf-8")
    env = dict(os.environ)
    for key in (
        "PFC_RC7_MISSION_ID",
        "PFC_RC7_RELEASE_ID",
        "PFC_RC7_MISSION_GOAL",
        "PFC_RC7_R1_PATH",
        "PFC_RC7_BANK_TARGET_ID",
    ):
        env.pop(key, None)
    env["PFC_PYTHON_BIN"] = sys.executable
    env["PFC_AITEST_STATE_DIR"] = str(tmp_path / "state")
    env["PFC_RC7_SOURCE_COMMIT"] = "a" * 40
    env["PFC_RC7_DSH_PROFILE"] = "rc7-bank"
    env["PFC_RC7_DSH_BIN"] = sys.executable
    env["PFC_RC7_DSH_PATCH"] = str(patch)
    env["PFC_RC7_TARGET_ID"] = "BANK-TARGET-TURNKEY"

    proc = subprocess.run(
        [
            "sh",
            str(script),
            "--mission-id",
            "MISSION-TURNKEY-CLI",
            "--release-id",
            "REL-TURNKEY",
            "--goal",
            "Validate one SST without pre-setting Mission environment variables",
            "--max-steps",
            "1",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    # One autonomous step completes Runtime-owned Reality Recon and then stops
    # because this test deliberately sets max-steps=1.  The important contract
    # is that the launcher did not stop at bootstrap and require a manual
    # follow-up "continue".
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout.splitlines()[-1])
    assert payload["bootstrap_action"] == "STARTED"
    assert payload["status"] == "BUDGET_EXHAUSTED"
    assert payload["graph_version"] == "v2"
    assert payload["mission_id"] == "MISSION-TURNKEY-CLI"
    assert payload["release_id"] == "REL-TURNKEY"
    assert payload["target_id"] == "BANK-TARGET-TURNKEY"
    assert payload["steps"] == 1
    assert payload["manual_continue_required"] is False
    assert (tmp_path / "state" / "r1" / "event-stream.jsonl").is_file()


def test_windows_bank_mission_entrypoint_exposes_same_direct_cli_mode() -> None:
    cmd = (REPO_ROOT / "packaging" / "rc7" / "START-RC7-BANK-MISSION.cmd").read_text(encoding="utf-8")
    assert "goto ENV_MODE" in cmd
    assert '-m rc7_runtime.bank_mission_start --r1 "%PFC_RC7_R1_PATH%" --package-root "%ROOT%" %*' in cmd
    assert "PFC_RC7_MISSION_ID" in cmd
    assert "PFC_RC7_RELEASE_ID" in cmd
    assert "PFC_RC7_MISSION_GOAL" in cmd
