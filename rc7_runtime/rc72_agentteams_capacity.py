"""R4-07 verified DSH Agent Teams capacity policy (member roster != active work).

The third-party package may be installed in a protected bank profile. This
module NEVER edits that profile, installs a plugin, or treats planned members as
observed DSH sessions. A real installed-plugin/version/config observation is
required for positive qualification.
"""
from dataclasses import dataclass
from typing import Mapping

from .models import ContractError


NANMICODER_PLUGIN = "@nanmicoder/dsh-agent-teams"
LEGACY_TEAM_PLUGIN = "dsh-team"
OFFICIAL_TEAM_PLUGIN = "@deepseek-ai/dsh-agent-team"


@dataclass(frozen=True)
class TeamCapacityPolicy:
    """32 roster slots, four in-flight R1 workers by default.

    A slot represents a plugin-member identity; max_active_workers governs
    scheduler admissions, not the number of Team records or model calls.
    """

    team_member_capacity: int = 32
    max_active_workers: int = 4

    def __post_init__(self):
        for name in ("team_member_capacity", "max_active_workers"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 32:
                raise ContractError("R4_TEAM_CAPACITY_INVALID_" + name.upper())
        if self.max_active_workers > self.team_member_capacity:
            raise ContractError("R4_ACTIVE_WORKERS_EXCEED_ROSTER_CAPACITY")


def _field(plugin_name):
    if plugin_name == NANMICODER_PLUGIN:
        return "maxMembers"
    if plugin_name == LEGACY_TEAM_PLUGIN:
        return "maxTeammates"
    if plugin_name == OFFICIAL_TEAM_PLUGIN:
        raise ContractError("R4_OFFICIAL_TEAM_USES_SUBAGENT_RUNTIME_CAPACITY")
    raise ContractError("R4_UNKNOWN_DSH_AGENTTEAMS_PLUGIN")


def proposed_plugin_config(plugin_name, current_config, policy=None):
    """Pure, explicit proposed config. No write to an active DSH profile."""
    policy = policy if policy is not None else TeamCapacityPolicy()
    if type(policy) is not TeamCapacityPolicy:
        raise ContractError("R4_CAPACITY_POLICY_REQUIRED")
    if not isinstance(current_config, Mapping):
        raise ContractError("R4_OBSERVED_PLUGIN_CONFIG_REQUIRED")
    field = _field(plugin_name)
    if (field in current_config
            and (type(current_config[field]) is not int
                 or current_config[field] < 1)):
        raise ContractError("R4_PLUGIN_CAPACITY_CONFIG_INVALID")
    result = dict(current_config)
    result[field] = policy.team_member_capacity
    return result


def verify_installed_plugin_capacity(*, plugin_name, plugin_version,
                                     observed_config, policy=None):
    """Verify real plugin identity + observed config; no inferred success.

    The caller must have independently obtained plugin_name/version/config
    from the actual running DSH profile. This verifies that observation's
    shape/value; it cannot by itself verify the provenance of a caller.
    """
    policy = policy if policy is not None else TeamCapacityPolicy()
    if type(policy) is not TeamCapacityPolicy:
        raise ContractError("R4_CAPACITY_POLICY_REQUIRED")
    if not isinstance(plugin_version, str) or not plugin_version.strip():
        raise ContractError("R4_INSTALLED_PLUGIN_VERSION_REQUIRED")
    if not isinstance(observed_config, Mapping):
        raise ContractError("R4_OBSERVED_PLUGIN_CONFIG_REQUIRED")
    field = _field(plugin_name)
    value = observed_config.get(field)
    if type(value) is not int or value != policy.team_member_capacity:
        raise ContractError("R4_INSTALLED_PLUGIN_MEMBER_CAPACITY_NOT_QUALIFIED")
    return {
        "plugin": plugin_name,
        "plugin_version": plugin_version,
        "configuration_field": field,
        "team_member_capacity": value,
        "max_active_workers": policy.max_active_workers,
        "field_verified": False,
        "bank_final": False,
    }
