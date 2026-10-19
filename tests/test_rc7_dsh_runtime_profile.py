from __future__ import annotations

import json
from pathlib import Path

from rc7_release import dsh_plugins, dsh_runtime_profile


def _package_dir(profile: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return profile / "node_modules" / scope / name
    return profile / "node_modules" / package


def _seed_bank_profile(root: Path, *, include_required: bool = True) -> Path:
    profile = root / "profiles" / "web"
    private = profile / "node_modules" / "wizard-opencode-plugin"
    private.mkdir(parents=True)
    (profile / "package.json").write_text(
        json.dumps({"name": "bank-web", "dependencies": {"wizard-opencode-plugin": "file:bank"}}),
        encoding="utf-8",
    )
    (private / "package.json").write_text(
        json.dumps({"name": "wizard-opencode-plugin", "version": "bank-private"}),
        encoding="utf-8",
    )
    if include_required:
        for package in dsh_plugins.REQUIRED:
            root_dir = _package_dir(profile, package)
            root_dir.mkdir(parents=True, exist_ok=True)
            (root_dir / "package.json").write_text(
                json.dumps({"name": package, "version": "bank-existing"}),
                encoding="utf-8",
            )
    return profile


def test_runtime_profile_physically_clones_bank_profile_without_package_manager(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    source = _seed_bank_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    source_before = dsh_runtime_profile.profile_snapshot("web")

    def forbidden_install(*args, **kwargs):
        raise AssertionError("PRESTART_PACKAGE_MANAGER_MUST_NOT_RUN")

    monkeypatch.setattr(dsh_runtime_profile.dsh_plugins, "install", forbidden_install)
    result = dsh_runtime_profile.prepare_runtime_profile(tmp_path)

    assert result["status"] == "PASS"
    assert result["protected_bank_profile_integrity"] == "PASS"
    assert result["package_manager_prestart"] == "FORBIDDEN"
    assert result["plugin_bootstrap_policy"] == "POST_START_NON_BLOCKING"
    assert result["persistent_install_attempted"] is False
    assert result["install"]["status"] == "SKIPPED"
    assert result["capability_state"] == "READY_FROM_CLONE"
    clone = dsh_home / "profiles" / "rc7-bank"
    assert (clone / "node_modules" / "wizard-opencode-plugin" / "package.json").is_file()
    assert (clone / dsh_runtime_profile.PROFILE_MARKER).is_file()
    marker = json.loads((clone / dsh_runtime_profile.PROFILE_MARKER).read_text(encoding="utf-8"))
    assert marker["schema_version"] == dsh_runtime_profile.PROFILE_SCHEMA
    assert marker["startup_policy"] == "CLONE_FIRST_NO_PACKAGE_MANAGER"
    assert dsh_runtime_profile.profile_snapshot("web")["digest"] == source_before["digest"]
    assert "wizard-opencode-plugin" in json.loads((source / "package.json").read_text(encoding="utf-8"))["dependencies"]


def test_runtime_profile_rebuilds_clone_when_bank_profile_drifts(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    source = _seed_bank_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr(
        dsh_runtime_profile.dsh_plugins,
        "install",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not install")),
    )
    first = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert first["status"] == "PASS"
    source_manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
    source_manifest["bank-revision"] = 2
    (source / "package.json").write_text(json.dumps(source_manifest), encoding="utf-8")
    second = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert second["status"] == "PASS"
    assert second["rebuild_reason"] == "BANK_BASE_PROFILE_DRIFT"


def test_v1_runtime_clone_is_rebuilt_to_remove_possible_partial_install(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    _seed_bank_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    base = dsh_runtime_profile.profile_snapshot("web")
    clone = dsh_home / "profiles" / "rc7-bank"
    clone.mkdir(parents=True)
    (clone / "package.json").write_text(json.dumps({"name": "dirty-half-installed"}), encoding="utf-8")
    (clone / dsh_runtime_profile.PROFILE_MARKER).write_text(
        json.dumps(
            {
                "schema_version": "pfc.aitest.rc7.dsh-runtime-profile.v1",
                "base_profile": "web",
                "base_digest": base["digest"],
                "runtime_profile": "rc7-bank",
            }
        ),
        encoding="utf-8",
    )

    result = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert result["status"] == "PASS"
    assert result["rebuild_reason"] == "RUNTIME_PROFILE_POLICY_UPGRADE"
    assert json.loads((clone / "package.json").read_text(encoding="utf-8"))["name"] == "bank-web"


def test_missing_required_plugins_degrades_capability_but_does_not_block_startup(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    _seed_bank_profile(dsh_home, include_required=False)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr(
        dsh_runtime_profile.dsh_plugins,
        "install",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not install")),
    )

    result = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert result["status"] == "PASS"
    assert result["capability_state"] == "DEGRADED_MISSING_REQUIRED_PLUGIN_MANIFESTS"
    assert result["startup_blocked_by_plugin_readiness"] is False
    assert set(result["required_plugin_state"]["missing"]) == set(dsh_plugins.REQUIRED)
