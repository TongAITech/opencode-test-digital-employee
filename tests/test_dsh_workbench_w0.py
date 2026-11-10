"""Independent W0-only negative-first design-contract tests; no fake live API."""
from __future__ import annotations
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from w0_contract_gate import (
    ContractViolation, accept_event, legal_scope_rows, validate_command, verify_bank_staging
)


def fixture_rows():
    return [
        dict(project_id="P1", batch_id="B1", release_date="2026-11-12",
             requirement_id=r, system_version_id=v, sst_id=s)
        for r, v, s in [
            ("R1", "SYS-A:1.2", "S1"), ("R1", "SYS-A:1.2", "S2"),
            ("R1", "SYS-B:1.2", "S3"), ("R2", "SYS-A:1.2", "S4"),
            ("R3", "SYS-C:2.0", None),
        ]
    ] + [
        dict(project_id="P1", batch_id="B2", release_date="2026-12-01",
             requirement_id="R1", system_version_id="SYS-A:1.2", sst_id="S1"),
        dict(project_id="P2", batch_id="B3", release_date="2026-11-12",
             requirement_id="R1", system_version_id="SYS-A:1.2", sst_id="S1"),
    ]


def scope(**overrides):
    row = dict(project_id="P1", batch_id="B1", release_date="2026-11-12",
               requirement_ids=[], system_version_ids=[], sst_ids=[])
    row.update(overrides)
    return row


class TestScope(unittest.TestCase):
    def assert_code(self, code, action):
        with self.assertRaises(ContractViolation) as captured:
            action()
        self.assertEqual(captured.exception.code, code)

    def test_t1_same_requirement_multiple_versions_multiple_ssts(self):
        x = legal_scope_rows(scope(requirement_ids=["R1"]), fixture_rows(), {"P1"})
        self.assertEqual({r["sst_id"] for r in x}, {"S1", "S2", "S3"})

    def test_t2_shared_version_different_sst(self):
        x = legal_scope_rows(scope(requirement_ids=["R2"], system_version_ids=["SYS-A:1.2"]),
                             fixture_rows(), {"P1"})
        self.assertEqual([r["sst_id"] for r in x], ["S4"])

    def test_t3_same_label_other_system_independent(self):
        x = legal_scope_rows(scope(requirement_ids=["R1"], system_version_ids=["SYS-B:1.2"]),
                             fixture_rows(), {"P1"})
        self.assertEqual([r["sst_id"] for r in x], ["S3"])

    def test_t4_same_names_other_date_not_leaking(self):
        x = legal_scope_rows(scope(requirement_ids=["R1"], sst_ids=["S1"]),
                             fixture_rows(), {"P1"})
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0]["batch_id"], "B1")

    def test_t5_unsplit_sst_still_visible(self):
        x = legal_scope_rows(scope(requirement_ids=["R3"]), fixture_rows(), {"P1"})
        self.assertIsNone(x[0]["sst_id"])

    def test_t6_reject_orphan_and_cross_batch_join(self):
        self.assert_code("ILLEGAL_ASSOCIATION", lambda: legal_scope_rows(
            scope(requirement_ids=["R2"], sst_ids=["S1"]), fixture_rows(), {"P1"}))
        self.assert_code("ILLEGAL_ASSOCIATION", lambda: legal_scope_rows(
            scope(requirement_ids=["R3"], sst_ids=["S3"]), fixture_rows(), {"P1"}))

    def test_t7_no_cartesian_expansion(self):
        x = legal_scope_rows(scope(requirement_ids=["R1", "R2"],
                                   system_version_ids=["SYS-A:1.2", "SYS-B:1.2"]),
                             fixture_rows(), {"P1"})
        self.assertEqual(len(x), 4)
        self.assertNotIn(("R2", "SYS-B:1.2"),
                         {(r["requirement_id"], r["system_version_id"]) for r in x})

    def test_t8_date_revision_preserves_stable_batch_id(self):
        revised = fixture_rows()
        for row in revised:
            if row["batch_id"] == "B1":
                row["release_date"] = "2026-11-13"
        x = legal_scope_rows(scope(release_date="2026-11-13"), revised, {"P1"})
        self.assertEqual({r["batch_id"] for r in x}, {"B1"})
        self.assert_code("INVALID_SCOPE", lambda: legal_scope_rows(scope(), revised, {"P1"}))

    def test_t9_stale_restored_selection_rejected(self):
        self.assert_code("ILLEGAL_ASSOCIATION", lambda: legal_scope_rows(
            scope(sst_ids=["S999"]), fixture_rows(), {"P1"}))

    def test_t10_project_acl(self):
        self.assert_code("FORBIDDEN", lambda: legal_scope_rows(
            scope(project_id="P2", batch_id="B3"), fixture_rows(), {"P1"}))
        self.assert_code("FORBIDDEN", lambda: legal_scope_rows(
            scope(project_id="P1", batch_id="B3"), fixture_rows(), {"P1"}))

    def test_validation_and_missing_truth(self):
        self.assert_code("RESOURCE_NOT_FOUND", lambda: legal_scope_rows(
            scope(batch_id="missing"), fixture_rows(), {"P1"}))
        self.assert_code("INVALID_SCOPE", lambda: legal_scope_rows(
            scope(release_date="2026-02-30"), fixture_rows(), {"P1"}))


