"""R4 exact profile mutation tests, no real DSH/Field claim."""
import json

import pytest

from rc7_release import dsh_runtime_profile
from rc7_release.rc72_team_profile_capacity import (
    TeamProfileCapacityError, _rewrite_exact_agentteams_row,
    apply_cloned_profile_capacity,
)
from test_rc7_dsh_runtime_profile import _seed_bank_profile


def _base(tmp_path, monkeypatch, config):
    home = tmp_path / ".dsh"
    source = _seed_bank_profile(home)
    (source / "cordis.patch.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    result = dsh_runtime_profile.prepare_runtime_profile(tmp_path, runtime_profile="rc7.2-bank")
    assert result["status"] == "PASS"
    clone = home / "profiles" / "rc7.2-bank"
    before = dsh_runtime_profile.profile_snapshot("web")["digest"]
    return source, clone, before


def test_full_plugin_config_and_protected_profile_preserved(tmp_path, monkeypatch):
    original = ("- insert:\n"
                "    - id: agent-teams\n"
                "      name: '@nanmicoder/dsh-agent-teams'\n"
                "      config:\n"
                "        memberProvider: spawn\n"
                "        memberModel: deepseek-v4\n"
                "        maxMembers: 8 # previous limit\n"
                "        memberMaxDepth: 0\n"
                "    - id: other\n"
                "      name: 'bank-private'\n")
    source, clone, before = _base(tmp_path, monkeypatch, original)
    report = apply_cloned_profile_capacity()
    assert report["status"] == "SOURCE_CONFIG_APPLIED_NOT_RUNTIME_VERIFIED"
    assert report["team_member_capacity"] == 32 and report["max_active_workers"] == 4
    assert not report["field_verified"] and not report["bank_final"]
    updated = (clone / "cordis.patch.yml").read_text(encoding="utf-8")
    assert updated == original.replace("maxMembers: 8", "maxMembers: 32")
    assert (source / "cordis.patch.yml").read_text(encoding="utf-8") == original
    assert dsh_runtime_profile.profile_snapshot("web")["digest"] == before
    second = apply_cloned_profile_capacity()
    assert second["clone_config_sha256"] == report["clone_config_sha256"]
    assert (clone / "cordis.patch.yml").read_text(encoding="utf-8") == updated


def test_missing_config_field_is_inserted_without_removing_other_fields(tmp_path, monkeypatch):
    _, clone, _ = _base(tmp_path, monkeypatch, (
        "- id: agent-teams\n"
        "  name: '@nanmicoder/dsh-agent-teams'\n"
        "  config:\n"
        "    memberModel: qwen\n"
        "    memberMaxDepth: 0\n"
        "- id: plugin-x\n"))
    apply_cloned_profile_capacity()
    s = (clone / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "    maxMembers: 32\n    memberModel: qwen\n" in s
    assert "    memberMaxDepth: 0\n" in s


def test_plugin_row_without_config_gets_a_new_config_block(tmp_path, monkeypatch):
    _, clone, _ = _base(tmp_path, monkeypatch, (
        "- insert:\n"
        "    - id: agent-teams\n"
        "      name: '@nanmicoder/dsh-agent-teams'\n"
        "    - id: other\n"
        "      name: another\n"))
    apply_cloned_profile_capacity()
    s = (clone / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "    - id: agent-teams\n      config:\n        maxMembers: 32\n" in s


@pytest.mark.parametrize("src,error", [
    ("- id: other\n", "ROW_NOT_UNIQUE"),
    ("- id: agent-teams\n- id: agent-teams\n", "ROW_NOT_UNIQUE"),
    ("- id: agent-teams\n  config: {maxMembers: 8}\n", "INLINE_OR_DYNAMIC"),
    ("- id: agent-teams\n  config:\n    maxMembers: !!js 8\n", "NOT_PLAIN_INTEGER"),
    ("- id: agent-teams\n  config:\n    maxMembers: 8\n    maxMembers: 9\n", "DUPLICATED"),
    ("- id: agent-teams\n  config:\n    maxMembers: 0\n", "CAP_INVALID"),
])
def test_unsafe_or_ambiguous_source_denied(src, error):
    with pytest.raises(TeamProfileCapacityError, match=error):
        _rewrite_exact_agentteams_row(src, 32)


def test_missing_actual_plugin_is_refused_without_modifying_bank(tmp_path, monkeypatch):
    source, clone, before = _base(tmp_path, monkeypatch, "- id: agent-teams\n  config:\n    maxMembers: 8\n")
    package = clone / "node_modules" / "@nanmicoder" / "dsh-agent-teams" / "package.json"
    package.unlink()
    with pytest.raises(TeamProfileCapacityError, match="PLUGIN_OR_CONFIG_MISSING"):
        apply_cloned_profile_capacity()
    assert dsh_runtime_profile.profile_snapshot("web")["digest"] == before


def test_stale_clone_origin_and_symlink_blocked(tmp_path, monkeypatch):
    _, clone, _ = _base(tmp_path, monkeypatch, "- id: agent-teams\n  config:\n    maxMembers: 8\n")
    marker = clone / dsh_runtime_profile.PROFILE_MARKER
    origin = json.loads(marker.read_text(encoding="utf-8"))
    origin["base_digest"] = "0" * 64
    marker.write_text(json.dumps(origin), encoding="utf-8")
    with pytest.raises(TeamProfileCapacityError, match="ORIGIN_DRIFT"):
        apply_cloned_profile_capacity()


def test_clone_with_wrong_package_identity_denied(tmp_path, monkeypatch):
    _, clone, _ = _base(tmp_path, monkeypatch, "- id: agent-teams\n  config:\n    maxMembers: 8\n")
    package = clone / "node_modules" / "@nanmicoder" / "dsh-agent-teams" / "package.json"
    package.write_text('{"name":"impostor","version":"1.0.0"}', encoding="utf-8")
    with pytest.raises(TeamProfileCapacityError, match="IDENTITY_INVALID"):
        apply_cloned_profile_capacity()
