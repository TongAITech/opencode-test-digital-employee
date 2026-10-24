"""Canonical RC8 node-local team profiles.

Profiles are Center-owned policy. Nodes may resolve a profile id but must not
invent roles or silently fall back when a requested profile/stage is unknown.
"""
from __future__ import annotations

from typing import Dict

from .node_team_runtime import NodeTeamRuntimeError, TeamProfile


_STANDARD: Dict[str, TeamProfile] = {
    "requirement-analysis": TeamProfile("requirement-analysis", ("requirement-analyst", "coverage-critic")),
    "code-analysis": TeamProfile("code-analysis", ("change-analyst", "codegraph-worker", "impact-critic")),
    "test-design": TeamProfile("test-design", ("test-designer", "coverage-critic", "oracle-critic")),
    "test-execution": TeamProfile("test-execution", ("data-preparer", "test-executor", "evidence-verifier")),
    "defect-analysis": TeamProfile("defect-analysis", ("failure-classifier", "log-analyst", "defect-verifier")),
}

_STAGE_DEFAULT = {
    "REQUIREMENT_ANALYSIS": "requirement-analysis",
    "CODE_ANALYSIS": "code-analysis",
    "TEST_DESIGN": "test-design",
    "TEST_EXECUTION": "test-execution",
    "DEFECT_ANALYSIS": "defect-analysis",
}


def standard_team_profiles() -> Dict[str, TeamProfile]:
    return dict(_STANDARD)


def resolve_team_profile(*, profile_id: str = "", stage: str = "") -> TeamProfile:
    requested = (profile_id or "").strip()
    if not requested:
        requested = _STAGE_DEFAULT.get((stage or "").strip().upper(), "")
    if not requested:
        raise NodeTeamRuntimeError("TEAM_PROFILE_REQUIRED_FOR_STAGE")
    profile = _STANDARD.get(requested)
    if profile is None:
        raise NodeTeamRuntimeError("UNKNOWN_TEAM_PROFILE:%s" % requested)
    return profile
