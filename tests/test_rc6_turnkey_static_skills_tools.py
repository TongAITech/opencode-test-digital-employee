from __future__ import annotations

import json
import sys
from pathlib import Path

from rc6_release.package import build_package
from rc6_release.static_skills import ALL_SKILLS, PROFESSIONAL_SKILLS
from rc6_release.tool_bootstrap import bootstrap_tools, verify_tool_profile
from rc6_release.workspace_install import install_workspace


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _by_id(profile):
    return {item["tool_id"]: item for item in profile["tools"]}


def test_final_package_physically_contains_all_26_static_skills(tmp_path):
    package = build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)
    skill_root = package / ".dsh" / "skills"
    discovered = {path.parent.name for path in skill_root.glob("pfc-*/SKILL.md")}

    assert discovered == set(ALL_SKILLS)
    assert len(discovered) == 26
    assert len(PROFESSIONAL_SKILLS) == 25

    for name in PROFESSIONAL_SKILLS:
        text = (skill_root / name / "SKILL.md").read_text(encoding="utf-8")
        assert "## Mandatory RC6 governance" in text
        assert "## Professional method" in text
        assert "## Required output/evidence contract" in text
        assert "## Sufficiency / exit criteria" in text
        assert "DISCOVERED is not READY" in text


def test_workspace_install_copies_static_skills_byte_for_byte(tmp_path):
    package = build_package(REPO_ROOT, tmp_path / "dist", SOURCE_COMMIT, make_zip=False)
    workspace = tmp_path / "PFC"

    result = install_workspace(package, workspace)

    assert result["status"] == "PASS"
    assert result["skill_count"] == 26
    assert result["agent_count"] == 25
    assert result["rc6_profile_active"] == "PASS"

    for name in ALL_SKILLS:
        source = package / ".dsh" / "skills" / name / "SKILL.md"
        installed = workspace / ".dsh" / "skills" / name / "SKILL.md"
        assert installed.read_bytes() == source.read_bytes()

    manifest = json.loads((workspace / ".dsh" / "rc6" / "INSTALL_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["skill_source"] == "IMMUTABLE_PACKAGE_STATIC_PAYLOAD"


def test_tool_bootstrap_probes_reusable_host_tool_without_forging_target_ready(tmp_path, monkeypatch):
    workspace = tmp_path / "PFC"
    workspace.mkdir()
    monkeypatch.setenv("PFC_GIT_BIN", sys.executable)

    profile = bootstrap_tools(workspace)
    verified = verify_tool_profile(workspace)
    tools = _by_id(profile)

    assert tools["git"]["status"] == "PROBE_PASS"
    assert tools["git"]["provenance"] == "ENV:PFC_GIT_BIN"
    assert profile["summary"]["target_ready"] == 0
    assert verified["summary"]["target_ready"] == 0
    assert not any(item["target_ready"] for item in profile["tools"])
    assert all("DEFERRED_UNTIL" in item["broker_admission"] for item in profile["tools"])


def test_4a_and_cat_discovery_is_field_blocked_and_side_effect_free(tmp_path, monkeypatch):
    workspace = tmp_path / "PFC"
    tools_dir = workspace / "tools"
    tools_dir.mkdir(parents=True)

    foura = tools_dir / "foura_auth.py"
    foura.write_text("def login():\n    return 'not-executed-by-bootstrap'\n", encoding="utf-8")
    (tools_dir / "cat.yml").write_text("endpoint: placeholder\n", encoding="utf-8")
    monkeypatch.setenv("PFC_PYTHON", sys.executable)

    profile = bootstrap_tools(workspace)
    tools = _by_id(profile)

    assert tools["4a"]["status"] == "BLOCKED_FIELD_AUTH"
    assert tools["4a"]["capability_stage"] == "DISCOVERED"
    assert tools["cat"]["status"] == "BLOCKED_FIELD_LOGIN"
    assert tools["cat"]["capability_stage"] == "DISCOVERED"
    assert tools["4a"]["target_ready"] is False
    assert tools["cat"]["target_ready"] is False
    assert not list(workspace.rglob("__pycache__"))
