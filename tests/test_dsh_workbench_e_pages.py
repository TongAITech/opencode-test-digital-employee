"""E pre-B06 paginated consumer: fixture protocol tests, NOT production QA."""
import copy
import unittest

from tools.dsh_workbench.e_contract_oracle import ContractRejection
from tools.dsh_workbench.e_b06_page_consumer import (
    collect_authorized_b06_pages, r1_preview_after_full_b06_scope,
)


def link(req="R1", ver="V1", sst="S1"):
    return {
        "project_id": "P1", "batch_id": "B1",
        "requirement_id": req, "system_version_id": ver, "sst_id": sst,
        "split_state": "SPLIT" if sst else "UNSPLIT",
        "source_verified_requirement_version": {
            "source_link_ref": "source:rv:%s:%s" % (req, ver),
            "source_revision": "rv-v3",
        },
        "source_verified_link": {
            "source_link_ref": "source:brvs:%s:%s:%s" % (req, ver, sst),
            "verified_source_revision": "brvs-v5",
        } if sst else None,
    }


def page(rows, next_cursor=None, revision=5, access=7,
         release_date="2026-11-12"):
    refs = []
    for row in rows:
        for obj in (row.get("source_verified_requirement_version"),
                    row.get("source_verified_link")):
            if obj and obj.get("source_link_ref") not in refs:
                refs.append(obj["source_link_ref"])
    return {
        "project_id": "P1", "batch_id": "B1",
        "release_date": release_date, "relation_revision": revision,
        "access_scope_revision": access,
        "source_refs": refs,
        "warnings": [], "gap_indicators": [],
        "records": copy.deepcopy(rows),
        "next_page_cursor": next_cursor,
    }


class FixtureB06Port:
    """Simulates the response shape, not authorization or cursor signing."""
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, project_id, batch_id, page_size, page_cursor):
        self.calls.append((project_id, batch_id, page_size, page_cursor))
        idx = len(self.calls) - 1
        if idx >= len(self.pages):
            raise AssertionError("unexpected B06 call")
        source = self.pages[idx]
        if isinstance(source, Exception):
            raise source
        return copy.deepcopy(source)


