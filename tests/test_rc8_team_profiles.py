import pytest

from rc8_center.node_team_runtime import NodeTeamRuntimeError
from rc8_center.team_profiles import resolve_team_profile, standard_team_profiles


def test_stage_resolves_canonical_profile():
    profile = resolve_team_profile(stage="CODE_ANALYSIS")
    assert profile.profile_id == "code-analysis"
    assert "codegraph-worker" in profile.member_roles


def test_execution_profile_keeps_data_and_evidence_roles():
    profile = resolve_team_profile(stage="TEST_EXECUTION")
    assert profile.member_roles == ("data-preparer", "test-executor", "evidence-verifier")


def test_unknown_stage_is_fail_closed():
    with pytest.raises(NodeTeamRuntimeError, match="TEAM_PROFILE_REQUIRED_FOR_STAGE"):
        resolve_team_profile(stage="UNKNOWN")


def test_unknown_explicit_profile_is_fail_closed():
    with pytest.raises(NodeTeamRuntimeError, match="UNKNOWN_TEAM_PROFILE"):
        resolve_team_profile(profile_id="invented")


def test_registry_copy_cannot_mutate_canonical_policy():
    profiles = standard_team_profiles()
    profiles.pop("code-analysis")
    assert resolve_team_profile(profile_id="code-analysis").profile_id == "code-analysis"
