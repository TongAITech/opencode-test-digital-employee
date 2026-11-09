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
    return {
        "project_id": "P1", "batch_id": "B1",
        "release_date": "2026-11-12",
        "relation_revision": 2, "access_scope_revision": 3,
        "authorized_mission_ids": ["M1"],
        "records": [verified_relation()] if rows is None else rows,
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
        self.calls = []
        self.overview = overview if overview is not None else legacy_overview()

    def mission_overview(self, mission_id):
        self.calls.append(("read", mission_id))
        return copy.deepcopy(self.overview)


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
                                  project_id="P1", batch_id="B1",
                                  mission_id="M1")
        self.assertEqual(2, len(out["records"]))
        refs = [item["source_verified_link_ref"] for item in out["records"]]
        self.assertEqual(2, len(set(refs)))
        self.assertEqual(["V1", "V2"],
                         [item["system_version_id"] for item in out["records"]])

    def test_same_version_shared_by_two_requirements_not_same_sst(self):
        rows = [verified_relation(req="R1", ver="V1", sst="S1"),
                verified_relation(req="R2", ver="V1", sst="S2")]
        out = normalize_b06_scope(verified_scope(rows),
                                  project_id="P1", batch_id="B1",
                                  mission_id="M1")
        self.assertEqual([("R1", "S1"), ("R2", "S2")],
                         [(x["requirement_id"], x["sst_id"])
                          for x in out["records"]])

    def test_missing_source_verified_requirement_version_denied(self):
        row = verified_relation()
        row["source_verified_requirement_version"] = None
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: normalize_b06_scope(
            verified_scope([row]), project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_missing_sst_source_verified_link_denied(self):
        row = verified_relation()
        row["source_verified_link"]["verified_source_revision"] = ""
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: normalize_b06_scope(
            verified_scope([row]), project_id="P1", batch_id="B1",
            mission_id="M1"))

    def test_unsplit_row_valid_but_fake_sst_denied(self):
        row = verified_relation(sst=None)
        result = normalize_b06_scope(verified_scope([row]),
                                     project_id="P1", batch_id="B1",
                                     mission_id="M1")
        self.assertEqual("UNSPLIT", result["records"][0]["split_state"])
        self.assertIsNone(result["records"][0]["sst_id"])
        row["sst_id"] = "fake-SST"
        self.reject("UNSPLIT_MUST_NOT_INVENT_SST",
                    lambda: normalize_b06_scope(verified_scope([row]),
                        project_id="P1", batch_id="B1", mission_id="M1"))

    def test_cross_project_batch_scope_rejected(self):
        self.reject("FORBIDDEN", lambda: normalize_b06_scope(
            verified_scope(), project_id="P2", batch_id="B1",
            mission_id="M1"))
        self.reject("ILLEGAL_ASSOCIATION", lambda: normalize_b06_scope(
            verified_scope(), project_id="P1", batch_id="B2",
            mission_id="M1"))
        bad = verified_scope()
        bad["records"][0]["batch_id"] = "B2"
        self.reject("CROSS_BATCH_ASSOCIATION", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1", mission_id="M1"))

    def test_mission_ownership_missing_does_not_leak(self):
        self.reject("FORBIDDEN", lambda: normalize_b06_scope(
            verified_scope(), project_id="P1", batch_id="B1",
            mission_id="M2"))

    def test_duplicate_join_and_unknown_revision_denied(self):
        row = verified_relation()
        self.reject("DUPLICATE_RELATION", lambda: normalize_b06_scope(
            verified_scope([row, copy.deepcopy(row)]),
            project_id="P1", batch_id="B1", mission_id="M1"))
        bad = verified_scope()
        bad["relation_revision"] = None
        self.reject("SCOPE_REVISION_UNAVAILABLE", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1", mission_id="M1"))

    def test_business_day_invalid_date_fail_closed(self):
        bad = verified_scope()
        bad["release_date"] = "2026-02-30"
        self.reject("INVALID_BUSINESS_DATE", lambda: normalize_b06_scope(
            bad, project_id="P1", batch_id="B1", mission_id="M1"))

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
            deny_b06, admin, trusted_principal_id="alice", project_id="P1",
            batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.calls)
        self.assertEqual([], admin.writes)

    def test_b06_invalid_source_does_not_query_r1(self):
        admin = LegacyAdminFixture()
        row = verified_relation()
        row["source_verified_link"] = None
        self.reject("SOURCE_VERIFIED_LINK_REQUIRED", lambda: r1_preview_from_legacy_admin(
            lambda *_: verified_scope([row]), admin,
            trusted_principal_id="alice", project_id="P1",
            batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.calls)

    def test_valid_seam_calls_read_only_projection(self):
        admin = LegacyAdminFixture()
        observed = []
        def b06(principal, project, batch, mission):
            observed.append((principal, project, batch, mission))
            return verified_scope()
        p = r1_preview_from_legacy_admin(
            b06, admin, trusted_principal_id="alice", project_id="P1",
            batch_id="B1", mission_id="M1")
        self.assertEqual([("alice", "P1", "B1", "M1")], observed)
        self.assertEqual([("read", "M1")], admin.projection.calls)
        self.assertEqual([], admin.writes)
        self.assertEqual("PROTOTYPE_UNQUALIFIED", p["data_quality"])
        self.assertEqual("HOLD", p["release_decision"])

    def test_principal_must_be_server_derived_before_seam(self):
        admin = LegacyAdminFixture()
        self.reject("UNAUTHENTICATED", lambda: r1_preview_from_legacy_admin(
            lambda *_: verified_scope(), admin,
            trusted_principal_id="", project_id="P1",
            batch_id="B1", mission_id="M1"))
        self.assertEqual([], admin.projection.calls)


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
            # B06 is a fixture too; test does NOT grant production authorization.
            self.reject("R1_MISSION_SCOPE_UNRESOLVED",
                        lambda: r1_preview_from_legacy_admin(
                            lambda *_: verified_scope(), app,
                            trusted_principal_id="fixture-principal",
                            project_id="P1", batch_id="B1", mission_id="M1"))
            self.assertEqual(before, path.read_bytes(),
                             "Read-only preview must not append any R1 event")

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