class TestCommand(unittest.TestCase):
    def setUp(self):
        self.body = dict(command_id="C1", idempotency_key="I1",
                         expected_state_revision=4, scope_ref="B1:R1:SYS-A:1.2:S1",
                         action="retry_failed", reason="verified defect")
    def check(self, body=None, principal="user1", authorized=True, rev=4):
        return validate_command(body or self.body, authenticated_principal=principal,
                                authorized=authorized, current_revision=rev,
                                authorized_scope_ref=self.body["scope_ref"])

    def test_authorized_valid_envelope(self):
        self.assertEqual(self.check()["command_id"], "C1")

    def test_body_cannot_spoof_identity(self):
        with self.assertRaisesRegex(ContractViolation, "UNTRUSTED_PRINCIPAL"):
            self.check(dict(self.body, principal="admin"))

    def test_no_permission_no_mutation(self):
        with self.assertRaisesRegex(ContractViolation, "FORBIDDEN"):
            self.check(authorized=False)

    def test_foreign_scope_rejected_before_command_acceptance(self):
        with self.assertRaisesRegex(ContractViolation, "FORBIDDEN"):
            self.check(dict(self.body, scope_ref="B2:R1:SYS-A:1.2:S1"))

    def test_state_revision_conflict(self):
        with self.assertRaisesRegex(ContractViolation, "STATE_REVISION_CONFLICT"):
            self.check(rev=5)

    def test_publish_or_direct_gate_override_forbidden(self):
        with self.assertRaisesRegex(ContractViolation, "GATE_BLOCKED"):
            self.check(dict(self.body, action="publish"))

    def test_required_idempotency_and_reason(self):
        with self.assertRaisesRegex(ContractViolation, "VALIDATION_ERROR"):
            self.check(dict(self.body, idempotency_key=""))


