from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

INSTALLER_PATH = Path(__file__).resolve().parents[1] / "offline-ecosystem" / "install.py"
BUILDER_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_rc72_dsh_ecosystem_bundle.py"

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

installer = _load(INSTALLER_PATH, "rc72_offline_installer_for_builder_tests")
builder = _load(BUILDER_PATH, "rc72_offline_builder_tests")


def test_builder_and_installer_package_tree_hash_contract(tmp_path: Path) -> None:
    root = tmp_path / "package"
    (root / "lib").mkdir(parents=True)
    (root / "package.json").write_text('{"name":"fixture","version":"1.0.0"}', encoding="utf-8")
    (root / "lib/index.js").write_text("export default 1", encoding="utf-8")
    assert builder._tree_sha256(root) == installer._tree_sha256(root)


def test_mnemon_bank_policy_keeps_only_local_native_provider(tmp_path: Path) -> None:
    root = tmp_path / "dsh-mnemon"
    root.mkdir()
    patch = root / "cordis.patch.yml"
    patch.write_text(
        "- insert:\n"
        "        - id: mnemon-source-memory-spaces\n"
        "          name: dsh-mnemon-source-memory-spaces\n"
        "          config:\n"
        "            providers:\n"
        "              - use: dsh-mnemon-provider-mnemon-native\n"
        "                instanceId: mnemon-native\n"
        "              - use: dsh-mnemon-provider-openviking\n"
        "                instanceId: openviking\n"
        "              - use: dsh-mnemon-provider-honcho\n"
        "                instanceId: honcho\n"
        "        # Skills keep DSH's own files and their evolution data\n",
        encoding="utf-8",
    )
    policy = builder._apply_bank_policy({"id": "dsh-mnemon"}, root)
    result = patch.read_text(encoding="utf-8")
    assert "dsh-mnemon-provider-mnemon-native" in result
    assert "dsh-mnemon-provider-openviking" not in result
    assert "dsh-mnemon-provider-honcho" not in result
    assert policy == {
        "active_memory_provider": "mnemon-native",
        "remote_memory_providers_enabled": False,
        "auto_capture_enabled": False,
        "skill_self_evolution_enabled": False,
    }


def test_deterministic_zip_is_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "a.txt").write_text("A", encoding="utf-8")
    (root / "b.txt").write_text("B", encoding="utf-8")
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    builder._write_deterministic_zip(root, first)
    builder._write_deterministic_zip(root, second)
    assert first.read_bytes() == second.read_bytes()



def test_source_build_prepares_mnemon_and_modlens_only(tmp_path: Path, monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/usr/bin/pnpm" if name == "pnpm" else None)
    monkeypatch.setattr(
        builder,
        "_run",
        lambda command, cwd=None, timeout=900: commands.append((command, cwd, timeout)) or "",
    )
    builder._prepare_source_build({"id": "dsh-mnemon"}, tmp_path)
    builder._prepare_source_build({"id": "modlens"}, tmp_path)
    builder._prepare_source_build({"id": "dsh-skills-manager"}, tmp_path)
    assert [row[0][1:] for row in commands] == [
        ["install", "--frozen-lockfile"],
        ["run", "build"],
        ["install", "--frozen-lockfile"],
        ["run", "build"],
    ]
    assert all(row[1] == tmp_path for row in commands)
    assert all(row[2] == 1800 for row in commands)


def test_source_build_fails_closed_when_pinned_pnpm_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(builder.shutil, "which", lambda _name: None)
    with pytest.raises(builder.BundleBuildError, match="PINNED_PNPM_10_13_1_REQUIRED_FOR_SOURCE_BUILD"):
        builder._prepare_source_build({"id": "dsh-mnemon"}, tmp_path)
