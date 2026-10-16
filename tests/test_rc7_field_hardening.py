from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime import truth as rc6_truth
from rc7_release import dsh_plugins
from rc7_release.dsh import write_patch
from rc7_release.final_unified_qualification import _decode_output
from rc7_release import mcp_server as rc7_mcp


def _seed_plugin_payload(home: Path) -> None:
    vendor = home / "workspace-template" / "runtime" / "dsh-plugins"
    for package in dsh_plugins.REQUIRED:
        target = dsh_plugins.package_path(vendor, package)
        target.mkdir(parents=True, exist_ok=True)
        (target / "package.json").write_text(
            json.dumps({"name": package, "version": "0.0.0-field-test"}),
            encoding="utf-8",
        )


def test_rc7_mcp_import_installs_truth_overlay_and_reports_rc7_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PFC_AITEST_HOME", str(tmp_path))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "runtime-state"))

    assert "RC7_CONTROL_EVENT_UPSERTED" in rc6_truth.EVENT_TYPES
    assert "rc7_control_event" in rc6_truth.BUCKETS

    response = rc7_mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "runtime_status", "arguments": {}},
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["server"] == "pfc-aitest-rc7"
    assert payload["rc7_truth_overlay"] is True
    assert payload["canonical_r1_path"].endswith("runtime-state/r1/event-stream.jsonl") or payload[
        "canonical_r1_path"
    ].endswith("runtime-state\\r1\\event-stream.jsonl")


def test_bank_web_profile_is_immutable_even_with_explicit_mutation_flag(tmp_path: Path) -> None:
    _seed_plugin_payload(tmp_path)
    result = dsh_plugins.install(
        tmp_path,
        "web",
        dry_run=False,
        allow_profile_mutation=True,
    )
    assert result["status"] == "FAIL"
    assert result["reason"] == "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN"


def test_normal_payload_check_is_read_only_for_bank_web_profile(tmp_path: Path) -> None:
    _seed_plugin_payload(tmp_path)
    result = dsh_plugins.install(tmp_path, "web", dry_run=True)
    assert result["status"] == "PASS"
    assert result["mode"] == "PAYLOAD_ONLY_NO_PROFILE_MUTATION"
    assert result["protected_profile"] is True


def test_mutable_isolated_profile_uses_file_specs_not_link_specs(tmp_path: Path, monkeypatch) -> None:
    _seed_plugin_payload(tmp_path)
    monkeypatch.setattr(dsh_plugins.shutil, "which", lambda *args, **kwargs: "dsh")
    calls = []

    def fake_run(cmd, env):
        calls.append(list(cmd))
        if cmd[-1] == "--version":
            return 0, "0.0-test"
        return 0, "ok"

    monkeypatch.setattr(dsh_plugins, "run", fake_run)
    result = dsh_plugins.install(
        tmp_path,
        "rc7-qualification",
        allow_profile_mutation=True,
    )
    assert result["status"] == "PASS"
    add_calls = [call for call in calls if "add" in call]
    assert len(add_calls) == len(dsh_plugins.REQUIRED)
    assert all(call[-1].startswith("file:") for call in add_calls)
    assert all(not call[-1].startswith("link:") for call in add_calls)


def test_mcp_patch_always_binds_canonical_state_root(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "RC7 Home With Spaces"
    home.mkdir()
    state_root = home / "runtime-state-custom"
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state_root))
    output = home / "state" / "rc7-dsh.patch.yml"
    write_patch(output, home, "python.exe")
    text = output.read_text(encoding="utf-8")
    assert "PFC_AITEST_STATE_DIR" in text
    assert str(state_root).replace("'", "''") in text
    assert "pfc_aitest_rc7" in text


def test_probe_decoder_never_crashes_on_mixed_windows_bytes() -> None:
    raw = b"prefix\x94\xffsuffix"
    decoded = _decode_output(raw)
    assert isinstance(decoded, str)
    assert "prefix" in decoded
    assert "suffix" in decoded


def test_launchers_use_runtime_state_r1_and_never_install_into_web_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    cmd = (root / "packaging" / "rc7" / "AITEST.cmd").read_text(encoding="utf-8")
    sh = (root / "packaging" / "rc7" / "AITEST.sh").read_text(encoding="utf-8")
    admin_cmd = (root / "packaging" / "rc7" / "START-RC7-ADMIN.cmd").read_text(encoding="utf-8")
    admin_sh = (root / "packaging" / "rc7" / "START-RC7-ADMIN.sh").read_text(encoding="utf-8")

    assert "dsh_plugins" in cmd and "--dry-run" in cmd
    assert "dsh_plugins" in sh and "--dry-run" in sh
    assert "plugin --profile web add" not in cmd.lower()
    assert "plugin --profile web add" not in sh.lower()
    assert "runtime-state" in admin_cmd
    assert "event-stream.jsonl" in admin_cmd
    assert "runtime-state" in admin_sh
    assert "event-stream.jsonl" in admin_sh
    assert "state\\rc7-r1.jsonl" not in admin_cmd
    assert "state/rc7-r1.jsonl" not in admin_sh
