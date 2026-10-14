from __future__ import annotations

from pathlib import Path

import pytest

from rc6_release.package import build_package
from rc6_release.workspace_install import (
    ROLE_DESCRIPTIONS,
    WorkspaceInstallError,
    install_workspace,
    rollback_workspace,
    verify_workspace,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"


def _package(tmp_path: Path) -> Path:
    return build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)


def test_workspace_fresh_install_and_idempotent_repair(tmp_path):
    package = _package(tmp_path)
    workspace = tmp_path / "PFC"
    first = install_workspace(package, workspace)
    assert first["status"] == "PASS"
    assert first["install_mode"] == "FRESH_INSTALL"
    assert first["rc6_profile_active"] == "PASS"
    assert first["agent_count"] == len(ROLE_DESCRIPTIONS) == 25
    assert first["skill_count"] == first["agent_count"] + 1 == 26
    assert (workspace / ".dsh/skills/pfc-full-chain-test/SKILL.md").is_file()
    assert (workspace / ".dsh/skills/pfc-requirement-analysis/SKILL.md").is_file()

    second = install_workspace(package, workspace)
    assert second["status"] == "PASS"
    assert second["install_mode"] == "RC6_REPAIR"
    assert verify_workspace(package, workspace)["status"] == "PASS"


def test_workspace_upgrade_backs_up_legacy_and_preserves_unrelated_skill(tmp_path):
    package = _package(tmp_path)
    workspace = tmp_path / "PFC"
    legacy = workspace / ".dsh/skills/pfc-old-rc5/SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy rc5\n", encoding="utf-8")
    legacy_agent = workspace / ".agents/skills/pfc-old-agent/SKILL.md"
    legacy_agent.parent.mkdir(parents=True)
    legacy_agent.write_text("legacy agent\n", encoding="utf-8")
    custom = workspace / ".dsh/skills/custom-bank/SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("keep me\n", encoding="utf-8")

    result = install_workspace(package, workspace)
    assert result["install_mode"] == "UPGRADE_FROM_LEGACY"
    assert result["legacy_rc5_pfc_active"] is False
    assert custom.read_text(encoding="utf-8") == "keep me\n"
    assert not legacy.exists()
    assert not legacy_agent.exists()
    backup = Path(result["backup_path"])
    assert (backup / ".dsh/skills/pfc-old-rc5/SKILL.md").is_file()
    assert (backup / ".agents/skills/pfc-old-agent/SKILL.md").is_file()


def test_workspace_rollback_restores_previous_managed_profile(tmp_path):
    package = _package(tmp_path)
    workspace = tmp_path / "PFC"
    legacy = workspace / ".dsh/skills/pfc-legacy/SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("before\n", encoding="utf-8")
    result = install_workspace(package, workspace)
    assert result["install_mode"] == "UPGRADE_FROM_LEGACY"
    rollback = rollback_workspace(workspace, result["backup_path"])
    assert rollback["status"] == "PASS"
    assert legacy.read_text(encoding="utf-8") == "before\n"
    assert not (workspace / ".dsh/rc6/INSTALL_MANIFEST.json").exists()


def test_workspace_profile_verification_rejects_role_skill_tamper(tmp_path):
    package = _package(tmp_path)
    workspace = tmp_path / "PFC"
    install_workspace(package, workspace)
    role = workspace / ".dsh/skills/pfc-code-analysis/SKILL.md"
    role.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(WorkspaceInstallError, match="RC6_SKILL_HASH_MISMATCH:pfc-code-analysis"):
        verify_workspace(package, workspace)
