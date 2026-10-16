from __future__ import annotations

import json
from pathlib import Path

from rc7_release import dsh_runtime_profile


def _seed_bank_profile(root: Path) -> Path:
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
    return profile


def test_runtime_profile_physically_clones_bank_profile_and_preserves_source(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    source = _seed_bank_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    source_before = dsh_runtime_profile.profile_snapshot("web")

    def fake_install(home, profile, dry_run=False, **kwargs):
        assert profile == "rc7-bank"
        clone_manifest = dsh_home / "profiles" / profile / "package.json"
        data = json.loads(clone_manifest.read_text(encoding="utf-8"))
        data.setdefault("dependencies", {})["dsh-context"] = "file:test"
        clone_manifest.write_text(json.dumps(data), encoding="utf-8")
        return {"status": "PASS", "profile": profile}

    monkeypatch.setattr(dsh_runtime_profile.dsh_plugins, "install", fake_install)
    result = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert result["status"] == "PASS"
    assert result["protected_bank_profile_integrity"] == "PASS"
    clone = dsh_home / "profiles" / "rc7-bank"
    assert (clone / "node_modules" / "wizard-opencode-plugin" / "package.json").is_file()
    assert (clone / dsh_runtime_profile.PROFILE_MARKER).is_file()
    assert dsh_runtime_profile.profile_snapshot("web")["digest"] == source_before["digest"]
    assert "dsh-context" not in json.loads((source / "package.json").read_text(encoding="utf-8"))["dependencies"]


def test_runtime_profile_rebuilds_clone_when_bank_profile_drifts(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    source = _seed_bank_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr(
        dsh_runtime_profile.dsh_plugins,
        "install",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    first = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert first["status"] == "PASS"
    source_manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
    source_manifest["bank-revision"] = 2
    (source / "package.json").write_text(json.dumps(source_manifest), encoding="utf-8")
    second = dsh_runtime_profile.prepare_runtime_profile(tmp_path)
    assert second["status"] == "PASS"
    assert second["rebuild_reason"] == "BANK_BASE_PROFILE_DRIFT"
