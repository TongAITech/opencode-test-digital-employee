from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
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
    (root / "modlens-config.bank-template.json").write_text("{}", encoding="utf-8")
    return root


def _fake_dsh(tmp_path: Path, log: Path, version: str = "0.2.2-rc.1") -> Path:
    script = tmp_path / "fake_dsh.py"
    script.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "profile=args[args.index('--profile')+1] if '--profile' in args else 'web'\n"
        "home=Path(os.environ['DSH_HOME'])\n"
        "profile_root=home/'profiles'/profile\n"
        "if args == ['--version']:\n print('DSH " + version + "'); raise SystemExit(0)\n"
        "if '--from-default-profile' in args:\n"
        " profile_root.mkdir(parents=True, exist_ok=True)\n"
        " data={'name':'dsh-profile-'+profile,'private':True,'dependencies':{'@deepseek-ai/dsh-base':'0.2.2-rc.1'},'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base']}}}\n"
        " (profile_root/'package.json').write_text(json.dumps(data), encoding='utf-8')\n"
        " print('initialized'); raise SystemExit(0)\n"
        "if args and args[0]=='plugin' and 'add' in args:\n"
        " assert os.environ.get('npm_config_offline') == 'true'\n"
        " assert os.environ.get('PNPM_CONFIG_OFFLINE') == 'true'\n"
        " assert os.environ.get('MNEMON_CLI_PATH') and os.path.isfile(os.environ['MNEMON_CLI_PATH'])\n"
        " spec=args[-1]; assert spec.startswith('link:')\n"
        " package_root=Path(spec[5:]); package=json.loads((package_root/'package.json').read_text(encoding='utf-8'))\n"
        " data=json.loads((profile_root/'package.json').read_text(encoding='utf-8'))\n"
        " data.setdefault('dependencies',{})[package['name']]=spec\n"
        " bundles=data.setdefault('dsh',{}).setdefault('profile',{}).setdefault('bundles',[])\n"
        " if package['name'] not in bundles: bundles.append(package['name'])\n"
        " (profile_root/'package.json').write_text(json.dumps(data), encoding='utf-8')\n"
        " open(os.environ['FAKE_DSH_LOG'],'a').write(json.dumps(args)+'\\n')\n"
        " print('linked'); raise SystemExit(0)\n"
        "if args and args[0]=='plugin' and 'remove' in args:\n"
        " package=args[-1]; data=json.loads((profile_root/'package.json').read_text(encoding='utf-8'))\n"
        " data.get('dependencies',{}).pop(package,None)\n"
        " bundles=data.get('dsh',{}).get('profile',{}).get('bundles',[])\n"
        " if package in bundles: bundles.remove(package)\n"
        " (profile_root/'package.json').write_text(json.dumps(data), encoding='utf-8')\n"
        " open(os.environ['FAKE_DSH_LOG'],'a').write(json.dumps(args)+'\\n')\n"
        " print('unlinked'); raise SystemExit(0)\n"
        "if '--dump-config' in args:\n print('composed-profile-config'); raise SystemExit(0)\n"
        "if '--no-open' in args:\n time.sleep(8); raise SystemExit(0)\n"
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


def _patch_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh-home"))
    monkeypatch.setenv("FAKE_DSH_LOG", str(tmp_path / "dsh.log"))
    original_which = installer.shutil.which
    monkeypatch.setattr(
        installer.shutil,
        "which",
        lambda name, *args, **kwargs: ("pnpm" if name == "pnpm" else original_which(name, *args, **kwargs)),
    )


def _mock_native_cli(monkeypatch, version="0.2.9") -> None:
    original_run = installer._run

    def _run_with_native_fixture(command, env=None):
        if Path(str(command[0])).name in ("mnemon.exe", "mnemon"):
            return "mnemon " + version
        return original_run(command, env=env)

    monkeypatch.setattr(installer, "_run", _run_with_native_fixture)


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


