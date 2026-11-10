"""F-owned RC7.2 R4 and DSH workbench boundary checks.

These are source-contract sanity probes, not actual DSH 1.18.26 / Agent
Teams 32-worker bank field qualification. They intentionally fail if an
in-memory roster/config is misrepresented as real team execution.
"""
import unittest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_agentteams_capacity import (
    TeamCapacityPolicy,
    proposed_plugin_config,
    verify_installed_plugin_capacity,
    NANMICODER_PLUGIN,
    OFFICIAL_TEAM_PLUGIN,
)


class TestFTeamCapacityBoundary(unittest.TestCase):
    def test_roster32_is_not_active32_and_is_not_case_limit(self):
        p = TeamCapacityPolicy()
        self.assertEqual(32, p.team_member_capacity)
        self.assertEqual(4, p.max_active_workers)
        self.assertGreater(p.team_member_capacity, p.max_active_workers)

    def test_plugin_configuration_proposal_does_not_mutate_existing_credentials(self):
        current = {"maxMembers": 8, "rolePermissions": ["read"], "context": "keep"}
        before = dict(current)
        candidate = proposed_plugin_config(NANMICODER_PLUGIN, current)
        self.assertEqual(32, candidate["maxMembers"])
        self.assertEqual(before, current)
        self.assertEqual(["read"], candidate["rolePermissions"])

    def test_observed_config_value_does_not_claim_actual_field_executions(self):
        observed = verify_installed_plugin_capacity(
            plugin_name=NANMICODER_PLUGIN, plugin_version="0.1.29",
            observed_config={"maxMembers": 32},
        )
        self.assertEqual(32, observed["team_member_capacity"])
        self.assertEqual(4, observed["max_active_workers"])
        self.assertIs(observed["field_verified"], False)
        self.assertIs(observed["bank_final"], False)
        self.assertNotIn("active_worker_sessions", observed)

    def test_protected_official_plugin_does_not_accept_nanmi_config_field(self):
        with self.assertRaises(ContractError):
            proposed_plugin_config(OFFICIAL_TEAM_PLUGIN, {"maxMembers": 8})

    def test_invalid_or_excessive_active_worker_capacity_fails_closed(self):
        for active in (0, 33, True, -1):
            with self.subTest(active=active):
                with self.assertRaises(ContractError):
                    TeamCapacityPolicy(max_active_workers=active)
        with self.assertRaises(ContractError):
            TeamCapacityPolicy(team_member_capacity=8, max_active_workers=9)


if __name__ == "__main__":
    unittest.main()
