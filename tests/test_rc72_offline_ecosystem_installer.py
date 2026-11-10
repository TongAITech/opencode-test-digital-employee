from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER_PATH = Path(__file__).resolve().parents[1] / "offline-ecosystem" / "install.py"
SPEC = importlib.util.spec_from_file_location("rc72_ecosystem_installer", str(INSTALLER_PATH))
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def _make_bundle(root: Path) -> Path:
    (root / "packages").mkdir(parents=True)
    (root / "runtime/mnemon").mkdir(parents=True)
    shutil.copy2(str(INSTALLER_PATH), str(root / "install.py"))
    extensions = []
    for package_id, name, version, license_id in (
        ("dsh-skills-manager", "@michengai/dsh-skills-manager", "1.4.1", "Apache-2.0"),
        ("dsh-mnemon", "dsh-mnemon", "0.5.43", "MIT"),
        ("dsh-archify", "dsh-archify", "0.1.0", "MIT"),
        ("modlens", "@liustack/modlens", "3.27.3", "MIT"),
    ):
        package_root = root / "packages" / package_id
        package_root.mkdir()
        (package_root / "package.json").write_text(
            json.dumps({"name": name, "version": version, "license": license_id}),
            encoding="utf-8",
        )
        (package_root / "LICENSE").write_text(license_id, encoding="utf-8")
        (package_root / "index.js").write_text("module.exports = {};", encoding="utf-8")
        extensions.append({
            "id": package_id,
            "package": name,
            "version": version,
            "license": license_id,
            "bundle_tree_sha256": installer._tree_sha256(package_root),
        })
    native = root / "runtime/mnemon/mnemon.exe" if installer._platform_id() == "win32-x64" else root / "runtime/mnemon/mnemon"
    native.write_bytes(b"native-cli-fixture")
    manifest = {
        "schema_version": installer.SCHEMA,
        "platform": installer._platform_id(),
        "explicit_exclusions": installer.EXCLUDED,
        "extensions": extensions,
        "mnemon_native_cli": {
            "version": "0.2.9",
            "path": native.relative_to(root).as_posix(),
            "sha256": installer._sha256(native),
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _fake_dsh(tmp_path: Path, log: Path, version: str = "0.2.2-rc.1") -> Path:
    script = tmp_path / "fake_dsh.py"
    script.write_text(
        "import json, os, sys\n"
        "args=sys.argv[1:]\n"
        "if args == ['--version']:\n print('DSH " + version + "'); raise SystemExit(0)\n"
        "if 'list' in args:\n"
        " print('\\n'.join(['@michengai/dsh-skills-manager','dsh-mnemon','dsh-archify','@liustack/modlens'])); raise SystemExit(0)\n"
        "if 'add' in args or 'remove' in args:\n"
        " assert os.environ.get('npm_config_offline') == 'true'\n"
        " assert os.environ.get('PNPM_CONFIG_OFFLINE') == 'true'\n"
        " assert os.environ.get('MNEMON_CLI_PATH') and os.path.isfile(os.environ['MNEMON_CLI_PATH'])\n"
        " open(os.environ['FAKE_DSH_LOG'],'a').write(json.dumps(args)+'\\n')\n"
        " raise SystemExit(0)\n"
        "print('unknown command', args); raise SystemExit(9)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        command = tmp_path / "fake_dsh.cmd"
        command.write_text('@echo off\r\npython "%~dp0fake_dsh.py" %*\r\n', encoding="utf-8")
    else:
        command = tmp_path / "fake_dsh"
        command.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script), encoding="utf-8")
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
    return command


def _fake_rc72_home(root: Path) -> Path:
    (root / "packaging/rc7.2").mkdir(parents=True)
    (root / "workspace-template/runtime").mkdir(parents=True)
    (root / "SOURCE_COMMIT").write_text("a" * 40, encoding="utf-8")
    (root / "packaging/rc7.2/AITEST.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def test_bundle_root_resolves_double_folder_with_spaces(tmp_path: Path) -> None:
    outer = tmp_path / "outer folder with spaces"
    root = _make_bundle(outer / "inner package with spaces")
    assert installer.resolve_bundle_root(outer) == root.resolve()


def test_bundle_verify_checks_platform_and_all_four_package_trees(tmp_path: Path) -> None:
    root = _make_bundle(tmp_path / "bundle")
    result = installer.verify_bundle(root)
    assert result["status"] == "PASS"
    assert result["extensions"] == 4


def test_bundle_verify_rejects_tampered_plugin_tree(tmp_path: Path) -> None:
    root = _make_bundle(tmp_path / "bundle")
    (root / "packages/dsh-mnemon/index.js").write_text("tampered", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="BUNDLE_PACKAGE_TREE_SHA256_MISMATCH"):
        installer.verify_bundle(root)


def test_install_and_uninstall_are_offline_and_never_target_web(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    log = tmp_path / "dsh.log"
    dsh = _fake_dsh(tmp_path, log)
    os.environ["FAKE_DSH_LOG"] = str(log)
    original_run = installer._run
    def _run_with_native_fixture(command, env=None):
        if Path(str(command[0])).name in ("mnemon.exe", "mnemon"):
            return "mnemon 0.2.9"
        return original_run(command, env=env)
    monkeypatch.setattr(installer, "_run", _run_with_native_fixture)
    receipt = installer.install(bundle, rc72_home=rc72_home, dsh_bin=dsh, profile="rc7.2-bank")
    assert receipt["status"] == "INSTALLED_HOST_ACTIVATION_NOT_BANK_ACCEPTANCE"
    assert receipt["profile"] == "rc7.2-bank"
    assert installer.health(rc72_home, dsh_bin=dsh)["status"] == "PASS"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if '"add"' in line]) == 4
    with pytest.raises(installer.InstallError, match="PROTECTED_OR_NON_RC72_PROFILE_FORBIDDEN"):
        installer.install(bundle, rc72_home=rc72_home, dsh_bin=dsh, profile="web")
    result = installer.uninstall(rc72_home, dsh_bin=dsh, profile="rc7.2-bank")
    assert result["status"] == "UNINSTALLED"
    assert result["memory_data_preserved"] is True
    assert not (rc72_home / "workspace-template/runtime/mnemon").exists()


def test_dsh_host_version_outside_peer_range_fails_before_copy(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    dsh = _fake_dsh(tmp_path, tmp_path / "dsh.log", version="0.1.9")
    with pytest.raises(installer.InstallError, match="DSH_VERSION_OUTSIDE_SKILLS_MANAGER_RANGE"):
        installer.install(bundle, rc72_home=rc72_home, dsh_bin=dsh, profile="rc7.2-bank")
    assert not (rc72_home / "workspace-template/runtime/dsh-ecosystem-extensions").exists()
