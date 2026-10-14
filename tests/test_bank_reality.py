import tempfile
import unittest
from pathlib import Path

from rc6_runtime.reality import BankRealityRegistry, RealityError
from rc6_runtime.target import TargetIdentityBuilder, TargetIdentityError


def ready_fact(kind, fact_id, attributes):
    return {"kind": kind, "id": fact_id, "status": "READY", "attributes": attributes}


def seed_registry(path):
    reg = BankRealityRegistry(path)
    facts = [
        ready_fact("application", "cfg-admin", {"name": "cfg-admin"}),
        ready_fact("application", "cfg-data", {"name": "cfg-data"}),
        ready_fact("application", "cfg-scd", {"name": "cfg-scd"}),
        ready_fact("application", "cfg-center", {"name": "cfg-center"}),
        ready_fact("repository", "repo-admin", {"application": "cfg-admin", "release_id": "BLOAN-PF1.2.0", "revision": "a" * 40, "branch": "Release_BLOAN-PF1.2.0"}),
        ready_fact("repository", "repo-data", {"application": "cfg-data", "release_id": "BLOAN-PF1.2.0", "revision": "b" * 40, "branch": "Release_BLOAN-PF1.2.0"}),
        ready_fact("repository", "repo-scd", {"application": "cfg-scd", "release_id": "BLOAN-PF1.2.0", "revision": "c" * 40, "branch": "Release_BLOAN-PF1.2.0"}),
        ready_fact("repository", "repo-center", {"application": "cfg-center", "release_id": "BLOAN-PF1.2.0", "revision": "d" * 40, "branch": "Release_BLOAN-PF1.2.0"}),
        ready_fact("environment", "FAT1", {"name": "FAT1", "deployed_release_id": "BLOAN-PF1.2.0", "deployment_mode": "REMOTE_DEPLOYMENT"}),
        ready_fact("route", "FAT1-frontend", {"environment_id": "FAT1", "url": "http://fat1.example.internal/pfc"}),
        ready_fact("route", "FAT1-gateway", {"environment_id": "FAT1", "url": "http://fat1.example.internal/api"}),
        ready_fact("database", "FAT1-data", {"environment_id": "FAT1", "application": "cfg-data", "profile_id": "tdsql-fat1-data", "db_type": "TDSQL"}),
        ready_fact("database", "FAT1-scd", {"environment_id": "FAT1", "application": "cfg-scd", "profile_id": "tdsql-fat1-scd", "db_type": "TDSQL"}),
        ready_fact("database", "FAT1-center", {"environment_id": "FAT1", "application": "cfg-center", "profile_id": "tdsql-fat1-center", "db_type": "TDSQL"}),
        ready_fact("auth", "FAT1-4A", {"environment_id": "FAT1", "profile_id": "4a-fat1"}),
        ready_fact("cat", "FAT1-CAT", {"environment_id": "FAT1", "profile_id": "cat-fat1"}),
        ready_fact("account", "FAT1-default", {"environment_id": "FAT1", "username": "test-user", "credential_ref": "local-secret://fat1/default"}),
    ]
    count = reg.migrate_once("v194-history", facts)
    return reg, count


def build_target(reg):
    return TargetIdentityBuilder(reg).build(
        release_id="BLOAN-PF1.2.0",
        deployment_mode="REMOTE_DEPLOYMENT",
        environment_fact_id="FAT1",
        repository_fact_ids={
            "cfg-admin": "repo-admin",
            "cfg-data": "repo-data",
            "cfg-scd": "repo-scd",
            "cfg-center": "repo-center",
        },
        frontend_route_fact_id="FAT1-frontend",
        gateway_route_fact_id="FAT1-gateway",
        database_fact_ids={
            "cfg-data": "FAT1-data",
            "cfg-scd": "FAT1-scd",
            "cfg-center": "FAT1-center",
        },
        auth_fact_id="FAT1-4A",
        cat_fact_id="FAT1-CAT",
        account_fact_id="FAT1-default",
    )


class RegistryTests(unittest.TestCase):
    def test_historical_migration_is_one_time_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            reg, count = seed_registry(Path(d) / "bank-reality.json")
            self.assertGreater(count, 0)
            self.assertTrue(reg.migration_complete("v194-history"))
            self.assertEqual(reg.migrate_once("v194-history", []), 0)
            self.assertEqual(len(reg.list()), count)

    def test_freshness_reconcile_ready_then_stale(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            ready = reg.reconcile("repository", "repo-data", {"revision": "b" * 40}, verified_at="2026-10-14T14:00:00+08:00")
            self.assertEqual(ready["status"], "READY")
            stale = reg.reconcile("repository", "repo-data", {"revision": "e" * 40}, verified_at="2026-10-14T14:01:00+08:00")
            self.assertEqual(stale["status"], "STALE")
            self.assertIn("revision", stale["drift"])

    def test_secret_values_are_forbidden_but_secret_refs_are_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            reg = BankRealityRegistry(Path(d) / "bank-reality.json")
            with self.assertRaises(RealityError):
                reg.upsert("account", "bad", {"username": "u", "password": "plaintext"}, status="READY")
            good = reg.upsert("account", "good", {"username": "u", "credential_ref": "local-secret://good"}, status="READY")
            self.assertEqual(good["status"], "READY")


class TargetIdentityTests(unittest.TestCase):
    def test_remote_fat_target_is_deterministic_and_does_not_require_local_services(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            t1 = build_target(reg)
            t2 = build_target(reg)
            self.assertEqual(t1.target_id, t2.target_id)
            self.assertEqual(t1.deployment_mode, "REMOTE_DEPLOYMENT")
            self.assertEqual(set(t1.repositories), {"cfg-admin", "cfg-data", "cfg-scd", "cfg-center"})
            self.assertNotIn("localhost", t1.frontend_url)

    def test_database_needs_binding_blocks_execution_target(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            fact = reg.get("database", "FAT1-data")
            reg.upsert("database", "FAT1-data", fact["attributes"], status="NEEDS_BINDING")
            with self.assertRaises(TargetIdentityError) as ctx:
                build_target(reg)
            self.assertIn("REALITY_FACT_NOT_READY:database:FAT1-data", str(ctx.exception))

    def test_stale_repository_blocks_target(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            reg.reconcile("repository", "repo-admin", {"revision": "x" * 40})
            with self.assertRaises(TargetIdentityError):
                build_target(reg)

    def test_environment_release_mismatch_blocks_target(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            env = reg.get("environment", "FAT1")
            attrs = dict(env["attributes"])
            attrs["deployed_release_id"] = "BLOAN-PF1.1.0"
            reg.upsert("environment", "FAT1", attrs, status="READY")
            with self.assertRaises(TargetIdentityError) as ctx:
                build_target(reg)
            self.assertEqual(str(ctx.exception), "TARGET_ENVIRONMENT_RELEASE_MISMATCH")

    def test_missing_route_blocks_target(self):
        with tempfile.TemporaryDirectory() as d:
            reg, _ = seed_registry(Path(d) / "bank-reality.json")
            gateway = reg.get("route", "FAT1-gateway")
            reg.upsert("route", "FAT1-gateway", gateway["attributes"], status="NEEDS_BINDING")
            with self.assertRaises(TargetIdentityError):
                build_target(reg)


if __name__ == "__main__":
    unittest.main()
