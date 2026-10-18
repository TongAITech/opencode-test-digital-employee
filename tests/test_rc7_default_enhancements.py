from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_release import dsh, dsh_plugins
from rc7_release.plugin_payload import REQUIRED_PLUGIN_NAMES, package_path


def _write_package(vendor: Path, name: str, main: str = "index.js") -> Path:
    root = package_path(vendor, name)
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps({"name": name, "version": "test", "main": main}),
        encoding="utf-8",
    )
    entry = root / main
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("export function apply() {}\n", encoding="utf-8")
    return root


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "rc7"
    vendor = home / "workspace-template" / "runtime" / "dsh-plugins"
    for name in REQUIRED_PLUGIN_NAMES:
        _write_package(vendor, name)
    _write_package(vendor, "dsh-vision-router", "lib/public-entry.js")
    _write_package(vendor, "dsh-memento", "index.mjs")
    _write_package(vendor, "@perrylink/dsh-plugin-doctor")
    return home


def test_default_enhancements_are_bundled_and_runtime_enabled(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    result = dsh_plugins.install(home, "web", dry_run=True)

    assert result["status"] == "PASS"
    assert result["protected_profile"] is True
    assert result["default_enhancements"] == "RUNTIME_PATCH_ENABLED"
    assert result["default_runtime_ready"] is True
    assert result["default_runtime_missing"] == []
    assert result["default_runtime_enhancements"] == ["dsh-vision-router", "dsh-memento"]
    assert result["plugins"]["dsh-vision-router"]["tier"] == "P1_DEFAULT_RUNTIME"
    assert result["plugins"]["dsh-memento"]["tier"] == "P1_DEFAULT_RUNTIME"
    assert result["remote_vision_policy"] == "LOCAL_ONLY_PUBLIC_REMOTE_FORBIDDEN"
    assert result["memento_truth_policy"] == "NON_AUTHORITATIVE_R1_EVENT_STREAM_ONLY"


def test_default_enhancement_missing_is_reported_but_strictness_stays_at_startup_gate(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    vision = package_path(home / "workspace-template" / "runtime" / "dsh-plugins", "dsh-vision-router")
    for item in sorted(vision.rglob("*"), reverse=True):
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            item.rmdir()
    vision.rmdir()

    result = dsh_plugins.install(home, "web", dry_run=True)
    assert result["status"] == "PASS"
    assert result["default_runtime_ready"] is False
    assert "dsh-vision-router" in result["default_runtime_missing"]
    assert result["default_enhancements"] == "RUNTIME_PATCH_PAYLOAD_INCOMPLETE"


def test_runtime_patch_enables_vision_local_only_and_memento_nontruth(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    patch = tmp_path / "state" / "rc7-dsh.patch.yml"
    dsh.write_patch(patch, home, "python.exe", require_default_enhancements=True)
    text = patch.read_text(encoding="utf-8")
    policy = (patch.parent / dsh.TOOL_POLICY_PLUGIN_NAME).read_text(encoding="utf-8")

    assert "id: vision-router" in text
    assert "dsh-vision-router" in text
    assert "localOnlyVision: true" in text
    assert "freeFallback: false" in text
    assert "desktopScreenshot: false" in text
    assert "id: memento" in text
    assert "dsh-memento" in text
    assert "writePolicy: ask" in text
    assert "language: zh" in text
    assert "runtime-state" in text and "memento" in text and "memory.db" in text
    assert "runtime-state/r1/event-stream.jsonl" in policy
    assert "Memento/memory is non-authoritative" in policy
    assert "RC7_DSH_TOOL_NOT_AUTHORIZED" in policy


def test_runtime_patch_strict_mode_rejects_missing_payload(tmp_path: Path) -> None:
    home = tmp_path / "empty"
    with pytest.raises(RuntimeError, match="RC7_DEFAULT_ENHANCEMENT_MISSING"):
        dsh.write_patch(
            tmp_path / "state" / "patch.yml",
            home,
            "python.exe",
            require_default_enhancements=True,
        )


def test_protected_web_profile_still_cannot_be_mutated(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    result = dsh_plugins.install(home, "web", dry_run=False, allow_profile_mutation=True)
    assert result["status"] == "FAIL"
    assert result["reason"] == "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN"
    assert result["protected_profile_mutation"] == "FORBIDDEN"


def test_windows_turnkey_uses_clone_and_strict_runtime_patch() -> None:
    root = Path(__file__).resolve().parents[1]
    cmd = (root / "packaging" / "rc7" / "AITEST.cmd").read_text(encoding="utf-8")
    assert "PFC_RC7_DSH_BASE_PROFILE=web" in cmd
    assert "PFC_RC7_DSH_PROFILE=rc7-bank" in cmd
    assert "rc7_release.dsh_runtime_profile" in cmd
    assert "--require-default-enhancements" in cmd
    assert "LOCAL-ONLY" in cmd
    assert "R1 NON-AUTHORITATIVE" in cmd
