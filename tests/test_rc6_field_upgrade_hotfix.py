from __future__ import annotations

import json
import sys
from pathlib import Path

from rc6_release.legacy_field_bridge import write_env
from rc6_release.legacy_skill_guard import (
    rollback_legacy_pfc_skills,
    sanitize_legacy_pfc_skills,
    verify_legacy_pfc_skills,
)
from rc6_release.tool_bootstrap import bootstrap_tools, verify_tool_profile


def _by_id(profile):
    return {item["tool_id"]: item for item in profile["tools"]}


def test_legacy_opencode_pfc_skill_is_backed_up_removed_and_restorable(tmp_path):
    workspace = tmp_path / "PFC"
    legacy_skill = workspace / ".opencode/skills/pfc-bank-context/SKILL.md"
    legacy_agent = workspace / ".opencode/agents/pfc-old-agent.md"
    custom_skill = workspace / ".opencode/skills/custom-bank/SKILL.md"
    legacy_skill.parent.mkdir(parents=True)
    legacy_agent.parent.mkdir(parents=True)
    custom_skill.parent.mkdir(parents=True)
    legacy_skill.write_text("legacy pfc bank context\n", encoding="utf-8")
    legacy_agent.write_text("legacy pfc agent\n", encoding="utf-8")
    custom_skill.write_text("must survive\n", encoding="utf-8")

    result = sanitize_legacy_pfc_skills(workspace)

    assert result["status"] == "PASS"
    assert result["removed_count"] == 2
    assert not legacy_skill.exists()
    assert not legacy_agent.exists()
    assert custom_skill.read_text(encoding="utf-8") == "must survive\n"
    assert verify_legacy_pfc_skills(workspace)["status"] == "PASS"

    backup = Path(result["backup_path"])
    assert (backup / ".opencode/skills/pfc-bank-context/SKILL.md").is_file()
    assert (backup / ".opencode/agents/pfc-old-agent.md").is_file()

    rollback = rollback_legacy_pfc_skills(workspace)
    assert rollback["restored_count"] == 2
    assert legacy_skill.read_text(encoding="utf-8") == "legacy pfc bank context\n"
    assert legacy_agent.read_text(encoding="utf-8") == "legacy pfc agent\n"
    assert custom_skill.read_text(encoding="utf-8") == "must survive\n"


def test_field_bridge_uses_runtime_registry_and_cat_secret_reference_without_reading_secret(tmp_path, monkeypatch):
    workspace = tmp_path / "PFC"
    context = workspace / "aitest-runtime-context"
    secrets = context / "secrets"
    secrets.mkdir(parents=True)

    marker = "SUPER_SECRET_VALUE_MUST_NEVER_APPEAR_IN_BRIDGE_STATE"
    cat_config = secrets / "cat.json"
    cat_config.write_text(json.dumps({"password": marker}), encoding="utf-8")

    registry = {
        "schema_version": "legacy.field.registry.v1",
        "tools": {
            "codegraph": {
                "tool_id": "codegraph",
                "executable": sys.executable,
            }
        },
    }
    (context / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

    env_file = tmp_path / "legacy-field-env.sh"
    result = write_env(workspace, env_file)
    bindings = {item["tool_id"]: item for item in result["bindings"]}

    assert result["registry_present"] is True
    assert result["secret_contents_read"] is False
    assert result["target_ready_forged"] is False
    assert bindings["codegraph"]["found"] is True
    assert bindings["codegraph"]["provenance"] == "AITEST_RUNTIME_CONTEXT_REGISTRY"
    assert Path(bindings["codegraph"]["path"]) == Path(sys.executable).resolve()
    assert bindings["cat"]["found"] is True
    assert bindings["cat"]["provenance"] == "AITEST_RUNTIME_CONTEXT_SECRET_REF"
    assert Path(bindings["cat"]["path"]) == cat_config.resolve()

    env_text = env_file.read_text(encoding="utf-8")
    assert "PFC_CODEGRAPH_BIN=" in env_text
    assert "PFC_CAT_CONFIG=" in env_text
    assert marker not in env_text

    bridge_state = (workspace / ".dsh/rc6/LEGACY_FIELD_BRIDGE.json").read_text(encoding="utf-8")
    assert marker not in bridge_state

    monkeypatch.setenv("PFC_CODEGRAPH_BIN", bindings["codegraph"]["path"])
    monkeypatch.setenv("PFC_CAT_CONFIG", bindings["cat"]["path"])
    monkeypatch.setenv("PFC_PYTHON", sys.executable)
    profile = bootstrap_tools(workspace)
    verified = verify_tool_profile(workspace)
    tools = _by_id(profile)

    assert tools["codegraph"]["status"] == "PROBE_PASS"
    assert tools["codegraph"]["provenance"] == "ENV:PFC_CODEGRAPH_BIN"
    assert tools["cat"]["status"] == "BLOCKED_FIELD_LOGIN"
    assert tools["cat"]["capability_stage"] == "DISCOVERED"
    assert tools["cat"]["target_ready"] is False
    assert profile["summary"]["target_ready"] == 0
    assert verified["summary"]["target_ready"] == 0


def test_cat_known_historical_location_is_discovered_even_without_registry_entry(tmp_path):
    workspace = tmp_path / "PFC"
    cat_config = workspace / "aitest-runtime-context/secrets/cat.json"
    cat_config.parent.mkdir(parents=True)
    cat_config.write_text("{}\n", encoding="utf-8")

    result = write_env(workspace, tmp_path / "env.sh")
    bindings = {item["tool_id"]: item for item in result["bindings"]}

    assert bindings["cat"]["found"] is True
    assert bindings["cat"]["provenance"] == "AITEST_RUNTIME_CONTEXT_SECRET_REF"
    assert Path(bindings["cat"]["path"]) == cat_config.resolve()