def test_default_install_stages_all_optional_extensions_without_profile_mutation(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    _patch_environment(monkeypatch, tmp_path)
    _mock_native_cli(monkeypatch)
    receipt = installer.install(bundle, rc72_home=rc72_home, profile="rc7.2-bank")
    assert receipt["status"] == "STAGED_OPTIONAL_NOT_ACTIVATED"
    assert receipt["default_enabled"] is False
    assert all(row["installed"] is False for row in receipt["extensions"])
    assert not (tmp_path / "dsh-home/profiles").exists()
    health = installer.health(rc72_home)
    assert health["status"] == "STAGED"
    assert health["installed_plugins"] == 0
    assert len(health["staged_plugins"]) == 4


def test_explicit_activation_uses_local_link_and_writes_profile_receipt(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    _patch_environment(monkeypatch, tmp_path)
    _mock_native_cli(monkeypatch)
    log = tmp_path / "dsh.log"
    dsh = _fake_dsh(tmp_path, log)
    installer.install(bundle, rc72_home=rc72_home, profile="rc7.2-bank")
    result = installer.enable_plugin(rc72_home, "dsh-skills-manager", dsh_bin=dsh, profile="rc7.2-bank", boot_seconds=2)
    assert result["status"] == "PROFILE_CONFIG_AND_BOOT_PASS_RUNTIME_EFFECT_HOLD"
    assert result["runtime_effect_verified"] is False
    proof = Path(result["activation_receipt"])
    assert proof.is_file()
    proof_data = json.loads(proof.read_text(encoding="utf-8"))
    assert proof_data["protected_web_profile_unchanged"] is True
    assert proof_data["link_spec"].startswith("link:")
    health = installer.health(rc72_home)
    assert health["status"] == "PROFILE_CONFIG_AND_BOOT_PASS_RUNTIME_EFFECT_HOLD"
    assert health["installed_plugins"] == 1
    assert len(health["staged_plugins"]) == 3
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if '"add"' in line]) == 1
    result = installer.uninstall(rc72_home, dsh_bin=dsh, profile="rc7.2-bank")
    assert result["status"] == "UNINSTALLED"
    assert result["memory_data_preserved"] is True
    assert result["protected_web_profile_mutated"] is False
    assert len([line for line in log.read_text(encoding="utf-8").splitlines() if '"remove"' in line]) == 1
    assert not (rc72_home / "workspace-template/runtime/mnemon").exists()


def test_protected_web_profile_cannot_be_an_activation_target(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    _patch_environment(monkeypatch, tmp_path)
    _mock_native_cli(monkeypatch)
    installer.install(bundle, rc72_home=rc72_home, profile="rc7.2-bank")
    with pytest.raises(installer.InstallError, match="PROTECTED_OR_NON_RC72_PROFILE_FORBIDDEN"):
        installer.enable_plugin(rc72_home, "dsh-skills-manager", profile="web")


def test_dsh_host_version_outside_peer_range_fails_before_profile_mutation(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    _patch_environment(monkeypatch, tmp_path)
    _mock_native_cli(monkeypatch)
    dsh = _fake_dsh(tmp_path, tmp_path / "dsh.log", version="0.1.9")
    installer.install(bundle, rc72_home=rc72_home, profile="rc7.2-bank")
    with pytest.raises(installer.InstallError, match="DSH_VERSION_OUTSIDE_SKILLS_MANAGER_RANGE"):
        installer.enable_plugin(rc72_home, "dsh-skills-manager", dsh_bin=dsh, profile="rc7.2-bank")
    assert not (tmp_path / "dsh-home/profiles/rc7.2-bank").exists()


def test_native_cli_version_failure_rolls_back_all_staged_files(tmp_path: Path, monkeypatch) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    rc72_home = _fake_rc72_home(tmp_path / "RC72")
    _mock_native_cli(monkeypatch, version="0.2.8")
    with pytest.raises(installer.InstallError, match="MNEMON_CLI_VERSION_MISMATCH"):
        installer.install(bundle, rc72_home=rc72_home, profile="rc7.2-bank")
    assert not (rc72_home / "workspace-template/runtime/dsh-ecosystem-extensions").exists()
    assert not (rc72_home / "workspace-template/runtime/mnemon/mnemon").exists()
    assert not (rc72_home / "workspace-template/runtime/mnemon/mnemon.exe").exists()
    assert not (rc72_home / "runtime-state/ecosystem-extensions/install-receipt.json").exists()


def test_modlens_configuration_requires_internal_https_and_disables_credential_reuse(tmp_path: Path, monkeypatch) -> None:
    import builtins

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    values = iter(["http://vision.bank.internal/v1", "vision-model"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(values))
    monkeypatch.setattr(installer.getpass, "getpass", lambda _prompt: "test-secret")
    with pytest.raises(installer.InstallError, match="MODLENS_ENDPOINT_NOT_IN_APPROVED_INTERNAL_SUFFIX"):
        installer.configure_modlens(internal_host_suffix="bank.internal")
    assert not (tmp_path / ".modlens/config.json").exists()

    values = iter(["https://vision.bank.internal/v1", "vision-model"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(values))
    result = installer.configure_modlens(internal_host_suffix="bank.internal")
    assert result["status"] == "CONFIGURED_INTERNAL_ENDPOINT_ONLY"
    config = json.loads((tmp_path / ".modlens/config.json").read_text(encoding="utf-8"))
    assert config["provider"] == "openai"
    assert config["providers"]["openai"]["proxy"] == ""
    assert all(value is False for value in config["reuse"].values())
    assert config["guards"]["denyWhenUnknown"] is True
