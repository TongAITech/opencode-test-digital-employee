from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_release.dsh_plugin_qualification import (
    PluginQualificationError,
    profile_contract_snapshot,
    qualify,
)


def _seed_profile(root: Path) -> Path:
    profile = root / "profiles" / "web"
    wizard = profile / "node_modules" / "wizard-opencode-plugin"
    wizard.mkdir(parents=True)
    (profile / "package.json").write_text(
        json.dumps({"name": "bank-web", "dependencies": {"wizard-opencode-plugin": "file:bank"}}),
        encoding="utf-8",
    )
    (wizard / "package.json").write_text(
        json.dumps({"name": "wizard-opencode-plugin", "version": "bank-private"}),
        encoding="utf-8",
    )
    return profile


def test_protected_profile_snapshot_detects_private_plugin_removal(tmp_path, monkeypatch) -> None:
    dsh_home = tmp_path / ".dsh"
    profile = _seed_profile(dsh_home)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))

    before = profile_contract_snapshot("web")
    assert before["exists"] is True
    assert "node_modules/wizard-opencode-plugin/package.json" in before["files"]

    (profile / "node_modules" / "wizard-opencode-plugin" / "package.json").unlink()
    after = profile_contract_snapshot("web")
    assert after["digest"] != before["digest"]


def test_qualification_refuses_to_use_protected_profile_as_isolated_target(tmp_path) -> None:
    with pytest.raises(PluginQualificationError, match="ISOLATED_PROFILE_MUST_NOT_BE_PROTECTED"):
        qualify(tmp_path, protected_profile="web", isolated_profile="web")
