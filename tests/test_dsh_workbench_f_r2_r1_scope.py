"""F-owned independent adversarial regression for E107 P1 scope-first R1 read.

Pinned review target: A W0 f6aa541a7c82b74bcd1937754637d8341111fb70.
These are W0 tests against actual AdminProjection source + E's adapter, not
the bank Host, real PostgreSQL, principal ACL, or production QA.
"""
import unittest

from rc7_admin.projection import AdminProjection, AdminProjectionError
from tools.dsh_workbench.e_contract_oracle import ContractRejection
from tools.dsh_workbench.e_readonly_scope_prototype import (
    read_scoped_r1_mission_overview,
)


class ObservedTruth:
    def __init__(self, mission, *, duplicate=False, bad_detail=False):
        self.mission = mission
        self.duplicate = duplicate
        self.bad_detail = bad_detail
        self.calls = []
        self.rebuilds = 0

    def query(self, artifact_type, **filters):
        self.calls.append((artifact_type, dict(filters)))
        if artifact_type == "rc7_mission":
            rows = [] if self.mission is None else [self.mission]
            return rows * (2 if self.duplicate else 1)
        if self.bad_detail and artifact_type == "execution_attempt":
            raise RuntimeError("DETAIL_READ_FAILURE")
        return [{"mission_id": filters["mission_id"], "secret": "unrelated-detail"}]

    def rebuild_projection(self):
        self.rebuilds += 1
        raise AssertionError("MUST_NOT_REPLAY_GLOBAL_R1_BEFORE_SCOPE_AUTHORIZATION")


class TestFIndependentE107P1(unittest.TestCase):
    def mission(self, **changes):
        base = {"mission_id": "M-FOREIGN", "project_id": "P2",
                "batch_id": "B2", "release_id": "P1-legacy-label",
                "secret": "sensitive-mission-field"}
        base.update(changes)
        return base

    def assert_scope_reject_no_detail(self, mission, *, duplicate=False):
        truth = ObservedTruth(mission, duplicate=duplicate)
        projection = AdminProjection(truth)
        with self.assertRaises(AdminProjectionError) as ctx:
            projection.mission_overview_scoped(
                mission_id="M-FOREIGN", project_id="P1", batch_id="B1")
        self.assertEqual("R1_MISSION_SCOPE_UNRESOLVED", str(ctx.exception))
        self.assertEqual(
            [("rc7_mission", {"mission_id": "M-FOREIGN"})],
            truth.calls,
            "P1: related records MUST NOT be fetched for unapproved Mission")
        self.assertEqual(0, truth.rebuilds)

    def test_other_project_mission_cannot_trigger_related_reads(self):
        self.assert_scope_reject_no_detail(
            self.mission(project_id="P2", batch_id="B1"))

    def test_other_batch_mission_cannot_trigger_related_reads(self):
        self.assert_scope_reject_no_detail(
            self.mission(project_id="P1", batch_id="B2"))

    def test_missing_project_or_batch_cannot_infer_legacy_release_id(self):
        for delta in (
            {"project_id": None, "batch_id": "B1"},
            {"project_id": "P1", "batch_id": None},
            {"project_id": None, "batch_id": None},
        ):
            with self.subTest(delta=delta):
                self.assert_scope_reject_no_detail(self.mission(**delta))

    def test_absent_mission_indistinguishable_from_foreign_scope(self):
        self.assert_scope_reject_no_detail(None)

    def test_duplicate_mission_identity_fails_closed(self):
        self.assert_scope_reject_no_detail(
            self.mission(project_id="P1", batch_id="B1"), duplicate=True)

    def test_valid_mission_reads_identity_before_three_related_collections(self):
        truth = ObservedTruth(self.mission(project_id="P1", batch_id="B1"))
        overview = AdminProjection(truth).mission_overview_scoped(
            mission_id="M-FOREIGN", project_id="P1", batch_id="B1")
        self.assertEqual(
            {"mission_id": "M-FOREIGN", "project_id": "P1", "batch_id": "B1"},
            overview["mission"])
        self.assertNotIn("secret", overview["mission"])
        self.assertEqual(
            ["rc7_mission", "rc7_task", "execution_attempt", "rc7_evidence"],
            [kind for kind, _ in truth.calls])
        self.assertEqual({"tasks", "executions", "evidence"}, set(overview["related"]))
        self.assertEqual(0, truth.rebuilds)

    def test_related_failure_must_not_return_partial_mission_result(self):
        truth = ObservedTruth(
            self.mission(project_id="P1", batch_id="B1"), bad_detail=True)
        with self.assertRaises(AdminProjectionError) as ctx:
            AdminProjection(truth).mission_overview_scoped(
                mission_id="M-FOREIGN", project_id="P1", batch_id="B1")
        self.assertEqual("R1_RELATED_READ_FAILED", str(ctx.exception))
        self.assertEqual(
            ["rc7_mission", "rc7_task", "execution_attempt"],
            [kind for kind, _ in truth.calls])

    def test_adapter_rejects_foreign_scope_without_unscoped_fallback(self):
        truth = ObservedTruth(self.mission(project_id="P2", batch_id="B1"))
        with self.assertRaises(ContractRejection) as ctx:
            read_scoped_r1_mission_overview(
                AdminProjection(truth), project_id="P1", batch_id="B1",
                mission_id="M-FOREIGN")
        self.assertEqual("R1_MISSION_SCOPE_UNRESOLVED", ctx.exception.code)
        self.assertEqual(["rc7_mission"], [kind for kind, _ in truth.calls])

    def test_adapter_forbids_legacy_only_projection(self):
        class LegacyOnly:
            def __init__(self):
                self.called = False

            def mission_overview(self, mission_id):
                self.called = True
                raise AssertionError("unscoped method invoked")

        legacy = LegacyOnly()
        with self.assertRaises(ContractRejection) as ctx:
            read_scoped_r1_mission_overview(
                legacy, project_id="P1", batch_id="B1",
                mission_id="M-FOREIGN")
        self.assertEqual("R1_SCOPED_READ_UNAVAILABLE", ctx.exception.code)
        self.assertFalse(legacy.called)


if __name__ == "__main__":
    unittest.main()
