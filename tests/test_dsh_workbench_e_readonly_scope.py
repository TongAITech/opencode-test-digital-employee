"""W0 E01 pre-B06 read-only integration seam tests (NOT implementation QA)."""
import copy
import unittest

from tools.dsh_workbench.e_contract_oracle import ContractRejection
from tools.dsh_workbench.e_readonly_scope_prototype import (
    normalize_b06_scope, r1_preview, r1_preview_from_legacy_admin,
)


def verified_relation(req="R1", ver="V1", sst="SST-100"):
    return {
        "project_id": "P1", "batch_id": "B1", "requirement_id": req,
        "system_version_id": ver, "sst_id": sst,
        "split_state": "SPLIT" if sst is not None else "UNSPLIT",
        "source_verified_requirement_version": {
            "source_link_ref": "starlink:reqver:%s:%s" % (req, ver),
            "source_revision": "revision:reqver:v3",
        },
        "source_verified_link": {
            "source_link_ref": "starlink:sst:%s:%s:%s" % (req, ver, sst),
            "verified_source_revision": "revision:sst:v9",
        } if sst is not None else None,
    }


def verified_scope(rows=None):
    records = [verified_relation()] if rows is None else rows
    source_refs = []
    for row in records:
        rv = row.get("source_verified_requirement_version") or {}
        sst = row.get("source_verified_link") or {}
        for value in (rv.get("source_link_ref"), sst.get("source_link_ref")):
            if value and value not in source_refs:
                source_refs.append(value)
    return {
        "project_id": "P1", "batch_id": "B1",
        "release_date": "2026-11-12",
        "relation_revision": 2, "access_scope_revision": 3,
        "source_refs": source_refs,
        "next_page_cursor": None,
        "warnings": [], "gap_indicators": [],
        "records": records,
    }


def legacy_overview(mission=None, related=None):
    return {
        "mission": mission or {
            "mission_id": "M1", "project_id": "P1", "batch_id": "B1",
        },
        "related": related if related is not None else {
            "tasks": [{"task_id": "W1", "mission_id": "M1", "status": "PASS"}],
            "executions": [
                {"attempt_id": "A1", "mission_id": "M1", "result": "PASS"},
            ],
            "evidence": [
                {"evidence_id": "EV1", "mission_id": "M1",
                 "content_hash": "sha256:" + "a" * 64},
            ],
        },
    }


class LegacyProjectionFixture:
    def __init__(self, overview=None):
        self.identity_calls = []
        self.related_calls = []
        self.unscoped_calls = []
        self.overview = overview if overview is not None else legacy_overview()

    def mission_overview_scoped(self, *, mission_id, project_id, batch_id):
        self.identity_calls.append((project_id, batch_id, mission_id))
        mission = self.overview.get("mission")
        if (not isinstance(mission, dict)
                or mission.get("mission_id") != mission_id
                or mission.get("project_id") != project_id
                or mission.get("batch_id") != batch_id):
            raise ContractRejection("R1_MISSION_SCOPE_UNRESOLVED")
        self.related_calls.append(mission_id)
        return copy.deepcopy(self.overview)

    def mission_overview(self, mission_id):
        self.unscoped_calls.append(mission_id)
        raise AssertionError("unscoped mission_overview must never be called")


