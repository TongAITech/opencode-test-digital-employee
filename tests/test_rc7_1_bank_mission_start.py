from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission_autopilot import discover_config
from rc7_runtime.bank_mission_start import (
    BankMissionStartError,
    _case_provider_config,
    _target_id,
    main,
)


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


def _provider_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"providers": {}}, sort_keys=True), encoding="utf-8")
    return path


def test_legacy_bank_target_alias_is_supported_but_conflict_never_guessed(monkeypatch):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.setenv("PFC_RC7_BANK_TARGET_ID", "BANK-TARGET-1")
    assert _target_id(None) == "BANK-TARGET-1"

    monkeypatch.setenv("PFC_RC7_TARGET_ID", "BANK-TARGET-2")
    with pytest.raises(BankMissionStartError, match="AUTOPILOT_TARGET_ID_ENV_CONFLICT"):
        _target_id(None)


def test_case_provider_config_auto_binds_only_canonical_real_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
    root, _dsh, _requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    canonical = _provider_config(root / "state" / "bank-field-providers.json")

    selected = _case_provider_config(
        r1_path=str(r1),
        package_root=str(root),
        cli_value=None,
    )

    assert selected == str(canonical.resolve())
    assert os.environ["PFC_RC7_CASE_PROVIDER_CONFIG"] == str(canonical.resolve())


def test_case_provider_config_missing_canonical_stays_unbound(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
    root, _dsh, _requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"

    assert _case_provider_config(
        r1_path=str(r1),
        package_root=str(root),
        cli_value=None,
    ) is None
    assert "PFC_RC7_CASE_PROVIDER_CONFIG" not in os.environ


def test_case_provider_config_cli_env_conflict_is_fail_closed(tmp_path: Path, monkeypatch):
    root, _dsh, _requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    cli_config = _provider_config(root / "state" / "cli-providers.json")
    env_config = _provider_config(root / "state" / "env-providers.json")
    monkeypatch.setenv("PFC_RC7_CASE_PROVIDER_CONFIG", str(env_config))

    with pytest.raises(BankMissionStartError, match="AUTOPILOT_CASE_PROVIDER_CONFIG_CLI_ENV_CONFLICT"):
        _case_provider_config(
            r1_path=str(r1),
            package_root=str(root),
            cli_value=str(cli_config),
        )


def test_case_provider_config_missing_explicit_path_fails_before_bootstrap(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
    root, dsh, _requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    missing = root / "state" / "missing-providers.json"

    rc = main(
        [
            "--r1", str(r1),
            "--package-root", str(root),
            "--mission-id", "M-PROVIDER-MISSING",
            "--release-id", "R-PROVIDER-MISSING",
            "--goal", "prove provider fail closed before bootstrap",
            "--target-id", "BANK-TARGET-1",
            "--dsh-bin", str(dsh),
            "--case-provider-config", str(missing),
        ]
    )

    assert rc == 2
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["status"] == "FIELD_REQUIRED"
    assert "AUTOPILOT_CASE_PROVIDER_CONFIG_NOT_FOUND" in payload["reason"]
    assert not r1.exists()


def test_case_provider_example_is_never_runtime_authority(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
    root, _dsh, _requirement = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    example = _provider_config(root / "packaging" / "rc7" / "bank-field-providers.example.json")

    with pytest.raises(BankMissionStartError, match="AUTOPILOT_CASE_PROVIDER_EXAMPLE_FORBIDDEN"):
        _case_provider_config(
            r1_path=str(r1),
            package_root=str(root),
            cli_value=str(example),
        )


def test_bank_mission_start_preserves_bootstrap_input_then_immediately_drives_autopilot(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_BANK_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_AUTONOMOUS_RUN_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
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


def test_bank_mission_start_derives_stable_runtime_run_id_when_missing(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("PFC_RC7_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_BANK_TARGET_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_AUTONOMOUS_RUN_ID", raising=False)
    monkeypatch.delenv("PFC_RC7_CASE_PROVIDER_CONFIG", raising=False)
    root, dsh, _ = _package(tmp_path)
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"

    argv = [
        "--r1",
        str(r1),
        "--package-root",
        str(root),
        "--mission-id",
        "M-NO-RUN",
        "--release-id",
        "R-NO-RUN",
        "--goal",
        "prove runtime-owned autonomous run identity",
        "--target-id",
        "BANK-TARGET-1",
        "--dsh-bin",
        str(dsh),
        "--max-steps",
        "1",
    ]
    rc = main(argv)
    assert rc == 1
    first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert first["status"] == "BUDGET_EXHAUSTED"
    assert first["run_id"].startswith("RUN-RC71-")

    # Recreate the process-local Autopilot configuration without advancing the
    # durable Mission. Runtime-owned identity must resolve to the same run across
    # session/process recreation, while Mission execution remains a separate concern.
    resumed = discover_config(
        r1_path=str(r1),
        mission_id="M-NO-RUN",
        release_id="R-NO-RUN",
        goal="prove runtime-owned autonomous run identity",
        package_root=str(root),
        dsh_bin=str(dsh),
        target_id="BANK-TARGET-1",
    )
    assert resumed.run_id == first["run_id"]


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