class TestEvent(unittest.TestCase):
    def event(self, event_id="E1", revision=1, project_id="P1", batch_id="B1"):
        return dict(event_id=event_id, revision=revision, project_id=project_id,
                    batch_id=batch_id, timestamp="2026-11-09T08:00:00+08:00",
                    type="attempt.created", source_ref="R1:attempt/1", truth_revision=7)

    def test_sequential_and_deduplicate(self):
        state = {}
        self.assertTrue(accept_event(state, self.event(), authenticated_project_id="P1", authenticated_batch_id="B1"))
        self.assertFalse(accept_event(state, self.event(), authenticated_project_id="P1", authenticated_batch_id="B1"))
        self.assertTrue(accept_event(state, self.event("E2", 2), authenticated_project_id="P1", authenticated_batch_id="B1"))

    def test_snapshot_resume_contiguous(self):
        state = {"revision": 9}
        self.assertTrue(accept_event(state, self.event("E10", 10), authenticated_project_id="P1", authenticated_batch_id="B1"))
        self.assertEqual(state["revision"], 10)

    def test_gap_requires_recovery(self):
        with self.assertRaisesRegex(ContractViolation, "EVENT_REVISION_GAP"):
            accept_event({}, self.event("E3", 3), authenticated_project_id="P1", authenticated_batch_id="B1")

    def test_cross_project_event_forbidden(self):
        with self.assertRaisesRegex(ContractViolation, "FORBIDDEN"):
            accept_event({}, self.event(project_id="P2"), authenticated_project_id="P1", authenticated_batch_id="B1")

    def test_cross_batch_event_forbidden_even_with_same_project(self):
        state = {}
        with self.assertRaisesRegex(ContractViolation, "FORBIDDEN"):
            accept_event(state, self.event(batch_id="B2"),
                         authenticated_project_id="P1", authenticated_batch_id="B1")
        self.assertNotIn("revision", state)

    def test_cannot_reuse_cursor_from_another_batch(self):
        state = {}
        accept_event(state, self.event(),
                     authenticated_project_id="P1", authenticated_batch_id="B1")
        with self.assertRaisesRegex(ContractViolation, "EVENT_SCOPE_MISMATCH"):
            accept_event(state, self.event("E2", 2, batch_id="B2"),
                         authenticated_project_id="P1", authenticated_batch_id="B2")
        self.assertEqual(state["revision"], 1)

    def test_truth_revision_and_source_ref_are_required(self):
        state = {}
        for payload in (dict(self.event(), truth_revision=True),
                        dict(self.event(), source_ref="")):
            with self.assertRaisesRegex(ContractViolation, "VALIDATION_ERROR"):
                accept_event(state, payload,
                             authenticated_project_id="P1", authenticated_batch_id="B1")

    def test_event_id_conflict(self):
        state = {}
        accept_event(state, self.event(), authenticated_project_id="P1", authenticated_batch_id="B1")
        with self.assertRaisesRegex(ContractViolation, "EVENT_CONFLICT"):
            accept_event(state, dict(self.event(), type="evidence.verified"),
                         authenticated_project_id="P1", authenticated_batch_id="B1")


class TestLicenseGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
    def stage(self, name="runtime/worker.py", content=b"first party"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return dict(path=name, sha256=hashlib.sha256(content).hexdigest(),
                    origin_kind="first_party_independent",
                    source_repository="TongAITech/opencode-test-digital-employee",
                    provenance_review_ref="PR84/A-W0")
    def check(self, files):
        return verify_bank_staging(self.root, {"use_case": "bank_commercial", "files": files})

    def test_first_party_inventory_pass_not_legal_approval(self):
        self.assertEqual(self.check([self.stage()]), 1)

    def test_restricted_upstream_renamed_still_blocked(self):
        x = self.stage("renamed/new-ui.js")
        x["source_repository"] = "https://github.com/naodeng/dsh-qa"
        x["license"] = "PolyForm-Noncommercial-1.0.0"
        with self.assertRaisesRegex(ContractViolation, "BLOCKED_LICENSE"):
            self.check([x])

    def test_restricted_marker_blocked_without_rebranding(self):
        x = self.stage(content=b"// PolyForm Noncommercial License 1.0.0")
        with self.assertRaisesRegex(ContractViolation, "BLOCKED_LICENSE"):
            self.check([x])

    def test_missing_manifest_or_unknown_file_fails_closed(self):
        self.stage()
        with self.assertRaisesRegex(ContractViolation, "EMPTY_MANIFEST"):
            self.check([])
        with self.assertRaisesRegex(ContractViolation, "UNMANIFESTED_FILE"):
            self.check([self.stage(), dict(self.stage(), path="ghost.py")])

    def test_hash_mismatch(self):
        x = self.stage()
        x["sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractViolation, "FILE_HASH_MISMATCH"):
            self.check([x])

    def test_third_party_requires_notice_and_inventory(self):
        x = self.stage("vendor/mit.js", b"MIT code")
        x.update(origin_kind="third_party", source_repository="ZSeven-W/dsh-qa", license="MIT")
        with self.assertRaisesRegex(ContractViolation, "THIRD_PARTY_NOTICES_MISSING"):
            self.check([x])
        x["license_file"] = "vendor/LICENSE"
        notice = self.stage("vendor/LICENSE", b"MIT license")
        self.assertEqual(self.check([x, notice]), 2)

    def test_claiming_first_party_without_provenance_fails(self):
        x = self.stage()
        x["provenance_review_ref"] = ""
        with self.assertRaisesRegex(ContractViolation, "PROVENANCE_NOT_REVIEWED"):
            self.check([x])

    def test_unlisted_file_fails(self):
        x = self.stage()
        self.stage("extra.js")
        with self.assertRaisesRegex(ContractViolation, "UNMANIFESTED_FILE"):
            self.check([x])

    def test_hidden_normalized_paths_blocked(self):
        entry = self.stage()
        for path in ("runtime//worker.py", "runtime/./worker.py",
                     "runtime/../worker.py", "runtime/worker.py.", "C:/worker.py"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ContractViolation, "UNSAFE_PATH"):
                    self.check([dict(entry, path=path)])

    def test_symlink_in_staging_blocks(self):
        entry = self.stage()
        link = self.root / "vendor-link"
        try:
            link.symlink_to(self.root / "runtime", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not available on this environment")
        with self.assertRaisesRegex(ContractViolation, "UNSAFE_PATH"):
            self.check([entry])

    def test_traversal_blocked(self):
        x = self.stage()
        x["path"] = "../worker.py"
        with self.assertRaisesRegex(ContractViolation, "UNSAFE_PATH"):
            self.check([x])


class TestPageContract(unittest.TestCase):
    def test_six_pages_and_ten_sections_present_in_contract(self):
        m = (ROOT / "docs/dsh-workbench/01-PAGE-FUNCTION-MATRIX.md").read_text(encoding="utf-8")
        for item in ("P01", "P02", "P03", "P04", "P05", "P06",
                     "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10"):
            self.assertIn(item, m)
        self.assertIn("fc5a054a48973d004580a3cc1de60da3f701150b", m)

    def test_a01_a02_a03_acceptance_artifacts_not_a_fake_qa_pass(self):
        docs = ROOT / "docs" / "dsh-workbench"
        atoms = (docs / "WB-A01-ATOMIC-FEATURE-REGISTER.md").read_text(encoding="utf-8")
        for item in ("original_source_ref", "feature_id", "P01-01", "P02-01", "P03-01", "P04-01",
                     "P05-01", "P06-01", "D01-01", "D02-01", "D03-01",
                     "D04-01", "D05-01", "D06-01", "D07-01", "D08-01",
                     "D09-01", "D10-01", "X01-01", "X02-01", "X03-01", "NOT_RUN"):
            self.assertIn(item, atoms)
        self.assertIn("fc5a054a48973d004580a3cc1de60da3f701150b", atoms)
        self.assertIn("public/app.js#L", atoms)
        self.assertIn("public/index.html#L", atoms)
        self.assertIn("N/A（新增能力，无上游入口）", atoms)
        self.assertIn("BLOCKED_LICENSE", (docs / "WB-A02-LICENSE-BOUNDARY.md").read_text(encoding="utf-8"))
        signoff = (docs / "WB-A03-CROSS-GROUP-SIGNOFF.md").read_text(encoding="utf-8")
        # A03 now records the *actual* B/D/E signed design scope, not the
        # original placeholder B_PENDING. These are not W1 product QA.
        for item in ("B_DESIGN_SIGNOFF_RECONFIRMED", "F_RECHECK_REQUIRED",
                     "D_SIGNOFF_ISSUED", "E_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS",
                     "F_RECHECK_REQUIRED", "W1_IMPLEMENTATION_QA_NOT_RUN",
                     "FG18_DESIGN_RECHECK_PASS", "W0_NOT_FROZEN"):
            self.assertIn(item, signoff)
        self.assertNotIn("W0_DESIGN_FROZEN=YES", signoff)
        self.assertIn("F_INITIAL_REVIEWED_WITH_BLOCKERS", (docs / "08-CONSTRUCTION-PLAN.md").read_text(encoding="utf-8"))
        self.assertIn("W0_NOT_FROZEN", (docs / "09-GAP-MATRIX.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