class LegacyAdminFixture:
    def __init__(self, overview=None):
        self.projection = LegacyProjectionFixture(overview)
        self.writes = []

    def dispatch_post(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("Legacy command API must never be called")


class EReadOnlyScopeTests(unittest.TestCase):
    def reject(self, code, callback):
        with self.assertRaises(ContractRejection) as raised:
            callback()
        self.assertEqual(code, raised.exception.code)

    def test_prototype_good_source_and_readonly_r1_projections(self):
        preview = r1_preview(verified_scope(), legacy_overview(),
                             project_id="P1", batch_id="B1", mission_id="M1")
        self.assertEqual("2026-11-12", preview["release_date"])
        self.assertEqual(1, len(preview["records"]))
        self.assertEqual("starlink:sst:R1:V1:SST-100",
                         preview["records"][0]["source_verified_link_ref"])
        self.assertEqual(1, len(preview["attempts"]))
        self.assertEqual("UNKNOWN_UNQUALIFIED", preview["attempts"][0]["result"])
        self.assertEqual("UNVERIFIED_NO_CONTENT_READ",
                         preview["evidence"][0]["integrity"])
        self.assertEqual("HOLD", preview["release_decision"])
        self.assertIsNone(preview["truth_revision"])

    def test_same_raw_sst_id_two_versions_keep_distinct_links(self):
        rows = [verified_relation(ver="V1"), verified_relation(ver="V2")]
        out = normalize_b06_scope(verified_scope(rows),
                                  project_id="P1", batch_id="B1")
        self.assertEqual(2, len(out["records"]))
        refs = [item["source_verified_link_ref"] for item in out["records"]]
        self.assertEqual(2, len(set(refs)))
        self.assertEqual(["V1", "V2"],
                         [item["system_version_id"] for item in out["records"]])

    def test_same_version_shared_by_two_requirements_not_same_sst(self):
        rows = [verified_relation(req="R1", ver="V1", sst="S1"),
                verified_relation(req="R2", ver="V1", sst="S2")]
        out = normalize_b06_scope(verified_scope(rows),
                                  project_id="P1", batch_id="B1")
        self.assertEqual([("R1", "S1"), ("R2", "S2")],
                         [(x["requirement_id"], x["sst_id"])
                          for x in out["records"]])

    def test_missing_source_verified_requirement_version_denied(self):
        row = verified_relation()
        row["source_verified_requirement_version"] = None
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: normalize_b06_scope(
            verified_scope([row]), project_id="P1", batch_id="B1"))

    def test_missing_sst_source_verified_link_denied(self):
        row = verified_relation()
        row["source_verified_link"]["verified_source_revision"] = ""
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: normalize_b06_scope(
            verified_scope([row]), project_id="P1", batch_id="B1"))

    def test_unsplit_row_valid_but_fake_sst_denied(self):
        row = verified_relation(sst=None)
        result = normalize_b06_scope(verified_scope([row]),
                                     project_id="P1", batch_id="B1")
        self.assertEqual("UNSPLIT", result["records"][0]["split_state"])
        self.assertIsNone(result["records"][0]["sst_id"])
        row["sst_id"] = "fake-SST"
        self.reject("UNSPLIT_MUST_NOT_INVENT_SST",
                    lambda: normalize_b06_scope(verified_scope([row]),
                        project_id="P1", batch_id="B1"))

    def test_cross_project_batch_scope_rejected(self):
        self.reject("FORBIDDEN", lambda: normalize_b06_scope(
            verified_scope(), project_id="P2", batch_id="B1"))
        self.reject("ILLEGAL_ASSOCIATION", lambda: normalize_b06_scope(
            verified_scope(), project_id="P1", batch_id="B2"))
        bad = verified_scope()
        bad["records"][0]["batch_id"] = "B2"
        self.reject("CROSS_BATCH_ASSOCIATION", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1"))

    def test_mission_scope_is_checked_against_r1_not_b06_payload(self):
        scope = verified_scope()
        self.assertNotIn("authorized_mission_ids", scope)
        wrong = legacy_overview(mission={
            "mission_id": "M1", "project_id": "P1", "batch_id": "B2",
        })
        self.reject("R1_MISSION_SCOPE_UNRESOLVED", lambda: r1_preview(
            scope, wrong, project_id="P1", batch_id="B1", mission_id="M1"))

    def test_duplicate_join_and_unknown_revision_denied(self):
        row = verified_relation()
        self.reject("DUPLICATE_RELATION", lambda: normalize_b06_scope(
            verified_scope([row, copy.deepcopy(row)]),
            project_id="P1", batch_id="B1"))
        bad = verified_scope()
        bad["relation_revision"] = None
        self.reject("SCOPE_REVISION_UNAVAILABLE", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1"))

    def test_business_day_invalid_date_fail_closed(self):
        bad = verified_scope()
        bad["release_date"] = "2026-02-30"
        self.reject("INVALID_BUSINESS_DATE", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1"))

    def test_old_r1_missing_canonical_batch_must_hold(self):
        source = legacy_overview(mission={"mission_id": "M1", "release_id": "B1"})
        self.reject("R1_MISSION_SCOPE_UNRESOLVED", lambda: r1_preview(
            verified_scope(), source, project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_r1_cross_project_mission_denied(self):
        source = legacy_overview(mission={
            "mission_id": "M1", "project_id": "P2", "batch_id": "B1"})
        self.reject("R1_MISSION_SCOPE_UNRESOLVED", lambda: r1_preview(
            verified_scope(), source, project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_cross_mission_evidence_not_attributed(self):
        source = legacy_overview(related={
            "tasks": [], "executions": [],
            "evidence": [{"evidence_id": "EV1", "mission_id": "M2"}],
        })
        self.reject("R1_UNVERIFIED_LINEAGE", lambda: r1_preview(
            verified_scope(), source, project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_duplicate_attempt_does_not_double_count(self):
        source = legacy_overview(related={
            "tasks": [], "evidence": [],
            "executions": [
                {"attempt_id": "A1", "mission_id": "M1"},
                {"attempt_id": "A1", "mission_id": "M1"},
            ],
        })
        self.reject("R1_DUPLICATE_ID", lambda: r1_preview(
            verified_scope(), source, project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_malformed_collection_denied(self):
        source = legacy_overview(related={"tasks": "not-array"})
        self.reject("R1_MALFORMED_COLLECTION", lambda: r1_preview(
            verified_scope(), source, project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_b06_deny_precedes_admin_r1_call(self):
        admin = LegacyAdminFixture()
        def deny_b06(*_args):
            raise ContractRejection("FORBIDDEN")
        self.reject("FORBIDDEN", lambda: r1_preview_from_legacy_admin(
            deny_b06, admin, project_id="P1",
            batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)
        self.assertEqual([], admin.writes)

    def test_b06_invalid_source_does_not_query_r1(self):
        admin = LegacyAdminFixture()
        row = verified_relation()
        row["source_verified_link"] = None
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: r1_preview_from_legacy_admin(
            lambda *_: verified_scope([row]), admin,
            project_id="P1", batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)

    def test_valid_seam_calls_read_only_projection(self):
        admin = LegacyAdminFixture()
        observed = []
        def b06(project, batch):
            observed.append((project, batch))
            return verified_scope()
        p = r1_preview_from_legacy_admin(
            b06, admin, project_id="P1", batch_id="B1", mission_id="M1")
        self.assertEqual([("P1", "B1")], observed)
        self.assertEqual([("P1", "B1", "M1")],
                         admin.projection.identity_calls)
        self.assertEqual(["M1"], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)
        self.assertEqual([], admin.writes)
        self.assertEqual("PROTOTYPE_UNQUALIFIED", p["data_quality"])
        self.assertEqual("HOLD", p["release_decision"])

    def test_scoped_projection_rejects_cross_project_before_related_reads(self):
        admin = LegacyAdminFixture(legacy_overview(mission={
            "mission_id": "M1", "project_id": "P2", "batch_id": "B1",
        }))
        self.reject("R1_MISSION_SCOPE_UNRESOLVED", lambda:
            r1_preview_from_legacy_admin(
                lambda *_: verified_scope(), admin,
                project_id="P1", batch_id="B1", mission_id="M1"))
        self.assertEqual([("P1", "B1", "M1")],
                         admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)

    def test_scoped_projection_rejects_cross_batch_before_related_reads(self):
        admin = LegacyAdminFixture(legacy_overview(mission={
            "mission_id": "M1", "project_id": "P1", "batch_id": "B2",
        }))
        self.reject("R1_MISSION_SCOPE_UNRESOLVED", lambda:
            r1_preview_from_legacy_admin(
                lambda *_: verified_scope(), admin,
                project_id="P1", batch_id="B1", mission_id="M1"))
        self.assertEqual([("P1", "B1", "M1")],
                         admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)

    def test_unscoped_legacy_projection_is_not_used_as_fallback(self):
        class UnsafeProjection:
            def __init__(self):
                self.calls = []

            def mission_overview(self, mission_id):
                self.calls.append(mission_id)
                raise AssertionError("unsafe unscoped read")

        admin = type("Legacy", (), {})()
        admin.projection = UnsafeProjection()
        self.reject("R1_SCOPED_READ_UNAVAILABLE", lambda:
            r1_preview_from_legacy_admin(
                lambda *_: verified_scope(), admin,
                project_id="P1", batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.calls)

    def test_seam_does_not_accept_a_client_supplied_principal(self):
        admin = LegacyAdminFixture()
        observed = []
        def b06(project, batch):
            observed.append((project, batch))
            return verified_scope()
        with self.assertRaises(TypeError):
            r1_preview_from_legacy_admin(
                b06, admin, trusted_principal_id="attacker-admin",
                project_id="P1", batch_id="B1", mission_id="M1")
        self.assertEqual([], observed)
        self.assertEqual([], admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)

    def test_host_bound_b06_authorization_failure_precedes_r1(self):
        admin = LegacyAdminFixture()
        def host_bound_b06(project, batch):
            raise ContractRejection("UNAUTHENTICATED")
        self.reject("UNAUTHENTICATED", lambda: r1_preview_from_legacy_admin(
            host_bound_b06, admin, project_id="P1", batch_id="B1",
            mission_id="M1"))
        self.assertEqual([], admin.projection.identity_calls)
        self.assertEqual([], admin.projection.related_calls)
        self.assertEqual([], admin.projection.unscoped_calls)


    def test_empty_b06_relations_are_not_an_empty_success(self):
        self.reject("ILLEGAL_ASSOCIATION", lambda: normalize_b06_scope(
            verified_scope([]), project_id="P1", batch_id="B1"))

    def test_b06_source_refs_are_required_and_must_cover_relation_links(self):
        missing = verified_scope()
        missing.pop("source_refs")
        self.reject("SOURCE_REFS_REQUIRED", lambda: normalize_b06_scope(
            missing, project_id="P1", batch_id="B1"))
        incomplete = verified_scope()
        incomplete["source_refs"].remove("starlink:sst:R1:V1:SST-100")
        self.reject("SOURCE_REFERENCE_NOT_IN_SCOPE", lambda: normalize_b06_scope(
            incomplete, project_id="P1", batch_id="B1"))

    def test_duplicate_b06_source_refs_are_rejected(self):
        duplicate = verified_scope()
        duplicate["source_refs"].append(duplicate["source_refs"][0])
        self.reject("SOURCE_REFS_DUPLICATE", lambda: normalize_b06_scope(
            duplicate, project_id="P1", batch_id="B1"))

    def test_missing_pagination_metadata_never_claims_scope_complete(self):
        missing = verified_scope()
        missing.pop("next_page_cursor")
        out = normalize_b06_scope(missing, project_id="P1", batch_id="B1")
        self.assertFalse(out["pagination_complete"])

    def test_partial_b06_page_preserves_cursor_and_remains_hold(self):
        partial = verified_scope()
        partial["next_page_cursor"] = "cursor:page-2"
        preview = r1_preview(partial, legacy_overview(),
                             project_id="P1", batch_id="B1", mission_id="M1")
        self.assertEqual("cursor:page-2", preview["next_page_cursor"])
        self.assertFalse(preview["scope_complete"])
        self.assertIn("B06_SCOPE_PAGINATION_INCOMPLETE",
                      preview["gap_indicators"])
        self.assertEqual("HOLD", preview["release_decision"])

    def test_preview_preserves_b06_and_r1_source_refs(self):
        preview = r1_preview(verified_scope(), legacy_overview(),
                             project_id="P1", batch_id="B1", mission_id="M1")
        self.assertIn("starlink:reqver:R1:V1", preview["source_refs"])
        self.assertIn("starlink:sst:R1:V1:SST-100", preview["source_refs"])
        self.assertIn("rc7_admin:mission_overview_scoped:M1", preview["source_refs"])

    def test_real_rc7_admin_r1_mission_source_is_not_b06_batch_identity(self):
        """Real old R1 code fixture: release_id cannot be guessed to be batch."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rc7_admin.server import AdminApplication
        from rc7_runtime.models import Mission
        from rc7_runtime.truth_overlay import append_entity

        with TemporaryDirectory() as td:
            path = Path(td) / "fixture-r1.jsonl"
            app = AdminApplication(str(path))
            append_entity(app.truth, Mission(
                mission_id="M1", release_id="B1", goal="fixture only"),
                release_id="B1")
            before = path.read_bytes()
            query_calls = []
            original_query = app.truth.query
            def observed_query(artifact_type, **filters):
                query_calls.append((artifact_type, filters))
                return original_query(artifact_type, **filters)
            app.truth.query = observed_query
            # B06 is a fixture too; test does NOT grant production authorization.
            self.reject("R1_MISSION_SCOPE_UNRESOLVED",
                        lambda: r1_preview_from_legacy_admin(
                            lambda *_: verified_scope(), app,
                            project_id="P1", batch_id="B1", mission_id="M1"))
            self.assertEqual([("rc7_mission", {"mission_id": "M1"})],
                             query_calls,
                             "only the minimal Mission identity query may run")
            self.assertEqual(before, path.read_bytes(),
                             "Read-only preview must not append any R1 event")

    def test_real_admin_projection_checks_project_scope_before_related_queries(self):
        from rc7_admin.projection import AdminProjection, AdminProjectionError

        class RecordingTruth:
            def __init__(self, mission):
                self.mission = mission
                self.queries = []

            def query(self, artifact_type, **filters):
                self.queries.append((artifact_type, filters))
                if artifact_type == "rc7_mission":
                    if self.mission.get("mission_id") == filters.get("mission_id"):
                        return [copy.deepcopy(self.mission)]
                    return []
                return []

        truth = RecordingTruth({
            "mission_id": "M1", "project_id": "P2", "batch_id": "B1",
        })
        projection = AdminProjection(truth)
        with self.assertRaises(AdminProjectionError) as raised:
            projection.mission_overview_scoped(
                mission_id="M1", project_id="P1", batch_id="B1")
        self.assertEqual("R1_MISSION_SCOPE_UNRESOLVED", str(raised.exception))
        self.assertEqual([("rc7_mission", {"mission_id": "M1"})],
                         truth.queries)

    def test_real_admin_projection_checks_batch_scope_before_related_queries(self):
        from rc7_admin.projection import AdminProjection, AdminProjectionError

        class RecordingTruth:
            def __init__(self, mission):
                self.mission = mission
                self.queries = []

            def query(self, artifact_type, **filters):
                self.queries.append((artifact_type, filters))
                if artifact_type == "rc7_mission":
                    return [copy.deepcopy(self.mission)]
                return []

        truth = RecordingTruth({
            "mission_id": "M1", "project_id": "P1", "batch_id": "B2",
        })
        with self.assertRaises(AdminProjectionError) as raised:
            AdminProjection(truth).mission_overview_scoped(
                mission_id="M1", project_id="P1", batch_id="B1")
        self.assertEqual("R1_MISSION_SCOPE_UNRESOLVED", str(raised.exception))
        self.assertEqual([("rc7_mission", {"mission_id": "M1"})],
                         truth.queries)

    def test_real_admin_projection_loads_details_only_after_scope_match(self):
        from rc7_admin.projection import AdminProjection

        class RecordingTruth:
            def __init__(self, mission):
                self.mission = mission
                self.queries = []

            def query(self, artifact_type, **filters):
                self.queries.append((artifact_type, filters))
                if artifact_type == "rc7_mission":
                    return [copy.deepcopy(self.mission)]
                return [{"mission_id": "M1", "id": artifact_type}]

        truth = RecordingTruth({
            "mission_id": "M1", "project_id": "P1", "batch_id": "B1",
            "goal": "not returned by scoped identity lookup",
        })
        result = AdminProjection(truth).mission_overview_scoped(
            mission_id="M1", project_id="P1", batch_id="B1")
        self.assertEqual(
            [("rc7_mission", {"mission_id": "M1"}),
             ("rc7_task", {"mission_id": "M1"}),
             ("execution_attempt", {"mission_id": "M1"}),
             ("rc7_evidence", {"mission_id": "M1"})],
            truth.queries)
        self.assertEqual({
            "mission_id": "M1", "project_id": "P1", "batch_id": "B1",
        }, result["mission"])
        self.assertEqual(["tasks", "executions", "evidence"],
                         list(result["related"]))

    def test_real_rc7_admin_has_no_workbench_control_or_graph_api(self):
        """Pinned old API rejects the proposed routes; not production HTTP QA."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rc7_admin.server import AdminApplication
        from rc7_admin.projection import AdminProjectionError

        with TemporaryDirectory() as td:
            app = AdminApplication(str(Path(td) / "fixture-r1.jsonl"))
            with self.assertRaises(AdminProjectionError) as missing_get:
                app.dispatch_get("/api/workbench/v1/missions/M1/graph", {})
            self.assertEqual("UNKNOWN_RESOURCE", str(missing_get.exception))
            with self.assertRaises(AdminProjectionError) as missing_post:
                app.dispatch_post("/api/workbench/v1/missions/M1/commands", {})
            self.assertEqual("UNKNOWN_COMMAND", str(missing_post.exception))


if __name__ == "__main__":
    unittest.main()
