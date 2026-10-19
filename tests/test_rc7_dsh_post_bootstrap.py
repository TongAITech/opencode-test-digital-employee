from __future__ import annotations

import json
from pathlib import Path

from rc7_release import dsh_plugins, dsh_post_bootstrap


def _package_dir(profile: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return profile / "node_modules" / scope / name
    return profile / "node_modules" / package


def _runtime_profile(root: Path, *, ready: bool) -> Path:
    profile = root / "profiles" / "rc7-bank"
    profile.mkdir(parents=True)
    (profile / "package.json").write_text(json.dumps({"name": "rc7-bank"}), encoding="utf-8")
    if ready:
        for package in dsh_plugins.REQUIRED:
            target = _package_dir(profile, package)
            target.mkdir(parents=True, exist_ok=True)
            (target / "package.json").write_text(json.dumps({"name": package, "version": "test"}), encoding="utf-8")
    return profile


def test_ready_clone_never_calls_package_manager(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    _runtime_profile(dsh_home, ready=True)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))

    def forbidden(*args, **kwargs):
        raise AssertionError("package manager should not run for ready clone")

    monkeypatch.setattr(dsh_post_bootstrap.dsh_plugins, "install", forbidden)
    result = dsh_post_bootstrap.probe_or_repair(tmp_path)
    assert result["status"] == "PASS"
    assert result["capability_state"] == "READY_FROM_CLONE"
    assert result["persistent_install_attempted"] is False


def test_missing_plugins_are_degraded_not_startup_failure(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    _runtime_profile(dsh_home, ready=False)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    result = dsh_post_bootstrap.probe_or_repair(tmp_path)
    assert result["status"] == "DEGRADED"
    assert result["reason"] == "POST_START_REPAIR_AVAILABLE_BUT_NOT_REQUESTED"
    assert result["non_blocking"] is True


def test_broken_package_manager_remains_nonblocking_after_start(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    _runtime_profile(dsh_home, ready=False)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr(
        dsh_post_bootstrap.dsh_plugins,
        "install",
        lambda *args, **kwargs: {
            "status": "FAIL",
            "reason": "DSH_PLUGIN_INSTALL_FAILED",
            "output_tail": "MODULE_NOT_FOUND",
        },
    )
    result = dsh_post_bootstrap.probe_or_repair(tmp_path, attempt_persistent_install=True)
    assert result["status"] == "DEGRADED"
    assert result["reason"] == "PERSISTENT_INSTALL_FAILED_NON_BLOCKING"
    assert result["capability_state"] == "DEGRADED_PACKAGE_MANAGER_UNAVAILABLE"
    assert result["persistent_install_attempted"] is True
    assert result["persistent_install"]["reason"] == "DSH_PLUGIN_INSTALL_FAILED"


def test_protected_web_profile_cannot_be_post_start_install_target(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    (dsh_home / "profiles" / "web").mkdir(parents=True)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    result = dsh_post_bootstrap.probe_or_repair(tmp_path, profile="web", attempt_persistent_install=True)
    assert result["status"] == "FAIL"
    assert result["reason"] == "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN"
