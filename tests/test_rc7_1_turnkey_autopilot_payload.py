from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rc7_release import package as package_builder


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_built_turnkey_contains_importable_rc71_autopilot_runtime(tmp_path: Path, monkeypatch) -> None:
    # The delivery contract under test is source/launcher/manifest/checksum
    # inclusion.  Do not copy the CI host's entire Windows Python installation
    # into this unit test; the actual RC7.1 Turnkey workflow tests that separately.
    monkeypatch.setattr(package_builder, "_bundle_current_windows_python", lambda _root: False)
    monkeypatch.delenv(package_builder.BUILD_CODEGRAPH_BIN_ENV, raising=False)
    monkeypatch.delenv(package_builder.BUILD_BROWSER_DIR_ENV, raising=False)

    package_root = package_builder.build_package(
        REPO_ROOT,
        tmp_path / "dist",
        "a" * 40,
        make_zip=False,
    )
    assert package_builder.verify_package(package_root)["status"] == "PASS"

    output = tmp_path / "rc71-autopilot-delivery.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "rc7_release.rc71_autopilot_delivery_gate",
            "--package-root",
            str(package_root),
            "--output",
            str(output),
            "--require-pass",
        ],
        cwd=str(package_root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["manifest_coverage"] == "PASS"
    assert payload["checksum_coverage"] == "PASS"
    assert payload["autostart_entry"] == "PASS"
    assert payload["manual_continue_required"] is False
    assert len(payload["package_local_imports"]) == 5

    manifest = json.loads((package_root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    manifest_paths = {row["path"] for row in manifest["files"]}
    for relative in (
        "rc7_runtime/bank_mission_start.py",
        "rc7_runtime/bank_mission_autopilot.py",
        "rc7_runtime/bank_execution_autopilot.py",
        "rc7_runtime/active_task_supervisor.py",
        "rc7_runtime/execution_capability.py",
        "packaging/rc7/START-RC7-BANK-MISSION.cmd",
        "packaging/rc7/START-RC7-BANK-MISSION.sh",
    ):
        assert relative in manifest_paths
        assert (package_root / relative).is_file()
