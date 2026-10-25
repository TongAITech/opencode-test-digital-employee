from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission_start import BankMissionStartError, _target_id, main


def _package(tmp_path: Path):
    root = tmp_path / "package"
    (root / "runtime-state" / "r1").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "SOURCE_COMMIT").write_text("0123456789abcdef", encoding="utf-8")
    (root / "state" / "rc7-dsh-runtime-profile.json").write_text(
        json.dumps({"runtime_profile": "rc7-bank"}), encoding="utf-8"
    )
    (root / "state" / "rc7-dsh.patch.yml").write_text("patch: true\n", encoding="utf-8")
    dsh = root / "dsh"
    dsh.write_text("stub", encoding="utf-8")
    requirement = root / "requirement.md"
    requirement.write_text("bank requirement", encoding="utf-8")
    return root, dsh, requirement


def test_legacy_bank_target_alias_is_supported_but_conflict_never_guessed(monkeypatch):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.setenv("PFC_RC7_BANK_TARGET_ID", "BANK-TARGET-1")
    assert _target_id(None) == "BANK-TARGET-1"

    monkeypatch.setenv("PFC_RC7_TARGET_ID", "BANK-TARGET-2")
    with pytest.raises(BankMissionStartError, match="AUTOPILOT_TARGET_ID_ENV_CONFLICT"):
        _target_id(None)


def test_bank_mission_start_preserves_bootstrap_input_then_immediately_drives_autopilot(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_BANK_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_AUTONOMOUS_RUN_ID", raising=False)
    root, dsh, requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    requirement_ref = "file://" + str(requirement)

    rc = main(
        [
            "--r1",
            str(r1),
            "--package-root",
            str(root),
            "--mission-id",
            "M-START",
            "--release-id",
            "R-START",
            "--goal",
            "prove turnkey autostart",
            "--run-id",
            "RUN-START",
            "--target-id",
            "BANK-TARGET-1",
            "--dsh-bin",
            str(dsh),
            "--input",
            "REQUIREMENT_ANALYSIS=" + requirement_ref,
            "--max-steps",
            "1",
        ]
    )
    # One step is deliberately insufficient for the whole Mission; the point is
    # proving the entry actually drove Reality Recon instead of stopping at
    # bootstrap. BUDGET_EXHAUSTED therefore returns 1 by contract.
    assert rc == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["bootstrap_action"] == "STARTED"
    assert payload["status"] == "BUDGET_EXHAUSTED"
    assert payload["steps"] == 1
    assert payload["manual_continue_required"] is False
    assert payload["target_id"] == "BANK-TARGET-1"
    assert payload["run_id"] == "RUN-START"

    truth = TruthRuntime(r1)
    reality = [
        row for row in truth.query("rc7_task", mission_id="M-START")
        if row.get("node") == "REALITY_RECON"
    ]
    assert len(reality) == 1
    assert reality[0]["state"] == "PASS"
    requirement_task = [
        row for row in truth.query("rc7_task", mission_id="M-START")
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ][0]
    assert requirement_task["state"] == "READY"
    assert requirement_ref in list(requirement_task.get("input_artifact_refs") or [])


def test_bank_mission_start_fails_closed_when_run_id_is_missing(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_BANK_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_AUTONOMOUS_RUN_ID", raising=False)
    root, dsh, _ = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"

    rc = main(
        [
            "--r1",
            str(r1),
            "--package-root",
            str(root),
            "--mission-id",
            "M-NO-RUN",
            "--release-id",
            "R-NO-RUN",
            "--goal",
            "prove autonomous run identity is never guessed",
            "--target-id",
            "BANK-TARGET-1",
            "--dsh-bin",
            str(dsh),
            "--max-steps",
            "1",
        ]
    )
    assert rc == 2
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["status"] == "FIELD_REQUIRED"
    assert payload["reason"] == "AUTOPILOT_RUN_ID_REQUIRED_NO_GUESSING"


def test_packaged_bank_mission_launchers_use_autostart_not_bootstrap_only():
    root = Path(__file__).resolve().parents[1]
    cmd = (root / "packaging" / "rc7" / "START-RC7-BANK-MISSION.cmd").read_text(
        encoding="utf-8"
    )
    sh = (root / "packaging" / "rc7" / "START-RC7-BANK-MISSION.sh").read_text(
        encoding="utf-8"
    )
    for text in (cmd, sh):
        assert "-m rc7_runtime.bank_mission_start" in text
        assert "--package-root" in text
        assert "-m rc7_runtime.bank_mission --r1" not in text