class FixtureLegacyAdmin:
    class Projection:
        def __init__(self, overview):
            self.overview = overview
            self.identity_calls = []
            self.related_calls = []
            self.unscoped_calls = []

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

    def __init__(self, mission=None):
        self.projection = self.Projection({
            "mission": mission if mission is not None else {
                "mission_id": "M1", "project_id": "P1", "batch_id": "B1",
            },
            "related": {"tasks": [], "executions": [], "evidence": []},
        })
        self.writes = []

    def dispatch_post(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("R1 write prohibited")


class EPageConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.r1 = FixtureLegacyAdmin()

    def fixture(self, pages=None):
        return FixtureB06Port(pages if pages is not None else [
            page([link(sst="S1")], "opaque-next"),
            page([link(ver="V2", sst="S2"),
                  link(req="R2", ver="V1", sst=None)]),
        ])

    def run_read(self, port, **kw):
        return r1_preview_after_full_b06_scope(
            port, self.r1, project_id="P1", batch_id="B1", mission_id="M1",
            page_size=2, **kw)

    def rejected(self, code, callback, no_r1=True):
        with self.assertRaises(ContractRejection) as ctx:
            callback()
        self.assertEqual(code, ctx.exception.code)
        if no_r1:
            self.assertEqual([], self.r1.projection.related_calls)
            self.assertEqual([], self.r1.projection.unscoped_calls)
        self.assertEqual([], self.r1.writes)

    def test_two_pages_are_combined_before_any_r1_read(self):
        port = self.fixture()
        result = self.run_read(port)
        self.assertEqual([("P1", "B1", 2, None),
                          ("P1", "B1", 2, "opaque-next")], port.calls)
        self.assertEqual([("P1", "B1", "M1")],
                         self.r1.projection.identity_calls)
        self.assertEqual(["M1"], self.r1.projection.related_calls)
        self.assertEqual([], self.r1.projection.unscoped_calls)
        self.assertEqual(3, len(result["records"]))
        self.assertTrue(result["scope_complete"])
        self.assertEqual("HOLD", result["release_decision"])
        self.assertEqual("UNKNOWN_NOT_READ_FROM_CANONICAL_NODEGATE",
                         result["nodegate"]["decision"])
        self.assertIn("source:brvs:R1:V1:S1", result["source_refs"])
        self.assertIn("rc7_admin:mission_overview_scoped:M1", result["source_refs"])

    def test_single_terminal_page_consumed_once(self):
        port = self.fixture([page([link()])])
        out = self.run_read(port)
        self.assertEqual(1, len(out["records"]))
        self.assertEqual([("P1", "B1", 2, None)], port.calls)

    def test_next_cursor_required_even_for_terminal_page(self):
        bad = page([link()])
        del bad["next_page_cursor"]
        self.rejected("B06_PAGINATION_UNAVAILABLE",
                      lambda: self.run_read(self.fixture([bad])))

    def test_cursor_cycle_never_reads_r1(self):
        port = self.fixture([
            page([link()], "again"),
            page([link(ver="V2")], "again"),
        ])
        self.rejected("B06_CURSOR_CYCLE", lambda: self.run_read(port))
        self.assertEqual(2, len(port.calls))

    def test_cross_batch_second_page_rejected(self):
        bad = page([link(ver="V2")])
        bad["batch_id"] = "B2"
        self.rejected("ILLEGAL_ASSOCIATION",
                      lambda: self.run_read(self.fixture([
                          page([link()], "second"), bad])))

    def test_cross_project_second_page_rejected(self):
        bad = page([link(ver="V2")])
        bad["project_id"] = "P2"
        self.rejected("FORBIDDEN", lambda: self.run_read(self.fixture([
            page([link()], "second"), bad])))

    def test_relation_revision_changed_between_pages(self):
        self.rejected("B06_RELATION_REVISION_CHANGED",
                      lambda: self.run_read(self.fixture([
                          page([link()], "next"),
                          page([link(ver="V2")], revision=6)])))

    def test_access_scope_revision_changed_between_pages(self):
        self.rejected("B06_ACCESS_REVISION_CHANGED",
                      lambda: self.run_read(self.fixture([
                          page([link()], "next"),
                          page([link(ver="V2")], access=8)])))

    def test_release_business_day_changed_between_pages(self):
        self.rejected("B06_BUSINESS_DATE_CHANGED",
                      lambda: self.run_read(self.fixture([
                          page([link()], "next"),
                          page([link(ver="V2")],
                               release_date="2026-11-19")])))

    def test_same_relation_in_second_page_cannot_double_count(self):
        self.rejected("B06_DUPLICATE_RELATION_ACROSS_PAGES",
                      lambda: self.run_read(self.fixture([
                          page([link()], "next"), page([link()])])))

    def test_unsplit_then_split_same_parent_rejected(self):
        self.rejected("B06_SPLIT_STATE_CONFLICT",
                      lambda: self.run_read(self.fixture([
                          page([link(sst=None)], "next"),
                          page([link(sst="S1")])])))

    def test_same_raw_sst_id_in_different_versions_are_distinct(self):
        result = self.run_read(self.fixture([
            page([link(ver="V1", sst="SST-100")], "next"),
            page([link(ver="V2", sst="SST-100")])]))
        self.assertEqual(2, len(result["records"]))
        self.assertEqual(["V1", "V2"],
                         [r["system_version_id"] for r in result["records"]])

    def test_same_requirement_version_split_across_pages_stable_source(self):
        """Multiple SSTs may share exactly one verified BRV source revision."""
        port = self.fixture([
            page([link(sst="S1")], "next"),
            page([link(sst="S2")]),
        ])
        result = self.run_read(port)
        self.assertEqual([("P1", "B1", "M1")],
                         self.r1.projection.identity_calls)
        self.assertEqual(["M1"], self.r1.projection.related_calls)
        self.assertEqual(["S1", "S2"],
                         [r["sst_id"] for r in result["records"]])
        self.assertEqual("HOLD", result["release_decision"])

    def test_cross_page_same_parent_source_revision_drift_is_rejected(self):
        """A joined BRV may not silently change source rev while paging SST."""
        second = page([link(sst="S2")])
        second["records"][0]["source_verified_requirement_version"][
            "source_revision"] = "rv-v4"
        self.rejected("B06_REQUIREMENT_VERSION_SOURCE_DRIFT",
                      lambda: self.run_read(self.fixture([
                          page([link(sst="S1")], "next"), second])))

    def test_cross_page_same_parent_source_ref_drift_is_rejected(self):
        """A different verified link_ref with same revision is also drift."""
        second = page([link(sst="S2")])
        second["records"][0]["source_verified_requirement_version"][
            "source_link_ref"] = "source:rv:OTHER"
        # Keep B06's own page provenance consistent so this test reaches
        # the stricter *cross-page* BRV source identity check.
        second["source_refs"] = [
            "source:rv:OTHER" if ref == "source:rv:R1:V1" else ref
            for ref in second["source_refs"]
        ]
        self.rejected("B06_REQUIREMENT_VERSION_SOURCE_DRIFT",
                      lambda: self.run_read(self.fixture([
                          page([link(sst="S1")], "next"), second])))

    def test_within_page_same_parent_source_revision_drift_is_rejected(self):
        second = link(sst="S2")
        second["source_verified_requirement_version"][
            "source_revision"] = "rv-v4"
        self.rejected("B06_REQUIREMENT_VERSION_SOURCE_DRIFT",
                      lambda: self.run_read(self.fixture([
                          page([link(sst="S1"), second])])))

    def test_different_system_versions_independent_verified_source_revisions(self):
        second = link(ver="V2", sst="SST-100")
        second["source_verified_requirement_version"][
            "source_revision"] = "rv-v4"
        result = self.run_read(self.fixture([
            page([link(ver="V1", sst="SST-100")], "next"),
            page([second])]))
        self.assertEqual(2, len(result["records"]))
        self.assertEqual(["V1", "V2"],
                         [r["system_version_id"] for r in result["records"]])

    def test_second_page_missing_verified_link_rejected(self):
        bad = page([link(ver="V2")])
        bad["records"][0]["source_verified_link"] = None
        self.rejected("SOURCE_VERIFIED_LINK_REQUIRED",
                      lambda: self.run_read(self.fixture([
                          page([link()], "next"), bad])))

    def test_second_page_forbidden_prevents_r1_access(self):
        port = self.fixture([
            page([link()], "next"), ContractRejection("FORBIDDEN"),
        ])
        self.rejected("FORBIDDEN", lambda: self.run_read(port))

    def test_bounded_page_count_fails_closed(self):
        port = self.fixture([page([link()], "next")])
        self.rejected("B06_PAGE_LIMIT_REACHED",
                      lambda: self.run_read(port, max_pages=1))
        self.assertEqual(1, len(port.calls))

    def test_page_size_violation_rejected(self):
        port = self.fixture([page([link(), link(ver="V2"),
                                    link(ver="V3")])])
        self.rejected("B06_PAGE_SIZE_EXCEEDED",
                      lambda: self.run_read(port))

    def test_invalid_page_size_and_limit_block_fetch(self):
        port = self.fixture()
        # Only explicit out-of-range inputs; no B06 calls are permitted.
        from tools.dsh_workbench.e_b06_page_consumer import collect_authorized_b06_pages
        self.rejected("INVALID_PAGE_SIZE",
                      lambda: collect_authorized_b06_pages(
                          port, project_id="P1", batch_id="B1", page_size=0))
        self.rejected("INVALID_PAGE_LIMIT",
                      lambda: collect_authorized_b06_pages(
                          port, project_id="P1", batch_id="B1", max_pages=0))
        self.assertEqual([], port.calls)

    def test_old_mission_without_batch_identity_is_not_inferred(self):
        self.r1 = FixtureLegacyAdmin(mission={
            "mission_id": "M1", "release_id": "B1",
        })
        self.rejected("R1_MISSION_SCOPE_UNRESOLVED",
                      lambda: self.run_read(self.fixture()))
        self.assertEqual([("P1", "B1", "M1")],
                         self.r1.projection.identity_calls)
        self.assertEqual([], self.r1.projection.related_calls)

    def test_cross_project_mission_rejected_before_related_r1_reads(self):
        self.r1 = FixtureLegacyAdmin(mission={
            "mission_id": "M1", "project_id": "P2", "batch_id": "B1",
        })
        self.rejected("R1_MISSION_SCOPE_UNRESOLVED",
                      lambda: self.run_read(self.fixture()))
        self.assertEqual([("P1", "B1", "M1")],
                         self.r1.projection.identity_calls)
        self.assertEqual([], self.r1.projection.related_calls)

    def test_cross_batch_mission_rejected_before_related_r1_reads(self):
        self.r1 = FixtureLegacyAdmin(mission={
            "mission_id": "M1", "project_id": "P1", "batch_id": "B2",
        })
        self.rejected("R1_MISSION_SCOPE_UNRESOLVED",
                      lambda: self.run_read(self.fixture()))
        self.assertEqual([("P1", "B1", "M1")],
                         self.r1.projection.identity_calls)
        self.assertEqual([], self.r1.projection.related_calls)

    def test_unsafe_unscoped_projection_is_never_used_as_fallback(self):
        class UnscopedOnly:
            def __init__(self):
                self.calls = []

            def mission_overview(self, mission_id):
                self.calls.append(mission_id)
                raise AssertionError("unsafe method must not be called")

        legacy = type("Legacy", (), {})()
        legacy.projection = UnscopedOnly()
        with self.assertRaises(ContractRejection) as raised:
            r1_preview_after_full_b06_scope(
                self.fixture(), legacy, project_id="P1", batch_id="B1",
                mission_id="M1")
        self.assertEqual("R1_SCOPED_READ_UNAVAILABLE",
                         raised.exception.code)
        self.assertEqual([], legacy.projection.calls)

    def test_no_raw_principal_parameter_accepted(self):
        port = self.fixture()
        with self.assertRaises(TypeError):
            collect_authorized_b06_pages(
                port, project_id="P1", batch_id="B1",
                trusted_principal_id="attacker")
        self.assertEqual([], port.calls)

    def test_actual_rc7_admin_r1_stream_read_only_after_two_pages(self):
        """Actual inherited TruthRuntime/Projection fixture; not bank R1."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rc7_admin.server import AdminApplication
        from rc7_runtime.models import Mission
        from rc7_runtime.truth_overlay import append_entity

        with TemporaryDirectory() as td:
            event_path = Path(td) / "synthetic-r1.jsonl"
            app = AdminApplication(str(event_path))
            append_entity(app.truth, Mission(
                mission_id="M1", release_id="B1", goal="synthetic only"),
                release_id="B1")
            original = event_path.read_bytes()
            query_calls = []
            original_query = app.truth.query
            def observed_query(artifact_type, **filters):
                query_calls.append((artifact_type, filters))
                return original_query(artifact_type, **filters)
            app.truth.query = observed_query
            valid_b06 = self.fixture()
            with self.assertRaises(ContractRejection) as raised:
                r1_preview_after_full_b06_scope(
                    valid_b06, app, project_id="P1", batch_id="B1",
                    mission_id="M1", page_size=2)
            self.assertEqual("R1_MISSION_SCOPE_UNRESOLVED",
                             raised.exception.code)
            self.assertEqual([("rc7_mission", {"mission_id": "M1"})],
                             query_calls,
                             "only the minimal Mission identity query may run")
            self.assertEqual(2, len(valid_b06.calls))
            self.assertEqual(original, event_path.read_bytes())

    def test_actual_rc7_admin_r1_not_read_when_b06_page_two_denied(self):
        """Second-page denial must stop before the actual R1 projection."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rc7_admin.server import AdminApplication
        from rc7_runtime.models import Mission
        from rc7_runtime.truth_overlay import append_entity

        with TemporaryDirectory() as td:
            event_path = Path(td) / "synthetic-r1.jsonl"
            app = AdminApplication(str(event_path))
            append_entity(app.truth, Mission(
                mission_id="M1", release_id="B1", goal="synthetic only"),
                release_id="B1")
            original = event_path.read_bytes()

            def forbidden_read(_):
                raise AssertionError("R1 read before complete B06 ACL proof")

            app.projection.mission_overview_scoped = forbidden_read
            bad_page = page([link(ver="V2")])
            bad_page["project_id"] = "P2"
            port = self.fixture([page([link()], "next"), bad_page])
            with self.assertRaises(ContractRejection) as raised:
                r1_preview_after_full_b06_scope(
                    port, app, project_id="P1", batch_id="B1",
                    mission_id="M1", page_size=2)
            self.assertEqual("FORBIDDEN", raised.exception.code)
            self.assertEqual(2, len(port.calls))
            self.assertEqual(original, event_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
